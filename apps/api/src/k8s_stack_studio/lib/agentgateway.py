"""AgentGateway private analytics client for per-user usage."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from itertools import groupby, pairwise
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.models.usage import (
    AgentGatewayDailySummary,
    AgentGatewaySummary,
    DailyUsage,
    DailyUsageResponse,
    ModelUsage,
    UsagePeriod,
    UsageResponse,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


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
        self, user_id: str, start: date | None = None, end: date | None = None
    ) -> DailyUsageResponse:
        """Query consecutive equal-duration calendar days together, isolating today."""
        now = _utc_now()
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
                )
            )
        return DailyUsageResponse(
            timezone=self._timezone.key,
            start_date=start,
            end_date=end,
            today=today,
            days=days,
        )

    async def _fetch_daily_run(
        self,
        user_id: str,
        start: datetime,
        end: datetime,
        seconds: int,
        first_day: date,
        day_count: int,
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
        payload = self._summary_payload(user_id, start, end)
        del payload["bucketCount"]
        payload["bucketSeconds"] = seconds
        payload["groupBy"] = [{"field": "requestModel"}]
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
        if len({group.group.request_model for group in summary.groups}) != len(summary.groups):
            raise AgentGatewayUsageError
        seen: set[tuple[datetime, str | None]] = set()
        models: dict[tuple[date, str | None], ModelUsage] = {}
        for bucket in summary.buckets:
            key = (bucket.start, bucket.group.request_model)
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
            model = models[model_key]
            model.requests += bucket.requests
            model.total_tokens += bucket.total_tokens
            model.cost_usd += bucket.cost or 0.0
        for usage in days.values():
            usage.models.sort(key=lambda item: (item.model is not None, item.model or ""))
        return list(days.values())

    async def fetch_usage(self, user_id: str) -> UsageResponse:
        """Return all supported calendar and rolling usage periods for a user."""
        now = _utc_now()
        usage: dict[str, UsagePeriod] = {}
        for name, (start, end) in self._periods(now).items():
            usage[name] = await self._fetch_period(user_id, start, end)
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
    ) -> UsagePeriod:
        """Fetch and validate one ungrouped analytics summary."""
        try:
            response = await self._client.post(
                f"{self._base}/api/logs/analytics/summary",
                json=self._summary_payload(user_id, start, end),
            )
            response.raise_for_status()
            summary = AgentGatewaySummary.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as error:
            raise AgentGatewayUsageError from error

        if len(summary.groups) > 1:
            raise AgentGatewayUsageError
        if not summary.groups:
            return UsagePeriod()

        group = summary.groups[0]
        return UsagePeriod(
            requests=group.requests,
            total_tokens=group.total_tokens,
            cost_usd=group.cost or 0.0,
        )

    @classmethod
    def _summary_payload(
        cls,
        user_id: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, object]:
        """Create the private analytics request for one principal and period."""
        return {
            "timeRange": {
                "from": cls._isoformat_utc(start),
                "to": cls._isoformat_utc(end),
            },
            "filters": {"attributes": {"agentgateway.user": user_id}},
            "groupBy": [],
            "bucketCount": 1,
        }

    @staticmethod
    def _isoformat_utc(value: datetime) -> str:
        """Serialize a datetime as an ISO 8601 UTC timestamp."""
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
