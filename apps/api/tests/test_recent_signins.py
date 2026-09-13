from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from k8s_stack_studio.controllers.admin import _principal_to_user_dict, router
from k8s_stack_studio.lib.auth import StudioAdmissionMiddleware, StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_keycloak_admin
from k8s_stack_studio.lib.keycloak_admin import KeycloakAdminClient

END = datetime(2026, 9, 11, 12, tzinfo=UTC)
START = END - timedelta(days=7)
TIME = int(END.timestamp() * 1000) - 1000
EVENT = {"type": "LOGIN", "userId": "a", "time": TIME, "clientId": "another-client"}


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ([EVENT], "recorded"),
        ([], "no_record"),
        ([EVENT | {"time": int(START.timestamp() * 1000)}], "recorded"),
        ([EVENT | {"time": int(START.timestamp() * 1000) - 1}], "no_record"),
        ([EVENT | {"time": int(END.timestamp() * 1000) + 1}], "unavailable"),
        ([EVENT | {"time": -1}], "unavailable"),
        ([EVENT | {"time": True}], "unavailable"),
        ([EVENT | {"time": "invalid"}], "unavailable"),
        ([EVENT | {"type": "LOGIN_ERROR"}], "unavailable"),
        ([EVENT | {"type": "REFRESH_TOKEN"}], "unavailable"),
        ([EVENT | {"userId": "someone-else"}], "unavailable"),
        ([EVENT | {"error": "failed"}], "unavailable"),
        ([EVENT, EVENT], "unavailable"),
        ({}, "unavailable"),
        ([None], "unavailable"),
    ],
)
async def test_event_filter_validation_and_redaction(settings, body, expected):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer delegated"
        assert dict(request.url.params) == {
            "user": "a",
            "type": "LOGIN",
            "max": "1",
            "direction": "desc",
            "dateFrom": str(int(START.timestamp() * 1000)),
            "dateTo": str(int(END.timestamp() * 1000)),
        }
        assert request.extensions["timeout"]["read"] == 5
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await KeycloakAdminClient(settings, http).recent_signin(
            "a", "delegated", START, END
        )
    assert result["status"] == expected
    assert set(result) == {"status", "timestamp"}
    if expected == "recorded":
        assert isinstance(result["timestamp"], str)
        assert datetime.fromisoformat(result["timestamp"]).tzinfo == UTC
    else:
        assert result["timestamp"] is None


@pytest.mark.parametrize("failure", [403, 500, "timeout", "invalid-json"])
async def test_event_failures_are_unavailable(settings, failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private upstream detail", request=request)
        if failure == "invalid-json":
            return httpx.Response(200, content="not json")
        return httpx.Response(failure, json={"error": "private upstream detail"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await KeycloakAdminClient(settings, http).recent_signin(
            "a", "delegated", START, END
        )
    assert result == {"status": "unavailable", "timestamp": None}


def admin_app(admin, roles):
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(StudioAdmissionMiddleware)

    @app.middleware("http")
    async def verified_principal(request, call_next):
        if roles is not None:
            request.scope["user"] = StudioPrincipal("admin", frozenset(roles), frozenset(), {})
        return await call_next(request)

    app.dependency_overrides[get_keycloak_admin] = lambda: admin
    return app


@pytest.mark.parametrize(
    "roles,expected", [(None, 401), (["studio-user"], 403), (["keycloak-admin"], 403)]
)
async def test_signins_require_both_roles(roles, expected):
    admin = AsyncMock()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_app(admin, roles)), base_url="http://test"
    ) as http:
        response = await http.get("/api/admin/recent-signins?user_ids=a")
    assert response.status_code == expected
    admin.recent_signin.assert_not_called()


async def test_batch_bounds_concurrency_window_and_partial_failure():
    active = peak = 0

    async def lookup(user_id, token, start, end):
        nonlocal active, peak
        assert token == "delegated"
        assert end - start == timedelta(days=7)
        assert start.tzinfo == UTC
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.001)
        active -= 1
        return {"status": "unavailable" if user_id == "0" else "no_record", "timestamp": None}

    admin = AsyncMock()
    admin.recent_signin.side_effect = lookup
    admin.list_users.return_value = [{"id": "a"}]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_app(admin, ["studio-user", "keycloak-admin"])),
        base_url="http://test",
        headers={"Authorization": "Bearer delegated"},
    ) as http:
        response = await http.get(
            "/api/admin/recent-signins", params={"user_ids": list(map(str, range(25)))}
        )
        assert response.status_code == 200
        assert len(response.json()["users"]) == 25
        assert response.json()["users"]["0"]["status"] == "unavailable"
        assert response.json()["users"]["1"]["status"] == "no_record"
        assert peak == 4
        for params in ({}, {"user_ids": list(map(str, range(26)))}, {"user_ids": [""]}):
            assert (await http.get("/api/admin/recent-signins", params=params)).status_code == 422
        assert (await http.get("/api/admin/users?first=25&max=25&search=alice")).status_code == 200
        admin.list_users.assert_awaited_once_with(
            "delegated", search="alice", first=25, max_results=25
        )
        for query in ("first=-1", "max=26", "max=0"):
            assert (await http.get(f"/api/admin/users?{query}")).status_code == 422


async def test_list_pagination_reaches_keycloak(settings):
    def handler(request):
        assert dict(request.url.params) == {"first": "25", "max": "25", "search": "alice"}
        return httpx.Response(200, json=[{"id": "a"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await KeycloakAdminClient(settings, http).list_users("token", "alice", 25, 25) == [
            {"id": "a"}
        ]


def test_self_profile_does_not_invent_account_or_verification_status():
    profile = _principal_to_user_dict(StudioPrincipal("a", frozenset(), frozenset(), {}))
    assert profile["enabled"] is None
    assert profile["emailVerified"] is None
