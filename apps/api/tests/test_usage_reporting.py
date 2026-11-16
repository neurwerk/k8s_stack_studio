import os
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import override
from uuid import uuid4
from zoneinfo import ZoneInfo

import asyncpg
import httpx
import pytest
from studio_collector import store
from studio_collector.models import Dimensions, UsageRow
from studio_collector.pricing import Account, Catalogue, Price

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.usage import UsageReader
from k8s_stack_studio.models.gateway_metadata import UsageQuery


@pytest.fixture
async def reporting():
    dsn = os.environ.get("USAGE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("USAGE_TEST_DATABASE_URL must name a disposable test database")
    connection = await asyncpg.connect(dsn)
    schema = "usage_api_test_" + uuid4().hex
    await connection.execute(f'CREATE SCHEMA "{schema}"')
    await connection.execute(f'SET search_path TO "{schema}"')
    timezone = ZoneInfo("UTC")
    await store.initialize(connection, timezone)
    await connection.execute(
        "UPDATE usage_meta SET activated_at=$1", datetime(2026, 11, 1, tzinfo=UTC)
    )

    class Reader(UsageReader):
        @override
        @asynccontextmanager
        async def connection(self):
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                yield connection

    async with httpx.AsyncClient() as client:
        try:
            yield Reader(Settings(usage_timezone="UTC"), client), connection
        finally:
            await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
            await connection.close()


async def test_sql_scope_filters_daily_consistency_missing_and_zero(reporting):
    reader, connection = reporting
    start = datetime(2026, 11, 2, tzinfo=UTC)
    for hour in range(24):
        a = start + timedelta(hours=hour)
        rows = (
            []
            if hour
            else [
                UsageRow(
                    dimensions=Dimensions(principal_id="self", app_id="editor", model="m"),
                    requests=Decimal(2),
                    total_tokens=20,
                    cost_usd=Decimal("0.01"),
                    tokens_known=Decimal(2),
                    cost_known=Decimal(2),
                ),
                UsageRow(
                    dimensions=Dimensions(principal_id="other", app_id="editor", model="m"),
                    requests=Decimal(99),
                    total_tokens=990,
                ),
            ]
        )
        await store.replace(
            connection,
            "llm",
            a,
            a + timedelta(hours=1),
            a + timedelta(hours=1),
            ZoneInfo("UTC"),
            rows,
        )
    result = await reader.fetch_daily_usage("self", date(2026, 11, 2), date(2026, 11, 3))
    assert result.days[0].models[0].requests == 2
    assert result.days[0].coverage.complete
    assert not result.days[1].coverage.complete and result.days[1].models == []
    sources = await reader.fetch_source_breakdown(
        "self", date(2026, 11, 2), date(2026, 11, 2), UsageQuery(app_id="editor")
    )
    assert len(sources.people) == 1 and sources.people[0].user_id == "self"
    assert sources.apps[0].total_tokens == 20
    none = await reader.fetch_daily_usage(
        "self", date(2026, 11, 2), date(2026, 11, 2), UsageQuery(app_id="different")
    )
    assert none.days[0].coverage.complete and not none.days[0].models
    hourly = await reader.rows(
        connection, "self", start, start + timedelta(days=1), UsageQuery(), daily=False
    )
    assert sum(row.requests for _, row in hourly) == result.days[0].models[0].requests


async def test_long_chart_points_keep_totals_and_missing_previous_year(reporting):
    reader, connection = reporting
    start = datetime(2026, 11, 2, tzinfo=UTC)
    row = UsageRow(
        dimensions=Dimensions(principal_id="self", server="search", tool="lookup"),
        requests=Decimal("1.25"),
    )
    await store.replace(
        connection,
        "mcp",
        start,
        start + timedelta(hours=1),
        start + timedelta(hours=1),
        ZoneInfo("UTC"),
        [row],
    )
    result = await reader.fetch_daily_usage(
        "self", date(2020, 1, 1), date(2026, 11, 2), UsageQuery(kind="mcp", compare_year=True)
    )
    assert len(result.days) <= 366
    assert sum(m.requests for d in result.days for m in d.models) == 1.25
    assert result.previous_year and all(not d.models for d in result.previous_year)
    tool = next(m for d in result.days for m in d.models)
    assert tool.server == "search" and tool.tool == "lookup"
    assert tool.accounting.tokens.state == "unknown"


async def test_partial_historical_day_is_not_measured_zero_for_missing_hours(reporting):
    reader, connection = reporting
    start = datetime(2026, 11, 2, tzinfo=UTC)
    await store.replace(
        connection,
        "llm",
        start,
        start + timedelta(hours=1),
        start + timedelta(hours=1),
        ZoneInfo("UTC"),
        [],
    )
    result = await reader.fetch_daily_usage("self", start.date(), start.date())
    assert not result.coverage.complete and not result.days[0].coverage.complete
    assert not result.days[0].models


async def test_billing_adjusts_once_across_tools_and_users_and_keeps_account_isolation(reporting):
    reader, connection = reporting
    start = datetime(2026, 11, 2, tzinfo=UTC)
    price = Price(
        effective_from=datetime(2026, 11, 1, tzinfo=UTC),
        default=Decimal(5),
        monthly_fee=Decimal(10),
        included_calls=Decimal(2000),
    )
    catalogue = Catalogue(
        accounts=[
            Account(server="docs", billing_account="one-seat", prices=[price]),
            Account(server="other", billing_account="other-seat", prices=[price]),
        ]
    )
    rows = [
        catalogue.apply(
            UsageRow(
                dimensions=Dimensions(server=server, tool=tool, principal_id=person),
                requests=Decimal(calls),
            ),
            start,
        )
        for server, tool, person, calls in [
            ("docs", "resolve", "self", 1500),
            ("docs", "query", "other", 1000),
            ("other", "query", "self", 1000),
        ]
    ]
    await store.replace(
        connection,
        "mcp",
        start,
        start + timedelta(hours=1),
        start + timedelta(hours=1),
        ZoneInfo("UTC"),
        rows,
        catalogue,
    )
    estimates = {row.billing_account: row for row in await reader.fetch_billing(start.date())}
    assert estimates["one-seat"].gross_usage_usd == Decimal("12.5")
    assert estimates["one-seat"].adjusted_estimate_usd == Decimal("12.5")
    assert estimates["other-seat"].adjusted_estimate_usd == Decimal(10)
    assert all(not e.complete for e in estimates.values())


async def test_request_lookup_is_scoped_and_never_queries_pre_activation(reporting):
    reader, _connection = reporting
    from unittest.mock import AsyncMock

    reader.source.collect = AsyncMock(return_value=[])
    await reader.fetch_daily_usage(
        "self",
        date(2026, 10, 30),
        date(2026, 11, 1),
        UsageQuery(request_id="request-1", app_id="editor"),
    )
    calls = reader.source.collect.call_args_list
    assert len(calls) == 1
    assert calls[0].args[0] == datetime(2026, 11, 1, tzinfo=UTC)
    assert calls[0].args[2] == {
        "agentgateway.user": "self",
        "neurwerk.request_id": "request-1",
        "neurwerk.app_id": "editor",
    }
