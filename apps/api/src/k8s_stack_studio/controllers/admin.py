"""Admin routes for users and read-only Keycloak access discovery.

Endpoints:
  - GET /api/me                    — current user's JWT claims
  - GET /api/admin/users           — list all Keycloak users (keycloak-admin)
  - GET /api/admin/users/{user_id} — single user detail (self or keycloak-admin)
  - GET /api/admin/clients         — list safe OIDC client metadata (keycloak-admin)
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, TypedDict

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import Field

from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.dependencies import (
    get_current_user_id,
    get_keycloak_admin,
    require_role,
)
from k8s_stack_studio.lib.exceptions import KeycloakAdminRequestError
from k8s_stack_studio.lib.keycloak_admin import KeycloakAdminClient
from k8s_stack_studio.models.admin import (
    AdminClientAccess,
    AdminClientPage,
    AdminGroupDetail,
    AdminGroupPage,
    AdminRolePage,
    AdminUserAccess,
    UserGroups,
)

router = APIRouter(prefix="/api", tags=["admin"])
USER_ID_PATTERN = re.compile(
    r"(?:[0-9a-fA-F]{24}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\Z"
)
USER_SORT_FIELDS = Literal["username", "email", "firstName", "lastName", "status", "recentSignin"]
_USER_CACHE_TTL = 600


class _SigninActivity(TypedDict):
    window_start: datetime
    window_end: datetime
    users: dict[str, dict[str, str | None]]


_user_cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]], _SigninActivity | None]] = {}
_user_cache_lock = asyncio.Lock()


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
    first: int = Query(0, ge=0),
    max_results: int = Query(25, alias="max", ge=1, le=25),
    _: None = Depends(require_role("keycloak-admin")),
    admin: KeycloakAdminClient = Depends(get_keycloak_admin),
) -> list[dict[str, Any]]:
    """List a bounded page of Keycloak users (keycloak-admin role required).

    Forwards the caller's bearer token to the Keycloak Admin API.
    """
    user_token = _extract_bearer_token(request)
    if search and USER_ID_PATTERN.fullmatch(search):
        try:
            user = await admin.get_user(search, user_token)
        except KeycloakAdminRequestError as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
        else:
            return [user] if first == 0 else []
    return await admin.list_users(user_token, search=search, first=first, max_results=max_results)


async def _all_keycloak_users(
    admin: KeycloakAdminClient, token: str, search: str | None
) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    if search and USER_ID_PATTERN.fullmatch(search):
        try:
            return [await admin.get_user(search, token)]
        except KeycloakAdminRequestError as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
    while True:
        batch = await admin.list_users(token, search=search, first=len(users), max_results=100)
        users.extend(batch)
        if len(batch) < 100:
            return users


async def _all_recent_signins(
    admin: KeycloakAdminClient, token: str, users: list[dict[str, Any]]
) -> _SigninActivity:
    end = datetime.now(UTC)
    start = end - timedelta(days=7)
    semaphore = asyncio.Semaphore(4)

    async def lookup(user: dict[str, Any]) -> tuple[str, dict[str, str | None]]:
        async with semaphore:
            user_id = str(user["id"])
            return user_id, await admin.recent_signin(user_id, token, start, end)

    records = await asyncio.gather(*(lookup(user) for user in users))
    return {"window_start": start, "window_end": end, "users": dict(records)}


async def _sorted_user_snapshot(
    admin: KeycloakAdminClient, token: str, search: str | None, with_signins: bool
) -> tuple[list[dict[str, Any]], _SigninActivity | None]:
    cache_key = (hashlib.sha256(token.encode()).hexdigest(), search or "")
    async with _user_cache_lock:
        cached = _user_cache.get(cache_key)
        if cached is not None and time.monotonic() >= cached[0]:
            cached = None
    if cached is None:
        users = await _all_keycloak_users(admin, token, search)
        async with _user_cache_lock:
            cached = _user_cache.get(cache_key)
            if cached is None or time.monotonic() >= cached[0]:
                cached = (time.monotonic() + _USER_CACHE_TTL, users, None)
                _user_cache[cache_key] = cached
            # Keep only a few delegated, short-lived snapshots in process memory.
            for key, entry in list(_user_cache.items()):
                if time.monotonic() >= entry[0]:
                    del _user_cache[key]
            while len(_user_cache) > 8:
                del _user_cache[next(iter(_user_cache))]
    expires, users, activity = cached
    if with_signins and activity is None:
        activity = await _all_recent_signins(admin, token, users)
        async with _user_cache_lock:
            current = _user_cache.get(cache_key)
            if current is not None and current[1] is users:
                if current[2] is None:
                    _user_cache[cache_key] = (expires, users, activity)
                else:
                    activity = current[2]
    return users, activity


def _user_sort_value(
    user: dict[str, Any], sort: USER_SORT_FIELDS, activity: _SigninActivity | None
) -> tuple[bool, str | float]:
    if sort == "recentSignin":
        record = activity["users"].get(user["id"]) if activity else None
        stamp = record.get("timestamp") if record and record["status"] == "recorded" else None
        return (not bool(stamp), datetime.fromisoformat(stamp).timestamp() if stamp else 0.0)
    if sort == "status":
        value = f"{user.get('enabled')} {user.get('emailVerified')}"
    else:
        value = user.get(sort) or ""
    return (not bool(value), str(value).casefold())


@router.get("/admin/users/sorted")
async def sorted_users(
    request: Request,
    sort: USER_SORT_FIELDS,
    direction: Literal["asc", "desc"] = "asc",
    search: str | None = None,
    first: int = Query(0, ge=0),
    max_results: int = Query(25, alias="max", ge=1, le=25),
    _: None = Depends(require_role("keycloak-admin")),
    admin: KeycloakAdminClient = Depends(get_keycloak_admin),
) -> dict[str, Any]:
    """Sort all matching users before slicing a page; event lookup is only needed for sign-ins."""
    token = _extract_bearer_token(request)
    users, activity = await _sorted_user_snapshot(admin, token, search, sort == "recentSignin")

    def sort_value(user: dict[str, Any]) -> tuple[bool, str | float]:
        return _user_sort_value(user, sort, activity)

    # Missing values always trail recorded values, regardless of direction.
    present = [user for user in users if not sort_value(user)[0]]
    missing = [user for user in users if sort_value(user)[0]]
    ordered = sorted(present, key=sort_value, reverse=direction == "desc") + missing
    page = ordered[first : first + max_results]
    page_activity = (
        {**activity, "users": {user["id"]: activity["users"][user["id"]] for user in page}}
        if activity
        else None
    )
    return {"items": page, "total": len(ordered), "activity": page_activity}


@router.get("/admin/recent-signins")
async def recent_signins(
    request: Request,
    user_ids: list[Annotated[str, Field(min_length=1, max_length=255)]] = Query(
        min_length=1, max_length=25
    ),
    _: None = Depends(require_role("keycloak-admin")),
    admin: KeycloakAdminClient = Depends(get_keycloak_admin),
) -> dict[str, Any]:
    """Read bounded seven-day LOGIN history for the displayed user page."""
    token = _extract_bearer_token(request)
    end = datetime.now(UTC)
    end = end.replace(microsecond=end.microsecond // 1000 * 1000)
    start = end - timedelta(days=7)
    semaphore = asyncio.Semaphore(4)

    async def lookup(user_id: str) -> tuple[str, dict[str, str | None]]:
        async with semaphore:
            return user_id, await admin.recent_signin(user_id, token, start, end)

    records = await asyncio.gather(*(lookup(user_id) for user_id in dict.fromkeys(user_ids)))
    return {"window_start": start, "window_end": end, "users": dict(records)}


# ── GET /api/admin/users/{user_id} ───────────────────────────────────────────


def _principal_to_user_dict(principal: StudioPrincipal) -> dict[str, Any]:
    """Convert the middleware-verified profile claims to Keycloak user data."""
    return {
        "id": principal.subject,
        "username": principal.profile.get("preferred_username", ""),
        "email": principal.profile.get("email", ""),
        "firstName": principal.profile.get("given_name", ""),
        "lastName": principal.profile.get("family_name", ""),
        "enabled": None,  # A previously issued JWT is not current account-state evidence.
        "emailVerified": principal.profile.get("email_verified"),
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
    try:
        return await admin.get_user(user_id, user_token)
    except KeycloakAdminRequestError as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            ) from exc
        raise


# ── GET /api/admin/clients ───────────────────────────────────────────────────


@router.get("/admin/clients")
async def list_clients(
    request: Request,
    first: int = Query(0, ge=0),
    max_results: int = Query(25, alias="max", ge=1, le=25),
    _: None = Depends(require_role("keycloak-admin")),
    admin: KeycloakAdminClient = Depends(get_keycloak_admin),
) -> AdminClientPage:
    """List safe metadata for viewable OIDC clients.

    Forwards the caller's bearer token to the Keycloak Admin API.
    """
    user_token = _extract_bearer_token(request)
    return await admin.list_clients(user_token, first=first, max_results=max_results)


@router.get("/admin/clients/{client_id}/access")
async def get_client_access(
    client_id: str,
    request: Request,
    _: None = Depends(require_role("keycloak-admin")),
    admin: KeycloakAdminClient = Depends(get_keycloak_admin),
) -> AdminClientAccess:
    """Read a client's defined roles, token scope, and service-account roles."""
    return await admin.get_client_access(client_id, _extract_bearer_token(request))


