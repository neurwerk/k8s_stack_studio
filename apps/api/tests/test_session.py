"""Tests for the verified Studio session endpoint."""

from unittest.mock import AsyncMock

import pytest

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.session import SessionResponse, get_session
from k8s_stack_studio.lib.auth import StudioPrincipal


@pytest.mark.asyncio
async def test_session_returns_sorted_verified_authorization_claims(monkeypatch) -> None:
    """Expose only claims already validated by the API middleware."""
    principal = StudioPrincipal(
        subject="user-1",
        roles=frozenset({"studio-user", "pii-admin"}),
        agentgateway_roles=frozenset({"model:remote/example:invoke", "llm:invoke"}),
        profile={"email": "user@example.test"},
    )

    ready = AsyncMock(return_value=True)
    monkeypatch.setattr("k8s_stack_studio.controllers.session.schema_ready", ready)
    settings = Settings(notice_database_url="postgresql://unused")
    assert await get_session(principal, settings) == SessionResponse(
        subject="user-1",
        realm_roles=["pii-admin", "studio-user"],
        agentgateway_roles=["llm:invoke", "model:remote/example:invoke"],
        notice_preferences_available=True,
    )
    ready.assert_awaited_once_with("postgresql://unused")
