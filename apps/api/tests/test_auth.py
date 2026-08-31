"""Tests for auth module (Keycloak OIDC middleware setup)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.auth import _map_principal, configure_auth


def test_configure_auth_registers_middleware() -> None:
    """configure_auth adds Keycloak middleware without crashing."""
    app = FastAPI()
    settings = Settings(
        keycloak_server_url="http://kc:8080",
        keycloak_realm="testrealm",
        keycloak_client_id="testcli",
        keycloak_client_secret="",
    )
    configure_auth(app, settings)
    # configure_auth installs middleware; verify at least one was registered
    assert len(app.user_middleware) >= 1


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
