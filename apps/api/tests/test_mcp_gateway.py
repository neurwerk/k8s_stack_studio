"""Catalog paths select MCP routes, never the fixed internal transport authority."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import httpx2
import pytest

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib import mcp_gateway
from k8s_stack_studio.models.mcp import McpRegistration


@pytest.fixture
def endpoint(tmp_path):
    route = {
        "id": "owned-endpoint",
        "url": "https://gateway.example.test:443/operator/selected-endpoint",
        "entry_mode": "api",
        "caller_auth_modes": ["oidc_bearer", "neurwerk_bearer"],
    }
    destination = {
        "id": "custom-server",
        "kind": "mcp",
        "display_name": "Custom server",
        "endpoint_ids": [route["id"]],
        "profile_ids": [],
        "required_permissions": ["llm:invoke", "mcp:custom-server:invoke"],
        "credential_modes": [],
    }
    entry = {
        "id": "unchanged-binding",
        "provider_id": None,
        "display_name": "Custom server",
        "routes": [route],
        "destinations": [destination],
    }
    catalog = {
        "schema_version": 2,
        "catalog_revision": "catalog-1",
        "policy_revision": "policy-1",
        "profiles": [],
        "self-hosted-api-providers": [],
        "external-api-providers": [],
        "external-subscription-providers": [],
        "mcp-servers": [entry],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog))
    settings = Settings(
        gateway_catalog_file=str(path), mcp_gateway_url="http://gateway.internal.test:8082"
    )
    item = McpRegistration(
        id=destination["id"],
        name=destination["display_name"],
        authentication_model="no-authentication",
        server_id="native-server",
    )
    return settings, item, path, catalog


def mcp_response(request):
    body = json.loads(request.content)
    if "id" not in body:
        return httpx2.Response(202)
    result = (
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "configured-server", "version": "1"},
        }
        if body["method"] == "initialize"
        else {"tools": []}
    )
    return httpx2.Response(
        200,
        json={"jsonrpc": "2.0", "id": body["id"], "result": result},
        headers={"set-cookie": "upstream=private; Path=/"},
    )


@pytest.mark.parametrize(
    "public_url",
    [
        "https://gateway.example.test:443/operator/selected-endpoint",
        "https://another-public.example.test:8443/operator/selected-endpoint",
    ],
)
async def test_custom_catalog_path_drives_internal_sdk_and_exact_caller_scope(
    endpoint, monkeypatch, public_url
):
    settings, item, path, catalog = endpoint
    catalog["mcp-servers"][0]["routes"][0]["url"] = public_url
    path.write_text(json.dumps(catalog))
    assert mcp_gateway.gateway_catalog(settings).mcp_servers[0].routes[0].url == public_url
    sent = []
    clients = []
    real_client = httpx2.AsyncClient

    def upstream(request):
        assert str(request.url) == settings.mcp_gateway_url + "/operator/selected-endpoint"
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer caller-token"
        assert "cookie" not in request.headers
        sent.append(request)
        return mcp_response(request)

    def client_factory(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        client = real_client(
            transport=httpx2.MockTransport(upstream), cookies={"local": "private"}, **kwargs
        )
        clients.append(client)
        return client

    monkeypatch.setattr(mcp_gateway.httpx2, "AsyncClient", client_factory)
    async with mcp_gateway.gateway_client(settings, item, "Bearer caller-token") as client:
        assert (await client.list_tools()).tools == []
        count = len(sent)
        for path in (
            "/bindings/mcp-custom-server/mcp",
            "/mcp/custom-server",
            "/operator/selected-endpoint/extra",
            "/operator/another-server",
        ):
            for method in ("POST", "GET", "DELETE"):
                with pytest.raises(mcp_gateway.McpGatewayError):
                    await clients[0].request(method, settings.mcp_gateway_url + path)
        for method in ("GET", "DELETE"):
            with pytest.raises(mcp_gateway.McpGatewayError):
                await clients[0].request(
                    method, settings.mcp_gateway_url + "/operator/selected-endpoint"
                )
        with pytest.raises(mcp_gateway.McpGatewayError):
            await clients[0].post(public_url)
        assert len(sent) == count
    assert {json.loads(request.content)["method"] for request in sent} >= {
        "initialize",
        "tools/list",
    }


@pytest.mark.parametrize(
    "invalid",
    [
        "missing-file",
        "invalid-document",
        "missing-destination",
        "wrong-kind",
        "unowned-route",
        "proxy-only",
        "no-oidc",
        "ambiguous",
    ],
)
async def test_unavailable_or_out_of_scope_endpoint_never_creates_transport(
    endpoint, monkeypatch, invalid
):
    settings, item, path, catalog = endpoint
    entry = catalog["mcp-servers"][0]
    route, destination = entry["routes"][0], entry["destinations"][0]
    if invalid == "missing-file":
        path.unlink()
    elif invalid == "invalid-document":
        path.write_text("{}")
    else:
        if invalid in {"missing-destination", "wrong-kind"}:
            destination.update(
                {
                    "missing-destination": {"id": "another-server"},
                    "wrong-kind": {"kind": "model"},
                }[invalid]
            )
        elif invalid == "unowned-route":
            extra = deepcopy(route)
            extra["id"] = "other-owned-endpoint"
            extra["entry_mode"] = "forward_proxy"
            entry["routes"].append(extra)
            destination["endpoint_ids"] = [extra["id"]]
        elif invalid in {"proxy-only", "no-oidc"}:
            route.update(
                {
                    "proxy-only": {"entry_mode": "forward_proxy"},
                    "no-oidc": {"caller_auth_modes": ["neurwerk_bearer"]},
                }[invalid]
            )
        elif invalid == "ambiguous":
            extra = deepcopy(route)
            extra.update(id="second-endpoint", url="https://gateway.example.test/second")
            entry["routes"].append(extra)
            destination["endpoint_ids"].append(extra["id"])
        path.write_text(json.dumps(catalog))

    def unexpected_transport(**kwargs):
        pytest.fail("Untrusted or missing endpoint must fail before creating a credentialed client")

    monkeypatch.setattr(mcp_gateway.httpx2, "AsyncClient", unexpected_transport)
    with pytest.raises(mcp_gateway.McpGatewayError) as denied:
        async with mcp_gateway.gateway_client(settings, item, "Bearer caller-token"):
            pytest.fail("Untrusted or missing endpoint must not yield a client")
    assert denied.value.status == 503
    assert str(denied.value) == "MCP gateway endpoint is unavailable."


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "",
        "//another.example.test/mcp",
        "/safe/../another",
        "/safe/./another",
        "/safe/%2e%2E/another",
        "/safe/.%2e/another",
        "/safe/%252e%252e/another",
        "/safe%2fanother",
        "/safe%2Fanother",
        "/safe%5canother",
        "/safe%255canother",
        "/safe\\another",
        "/safe\x00another",
        "/safe\x7fanother",
        "/safe\nanother",
        "/safe%00another",
        "/safe%0danother",
        "/safe%7fanother",
        "/safe?query=value",
        "/safe#fragment",
        "/safe?",
        "/safe#",
        "/safe%3fquery=value",
        "/safe%23fragment",
        "/safe%",
        "/safe%2",
        "/safe%zz",
    ],
)
async def test_unsafe_catalog_path_is_rejected_before_http_normalization(
    endpoint, monkeypatch, unsafe_path
):
    settings, item, path, catalog = endpoint
    catalog["mcp-servers"][0]["routes"][0]["url"] = "https://public.example.test" + unsafe_path
    path.write_text(json.dumps(catalog))

    def unexpected_url(*args, **kwargs):
        pytest.fail(
            "Unsafe catalog path must fail before HTTP URL normalization or client creation"
        )

    monkeypatch.setattr(mcp_gateway.httpx2, "URL", unexpected_url)
    monkeypatch.setattr(mcp_gateway.httpx2, "AsyncClient", unexpected_url)
    with pytest.raises(mcp_gateway.McpGatewayError) as denied:
        async with mcp_gateway.gateway_client(settings, item, "Bearer caller-token"):
            pytest.fail("Unsafe path must not yield a client")
    assert denied.value.status == 503


async def test_concurrent_callers_keep_credentials_and_cookies_isolated(endpoint, monkeypatch):
    settings, item, _, _ = endpoint
    real_client = httpx2.AsyncClient
    clients = []
    seen = {}

    def client_factory(**kwargs):
        authorization = kwargs["headers"]["Authorization"]
        seen[authorization] = []

        async def upstream(request):
            await asyncio.sleep(0)
            assert request.headers["authorization"] == authorization
            assert "cookie" not in request.headers
            assert str(request.url) == settings.mcp_gateway_url + "/operator/selected-endpoint"
            seen[authorization].append(json.loads(request.content)["method"])
            return mcp_response(request)

        client = real_client(
            transport=httpx2.MockTransport(upstream), cookies={"caller": authorization}, **kwargs
        )
        clients.append(client)
        return client

    async def discover(authorization):
        async with mcp_gateway.gateway_client(settings, item, authorization) as client:
            assert (await client.list_tools()).tools == []

    monkeypatch.setattr(mcp_gateway.httpx2, "AsyncClient", client_factory)
    await asyncio.gather(discover("Bearer caller-one"), discover("Bearer caller-two"))
    assert len(clients) == 2 and clients[0] is not clients[1]
    assert all(client.is_closed for client in clients)
    assert set(seen) == {"Bearer caller-one", "Bearer caller-two"}
    assert all("initialize" in methods and "tools/list" in methods for methods in seen.values())
