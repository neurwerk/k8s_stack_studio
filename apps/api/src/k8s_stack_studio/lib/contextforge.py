"""Native provisioning with an explicit service identity, never a user's OAuth identity."""

from __future__ import annotations

import secrets
from typing import cast
from urllib.parse import quote

import httpx

from k8s_stack_studio.config.settings import Settings

INVOCATION_PERMISSIONS = frozenset(
    {
        "tools.read",
        "tools.execute",
        "servers.read",
        "servers.use",
        "gateways.read",
    }
)
PROVISIONING_PERMISSIONS = frozenset(
    {"admin.user_management", "teams.read", "teams.manage_members"}
)


class ContextForgeAccountError(Exception):
    """Native account provisioning failed; upstream content must stay private."""


class ContextForgeRateLimitError(ContextForgeAccountError):
    """Carry only a bounded retry time, never the native error body."""

    def __init__(self, retry_after: str) -> None:
        """Normalize the native Retry-After seconds for the UI."""
        self.retry_after = min(3600, max(1, int(retry_after))) if retry_after.isdigit() else 60
        super().__init__("Connection checks are temporarily rate limited")


class ContextForgeAccountMissingError(ContextForgeAccountError):
    """No personal native account exists yet; connecting can prepare one."""


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ContextForgeAccountError
    return cast("dict[str, object]", value)


