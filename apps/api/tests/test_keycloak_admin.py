"""Tests for KeycloakAdminClient."""

from __future__ import annotations

import httpx
import pytest

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.exceptions import KeycloakAdminRequestError
from k8s_stack_studio.lib.keycloak_admin import KeycloakAdminClient


async def test_get_user_preserves_not_found_status(settings: Settings) -> None:
    """A missing Keycloak user remains distinguishable from other failures."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(KeycloakAdminRequestError, match="HTTP 404") as exc_info:
            await KeycloakAdminClient(settings, http).get_user("missing", "token")
    assert exc_info.value.status_code == 404
