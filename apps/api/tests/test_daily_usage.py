from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TypedDict
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.usage import aggregate_router, router
from k8s_stack_studio.lib.agentgateway import AgentGatewayClient
from k8s_stack_studio.lib.auth import StudioAdmissionMiddleware, StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_agentgateway


class DailyTestState(TypedDict):
    now: datetime
    principal: StudioPrincipal | None
    response: httpx.Response | Exception | None
    active: int
    max_active: int


@pytest.fixture
async def daily_api(request):
    payloads = []
    state: DailyTestState = {
        "now": datetime(2026, 11, 2, 12, tzinfo=UTC),
        "principal": StudioPrincipal("self", frozenset({"studio-user"}), frozenset(), {}),
        "response": None,
        "active": 0,
        "max_active": 0,
    }

    async def upstream(request):
        assert request.url.path == "/api/logs/analytics/summary"
        assert request.method == "POST"
        payload = json.loads(request.content)
        payloads.append(payload)
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        await asyncio.sleep(0)
        state["active"] -= 1
        if isinstance(state["response"], Exception):
            raise state["response"]
        if state["response"] is not None:
            return state["response"]
        groups = [
            {"group": {"requestModel": "model-b"}, "requests": 2, "totalTokens": 100, "cost": 0.25},
            {"group": {"requestModel": None}, "requests": 1, "totalTokens": 0},
            {"group": {"requestModel": "model-a"}, "requests": 3, "totalTokens": 80, "cost": None},
        ]
        start = datetime.fromisoformat(payload["timeRange"]["from"])
        end = datetime.fromisoformat(payload["timeRange"]["to"])
        seconds = min(payload["bucketSeconds"], max(1, int((end - start).total_seconds())))
        buckets = []
        timestamp = start
        while timestamp < end:
            buckets.extend({"start": timestamp.isoformat(), **group} for group in groups)
            timestamp += timedelta(seconds=seconds)
        return httpx.Response(
            200,
            json={
                "bucketSeconds": seconds,
                "groups": groups,
                "buckets": buckets,
                "filterOptions": {"requestModel": ["other-users-private-model"]},
            },
        )

    app = FastAPI()
    app.include_router(router)
    app.include_router(aggregate_router)
    app.add_middleware(StudioAdmissionMiddleware)

    @app.middleware("http")
    async def identity(request, call_next):
        if state["principal"] is not None:
            request.scope["user"] = state["principal"]
        return await call_next(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as upstream_client:
        gateway = AgentGatewayClient(
            Settings(usage_timezone=getattr(request, "param", "Europe/Berlin")), upstream_client
        )
        app.dependency_overrides[get_agentgateway] = lambda: gateway
        with patch("k8s_stack_studio.lib.agentgateway._utc_now", side_effect=lambda: state["now"]):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                yield client, payloads, state


async def test_daily_default_contract_and_sequential_runs(daily_api):
    client, payloads, state = daily_api
    response = await client.get("/api/users/self/usage/daily")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"timezone", "start_date", "end_date", "today", "days"}
    assert body["timezone"] == "Europe/Berlin"
    assert body["start_date"] == "2026-10-04"
    assert body["end_date"] == body["today"] == "2026-11-02"
    assert len(body["days"]) == 30
    assert len(payloads) == 4
    assert [day["date"] for day in body["days"]] == sorted(day["date"] for day in body["days"])
    assert body["days"][0]["models"] == [
        {"model": None, "requests": 1, "total_tokens": 0, "cost_usd": 0.0},
        {"model": "model-a", "requests": 3, "total_tokens": 80, "cost_usd": 0.0},
        {"model": "model-b", "requests": 2, "total_tokens": 100, "cost_usd": 0.25},
    ]
    assert "filterOptions" not in response.text
    assert "other-users-private-model" not in response.text
    assert all(day["models"] == body["days"][0]["models"] for day in body["days"])
    assert state["max_active"] == 1
    assert payloads[-1]["timeRange"]["to"] == "2026-11-02T12:00:00Z"
    for payload in payloads:
        assert payload["filters"] == {"attributes": {"agentgateway.user": "self"}}
        assert payload["groupBy"] == [{"field": "requestModel"}]
        assert "bucketCount" not in payload


async def test_all_user_usage_requires_usage_admin_before_any_upstream_request(daily_api):
    client, payloads, _state = daily_api
    for path in ("/api/usage/daily", "/api/usage/people"):
        assert (await client.get(path)).status_code == 403
    assert payloads == []


