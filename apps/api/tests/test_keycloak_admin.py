"""Tests for KeycloakAdminClient."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.exceptions import KeycloakAdminRequestError
from k8s_stack_studio.lib.keycloak_admin import KeycloakAdminClient


def test_client_init_stores_settings() -> None:
    """Init stores base_url, realm, and shared client."""
    mock = MagicMock(spec=httpx.AsyncClient)
    settings = Settings(
        keycloak_server_url="http://kc:8080/",
        keycloak_realm="testrealm",
        keycloak_client_id="testcli",
    )
    c = KeycloakAdminClient(settings=settings, client=mock)
    assert c._base_url == "http://kc:8080"
    assert c._realm == "testrealm"
    assert c._client is mock


async def test_get_user_preserves_not_found_status(settings: Settings) -> None:
    """A missing Keycloak user remains distinguishable from other failures."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(KeycloakAdminRequestError, match="HTTP 404") as exc_info:
            await KeycloakAdminClient(settings, http).get_user("missing", "token")
    assert exc_info.value.status_code == 404
