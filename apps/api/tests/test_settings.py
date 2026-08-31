"""Tests for application settings."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from k8s_stack_studio.config.settings import Settings


def test_settings_defaults() -> None:
    """Settings load with sensible defaults."""
    s = Settings(
        keycloak_server_url="http://kc:80",
        keycloak_realm="realm",
        keycloak_client_id="cli",
    )
    assert s.host == "0.0.0.0"
    assert s.port == 4010
    assert s.mgmt_port == 4090
    assert s.log_level == "info"
    assert (
        s.pii_engine_url
        == "https://monitor-pii-engine-service.monitor-pii-engine.svc.cluster.local:443"
    )
    assert s.pii_engine_timeout == 30.0
    assert s.pii_engine_ca_cert == "/var/run/pii-engine/tls/ca.crt"
    assert s.pii_engine_client_cert == "/var/run/pii-engine/tls/tls.crt"
    assert s.pii_engine_client_key == "/var/run/pii-engine/tls/tls.key"
    assert s.pii_engine_allow_insecure_local is False
    assert s.opensearch_url.startswith("https://")
    assert s.opensearch_user == "studio-logs-read"
    assert s.opensearch_ca_cert == ""
    assert s.opensearch_allow_insecure_local is False
    assert s.opensearch_tls_verify is True
    assert s.keycloak_server_url == "http://kc:80"
    assert s.keycloak_realm == "realm"
    assert s.keycloak_client_id == "cli"


def test_settings_env_prefix() -> None:
    """K8S_STUDIO_ prefix maps to settings fields."""
    os.environ["K8S_STUDIO_LOG_LEVEL"] = "debug"
    try:
        s = Settings(
            keycloak_server_url="http://kc:80",
            keycloak_realm="r",
            keycloak_client_id="c",
        )
        assert s.log_level == "debug"
    finally:
        del os.environ["K8S_STUDIO_LOG_LEVEL"]


def test_example_environment_uses_explicit_pii_loopback_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented PII endpoint passes the same validation used by start_dev."""
    example_path = Path(__file__).parents[3] / ".env.example"
    values = {
        name: value
        for line in example_path.read_text().splitlines()
        if line and not line.startswith("#")
        for name, separator, value in [line.partition("=")]
        if separator
    }
    for name in (
        "K8S_STUDIO_PII_ENGINE_URL",
        "K8S_STUDIO_PII_ENGINE_CA_CERT",
        "K8S_STUDIO_PII_ENGINE_ALLOW_INSECURE_LOCAL",
    ):
        monkeypatch.setenv(name, values[name])

    settings = Settings()

    assert settings.pii_engine_url == "https://127.0.0.1:8443"
    assert settings.pii_engine_ca_cert == ""
    assert settings.pii_engine_allow_insecure_local is True


def test_example_environment_uses_optional_opensearch_system_trust(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A copied example does not require a nonexistent OpenSearch CA file."""
    example_path = Path(__file__).parents[3] / ".env.example"
    values = {
        name: value
        for line in example_path.read_text().splitlines()
        if line and not line.startswith("#")
        for name, separator, value in [line.partition("=")]
        if separator
    }
    for name in (
        "K8S_STUDIO_OPENSEARCH_URL",
        "K8S_STUDIO_OPENSEARCH_CA_CERT",
        "K8S_STUDIO_OPENSEARCH_ALLOW_INSECURE_LOCAL",
    ):
        monkeypatch.setenv(name, values[name])

    settings = Settings()

    assert values["K8S_STUDIO_OPENSEARCH_CA_CERT"] == ""
    assert settings.opensearch_ca_cert == ""
    assert settings.opensearch_tls_verify is True


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost:8443",
        "https://127.0.0.1:8443",
        "https://[::1]:8443",
    ],
)
def test_pii_engine_insecure_mode_accepts_exact_loopback_hosts(url: str) -> None:
    """The explicit PII bypass accepts only documented loopback spellings."""
    settings = Settings(
        pii_engine_url=url,
        pii_engine_allow_insecure_local=True,
    )

    assert settings.pii_engine_allow_insecure_local is True


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost.example:8443",
        "https://127.0.0.2:8443",
        "https://127.0.0.1.example:8443",
        "https://[::2]:8443",
        "https://localhost@pii.example.com:8443",
    ],
)
def test_pii_engine_insecure_mode_rejects_loopback_lookalikes(url: str) -> None:
    """Remote hosts cannot masquerade as an allowed loopback endpoint."""
    with pytest.raises(ValueError, match="restricted to exact loopback"):
        Settings(
            pii_engine_url=url,
            pii_engine_allow_insecure_local=True,
        )


def test_pii_engine_requires_https_even_for_explicit_local_mode() -> None:
    """The local option relaxes certificate verification, not TLS transport."""
    with pytest.raises(ValueError, match="must use HTTPS"):
        Settings(
            pii_engine_url="http://127.0.0.1:8443",
            pii_engine_allow_insecure_local=True,
        )


@pytest.mark.parametrize("url", ["https://[::1:8443", "https:///missing-host"])
def test_pii_engine_rejects_malformed_or_missing_hosts(url: str) -> None:
    """Malformed URLs fail configuration before any HTTP client is created."""
    with pytest.raises(ValueError, match="must include a hostname"):
        Settings(pii_engine_url=url)


def test_opensearch_custom_ca_is_used_for_verification() -> None:
    """A configured CA bundle replaces the system trust store."""
    settings = Settings(opensearch_ca_cert="/certs/opensearch-ca.crt")

    assert settings.opensearch_tls_verify == "/certs/opensearch-ca.crt"


@pytest.mark.parametrize(
    "url",
    [
        "https://opensearch.example.com:9200",
        "https://localhost.example:9200",
        "https://127.0.0.2:9200",
        "https://[::2]:9200",
    ],
)
def test_opensearch_insecure_mode_is_limited_to_exact_loopback(url: str) -> None:
    """The explicit local bypass cannot disable TLS for a remote endpoint."""
    local = Settings(
        opensearch_url="https://127.0.0.1:9200",
        opensearch_allow_insecure_local=True,
    )
    assert local.opensearch_tls_verify is False

    with pytest.raises(ValueError, match="restricted to exact loopback"):
        Settings(
            opensearch_url=url,
            opensearch_allow_insecure_local=True,
        )


def test_opensearch_remote_endpoint_requires_https() -> None:
    """Remote OpenSearch transport rejects plaintext URLs."""
    with pytest.raises(ValueError, match="must use HTTPS"):
        Settings(opensearch_url="http://opensearch.example.com:9200")


def test_opensearch_plaintext_loopback_requires_explicit_bypass() -> None:
    """Even loopback HTTP must be opted into as insecure local development."""
    with pytest.raises(ValueError, match="must use HTTPS"):
        Settings(opensearch_url="http://localhost:9200")

    settings = Settings(
        opensearch_url="http://[::1]:9200",
        opensearch_allow_insecure_local=True,
    )
    assert settings.opensearch_tls_verify is False
