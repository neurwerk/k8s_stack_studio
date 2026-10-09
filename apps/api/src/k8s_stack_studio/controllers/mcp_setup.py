"""Protected administrator setup; catalog IDs resolve every destination and secret path."""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from k8s_stack_studio import mcp_store, mcp_worker
from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.mcp import _verified_email
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.contextforge import ContextForgeAccountClient, ContextForgeAccountError
from k8s_stack_studio.lib.contextforge_oauth import ContextForgeOAuthClient
from k8s_stack_studio.lib.dependencies import get_current_principal, get_settings, require_role
from k8s_stack_studio.lib.mcp_credentials import McpCredentials, McpSetupError
from k8s_stack_studio.lib.mcp_native_setup import McpNativeSetup
from k8s_stack_studio.lib.mcp_publication import PublicationUnavailableError, publication_snapshot
from k8s_stack_studio.models.mcp import McpCredential, McpRegistration
from k8s_stack_studio.models.mcp_setup import (
    McpChange,
    McpOperation,
    McpPublish,
    McpSetupStatus,
    McpSetupTool,
)


def _configuration(settings: Settings = Depends(get_settings)) -> Settings:
    if not settings.mcp_setup_enabled:
        raise HTTPException(status_code=404, detail="MCP Setup is not enabled")
    try:
        return publication_snapshot(settings)[0]
    except PublicationUnavailableError:
        raise HTTPException(
            status_code=503, detail="MCP setup configuration is unavailable"
        ) from None


router = APIRouter(
    prefix="/api/admin/mcp",
    tags=["mcp-setup"],
    dependencies=[Depends(require_role("studio-user")), Depends(require_role("mcp-admin"))],
)


def _item(identity: str, settings: Settings) -> McpRegistration:
    item = next((item for item in settings.mcp_catalog if item.id == identity), None)
    if item is None:
        raise HTTPException(status_code=404, detail="MCP server is not installed")
    return item


def _origin(request: Request, settings: Settings) -> None:
    if request.headers.get("origin") != settings.contextforge_oauth_studio_origin:
        raise HTTPException(status_code=403, detail="Approved Studio origin is required")


@router.get("")
async def list_setup(
    request: Request,
    response: Response,
    settings: Settings = Depends(_configuration),
) -> list[McpSetupStatus]:
    """List installed integrations regardless of publication, key or connection state."""
    response.headers["Cache-Control"] = "no-store"
    try:
        states = await mcp_store.setups(settings.notice_dsn)
    except (asyncpg.PostgresError, OSError, TimeoutError):
        raise HTTPException(status_code=503, detail="MCP setup storage is unavailable") from None
    result = []
    for item in settings.mcp_catalog:
        state = states.get(item.id, {})
        result.append(
            McpSetupStatus(
                id=item.id,
                name=item.name,
                url=item.upstream_url,
                credential=item.credential
                or McpCredential(owner="none", required=False, method="none"),
                revision=state.get("revision", 0),
                selected_tools=state.get("selected_tools", []),
                published_tools=list(state.get("published_tools", {})),
                enabled=state.get("enabled", False),
                publication_uncertain=state.get("publication_uncertain", False),
                published_at=state.get("published_at"),
                key_configured=state.get("key_configured", False),
                refreshed_at=state.get("refreshed_at"),
                updated_at=state.get("updated_at"),
                operation=state.get("operation"),
                available=bool(item.gateway_id),
            )
        )
    return result


@router.get("/{identity}/tools")
async def setup_tools(
    identity: str,
    request: Request,
    response: Response,
    settings: Settings = Depends(_configuration),
) -> list[McpSetupTool]:
    """Read native cached definitions; GET never contacts or refreshes a provider."""
    response.headers["Cache-Control"] = "no-store"
    try:
        native = McpNativeSetup(settings, request.app.state.contextforge_admin_client)
        tools = await native.tools(_item(identity, settings))
        return [
            McpSetupTool(name=name, description=tool["description"]) for name, tool in tools.items()
        ]
    except (McpSetupError, ContextForgeAccountError):
        raise HTTPException(status_code=502, detail="MCP tool list is unavailable") from None


async def _begin(
    settings: Settings,
    item: McpRegistration,
    body: McpChange,
    principal: StudioPrincipal,
    kind: str,
    data: dict[str, Any],
    phase: str = "ready",
) -> tuple[McpOperation, bool]:
    try:
        return await mcp_store.begin(
            settings.notice_dsn,
            item.id,
            body.revision,
            body.operation_id,
            kind,
            principal.subject,
            {**data, "binding": mcp_store.binding(item), "revision": body.revision},
            phase=phase,
        )
    except (mcp_store.McpConflictError, asyncpg.UniqueViolationError):
        raise HTTPException(
            status_code=409,
            detail="MCP setup changed or an operation is running. Reload and retry.",
        ) from None
    except (asyncpg.PostgresError, OSError, TimeoutError):
        raise HTTPException(status_code=503, detail="MCP setup storage is unavailable") from None


