import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import asyncpg
import pytest

from studio_collector import store
from studio_collector.models import Dimensions, UsageRow
from studio_collector.pricing import Account, Catalogue, Price

START = datetime(2026, 11, 16, 10, tzinfo=UTC)
TZ = ZoneInfo("UTC")


@pytest.fixture
async def database():
    dsn = os.environ.get("USAGE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("USAGE_TEST_DATABASE_URL must name a disposable test database")
    connection = await asyncpg.connect(dsn)
    schema = "usage_test_" + uuid4().hex
    await connection.execute(f'CREATE SCHEMA "{schema}"')
    await connection.execute(f'SET search_path TO "{schema}"')
    await store.initialize(connection, TZ)
    try:
        yield connection
    finally:
        await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await connection.close()


def row(person, calls):
    return UsageRow(
        dimensions=Dimensions(principal_id=person, server="search", tool="lookup"),
        requests=Decimal(calls),
    )


async def put(connection, rows, offset=0, pricing=None):
    a = START + timedelta(hours=offset)
    b = a + timedelta(hours=1)
    await store.replace(connection, "mcp", a, b, b, TZ, rows, pricing)


async def test_atomic_replace_vanished_groups_daily_corrections_and_failure(database):
    await put(database, [row("first", "1"), row("removed", "2")])
    await put(database, [row("first", "1"), row("removed", "2")])
    await put(database, [row("first", "4")], offset=1)
    await put(database, [row("first", "3")])
    daily = await database.fetch("SELECT * FROM usage_daily_mcp")
    assert len(daily) == 1 and daily[0]["requests"] == 7
    assert await database.fetchval("SELECT count(*) FROM usage_hourly_mcp") == 2
    with pytest.raises(asyncpg.UniqueViolationError):
        await put(database, [row("same", "1"), row("same", "2")])
    assert await database.fetchval("SELECT sum(requests) FROM usage_daily_mcp") == 7
    await store.failed(database, "mcp")
    await store.replace(
        database, "llm", START, START + timedelta(hours=1), START + timedelta(hours=1), TZ, []
    )
    assert await database.fetchval("SELECT failed FROM usage_source_status WHERE kind='mcp'")
    assert await database.fetchval("SELECT count(*) FROM usage_bucket_status WHERE kind='llm'") == 1
    assert await database.fetchval("SELECT sum(requests) FROM usage_daily_mcp") == 7


async def test_price_snapshot_survives_config_edits_and_daily_is_hourly_sum(database):
    catalogue = Catalogue(
        accounts=[
            Account(
                server="search",
                billing_account="account",
                prices=[
                    Price(effective_from=START, default=Decimal(5)),
                ],
            )
        ]
    )
    original = catalogue.apply(row("first", "1000"), START)
    await put(database, [original], pricing=catalogue)
    changed = Catalogue(
        accounts=[
            Account(
                server="search",
                billing_account="account",
                prices=[
                    Price(effective_from=START, default=Decimal(99)),
                ],
            )
        ]
    )
    saved = await store.pricing_for(database, START, changed)
    await put(database, [saved.apply(row("first", "2000"), START)], pricing=saved)
    assert await database.fetchval("SELECT cost_usd FROM usage_daily_mcp") == 10
    assert await database.fetchval("SELECT rate FROM usage_hourly_mcp") == 5
    assert (
        await database.fetchval("SELECT price_revision FROM usage_hourly_mcp")
        == original.price_revision
    )


async def test_writer_lock_serializes_connections(database):
    other = await asyncpg.connect(os.environ["USAGE_TEST_DATABASE_URL"])
    try:
        assert await database.fetchval("SELECT pg_try_advisory_lock($1)", store.WRITER_LOCK)
        assert not await other.fetchval("SELECT pg_try_advisory_lock($1)", store.WRITER_LOCK)
        await database.execute("SELECT pg_advisory_unlock($1)", store.WRITER_LOCK)
        assert await other.fetchval("SELECT pg_try_advisory_lock($1)", store.WRITER_LOCK)
    finally:
        await other.close()


async def test_event_cutover_removes_only_legacy_mcp_once(database):
    # Recreate the previous schema marker and fractional rows.
    for table in ("usage_hourly_mcp", "usage_daily_mcp"):
        await database.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_integer_requests")
    await database.execute("UPDATE usage_meta SET mcp_events_activated_at=NULL")
    await put(database, [row("legacy", "1.5")], pricing=Catalogue())
    await store.replace(
        database,
        "llm",
        START,
        end := START + timedelta(hours=1),
        end,
        TZ,
        [UsageRow(dimensions=Dimensions(model="model"), requests=Decimal(2))],
    )
    activation = await store.metadata(database, TZ)
    await store.initialize(database, TZ)
    assert await database.fetchval("SELECT count(*) FROM usage_hourly_mcp") == 0
    assert await database.fetchval("SELECT count(*) FROM usage_daily_mcp") == 0
    assert await database.fetchval("SELECT count(*) FROM usage_bucket_status WHERE kind='mcp'") == 0
    assert await database.fetchval("SELECT count(*) FROM usage_source_status WHERE kind='mcp'") == 0
    assert await database.fetchval("SELECT sum(requests) FROM usage_daily_llm") == 2
    assert await store.metadata(database, TZ) == activation
    cutover = await store.metadata(database, TZ, "mcp")
    await put(database, [row("new", "3")])
    await store.initialize(database, TZ)
    assert await store.metadata(database, TZ, "mcp") == cutover
    assert await database.fetchval("SELECT sum(requests) FROM usage_daily_mcp") == 3
    with pytest.raises(asyncpg.CheckViolationError):
        await put(database, [row("invalid", "1.5")])
