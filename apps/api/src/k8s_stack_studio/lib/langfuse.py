"""Langfuse public API client for per-user token and cost usage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.models.usage import (
    LangfuseDailyMetricsResponse,
    LangfuseObservationsResponse,
    UsagePeriod,
    UsageResponse,
)


class LangfuseClient:
    """Query Langfuse's legacy public usage APIs with project-scoped credentials."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        """Store Langfuse connection settings and the shared HTTP client."""
        self._base = settings.langfuse_url.rstrip("/")
        self._client = client
        self._auth = httpx.BasicAuth(settings.langfuse_public_key, settings.langfuse_secret_key)
        self._timezone = ZoneInfo(settings.usage_timezone)

    async def fetch_usage(self, user_id: str) -> UsageResponse:
        """Return all supported calendar and rolling usage periods for a user."""
        now = datetime.now(UTC)
        calendar_periods = self._calendar_periods(now)
        rolling_periods = self._rolling_periods(now)
        calendar_usage = await self._fetch_daily_periods(user_id, calendar_periods)
        rolling_usage = await self._fetch_observation_periods(user_id, rolling_periods)
        return UsageResponse(**calendar_usage, **rolling_usage)

    def _calendar_periods(self, now: datetime) -> dict[str, tuple[datetime, datetime]]:
        local_now = now.astimezone(self._timezone)
        today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        previous_month_end = month_start
        last_month = (previous_month_end - timedelta(days=1)).replace(day=1)
        return {
            "this_month": (month_start, local_now),
            "last_month": (last_month, previous_month_end),
            "this_week": (week_start, local_now),
            "last_week": (week_start - timedelta(days=7), week_start),
            "today": (today, local_now),
        }

    @staticmethod
    def _rolling_periods(now: datetime) -> dict[str, tuple[datetime, datetime]]:
        return {
            "last_30_days": (now - timedelta(days=30), now),
            "last_7_days": (now - timedelta(days=7), now),
            "last_24_hours": (now - timedelta(hours=24), now),
        }

    async def _fetch_daily_periods(
        self, user_id: str, periods: dict[str, tuple[datetime, datetime]]
    ) -> dict[str, UsagePeriod]:
        period_usage = {
            name: await self._fetch_daily_usage(user_id, start, end)
            for name, (start, end) in periods.items()
        }
        period_usage["total"] = await self._fetch_daily_usage(user_id)
        return period_usage

    async def _fetch_observation_periods(
        self, user_id: str, periods: dict[str, tuple[datetime, datetime]]
    ) -> dict[str, UsagePeriod]:
        return {
            name: await self._fetch_observation_usage(user_id, start, end)
            for name, (start, end) in periods.items()
        }

    async def _fetch_daily_usage(
        self,
        user_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> UsagePeriod:
        page = 1
        usage = UsagePeriod()
        while True:
            response = await self._get_daily_page(user_id, start, end, page)
            for day in response.data:
                for item in day.usage:
                    usage.input_tokens += item.input_usage
                    usage.output_tokens += item.output_usage
                    usage.total_tokens += item.total_usage
                    usage.cost_usd += item.total_cost
            if page >= response.meta.total_pages:
                return usage
            page += 1

    async def _fetch_observation_usage(
        self, user_id: str, start: datetime, end: datetime
    ) -> UsagePeriod:
        page = 1
        usage = UsagePeriod()
        while True:
            response = await self._get_observations_page(user_id, start, end, page)
            for observation in response.data:
                usage.input_tokens += observation.prompt_tokens
                usage.output_tokens += observation.completion_tokens
                usage.total_tokens += observation.total_tokens
                usage.cost_usd += observation.cost_details.total
            if page >= response.meta.total_pages:
                return usage
            page += 1

    async def _get_daily_page(
        self,
        user_id: str,
        start: datetime | None,
        end: datetime | None,
        page: int,
    ) -> LangfuseDailyMetricsResponse:
        response = await self._client.get(
            f"{self._base}/api/public/metrics/daily",
            auth=self._auth,
            params=self._daily_params(user_id, start, end, page),
        )
        response.raise_for_status()
        return LangfuseDailyMetricsResponse.model_validate(response.json())

    async def _get_observations_page(
        self, user_id: str, start: datetime, end: datetime, page: int
    ) -> LangfuseObservationsResponse:
        response = await self._client.get(
            f"{self._base}/api/public/observations",
            auth=self._auth,
            params=self._observation_params(user_id, start, end, page),
        )
        response.raise_for_status()
        return LangfuseObservationsResponse.model_validate(response.json())

    @staticmethod
    def _daily_params(
        user_id: str,
        start: datetime | None,
        end: datetime | None,
        page: int,
    ) -> dict[str, str | int]:
        params: dict[str, str | int] = {
            "userId": user_id,
            "page": page,
            "limit": 100,
        }
        if start is not None:
            params["fromTimestamp"] = start.astimezone(UTC).isoformat()
        if end is not None:
            params["toTimestamp"] = end.astimezone(UTC).isoformat()
        return params

    @staticmethod
    def _observation_params(
        user_id: str, start: datetime, end: datetime, page: int
    ) -> dict[str, str | int]:
        return {
            "userId": user_id,
            "type": "GENERATION",
            "fromStartTime": start.astimezone(UTC).isoformat(),
            "toStartTime": end.astimezone(UTC).isoformat(),
            "page": page,
            "limit": 100,
        }
