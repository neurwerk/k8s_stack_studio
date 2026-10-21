"""MCP caller credentials may reach only one chart-published, same-origin endpoint."""

from __future__ import annotations

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
        gateway_catalog_file=str(path), mcp_gateway_url="https://gateway.example.test"
    )
    item = McpRegistration(
        id=destination["id"],
        name=destination["display_name"],
        authentication_model="no-authentication",
        server_id="native-server",
    )
    return settings, item, path, catalog


async def test_custom_catalog_url_drives_sdk_and_exact_caller_scope(endpoint, monkeypatch):
    settings, item, _, _ = endpoint
    sent = []
    clients = []
    real_client = httpx2.AsyncClient

    def upstream(request):
        assert str(request.url) == "https://gateway.example.test/operator/selected-endpoint"
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer caller-token"
        assert "cookie" not in request.headers
        sent.append(request)
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
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    def client_factory(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        client = real_client(transport=httpx2.MockTransport(upstream), **kwargs)
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
        "cross-host",
        "cross-scheme",
        "cross-port",
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
        elif invalid in {"proxy-only", "no-oidc", "cross-host", "cross-port"}:
            route.update(
                {
                    "proxy-only": {"entry_mode": "forward_proxy"},
                    "no-oidc": {"caller_auth_modes": ["neurwerk_bearer"]},
                    "cross-host": {"url": "https://another.example.test/selected-endpoint"},
                    "cross-port": {"url": "https://gateway.example.test:8443/selected-endpoint"},
                }[invalid]
            )
        elif invalid == "ambiguous":
            extra = deepcopy(route)
            extra.update(id="second-endpoint", url=settings.mcp_gateway_url + "/second")
            entry["routes"].append(extra)
            destination["endpoint_ids"].append(extra["id"])
        elif invalid == "cross-scheme":
            settings.mcp_gateway_url = "http://gateway.example.test"
        path.write_text(json.dumps(catalog))

    def unexpected_transport(**kwargs):
        pytest.fail("Untrusted or missing endpoint must fail before creating a credentialed client")

    monkeypatch.setattr(mcp_gateway.httpx2, "AsyncClient", unexpected_transport)
    with pytest.raises(mcp_gateway.McpGatewayError) as denied:
        async with mcp_gateway.gateway_client(settings, item, "Bearer caller-token"):
            pytest.fail("Untrusted or missing endpoint must not yield a client")
    assert denied.value.status == 503
    assert str(denied.value) == "MCP gateway endpoint is unavailable."
