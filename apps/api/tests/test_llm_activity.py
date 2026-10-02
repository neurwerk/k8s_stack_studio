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