@router.get("/admin/groups")
async def list_groups(
    request: Request,
    search: str | None = Query(None),
    first: int = Query(0, ge=0),
    max_results: int = Query(25, alias="max", ge=1, le=25),
    _: None = Depends(require_role("keycloak-admin")),
    admin: KeycloakAdminClient = Depends(get_keycloak_admin),
) -> AdminGroupPage:
    """List a bounded page of realm groups."""
    return await admin.list_groups(
        _extract_bearer_token(request), search=search, first=first, max_results=max_results
    )


@router.get("/admin/groups/{group_id}")
async def get_group_access(
    group_id: str,
    request: Request,
    _: None = Depends(require_role("keycloak-admin")),
    admin: KeycloakAdminClient = Depends(get_keycloak_admin),
) -> AdminGroupDetail:
    """Read one group's members and role mappings."""
    return await admin.get_group_access(group_id, _extract_bearer_token(request))


@router.get("/admin/roles")
async def list_realm_roles(
    request: Request,
    search: str | None = Query(None),
    first: int = Query(0, ge=0),
    max_results: int = Query(25, alias="max", ge=1, le=25),
    _: None = Depends(require_role("keycloak-admin")),
    admin: KeycloakAdminClient = Depends(get_keycloak_admin),
) -> AdminRolePage:
    """List a bounded page of realm roles."""
    return await admin.list_realm_roles(
        _extract_bearer_token(request), search=search, first=first, max_results=max_results
    )


@router.get("/admin/users/{user_id}/access")
async def get_user_access(
    user_id: str,
    request: Request,
    _: None = Depends(require_role("keycloak-admin")),
    admin: KeycloakAdminClient = Depends(get_keycloak_admin),
) -> AdminUserAccess:
    """Read a user's group membership plus direct and effective roles."""
    return await admin.get_user_access(user_id, _extract_bearer_token(request))


@router.get("/users/me/groups")
async def get_own_groups(
    request: Request,
    _: str = Depends(get_current_user_id),
    admin: KeycloakAdminClient = Depends(get_keycloak_admin),
) -> UserGroups:
    """Read the verified caller's own Keycloak memberships, including LDAP-synced paths."""
    return await admin.get_own_groups(_extract_bearer_token(request))