async def test_all_daily_usage_reuses_bounded_calendar_contract_without_user_filter(daily_api):
    client, payloads, state = daily_api
    state["principal"] = StudioPrincipal(
        "admin", frozenset({"studio-user", "langfuse-admin"}), frozenset(), {}
    )
    response = await client.get("/api/usage/daily?start=2026-10-25&end=2026-10-25")
    assert response.status_code == 200
    assert response.json()["days"][0]["date"] == "2026-10-25"
    assert len(payloads) == 1
    assert "filters" not in payloads[0]
    assert payloads[0]["timeRange"] == {
        "from": "2026-10-24T22:00:00Z",
        "to": "2026-10-25T23:00:00Z",
    }
    assert payloads[0]["bucketSeconds"] == 90000
    assert (await client.get("/api/usage/daily?start=2026-13-01")).status_code == 422
    assert (await client.get("/api/usage/daily?start=2026-01-01")).status_code == 422
    assert len(payloads) == 1


async def test_people_returns_sorted_attributed_users_without_upstream_metadata(daily_api):
    client, payloads, state = daily_api
    state["principal"] = StudioPrincipal(
        "admin", frozenset({"studio-user", "langfuse-admin"}), frozenset(), {}
    )
    state["response"] = httpx.Response(
        200,
        json={
            "groups": [
                {
                    "group": {"agentgateway.user": "person-b"},
                    "requests": 1,
                    "totalTokens": 5,
                    "cost": None,
                },
                {
                    "group": {"agentgateway.user": None},
                    "requests": 1,
                    "totalTokens": 99,
                    "cost": 0.1,
                },
                {
                    "group": {"attributes": {"agentgateway.user": "person-a"}},
                    "requests": 2,
                    "totalTokens": 10,
                    "cost": 0.25,
                },
            ],
            "filterOptions": {"agentgateway.user": ["private-other-user"]},
        },
    )
    response = await client.get("/api/usage/people?start=2026-10-25&end=2026-10-25")
    assert response.status_code == 200
    assert response.json() == {
        "timezone": "Europe/Berlin",
        "start_date": "2026-10-25",
        "end_date": "2026-10-25",
        "users": [
            {"user_id": "person-a", "requests": 2, "total_tokens": 10, "cost_usd": 0.25},
            {"user_id": "person-b", "requests": 1, "total_tokens": 5, "cost_usd": 0.0},
        ],
    }
    assert "filters" not in payloads[0]
    assert payloads[0]["groupBy"] == [{"field": "attributes", "key": "agentgateway.user"}]
    assert "filterOptions" not in response.text


async def test_people_rejects_duplicate_or_invalid_upstream_id(daily_api):
    client, _payloads, state = daily_api
    state["principal"] = StudioPrincipal(
        "admin", frozenset({"studio-user", "langfuse-admin"}), frozenset(), {}
    )
    state["response"] = httpx.Response(
        200,
        json={
            "groups": [
                {"group": {"agentgateway.user": "same"}, "requests": 1, "totalTokens": 1},
                {"group": {"agentgateway.user": "same"}, "requests": 1, "totalTokens": 1},
            ]
        },
    )
    assert (await client.get("/api/usage/people")).status_code == 502
    state["response"] = httpx.Response(
        200,
        json={
            "groups": [
                {"group": {"agentgateway.user": 123}, "requests": 1, "totalTokens": 1},
            ]
        },
    )
    assert (await client.get("/api/usage/people")).status_code == 502


@pytest.mark.parametrize(
    ("day", "start", "end", "seconds"),
    [
        ("2026-03-29", "2026-03-28T23:00:00Z", "2026-03-29T22:00:00Z", 82800),
        ("2026-10-25", "2026-10-24T22:00:00Z", "2026-10-25T23:00:00Z", 90000),
        ("2026-10-26", "2026-10-25T23:00:00Z", "2026-10-26T23:00:00Z", 86400),
    ],
)
async def test_daily_inclusive_dst_boundaries(daily_api, day, start, end, seconds):
    client, payloads, _state = daily_api
    response = await client.get(f"/api/users/self/usage/daily?start={day}&end={day}")
    assert response.status_code == 200
    assert len(response.json()["days"]) == 1
    assert payloads[0]["timeRange"] == {"from": start, "to": end}
    assert payloads[0]["bucketSeconds"] == seconds


