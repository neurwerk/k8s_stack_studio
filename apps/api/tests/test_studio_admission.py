"""Tests for Studio application admission and preserved feature-role checks."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.types import Message, Receive, Scope, Send

from k8s_stack_studio.lib.auth import StudioAdmissionMiddleware, StudioPrincipal
from k8s_stack_studio.lib.dependencies import require_role


def principal(*roles: str) -> StudioPrincipal:
    return StudioPrincipal(
        subject="user-1",
        roles=frozenset(roles),
        agentgateway_roles=frozenset(),
        profile={},
    )


async def status_for(scope: Scope) -> int:
    """Run admission middleware and return its emitted HTTP status."""
    messages: list[Message] = []

    async def app(_scope: Scope, _receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    await StudioAdmissionMiddleware(app)(scope, receive, send)
    return next(
        message["status"] for message in messages if message["type"] == "http.response.start"
    )


@pytest.mark.asyncio
async def test_studio_admission_requires_studio_user_for_operational_routes() -> None:
    scope: Scope = {"type": "http", "path": "/api/logs", "user": principal("opensearch-admin")}
    assert await status_for(scope) == 403

    scope["user"] = principal("studio-user")
    assert await status_for(scope) == 204


@pytest.mark.asyncio
async def test_studio_admission_keeps_version_public() -> None:
    assert await status_for({"type": "http", "path": "/api/version"}) == 204


@pytest.mark.parametrize(
    "role", ["pii-admin", "keycloak-admin", "opensearch-admin", "api-key-admin"]
)
def test_leaf_roles_still_reject_studio_users_without_the_feature_role(role: str) -> None:
    request = Request({"type": "http", "user": principal("studio-user"), "headers": []})
    with pytest.raises(HTTPException) as exc_info:
        require_role(role)(request)
    assert exc_info.value.status_code == 403
