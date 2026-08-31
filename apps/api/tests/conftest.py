"""Shared test fixtures for the Studio API.

Provides an ASGI test client, mock settings, and an HTTP transport mock
so integration and unit tests don't need real external services.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.main import create_app


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Settings singleton with test defaults (no real external services)."""
    return Settings(
        keycloak_server_url="http://keycloak-test:8080",
        keycloak_realm="test-realm",
        keycloak_client_id="test-client",
        keycloak_client_secret="test-secret",
        keycloak_api_key_bridge_url="http://bridge-test:8081",
        opensearch_url="https://opensearch-test:9200",
        opensearch_user="test-user",
        opensearch_password="test-pass",
        opensearch_ca_cert="",
        pii_engine_url="https://pii-engine-test:8000",
        pii_engine_ca_cert="/tmp/ca.crt",
        pii_engine_client_cert="/tmp/client.crt",
        pii_engine_client_key="/tmp/client.key",
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """Create a FastAPI app with a mocked http_client lifespan."""
    _app = create_app()
    _app.dependency_overrides = {}
    return _app


@pytest.fixture
async def async_client(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP test client connected to the app's ASGI transport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_http_transport() -> MagicMock:
    """Mock httpx.AsyncClient for unit tests that don't need the full app."""
    return MagicMock(spec=httpx.AsyncClient)


def _make_mock_resp(
    status_code: int = 200,
    json_data: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a mock httpx.Response with the given status and JSON body."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.reason_phrase = "OK"
    return resp
