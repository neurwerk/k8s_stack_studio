"""Tests for auth module (Keycloak OIDC middleware setup)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi_keycloak_middleware.keycloak_backend import KeycloakBackend

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.oauth_callback import router as callback_router
from k8s_stack_studio.lib.auth import _map_principal, configure_auth
from k8s_stack_studio.lib.dependencies import get_settings


@pytest.mark.asyncio
async def test_configure_auth_registers_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only exact GET callback bypasses JWT; other paths remain authenticated."""
    app = FastAPI()
    app.include_router(callback_router)
    app.dependency_overrides[get_settings] = lambda: Settings()
    # Missing-header requests need no real JWKS lookup or Keycloak connection.
    monkeypatch.setattr(KeycloakBackend, "_get_public_key", lambda self: None)
    settings = Settings(
        keycloak_server_url="http://kc:8080",
        keycloak_realm="testrealm",
        keycloak_client_id="testcli",
        keycloak_client_secret="",
    )
    configure_auth(app, settings)
    # configure_auth installs middleware; verify at least one was registered
    assert len(app.user_middleware) >= 1
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://studio.example.test"
    ) as client:
        # Feature-off 404 proves the request reached the real callback, not JWT's 401.
        assert (await client.get("/oauth/callback")).status_code == 404
        for method in ("POST", "PUT", "HEAD", "DELETE"):
            response = await client.request(method, "/oauth/callback")
            assert response.status_code == 405 and response.headers["allow"] == "GET"
        for path in (
            "/api/session",
            "/oauth/callback/",
            "/oauth/callback-extra",
            "/oauth/callback%0A",
        ):
            assert (await client.get(path)).status_code == 401


def test_configure_auth_rejects_missing_production_configuration() -> None:
    """A missing Keycloak configuration must not create an unauthenticated API."""
    with pytest.raises(RuntimeError, match="Keycloak"):
        configure_auth(FastAPI(), Settings())


def test_configure_auth_requires_explicit_local_bypass() -> None:
    """Only an intentional local flag permits unauthenticated development."""
    app = FastAPI()
    configure_auth(app, Settings(allow_unauthenticated_local=True))
    assert not app.user_middleware


@pytest.mark.asyncio
async def test_principal_reads_agentgateway_permissions_from_verified_claims() -> None:
    principal = await _map_principal(
        {
            "sub": "user-1",
            "realm_access": {"roles": ["studio-user"]},
            "resource_access": {
                "agentgateway": {"roles": ["llm:invoke", "model:permitted:invoke"]}
            },
        }
    )

    assert principal.roles == frozenset({"studio-user"})
    assert principal.agentgateway_roles == frozenset({"llm:invoke", "model:permitted:invoke"})
