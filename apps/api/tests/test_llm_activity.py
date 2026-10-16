"""The project-wide Langfuse key must never expose another principal's content."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.llm_logs import router
from k8s_stack_studio.lib.auth import StudioAdmissionMiddleware, StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_settings


def observation(
    identifier: str, *, owner: str = "self", when: str = "2026-10-01T12:00:00Z"
) -> dict[str, object]:
    return {
        "id": identifier,
        "userId": owner,
        "type": "GENERATION",
        "startTime": when,
        "endTime": "2026-10-01T12:00:00.275Z",
        "name": "llm",
        "model": "test-model",
        "input": '{"messages":[{"role":"user","content":"a full request"}]}',
        "output": '{"role":"assistant","content":"a full response"}',
        "metadata": {
            "attributes.http.method": "POST",
            "attributes.http.path": "/v1/chat/completions?token=hidden",
            "attributes.http.status": 200,
            "url.full": "https://service.test/?token=hidden",
            "connection_string": "postgresql://user:pass@db.example/studio",
        },
    }


def sample_response(request: httpx.Request) -> httpx.Response:
    """Return the bounded generations expected by the existing activity boundary test."""
    if request.url.params.get("filter"):
        filters = json.loads(request.url.params["filter"])
        if len(filters) == 4:
            return httpx.Response(200, json={"data": [observation("one")]})
        column = filters[-1]["column"]
        if column == "input":
            return httpx.Response(200, json={"data": [observation("one"), observation("two")]})
        if column == "output":
            return httpx.Response(200, json={"data": [observation("two"), observation("three")]})
        return httpx.Response(200, json={"data": []})
    return httpx.Response(200, json={"data": [observation("one")]})


@pytest.fixture
async def activity_api():
    calls: list[httpx.Request] = []
    state: dict[str, object] = {
        "enabled": True,
        "principal": StudioPrincipal("self", frozenset({"studio-user"}), frozenset(), {}),
        "result": None,
    }

    async def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path == "/api/public/v2/observations"
        assert request.headers["authorization"].startswith("Basic ")
        result = state["result"]
        if isinstance(result, httpx.Response):
            return result
        return sample_response(request)

    app = FastAPI()
    app.include_router(router)
    app.add_middleware(StudioAdmissionMiddleware)

    @app.middleware("http")
    async def identity(request, call_next):
        if state["principal"] is not None:
            request.scope["user"] = state["principal"]
        return await call_next(request)

    def settings() -> Settings:
        return Settings(
            llm_logs_enabled=bool(state["enabled"]),
            langfuse_url="http://langfuse-test:3000",
            langfuse_public_key="test-public",
            langfuse_secret_key="test-secret",
        )

    app.dependency_overrides[get_settings] = settings
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as upstream_client:
        app.state.langfuse_client = upstream_client
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            yield client, calls, state


async def test_personal_activity_boundary(activity_api):
    client, calls, state = activity_api
    state["principal"] = StudioPrincipal(
        "self", frozenset({"studio-user", "langfuse-admin", "keycloak-admin"}), frozenset(), {}
    )
    result = await client.post("/api/me/llm-activity", json={})
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()[0]["input"].endswith('"a full request"}]}')
    assert result.json()[0]["metadata"] == {
        "attributes.http.method": "POST",
        "attributes.http.status": 200,
    }
    assert "hidden" not in result.text
    assert "postgresql://" not in result.text
    assert json.loads(calls[0].url.params["filter"])[0]["value"] == "self"
    assert json.loads(calls[0].url.params["filter"])[1]["value"] == ["GENERATION", "TOOL"]
    assert calls[0].url.params["limit"] == "10"

    calls.clear()
    result = await client.post(
        "/api/me/llm-activity",
        json={
            "q": "private phrase",
            "start": "2026-09-01T00:00:00Z",
            "end": "2026-10-02T00:00:00Z",
            "type": "llm",
        },
    )
    assert [item["id"] for item in result.json()] == ["one", "two", "three"]
    for request, column in zip(calls, ("input", "output"), strict=True):
        filters = json.loads(request.url.params["filter"])
        assert {(part["column"], part["operator"]) for part in filters} == {
            ("userId", "="),
            ("type", "any of"),
            ("startTime", ">="),
            ("startTime", "<"),
            (column, "matches"),
        }
        assert filters[0]["value"] == "self"
        assert filters[1]["value"] == ["GENERATION"]

    state["result"] = httpx.Response(200, json={"data": [observation("private", owner="other")]})
    result = await client.post("/api/me/llm-activity", json={})
    assert result.status_code == 502
    assert "private" not in result.text
    calls.clear()
    for field, value in (("userId", "other"), ("filter", "[]"), ("limit", 1000)):
        assert (await client.post("/api/me/llm-activity", json={field: value})).status_code == 422
    state["enabled"] = False
    assert (await client.post("/api/me/llm-activity", json={})).status_code == 404
    assert calls == []


async def test_classified_activity_stays_self_only_and_allowlisted(activity_api):
    client, calls, state = activity_api
    state["principal"] = StudioPrincipal(
        "self", frozenset({"studio-user", "langfuse-admin", "gateway-admin"}), frozenset(), {}
    )
    row = observation("normalized")
    metadata = {
        "neurwerk.entry_mode": "forward_proxy",
        "neurwerk.destination_kind": "model",
        "neurwerk.destination_id": "example",
        "neurwerk.provider_credential_source": "caller_supplied",
        "neurwerk.request_id": "request-1",
        "neurwerk.token_usage_known": True,
        "neurwerk.cost_known": False,
        "neurwerk.provider_id": {"authorization": "must-not-escape"},
        "neurwerk.cookies": "must-not-escape",
        "response.body": "restored-must-not-escape",
        "attributes.http.method": {"unexpected": "must-not-escape"},
    }
    row.update(metadata=metadata, totalUsage=0, totalCost=0)
    state["result"] = httpx.Response(200, json={"data": [row]})
    result = await client.post(
        "/api/me/llm-activity",
        json={
            "type": "llm",
            "q": "example",
            "provider_credential_source": "caller_supplied",
            "entry_mode": "forward_proxy",
        },
    )
    assert result.status_code == 200
    assert len(result.json()) == 1  # Search branches return the same observation, deduplicated.
    item = result.json()[0]
    assert item["gateway"]["billing_classification"] == "unknown"
    assert item["gateway"]["provider_credential_source"] == "caller_supplied"
    assert item["gateway"]["provider_id"] is None
    assert item["accounting"]["tokens"]["complete_total"] == 0
    assert item["accounting"]["cost_usd"]["complete_total"] is None
    assert "must-not-escape" not in result.text
    for call in calls:
        conditions = json.loads(call.url.params["filter"])
        assert conditions[0] == {
            "type": "string",
            "column": "userId",
            "operator": "=",
            "value": "self",
        }
        assert {part["key"] for part in conditions if part["column"] == "metadata"} == {
            "neurwerk.entry_mode",
            "neurwerk.provider_credential_source",
        }
    row["userId"] = "other"
    state["result"] = httpx.Response(200, json={"data": [row]})
    assert (
        await client.post("/api/me/llm-activity", json={"entry_mode": "forward_proxy"})
    ).status_code == 502
    row["userId"] = "self"
    state["result"] = httpx.Response(200, json={"data": [row]})
    assert (
        await client.post("/api/me/llm-activity", json={"entry_mode": "api"})
    ).status_code == 502
    calls.clear()
    for extra in (
        {"user_id": "other"},
        {"metadata": {"userId": "other"}},
        {"provider_id": "x" * 256},
        {"type": "application"},
    ):
        assert (await client.post("/api/me/llm-activity", json=extra)).status_code == 422
    assert calls == []


async def test_historical_activity_does_not_turn_reported_zero_into_free(activity_api):
    client, _, state = activity_api
    row = observation("historical")
    row.update(totalUsage=0, totalCost=0)
    state["result"] = httpx.Response(200, json={"data": [row]})
    response = await client.post("/api/me/llm-activity", json={})
    assert response.status_code == 200
    item = response.json()[0]
    assert item["tokens"] == item["costUsd"] == 0
    assert item["accounting"]["tokens"]["state"] == "unknown"
    assert item["accounting"]["cost_usd"]["complete_total"] is None


async def test_mcp_status_redacts_credentials_without_losing_error_context(activity_api):
    client, _, state = activity_api
    row = observation("tool-error")
    row.update(
        type="TOOL",
        level="ERROR",
        statusMessage=(
            "Connection refused using Bearer synthetic-bearer "
            "at https://synthetic-user:synthetic-password@tool.example/"
            "?api_key=synthetic-query; retry after reconnecting"
        ),
    )
    state["result"] = httpx.Response(200, json={"data": [row]})
    response = await client.post("/api/me/llm-activity", json={"type": "mcp"})
    assert response.status_code == 200
    status = response.json()[0]["status"]
    assert "Connection refused" in status
    assert "retry after reconnecting" in status
    assert "tool.example" in status
    for credential in (
        "synthetic-bearer",
        "synthetic-user",
        "synthetic-password",
        "synthetic-query",
    ):
        assert credential not in status
        assert credential not in response.text


@pytest.mark.parametrize("level, expected", [("ERROR", "ERROR"), ("DEFAULT", None), (None, None)])
async def test_mcp_status_without_message_preserves_level_fallback(activity_api, level, expected):
    client, _, state = activity_api
    row = observation("tool-status")
    row.update(type="TOOL", level=level)
    state["result"] = httpx.Response(200, json={"data": [row]})
    response = await client.post("/api/me/llm-activity", json={"type": "mcp"})
    assert response.status_code == 200
    assert response.json()[0]["status"] == expected
