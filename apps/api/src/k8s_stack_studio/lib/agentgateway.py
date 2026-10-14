"""AgentGateway private analytics client for per-user usage."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from itertools import groupby, pairwise
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.models.gateway_metadata import GatewayFilters
from k8s_stack_studio.models.usage import (
    AgentGatewayDailySummary,
    AgentGatewayModelKey,
    AgentGatewaySummary,
    AgentGatewayUserSummary,
    DailyUsage,
    DailyUsageResponse,
    ModelUsage,
    UsagePeopleResponse,
    UsagePeriod,
    UsageResponse,
    UserUsageTotal,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_COMPLETENESS_GROUPS = [
    {"field": "attributes", "key": "neurwerk.token_usage_known"},
    {"field": "attributes", "key": "neurwerk.cost_known"},
]


class AgentGatewayUsageError(RuntimeError):
    """AgentGateway could not provide a valid usage summary."""


class InvalidUsageRangeError(ValueError):
    """The requested inclusive date range is invalid."""


def _utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


class AgentGatewayClient:
    """Query AgentGateway's private request-log analytics API."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        """Store AgentGateway connection and calendar settings."""
        self._base = settings.agentgateway_admin_url.rstrip("/")
        self._client = client
        self._timezone = ZoneInfo(settings.usage_timezone)

    async def fetch_daily_usage(
        self,
        user_id: str,
        start: date | None = None,
        end: date | None = None,
        filters: GatewayFilters | None = None,
    ) -> DailyUsageResponse:
        """Query consecutive equal-duration calendar days together, isolating today."""
        return await self._daily_usage(user_id, start, end, filters)

    async def fetch_all_daily_usage(
        self,
        start: date | None = None,
        end: date | None = None,
        filters: GatewayFilters | None = None,
    ) -> DailyUsageResponse:
        """Query aggregate model usage without a user filter (admin route only)."""
        return await self._daily_usage(None, start, end, filters)

    async def _daily_usage(
        self,
        user_id: str | None,
        start: date | None,
        end: date | None,
        filters: GatewayFilters | None,
    ) -> DailyUsageResponse:
        """Share one calendar and DST contract across self and all-user views."""
        now = _utc_now()
        start, end, midnights = self._calendar_window(start, end, now)
        days: list[DailyUsage] = []
        for (seconds, _partial), windows in groupby(
            pairwise(midnights),
            key=lambda window: (int((window[1] - window[0]).total_seconds()), window[1] > now),
        ):
            run = list(windows)
            days.extend(
                await self._fetch_daily_run(
                    user_id,
                    run[0][0],
                    min(run[-1][1], now),
                    seconds,
                    start + timedelta(days=len(days)),
                    len(run),
                    filters,
                )
            )
        return DailyUsageResponse(
            timezone=self._timezone.key,
            start_date=start,
            end_date=end,
            today=now.astimezone(self._timezone).date(),
            days=days,
        )

    def _calendar_window(
        self, start: date | None, end: date | None, now: datetime
    ) -> tuple[date, date, list[datetime]]:
        """Resolve an inclusive, bounded local date range to UTC midnight boundaries."""
        today = now.astimezone(self._timezone).date()
        end = end or today
        start = start or end - timedelta(days=min(29, end.toordinal() - 1))
        if start > end or end > today or (end - start).days >= 90:
            raise InvalidUsageRangeError
        try:
            midnights = [
                datetime.combine(
                    start + timedelta(days=offset), time.min, self._timezone
                ).astimezone(UTC)
                for offset in range((end - start).days + 2)
            ]
        except OverflowError as error:
            raise InvalidUsageRangeError from error
        return start, end, midnights

    async def fetch_user_breakdown(
        self,
        start: date | None = None,
        end: date | None = None,
        filters: GatewayFilters | None = None,
    ) -> UsagePeopleResponse:
        """Return only verified attributed user IDs and totals for admin selection."""
        now = _utc_now()
        start, end, midnights = self._calendar_window(start, end, now)
        until = min(midnights[-1], now)
        if until <= midnights[0]:
            return UsagePeopleResponse(
                timezone=self._timezone.key, start_date=start, end_date=end, users=[]
            )
        payload = self._summary_payload(None, midnights[0], until, filters)
        payload["groupBy"] = [
            {"field": "attributes", "key": "agentgateway.user"},
            *_COMPLETENESS_GROUPS,
        ]
        try:
            response = await self._client.post(
                f"{self._base}/api/logs/analytics/summary", json=payload
            )
            response.raise_for_status()
            summary = AgentGatewayUserSummary.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError, ValueError) as error:
            raise AgentGatewayUsageError from error
        users_by_id: dict[str, UserUsageTotal] = {}
        if len({item.group for item in summary.groups}) != len(summary.groups):
            raise AgentGatewayUsageError
        for item in summary.groups:
            user_id = item.group.user_id
            if user_id is None:
                continue  # A record without a verified principal is not a person.
            if not user_id or len(user_id) > 255:
                raise AgentGatewayUsageError
            users_by_id.setdefault(user_id, UserUsageTotal(user_id=user_id)).add(item)
        if len(users_by_id) > 5000:
            raise AgentGatewayUsageError
        users = list(users_by_id.values())
        users.sort(key=lambda item: (-item.total_tokens, item.user_id))
        return UsagePeopleResponse(
            timezone=self._timezone.key, start_date=start, end_date=end, users=users
        )

    async def _fetch_daily_run(
        self,
        user_id: str | None,
        start: datetime,
        end: datetime,
        seconds: int,
        first_day: date,
        day_count: int,
        filters: GatewayFilters | None,
    ) -> list[DailyUsage]:
        """Map aligned model buckets into days, including sparse and partial days."""
        days = {
            first_day + timedelta(days=offset): DailyUsage(
                date=first_day + timedelta(days=offset), models=[]
            )
            for offset in range(day_count)
        }
        if end <= start:
            # Keep skipped dates and midnight today empty; Gateway expands empty ranges.
            return list(days.values())
        payload = self._summary_payload(user_id, start, end, filters)
        del payload["bucketCount"]
        payload["bucketSeconds"] = seconds
        payload["groupBy"] = [{"field": "requestModel"}, *_COMPLETENESS_GROUPS]
        try:
            response = await self._client.post(
                f"{self._base}/api/logs/analytics/summary", json=payload
            )
            response.raise_for_status()
            summary = AgentGatewayDailySummary.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError, ValueError) as error:
            raise AgentGatewayUsageError from error
        # Gateway clamps bucketSeconds to the whole-second span for a partial day.
        effective_seconds = min(seconds, max(1, int((end - start).total_seconds())))
        if summary.bucket_seconds != effective_seconds:
            raise AgentGatewayUsageError
        if len({group.group for group in summary.groups}) != len(summary.groups):
            raise AgentGatewayUsageError
        seen: set[tuple[datetime, AgentGatewayModelKey]] = set()
        models: dict[tuple[date, str | None], ModelUsage] = {}
        for bucket in summary.buckets:
            key = (bucket.start, bucket.group)
            if (
                not start <= bucket.start < end
                or (bucket.start - start) % timedelta(seconds=effective_seconds)
                or key in seen
            ):
                raise AgentGatewayUsageError
            seen.add(key)
            day = first_day + timedelta(days=(bucket.start - start) // timedelta(seconds=seconds))
            model_key = (day, bucket.group.request_model)
            if model_key not in models:
                models[model_key] = ModelUsage(model=bucket.group.request_model)
                days[day].models.append(models[model_key])
            # Fractional partial-day spans can produce two clamped upstream buckets.
            models[model_key].add(bucket)
        for usage in days.values():
            usage.models.sort(key=lambda item: (item.model is not None, item.model or ""))
        return list(days.values())

    async def fetch_usage(
        self, user_id: str, filters: GatewayFilters | None = None
    ) -> UsageResponse:
        """Return all supported calendar and rolling usage periods for a user."""
        now = _utc_now()
        usage: dict[str, UsagePeriod] = {}
        for name, (start, end) in self._periods(now).items():
            usage[name] = await self._fetch_period(user_id, start, end, filters)
        return UsageResponse.model_validate(usage)

    def _periods(self, now: datetime) -> dict[str, tuple[datetime, datetime]]:
        """Build the nine calendar and rolling periods in request order."""
        local_now = now.astimezone(self._timezone)
        today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        last_month_start = (month_start - timedelta(days=1)).replace(day=1)
        return {
            "total": (_EPOCH, now),
            "this_month": (month_start, local_now),
            "last_month": (last_month_start, month_start),
            "last_30_days": (now - timedelta(days=30), now),
            "this_week": (week_start, local_now),
            "last_week": (week_start - timedelta(days=7), week_start),
            "last_7_days": (now - timedelta(days=7), now),
            "today": (today, local_now),
            "last_24_hours": (now - timedelta(hours=24), now),
        }

    async def _fetch_period(
        self,
        user_id: str,
        start: datetime,
        end: datetime,
        filters: GatewayFilters | None,
    ) -> UsagePeriod:
        """Fetch and combine groups that retain native completeness evidence."""
        try:
            response = await self._client.post(
                f"{self._base}/api/logs/analytics/summary",
                json=self._summary_payload(user_id, start, end, filters),
            )
            response.raise_for_status()
            summary = AgentGatewaySummary.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as error:
            raise AgentGatewayUsageError from error

        if len({item.group for item in summary.groups}) != len(summary.groups):
            raise AgentGatewayUsageError
        usage = UsagePeriod()
        for group in summary.groups:
            usage.add(group)
        return usage

    @classmethod
    def _summary_payload(
        cls,
        user_id: str | None,
        start: datetime,
        end: datetime,
        filters: GatewayFilters | None = None,
    ) -> dict[str, object]:
        """Create the private analytics request for one principal and period."""
        payload: dict[str, object] = {
            "timeRange": {
                "from": cls._isoformat_utc(start),
                "to": cls._isoformat_utc(end),
            },
            "groupBy": _COMPLETENESS_GROUPS,
            "bucketCount": 1,
        }
        attributes = filters.attributes() if filters else {}
        if user_id is not None:
            attributes["agentgateway.user"] = user_id
        if attributes:
            payload["filters"] = {"attributes": attributes}
        return payload

    @staticmethod
    def _isoformat_utc(value: datetime) -> str:
        """Serialize a datetime as an ISO 8601 UTC timestamp."""
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