class ContextForgeAccountClient:
    """Use released native account, membership and role APIs with operator credentials."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        """Store fixed operator configuration and an isolated HTTP client."""
        self.settings = settings
        self.client = client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
        allow: tuple[int, ...] = (),
    ) -> httpx.Response:
        headers = (
            {"x-contextforge-account-email": self.settings.contextforge_service_account_email}
            if self.settings.contextforge_service_auth_mode == "trusted-proxy"
            else {
                "Authorization": "Bearer "
                + self.settings.contextforge_service_token.get_secret_value()
            }
        )
        # Do not merge client/caller cookies or credentials. Proxy mode deliberately
        # asserts only the fixed service identity; native RBAC does not validate JWTs here.
        request = httpx.Request(
            method,
            self.settings.contextforge_url.rstrip("/") + path,
            headers=headers,
            json=payload,
            params=params,
        )
        try:
            result = await self.client.send(request, auth=None, follow_redirects=False)
        except httpx.HTTPError:
            raise ContextForgeAccountError from None
        if result.status_code == 429:
            raise ContextForgeRateLimitError(result.headers.get("retry-after", "60"))
        if result.status_code not in allow and not 200 <= result.status_code < 300:
            raise ContextForgeAccountError
        return result

    @staticmethod
    def _json(result: httpx.Response) -> object:
        try:
            return result.json()
        except ValueError:
            raise ContextForgeAccountError from None

    @staticmethod
    def _check_user(value: object, email: str) -> dict[str, object]:
        user = _object(value)
        if user.get("email") != email or user.get("is_admin") is not False:
            raise ContextForgeAccountError
        if user.get("email_verified") is not True:
            raise ContextForgeAccountError
        return user

    async def _check_configuration(self) -> None:
        if self.settings.contextforge_service_auth_mode == "trusted-proxy":
            await self._check_service_account()
        team = _object(
            self._json(await self._request("GET", f"/teams/{self.settings.contextforge_team_id}"))
        )
        if (
            team.get("id") != self.settings.contextforge_team_id
            or team.get("is_active") is not True
            or team.get("is_personal") is not False
        ):
            raise ContextForgeAccountError
        for role_id, scope, permissions in (
            (self.settings.contextforge_global_role_id, "global", frozenset()),
            (self.settings.contextforge_team_role_id, "team", INVOCATION_PERMISSIONS),
        ):
            role = _object(self._json(await self._request("GET", f"/rbac/roles/{role_id}")))
            actual_permissions = role.get("permissions")
            if (
                role.get("id") != role_id
                or role.get("scope") != scope
                or role.get("is_active") is not True
                or role.get("inherits_from") is not None
                or not isinstance(actual_permissions, list)
                or not all(isinstance(item, str) for item in actual_permissions)
                or set(actual_permissions) != permissions
            ):
                raise ContextForgeAccountError

    async def _check_service_account(self) -> None:
        # Native proxy RBAC does not itself require active/verified non-admin users.
        # Check these explicitly before any user provisioning or OAuth admission.
        email = self.settings.contextforge_service_account_email
        path = f"/auth/email/admin/users/{quote(email, safe='')}"
        user = self._check_user(self._json(await self._request("GET", path)), email)
        if user.get("is_active") is not True:
            raise ContextForgeAccountError
        roles = self._json(await self._request("GET", f"/rbac/users/{quote(email, safe='')}/roles"))
        if not isinstance(roles, list) or not roles or len(roles) > 10:
            raise ContextForgeAccountError
        permissions: set[str] = set()
        for value in roles:
            assignment = _object(value)
            role_id = assignment.get("role_id")
            if (
                not isinstance(role_id, str)
                or assignment.get("user_email") != email
                or assignment.get("is_active") is not True
                or assignment.get("expires_at") is not None
                or (assignment.get("scope"), assignment.get("scope_id"))
                not in {
                    ("global", None),
                    ("team", self.settings.contextforge_team_id),
                }
            ):
                raise ContextForgeAccountError
            role = _object(
                self._json(await self._request("GET", f"/rbac/roles/{quote(role_id, safe='')}"))
            )
            actual = role.get("permissions")
            if (
                role.get("id") != role_id
                or role.get("scope") != assignment.get("scope")
                or role.get("is_active") is not True
                or role.get("inherits_from") is not None
                or not isinstance(actual, list)
                or not all(isinstance(item, str) for item in actual)
            ):
                raise ContextForgeAccountError
            permissions.update(cast("list[str]", actual))
        if permissions != PROVISIONING_PERMISSIONS:
            raise ContextForgeAccountError
        await self._ensure_membership(email, created=False, expected_role="owner")

    async def _roles(self, email: str) -> set[str]:
        result = self._json(
            await self._request("GET", f"/rbac/users/{quote(email, safe='')}/roles")
        )
        if not isinstance(result, list):
            raise ContextForgeAccountError
        expected = {
            self.settings.contextforge_global_role_id: ("global", None),
            self.settings.contextforge_team_role_id: ("team", self.settings.contextforge_team_id),
        }
        found: set[str] = set()
        for value in result:
            role = _object(value)
            role_id = role.get("role_id")
            if (
                not isinstance(role_id, str)
                or role_id not in expected
                or role.get("user_email") != email
                or role.get("is_active") is not True
                or (role.get("scope"), role.get("scope_id")) != expected[role_id]
                or role.get("expires_at") is not None
            ):
                raise ContextForgeAccountError
            found.add(role_id)
        return found

    def _check_membership(
        self, value: object, email: str, *, expected_role: str = "member"
    ) -> None:
        member = _object(value)
        if (
            member.get("user_email") != email
            or member.get("team_id") != self.settings.contextforge_team_id
            or member.get("role") != expected_role
            or member.get("is_active") is not True
        ):
            raise ContextForgeAccountError

    async def _ensure_membership(
        self, email: str, *, created: bool, expected_role: str = "member"
    ) -> None:
        path = f"/teams/{self.settings.contextforge_team_id}/members"
        if created:
            result = await self._request(
                "POST", path, payload={"email": email, "role": "member"}, allow=(409,)
            )
            if result.status_code != 409:
                self._check_membership(self._json(result), email)
                return
        # The native API has no per-member GET. Bound existing-membership lookup.
        # An absent result may mean revoked membership, so never POST for an existing account.
        params = {"limit": "100", "include_pagination": "true"}
        for _ in range(10):
            page = _object(self._json(await self._request("GET", path, params=params)))
            members = page.get("members")
            if not isinstance(members, list):
                raise ContextForgeAccountError
            for value in members:
                if _object(value).get("user_email") == email:
                    self._check_membership(value, email, expected_role=expected_role)
                    return
            cursor = page.get("nextCursor")
            if not isinstance(cursor, str) or not cursor:
                break
            params["cursor"] = cursor
        raise ContextForgeAccountError

    async def check_account(self, email: str) -> None:
        """Check an existing account read-only; a status lookup must never restore access."""
        await self._check_configuration()
        path = f"/auth/email/admin/users/{quote(email, safe='')}"
        result = await self._request("GET", path, allow=(404,))
        if result.status_code == 404:
            raise ContextForgeAccountMissingError
        user = self._check_user(self._json(result), email)
        if user.get("is_active") is not True or await self._roles(email) != {
            self.settings.contextforge_global_role_id,
            self.settings.contextforge_team_role_id,
        }:
            raise ContextForgeAccountError
        await self._ensure_membership(email, created=False)

    async def prepare_account(self, email: str) -> None:
        """Prepare only this verified email; never reactivate an existing disabled account."""
        await self._check_configuration()
        path = f"/auth/email/admin/users/{quote(email, safe='')}"
        result = await self._request("GET", path, allow=(404,))
        created = False
        if result.status_code == 404:
            payload: dict[str, object] = {
                "email": email,
                "password": "Aa1!" + secrets.token_urlsafe(48),
                "is_admin": False,
                "is_active": False,
                "password_change_required": False,
            }
            try:
                result = await self._request(
                    "POST", "/auth/email/admin/users", payload=payload, allow=(409,)
                )
            finally:
                payload.clear()  # No credential cache, external store, browser response or log.
            created = result.status_code != 409
            if not created:
                result = await self._request("GET", path)
        user = self._check_user(self._json(result), email)
        # New accounts must still be inactive; existing accounts must already be active.
        if user.get("is_active") is not (not created):
            raise ContextForgeAccountError
        expected_roles = {
            self.settings.contextforge_global_role_id,
            self.settings.contextforge_team_role_id,
        }
        initial_roles = await self._roles(email)  # Refuse unrelated/operator grants.
        if not created and initial_roles != expected_roles:
            # Missing assignments may be deliberately revoked; require operator repair.
            raise ContextForgeAccountError
        await self._ensure_membership(email, created=created)
        if not created:
            return
        found = await self._roles(email)
        for role_id, scope, scope_id in (
            (self.settings.contextforge_global_role_id, "global", None),
            (self.settings.contextforge_team_role_id, "team", self.settings.contextforge_team_id),
        ):
            if role_id not in found:
                await self._request(
                    "POST",
                    f"/rbac/users/{quote(email, safe='')}/roles",
                    payload={
                        "role_id": role_id,
                        "scope": scope,
                        "scope_id": scope_id,
                    },
                )
        if await self._roles(email) != expected_roles:
            raise ContextForgeAccountError
        result = await self._request("PATCH", path, payload={"is_active": True})
        if self._check_user(self._json(result), email).get("is_active") is not True:
            raise ContextForgeAccountError
