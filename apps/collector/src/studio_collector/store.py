"""Collector-owned PostgreSQL schema and atomic bucket replacement."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import asyncpg

from studio_collector.calendar import midnight
from studio_collector.models import Kind, StoreError, UsageRow
from studio_collector.pricing import Catalogue

WRITER_LOCK = 819402561
MEASURES = ("requests", "total_tokens", "tokens_known", "cost_usd", "cost_known")
TABLES = {
    ("hourly", "llm"): "usage_hourly_llm",
    ("daily", "llm"): "usage_daily_llm",
    ("hourly", "mcp"): "usage_hourly_mcp",
    ("daily", "mcp"): "usage_daily_mcp",
}


async def initialize(connection: asyncpg.Connection, timezone: ZoneInfo) -> None:
    """Initialize only Studio reporting storage, under the collector writer lock."""
    async with connection.transaction():
        await connection.execute("SELECT pg_advisory_xact_lock($1)", WRITER_LOCK)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS usage_meta (
                singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
                version integer NOT NULL CHECK(version = 1),
                activated_at timestamptz NOT NULL DEFAULT date_trunc('second', now()),
                timezone text NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage_source_status (
                kind text PRIMARY KEY CHECK(kind IN ('llm', 'mcp')),
                attempted_at timestamptz NOT NULL,
                succeeded_at timestamptz,
                failed boolean NOT NULL DEFAULT false
            );
            CREATE TABLE IF NOT EXISTS usage_bucket_status (
                kind text NOT NULL CHECK(kind IN ('llm', 'mcp')),
                bucket_start timestamptz NOT NULL,
                bucket_end timestamptz NOT NULL,
                collected_through timestamptz NOT NULL,
                refreshed_at timestamptz NOT NULL DEFAULT now(),
                pricing jsonb,
                PRIMARY KEY(kind, bucket_start)
            );
        """)
        await connection.execute(
            "INSERT INTO usage_meta(version, timezone) VALUES(1, $1) ON CONFLICT DO NOTHING",
            timezone.key,
        )
        await connection.execute(
            "ALTER TABLE usage_meta ADD COLUMN IF NOT EXISTS mcp_events_activated_at timestamptz"
        )
        await connection.execute(
            "ALTER TABLE usage_source_status ADD COLUMN IF NOT EXISTS completed_through timestamptz"
        )
        await metadata(connection, timezone)
        for (grain, kind), table in TABLES.items():
            pricing = (
                ", rate numeric CHECK(rate >= 0), price_revision text, billing_account text"
                if (grain, kind) == ("hourly", "mcp")
                else ""
            )
            await connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    bucket_start timestamptz NOT NULL,
                    bucket_end timestamptz NOT NULL CHECK(bucket_end > bucket_start),
                    group_key text NOT NULL CHECK(length(group_key) = 64),
                    dimensions jsonb NOT NULL,
                    requests numeric NOT NULL CHECK(requests >= 0),
                    total_tokens bigint NOT NULL CHECK(total_tokens >= 0),
                    tokens_known numeric NOT NULL CHECK(tokens_known BETWEEN 0 AND requests),
                    cost_usd numeric NOT NULL CHECK(cost_usd >= 0),
                    cost_known numeric NOT NULL CHECK(cost_known BETWEEN 0 AND requests),
                    refreshed_at timestamptz NOT NULL DEFAULT now()
                    {pricing},
                    PRIMARY KEY(bucket_start, group_key)
                )
            """)
            fields = ["principal_id", "app_id", "credential_id"]
            fields += ["model"] if kind == "llm" else ["server", "tool"]
            for field in fields:
                await connection.execute(
                    f"CREATE INDEX IF NOT EXISTS {table}_{field}_time "
                    f"ON {table} ((dimensions->>'{field}'), bucket_start)"
                )
        # Approved one-time cutover: sampled MCP estimates cannot become event counts.
        # The existing LLM activation, rows, and source status remain untouched.
        if not await connection.fetchval("SELECT mcp_events_activated_at FROM usage_meta"):
            for table in (TABLES["hourly", "mcp"], TABLES["daily", "mcp"]):
                await connection.execute(f"DELETE FROM {table}")  # noqa: S608 -- fixed tables
                await connection.execute(
                    f"ALTER TABLE {table} ADD CONSTRAINT {table}_integer_requests "
                    "CHECK(requests = trunc(requests))"
                )
            await connection.execute("DELETE FROM usage_bucket_status WHERE kind='mcp'")
            await connection.execute("DELETE FROM usage_source_status WHERE kind='mcp'")
            await connection.execute(
                "UPDATE usage_meta SET mcp_events_activated_at=date_trunc('second', now())"
            )


async def metadata(
    connection: asyncpg.Connection, timezone: ZoneInfo, kind: Kind = "llm"
) -> datetime:
    """Check schema/calendar identity; calendar changes require a fresh activation."""
    row = await connection.fetchrow("SELECT * FROM usage_meta WHERE singleton")
    if not row or row["version"] != 1 or row["timezone"] != timezone.key:
        raise StoreError
    return row["mcp_events_activated_at"] if kind == "mcp" else row["activated_at"]


async def pricing_for(
    connection: asyncpg.Connection, start: datetime, catalogue: Catalogue
) -> Catalogue:
    """An already collected bucket keeps its original dated pricing catalogue."""
    saved = await connection.fetchval(
        "SELECT pricing FROM usage_bucket_status WHERE kind='mcp' AND bucket_start=$1", start
    )
    return Catalogue.model_validate_json(saved) if saved else catalogue.at(start)


async def replace(
    connection: asyncpg.Connection,
    kind: Kind,
    start: datetime,
    end: datetime,
    through: datetime,
    timezone: ZoneInfo,
    rows: list[UsageRow],
    pricing: Catalogue | None = None,
) -> None:
    """Replace a whole bucket and rebuild its local day in the same transaction."""
    from datetime import timedelta

    hourly, daily = TABLES["hourly", kind], TABLES["daily", kind]
    day = start.astimezone(timezone).date()
    day_start, day_end = midnight(day, timezone), midnight(day + timedelta(days=1), timezone)
    columns = ", ".join(MEASURES)
    sums = ", ".join(f"SUM({name})" for name in MEASURES)
    async with connection.transaction():
        await connection.execute(f"DELETE FROM {hourly} WHERE bucket_start=$1", start)  # noqa: S608
        for row in rows:
            values = [
                start,
                end,
                row.dimensions.key,
                row.dimensions.model_dump_json(),
                *(getattr(row, name) for name in MEASURES),
            ]
            extra = ""
            if kind == "mcp":
                extra = ", rate, price_revision, billing_account"
                values.extend([row.rate, row.price_revision, row.billing_account])
            parameters = ",".join(f"${i}" for i in range(1, len(values) + 1))
            await connection.execute(
                f"INSERT INTO {hourly} "  # noqa: S608 -- fixed table and column allowlists
                f"(bucket_start,bucket_end,group_key,dimensions,{columns}{extra}) "
                f"VALUES ({parameters})",
                *values,
            )
        await connection.execute(f"DELETE FROM {daily} WHERE bucket_start=$1", day_start)  # noqa: S608
        await connection.execute(
            f"INSERT INTO {daily} (bucket_start,bucket_end,group_key,dimensions,{columns}) "  # noqa: S608
            f"SELECT $1,$2,group_key,dimensions,{sums} FROM {hourly} "
            "WHERE bucket_start >= $1 AND bucket_start < $2 GROUP BY group_key,dimensions",
            day_start,
            day_end,
        )
        await connection.execute(
            """
            INSERT INTO usage_bucket_status
                (kind,bucket_start,bucket_end,collected_through,pricing)
            VALUES($1,$2,$3,$4,$5)
            ON CONFLICT(kind,bucket_start) DO UPDATE SET
                collected_through=excluded.collected_through, refreshed_at=now()
        """,
            kind,
            start,
            end,
            through,
            pricing.model_dump_json() if pricing else None,
        )
        await connection.execute(
            """
            INSERT INTO usage_source_status(kind,attempted_at,succeeded_at)
            VALUES($1,now(),now()) ON CONFLICT(kind) DO UPDATE SET
                attempted_at=now(),succeeded_at=now(),failed=false
        """,
            kind,
        )


async def failed(connection: asyncpg.Connection, kind: Kind) -> None:
    """Expose a source failure without changing its last valid data."""
    await connection.execute(
        """
        INSERT INTO usage_source_status(kind,attempted_at,failed) VALUES($1,now(),true)
        ON CONFLICT(kind) DO UPDATE SET attempted_at=now(),failed=true
    """,
        kind,
    )


def decode(row: asyncpg.Record) -> UsageRow:
    """Read the same normalized measures from hourly and daily records."""
    return UsageRow.model_validate(
        {
            "dimensions": json.loads(row["dimensions"]),
            **{name: row[name] for name in MEASURES},
        }
    )