@pytest.mark.parametrize(
    ("start", "now", "ranges"),
    [
        (
            "2026-03-27",
            datetime(2026, 3, 31, 12, tzinfo=UTC),
            [
                ("2026-03-26T23:00:00Z", "2026-03-28T23:00:00Z", 86400),
                ("2026-03-28T23:00:00Z", "2026-03-29T22:00:00Z", 82800),
                ("2026-03-29T22:00:00Z", "2026-03-30T22:00:00Z", 86400),
                ("2026-03-30T22:00:00Z", "2026-03-31T12:00:00Z", 86400),
            ],
        ),
        (
            "2026-10-23",
            datetime(2026, 10, 27, 12, tzinfo=UTC),
            [
                ("2026-10-22T22:00:00Z", "2026-10-24T22:00:00Z", 86400),
                ("2026-10-24T22:00:00Z", "2026-10-25T23:00:00Z", 90000),
                ("2026-10-25T23:00:00Z", "2026-10-26T23:00:00Z", 86400),
                ("2026-10-26T23:00:00Z", "2026-10-27T12:00:00Z", 86400),
            ],
        ),
    ],
)
async def test_daily_splits_dst_runs_and_partial_today(daily_api, start, now, ranges):
    client, payloads, state = daily_api
    state["now"] = now
    response = await client.get(f"/api/users/self/usage/daily?start={start}")
    assert response.status_code == 200
    assert len(response.json()["days"]) == 5
    assert [
        (payload["timeRange"]["from"], payload["timeRange"]["to"], payload["bucketSeconds"])
        for payload in payloads
    ] == ranges
    assert state["max_active"] == 1


async def test_daily_maps_sparse_model_buckets_not_run_totals(daily_api):
    client, payloads, state = daily_api
    state["response"] = httpx.Response(
        200,
        json={
            "bucketSeconds": 86400,
            "groups": [
                {"group": {"requestModel": None}, "requests": 5, "totalTokens": 50, "cost": 0.75}
            ],
            "buckets": [
                {
                    "start": "2026-06-01T22:00:00Z",
                    "group": {"requestModel": None},
                    "requests": 2,
                    "totalTokens": 20,
                    "cost": 0.25,
                },
                {
                    "start": "2026-06-02T22:00:00Z",
                    "group": {"requestModel": None},
                    "requests": 3,
                    "totalTokens": 30,
                    "cost": 0.5,
                },
            ],
        },
    )
    response = await client.get("/api/users/self/usage/daily?start=2026-06-01&end=2026-06-04")
    assert response.status_code == 200
    assert len(payloads) == 1
    assert response.json()["days"] == [
        {"date": "2026-06-01", "models": []},
        {
            "date": "2026-06-02",
            "models": [{"model": None, "requests": 2, "total_tokens": 20, "cost_usd": 0.25}],
        },
        {
            "date": "2026-06-03",
            "models": [{"model": None, "requests": 3, "total_tokens": 30, "cost_usd": 0.5}],
        },
        {"date": "2026-06-04", "models": []},
    ]


async def test_daily_partial_fractional_span_combines_clamped_buckets(daily_api):
    client, payloads, state = daily_api
    state["now"] = datetime(2026, 11, 2, 12, microsecond=500000, tzinfo=UTC)
    response = await client.get("/api/users/self/usage/daily?start=2026-11-02")
    assert response.status_code == 200
    assert len(payloads) == 1
    assert payloads[0]["bucketSeconds"] == 86400
    assert payloads[0]["timeRange"]["to"] == "2026-11-02T12:00:00.500000Z"
    assert response.json()["days"][0]["models"] == [
        {"model": None, "requests": 2, "total_tokens": 0, "cost_usd": 0.0},
        {"model": "model-a", "requests": 6, "total_tokens": 160, "cost_usd": 0.0},
        {"model": "model-b", "requests": 4, "total_tokens": 200, "cost_usd": 0.5},
    ]


@pytest.mark.parametrize("seconds", [60, 86400])
async def test_daily_rejects_wrong_bucket_width_or_duplicate_bucket(daily_api, seconds):
    client, _payloads, state = daily_api
    bucket = {
        "start": "2026-05-31T22:00:00Z",
        "group": {"requestModel": None},
        "requests": 1,
        "totalTokens": 2,
    }
    state["response"] = httpx.Response(
        200,
        json={
            "bucketSeconds": seconds,
            "groups": [],
            "buckets": [bucket, bucket],
        },
    )
    response = await client.get("/api/users/self/usage/daily?start=2026-06-01&end=2026-06-02")
    assert response.status_code == 502


