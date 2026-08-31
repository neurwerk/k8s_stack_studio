"""Tests for API-key and AgentGateway-permission bridge proxies."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers import api_keys
from k8s_stack_studio.controllers.api_keys import (
    _check_self_or_api_key_admin,
    create_api_key,
    get_agentgateway_permissions,
)
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.models.api_keys import CreateApiKeyRequest


def request_with_principal(
    principal: StudioPrincipal,
    client: MagicMock,
    authorization: str = "Bearer caller-jwt",
) -> MagicMock:
    request = MagicMock()
    request.scope = {"user": principal}
    request.headers.get.return_value = authorization
    request.app = SimpleNamespace(state=SimpleNamespace(http_client=client))
    return request


def principal(*roles: str) -> StudioPrincipal:
    return StudioPrincipal("caller", frozenset(roles), frozenset(), {})


@pytest.mark.asyncio
async def test_permission_proxy_allows_self_forwards_jwt_and_preserves_bridge_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_keys,
        "get_settings",
        lambda: Settings(keycloak_api_key_bridge_url="http://bridge.internal"),
    )
    client = MagicMock(spec=httpx.AsyncClient)
    client.request = AsyncMock(
        return_value=httpx.Response(
            409,
            content=b"permission response",
            headers={"content-type": "text/plain"},
        )
    )
    request = request_with_principal(principal("studio-user"), client)

    _check_self_or_api_key_admin("caller", request, "caller")
    response = await get_agentgateway_permissions("caller", request, None)

    assert response.status_code == 409
    assert response.body == b"permission response"
    assert response.headers["content-type"] == "text/plain"
    client.request.assert_awaited_once_with(
        "GET",
        "http://bridge.internal/permissions",
        headers={"Authorization": "Bearer caller-jwt"},
        params={"user_id": "caller"},
    )


def test_permission_proxy_allows_admin_but_rejects_other_users() -> None:
    request = request_with_principal(principal("studio-user", "api-key-admin"), MagicMock())
    _check_self_or_api_key_admin("other", request, "caller")

    request.scope["user"] = principal("studio-user")
    with pytest.raises(HTTPException) as exc_info:
        _check_self_or_api_key_admin("other", request, "caller")
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_create_api_key_forwards_validated_grant_and_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_keys,
        "get_settings",
        lambda: Settings(keycloak_api_key_bridge_url="http://bridge.internal"),
    )
    client = MagicMock(spec=httpx.AsyncClient)
    response = MagicMock(spec=httpx.Response)
    response.status_code = 201
    response.json.return_value = {"id": "key-1"}
    client.post = AsyncMock(return_value=response)
    request = request_with_principal(principal("studio-user"), client)

    result = await create_api_key(
        "caller",
        request,
        CreateApiKeyRequest(name="automation", permissions=["llm:invoke"], expires_in_days=90),
        None,
    )

    assert result == {"id": "key-1"}
    call = client.post.await_args
    assert call is not None
    assert call.kwargs["json"] == {
        "name": "automation",
        "permissions": ["llm:invoke"],
        "expires_in_days": 90,
        "target_user_id": "caller",
    }


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "permissions": ["llm:invoke"], "expires_in_days": 90},
        {"name": "key", "permissions": [], "expires_in_days": 90},
        {"name": "key", "permissions": ["llm:invoke"], "expires_in_days": 0},
        {"name": "key", "permissions": ["llm:invoke"], "expires_in_days": 366},
        {"name": "key", "permissions": ["llm:invoke"], "expires_in_days": 90, "extra": True},
    ],
)
def test_create_api_key_body_is_strict(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CreateApiKeyRequest.model_validate(body)


def test_api_key_renewal_route_is_absent() -> None:
    paths = {getattr(route, "path", "") for route in api_keys.router.routes}
    assert "/api/users/{user_id}/api-keys/{key_id}/renew" not in paths
