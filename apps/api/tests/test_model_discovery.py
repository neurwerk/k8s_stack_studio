"""Local discovery never reveals models outside the caller's effective grants."""

import json

import httpx
import pytest
from fastapi import FastAPI

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.model_discovery import router
from k8s_stack_studio.lib.dependencies import get_settings


@pytest.mark.parametrize("group", ["self-hosted-api-providers", "external-api-providers"])
async def test_local_discovery_filters_and_conceals_models(tmp_path, group):
    catalog = {
        "schema_version": 2,
        "catalog_revision": "current",
        "policy_revision": "current",
        "endpoints": [
            {
                "id": name,
                "url": f"https://{name}.example.test/v1",
                "entry_mode": "api",
                "caller_auth_modes": ["neurwerk_bearer"],
            }
            for name in ("api-local", "api-company")
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
                    {"source": "caller_supplied", "required_permissions": mode_permissions}
                ],
            }
            for name, endpoint, mode_permissions in (
                ("local/visible", "api-local", []),
                ("local/hidden", "api-local", []),
                ("local/no-mode", "api-local", ["provider:private:company-use"]),
                ("company/visible", "api-company", []),
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
                    "model:company/visible:invoke",
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
                "X-Binding-Id": "api-company",
            }
            listed = await client.get(
                "/gateway/model-discovery/api-local/models?binding_id=api-company", headers=headers
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
                "/gateway/model-discovery/api-local/models/company%2Fvisible", headers=headers
            )
            assert (cross_binding.status_code, cross_binding.json()) == (404, hidden.json())
            encoded_twice = await client.get(
                "/gateway/model-discovery/api-local/models/local%252Fvisible", headers=headers
            )
            assert encoded_twice.status_code == 404