@pytest.mark.parametrize(
    "query",
    [
        "start=2026-02-30",
        "end=not-a-date",
        "start=20261101",
        "start=1793577600",
        "start=2026-11-01T00:00:00Z",
        "start=2026-1-01",
        "end=",
        "start=2026-11-02&end=2026-11-01",
        "end=2026-11-03",
        "start=2026-08-04",
        "start=0001-01-01&end=0001-01-01",
        "end=0001-01-01",
    ],
)
async def test_daily_rejects_invalid_ranges_before_upstream(daily_api, query):
    client, payloads, _state = daily_api
    response = await client.get(f"/api/users/self/usage/daily?{query}")
    assert response.status_code == 422
    assert payloads == []


@pytest.mark.parametrize(
    ("query", "first", "last", "count", "queries"),
    [
        ("start=2026-08-05", "2026-08-05", "2026-11-02", 90, 4),
        ("end=2026-10-31", "2026-10-02", "2026-10-31", 30, 3),
        ("start=2026-11-01", "2026-11-01", "2026-11-02", 2, 2),
        ("start=2026-06-01&end=2026-08-29", "2026-06-01", "2026-08-29", 90, 1),
    ],
)
async def test_daily_optional_bounds_and_maximum(daily_api, query, first, last, count, queries):
    client, payloads, state = daily_api
    response = await client.get(f"/api/users/self/usage/daily?{query}")
    assert response.status_code == 200
    assert response.json()["start_date"] == first
    assert response.json()["end_date"] == last
    assert len(response.json()["days"]) == count
    assert len(payloads) == queries
    assert state["max_active"] == 1


async def test_daily_midnight_skips_empty_upstream_range(daily_api):
    client, payloads, state = daily_api
    state["now"] = datetime(2026, 11, 1, 23, tzinfo=UTC)
    response = await client.get("/api/users/self/usage/daily?start=2026-11-02")
    assert response.status_code == 200
    assert response.json()["days"] == [{"date": "2026-11-02", "models": []}]
    assert payloads == []


@pytest.mark.parametrize("daily_api", ["Pacific/Apia"], indirect=True)
@pytest.mark.parametrize(
    ("start", "end", "labels", "queries"),
    [
        ("2011-12-30", "2011-12-30", ["2011-12-30"], 0),
        ("2011-12-30", "2011-12-31", ["2011-12-30", "2011-12-31"], 1),
        ("2011-12-29", "2011-12-31", ["2011-12-29", "2011-12-30", "2011-12-31"], 2),
    ],
)
async def test_daily_preserves_skipped_calendar_date(daily_api, start, end, labels, queries):
    client, payloads, _state = daily_api
    response = await client.get(f"/api/users/self/usage/daily?start={start}&end={end}")
    assert response.status_code == 200
    days = response.json()["days"]
    assert [day["date"] for day in days] == labels
    assert response.json()["timezone"] == "Pacific/Apia"
    assert len(payloads) == queries
    assert all(payload["bucketSeconds"] == 86400 for payload in payloads)
    for day in days:
        if day["date"] == "2011-12-30":
            assert day["models"] == []
        else:
            assert day["models"][2] == {
                "model": "model-b",
                "requests": 2,
                "total_tokens": 100,
                "cost_usd": 0.25,
            }


async def test_daily_requires_authentication(daily_api):
    client, payloads, state = daily_api
    state["principal"] = None
    response = await client.get("/api/users/self/usage/daily")
    assert response.status_code == 401
    assert payloads == []


