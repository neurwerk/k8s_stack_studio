"""Tests for KeycloakAdminClient."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from k8s_stack_studio.config.settings import Settings
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
