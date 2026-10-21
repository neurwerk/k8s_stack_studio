"""Caller-scoped MCP discovery and fixed checks through the normal policy gateway."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from urllib.parse import unquote_to_bytes, urlsplit

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult, TextContent, Tool

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.gateway import gateway_catalog
from k8s_stack_studio.lib.gateway_files import GatewayUnavailableError
from k8s_stack_studio.models.mcp import McpCheck, McpCheckResult, McpRegistration, McpTool

_in_flight = asyncio.Semaphore(4)
_logger = logging.getLogger(__name__)
_ENDPOINT_UNAVAILABLE = "MCP gateway endpoint is unavailable."


class McpGatewayError(Exception):
    """A safe failure message with optional HTTP status and retry time."""

    def __init__(
        self,
        message: str = "MCP request failed. Try again.",
        *,
        status: int = 502,
        retry_after: int | None = None,
    ) -> None:
        """Keep upstream response bodies and credentials out of exceptions."""
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _catalog_path(public_url: str) -> str:
    """Reject path reinterpretation before any HTTP URL normalization or decoding."""
    if any(ord(char) < 32 or ord(char) == 127 or char in "\\?#" for char in public_url):
        raise McpGatewayError(_ENDPOINT_UNAVAILABLE, status=503)
    path = urlsplit(public_url).path
    if not path.startswith("/") or path.startswith("//") or re.search(r"%(?![0-9a-fA-F]{2})", path):
        raise McpGatewayError(_ENDPOINT_UNAVAILABLE, status=503)
    for segment in path.split("/"):
        decoded = unquote_to_bytes(segment)
        # Encoded percent signs could hide separators or traversal on a later decode.
        if decoded in {b".", b".."} or any(
            byte < 32 or byte == 127 or byte in b"/\\%?#" for byte in decoded
        ):
            raise McpGatewayError(_ENDPOINT_UNAVAILABLE, status=503)
    return path


def _gateway_url(settings: Settings, item: McpRegistration) -> httpx2.URL:
    """Use only an owned catalog path on the chart's fixed internal transport origin."""
    try:
        catalog = gateway_catalog(settings)
    except GatewayUnavailableError:
        raise McpGatewayError(_ENDPOINT_UNAVAILABLE, status=503) from None
    routes = [
        route
        for entry in catalog.mcp_servers
        for destination in entry.destinations
        if destination.kind == "mcp" and destination.id == item.id
        for route in entry.routes
        if route.id in destination.endpoint_ids and route.entry_mode == "api"
    ]
    if (
        len(routes) != 1
        or not settings.mcp_gateway_url
        or "oidc_bearer" not in routes[0].caller_auth_modes
    ):
        raise McpGatewayError(_ENDPOINT_UNAVAILABLE, status=503)
    path = _catalog_path(routes[0].url)
    # Never urljoin: the public catalog must not select the transport authority.
    return httpx2.URL(settings.mcp_gateway_url + path)


@asynccontextmanager
async def gateway_client(
    settings: Settings, item: McpRegistration, authorization: str
) -> AsyncIterator[Client]:
    """Create a fresh transport per caller; never share credentials, cookies or SDK caches."""
    url = _gateway_url(settings, item)
    rejection: McpGatewayError | None = None
    stage = "initialize"

    async def guard(request: httpx2.Request) -> None:
        if request.url != url or request.method != "POST":
            raise McpGatewayError
        request.headers.pop("cookie", None)

    async def response_status(response: httpx2.Response) -> None:
        nonlocal rejection
        if response.status_code in {401, 403}:
            rejection = McpGatewayError(
                "Gateway access denied. Sign in again or check your permissions.", status=403
            )
        elif response.status_code == 429:
            value = response.headers.get("retry-after", "60")
            seconds = min(3600, max(1, int(value))) if value.isdigit() else 60
            rejection = McpGatewayError(
                "MCP checks are temporarily rate limited.", status=429, retry_after=seconds
            )

    try:
        async with (
            asyncio.timeout(45),
            _in_flight,
            httpx2.AsyncClient(
                headers={"Authorization": authorization},
                trust_env=False,
                follow_redirects=False,
                timeout=30,
                event_hooks={"request": [guard], "response": [response_status]},
            ) as http,
        ):
            transport = streamable_http_client(str(url), http_client=http, terminate_on_close=False)
            async with Client(
                transport, mode="auto", cache=None, read_timeout_seconds=30
            ) as client:
                stage = "request"
                yield client
    except Exception as exc:  # noqa: BLE001 -- SDK task groups wrap transport/protocol errors.
        error = rejection or (exc if isinstance(exc, McpGatewayError) else McpGatewayError())
        # Log only fixed stages, operator IDs and error types, never exception text,
        # credentials, request arguments, tool results or a caller's identity.
        _logger.warning(
            "MCP request failed: integration=%s stage=%s status=%s error_type=%s",
            item.id,
            stage,
            error.status,
            type(exc).__name__,
        )
        raise error from None


async def _tools(client: Client) -> dict[str, Tool]:
    tools: dict[str, Tool] = {}
    cursor: str | None = None
    for _ in range(10):
        page = await client.list_tools(cursor=cursor)
        for tool in page.tools:
            if tool.name in tools or len(tools) >= 100:
                raise McpGatewayError
            tools[tool.name] = tool
        cursor = page.next_cursor
        if not cursor:
            return tools
    raise McpGatewayError


async def available_tools(client: Client, item: McpRegistration) -> list[McpTool]:
    """Intersect current gateway discovery with the setup-verified approval mapping."""
    tools = await _tools(client)
    return [
        McpTool(
            name=name,
            description=(tools[wire_name].description or "")[:20000],
            checks={str(i): check for i, check in enumerate(item.checks) if check.tool == name},
        )
        for name, wire_name in item.tool_names.items()
        if wire_name in tools
    ]


def _display_value(result: CallToolResult, check: McpCheck) -> str | None:
    if not check.display or result.is_error:
        return None
    value: object = result.structured_content
    if value is None:
        texts = [block.text for block in result.content if isinstance(block, TextContent)]
        if len(texts) != 1:
            return None
        try:
            value = json.loads(texts[0])
        except ValueError:
            return None
    for part in check.display.field.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    if isinstance(value, str | int | float | bool):
        return str(value)[:256]
    return None


async def run_check(client: Client, item: McpRegistration, check: McpCheck) -> McpCheckResult:
    """Refresh discovery, then run precisely the configured tool and arguments once."""
    tools = await _tools(client)
    wire_name = item.tool_names.get(check.tool, "")
    if wire_name not in tools:
        raise McpGatewayError
    # The session uses the schema learned above. Advanced multi-round-trip workflows
    # stay unsupported; no automatic second invocation or provider-specific mapping.
    result = await client.session.call_tool(wire_name, arguments=check.arguments)
    if not isinstance(result, CallToolResult):
        raise McpGatewayError
    text = "\n".join(block.text for block in result.content if isinstance(block, TextContent))
    if not text and result.structured_content is not None:
        text = json.dumps(result.structured_content, ensure_ascii=False, indent=2)
    if len(text) > 16384:
        text = text[:16384] + "\n[Result shortened]"
    return McpCheckResult(
        status="failed" if result.is_error else "passed",
        checked_at=datetime.now(UTC),
        result=text,
        display_label=check.display.label if check.display else None,
        display_value=_display_value(result, check),
    )