@router.post("/{identity}/publish", status_code=202)
async def publish(
    identity: str,
    body: McpPublish,
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(_configuration),
) -> McpOperation:
    """Reserve intent, put secret text only in OpenBao, then let the durable worker publish."""
    _origin(request, settings)
    item = _item(identity, settings)
    response.headers["Cache-Control"] = "no-store"
    key = body.api_key.get_secret_value().strip()
    action = "keep" if body.key_action == "replace" and not key else body.key_action
    if len(body.selected_tools) != len(set(body.selected_tools)) or any(
        not name or len(name) > 200 for name in body.selected_tools
    ):
        raise HTTPException(status_code=422, detail="Choose unique discovered tools")
    if action != "keep" and (not item.credential or item.credential.owner != "shared"):
        raise HTTPException(status_code=422, detail="This server does not use a shared key")
    if action == "remove" and item.credential and item.credential.required:
        raise HTTPException(status_code=422, detail="This server requires an API key")
    if any(ord(char) < 32 or ord(char) == 127 for char in key):
        raise HTTPException(status_code=422, detail="Invalid API key format")
    data = {"selected_tools": sorted(body.selected_tools), "key_action": action}
    operation, _ = await _begin(
        settings,
        item,
        body,
        principal,
        "publish",
        data,
        "key-pending" if action != "keep" else "ready",
    )
    if operation.state in {"queued", "applying"} and action != "keep":
        credentials: McpCredentials = request.app.state.mcp_credentials
        try:
            async with mcp_store.connection(settings.notice_dsn) as conn:
                await conn.execute(
                    "SELECT pg_advisory_lock(hashtextextended($1,0))", "mcp:" + item.id
                )
                row = await conn.fetchrow("SELECT * FROM mcp_operations WHERE id=$1", operation.id)
                if row and row["state"] in {"queued", "applying"} and row["phase"] == "key-pending":
                    await credentials.write(
                        item.id, str(operation.id), key if action == "replace" else ""
                    )
                    await mcp_store.progress(conn, operation.id, "ready")
        except (McpSetupError, asyncpg.PostgresError, OSError, TimeoutError):
            # A lost write response is ambiguous. The worker reads operationId
            # from OpenBao before deciding whether input must be entered again.
            pass
    return operation


@router.post("/{identity}/disable", status_code=202)
async def disable(
    identity: str,
    body: McpChange,
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(_configuration),
) -> McpOperation:
    """Clear exposed native membership while retaining the administrator's saved selection."""
    _origin(request, settings)
    response.headers["Cache-Control"] = "no-store"
    operation, _ = await _begin(settings, _item(identity, settings), body, principal, "disable", {})
    return operation


@router.post("/{identity}/refresh")
async def refresh(
    identity: str,
    body: McpChange,
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(_configuration),
) -> McpOperation:
    """Refresh immediately as the admitted administrator; new tools remain unselected."""
    _origin(request, settings)
    item = _item(identity, settings)
    if not {"llm:invoke", f"mcp:{item.id}:invoke"} <= principal.agentgateway_roles:
        raise HTTPException(status_code=403, detail="Missing approved MCP invocation permission")
    email = _verified_email(principal)
    response.headers["Cache-Control"] = "no-store"
    operation, created = await _begin(settings, item, body, principal, "refresh", {})
    if not created:
        return operation
    try:
        async with mcp_store.connection(settings.notice_dsn) as conn:
            await conn.execute("SELECT pg_advisory_lock(hashtextextended($1,0))", "mcp:" + item.id)
            await _refresh(request, settings, conn, operation, item, email)
            row = await conn.fetchrow("SELECT * FROM mcp_operations WHERE id=$1", operation.id)
            return mcp_store.operation(row)
    except (asyncpg.PostgresError, OSError, TimeoutError):
        raise HTTPException(status_code=503, detail="MCP setup storage is unavailable") from None


async def _refresh(
    request: Request,
    settings: Settings,
    conn: asyncpg.Connection,
    operation: McpOperation,
    item: McpRegistration,
    email: str,
) -> None:
    touched = False
    error_code = None
    try:
        async with asyncio.timeout(90):
            native = McpNativeSetup(settings, request.app.state.contextforge_admin_client)
            await native.tools(item)  # Verify the installed gateway before a provider call.
            account = ContextForgeAccountClient(
                settings, request.app.state.contextforge_admin_client
            )
            await account.prepare_account(email)
            if item.credential and item.credential.owner == "shared":
                record = await request.app.state.mcp_credentials.read(item.id)
                if item.credential.required and not record.api_key:
                    await mcp_store.fail(conn, operation.id, "api-key-required")
                    return
                await request.app.state.mcp_activation.wait(item, record)
            await account.prepare_discovery(email)
            await mcp_store.progress(conn, operation.id, "refreshing")
            touched = True
            await ContextForgeOAuthClient(
                settings,
                request.app.state.contextforge_oauth_client,
                email,
            ).discover(item)
    except McpSetupError as exc:
        error_code = exc.code
    except (ContextForgeAccountError, TimeoutError):
        error_code = "refresh-failed"
    if touched:
        # Even a failed native refresh can change definitions and associations.
        # Confirm the remaining published names; never select newly discovered tools.
        try:
            async with asyncio.timeout(45):
                await mcp_worker.reconcile_refresh(
                    request.app,
                    settings,
                    conn,
                    operation.id,
                    item,
                    error_code=error_code,
                )
                return
        except (ContextForgeAccountError, McpSetupError, TimeoutError):
            error_code = "refresh-failed"
    await mcp_store.fail(conn, operation.id, error_code or "refresh-failed")
