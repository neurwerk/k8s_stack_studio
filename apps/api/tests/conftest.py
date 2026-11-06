"""Shared settings fixture for the Studio API."""

from __future__ import annotations

import pytest

from k8s_stack_studio.config.settings import Settings


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
