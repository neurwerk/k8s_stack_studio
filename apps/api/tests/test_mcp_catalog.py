"""Catalog permission hints use only the verified caller, never browser overrides."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.mcp import router
from k8s_stack_studio.lib.auth import StudioAdmissionMiddleware, StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_settings
from k8s_stack_studio.models.mcp import McpRegistration


def test_chart_credential_policy_is_fixed():
    base = {
        "id": "context7",
        "name": "Context7",
        "authentication_model": "no-authentication",
        "gateway_id": "gateway",
        "server_id": "server",
        "upstream_url": "https://mcp.example.test/mcp",
    }
    assert McpRegistration.model_validate(base).credential is None
    item = McpRegistration.model_validate(
        base
        | {
            "credential": {
                "owner": "shared",
                "required": False,
                "method": "gateway-header",
                "header": "CONTEXT7_API_KEY",
            }
        }
    )
    assert item.credential is not None and item.credential.required is False
    for credential in (
        {"owner": "individual", "required": True, "method": "oauth"},
        {"owner": "shared", "required": False, "method": "oauth"},
        {"owner": "none", "required": True, "method": "none"},
    ):
        with pytest.raises(ValueError):
            McpRegistration.model_validate(base | {"credential": credential})
    with pytest.raises(ValueError):
        McpRegistration.model_validate(
            base | {"upstream_url": "https://user:secret@mcp.example.test/mcp"}
        )


@pytest.mark.parametrize("unsafe_default", [False, True])
async def test_native_account_preparation_boundary(unsafe_default, caplog):
    """Only verified permissioned emails can activate a least-privilege native account."""
    settings = Settings(
        mcp_catalog_enabled=True,
        contextforge_team_id="team-fixed",
        mcp_catalog=[
            McpRegistration(
                id="context7",
                name="Context7",
                authentication_model="no-authentication",
                gateway_id="gateway",
                server_id="server",
            )
        ],
        contextforge_account_onboarding_enabled=True,
        contextforge_url="https://native.example.test",
        contextforge_service_token=SecretStr("service-secret"),
        contextforge_global_role_id="global-empty",
        contextforge_team_role_id="team-invoke",
    )
    principal = StudioPrincipal(
        "self",
        frozenset({"studio-user"}),
        frozenset({"llm:invoke", "mcp:context7:invoke"}),
        {"email": "Self@example.test", "email_verified": True},
    )
    email = "self@example.test"
    user_path = f"/auth/email/admin/users/{email}"
    roles_path = f"/rbac/users/{email}/roles"
    user = {"email": email, "is_admin": False, "is_active": False, "email_verified": True}
    grants = [
        {
            "role_id": "global-empty",
            "scope": "global",
            "scope_id": None,
            "user_email": email,
            "is_active": True,
        },
        {
            "role_id": "team-invoke",
            "scope": "team",
            "scope_id": "team-fixed",
            "user_email": email,
            "is_active": True,
        },
    ]
    preflight = [
        (
            "GET",
            "/teams/team-fixed",
            200,
            {"id": "team-fixed", "is_active": True, "is_personal": False},
        ),
        (
            "GET",
            "/rbac/roles/global-empty",
            200,
            {
                "id": "global-empty",
                "scope": "global",
                "is_active": True,
                "inherits_from": None,
                "permissions": [],
            },
        ),
        (
            "GET",
            "/rbac/roles/team-invoke",
            200,
            {
                "id": "team-invoke",
                "scope": "team",
                "is_active": True,
                "inherits_from": None,
                "permissions": [
                    "tools.read",
                    "tools.execute",
                    "servers.read",
                    "servers.use",
                    "gateways.read",
                ],
            },
        ),
    ]
    steps = [
        *preflight,
        ("GET", user_path, 404, {}),
        ("POST", "/auth/email/admin/users", 201, user),
        ("GET", roles_path, 200, [{**grants[0], "role_id": "operator"}] if unsafe_default else []),
    ]
    if not unsafe_default:
        steps.extend(
            [
                (
                    "POST",
                    "/teams/team-fixed/members",
                    201,
                    {
                        "team_id": "team-fixed",
                        "user_email": email,
                        "role": "member",
                        "is_active": True,
                    },
                ),
                ("GET", roles_path, 200, []),
                ("POST", roles_path, 200, grants[0]),
                ("POST", roles_path, 200, grants[1]),
                ("GET", roles_path, 200, grants),
                ("PATCH", user_path, 200, {**user, "is_active": True}),
            ]
        )
    password = ""
    requests = []

    def upstream(request):
        nonlocal password
        requests.append(request.url.path)
        assert request.headers["authorization"] == "Bearer service-secret"
        assert "x-contextforge-account-email" not in request.headers
        method, path, status, result = steps.pop(0)
        assert (request.method, request.url.path) == (method, path)
        body = json.loads(request.content) if request.content else {}
        if path == "/auth/email/admin/users":
            password = body.pop("password")
            assert len(password) >= 64
            assert body == {
                "email": email,
                "is_admin": False,
                "is_active": False,
                "password_change_required": False,
            }
        if method == "PATCH":
            assert body == {"is_active": True}
        return httpx.Response(status, json=result)

    app = FastAPI()
    app.include_router(router)
    app.add_middleware(StudioAdmissionMiddleware)
    app.dependency_overrides[get_settings] = lambda: settings

    @app.middleware("http")
    async def identity(request, call_next):
        request.scope["user"] = principal
        return await call_next(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as native:
        app.state.contextforge_admin_client = native
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/me/mcp/account", json={"email": "other@example.test"}
            )
            assert response.status_code == 422 and not requests
            response = await client.post(
                "/api/me/mcp/account",
                json={},
                headers={"x-contextforge-account-email": "other@example.test"},
            )
            assert response.headers["cache-control"] == "no-store"
            assert response.status_code == (502 if unsafe_default else 200)
            assert not steps
            assert password not in response.text and "service-secret" not in response.text
            assert password not in caplog.text and "service-secret" not in caplog.text
            # Never reactivate an existing operator-disabled account or partial setup.
            steps.extend([*preflight, ("GET", user_path, 200, user)])
            assert (await client.post("/api/me/mcp/account", json={})).status_code == 502
            assert not steps
            # A native read cannot distinguish absent from revoked membership.
            # Resolution must stay read-only, even with the expected active roles.
            steps.extend(
                [
                    *preflight,
                    ("GET", user_path, 200, {**user, "is_active": True}),
                    ("GET", roles_path, 200, grants),
                    ("GET", "/teams/team-fixed/members", 200, {"members": [], "nextCursor": None}),
                ]
            )
            assert (await client.post("/api/me/mcp/account", json={})).status_code == 502
            assert not steps
            requests.clear()
            principal = StudioPrincipal(
                "self",
                frozenset({"studio-user", "keycloak-admin"}),
                frozenset({"llm:invoke"}),
                {"email": "self@example.test", "email_verified": True},
            )
            assert (await client.post("/api/me/mcp/account", json={})).status_code == 403
            assert not requests
            settings.contextforge_account_onboarding_enabled = False
            assert (await client.post("/api/me/mcp/account", json={})).status_code == 404


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
                "can_discover": False,
                "publication": None,
            }
        ]
        assert "private-" not in result.text
        assert (await client.post("/api/me/mcp/github/connect")).status_code == 404

        settings.mcp_catalog_enabled = False
        assert (await client.get("/api/me/mcp/catalog")).status_code == 404
        principal = StudioPrincipal("self", frozenset(), frozenset(roles), {})
        assert (await client.get("/api/me/mcp/catalog")).status_code == 403
