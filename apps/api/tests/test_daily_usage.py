from datetime import date
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from k8s_stack_studio.controllers.usage import aggregate_router, router
from k8s_stack_studio.lib.auth import StudioAdmissionMiddleware, StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_usage
from k8s_stack_studio.lib.usage import UsageReader, UsageUnavailable
from k8s_stack_studio.models.usage import (
    DailyUsageResponse,
    UsagePeopleResponse,
    UsageSourcesResponse,
)


@pytest.fixture
async def daily_api():
    app = FastAPI()
    app.include_router(router)
    app.include_router(aggregate_router)
    app.add_middleware(StudioAdmissionMiddleware)
    principal = {"user": StudioPrincipal("self", frozenset({"studio-user"}), frozenset(), {})}

    @app.middleware("http")
    async def identity(request, call_next):
        request.scope["user"] = principal["user"]
        return await call_next(request)

    reader = AsyncMock(spec=UsageReader)
    today = date.today()
    reader.fetch_daily_usage.return_value = DailyUsageResponse(
        timezone="UTC", start_date=today, end_date=today, today=today, days=[]
    )
    reader.fetch_all_daily_usage.return_value = reader.fetch_daily_usage.return_value
    reader.fetch_source_breakdown.return_value = UsageSourcesResponse(
        timezone="UTC", start_date=today, end_date=today, apps=[], credentials=[]
    )
    reader.fetch_user_breakdown.return_value = UsagePeopleResponse(
        timezone="UTC", start_date=today, end_date=today, users=[]
    )
    app.dependency_overrides[get_usage] = lambda: reader
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, reader, principal


@pytest.mark.parametrize("kind", ["llm", "mcp"])
@pytest.mark.parametrize("suffix", ["daily", "sources"])
@pytest.mark.parametrize(
    "admin,target,status",
    [
        (False, "self", 200),
        (False, "other", 403),
        (False, None, 403),
        (True, "other", 200),
        (True, None, 200),
    ],
)
async def test_self_admin_boundaries_before_reporting(
    daily_api, kind, suffix, admin, target, status
):
    client, reader, principal = daily_api
    if admin:
        principal["user"] = StudioPrincipal(
            "self", frozenset({"studio-user", "langfuse-admin"}), frozenset(), {}
        )
    route = f"/api/users/{target}/usage/{suffix}" if target else f"/api/usage/{suffix}"
    response = await client.get(route, params={"kind": kind})
    assert response.status_code == status
    if status == 403:
        assert not reader.mock_calls
    else:
        assert response.headers["cache-control"] == "no-store"
        call = next(c for c in reader.mock_calls if "fetch_" in c[0])
        if target:
            assert call.args[0] == target
        assert call.args[-1].kind == kind


@pytest.mark.parametrize("path", ["/api/usage/people", "/api/usage/billing?day=2026-11-01"])
async def test_account_wide_reports_require_admin(daily_api, path):
    client, reader, _ = daily_api
    assert (await client.get(path)).status_code == 403
    assert not reader.mock_calls


@pytest.mark.parametrize(
    "params",
    [
        {"principal_id": "other"},
        {"user_id": "other"},
        {"attributes": '{"agentgateway.user":"other"}'},
        {"kind": "other"},
        {"start": "bad-date"},
    ],
)
async def test_filters_cannot_select_owner_or_arbitrary_source(daily_api, params):
    client, reader, _ = daily_api
    assert (await client.get("/api/users/self/usage/daily", params=params)).status_code == 422
    assert not reader.mock_calls


async def test_safe_reporting_failure(daily_api):
    client, reader, _ = daily_api
    reader.fetch_daily_usage.side_effect = UsageUnavailable("private database detail")
    response = await client.get("/api/users/self/usage/daily")
    assert response.status_code == 502 and "private" not in response.text
