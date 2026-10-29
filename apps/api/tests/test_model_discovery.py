"""Local discovery never reveals models outside the caller's effective grants."""

import json

import httpx
import pytest
from fastapi import FastAPI

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.model_discovery import router
from k8s_stack_studio.lib.dependencies import get_settings


@pytest.fixture
async def selector_discovery(tmp_path):
    modes = ["global", "none", "override"]
    entry = {
        "id": "binding",
        "provider_id": "example",
        "display_name": "Example",
        "global_credential_status": "configured",
        "routes": [
            {
                "id": "api",
                "url": "https://gateway.example.test/v1",
                "entry_mode": "api",
                "caller_auth_modes": ["neurwerk_bearer"],
                "credential_mode_header": "X-Neurwerk-Credential-Mode",
            }
        ],
        "destinations": [
            {
                "id": mode,
                "kind": "model",
                "display_name": mode,
                "provider_id": "example",
                "endpoint_ids": ["api"],
                "profile_ids": [],
                "required_permissions": ["llm:invoke", f"model:{mode}:invoke"],
                "credential_modes": [{"source": mode, "required_permissions": [f"mode:{mode}"]}],
            }
            for mode in modes
        ],
    }
    catalog = {
        "schema_version": 3,
        "catalog_revision": "current",
        "policy_revision": "current",
        "profiles": [],
        "self-hosted-api-providers": [],
        "external-api-providers": [entry],
        "external-subscription-providers": [],
        "mcp-servers": [],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog))
    permissions = ["llm:invoke", "provider:example:global-use"] + [
        permission for mode in modes for permission in (f"model:{mode}:invoke", f"mode:{mode}")
    ]
    calls = []

    def verify(request):
        calls.append(request)
        assert json.loads(request.content) == {"binding_id": "binding"}
        assert "x-neurwerk-credential-mode" not in request.headers
        assert "x-api-key" not in request.headers
        assert "authorization" not in request.headers
        assert request.headers["x-neurwerk-authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"permissions": permissions})

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        gateway_catalog_file=str(path), keycloak_api_key_bridge_url="http://bridge.test"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(verify)) as bridge:
        app.state.http_client = bridge
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://studio.test"
        ) as client:
            yield client, permissions, entry, path, catalog, calls


@pytest.mark.parametrize("mode", ["global", "none", "override"])
async def test_explicit_discovery_filters_list_and_retrieve_without_provider(
    selector_discovery, mode
):
    client, _, _, _, _, calls = selector_discovery
    headers = {
        "X-Neurwerk-Authorization": "Bearer test-key",
        "X-Neurwerk-Credential-Mode": f" \t{mode}\t ",
    }
    base = "/gateway/model-discovery/binding/models"
    listed = await client.get(base, headers=headers)
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "no-store"
    assert [item["id"] for item in listed.json()["data"]] == [mode]
    retrieved = await client.get(f"{base}/{mode}", headers=headers)
    assert retrieved.json() == listed.json()["data"][0]
    if mode == "override":
        # Discovery neither consumes nor validates provider credentials, even if supplied.
        headers["Authorization"] = "not-a-provider-credential"
        headers["x-api-key"] = "not-a-provider-credential"
        assert (await client.get(base, headers=headers)).json() == listed.json()
    hidden = "none" if mode != "none" else "global"
    assert (await client.get(f"{base}/{hidden}", headers=headers)).status_code == 404
    assert len(calls) == (4 if mode == "override" else 3)


@pytest.mark.parametrize(
    "missing", ["llm:invoke", "model:global:invoke", "mode:global", "provider:example:global-use"]
)
async def test_explicit_discovery_requires_all_permissions(selector_discovery, missing):
    client, permissions, _, _, _, _ = selector_discovery
    permissions.remove(missing)
    headers = {
        "X-Neurwerk-Authorization": "Bearer test-key",
        "X-Neurwerk-Credential-Mode": "global",
    }
    base = "/gateway/model-discovery/binding/models"
    listed = await client.get(base, headers=headers)
    retrieved = await client.get(f"{base}/global", headers=headers)
    if missing == "llm:invoke":
        assert listed.status_code == retrieved.status_code == 403
    else:
        assert listed.status_code == 200
        assert listed.json()["data"] == []
        assert retrieved.status_code == 404


@pytest.mark.parametrize("status", [None, "missing", "disabled"])
async def test_explicit_global_discovery_requires_configured_credential(selector_discovery, status):
    client, _, entry, path, catalog, _ = selector_discovery
    entry["global_credential_status"] = status
    path.write_text(json.dumps(catalog))
    headers = {
        "X-Neurwerk-Authorization": "Bearer test-key",
        "X-Neurwerk-Credential-Mode": "global",
    }
    base = "/gateway/model-discovery/binding/models"
    assert (await client.get(base, headers=headers)).json()["data"] == []
    assert (await client.get(f"{base}/global", headers=headers)).status_code == 404
    del headers["X-Neurwerk-Credential-Mode"]
    assert len((await client.get(base, headers=headers)).json()["data"]) == 3


