"""Keycloak JWT validation middleware for FastAPI.

Uses fastapi-keycloak-middleware to validate JWTs locally via JWKS.
The management app (port 4090) is unauthenticated; this middleware only
applies to the authenticated API port (4010).
"""

# ruff: noqa: TRY003

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, override

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi_keycloak_middleware import (
    KeycloakConfiguration,
    setup_keycloak_middleware,
)
from starlette.authentication import AuthenticationError, BaseUser
from starlette.types import ASGIApp, Receive, Scope, Send

from k8s_stack_studio.config.settings import Settings

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StudioPrincipal(BaseUser):
    """Authenticated Keycloak subject and roles from verified claims."""

    subject: str
    roles: frozenset[str]
    agentgateway_roles: frozenset[str]
    profile: dict[str, str | bool | int]

    @property
    @override
    def is_authenticated(self) -> bool:
        """Identify this principal as authenticated to Starlette."""
        return True

    @property
    @override
    def display_name(self) -> str:
        """Avoid putting profile values into authorization logs or responses."""
        return self.subject

    @property
    @override
    def identity(self) -> str:
        """Return the verified Keycloak subject."""
        return self.subject


async def _map_principal(claims: dict[str, Any]) -> StudioPrincipal:
    """Create the request principal only from middleware-verified token claims."""
    subject = claims.get("sub")
    realm_access = claims.get("realm_access")
    roles = realm_access.get("roles") if isinstance(realm_access, dict) else None
    if not isinstance(subject, str) or not subject or not isinstance(roles, list):
        raise ValueError("verified token is missing subject or realm roles")
    valid_roles = [role for role in roles if isinstance(role, str)]
    if len(valid_roles) != len(roles):
        raise ValueError("verified token contains invalid realm roles")
    profile: dict[str, str | bool | int] = {}
    for name in ("preferred_username", "email", "given_name", "family_name"):
        value = claims.get(name)
        if isinstance(value, str):
            profile[name] = value
    for name in ("email_verified",):
        value = claims.get(name)
        if isinstance(value, bool):
            profile[name] = value
    value = claims.get("iat")
    if isinstance(value, int):
        profile["iat"] = value
    return StudioPrincipal(
        subject=subject,
        roles=frozenset(valid_roles),
        agentgateway_roles=_agentgateway_roles(claims.get("resource_access", {})),
        profile=profile,
    )


def _agentgateway_roles(resource_access: object) -> frozenset[str]:
    """Read AgentGateway client roles from the verified resource-access claim."""
    if not isinstance(resource_access, dict):
        raise TypeError("verified token contains invalid resource access")
    agentgateway_access = resource_access.get("agentgateway", {})
    if not isinstance(agentgateway_access, dict):
        raise TypeError("verified token contains invalid AgentGateway access")
    roles = agentgateway_access.get("roles", [])
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        raise TypeError("verified token contains invalid AgentGateway roles")
    return frozenset(role for role in roles if isinstance(role, str))


class StudioAdmissionMiddleware:
    """Require the Studio application role after Keycloak verifies a request."""

    def __init__(self, app: ASGIApp) -> None:
        """Store the inner ASGI application."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject authenticated callers that lack Studio application admission."""
        if scope["type"] != "http" or scope["path"] == "/api/version":
            await self.app(scope, receive, send)
            return
        if scope["path"].startswith("/api/"):
            principal = scope.get("user")
            if not isinstance(principal, StudioPrincipal):
                response = JSONResponse(status_code=401, content={"detail": "Not authenticated"})
                await response(scope, receive, send)
                return
            if "studio-user" not in principal.roles:
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "Missing required role: studio-user"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def configure_auth(app: FastAPI, settings: Settings) -> None:
    """Install Keycloak middleware and exception handler on the FastAPI app.

    All routes require a valid JWT (public endpoints like /health and
    /metrics are served by the separate management app on port 4090).
    """
    configured = (
        settings.keycloak_server_url and settings.keycloak_realm and settings.keycloak_client_id
    )
    if not configured:
        if not settings.allow_unauthenticated_local:
            raise RuntimeError("Keycloak server URL, realm, and client ID are required")
        _logger.warning(
            "Keycloak middleware is disabled by explicit local-development configuration."
        )
        return

    config = KeycloakConfiguration(
        url=settings.keycloak_server_url,
        realm=settings.keycloak_realm,
        client_id=settings.keycloak_client_id,
        client_secret=settings.keycloak_client_secret or "",
        claims=[
            "sub",
            "realm_access",
            "resource_access",
            "preferred_username",
            "email",
            "given_name",
            "family_name",
            "email_verified",
            "iat",
        ],
        # _map_principal keeps required identity and realm-role claims strict;
        # callers without AgentGateway grants have no resource_access claim.
        reject_on_missing_claim=False,
    )

    # Middleware added later is outermost. Keycloak must run first so admission
    # reads only the verified principal it places in the ASGI scope.
    app.add_middleware(StudioAdmissionMiddleware)
    setup_keycloak_middleware(
        app,
        keycloak_configuration=config,
        exclude_patterns=[r"^/api/version$"],
        user_mapper=_map_principal,
    )

    @app.exception_handler(AuthenticationError)
    async def _auth_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": str(exc)})

    _logger.info(
        "Keycloak auth middleware installed (realm=%s, client=%s)",
        settings.keycloak_realm,
        settings.keycloak_client_id,
    )
