"""Role-based discovery preserves caller identity and leases only scoped native authority."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.mcp import router
from k8s_stack_studio.lib.auth import StudioAdmissionMiddleware, StudioPrincipal
from k8s_stack_studio.lib.contextforge import (
    DISCOVERY_ROLE_MARKER,
    ContextForgeAccountClient,
    ContextForgeAccountError,
    ContextForgeRateLimitError,
)
from k8s_stack_studio.lib.contextforge_oauth import ContextForgeOAuthClient
from k8s_stack_studio.lib.dependencies import get_settings
from k8s_stack_studio.lib.mcp_publication import publication_snapshot
from tests.test_mcp_discovery import configured_projection


def admin_projection(tmp_path):
    settings, data = configured_projection(tmp_path)
    settings = Settings.model_validate(
        {
            **settings.model_dump(),
            "contextforge_operator_discovery_enabled": False,
            "contextforge_operator_email": "",
            "contextforge_operator_subject": "",
            "contextforge_admin_discovery_enabled": True,
        }
    )
    (data / "admin_discovery_role_id").write_text("admin-discovery")
    (data / "admin_discovery_ready").write_text("true")
    return settings, data


async def test_any_mcp_admin_uses_own_connection_and_revocation_denies(tmp_path, monkeypatch):
    settings, data = admin_projection(tmp_path)
    principal = StudioPrincipal(
        "one",
        frozenset({"studio-user", "mcp-admin"}),
        frozenset({"llm:invoke", "mcp:github:invoke"}),
        {"email": "one@example.test", "email_verified": True},
    )
    calls = []

    async def grant(self, email):
        calls.append(("grant", email))
        assert self.settings.contextforge_admin_discovery_role_id == "admin-discovery"

    async def discover(self, item):
        calls.append(("discover", self.email))
        assert item.gateway_id == "fixed-gateway"

    monkeypatch.setattr(ContextForgeAccountClient, "prepare_discovery", grant)
    monkeypatch.setattr(ContextForgeOAuthClient, "discover", discover)
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(StudioAdmissionMiddleware)
    app.dependency_overrides[get_settings] = lambda: settings

    @app.middleware("http")
    async def identity(request, call_next):
        request.scope["user"] = principal
        return await call_next(request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ) as native:
        app.state.contextforge_admin_client = native
        app.state.contextforge_oauth_client = native
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
            headers={
                "origin": settings.contextforge_oauth_studio_origin,
                "x-contextforge-account-email": "forged@example.test",
            },
        ) as client:
            path = "/api/me/mcp/github/discover"
            for subject in ("one", "two"):
                principal = StudioPrincipal(
                    subject,
                    principal.roles,
                    principal.agentgateway_roles,
                    {"email": f"{subject}@example.test", "email_verified": True},
                )
                assert (await client.get("/api/me/mcp/catalog")).json()[0]["can_discover"]
                assert (await client.post(path, json={})).status_code == 200
                assert calls[-2:] == [
                    ("grant", f"{subject}@example.test"),
                    ("discover", f"{subject}@example.test"),
                ]
            calls.clear()
            assert (
                await client.post(path, json={"email": "other@example.test"})
            ).status_code == 422
            assert (
                await client.post(path, json={}, headers={"origin": "https://other.test"})
            ).status_code == 403
            (data / "admin_discovery_ready").unlink()
            assert (await client.post(path, json={})).status_code == 403
            (data / "admin_discovery_ready").write_text("true")
            for roles, grants, verified in [
                ({"studio-user"}, principal.agentgateway_roles, True),
                ({"studio-user", "mcp-admin"}, {"llm:invoke"}, True),
                ({"studio-user", "mcp-admin"}, principal.agentgateway_roles, False),
                ({"mcp-admin"}, principal.agentgateway_roles, True),
            ]:
                principal = StudioPrincipal(
                    "two",
                    frozenset(roles),
                    frozenset(grants),
                    {"email": "two@example.test", "email_verified": verified},
                )
                assert (await client.post(path, json={})).status_code == 403
            assert calls == []


def native_grant(email, *, lifetime=120, remaining=120):
    expires = datetime.now(UTC) + timedelta(seconds=remaining)
    return {
        "role_id": "admin-discovery",
        "user_email": email,
        "scope": "team",
        "scope_id": "fixed-team",
        "is_active": True,
        "granted_by": "provisioner@example.test",
        "granted_at": (expires - timedelta(seconds=lifetime)).isoformat(),
        "expires_at": expires.isoformat(),
    }


@pytest.mark.parametrize("existing", [None, "current", "expired", "near-expiry"])
async def test_native_grant_is_bounded_and_ordinary_reads_never_renew(
    tmp_path, monkeypatch, existing
):
    settings = publication_snapshot(admin_projection(tmp_path)[0])[0]
    email = "person@example.test"
    baseline = [
        {
            "role_id": role,
            "user_email": email,
            "scope": scope,
            "scope_id": team,
            "is_active": True,
            "expires_at": None,
        }
        for role, scope, team in [
            ("global-empty", "global", None),
            ("team-invoke", "team", "fixed-team"),
        ]
    ]
    grants = list(baseline)
    if existing:
        grants.append(
            native_grant(
                email, remaining={"current": 90, "expired": -10, "near-expiry": 10}[existing]
            )
        )
    writes = []

    async def checked_configuration(self):
        pass  # Existing account tests cover fixed service and baseline role validation.

    monkeypatch.setattr(ContextForgeAccountClient, "_check_configuration", checked_configuration)

    def upstream(request):
        assert request.headers["x-contextforge-account-email"] == "provisioner@example.test"
        assert "cookie" not in request.headers and "authorization" not in request.headers
        path = request.url.path
        if request.method == "POST":
            assert path == f"/rbac/users/{email}/roles"
            body = json.loads(request.content)
            assert set(body) == {"role_id", "scope", "scope_id", "expires_at"}
            assert body["role_id"] == "admin-discovery" and body["scope_id"] == "fixed-team"
            result = native_grant(email) | body
            grants[:] = [*baseline, result]
            writes.append(body)
            return httpx.Response(200, json=result)
        assert request.method == "GET"
        if path.startswith("/auth/"):
            body = {"email": email, "is_active": True, "is_admin": False, "email_verified": True}
        elif path.startswith("/rbac/users/"):
            assert request.url.params["active_only"] == "false"
            body = grants
        elif path.startswith("/rbac/roles/"):
            body = {
                "id": "admin-discovery",
                "name": "contextforge-tool-discovery",
                "description": DISCOVERY_ROLE_MARKER,
                "scope": "team",
                "is_active": True,
                "is_system_role": False,
                "inherits_from": None,
                "permissions": ["gateways.update"],
            }
        else:
            assert path == "/teams/fixed-team/members"
            body = {
                "members": [
                    {
                        "user_email": email,
                        "team_id": "fixed-team",
                        "role": "member",
                        "is_active": True,
                    }
                ]
            }
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as native:
        account = ContextForgeAccountClient(settings, native)
        await account.check_account(email)
        assert not writes
        if existing == "near-expiry":
            with pytest.raises(ContextForgeRateLimitError):
                await account.prepare_discovery(email)
            assert not writes
        else:
            await account.prepare_discovery(email)
            assert len(writes) == (0 if existing == "current" else 1)
            await account.check_account(email)
            assert len(writes) == (0 if existing == "current" else 1)


@pytest.mark.parametrize(
    "change",
    [
        {"scope_id": "another-team"},
        {"user_email": "another@example.test"},
        {"expires_at": None},
        {"granted_by": "another@example.test"},
        {"is_active": False},
        {"scope": "global"},
        {"expires_at": "bad"},
    ],
)
def test_discovery_grant_rejects_wrong_identity_scope_or_unbounded_authority(tmp_path, change):
    settings = publication_snapshot(admin_projection(tmp_path)[0])[0]
    account = ContextForgeAccountClient(settings, Mock(spec=httpx.AsyncClient))
    with pytest.raises(ContextForgeAccountError):
        account._discovery_expiration(
            native_grant("person@example.test") | change, "person@example.test"
        )


def test_long_native_grant_and_mixed_modes_are_rejected(tmp_path):
    settings = publication_snapshot(admin_projection(tmp_path)[0])[0]
    with pytest.raises(ContextForgeAccountError):
        ContextForgeAccountClient(settings, Mock(spec=httpx.AsyncClient))._discovery_expiration(
            native_grant("person@example.test", lifetime=3600), "person@example.test"
        )
    with pytest.raises(ValueError):
        Settings.model_validate(
            {**settings.model_dump(), "contextforge_operator_discovery_enabled": True}
        )
