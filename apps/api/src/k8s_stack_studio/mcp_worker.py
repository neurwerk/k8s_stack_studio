"""Resume durable publication intent under PostgreSQL session locks after any restart."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import FastAPI

from k8s_stack_studio import mcp_store
from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.contextforge import ContextForgeAccountError
from k8s_stack_studio.lib.mcp_credentials import McpActivation, McpCredentials, McpSetupError
from k8s_stack_studio.lib.mcp_native_setup import McpNativeSetup
from k8s_stack_studio.lib.mcp_publication import PublicationUnavailableError, publication_snapshot
from k8s_stack_studio.models.mcp import McpRegistration

_logger = logging.getLogger(__name__)


async def _apply(
    app: FastAPI,
    settings: Settings,
    conn: asyncpg.Connection,
    row: asyncpg.Record,
) -> None:
    live, _ = publication_snapshot(settings)
    item = next((item for item in live.mcp_catalog if item.id == row["integration_id"]), None)
    if item is None:
        raise McpSetupError("catalog-changed")
    native = McpNativeSetup(live, app.state.contextforge_admin_client)
    request = json.loads(row["request"])
    if request["binding"] != mcp_store.binding(item):
        raise McpSetupError("catalog-changed")
    if row["kind"] == "refresh":
        if row["phase"] == "refreshing":
            await reconcile_refresh(
                app,
                live,
                conn,
                row["id"],
                item,
                error_code="refresh-interrupted",
            )
        else:
            await mcp_store.fail(conn, row["id"], "refresh-interrupted")
        return
    if row["kind"] == "disable":
        await native.publish(
            item,
            [],
            before_write=lambda: mcp_store.progress(conn, row["id"], "disabling"),
        )
        await mcp_store.finish(
            conn,
            row["id"],
            item.id,
            published={},
            enabled=False,
            registration_binding=mcp_store.binding(item),
        )
        return
    configured, version = await _activate(app, conn, row, item, request)
    names = request["selected_tools"]
    published = await native.publish(
        item,
        names,
        before_write=lambda: mcp_store.progress(conn, row["id"], "publishing"),
    )
    await mcp_store.finish(
        conn,
        row["id"],
        item.id,
        selected=names,
        published=published,
        enabled=bool(names),
        key_configured=configured,
        credential_version=version,
        registration_binding=mcp_store.binding(item),
    )


async def _activate(
    app: FastAPI,
    conn: asyncpg.Connection,
    row: asyncpg.Record,
    item: McpRegistration,
    request: dict[str, Any],
) -> tuple[bool, str]:
    if not item.credential or item.credential.owner != "shared":
        return False, ""
    credentials: McpCredentials = app.state.mcp_credentials
    record = await credentials.read(item.id)
    if item.credential.required and not record.api_key:
        raise McpSetupError("api-key-required")
    if row["credential_version"] and row["credential_version"] != record.version:
        raise McpSetupError("credential-changed")
    if request["key_action"] != "keep" and record.operation_id != str(row["id"]):
        # The process may have stopped before a secret reached OpenBao. Never
        # store it in the operation table or invent a replacement on recovery.
        raise McpSetupError("key-entry-required")
    # "Configured" means saved in OpenBao, not that activation has succeeded.
    # Keep the retry usable after a saved key times out during delivery.
    await conn.execute(
        "UPDATE mcp_setups SET key_configured=$2 WHERE integration_id=$1",
        item.id,
        bool(record.api_key),
    )
    await conn.execute(
        "UPDATE mcp_operations SET credential_version=$2 WHERE id=$1", row["id"], record.version
    )
    await mcp_store.progress(conn, row["id"], "waiting-for-key-activation")
    activation: McpActivation = app.state.mcp_activation
    await activation.wait(item, record)
    if (await credentials.read(item.id)).version != record.version:
        raise McpSetupError("credential-changed")
    return bool(record.api_key), record.version


async def _process(app: FastAPI, settings: Settings, operation_id: UUID) -> None:
    async with mcp_store.connection(settings.notice_dsn) as conn:
        row = await conn.fetchrow("SELECT * FROM mcp_operations WHERE id=$1", operation_id)
        if row is None or row["state"] not in {"queued", "applying"}:
            return
        if not await conn.fetchval(
            "SELECT pg_try_advisory_lock(hashtextextended($1,0))", "mcp:" + row["integration_id"]
        ):
            return
        row = await conn.fetchrow("SELECT * FROM mcp_operations WHERE id=$1", operation_id)
        if row is None or row["state"] not in {"queued", "applying"}:
            return
        try:
            async with asyncio.timeout(600):
                await _apply(app, settings, conn, row)
        except McpSetupError as exc:
            await mcp_store.fail(conn, row["id"], exc.code)
        except (ContextForgeAccountError, PublicationUnavailableError):
            await mcp_store.fail(conn, row["id"], "native-unavailable")
        except TimeoutError:
            await mcp_store.fail(conn, row["id"], "activation-timeout")


async def reconcile_refresh(
    app: FastAPI,
    settings: Settings,
    conn: asyncpg.Connection,
    operation_id: UUID,
    item: McpRegistration,
    *,
    error_code: str | None = None,
) -> None:
    """Confirm the surviving publication after refresh, including interrupted attempts.

    This does not call a provider or reuse an administrator's expired admission.
    Only tools from the last confirmed publication may remain exposed.
    """
    state = await conn.fetchrow("SELECT * FROM mcp_setups WHERE integration_id=$1", item.id)
    native = McpNativeSetup(settings, app.state.contextforge_admin_client)
    tools = await native.tools(item)
    selected = [name for name in json.loads(state["selected_tools"]) if name in tools]
    names = (
        [name for name in json.loads(state["published_tools"]) if name in tools]
        if state["binding"] == mcp_store.binding(item)
        else []
    )
    published = await native.publish(item, names)
    await mcp_store.finish(
        conn,
        operation_id,
        item.id,
        selected=selected,
        published=published,
        enabled=bool(published),
        refreshed=error_code is None,
        error_code=error_code,
        registration_binding=mcp_store.binding(item),
    )


async def run(app: FastAPI, settings: Settings) -> None:
    """A small restart-safe worker; independent providers run concurrently."""
    while True:
        try:
            async with mcp_store.connection(settings.notice_dsn) as conn:
                rows = await conn.fetch(
                    "SELECT id FROM mcp_operations WHERE state IN ('queued','applying') "
                    "AND ((kind!='refresh' AND phase!='key-pending') "
                    "OR updated_at < now()-interval '2 minutes') ORDER BY started_at LIMIT 4"
                )
            results = await asyncio.gather(
                *(_process(app, settings, row["id"]) for row in rows), return_exceptions=True
            )
            if any(isinstance(result, Exception) for result in results):
                _logger.warning(
                    "MCP operation storage temporarily unavailable; pending work retained"
                )
        except (asyncpg.PostgresError, OSError, TimeoutError):
            _logger.warning("MCP operation storage temporarily unavailable; pending work retained")
        await asyncio.sleep(2)
