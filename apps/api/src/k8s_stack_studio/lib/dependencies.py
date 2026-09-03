"""FastAPI dependency injection — wires settings, clients, and services together.

Every dependency is a callable suitable for ``Depends()``.  This is the
single place where concrete instances are created; controllers never call
constructors directly.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, Request, status

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.agentgateway import AgentGatewayClient
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.keycloak_admin import KeycloakAdminClient
from k8s_stack_studio.lib.opensearch import OpenSearchClient
from k8s_stack_studio.lib.pii_engine import PiiEngineClient


@lru_cache
def get_settings() -> Settings:
    """Return the cached Settings singleton (created once per process)."""
    return Settings()


# ── infrastructure clients ───────────────────────────────────────────────────


def get_pii_engine_client(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> PiiEngineClient:
    """Return the dedicated mTLS PII Engine client.

    Human Keycloak authorization is enforced by the controller dependency; the
    incoming bearer token is deliberately not passed to this client.
    """
    client: httpx.AsyncClient = request.app.state.pii_engine_client
    return PiiEngineClient(base_url=settings.pii_engine_url, client=client)


def get_keycloak_admin(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> KeycloakAdminClient:
    """Return a KeycloakAdminClient backed by the shared httpx client."""
    client: httpx.AsyncClient = request.app.state.http_client
    return KeycloakAdminClient(settings=settings, client=client)


def get_opensearch(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> OpenSearchClient:
    """Return an OpenSearchClient backed by its isolated TLS client."""
    client: httpx.AsyncClient = request.app.state.opensearch_client
    return OpenSearchClient(settings=settings, client=client)


def get_agentgateway(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> AgentGatewayClient:
    """Return an AgentGatewayClient backed by its private-network client."""
    client: httpx.AsyncClient = request.app.state.agentgateway_client
    return AgentGatewayClient(settings=settings, client=client)


# ── auth helpers ─────────────────────────────────────────────────────────────


def get_current_user_id(request: Request) -> str:
    """Extract the Keycloak user ID (``sub`` claim) from the validated JWT.

    Raises 401 if the request is not authenticated.
    """
    return get_current_principal(request).subject


def get_current_principal(request: Request) -> StudioPrincipal:
    """Return the Keycloak principal created from verified token claims."""
    principal = request.scope.get("user")
    if not isinstance(principal, StudioPrincipal):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return principal


def require_role(role: str) -> Callable[[Request], None]:
    """Factory that returns a dependency enforcing the given Keycloak realm role.

    Usage::

        @router.get("/admin/users")
        async def list_users(_: None = Depends(require_role("keycloak-admin"))):
            ...
    """

    def _check_role(request: Request) -> None:
        principal = request.scope.get("user")
        if not isinstance(principal, StudioPrincipal):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
        if role not in principal.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required role: {role}",
            )

    return _check_role
