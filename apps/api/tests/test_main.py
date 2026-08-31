"""Tests for the FastAPI app factory (create_app, create_mgmt_app)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from k8s_stack_studio.main import create_app, create_mgmt_app


def test_create_app_returns_fastapi(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_app() returns a FastAPI instance with expected title."""
    monkeypatch.setenv("K8S_STUDIO_KEYCLOAK_SERVER_URL", "http://keycloak.test")
    monkeypatch.setenv("K8S_STUDIO_KEYCLOAK_REALM", "test")
    monkeypatch.setenv("K8S_STUDIO_KEYCLOAK_CLIENT_ID", "studio")
    app = create_app()
    assert isinstance(app, FastAPI)
    assert app.title == "AI Stack Studio"
    paths = set(app.openapi()["paths"])
    assert "/api/policy-engine/evaluate" in paths
    assert "/api/policy-engine/test-llm" not in paths
    assert "/api/agentgateway/models" not in paths


def test_create_mgmt_app_returns_fastapi() -> None:
    """create_mgmt_app() returns a FastAPI instance with no docs."""
    app = create_mgmt_app()
    assert isinstance(app, FastAPI)
    assert app.docs_url is None


@pytest.mark.asyncio
async def test_mgmt_app_health_endpoint() -> None:
    """The mgmt app has a /health route that returns {'status': 'ok'}."""
    app = create_mgmt_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
