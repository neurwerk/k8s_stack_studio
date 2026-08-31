"""Tests for shared HTTP client TLS configuration."""

from __future__ import annotations

import ssl
from unittest.mock import patch

import httpx
import pytest

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.exceptions import PiiEngineTlsConfigError
from k8s_stack_studio.lib.http_client import _create_client, _create_pii_engine_client


def test_shared_client_verifies_tls_by_default() -> None:
    """General service traffic never inherits an OpenSearch development bypass."""
    with patch("k8s_stack_studio.lib.http_client.httpx.AsyncClient") as constructor:
        _create_client()

    constructor.assert_called_once_with(
        timeout=httpx.Timeout(15.0),
        verify=True,
        trust_env=True,
    )


def test_isolated_opensearch_client_ignores_proxy_environment() -> None:
    """OpenSearch traffic cannot be redirected by ambient proxy settings."""
    with patch("k8s_stack_studio.lib.http_client.httpx.AsyncClient") as constructor:
        _create_client(verify="/certs/opensearch-ca.crt", trust_env=False)

    constructor.assert_called_once_with(
        timeout=httpx.Timeout(15.0),
        verify="/certs/opensearch-ca.crt",
        trust_env=False,
    )


def test_pii_engine_client_uses_dedicated_mtls_settings() -> None:
    """The engine client receives CA, client certificate, key, and timeout."""
    settings = Settings(
        pii_engine_url="https://engine",
        pii_engine_ca_cert="/certs/ca.crt",
        pii_engine_client_cert="/certs/client.crt",
        pii_engine_client_key="/certs/client.key",
        pii_engine_timeout=42.0,
    )
    with (
        patch("k8s_stack_studio.lib.http_client.ssl.create_default_context") as create_context,
        patch("k8s_stack_studio.lib.http_client.httpx.AsyncClient") as constructor,
    ):
        _create_pii_engine_client(settings)

    create_context.assert_called_once_with(cafile="/certs/ca.crt")
    create_context.return_value.load_cert_chain.assert_called_once_with(
        certfile="/certs/client.crt",
        keyfile="/certs/client.key",
    )
    constructor.assert_called_once_with(
        timeout=httpx.Timeout(42.0),
        verify=create_context.return_value,
        trust_env=False,
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost:8443",
        "https://127.0.0.1:8443",
        "https://[::1]:8443",
    ],
)
def test_pii_engine_local_client_disables_server_verification_but_uses_client_identity(
    url: str,
) -> None:
    """Loopback development keeps mTLS while accepting a locally mismatched certificate."""
    settings = Settings(
        pii_engine_url=url,
        pii_engine_ca_cert="",
        pii_engine_client_cert="/certs/client.crt",
        pii_engine_client_key="/certs/client.key",
        pii_engine_allow_insecure_local=True,
    )
    with (
        patch("k8s_stack_studio.lib.http_client.ssl.create_default_context") as create_context,
        patch("k8s_stack_studio.lib.http_client.httpx.AsyncClient") as constructor,
    ):
        _create_pii_engine_client(settings)

    create_context.assert_called_once_with()
    context = create_context.return_value
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE
    context.load_cert_chain.assert_called_once_with(
        certfile="/certs/client.crt",
        keyfile="/certs/client.key",
    )
    constructor.assert_called_once_with(
        timeout=httpx.Timeout(settings.pii_engine_timeout),
        verify=context,
        trust_env=False,
    )


def test_pii_engine_loopback_requires_explicit_insecure_mode_without_ca() -> None:
    """A loopback hostname alone never disables server verification."""
    settings = Settings(
        pii_engine_url="https://127.0.0.1:8443",
        pii_engine_ca_cert="",
        pii_engine_client_cert="/certs/client.crt",
        pii_engine_client_key="/certs/client.key",
    )

    with pytest.raises(PiiEngineTlsConfigError):
        _create_pii_engine_client(settings)


def test_pii_engine_client_rejects_incomplete_cluster_tls() -> None:
    """Cluster HTTPS never silently falls back to unauthenticated HTTP."""
    settings = Settings(
        pii_engine_url="https://engine",
        pii_engine_ca_cert="",
        pii_engine_client_cert="",
        pii_engine_client_key="",
    )
    try:
        _create_pii_engine_client(settings)
    except PiiEngineTlsConfigError as error:
        assert "workload TLS paths" in str(error)
    else:
        raise AssertionError("expected incomplete TLS configuration to fail")


def test_pii_engine_client_rejects_plain_http() -> None:
    """Studio never permits a plaintext production connection to PII Engine."""
    with (
        patch("k8s_stack_studio.lib.http_client.httpx.AsyncClient") as constructor,
        pytest.raises(ValueError, match="must use HTTPS"),
    ):
        Settings(
            pii_engine_url="http://engine",
            pii_engine_ca_cert="/certs/ca.crt",
            pii_engine_client_cert="/certs/client.crt",
            pii_engine_client_key="/certs/client.key",
        )
    constructor.assert_not_called()
