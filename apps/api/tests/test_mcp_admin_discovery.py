"""Role-based discovery preserves caller identity and leases only scoped native authority."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import httpx
import pytest

from k8s_stack_studio.lib.contextforge import (
    DISCOVERY_ROLE_MARKER,
    ContextForgeAccountClient,
    ContextForgeAccountError,
    ContextForgeRateLimitError,
)
from k8s_stack_studio.lib.mcp_publication import publication_snapshot
from tests.test_mcp_publication import configured_projection


def admin_projection(tmp_path):
    settings, data = configured_projection(tmp_path)
    (data / "admin_discovery_role_id").write_text("admin-discovery")
    (data / "admin_discovery_ready").write_text("true")
    return settings, data


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


@pytest.mark.parametrize("readiness", ["missing", "false", "disabled"])
async def test_withheld_discovery_does_not_block_ordinary_roles_after_expiry(tmp_path, readiness):
    settings, data = admin_projection(tmp_path)
    if readiness == "missing":
        (data / "admin_discovery_ready").unlink()
    elif readiness == "false":
        (data / "admin_discovery_ready").write_text("false")
    settings = publication_snapshot(settings)[0]
    if readiness == "disabled":
        settings.contextforge_admin_discovery_enabled = False
        settings.contextforge_admin_discovery_role_id = ""
    assert not settings.contextforge_admin_discovery_role_id
    email = "person@example.test"
    grants = [
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
    grants.append(native_grant(email, remaining=-10))

    def upstream(request):
        assert request.method == "GET"
        assert request.url.path == f"/rbac/users/{email}/roles"
        # Native active_only defaults to true and excludes expired assignments.
        result = (
            grants
            if request.url.params.get("active_only") == "false"
            else [
                grant
                for grant in grants
                if grant["expires_at"] is None
                or datetime.fromisoformat(str(grant["expires_at"])) > datetime.now(UTC)
            ]
        )
        return httpx.Response(200, json=result)

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as native:
        account = ContextForgeAccountClient(settings, native)
        assert await account._roles(email) == {"global-empty", "team-invoke"}
        # With no verified discovery role, an active extra grant still fails closed.
        grants[-1] = native_grant(email)
        with pytest.raises(ContextForgeAccountError):
            await account._roles(email)


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


def test_long_native_grant_is_rejected(tmp_path):
    settings = publication_snapshot(admin_projection(tmp_path)[0])[0]
    with pytest.raises(ContextForgeAccountError):
        ContextForgeAccountClient(settings, Mock(spec=httpx.AsyncClient))._discovery_expiration(
            native_grant("person@example.test", lifetime=3600), "person@example.test"
        )
