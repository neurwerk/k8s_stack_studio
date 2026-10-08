"""Named operator admission and live publication must fail closed without writes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.mcp import router
from k8s_stack_studio.lib.auth import StudioAdmissionMiddleware, StudioPrincipal
from k8s_stack_studio.lib.contextforge import ContextForgeAccountClient, ContextForgeAccountError
from k8s_stack_studio.lib.dependencies import get_settings
from k8s_stack_studio.lib.mcp_publication import PublicationUnavailableError, publication_snapshot
from k8s_stack_studio.models.mcp import McpRegistration


def configured_projection(tmp_path):
    catalog = [
        McpRegistration(
            id="github",
            name="GitHub",
            authentication_model="individual-authentication",
            gateway_id="fixed-gateway",
            server_id="fixed-server",
            oauth_authorization_origin="https://provider.example.test",
            approved_tools=["read"],
        )
    ]
    settings = Settings(
        mcp_catalog_enabled=True,
        mcp_catalog=catalog,
        contextforge_team_id="fixed-team",
        contextforge_global_role_id="global-empty",
        contextforge_team_role_id="team-invoke",
        contextforge_account_onboarding_enabled=True,
        contextforge_service_auth_mode="trusted-proxy",
        contextforge_service_account_email="provisioner@example.test",
        contextforge_url="https://native.example.test",
        mcp_connections_enabled=True,
        contextforge_oauth_studio_origin="https://studio.example.test",
        contextforge_oauth_callback_url="https://studio.example.test/oauth/callback",
        contextforge_operator_discovery_enabled=True,
        contextforge_operator_email="operator@example.test",
        contextforge_operator_subject="bound-subject",
        contextforge_publication_status_path=str(tmp_path / "publication.json"),
    )
    data = tmp_path / "generation-one"
    data.mkdir()
    (tmp_path / "..data").symlink_to(data, target_is_directory=True)
    contents = {
        "studio.json": json.dumps([item.model_dump() for item in catalog]),
        "team_id": "fixed-team",
        "global_role_id": "global-empty",
        "team_role_id": "team-invoke",
        "operator_email": "operator@example.test",
        "operator_subject": "bound-subject",
        "operator_role_id": "team-discover",
        "publication.json": json.dumps(
            {
                "catalog_hash": "a" * 64,
                "checked_at": datetime.now(UTC).isoformat(),
                "integrations": [
                    {"id": "github", "state": "pending-discovery", "error_code": None}
                ],
            }
        ),
    }
    for name, value in contents.items():
        (data / name).write_text(value)
        (tmp_path / name).symlink_to(f"..data/{name}")
    return settings, data


def test_live_atomic_projection_and_fail_closed(tmp_path, monkeypatch):
    settings, data = configured_projection(tmp_path)
    live, statuses = publication_snapshot(settings)
    assert live.contextforge_operator_role_id == "team-discover"
    assert statuses["github"].state == "pending-discovery"
    catalog = json.loads((data / "studio.json").read_text())
    catalog[0]["tool_names"] = {"read": "native_read"}
    (data / "studio.json").write_text(json.dumps(catalog))
    publication = json.loads((data / "publication.json").read_text())
    publication["integrations"][0]["state"] = "published"
    (data / "publication.json").write_text(json.dumps(publication))
    assert publication_snapshot(settings)[0].mcp_catalog[0].tool_names == {"read": "native_read"}
    assert settings.mcp_catalog[0].tool_names == {}
    from k8s_stack_studio.lib import mcp_publication

    original = mcp_publication._read

    def switch(directory, name):
        if name == "publication.json":
            (tmp_path / "..data").unlink()
            (tmp_path / "..data").symlink_to(tmp_path / "missing-generation")
        return original(directory, name)

    monkeypatch.setattr(mcp_publication, "_read", switch)
    assert publication_snapshot(settings)[1]["github"].state == "published"
    with pytest.raises(PublicationUnavailableError):
        publication_snapshot(settings)
    settings.contextforge_publication_status_path = ""
    assert publication_snapshot(settings) == (settings, {})


@pytest.mark.parametrize(
    "key,value",
    [
        ("catalog_hash", "other"),
        ("checked_at", "2026-01-01T00:00:00"),
        ("integrations", [{"id": "other", "state": "published", "error_code": None}]),
    ],
)
def test_invalid_projection_is_not_stale_ready(tmp_path, key, value):
    settings, data = configured_projection(tmp_path)
    publication = json.loads((data / "publication.json").read_text())
    publication[key] = value
    (data / "publication.json").write_text(json.dumps(publication))
    with pytest.raises(PublicationUnavailableError):
        publication_snapshot(settings)


@pytest.mark.parametrize(
    "withheld", ["missing-email", "missing-subject", "wrong-subject", "disabled"]
)
def test_retained_operator_role_is_history_not_admission(tmp_path, withheld):
    settings, data = configured_projection(tmp_path)
    if withheld.startswith("missing-"):
        (data / ("operator_email" if withheld == "missing-email" else "operator_subject")).unlink()
    elif withheld == "wrong-subject":
        (data / "operator_subject").write_text("other-subject")
    else:
        settings.contextforge_operator_discovery_enabled = False
    live, statuses = publication_snapshot(settings)
    assert live.contextforge_operator_role_id == ""
    assert statuses["github"].state == "pending-discovery"


def test_empty_startup_and_omitted_unverified_registration(tmp_path):
    settings, data = configured_projection(tmp_path)
    settings = Settings.model_validate({**settings.model_dump(), "mcp_catalog": []})
    (data / "studio.json").write_text("[]")
    publication = json.loads((data / "publication.json").read_text())
    publication["integrations"][0].update(state="error", error_code="provider-unavailable")
    (data / "publication.json").write_text(json.dumps(publication))
    live, statuses = publication_snapshot(settings)
    assert live.mcp_catalog == [] and statuses["github"].state == "error"
    # The same running API can consume a later verified registration without restart.
    registration = McpRegistration(
        id="github",
        name="GitHub",
        authentication_model="individual-authentication",
        gateway_id="fixed-gateway",
        server_id="fixed-server",
        oauth_authorization_origin="https://provider.example.test",
        approved_tools=["read"],
        tool_names={"read": "github_native_read"},
    )
    (data / "studio.json").write_text(json.dumps([registration.model_dump()]))
    publication["integrations"][0].update(state="published", error_code=None)
    (data / "publication.json").write_text(json.dumps(publication))
    assert publication_snapshot(settings)[0].mcp_catalog == [registration]


@pytest.mark.parametrize(
    "unsafe", ["", "admin", "disabled", "inherited", "extra", "expired", "inactive", "revoked"]
)
async def test_operator_profile_is_exact_and_read_only(tmp_path, monkeypatch, unsafe):
    settings, _ = configured_projection(tmp_path)
    settings = publication_snapshot(settings)[0]
    email = settings.contextforge_operator_email

    async def checked_configuration(self):
        pass  # Existing account tests cover ordinary/service role and team configuration.

    monkeypatch.setattr(ContextForgeAccountClient, "_check_configuration", checked_configuration)

    def upstream(request):
        assert request.method == "GET"
        path = request.url.path
        if path.startswith("/auth/"):
            body = {
                "email": email,
                "is_admin": unsafe == "admin",
                "is_active": unsafe != "disabled",
                "email_verified": True,
            }
        elif path.startswith("/rbac/roles/"):
            body = {
                "id": "team-discover",
                "name": "neurwerk-mcp-discovery",
                "scope": "team",
                "is_active": True,
                "inherits_from": "parent" if unsafe == "inherited" else None,
                "permissions": ["gateways.update"],
            }
        elif path.startswith("/rbac/users/"):
            assert request.url.params["active_only"] == "false"
            roles = ["global-empty", "team-invoke", "team-discover"]
            if unsafe == "extra":
                roles.append("unrelated")
            body = [
                {
                    "role_id": role,
                    "user_email": email,
                    "scope": "global" if role == "global-empty" else "team",
                    "scope_id": None if role == "global-empty" else "fixed-team",
                    "is_active": unsafe != "inactive",
                    "expires_at": "2020-01-01" if unsafe == "expired" else None,
                }
                for role in roles
            ]
        else:
            assert path == "/teams/fixed-team/members"
            body = {
                "members": [
                    {
                        "user_email": email,
                        "team_id": "fixed-team",
                        "role": "member",
                        "is_active": unsafe != "revoked",
                    }
                ],
                "nextCursor": None,
            }
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as native:
        account = ContextForgeAccountClient(settings, native)
        if unsafe:
            with pytest.raises(ContextForgeAccountError):
                await account.check_operator(email)
        else:
            await account.check_operator(email)


async def test_discovery_admission_transport_and_publication(tmp_path, monkeypatch, caplog):
    settings, data = configured_projection(tmp_path)
    email = settings.contextforge_operator_email
    principal = StudioPrincipal(
        "bound-subject",
        frozenset({"studio-user"}),
        frozenset({"llm:invoke", "mcp:github:invoke"}),
        {"email": email, "email_verified": True},
    )
    requests = []
    native_status = 200
    result = {
        "gateway_id": "fixed-gateway",
        "success": True,
        "error": None,
        "validation_errors": [],
    }

    async def check_operator(self, who):
        assert who == email and self.settings.contextforge_operator_role_id == "team-discover"

    monkeypatch.setattr(ContextForgeAccountClient, "check_operator", check_operator)

    def upstream(request):
        requests.append(request)
        assert request.headers["x-contextforge-account-email"] == email
        assert "authorization" not in request.headers and "cookie" not in request.headers
        path = request.url.path
        if request.method == "POST":
            assert path == "/gateways/fixed-gateway/tools/refresh"
            assert dict(request.url.params) == {
                "include_resources": "false",
                "include_prompts": "false",
            }
            return httpx.Response(native_status, json=result, headers={"retry-after": "17"})
        if path.startswith("/oauth/status/"):
            return httpx.Response(
                200,
                json={
                    "oauth_enabled": True,
                    "grant_type": "authorization_code",
                    "user_token_status": {"status": "valid"},
                },
            )
        if path.startswith("/oauth/authorize/"):
            return httpx.Response(
                302,
                headers={
                    "location": "https://provider.example.test/authorize?response_type=code"
                    "&state=popup.abcdefghijklmnopqrstuvwxyz&redirect_uri=https%3A%2F%2Fstudio.example.test%2Foauth%2Fcallback"
                },
            )
        assert path in {"/gateways/fixed-gateway", "/servers/fixed-server"}
        return httpx.Response(
            200,
            json={
                "id": path.rsplit("/", 1)[1],
                "teamId": "fixed-team",
                "visibility": "public",
                "enabled": True,
                "authType": "oauth",
                "oauthConfig": {
                    "authorization_url": "https://provider.example.test/authorize",
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.contextforge_oauth_callback_url,
                },
            },
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
        transport=httpx.MockTransport(upstream), cookies={"private": "cookie"}
    ) as native:
        app.state.contextforge_admin_client = native
        app.state.contextforge_oauth_client = native
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
            headers={
                "origin": settings.contextforge_oauth_studio_origin,
                "authorization": "Bearer caller-token",
                "x-contextforge-account-email": "forged@example.test",
            },
        ) as client:
            path = "/api/me/mcp/github/discover"
            assert (await client.post(path, json={"gateway_id": "other"})).status_code == 422
            assert not requests
            assert (await client.get("/api/me/mcp/catalog")).json()[0]["can_discover"] is True
            response = await client.post(path, json={})
            assert response.status_code == 200 and "discovered_at" in response.json()
            assert response.headers["cache-control"] == "no-store"
            assert (await client.post("/api/me/mcp/github/connect", json={})).status_code == 200
            assert (await client.get("/api/me/mcp/github/status")).json()["status"] == "connected"
            for upstream_status, expected in [(409, 409), (429, 429), (200, 502)]:
                native_status = upstream_status
                result["success"] = False
                assert (await client.post(path, json={})).status_code == expected
            result.update(success=True, validation_errors=["private token"])
            assert (await client.post(path, json={})).status_code == 502
            requests.clear()
            (data / "operator_subject").unlink()
            assert (await client.get("/api/me/mcp/catalog")).json()[0]["can_discover"] is False
            assert (await client.post(path, json={})).status_code == 403 and not requests
            (data / "operator_subject").write_text("bound-subject")
            principal = StudioPrincipal(
                "other-subject", principal.roles, principal.agentgateway_roles, principal.profile
            )
            assert (await client.post(path, json={})).status_code == 403 and not requests
            assert (
                await client.post("/api/me/mcp/github/connect", json={})
            ).status_code == 403 and not requests
            (data / "publication.json").write_text("invalid")
            assert (await client.get("/api/me/mcp/github/publication")).json()[
                "state"
            ] == "unavailable"
            assert "private token" not in caplog.text and "caller-token" not in caplog.text