@pytest.mark.parametrize("absent", [True, False])
async def test_explicit_discovery_requires_route_capability(selector_discovery, absent):
    client, _, entry, path, catalog, _ = selector_discovery
    if absent:
        del entry["routes"][0]["credential_mode_header"]
    else:
        entry["routes"][0]["credential_mode_header"] = None
    path.write_text(json.dumps(catalog))
    headers = {
        "X-Neurwerk-Authorization": "Bearer test-key",
        "X-Neurwerk-Credential-Mode": "override",
    }
    response = await client.get("/gateway/model-discovery/binding/models", headers=headers)
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "headers,code",
    [
        ([("X-Neurwerk-Credential-Mode", "override"), ("Authorization", "Bearer test-key")], 401),
        (
            [
                ("X-Neurwerk-Credential-Mode", "override"),
                ("X-Neurwerk-Authorization", "Bearer test-key"),
                ("x-neurwerk-authorization", "Bearer test-key"),
            ],
            401,
        ),
        ([("X-Neurwerk-Credential-Mode", "none"), ("x-neurwerk-credential-mode", "none")], 400),
        ([("X-Neurwerk-Credential-Mode", "none,override")], 400),
        ([("X-Neurwerk-Credential-Mode", "")], 400),
        ([("X-Neurwerk-Credential-Mode", "GLOBAL")], 400),
        ([("X-Neurwerk-Credential-Mode", "other")], 400),
    ],
)
async def test_explicit_discovery_rejects_ambiguous_mode_or_missing_identity(
    selector_discovery, headers, code
):
    client, _, _, _, _, calls = selector_discovery
    for suffix in ("", "/override"):
        response = await client.get(
            f"/gateway/model-discovery/binding/models{suffix}", headers=headers
        )
        assert response.status_code == code
        assert response.headers["cache-control"] == "no-store"
    assert calls == []


@pytest.mark.parametrize("group", ["self-hosted-api-providers", "external-api-providers"])
async def test_local_discovery_filters_and_conceals_models(tmp_path, group):
    catalog = {
        "schema_version": 3,
        "catalog_revision": "current",
        "policy_revision": "current",
        "endpoints": [
            {
                "id": name,
                "url": f"https://{name}.example.test/v1",
                "entry_mode": "api",
                "caller_auth_modes": ["neurwerk_bearer"],
            }
            for name in ("api-local", "api-global")
        ],
        "destinations": [
            {
                "id": name,
                "kind": "model",
                "display_name": name,
                "endpoint_ids": [endpoint],
                "profile_ids": [],
                "required_permissions": ["llm:invoke", f"model:{name}:invoke"],
                "credential_modes": [
                    {"source": "override", "required_permissions": mode_permissions}
                ],
            }
            for name, endpoint, mode_permissions in (
                ("local/visible", "api-local", []),
                ("local/hidden", "api-local", []),
                ("local/no-mode", "api-local", ["provider:private:global-use"]),
                ("global/visible", "api-global", []),
            )
        ],
        "profiles": [],
    }
    routes = catalog.pop("endpoints")
    destinations = catalog.pop("destinations")
    catalog.update(
        {
            "self-hosted-api-providers": [
                {
                    "id": route["id"],
                    "provider_id": None,
                    "display_name": route["id"],
                    "routes": [route],
                    "destinations": [
                        item for item in destinations if route["id"] in item["endpoint_ids"]
                    ],
                }
                for route in routes
            ],
            "external-api-providers": [],
            "external-subscription-providers": [],
            "mcp-servers": [],
        }
    )
    if group == "external-api-providers":
        catalog[group] = catalog["self-hosted-api-providers"]
        catalog["self-hosted-api-providers"] = []
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        gateway_catalog_file=str(path), keycloak_api_key_bridge_url="http://bridge.test"
    )

    def verify(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/gateway/caller-permissions"
        assert json.loads(request.content) == {"binding_id": "api-local"}
        assert request.headers["x-neurwerk-authorization"] == "Bearer test-key"
        assert "authorization" not in request.headers
        assert "x-binding-id" not in request.headers
        return httpx.Response(
            200,
            json={
                "permissions": [
                    "llm:invoke",
                    "model:local/visible:invoke",
                    "model:local/no-mode:invoke",
                    "model:global/visible:invoke",
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(verify)) as bridge:
        app.state.http_client = bridge
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://studio.test"
        ) as client:
            headers = {
                "X-Neurwerk-Authorization": "Bearer test-key",
                "X-Roles": "admin",
                "Authorization": "Bearer upstream-must-not-be-forwarded",
                "X-Binding-Id": "api-global",
            }
            listed = await client.get(
                "/gateway/model-discovery/api-local/models?binding_id=api-global", headers=headers
            )
            assert listed.status_code == 200
            assert listed.headers["cache-control"] == "no-store"
            assert listed.json() == {
                "object": "list",
                "data": [
                    {"id": "local/visible", "object": "model", "created": 0, "owned_by": "neurwerk"}
                ],
            }
            visible = await client.get(
                "/gateway/model-discovery/api-local/models/local%2Fvisible", headers=headers
            )
            assert visible.json() == listed.json()["data"][0]
            hidden = await client.get(
                "/gateway/model-discovery/api-local/models/local%2Fhidden", headers=headers
            )
            unknown = await client.get(
                "/gateway/model-discovery/api-local/models/local%2Funknown", headers=headers
            )
            assert (hidden.status_code, hidden.json()) == (unknown.status_code, unknown.json())
            assert hidden.status_code == 404
            assert hidden.headers["cache-control"] == "no-store"
            cross_binding = await client.get(
                "/gateway/model-discovery/api-local/models/global%2Fvisible", headers=headers
            )
            assert (cross_binding.status_code, cross_binding.json()) == (404, hidden.json())
            encoded_twice = await client.get(
                "/gateway/model-discovery/api-local/models/local%252Fvisible", headers=headers
            )
            assert encoded_twice.status_code == 404
