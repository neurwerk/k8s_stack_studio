"""Application settings via pydantic-settings, read from K8S_STUDIO_ env vars."""

from __future__ import annotations

from typing import Self
from urllib.parse import SplitResult, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class InvalidUsageTimezoneError(ValueError):
    """The configured IANA timezone is unavailable in the container image."""

    def __init__(self) -> None:
        """Set a safe configuration error message."""
        super().__init__("Configured usage_timezone is not a valid IANA timezone.")


class InvalidAgentGatewayAdminUrlError(ValueError):
    """The configured AgentGateway admin URL is not a safe absolute URL."""

    def __init__(self) -> None:
        """Set a safe configuration error message."""
        super().__init__(
            "Configured agentgateway_admin_url must be an absolute HTTP(S) URL with a "
            "hostname and without credentials, query, or fragment."
        )


class MissingPiiEngineHostnameError(ValueError):
    """The configured PII Engine URL has no hostname."""

    def __init__(self) -> None:
        """Set a safe configuration error message."""
        super().__init__("Configured pii_engine_url must include a hostname.")


class RemotePiiEngineInsecureModeError(ValueError):
    """The insecure PII Engine option targets a non-loopback endpoint."""

    def __init__(self) -> None:
        """Set a safe configuration error message."""
        super().__init__(
            "pii_engine_allow_insecure_local is restricted to exact loopback endpoints."
        )


class PlaintextPiiEngineError(ValueError):
    """The configured PII Engine URL does not use TLS."""

    def __init__(self) -> None:
        """Set a safe configuration error message."""
        super().__init__("Configured pii_engine_url must use HTTPS.")


class MissingOpenSearchHostnameError(ValueError):
    """The configured OpenSearch URL has no hostname."""

    def __init__(self) -> None:
        """Set a safe configuration error message."""
        super().__init__("Configured opensearch_url must include a hostname.")


class RemoteOpenSearchInsecureModeError(ValueError):
    """The insecure OpenSearch option targets a non-loopback endpoint."""

    def __init__(self) -> None:
        """Set a safe configuration error message."""
        super().__init__(
            "opensearch_allow_insecure_local is restricted to exact loopback endpoints."
        )


class PlaintextOpenSearchError(ValueError):
    """The configured OpenSearch URL is plaintext without a local bypass."""

    def __init__(self) -> None:
        """Set a safe configuration error message."""
        super().__init__("Configured opensearch_url must use HTTPS.")


_LOCAL_INSECURE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _parse_url(value: str) -> SplitResult | None:
    """Parse a URL, returning None for malformed host syntax."""
    try:
        parsed = urlsplit(value)
        _ = parsed.hostname
    except ValueError:
        return None
    return parsed


def _is_exact_loopback(hostname: str | None) -> bool:
    """Recognize only the three supported local-development host spellings."""
    return hostname in _LOCAL_INSECURE_HOSTS


class Settings(BaseSettings):
    """Configuration for the Studio API backend."""

    model_config = SettingsConfigDict(
        env_prefix="K8S_STUDIO_",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 4010
    log_level: str = "info"

    # PII Engine workload endpoint. The dedicated client uses the configured
    # CA and client certificate; no human request token is sent to this service.
    pii_engine_url: str = (
        "https://monitor-pii-engine-service.monitor-pii-engine.svc.cluster.local:443"
    )
    pii_engine_ca_cert: str = "/var/run/pii-engine/tls/ca.crt"
    pii_engine_client_cert: str = "/var/run/pii-engine/tls/tls.crt"
    pii_engine_client_key: str = "/var/run/pii-engine/tls/tls.key"
    # Explicitly disable server verification only for an exact loopback endpoint.
    pii_engine_allow_insecure_local: bool = False
    pii_engine_timeout: float = Field(default=30.0, gt=0, le=120)

    # --- Keycloak OIDC ---
    # Server URL for Keycloak (for example, https://auth.example.com).
    keycloak_server_url: str = ""
    # Deployment-specific realm name.
    keycloak_realm: str = ""
    # OIDC client ID registered in Keycloak (for example, "studio").
    keycloak_client_id: str = ""
    # Client secret (optional — only needed for introspection; JWKS validation works without it)
    keycloak_client_secret: str = ""
    # Local-only escape hatch. Deployment charts must never enable this.
    allow_unauthenticated_local: bool = False

    # --- Keycloak API Key Bridge ---
    # URL for the keycloak-api-key-bridge service (manages per-user API keys).
    keycloak_api_key_bridge_url: str = ""

    # --- AgentGateway private analytics (per-user usage dashboard) ---
    agentgateway_admin_url: str = (
        "http://infra-agentgateway-gateway.infra-agentgateway.svc.cluster.local:15000"
    )
    # Calendar usage periods are calculated in this IANA timezone.
    usage_timezone: str = "UTC"

    # --- OpenSearch (logs viewer) ---
    # The internal service DNS default is overridden through environment config.
    opensearch_url: str = (
        "https://opensearch-cluster-master.monitor-opensearch.svc.cluster.local:9200"
    )
    # Read-only internal user provisioned by the monitor-opensearch init Job.
    opensearch_user: str = "studio-logs-read"
    # Patched into the Secret at runtime by the monitor-opensearch init Job.
    opensearch_password: str = ""
    # Optional CA bundle path. Empty uses the system trust store.
    opensearch_ca_cert: str = ""
    # Explicitly disable verification only for a loopback development endpoint.
    opensearch_allow_insecure_local: bool = False

    # --- Management port ---
    # Separate port for health and metrics (internal only, not exposed via HTTPRoute)
    mgmt_port: int = 4090

    @model_validator(mode="after")
    def validate_pii_engine_transport(self) -> Self:
        """Require HTTPS and constrain the explicit insecure local bypass."""
        parsed = _parse_url(self.pii_engine_url)
        if parsed is None or not parsed.hostname:
            raise MissingPiiEngineHostnameError
        if parsed.scheme != "https":
            raise PlaintextPiiEngineError
        if self.pii_engine_allow_insecure_local and not _is_exact_loopback(parsed.hostname):
            raise RemotePiiEngineInsecureModeError
        return self

    @model_validator(mode="after")
    def validate_opensearch_transport(self) -> Self:
        """Require verified HTTPS except for an explicit loopback-only bypass."""
        parsed = _parse_url(self.opensearch_url)
        if parsed is None or not parsed.hostname:
            raise MissingOpenSearchHostnameError
        if self.opensearch_allow_insecure_local and not _is_exact_loopback(parsed.hostname):
            raise RemoteOpenSearchInsecureModeError
        if parsed.scheme != "https" and not self.opensearch_allow_insecure_local:
            raise PlaintextOpenSearchError
        return self

    @property
    def opensearch_tls_verify(self) -> str | bool:
        """Return the narrowly scoped httpx TLS verification setting."""
        if self.opensearch_allow_insecure_local:
            return False
        return self.opensearch_ca_cert or True

    @field_validator("usage_timezone")
    @classmethod
    def validate_usage_timezone(cls, value: str) -> str:
        """Validate the configured IANA timezone used for calendar periods."""
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as e:
            raise InvalidUsageTimezoneError from e
        return value

    @field_validator("agentgateway_admin_url")
    @classmethod
    def validate_agentgateway_admin_url(cls, value: str) -> str:
        """Require a credential-free absolute HTTP(S) AgentGateway URL."""
        parsed = _parse_url(value)
        if (
            parsed is None
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise InvalidAgentGatewayAdminUrlError
        return value
