"""Durable MCP intent and operation history; no credential or caller token storage."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import asyncpg

from k8s_stack_studio.models.mcp import McpRegistration
from k8s_stack_studio.models.mcp_setup import McpOperation


class McpConflictError(Exception):
    """A stale revision or a different operation is already in progress."""


def binding(item: McpRegistration) -> str:
    """Bind durable intent to the exact installed native destination and credential policy."""
    definition = item.model_dump(exclude={"approved_tools", "tool_names", "checks", "name"})
    return hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()


def operation(row: asyncpg.Record) -> McpOperation:
    """Return the allowlisted, secret-free operation view."""
    return McpOperation.model_validate({key: row[key] for key in McpOperation.model_fields})


@asynccontextmanager
async def connection(dsn: str) -> AsyncIterator[asyncpg.Connection]:
    """Keep credentials out of logs and always release the connection and its locks."""
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        yield conn
    finally:
        await conn.close()


async def setups(dsn: str) -> dict[str, dict[str, Any]]:
    """Read current state with only the latest operation, not unbounded history."""
    async with connection(dsn) as conn:
        rows = await conn.fetch("SELECT * FROM mcp_setups")
        latest = await conn.fetch(
            "SELECT DISTINCT ON (integration_id) * FROM mcp_operations "
            "ORDER BY integration_id, started_at DESC"
        )
    operations = {row["integration_id"]: operation(row) for row in latest}
    return {
        row["integration_id"]: {
            **dict(row),
            "selected_tools": json.loads(row["selected_tools"]),
            "published_tools": json.loads(row["published_tools"]),
            "operation": operations.get(row["integration_id"]),
        }
        for row in rows
    }


async def begin(
    dsn: str,
    identity: str,
    revision: int,
    operation_id: UUID,
    kind: str,
    actor: str,
    request: dict[str, Any],
    *,
    phase: str = "ready",
) -> tuple[McpOperation, bool]:
    """Reserve one revision atomically; duplicate requests return their original result."""
    async with connection(dsn) as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO mcp_setups(integration_id) VALUES ($1) ON CONFLICT DO NOTHING", identity
        )
        row = await conn.fetchrow(
            "SELECT * FROM mcp_setups WHERE integration_id=$1 FOR UPDATE", identity
        )
        previous = await conn.fetchrow("SELECT * FROM mcp_operations WHERE id=$1", operation_id)
        if previous:
            if (
                previous["integration_id"],
                previous["actor"],
                previous["kind"],
                json.loads(previous["request"]),
            ) != (identity, actor, kind, request):
                raise McpConflictError
            return operation(previous), False
        if row["revision"] != revision or await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM mcp_operations WHERE integration_id=$1 "
            "AND state IN ('queued', 'applying'))",
            identity,
        ):
            raise McpConflictError
        await conn.execute(
            "UPDATE mcp_setups SET revision=revision+1, updated_at=now(), actor=$2 "
            ", selected_tools=COALESCE($3::jsonb,selected_tools) WHERE integration_id=$1",
            identity,
            actor,
            json.dumps(request["selected_tools"]) if kind == "publish" else None,
        )
        row = await conn.fetchrow(
            "INSERT INTO mcp_operations(id,integration_id,kind,state,phase,actor,request) "
            "VALUES ($1,$2,$3,'queued',$4,$5,$6::jsonb) RETURNING *",
            operation_id,
            identity,
            kind,
            phase,
            actor,
            json.dumps(request),
        )
        return operation(row), True


async def progress(conn: asyncpg.Connection, operation_id: UUID, phase: str) -> None:
    """Persist the current idempotent step before calling the next external system."""
    async with conn.transaction():
        await conn.execute(
            "UPDATE mcp_operations SET state='applying', phase=$2, updated_at=now() WHERE id=$1",
            operation_id,
            phase,
        )
        if phase in {"publishing", "disabling", "refreshing"}:
            await conn.execute(
                "UPDATE mcp_setups SET publication_uncertain=true WHERE integration_id="
                "(SELECT integration_id FROM mcp_operations WHERE id=$1)",
                operation_id,
            )


async def fail(conn: asyncpg.Connection, operation_id: UUID, error_code: str) -> None:
    """Save only a stable error code; exception messages may contain secrets."""
    await conn.execute(
        "UPDATE mcp_operations SET state='failed', error_code=$2, updated_at=now() WHERE id=$1",
        operation_id,
        error_code,
    )


async def finish(
    conn: asyncpg.Connection,
    operation_id: UUID,
    identity: str,
    *,
    selected: list[str] | None = None,
    published: dict[str, str] | None = None,
    enabled: bool | None = None,
    key_configured: bool | None = None,
    credential_version: str | None = None,
    refreshed: bool = False,
    registration_binding: str,
    error_code: str | None = None,
) -> None:
    """Commit confirmed runtime state and the successful operation in one transaction."""
    async with conn.transaction():
        await conn.execute(
            "UPDATE mcp_setups SET selected_tools=COALESCE($2::jsonb,selected_tools), "
            "published_tools=COALESCE($3::jsonb,published_tools), enabled=COALESCE($4,enabled), "
            "publication_uncertain=false, published_at=now(), "
            "key_configured=COALESCE($5,key_configured), "
            "credential_version=COALESCE($6,credential_version), "
            "refreshed_at=CASE WHEN $7 THEN now() ELSE refreshed_at END, "
            "binding=$8, updated_at=now() "
            "WHERE integration_id=$1",
            identity,
            json.dumps(selected) if selected is not None else None,
            json.dumps(published) if published is not None else None,
            enabled,
            key_configured,
            credential_version,
            refreshed,
            registration_binding,
        )
        await conn.execute(
            "UPDATE mcp_operations SET state=$2, phase='done', error_code=$3, "
            "updated_at=now() WHERE id=$1",
            operation_id,
            "failed" if error_code else "succeeded",
            error_code,
        )
