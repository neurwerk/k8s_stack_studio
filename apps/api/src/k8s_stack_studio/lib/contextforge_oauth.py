"""Pinned native OAuth via trusted user proxy identity, never the admin service token."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

import httpx

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.contextforge import (
    ContextForgeAccountError,
    ContextForgeRateLimitError,
    _object,
)
from k8s_stack_studio.models.mcp import (
    ConnectionStatus,
    McpConnectionStatus,
    McpRegistration,
    https_origin,
)


def _https_url(value: object) -> str:
    if not isinstance(value, str):
        raise ContextForgeAccountError
    try:
        url = urlsplit(value)
        _ = url.port
        if (
            url.scheme == "https"
            and url.hostname
            and url.username is None
            and url.password is None
            and not url.query
            and not url.fragment
            and url.geturl() == value
            and not any(character.isspace() or character == "\\" for character in value)
        ):
            return value
    except ValueError:
        pass
    raise ContextForgeAccountError


def _origin(value: str) -> str:
    return https_origin(value)


class ContextForgeOAuthClient:
    """Expose only allowlisted native OAuth metadata for approved catalog mappings."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient, email: str) -> None:
        """Use a dedicated transport with server-derived identity only."""
        self.settings = settings
        self.client = client
        self.email = email

    async def _get(self, path: str, *, popup: bool = False) -> httpx.Response:
        # Build a fresh request: do not merge client cookies, auth or caller headers.
        request = httpx.Request(
            "GET",
            self.settings.contextforge_url.rstrip("/") + path,
            headers={"x-contextforge-account-email": self.email},
            params={"popup": "true"} if popup else None,
        )
        try:
            response = await self.client.send(request, auth=None, follow_redirects=False)
        except httpx.HTTPError:
            raise ContextForgeAccountError from None
        if response.status_code == 429:
            raise ContextForgeRateLimitError(response.headers.get("retry-after", "60"))
        if response.status_code not in ((302, 307) if popup else (200,)):
            raise ContextForgeAccountError
        return response

    async def _json(self, path: str) -> dict[str, object]:
        response = await self._get(path)
        try:
            return _object(response.json())
        except ValueError:
            raise ContextForgeAccountError from None

    async def check_registration(self, item: McpRegistration) -> dict[str, object]:
        """Require fixed-team ownership and native public API visibility under proxy auth.

        In v1.0.11 proxy auth omits token_teams; OAuth scope checks therefore deny
        team/private gateways. Public here is native visibility, not public ingress.
        Network isolation and platform admission are mandatory runtime prerequisites.
        """
        gateway = await self._json(f"/gateways/{item.gateway_id}")
        server = await self._json(f"/servers/{item.server_id}")
        for value, expected_id in ((gateway, item.gateway_id), (server, item.server_id)):
            if (
                value.get("id") != expected_id
                or value.get("teamId") != self.settings.contextforge_team_id
                or value.get("visibility") != "public"
                or value.get("enabled") is not True
            ):
                raise ContextForgeAccountError
        config = _object(gateway.get("oauthConfig"))
        authorization_url = _https_url(config.get("authorization_url"))
        if (
            gateway.get("authType") != "oauth"
            or config.get("grant_type") != "authorization_code"
            or _origin(authorization_url) != item.oauth_authorization_origin
            or config.get("redirect_uri") != self.settings.contextforge_oauth_callback_url
            or gateway.get("authValue")
            or gateway.get("authHeaders")
            or gateway.get("passthroughHeaders")
        ):
            raise ContextForgeAccountError
        return config

    async def status(self, item: McpRegistration) -> McpConnectionStatus:
        """Do not confuse expiration or lookup failure with a permanently missing token."""
        await self.check_registration(item)
        payload = await self._json(f"/oauth/status/{item.gateway_id}")
        if (
            payload.get("oauth_enabled") is not True
            or payload.get("grant_type") != "authorization_code"
        ):
            raise ContextForgeAccountError
        info = _object(payload.get("user_token_status"))
        statuses: dict[str, ConnectionStatus] = {
            "valid": "connected",
            "near_expiry": "connected",
            "expired": "refresh pending",
            "missing": "connect required",
        }
        return McpConnectionStatus(
            status=statuses.get(str(info.get("status")), "status unavailable")
        )

    async def authorize(self, item: McpRegistration) -> str:
        """Return an approved native popup URL; native owns PKCE and token exchange."""
        config = await self.check_registration(item)
        response = await self._get(f"/oauth/authorize/{item.gateway_id}", popup=True)
        location = response.headers.get("location", "")
        try:
            url = urlsplit(location)
            pairs = parse_qsl(url.query, strict_parsing=True)
        except ValueError:
            raise ContextForgeAccountError from None
        params = dict(pairs)
        if (
            len(location) > 8192
            or url._replace(query="").geturl() != config["authorization_url"]
            or len(params) != len(pairs)
            or not set(params)
            <= {
                "response_type",
                "client_id",
                "redirect_uri",
                "state",
                "code_challenge",
                "code_challenge_method",
                "scope",
                "resource",
                "audience",
            }
            or params.get("response_type") != "code"
            or params.get("redirect_uri") != self.settings.contextforge_oauth_callback_url
            or not re.fullmatch(r"popup\.[A-Za-z0-9_-]{20,512}", params.get("state", ""))
        ):
            raise ContextForgeAccountError
        return location

    async def discover(self, item: McpRegistration) -> None:
        """Refresh only the approved gateway using this caller's native saved token."""
        if item.authentication_model == "individual-authentication":
            await self.check_registration(item)
        elif not self.settings.mcp_setup_enabled:
            raise ContextForgeAccountError
        request = httpx.Request(
            "POST",
            self.settings.contextforge_url.rstrip("/")
            + f"/gateways/{item.gateway_id}/tools/refresh",
            headers={"x-contextforge-account-email": self.email},
            params={"include_resources": "false", "include_prompts": "false"},
        )
        try:
            response = await self.client.send(request, auth=None, follow_redirects=False)
        except httpx.HTTPError:
            raise ContextForgeAccountError from None
        if response.status_code == 429:
            raise ContextForgeRateLimitError(response.headers.get("retry-after", "60"))
        if response.status_code == 409:
            raise ContextForgeDiscoveryBusyError
        if response.status_code != 200:
            raise ContextForgeAccountError
        try:
            value = _object(response.json())
        except ValueError:
            raise ContextForgeAccountError from None
        if (
            value.get("gatewayId") != item.gateway_id
            or value.get("success") is not True
            or value.get("error") is not None
            or value.get("validationErrors") != []
        ):
            raise ContextForgeAccountError


class ContextForgeDiscoveryBusyError(ContextForgeAccountError):
    """Another refresh is already running for this integration."""
