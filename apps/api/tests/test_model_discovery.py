"""Local discovery never reveals models outside the caller's effective grants."""

import json

import httpx
from fastapi import FastAPI

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.model_discovery import router
from k8s_stack_studio.lib.dependencies import get_settings


async def test_local_discovery_filters_and_conceals_models(tmp_path):
    catalog = {
        "schema_version": 1,
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
                "credential_modes": [{"source": "none", "required_permissions": mode_permissions}],
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
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        gateway_catalog_file=str(path), keycloak_api_key_bridge_url="http://bridge.test"
    )

    def verify(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/gateway/caller-permissions"
        assert request.headers["x-neurwerk-authorization"] == "Bearer test-key"
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
            headers = {"X-Neurwerk-Authorization": "Bearer test-key", "X-Roles": "admin"}
            listed = await client.get("/gateway/model-discovery", headers=headers)
            assert listed.status_code == 200
            assert listed.json() == {
                "object": "list",
                "data": [
                    {"id": "local/visible", "object": "model", "created": 0, "owned_by": "neurwerk"}
                ],
            }
            visible = await client.get("/gateway/model-discovery/local%2Fvisible", headers=headers)
            assert visible.json() == listed.json()["data"][0]
            hidden = await client.get("/gateway/model-discovery/local%2Fhidden", headers=headers)
            unknown = await client.get("/gateway/model-discovery/local%2Funknown", headers=headers)
            assert (hidden.status_code, hidden.json()) == (unknown.status_code, unknown.json())
            assert hidden.status_code == 404
            encoded_twice = await client.get(
                "/gateway/model-discovery/local%252Fvisible", headers=headers
            )
            assert encoded_twice.status_code == 404
