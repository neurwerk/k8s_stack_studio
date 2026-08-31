"""Admin routes — user management and client discovery.

Endpoints:
  - GET /api/me                    — current user's JWT claims
  - GET /api/admin/users           — list all Keycloak users (keycloak-admin)
  - GET /api/admin/users/{user_id} — single user detail (self or keycloak-admin)
  - GET /api/admin/clients         — list public OIDC clients (keycloak-admin)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.dependencies import (
    get_current_user_id,
    get_keycloak_admin,
    require_role,
)
from k8s_stack_studio.lib.keycloak_admin import KeycloakAdminClient

router = APIRouter(prefix="/api", tags=["admin"])


# ── helper: extract bearer token from request ──────────────────────────────


def _extract_bearer_token(request: Request) -> str:
    """Return the raw bearer token from the Authorization header.

    Raises 401 if the header is missing or malformed.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return auth_header.removeprefix("Bearer ").strip()


# ── GET /api/me ──────────────────────────────────────────────────────────────


@router.get("/me")
async def get_my_profile(request: Request) -> dict[str, Any]:
    """Return the current user's JWT claims.

    No special role required — any authenticated user can view their own profile.
    """
    principal = _principal(request)
    identity = {"sub": principal.subject, "realm_access": {"roles": sorted(principal.roles)}}
    return identity | principal.profile


# ── helper: self-or-admin check ──────────────────────────────────────────────


async def _require_self_or_admin(user_id: str, request: Request) -> None:
    """Dependency: allow access if the caller is *user_id* or has keycloak-admin role.

    Must be used as a dependency via ``Depends(_require_self_or_admin)``
    with ``user_id`` as an additional dependency or path param.
    """
    current_user_id = get_current_user_id(request)
    if user_id == current_user_id:
        return
    if "keycloak-admin" not in _principal(request).roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required role: keycloak-admin",
        )


# ── GET /api/admin/users ─────────────────────────────────────────────────────


@router.get("/admin/users")
async def list_users(
    request: Request,
    search: str | None = Query(None, description="Optional search string"),
    _: None = Depends(require_role("keycloak-admin")),
    admin: KeycloakAdminClient = Depends(get_keycloak_admin),
) -> list[dict[str, Any]]:
    """List all Keycloak users (keycloak-admin role required).

    Forwards the caller's bearer token to the Keycloak Admin API.
    """
    user_token = _extract_bearer_token(request)
    return await admin.list_users(user_token, search=search)


# ── GET /api/admin/users/{user_id} ───────────────────────────────────────────


def _principal_to_user_dict(principal: StudioPrincipal) -> dict[str, Any]:
    """Convert the middleware-verified profile claims to Keycloak user data."""
    return {
        "id": principal.subject,
        "username": principal.profile.get("preferred_username", ""),
        "email": principal.profile.get("email", ""),
        "firstName": principal.profile.get("given_name", ""),
        "lastName": principal.profile.get("family_name", ""),
        "enabled": True,  # JWT was issued, so the user is effectively enabled
        "emailVerified": principal.profile.get("email_verified", False),
        "createdTimestamp": principal.profile.get("iat", 0) * 1000,
    }


def _principal(request: Request) -> StudioPrincipal:
    """Return the user established by JWT middleware, never raw token claims."""
    principal = request.scope.get("user")
    if not isinstance(principal, StudioPrincipal):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return principal


@router.get("/admin/users/{user_id}")
async def get_user_detail(
    user_id: str,
    request: Request,
    _: None = Depends(_require_self_or_admin),
    admin: KeycloakAdminClient = Depends(get_keycloak_admin),
) -> dict[str, Any]:
    """Fetch a single user by Keycloak UUID.

    - **Self-view**: returns profile data extracted directly from the JWT
      claims (no Admin API call needed).
    - **Admin view** (keycloak-admin role): calls the Keycloak Admin REST API
      using the **admin's own bearer token**, so no service-account
      credentials are required.
    """
    current_user_id = get_current_user_id(request)

    # Self-view: build the profile from JWT claims — no Admin API call
    if user_id == current_user_id:
        return _principal_to_user_dict(_principal(request))

    # Admin viewing another user: forward the admin's bearer token
    user_token = _extract_bearer_token(request)
    return await admin.get_user(user_id, user_token)


# ── GET /api/admin/clients ───────────────────────────────────────────────────


@router.get("/admin/clients")
async def list_clients(
    request: Request,
    _: None = Depends(require_role("keycloak-admin")),
    admin: KeycloakAdminClient = Depends(get_keycloak_admin),
) -> list[dict[str, Any]]:
    """List all public OIDC clients (keycloak-admin role required).

    Forwards the caller's bearer token to the Keycloak Admin API.
    """
    user_token = _extract_bearer_token(request)
    return await admin.list_public_clients(user_token)
