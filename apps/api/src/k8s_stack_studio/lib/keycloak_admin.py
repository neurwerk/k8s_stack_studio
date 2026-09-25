"""Keycloak Admin REST API client (delegated user token).

Wraps the Keycloak Admin API endpoints needed for read-only user, group, role,
and client access views.

Every request forwards the calling **user's own bearer token** rather than
using a service-account client_credentials grant.  The user must therefore
have the necessary ``realm-management`` roles (e.g. ``view-users``,
``query-users``) in their JWT.

Uses the shared httpx.AsyncClient from the app lifespan for connection pooling.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import quote

import httpx

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.models.admin import (
    AdminClient,
    AdminClientAccess,
    AdminClientPage,
    AdminClientRoles,
    AdminGroup,
    AdminGroupDetail,
    AdminGroupPage,
    AdminRole,
    AdminRoleMappings,
    AdminRolePage,
    AdminUserAccess,
    AdminUserSummary,
    UserGroups,
)

_logger = logging.getLogger(__name__)


class InvalidKeycloakResponseError(ValueError):
    """Indicate that Keycloak returned an unexpected response shape."""


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidKeycloakResponseError
    return cast("dict[str, Any]", value)


def _items(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise InvalidKeycloakResponseError
    return value


def _text(value: object, field: str) -> str:
    item = _object(value).get(field)
    if not isinstance(item, str) or not item:
        raise InvalidKeycloakResponseError
    return item


def _optional_text(value: object, field: str) -> str:
    item = _object(value).get(field)
    return item if isinstance(item, str) else ""


def _role(value: object) -> AdminRole:
    item = _object(value)
    return AdminRole(
        id=_text(item, "id"),
        name=_text(item, "name"),
        description=_optional_text(item, "description"),
        composite=item.get("composite") is True,
    )


def _group(value: object) -> AdminGroup:
    item = _object(value)
    name = _text(item, "name")
    count = item.get("subGroupCount", 0)
    return AdminGroup(
        id=_text(item, "id"),
        name=name,
        path=_optional_text(item, "path") or f"/{name}",
        subgroup_count=count if type(count) is int and count >= 0 else 0,
    )


def _client_info(value: object) -> AdminClient:
    item = _object(value)
    return AdminClient(
        id=_text(item, "id"),
        client_id=_text(item, "clientId"),
        name=_optional_text(item, "name"),
        description=_optional_text(item, "description"),
        enabled=item.get("enabled") is True,
        public=item.get("publicClient") is True,
        service_accounts_enabled=item.get("serviceAccountsEnabled") is True,
        full_scope_allowed=item.get("fullScopeAllowed") is True,
    )


def _user_summary(value: object) -> AdminUserSummary:
    item = _object(value)
    return AdminUserSummary(
        id=_text(item, "id"),
        username=_text(item, "username"),
        email=_optional_text(item, "email"),
    )


def _role_mappings(value: object) -> AdminRoleMappings:
    item = _object(value)
    realm = sorted(
        (_role(role) for role in _items(item.get("realmMappings", []))), key=lambda role: role.name
    )
    clients: list[AdminClientRoles] = []
    raw_clients = item.get("clientMappings", {})
    if raw_clients is not None:
        for client_id, mapping_value in _object(raw_clients).items():
            mapping = _object(mapping_value)
            roles = sorted(
                (_role(role) for role in _items(mapping.get("mappings", []))),
                key=lambda role: role.name,
            )
            clients.append(
                AdminClientRoles(
                    id=_text(mapping, "id"),
                    client_id=client_id,
                    roles=roles,
                )
            )
    return AdminRoleMappings(
        realm_roles=realm,
        clients=sorted(clients, key=lambda client: client.client_id),
    )


class KeycloakAdminClient:
    """Minimal client for the Keycloak Admin REST API.

    All public methods require a ``user_token`` — the bearer token of the
    authenticated user making the request.
    """

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        """Store Keycloak connection settings and the shared HTTP client."""
        self._base_url = settings.keycloak_server_url.rstrip("/")
        self._realm = settings.keycloak_realm
        self._client = client

    # ── internal helpers ─────────────────────────────────────────────────────

    async def _admin_request(
        self,
        method: str,
        path: str,
        user_token: str,
        **kwargs: Any,  # noqa: ANN401  # TODO(2026-08): type as Unpack[HttpxKwargs] TypedDict
    ) -> dict[str, Any] | list[Any]:
        """Make an authenticated request to the Keycloak Admin REST API.

        Uses the calling **user's bearer token** for authorization.
        """
        url = f"{self._base_url}/admin/realms/{self._realm}/{path.lstrip('/')}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {user_token}"
        if not self._base_url.startswith("https://"):
            headers["X-Forwarded-Proto"] = "https"

        try:
            resp = await self._client.request(method, url, headers=headers, **kwargs)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            _logger.exception("Keycloak admin request (user token) failed: %s %s", method, url)
            raise RuntimeError(f"Keycloak admin request failed: {e}") from e  # noqa: TRY003  # TODO(2026-08): define KeycloakAdminError in lib/exceptions.py (Phase 3)
        body: dict[str, Any] | list[Any] = resp.json()
        return body

    # ── public API ───────────────────────────────────────────────────────────

    async def get_user(self, user_id: str, user_token: str) -> dict[str, Any]:
        """Fetch a single user by their Keycloak UUID.

        Keycloak Admin API: ``GET /admin/realms/{realm}/users/{id}``
        """
        result = await self._admin_request("GET", f"users/{user_id}", user_token)
        return result if isinstance(result, dict) else {}

    async def list_users(
        self, user_token: str, search: str | None = None, first: int = 0, max_results: int = 25
    ) -> list[dict[str, Any]]:
        """List a page of realm users, optionally filtered by search string.

        Keycloak Admin API: ``GET /admin/realms/{realm}/users``
        """
        params: dict[str, str] = {"first": str(first), "max": str(max_results)}
        if search:
            params["search"] = search
        result = await self._admin_request("GET", "users", user_token, params=params)
        return result if isinstance(result, list) else []

    async def recent_signin(
        self, user_id: str, user_token: str, start: datetime, end: datetime
    ) -> dict[str, str | None]:
        """Return only a successful LOGIN timestamp, never event details.

        Use epoch milliseconds to avoid server-local calendar-day boundaries.
        Missing event access or malformed data must not look like an empty history.
        """
        unavailable = {"status": "unavailable", "timestamp": None}
        try:
            result = await self._admin_request(
                "GET",
                "events",
                user_token,
                params={
                    "user": user_id,
                    "type": "LOGIN",
                    "max": "1",
                    "direction": "desc",
                    "dateFrom": str(int(start.timestamp() * 1000)),
                    "dateTo": str(int(end.timestamp() * 1000)),
                },
                timeout=5,
            )
        except (RuntimeError, ValueError):
            return unavailable
        if not isinstance(result, list) or len(result) > 1:
            return unavailable
        if not result:
            return {"status": "no_record", "timestamp": None}
        event = result[0]
        if not isinstance(event, dict):
            return unavailable
        timestamp = event.get("time")
        if (
            event.get("type") != "LOGIN"
            or event.get("userId") != user_id
            or event.get("error") is not None
            or type(timestamp) is not int
        ):
            return unavailable
        if timestamp > int(end.timestamp() * 1000) or timestamp < 0:
            return unavailable
        if timestamp < int(start.timestamp() * 1000):
            return {"status": "no_record", "timestamp": None}
        instant = datetime.fromtimestamp(timestamp / 1000, tz=UTC)
        return {"status": "recorded", "timestamp": instant.isoformat()}

    async def list_groups(
        self, user_token: str, search: str | None, first: int, max_results: int
    ) -> AdminGroupPage:
        """List a bounded page of root groups."""
        params = {
            "first": str(first),
            "max": str(max_results + 1),
            "briefRepresentation": "true",
            "populateHierarchy": "false",
            "subGroupsCount": "true",
        }
        if search:
            params["search"] = search
        result = _items(await self._admin_request("GET", "groups", user_token, params=params))
        return AdminGroupPage(
            items=[_group(item) for item in result[:max_results]],
            first=first,
            max=max_results,
            has_more=len(result) > max_results,
        )

    async def list_realm_roles(
        self, user_token: str, search: str | None, first: int, max_results: int
    ) -> AdminRolePage:
        """List a bounded page of realm roles."""
        params = {"first": str(first), "max": str(max_results + 1), "briefRepresentation": "false"}
        if search:
            params["search"] = search
        result = _items(await self._admin_request("GET", "roles", user_token, params=params))
        return AdminRolePage(
            items=[_role(item) for item in result[:max_results]],
            first=first,
            max=max_results,
            has_more=len(result) > max_results,
        )

    async def get_user_access(self, user_id: str, user_token: str) -> AdminUserAccess:
        """Read group membership plus direct and effective realm roles."""
        user = quote(user_id, safe="")
        groups_raw, direct_raw, effective_raw = await asyncio.gather(
            self._admin_request(
                "GET",
                f"users/{user}/groups",
                user_token,
                params={"first": "0", "max": "26", "briefRepresentation": "true"},
            ),
            self._admin_request("GET", f"users/{user}/role-mappings", user_token),
            self._admin_request("GET", f"users/{user}/role-mappings/realm/composite", user_token),
        )
        groups = _items(groups_raw)
        return AdminUserAccess(
            groups=[_group(item) for item in groups[:25]],
            groups_truncated=len(groups) > 25,
            direct=_role_mappings(direct_raw),
            effective_realm_roles=sorted(
                (_role(item) for item in _items(effective_raw)), key=lambda role: role.name
            ),
        )

    async def get_own_groups(self, user_token: str) -> UserGroups:
        """Read only the caller's groups from Keycloak's account API.

        The endpoint derives the subject from the forwarded token; Studio never
        accepts a target user ID for this self-service request.
        """
        url = f"{self._base_url}/realms/{self._realm}/account/groups"
        headers = {"Authorization": f"Bearer {user_token}", "Accept": "application/json"}
        if not self._base_url.startswith("https://"):
            headers["X-Forwarded-Proto"] = "https"
        try:
            response = await self._client.get(
                url, headers=headers, params={"briefRepresentation": "true"}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _logger.exception("Keycloak account groups request failed")
            raise RuntimeError("Keycloak account groups request failed") from exc  # noqa: TRY003
        groups = _items(response.json())
        for item in groups[:25]:
            if not _text(item, "path").startswith("/"):
                raise InvalidKeycloakResponseError
        return UserGroups(
            groups=[_group(item) for item in groups[:25]],
            groups_truncated=len(groups) > 25,
        )

    async def get_group_access(self, group_id: str, user_token: str) -> AdminGroupDetail:
        """Read one group, its first members, and its role mappings."""
        group = quote(group_id, safe="")
        info_raw, children_raw, members_raw, direct_raw, effective_raw = await asyncio.gather(
            self._admin_request("GET", f"groups/{group}", user_token),
            self._admin_request(
                "GET", f"groups/{group}/children", user_token, params={"first": "0", "max": "26"}
            ),
            self._admin_request(
                "GET", f"groups/{group}/members", user_token, params={"first": "0", "max": "26"}
            ),
            self._admin_request("GET", f"groups/{group}/role-mappings", user_token),
            self._admin_request("GET", f"groups/{group}/role-mappings/realm/composite", user_token),
        )
        children = _items(children_raw)
        members = _items(members_raw)
        return AdminGroupDetail(
            group=_group(info_raw),
            subgroups=[_group(item) for item in children[:25]],
            subgroups_truncated=len(children) > 25,
            members=[_user_summary(item) for item in members[:25]],
            members_truncated=len(members) > 25,
            direct=_role_mappings(direct_raw),
            effective_realm_roles=sorted(
                (_role(item) for item in _items(effective_raw)), key=lambda role: role.name
            ),
        )

    async def list_clients(self, user_token: str, first: int, max_results: int) -> AdminClientPage:
        """List safe metadata for public and confidential clients."""
        result = _items(
            await self._admin_request(
                "GET",
                "clients",
                user_token,
                params={"first": str(first), "max": str(max_results + 1), "viewableOnly": "true"},
            )
        )
        return AdminClientPage(
            items=[_client_info(item) for item in result[:max_results]],
            first=first,
            max=max_results,
            has_more=len(result) > max_results,
        )

    async def get_client_access(self, client_id: str, user_token: str) -> AdminClientAccess:
        """Read safe client metadata, role definitions, token scope, and service roles."""
        client = quote(client_id, safe="")
        info_raw, roles_raw, scope_raw = await asyncio.gather(
            self._admin_request("GET", f"clients/{client}", user_token),
            self._admin_request(
                "GET",
                f"clients/{client}/roles",
                user_token,
                params={"first": "0", "max": "101", "briefRepresentation": "false"},
            ),
            self._admin_request("GET", f"clients/{client}/scope-mappings", user_token),
        )
        info = _client_info(info_raw)
        roles = _items(roles_raw)
        service_roles: AdminRoleMappings | None = None
        if info.service_accounts_enabled:
            account_raw = await self._admin_request(
                "GET", f"clients/{client}/service-account-user", user_token
            )
            account_id = quote(_text(account_raw, "id"), safe="")
            service_roles = _role_mappings(
                await self._admin_request("GET", f"users/{account_id}/role-mappings", user_token)
            )
        return AdminClientAccess(
            client=info,
            defined_roles=sorted((_role(item) for item in roles[:100]), key=lambda role: role.name),
            roles_truncated=len(roles) > 100,
            token_scope_roles=_role_mappings(scope_raw),
            service_account_roles=service_roles,
        )
