"""Read-only reporting queries and the narrow request-ID source lookup."""

from __future__ import annotations

import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import asyncpg
import httpx
from studio_collector import store
from studio_collector.calendar import date_range, hours, midnight, periods
from studio_collector.models import (
    Dimensions,
    InvalidUsageRangeError,
    Kind,
    SourceError,
    StoreError,
    UsageRow,
)
from studio_collector.pricing import Catalogue, ProviderEstimate, billing_period, monthly_cost
from studio_collector.sources import LlmSource

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.models.gateway_metadata import UsageFilters, UsageQuery
from k8s_stack_studio.models.usage import (
    Coverage,
    DailyUsage,
    DailyUsageResponse,
    ModelUsage,
    UsagePeopleResponse,
    UsagePeriod,
    UsagePersonSources,
    UsageResponse,
    UsageSource,
    UsageSourcesResponse,
    UserUsageTotal,
)


class UsageUnavailable(RuntimeError):  # noqa: N818 -- public route error adapter
    """Reporting data cannot currently be read."""


class UsageReader:
    """Use only the reporting role; never initialize schema from API workers."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        """Store connection settings and the request-level HTTP client."""
        self.settings = settings
        self.timezone = ZoneInfo(settings.usage_timezone)
        self.source = LlmSource(client, settings.agentgateway_admin_url)

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[asyncpg.Connection]:
        """Bound each report to a consistent, read-only PostgreSQL snapshot."""
        connection = None
        try:
            connection = await asyncpg.connect(
                host=self.settings.usage_postgres_host,
                port=self.settings.usage_postgres_port,
                database="studio_usage",
                user="studio_usage_reader",
                password=self.settings.usage_postgres_password,
                timeout=5,
                command_timeout=30,
            )
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                yield connection
        except (asyncpg.PostgresError, OSError, TimeoutError, StoreError, SourceError) as error:
            raise UsageUnavailable from error
        finally:
            if connection is not None:
                await connection.close()

    async def coverage(
        self,
        connection: asyncpg.Connection,
        kind: Kind,
        start: datetime,
        end: datetime,
        *,
        provisional: bool = False,
    ) -> Coverage:
        """Distinguish successful empty buckets, missing history and stale sources."""
        activation = await store.metadata(connection, self.timezone)
        now = datetime.now(UTC)
        status = await connection.fetchrow("SELECT * FROM usage_source_status WHERE kind=$1", kind)
        collected = await connection.fetch(
            """
            SELECT bucket_start,collected_through FROM usage_bucket_status
            WHERE kind=$1 AND bucket_start < $3 AND bucket_end > $2
        """,
            kind,
            start,
            end,
        )
        through = {row["bucket_start"]: row["collected_through"] for row in collected}
        refreshed = status["succeeded_at"] if status else None
        # For a live bucket, coverage is complete through its latest collection.
        latest = max(through.values(), default=start)
        provisional = provisional or end > now
        expected_end = min(end, now, latest) if provisional else end
        complete = (
            start >= activation
            and expected_end > start
            and all(
                through.get(a, a) >= min(b, expected_end)
                for a, b in hours(start, expected_end, self.timezone)
            )
        )
        return Coverage(
            activated_at=activation,
            refreshed_at=refreshed,
            complete=complete,
            stale=not status
            or status["failed"]
            or refreshed is None
            or now - refreshed > timedelta(minutes=30),
            provisional=provisional,
            estimated=kind == "mcp",
        )

    async def rows(
        self,
        connection: asyncpg.Connection,
        user_id: str | None,
        start: datetime,
        end: datetime,
        filters: UsageFilters,
        *,
        daily: bool = True,
    ) -> list[tuple[datetime, UsageRow]]:
        """Constrain principals in SQL; caller filters can only narrow that scope."""
        if filters.request_id:
            return await self._request_rows(connection, user_id, start, end, filters, daily=daily)
        table = store.TABLES["daily" if daily else "hourly", filters.kind]
        values: list[object] = [start, end]
        conditions = ["bucket_start >= $1", "bucket_start < $2"]
        dimensions = {
            key.removeprefix("neurwerk."): value for key, value in filters.attributes().items()
        }
        for name in ("server", "tool"):
            if (value := getattr(filters, name)) is not None:
                dimensions[name] = value
        if user_id is not None:
            dimensions["principal_id"] = user_id
        for name, value in dimensions.items():
            if name not in Dimensions.model_fields:
                raise UsageUnavailable
            values.append(value)
            conditions.append(f"dimensions->>'{name}' = ${len(values)}")
        records = await connection.fetch(
            f"SELECT * FROM {table} WHERE {' AND '.join(conditions)}",  # noqa: S608 -- allowlisted identifiers
            *values,
        )
        return [(row["bucket_start"], store.decode(row)) for row in records]

    async def _request_rows(
        self,
        connection: asyncpg.Connection,
        user_id: str | None,
        start: datetime,
        end: datetime,
        filters: UsageFilters,
        *,
        daily: bool,
    ) -> list[tuple[datetime, UsageRow]]:
        """Bound the exceptional request-ID lookup to source-retained calendar days."""
        if filters.kind == "mcp":
            raise UsageUnavailable  # Native MCP counters have no request IDs.
        if filters.server or filters.tool:
            return []  # LLM records have no MCP server/tool dimensions.
        activation = await store.metadata(connection, self.timezone)
        days = (end.astimezone(self.timezone).date() - start.astimezone(self.timezone).date()).days
        if daily and days > 90:
            raise InvalidUsageRangeError
        attributes = filters.attributes()
        if user_id is not None:
            attributes["agentgateway.user"] = user_id
        result = []
        a = max(start, activation)
        end = min(end, datetime.now(UTC))
        while a < end:
            b = (
                min(
                    midnight(a.astimezone(self.timezone).date() + timedelta(days=1), self.timezone),
                    end,
                )
                if daily
                else end
            )
            for row in await self.source.collect(a, b, attributes):
                result.append((a, row))
            a = b
        return result

    async def fetch_daily_usage(
        self,
        user_id: str | None,
        start: date | None = None,
        end: date | None = None,
        filters: UsageQuery | None = None,
    ) -> DailyUsageResponse:
        """Read daily summaries; bound chart points without dropping any totals."""
        filters = filters or UsageQuery()
        now = datetime.now(UTC)
        start, end = date_range(start, end, now, self.timezone)
        if filters.compare_year and start.year == 1:
            raise InvalidUsageRangeError
        async with self.connection() as connection:
            days = await self._days(connection, user_id, start, end, filters)
            coverage = await self.coverage(
                connection,
                filters.kind,
                midnight(start, self.timezone),
                midnight(end + timedelta(days=1), self.timezone),
            )
            previous = None
            if filters.compare_year:
                # Clamp Feb 29 to Feb 28; each comparison range is queried once.
                def prior(day: date) -> date:
                    return (
                        day.replace(year=day.year - 1, day=min(day.day, 28))
                        if (day.month == 2 and day.day == 29)
                        else day.replace(year=day.year - 1)
                    )

                previous = await self._days(connection, user_id, prior(start), prior(end), filters)
        return DailyUsageResponse(
            timezone=self.timezone.key,
            start_date=start,
            end_date=end,
            today=now.astimezone(self.timezone).date(),
            kind=filters.kind,
            days=days,
            coverage=coverage,
            previous_year=previous,
        )

    async def _days(
        self,
        connection: asyncpg.Connection,
        user_id: str | None,
        start: date,
        end: date,
        filters: UsageQuery,
    ) -> list[DailyUsage]:
        step = math.ceil(((end - start).days + 1) / 366)
        points: dict[date, DailyUsage] = {}
        models: dict[tuple[date, str | None, str | None, str | None], ModelUsage] = {}
        for offset in range(0, (end - start).days + 1, step):
            day = start + timedelta(days=offset)
            until = min(day + timedelta(days=step - 1), end)
            coverage = await self.coverage(
                connection,
                filters.kind,
                midnight(day, self.timezone),
                midnight(until + timedelta(days=1), self.timezone),
            )
            points[day] = DailyUsage(date=day, end_date=until, models=[], coverage=coverage)
        rows = await self.rows(
            connection,
            user_id,
            midnight(start, self.timezone),
            midnight(end + timedelta(days=1), self.timezone),
            filters,
        )
        for instant, row in rows:
            day = instant.astimezone(self.timezone).date()
            point = start + timedelta(days=((day - start).days // step) * step)
            d = row.dimensions
            key = (point, d.model, d.server, d.tool)
            if key not in models:
                label = d.model if filters.kind == "llm" else f"{d.server or '?'} / {d.tool or '?'}"
                models[key] = ModelUsage(model=label, server=d.server, tool=d.tool)
                points[point].models.append(models[key])
            models[key].add(row)
        for point in points.values():
            for model in point.models:
                model.qualify(filters.kind, point.coverage)
        return list(points.values())

    async def fetch_all_daily_usage(
        self,
        start: date | None,
        end: date | None,
        filters: UsageQuery,
    ) -> DailyUsageResponse:
        """Admin-only aggregate over the same daily query."""
        return await self.fetch_daily_usage(None, start, end, filters)

    async def fetch_source_breakdown(
        self,
        user_id: str | None,
        start: date | None,
        end: date | None,
        filters: UsageQuery,
    ) -> UsageSourcesResponse:
        """Reuse stable IDs and existing name resolution for all drilldowns."""
        start, end = date_range(start, end, datetime.now(UTC), self.timezone)
        a, b = midnight(start, self.timezone), midnight(end + timedelta(days=1), self.timezone)
        async with self.connection() as connection:
            rows = await self.rows(
                connection, user_id, a, b, filters, daily=not bool(filters.request_id)
            )
            coverage = await self.coverage(connection, filters.kind, a, b)
        return source_breakdown(rows, filters.kind, coverage, self.timezone.key, start, end)

    async def fetch_user_breakdown(
        self,
        start: date | None,
        end: date | None,
        filters: UsageQuery,
    ) -> UsagePeopleResponse:
        """Derive the admin picker from the same principal-scoped stored totals."""
        sources = await self.fetch_source_breakdown(None, start, end, filters)
        return UsagePeopleResponse(
            timezone=sources.timezone,
            start_date=sources.start_date,
            end_date=sources.end_date,
            coverage=sources.coverage,
            users=[
                UserUsageTotal(user_id=p.user_id, **p.total.model_dump())
                for p in sources.people
                if p.user_id is not None
            ],
        )

    async def fetch_usage(self, user_id: str, filters: UsageFilters) -> UsageResponse:
        """Read each period from one grain, never summing daily and hourly rows together."""
        now = datetime.now(UTC)
        totals: dict[str, UsagePeriod] = {}
        coverage: dict[str, Coverage] = {}
        async with self.connection() as connection:
            activation = await store.metadata(connection, self.timezone)
            for name, (start, end) in periods(now, self.timezone, activation).items():
                coverage[name] = await self.coverage(
                    connection, filters.kind, start, end, provisional=end == now
                )
                totals[name] = UsagePeriod()
                # Calendar reports use daily summaries; rolling starts have
                # hour precision. Missing fractional edges remain incomplete.
                first, after = next(hours(start, end, self.timezone), (start, end))
                aligned = first if start == activation or first == start else after
                day_start = midnight(start.astimezone(self.timezone).date(), self.timezone)
                daily = start == day_start or name == "total"
                if daily:
                    aligned = day_start  # Activation's day contains only post-activation data.
                if filters.request_id:
                    aligned, daily = start, False
                for _, row in await self.rows(
                    connection, user_id, aligned, end, filters, daily=daily
                ):
                    totals[name].add(row)
                if aligned != start and start != activation:
                    coverage[name].complete = False
                totals[name].qualify(filters.kind, coverage[name])
        return UsageResponse.model_validate({**totals, "coverage": coverage})

    async def fetch_billing(self, day: date) -> list[ProviderEstimate]:
        """Apply account-wide plan adjustments once, never to a person or tool row."""
        result = []
        async with self.connection() as connection:
            saved = await connection.fetchval(
                "SELECT pricing FROM usage_bucket_status "
                "WHERE kind='mcp' AND bucket_start <= $1 ORDER BY bucket_start DESC LIMIT 1",
                midnight(day + timedelta(days=1), self.timezone),
            )
            if not saved:
                return []
            catalogue = Catalogue.model_validate_json(saved)
            for account in catalogue.accounts:
                start, end = billing_period(account, day)
                snapshots = await connection.fetch(
                    "SELECT DISTINCT ON (pricing) pricing,bucket_start FROM usage_bucket_status "
                    "WHERE kind='mcp' AND bucket_start >= $1 AND bucket_start < $2 "
                    "ORDER BY pricing,bucket_start",
                    start,
                    end,
                )
                snapshots.sort(key=lambda row: row["bucket_start"])
                accounts = [
                    a
                    for snapshot in snapshots
                    for a in Catalogue.model_validate_json(snapshot["pricing"]).accounts
                    if a.billing_account == account.billing_account
                ]
                if accounts:
                    account = accounts[0]  # First collected plan, never today's mutable prices.
                records = await connection.fetch(
                    "SELECT * FROM usage_hourly_mcp "
                    "WHERE bucket_start >= $1 AND bucket_start < $2 AND billing_account=$3",
                    start,
                    end,
                    account.billing_account,
                )
                calls = sum((r["requests"] for r in records), Decimal(0))
                gross = sum((r["cost_usd"] for r in records), Decimal(0))
                coverage = await self.coverage(connection, "mcp", start, end)
                price = account.at(start)
                # New mid-cycle activation can show a partial estimate, but never
                # claim a full provider bill or repeat the fee per tool/person.
                if price is None and records:
                    price = account.at(min(r["bucket_start"] for r in records))
                known = all(r["cost_known"] == r["requests"] for r in records)
                units = all(
                    store.decode(r).dimensions.tool in account.verified_call_units for r in records
                )
                aligned = all(
                    next(hours(edge, edge + timedelta(seconds=1), self.timezone))[0] == edge
                    for edge in (start, end)
                )
                stable_plan = price is not None and all(
                    a.model_dump(exclude={"prices"}) == account.model_dump(exclude={"prices"})
                    and (
                        a.prices[0].monthly_fee,
                        a.prices[0].included_calls,
                        a.prices[0].monthly_credit,
                    )
                    == (price.monthly_fee, price.included_calls, price.monthly_credit)
                    for a in accounts
                )
                result.append(
                    ProviderEstimate(
                        billing_account=account.billing_account,
                        server=account.server,
                        period_start=start,
                        period_end=end,
                        gross_usage_usd=gross,
                        adjusted_estimate_usd=monthly_cost(price, calls, gross)
                        if price and known and stable_plan and aligned
                        else None,
                        complete=coverage.complete
                        and not coverage.stale
                        and not coverage.provisional
                        and known
                        and units
                        and account.complete_account_usage
                        and stable_plan
                        and aligned,
                    )
                )
        return result


def source_breakdown(
    rows: list[tuple[datetime, UsageRow]],
    kind: Kind,
    coverage: Coverage,
    timezone: str,
    start: date,
    end: date,
) -> UsageSourcesResponse:
    """Build independent app/key/origin views without counting any view twice."""
    apps: dict[str | None, UsageSource] = {}
    credentials: dict[tuple[str | None, str | None], UsageSource] = {}
    origins: dict[tuple[str | None, str | None], UsageSource] = {}
    people: dict[str | None, UsagePersonSources] = {}
    person_apps: dict[tuple[str | None, str | None], UsageSource] = {}
    person_keys: dict[tuple[str | None, str | None, str | None], UsageSource] = {}
    for _, row in rows:
        d = row.dimensions
        apps.setdefault(d.app_id, UsageSource(id=d.app_id)).add(row)
        key = (d.credential_id, d.credential_kind)
        credentials.setdefault(key, UsageSource(id=key[0], kind=key[1])).add(row)
        origin = (d.app_id, "app") if d.app_id is not None else key
        origins.setdefault(origin, UsageSource(id=origin[0], kind=origin[1])).add(row)
        person = people.setdefault(d.principal_id, UsagePersonSources(user_id=d.principal_id))
        person.total.add(row)
        app_key = (d.principal_id, d.app_id)
        if app_key not in person_apps:
            person_apps[app_key] = UsageSource(id=d.app_id)
            person.apps.append(person_apps[app_key])
        person_apps[app_key].add(row)
        person_key = (d.principal_id, *key)
        if person_key not in person_keys:
            person_keys[person_key] = UsageSource(id=key[0], kind=key[1])
            person.credentials.append(person_keys[person_key])
        person_keys[person_key].add(row)
    for value in [
        *apps.values(),
        *credentials.values(),
        *origins.values(),
        *person_apps.values(),
        *person_keys.values(),
        *(p.total for p in people.values()),
    ]:
        value.qualify(kind, coverage)
    return UsageSourcesResponse(
        timezone=timezone,
        start_date=start,
        end_date=end,
        coverage=coverage,
        apps=list(apps.values()),
        credentials=list(credentials.values()),
        origins=list(origins.values()),
        people=list(people.values()),
    )