async def test_daily_timezone_environment_controls_today_and_boundaries(monkeypatch):
    monkeypatch.setenv("K8S_STUDIO_USAGE_TIMEZONE", "America/New_York")
    now = datetime(2026, 3, 9, 2, tzinfo=UTC)
    payloads = []

    def upstream(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        start = datetime.fromisoformat(payload["timeRange"]["from"])
        end = datetime.fromisoformat(payload["timeRange"]["to"])
        seconds = min(payload["bucketSeconds"], int((end - start).total_seconds()))
        return httpx.Response(200, json={"bucketSeconds": seconds, "groups": [], "buckets": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        with patch("k8s_stack_studio.lib.agentgateway._utc_now", return_value=now):
            response = await AgentGatewayClient(Settings(), client).fetch_daily_usage("self")
    assert response.timezone == "America/New_York"
    assert response.today.isoformat() == "2026-03-08"
    assert payloads[-1]["timeRange"] == {
        "from": "2026-03-08T05:00:00Z",
        "to": "2026-03-09T02:00:00Z",
    }
    assert payloads[-1]["bucketSeconds"] == 82800


async def test_daily_failure_stops_before_remaining_runs(daily_api):
    client, payloads, state = daily_api
    state["response"] = httpx.Response(503)
    response = await client.get("/api/users/self/usage/daily?start=2026-08-05")
    assert response.status_code == 502
    assert len(payloads) == 1


async def test_daily_empty_days_remain_in_response(daily_api):
    client, _payloads, state = daily_api
    state["response"] = httpx.Response(
        200, json={"bucketSeconds": 86400, "groups": [], "buckets": []}
    )
    response = await client.get("/api/users/self/usage/daily?start=2026-10-31&end=2026-11-01")
    assert response.status_code == 200
    assert response.json()["days"] == [
        {"date": "2026-10-31", "models": []},
        {"date": "2026-11-01", "models": []},
    ]


@pytest.mark.parametrize(
    ("roles", "target", "status"),
    [
        ({"studio-user"}, "other", 403),
        ({"studio-user", "keycloak-admin"}, "other", 403),
        ({"studio-user", "langfuse-admin"}, "other", 200),
        ({"langfuse-admin"}, "self", 403),
        (set(), "self", 403),
    ],
)
async def test_daily_route_authorization(daily_api, roles, target, status):
    client, payloads, state = daily_api
    state["principal"] = StudioPrincipal("self", frozenset(roles), frozenset(), {})
    response = await client.get(f"/api/users/{target}/usage/daily?start=2026-11-02")
    assert response.status_code == status
    if status == 200:
        assert payloads[0]["filters"] == {"attributes": {"agentgateway.user": target}}
    else:
        assert payloads == []


@pytest.mark.parametrize(
    "upstream",
    [
        httpx.Response(503, text="private details"),
        httpx.Response(200, text="not-json"),
        httpx.ConnectError("private details"),
    ],
)
async def test_daily_upstream_failures_are_safe_502(daily_api, upstream):
    client, _payloads, state = daily_api
    state["response"] = upstream
    response = await client.get("/api/users/self/usage/daily?start=2026-11-02")
    assert response.status_code == 502
    assert response.json() == {"detail": "Usage analytics are temporarily unavailable."}


@pytest.mark.parametrize(
    "invalid",
    [
        {"group": {}},
        {"group": {"requestModel": 42}},
        {"group": {"requestModel": None, "provider": "unexpected"}},
        {"requests": "2"},
        {"requests": True},
        {"totalTokens": -1},
        {"cost": -0.1},
        {"cost": "NaN"},
        {"cost": float("inf")},
    ],
)
@pytest.mark.parametrize("field", ["groups", "buckets"])
async def test_daily_rejects_malformed_typed_metrics(daily_api, invalid, field):
    client, _payloads, state = daily_api
    group = {"group": {"requestModel": None}, "requests": 1, "totalTokens": 2}
    entry = {**group, "start": "2026-11-01T23:00:00Z", **invalid}
    body = {"bucketSeconds": 46800, "groups": [], "buckets": [], field: [entry]}
    state["response"] = httpx.Response(200, content=json.dumps(body))
    response = await client.get("/api/users/self/usage/daily?start=2026-11-02")
    assert response.status_code == 502


@pytest.mark.parametrize(
    "timestamp",
    [
        "invalid",
        "2026-11-02T00:00:00",
        "2026-11-01T22:59:59Z",
        "2026-11-02T12:00:00Z",
        "2026-11-02T00:00:00Z",
    ],
)
async def test_daily_rejects_invalid_or_out_of_range_buckets(daily_api, timestamp):
    client, _payloads, state = daily_api
    state["response"] = httpx.Response(
        200,
        json={
            "bucketSeconds": 46800,
            "groups": [],
            "buckets": [
                {
                    "start": timestamp,
                    "group": {"requestModel": None},
                    "requests": 1,
                    "totalTokens": 2,
                }
            ],
        },
    )
    response = await client.get("/api/users/self/usage/daily?start=2026-11-02")
    assert response.status_code == 502


@pytest.mark.parametrize(
    "summary",
    [
        {},
        {"bucketSeconds": 0, "groups": [], "buckets": []},
        {"bucketSeconds": 86400, "groups": [], "buckets": None},
        {"bucketSeconds": 86400, "groups": None, "buckets": []},
        {
            "bucketSeconds": 86400,
            "groups": [
                {"group": {"requestModel": None}, "requests": 1, "totalTokens": 2},
                {"group": {"requestModel": None}, "requests": 3, "totalTokens": 4},
            ],
            "buckets": [],
        },
    ],
)
async def test_daily_rejects_invalid_summary_structure(daily_api, summary):
    client, _payloads, state = daily_api
    state["response"] = httpx.Response(200, json=summary)
    response = await client.get("/api/users/self/usage/daily?start=2026-11-02")
    assert response.status_code == 502
