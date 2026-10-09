"""Allowlisted native publication; the fixed service identity owns virtual servers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from k8s_stack_studio.lib.contextforge import ContextForgeAccountClient, _object
from k8s_stack_studio.lib.mcp_credentials import McpSetupError
from k8s_stack_studio.models.mcp import McpRegistration


class McpNativeSetup(ContextForgeAccountClient):
    """No general native API proxy, credentials, arbitrary IDs or user-selected URLs."""

    async def server(self, item: McpRegistration) -> dict[str, object]:
        """Verify ownership and the fixed gateway binding before reading or publishing."""
        row = _object(self._json(await self._request("GET", f"/servers/{item.server_id}")))
        if (
            row.get("id") != item.server_id
            or row.get("ownerEmail") != self.settings.contextforge_service_account_email
            or row.get("teamId") != self.settings.contextforge_team_id
            or row.get("visibility") != "public"
            or row.get("enabled") is not True
            or row.get("oauthEnabled") is not False
            or row.get("associatedResources") != []
            or row.get("associatedPrompts") != []
            or row.get("associatedA2aAgents") != []
            or not str(row.get("description", "")).endswith("/studio-v1/" + item.gateway_id)
        ):
            raise McpSetupError("native-ownership-conflict")
        return row

    async def tools(self, item: McpRegistration) -> dict[str, dict[str, str]]:
        """List all discovered tools for one chart-selected upstream, never other gateways."""
        if not item.gateway_id:
            raise McpSetupError("bootstrap-unavailable")
        await self.server(item)
        gateway = _object(self._json(await self._request("GET", f"/gateways/{item.gateway_id}")))
        if (
            gateway.get("teamId") != self.settings.contextforge_team_id
            or gateway.get("id") != item.gateway_id
            or gateway.get("enabled") is not True
            or gateway.get("url") != (item.native_url or item.upstream_url)
            or gateway.get("visibility") != "public"
        ):
            raise McpSetupError("native-ownership-conflict")
        value = self._json(
            await self._request(
                "GET",
                "/tools",
                params={
                    "gateway_id": item.gateway_id,
                    "include_inactive": "false",
                    "limit": "0",
                },
            )
        )
        if not isinstance(value, list) or len(value) > 500:
            raise McpSetupError("invalid-native-tools")
        tools: dict[str, dict[str, str]] = {}
        for entry in value:
            row = _object(entry)
            name, identity, wire = row.get("originalName"), row.get("id"), row.get("name")
            if (
                row.get("gatewayId") != item.gateway_id
                or row.get("teamId") != self.settings.contextforge_team_id
                or row.get("integrationType") != "MCP"
                or row.get("enabled") is not True
                or not all(
                    isinstance(field, str) and 0 < len(field) <= 200
                    for field in (name, identity, wire)
                )
                or name in tools
                or any(
                    tool["id"] == identity or tool["wire"] == item.id + "_" + str(wire)
                    for tool in tools.values()
                )
            ):
                raise McpSetupError("invalid-native-tools")
            tools[cast("str", name)] = {
                "id": cast("str", identity),
                "wire": item.id + "_" + cast("str", wire),
                "description": str(row.get("description") or "")[:20000],
            }
        return tools

    async def publish(
        self,
        item: McpRegistration,
        names: list[str],
        *,
        before_write: Callable[[], Awaitable[None]] | None = None,
    ) -> dict[str, str]:
        """Write exactly the selected native membership and verify its readback."""
        await self._check_service_account()
        await self.server(item)
        tools = await self.tools(item) if names else {}
        if len(names) != len(set(names)) or not set(names) <= set(tools):
            raise McpSetupError("tools-changed-refresh-required")
        desired = sorted(tools[name]["id"] for name in names)
        if before_write:
            await before_write()
        await self._request(
            "PUT", f"/servers/{item.server_id}", payload={"associated_tools": desired}
        )
        actual = await self.server(item)
        actual_ids = actual.get("associatedToolIds")
        if (
            not isinstance(actual_ids, list)
            or not all(isinstance(value, str) for value in actual_ids)
            or sorted(actual_ids) != desired
        ):
            raise McpSetupError("publication-unconfirmed")
        return {name: tools[name]["wire"] for name in names}
