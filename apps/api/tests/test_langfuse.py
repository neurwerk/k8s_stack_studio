"""Tests for Langfuse per-user token and cost usage aggregation."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.usage import _require_self_or_langfuse_admin
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.langfuse import LangfuseClient


@pytest.fixture
def langfuse_settings() -> Settings:
    """Return minimal Langfuse settings for client tests."""
    return Settings(
        langfuse_url="http://langfuse:3000",
        langfuse_public_key="public",
        langfuse_secret_key="secret",
        usage_timezone="Europe/Berlin",
    )


def _response(data: dict[str, object]) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = data
    return response


def _daily_response() -> dict[str, object]:
    return {
        "data": [
            {
                "usage": [
                    {
                        "inputUsage": 12,
                        "outputUsage": 5,
                        "totalUsage": 17,
                        "totalCost": 0.0012,
                    }
                ]
            }
        ],
        "meta": {"page": 1, "totalPages": 1},
    }


def _observations_response() -> dict[str, object]:
    return {
        "data": [
            {
                "promptTokens": 9,
                "completionTokens": 3,
                "totalTokens": 12,
                "costDetails": {"total": 0.0009},
            }
        ],
        "meta": {"page": 1, "totalPages": 1},
    }


@pytest.mark.asyncio
async def test_fetch_usage_aggregates_calendar_and_rolling_periods(
    langfuse_settings: Settings,
) -> None:
    """fetch_usage combines daily metrics and generation observations."""
    client = MagicMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(
        side_effect=[
            _response(_daily_response()),
            _response(_daily_response()),
            _response(_daily_response()),
            _response(_daily_response()),
            _response(_daily_response()),
            _response(_daily_response()),
            _response(_observations_response()),
            _response(_observations_response()),
            _response(_observations_response()),
        ]
    )
    langfuse = LangfuseClient(settings=langfuse_settings, client=client)

    usage = await langfuse.fetch_usage("user-1")

    assert usage.total.total_tokens == 17
    assert usage.this_month.cost_usd == 0.0012
    assert usage.last_month.cost_usd == 0.0012
    assert usage.last_30_days.input_tokens == 9
    assert usage.last_7_days.output_tokens == 3
    assert usage.last_24_hours.cost_usd == 0.0009
    assert client.get.await_count == 9


def test_calendar_periods_use_configured_timezone(langfuse_settings: Settings) -> None:
    """Calendar periods begin at Berlin-local boundaries and convert to UTC later."""
    client = MagicMock(spec=httpx.AsyncClient)
    langfuse = LangfuseClient(settings=langfuse_settings, client=client)
    now = datetime(2026, 8, 12, 12, tzinfo=UTC)

    periods = langfuse._calendar_periods(now)

    assert periods["today"][0].isoformat() == "2026-08-12T00:00:00+02:00"
    assert periods["this_week"][0].isoformat() == "2026-08-10T00:00:00+02:00"
    assert periods["this_month"][0].isoformat() == "2026-08-01T00:00:00+02:00"


def test_daily_params_use_utc_timestamps() -> None:
    """Daily metric parameters serialize local period boundaries as UTC timestamps."""
    start = datetime(2026, 8, 12, 0, tzinfo=UTC)
    end = datetime(2026, 8, 13, 0, tzinfo=UTC)

    params = LangfuseClient._daily_params("user-1", start, end, 3)

    assert params["userId"] == "user-1"
    assert params["page"] == 3
    assert params["fromTimestamp"] == "2026-08-12T00:00:00+00:00"


def test_total_params_omit_date_range() -> None:
    """The all-time query omits dates to avoid Langfuse's epoch parsing bug."""
    params = LangfuseClient._daily_params("user-1", None, None, 1)

    assert params == {"userId": "user-1", "page": 1, "limit": 100}


@pytest.mark.asyncio
async def test_usage_access_allows_self() -> None:
    """The usage route permits authenticated users to access their own totals."""
    request = MagicMock()
    request.scope = {"user": StudioPrincipal("user-1", frozenset(), frozenset(), {})}

    await _require_self_or_langfuse_admin("user-1", request)


@pytest.mark.asyncio
async def test_usage_access_rejects_non_admin_other_user() -> None:
    """The usage route rejects users without langfuse-admin for another profile."""
    request = MagicMock()
    request.scope = {"user": StudioPrincipal("user-1", frozenset(), frozenset(), {})}

    with pytest.raises(HTTPException) as exc_info:
        await _require_self_or_langfuse_admin("user-2", request)

    assert exc_info.value.status_code == 403
