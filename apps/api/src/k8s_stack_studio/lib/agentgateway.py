"""AgentGateway private analytics client for per-user usage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.models.usage import AgentGatewaySummary, UsagePeriod, UsageResponse

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class AgentGatewayUsageError(RuntimeError):
    """AgentGateway could not provide a valid usage summary."""


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
