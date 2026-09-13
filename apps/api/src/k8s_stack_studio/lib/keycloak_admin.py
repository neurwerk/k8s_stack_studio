"""Keycloak Admin REST API client (delegated user token).

Wraps the Keycloak Admin API endpoints needed for the user control pages:
listing users, fetching a user by ID, and listing public OIDC clients.

Every request forwards the calling **user's own bearer token** rather than
using a service-account client_credentials grant.  The user must therefore
have the necessary ``realm-management`` roles (e.g. ``view-users``,
``query-users``) in their JWT.

Uses the shared httpx.AsyncClient from the app lifespan for connection pooling.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from k8s_stack_studio.config.settings import Settings

_logger = logging.getLogger(__name__)


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

    async def list_public_clients(self, user_token: str) -> list[dict[str, Any]]:
        """List all public OIDC clients in the realm.

        Keycloak Admin API: ``GET /admin/realms/{realm}/clients``
        Returns only clients with ``publicClient: true``.
        """
        result = await self._admin_request("GET", "clients", user_token)
        if not isinstance(result, list):
            return []
        return [c for c in result if c.get("publicClient") is True]
