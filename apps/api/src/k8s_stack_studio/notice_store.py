"""Studio-owned notice preferences in PostgreSQL; run migrate before serving traffic."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import asyncpg

from k8s_stack_studio.config.settings import Settings

FIELDS = (
    "notices_enabled",
    "show_no_pii",
    "show_pass",
    "show_changes",
    "show_reroutes",
    "show_timing",
    "show_no_faces",
    "show_detected_faces",
    "show_unscanned_faces",
)


class NoticeSchemaError(RuntimeError):
    """Notice storage is not configured or needs a compatible migration."""

    def __init__(self, newer: bool = False) -> None:
        """Report a safe error without including the connection string."""
        super().__init__(
            "Notice schema is newer than this Studio version"
            if newer
            else "K8S_STUDIO_NOTICE_DATABASE_URL is required"
        )


# Append-only, explicitly applied migrations. No DDL runs during request handling.
MIGRATIONS = (
    """CREATE TABLE notice_users (
        principal_id text PRIMARY KEY CHECK (length(principal_id) BETWEEN 1 AND 128),
        show_no_pii boolean NOT NULL DEFAULT true,
        show_pass boolean NOT NULL DEFAULT true,
        show_changes boolean NOT NULL DEFAULT true,
        show_reroutes boolean NOT NULL DEFAULT true,
        show_timing boolean NOT NULL DEFAULT true
    );
    CREATE TABLE notice_keys (
        principal_id text NOT NULL CHECK (length(principal_id) BETWEEN 1 AND 128),
        credential_id text NOT NULL CHECK (length(credential_id) BETWEEN 1 AND 128),
        show_no_pii boolean,
        show_pass boolean,
        show_changes boolean,
        show_reroutes boolean,
        show_timing boolean,
        PRIMARY KEY (principal_id, credential_id)
    );""",
    """ALTER TABLE notice_users
        ADD COLUMN notices_enabled boolean NOT NULL DEFAULT true,
        ADD COLUMN show_no_faces boolean NOT NULL DEFAULT true,
        ADD COLUMN show_detected_faces boolean NOT NULL DEFAULT true,
        ADD COLUMN show_unscanned_faces boolean NOT NULL DEFAULT true;
    ALTER TABLE notice_keys
        ADD COLUMN notices_enabled boolean,
        ADD COLUMN show_no_faces boolean,
        ADD COLUMN show_detected_faces boolean,
        ADD COLUMN show_unscanned_faces boolean;""",
    """CREATE TABLE mcp_setups (
        integration_id text PRIMARY KEY,
        revision bigint NOT NULL DEFAULT 0,
        selected_tools jsonb NOT NULL DEFAULT '[]',
        published_tools jsonb NOT NULL DEFAULT '{}',
        publication_uncertain boolean NOT NULL DEFAULT false,
        published_at timestamptz,
        enabled boolean NOT NULL DEFAULT false,
        key_configured boolean NOT NULL DEFAULT false,
        credential_version text NOT NULL DEFAULT '',
        binding text NOT NULL DEFAULT '',
        refreshed_at timestamptz,
        updated_at timestamptz NOT NULL DEFAULT now(),
        actor text NOT NULL DEFAULT ''
    );
    CREATE TABLE mcp_operations (
        id uuid PRIMARY KEY,
        integration_id text NOT NULL REFERENCES mcp_setups(integration_id),
        kind text NOT NULL CHECK (kind IN ('publish', 'disable', 'refresh')),
        state text NOT NULL CHECK (state IN ('queued', 'applying', 'succeeded', 'failed')),
        phase text NOT NULL,
        actor text NOT NULL,
        request jsonb NOT NULL,
        credential_version text NOT NULL DEFAULT '',
        error_code text,
        started_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX mcp_one_active_operation ON mcp_operations(integration_id)
        WHERE state IN ('queued', 'applying');
    CREATE INDEX mcp_operation_history ON mcp_operations(integration_id, started_at DESC);""",
)


async def migrate(dsn: str) -> None:
    """Apply versioned schema changes transactionally under an advisory lock."""
    if not dsn:
        raise NoticeSchemaError
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(4010091)")
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS notice_schema_version (version integer PRIMARY KEY)"
            )
            version = await conn.fetchval("SELECT max(version) FROM notice_schema_version") or 0
            if version > len(MIGRATIONS):
                raise NoticeSchemaError(newer=True)
            for index in range(version, len(MIGRATIONS)):
                await conn.execute(MIGRATIONS[index])
                await conn.execute(
                    "INSERT INTO notice_schema_version (version) VALUES ($1)", index + 1
                )
    finally:
        await conn.close()


async def schema_ready(dsn: str) -> bool:
    """Check the committed migration marker once when fetching the browser session."""
    if not dsn:
        return False
    try:
        conn = await asyncpg.connect(dsn, timeout=2)
        try:
            version = await conn.fetchval("SELECT max(version) FROM notice_schema_version")
            return version == len(MIGRATIONS)
        finally:
            await conn.close()
    except (asyncpg.PostgresError, OSError, TimeoutError, ValueError):
        return False


async def read(dsn: str, principal_id: str, credential_id: str | None = None) -> dict[str, bool]:
    """Return nine independent effective flags; consumers apply the master switch."""
    conn = await asyncpg.connect(dsn)
    try:
        user = await conn.fetchrow(
            "SELECT * FROM notice_users WHERE principal_id = $1", principal_id
        )
        key = (
            await conn.fetchrow(
                "SELECT * FROM notice_keys WHERE principal_id = $1 AND credential_id = $2",
                principal_id,
                credential_id,
            )
            if credential_id
            else None
        )
        return {
            field: key[field] if key and key[field] is not None else user[field] if user else True
            for field in FIELDS
        }
    finally:
        await conn.close()


async def write(
    dsn: str, principal_id: str, values: Mapping[str, bool | None], credential_id: str | None = None
) -> None:
    """Replace all nine values atomically (null means inherit on keys)."""
    args: list[str | bool | None] = [principal_id]
    if credential_id:
        args.append(credential_id)
    args += [values[field] for field in FIELDS]
    key_query = """INSERT INTO notice_keys
        (principal_id, credential_id, notices_enabled, show_no_pii, show_pass, show_changes,
         show_reroutes, show_timing, show_no_faces, show_detected_faces, show_unscanned_faces)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (principal_id, credential_id) DO UPDATE SET
        notices_enabled = EXCLUDED.notices_enabled, show_no_pii = EXCLUDED.show_no_pii,
        show_pass = EXCLUDED.show_pass, show_changes = EXCLUDED.show_changes,
        show_reroutes = EXCLUDED.show_reroutes, show_timing = EXCLUDED.show_timing,
        show_no_faces = EXCLUDED.show_no_faces,
        show_detected_faces = EXCLUDED.show_detected_faces,
        show_unscanned_faces = EXCLUDED.show_unscanned_faces"""
    user_query = """INSERT INTO notice_users
        (principal_id, notices_enabled, show_no_pii, show_pass, show_changes,
         show_reroutes, show_timing, show_no_faces, show_detected_faces, show_unscanned_faces)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (principal_id) DO UPDATE SET
        notices_enabled = EXCLUDED.notices_enabled, show_no_pii = EXCLUDED.show_no_pii,
        show_pass = EXCLUDED.show_pass, show_changes = EXCLUDED.show_changes,
        show_reroutes = EXCLUDED.show_reroutes, show_timing = EXCLUDED.show_timing,
        show_no_faces = EXCLUDED.show_no_faces,
        show_detected_faces = EXCLUDED.show_detected_faces,
        show_unscanned_faces = EXCLUDED.show_unscanned_faces"""
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(key_query if credential_id else user_query, *args)
    finally:
        await conn.close()


async def read_overrides(dsn: str, principal_id: str, credential_id: str) -> dict[str, bool | None]:
    """Read the raw key overrides, or inherit every field if absent."""
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT * FROM notice_keys WHERE principal_id = $1 AND credential_id = $2",
            principal_id,
            credential_id,
        )
        return {field: row[field] if row else None for field in FIELDS}
    finally:
        await conn.close()


def main() -> None:
    """Apply migrations as a controlled, one-shot command."""
    asyncio.run(migrate(Settings().notice_dsn))
