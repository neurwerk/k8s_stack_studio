from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.usage import (
    _require_self_or_usage_admin,
    get_user_usage,
)
from k8s_stack_studio.lib.agentgateway import AgentGatewayClient
from k8s_stack_studio.lib.auth import StudioPrincipal


@pytest.fixture
def agentgateway_settings() -> Settings:
    return Settings(
        agentgateway_admin_url="http://agentgateway:15000",
        usage_timezone="Europe/Berlin",
    )


def _summary(*, groups: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "timeRange": {"from": "ignored", "to": "ignored"},
        "bucketSeconds": 60,
        "buckets": [],
        "filterOptions": {},
        "groups": groups if groups is not None else [],
    }


@pytest.mark.asyncio
async def test_fetch_usage_sends_nine_sequential_utc_summaries(
    agentgateway_settings: Settings,
) -> None:
    now = datetime(2026, 9, 3, 12, tzinfo=UTC)
    payloads: list[dict[str, object]] = []
    active_requests = 0
    max_active_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active_requests, max_active_requests
        assert request.url.path == "/api/logs/analytics/summary"
        active_requests += 1
        max_active_requests = max(max_active_requests, active_requests)
        await asyncio.sleep(0)
        payloads.append(json.loads(request.content))
        active_requests -= 1
        return httpx.Response(
            200,
            json=_summary(
                groups=[
                    {
                        "group": {},
                        "requests": 7,
                        "totalTokens": 340,
                        "cost": None,
                        "unrelated": "ignored",
                    }
                ]
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = AgentGatewayClient(agentgateway_settings, client)
        with patch("k8s_stack_studio.lib.agentgateway._utc_now", return_value=now):
            usage = await gateway.fetch_usage("user-1")

    expected_ranges = [
        ("1970-01-01T00:00:00Z", "2026-09-03T12:00:00Z"),
        ("2026-08-31T22:00:00Z", "2026-09-03T12:00:00Z"),
        ("2026-07-31T22:00:00Z", "2026-08-31T22:00:00Z"),
        ("2026-08-04T12:00:00Z", "2026-09-03T12:00:00Z"),
        ("2026-08-30T22:00:00Z", "2026-09-03T12:00:00Z"),
        ("2026-08-23T22:00:00Z", "2026-08-30T22:00:00Z"),
        ("2026-08-27T12:00:00Z", "2026-09-03T12:00:00Z"),
        ("2026-09-02T22:00:00Z", "2026-09-03T12:00:00Z"),
        ("2026-09-02T12:00:00Z", "2026-09-03T12:00:00Z"),
    ]
    assert all(
        payload
        == {
            "timeRange": {"from": start, "to": end},
            "filters": {"attributes": {"agentgateway.user": "user-1"}},
            "groupBy": [],
            "bucketCount": 1,
        }
        for payload, (start, end) in zip(payloads, expected_ranges, strict=True)
    )
    assert max_active_requests == 1
    assert usage.total.requests == 7
    assert usage.this_month.total_tokens == 340
    assert usage.last_24_hours.cost_usd == 0.0


@pytest.mark.asyncio
async def test_fetch_usage_treats_empty_groups_as_zero(
    agentgateway_settings: Settings,
) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=_summary()))
    async with httpx.AsyncClient(transport=transport) as client:
        usage = await AgentGatewayClient(agentgateway_settings, client).fetch_usage("user-1")

    assert usage.total.requests == 0
    assert usage.total.total_tokens == 0
    assert usage.total.cost_usd == 0.0


async def _assert_safe_502(
    settings: Settings,
    handler,
) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = AgentGatewayClient(settings, client)
        with pytest.raises(HTTPException) as error:
            await get_user_usage("user-1", None, gateway)

    assert error.value.status_code == 502
    assert error.value.detail == "Usage analytics are temporarily unavailable."


@pytest.mark.asyncio
async def test_upstream_http_failure_becomes_safe_502(
    agentgateway_settings: Settings,
) -> None:
    await _assert_safe_502(
        agentgateway_settings,
        lambda _request: httpx.Response(503, text="internal upstream details"),
    )


@pytest.mark.asyncio
async def test_upstream_connectivity_failure_becomes_safe_502(
    agentgateway_settings: Settings,
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private address and request details", request=request)

    await _assert_safe_502(agentgateway_settings, fail)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={"groups": [{"requests": "7"}]}),
        httpx.Response(
            200,
            json=_summary(
                groups=[
                    {"group": {}, "requests": 1, "totalTokens": 2, "cost": 0.1},
                    {"group": {}, "requests": 3, "totalTokens": 4, "cost": 0.2},
                ]
            ),
        ),
    ],
    ids=["invalid-json", "invalid-model", "multiple-groups"],
)
async def test_malformed_upstream_response_becomes_safe_502(
    agentgateway_settings: Settings,
    response: httpx.Response,
) -> None:
    await _assert_safe_502(agentgateway_settings, lambda _request: response)


@pytest.mark.asyncio
async def test_usage_access_allows_self() -> None:
    request = MagicMock()
    request.scope = {"user": StudioPrincipal("user-1", frozenset(), frozenset(), {})}

    await _require_self_or_usage_admin("user-1", request)


@pytest.mark.asyncio
async def test_usage_access_rejects_non_admin_other_user() -> None:
    request = MagicMock()
    request.scope = {"user": StudioPrincipal("user-1", frozenset(), frozenset(), {})}

    with pytest.raises(HTTPException) as error:
        await _require_self_or_usage_admin("user-2", request)

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_usage_access_allows_langfuse_admin_for_other_user() -> None:
    request = MagicMock()
    request.scope = {
        "user": StudioPrincipal("user-1", frozenset({"langfuse-admin"}), frozenset(), {})
    }

    await _require_self_or_usage_admin("user-2", request)
