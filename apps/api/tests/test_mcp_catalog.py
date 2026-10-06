"""Catalog permission hints use only the verified caller, never browser overrides."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.mcp import router
from k8s_stack_studio.lib.auth import StudioAdmissionMiddleware, StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_settings
from k8s_stack_studio.models.mcp import McpRegistration


@pytest.mark.parametrize(
    ("roles", "permitted"),
    [
        ([], False),
        (["llm:invoke"], False),
        (["mcp:github:invoke"], False),
        (["llm:invoke", "mcp:other:invoke"], False),
        (["llm:invoke", "mcp:github:invoke"], True),
    ],
)
async def test_catalog_verified_permission_boundary(roles, permitted):
    settings = Settings(
        mcp_catalog_enabled=True,
        contextforge_team_id="native-team",
        mcp_catalog=[
            McpRegistration(
                id="github",
                name="GitHub",
                authentication_model="individual-authentication",
                gateway_id="private-registration",
                server_id="private-server",
            )
        ],
    )
    principal = StudioPrincipal(
        "self", frozenset({"studio-user", "keycloak-admin"}), frozenset(roles), {}
    )
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(StudioAdmissionMiddleware)
    app.dependency_overrides[get_settings] = lambda: settings

    @app.middleware("http")
    async def identity(request, call_next):
        request.scope["user"] = principal
        return await call_next(request)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        result = await client.get(
            "/api/me/mcp/catalog?user_id=other&gateway_id=other&permitted=true",
            headers={"x-contextforge-account-email": "other@example.test"},
        )
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        assert result.json() == [
            {
                "id": "github",
                "name": "GitHub",
                "authentication_model": "individual-authentication",
                "permitted": permitted,
                "connection_status": "status unavailable",
            }
        ]
        assert "private-" not in result.text
        assert (await client.post("/api/me/mcp/github/connect")).status_code == 404

        settings.mcp_catalog_enabled = False
        assert (await client.get("/api/me/mcp/catalog")).status_code == 404
        principal = StudioPrincipal("self", frozenset(), frozenset(roles), {})
        assert (await client.get("/api/me/mcp/catalog")).status_code == 403
