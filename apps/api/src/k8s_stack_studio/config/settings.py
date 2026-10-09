"""Application settings via pydantic-settings, read from K8S_STUDIO_ env vars."""

from __future__ import annotations

import re
from typing import Literal, Self
from urllib.parse import SplitResult, quote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from k8s_stack_studio.models.mcp import McpRegistration


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


class InvalidLangfuseConfigError(ValueError):
    """Enabled LLM logs need a fixed URL and project credentials."""

    def __init__(self) -> None:
        """Keep configuration errors free of secret values."""
        super().__init__("Enabled LLM logs require a Langfuse URL and project credentials.")


class MissingPiiEngineHostnameError(ValueError):
    """The configured PII Engine URL has no hostname."""

    def __init__(self) -> None:
        """Set a safe configuration error message."""
        super().__init__("Configured pii_engine_url must include a hostname.")


class InvalidMcpCatalogConfigError(ValueError):
    """The enabled catalog needs unambiguous operator-owned mappings."""

    def __init__(self) -> None:
        """Keep validation errors free of registration details."""
        super().__init__("Enabled MCP catalog requires a stable native team ID and unique MCP IDs.")


class InvalidContextForgeAccountConfigError(ValueError):
    """Enabled account onboarding needs fixed native API configuration."""

    def __init__(self) -> None:
        """Use a safe error without service credentials."""
        super().__init__(
            "Native account onboarding requires the catalog, HTTPS URL, roles and "
            "a bearer token or an explicitly configured trusted-proxy service identity."
        )


class InvalidContextForgeOAuthConfigError(ValueError):
    """Personal OAuth requires fixed operator-owned configuration."""

    def __init__(self) -> None:
        """Keep validation errors free of native configuration and credentials."""
        super().__init__(
            "Personal MCP OAuth requires account onboarding, trusted-proxy service auth, "
            "approved HTTPS Studio/callback origins and per-integration authorization origins."
        )


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
        _ = parsed.port
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
    usage_timezone: str = "Europe/Berlin"

    # A disabled viewer has no Langfuse client and does not need credentials.
    llm_logs_enabled: bool = False
    langfuse_url: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # Native features remain separately gated until runtime publication/qualification.
    mcp_catalog_enabled: bool = False
    # Fixed authenticated data-plane origin, separate from private analytics.
    mcp_gateway_url: str = ""
    contextforge_team_id: str = Field(default="", max_length=100, pattern=r"^[a-zA-Z0-9_-]*$")
    mcp_catalog: list[McpRegistration] = Field(default_factory=list, max_length=200)
    contextforge_account_onboarding_enabled: bool = False
    contextforge_url: str = ""
    contextforge_ca_cert: str = ""
    contextforge_service_token: SecretStr = SecretStr("")
    contextforge_service_auth_mode: Literal["bearer", "trusted-proxy"] = "bearer"
    contextforge_service_account_email: str = Field(default="", max_length=254)
    contextforge_global_role_id: str = Field(
        default="", max_length=100, pattern=r"^[a-zA-Z0-9_-]*$"
    )
    contextforge_team_role_id: str = Field(default="", max_length=100, pattern=r"^[a-zA-Z0-9_-]*$")
    mcp_connections_enabled: bool = False
    contextforge_oauth_studio_origin: str = ""
    contextforge_oauth_callback_url: str = ""
    contextforge_operator_discovery_enabled: bool = False
    contextforge_admin_discovery_enabled: bool = False
    # Loaded only from the verified setup projection, never from browser input.
    contextforge_admin_discovery_role_id: str = ""
    contextforge_operator_email: str = Field(default="", max_length=254)
    contextforge_operator_subject: str = Field(default="", max_length=254)
    contextforge_operator_role_name: str = "neurwerk-mcp-discovery"
    # Resolved only from the trusted setup projection, never from browser input.
    contextforge_operator_role_id: str = ""
    contextforge_publication_status_path: str = ""
    mcp_setup_enabled: bool = False
    mcp_openbao_url: str = "https://infra-openbao.infra-openbao.svc.cluster.local:8200"
    mcp_openbao_ca_cert: str = "/var/run/contextforge/ca.crt"
    mcp_openbao_token_file: str = "/var/run/mcp-identity/openbao-token"  # noqa: S105 -- file path
    mcp_kubernetes_url: str = "https://kubernetes.default.svc"
    mcp_kubernetes_token_file: str = "/var/run/mcp-identity/kubernetes-token"  # noqa: S105 -- file path
    mcp_kubernetes_ca_cert: str = "/var/run/mcp-identity/ca.crt"
    mcp_provider_admin_url: str = (
        "http://contextforge-providers.infra-agentgateway.svc.cluster.local:15000"
    )

    @model_validator(mode="after")
    def validate_mcp_setup(self) -> Self:
        """Runtime management is an explicit compatible-chart and database opt-in."""
        if self.mcp_setup_enabled and (
            not self.notice_dsn
            or not self.contextforge_admin_discovery_enabled
            or not self.contextforge_publication_status_path
            or not self.mcp_openbao_url.startswith("https://")
            or not self.mcp_kubernetes_url.startswith("https://")
            or any(item.credential is None or not item.upstream_url for item in self.mcp_catalog)
        ):
            raise InvalidContextForgeAccountConfigError
        return self

    @field_validator("mcp_gateway_url")
    @classmethod
    def validate_mcp_gateway_url(cls, value: str) -> str:
        """Allow a fixed HTTP(S) origin only; callers never select a destination."""
        if not value:
            return value
        parsed = _parse_url(value)
        if (
            parsed is None
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or any(c.isspace() or c == "\\" for c in value)
        ):
            raise ValueError("MCP gateway must be a fixed HTTP(S) origin")  # noqa: TRY003
        return value.rstrip("/")

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

    # Dedicated Studio-owned database; schema is initialized by the explicit migrate command.
    notice_database_url: str = ""
    notice_postgres_host: str = ""
    notice_postgres_port: int = 5432
    notice_postgres_database: str = "studio"
    notice_postgres_user: str = "studio"
    notice_postgres_password: str = ""
    notice_port: int = 4091
    notice_tls_cert: str = "/var/run/studio-notices/tls/tls.crt"
    notice_tls_key: str = "/var/run/studio-notices/tls/tls.key"
    notice_tls_ca: str = "/var/run/studio-notices/tls/ca.crt"
    notice_client_cn: str = "monitor-agentgateway-extproc-studio"

    @property
    def notice_dsn(self) -> str:
        """Build a safely escaped DSN from the namespace-local password."""
        if self.notice_database_url:
            return self.notice_database_url
        if not self.notice_postgres_host or not self.notice_postgres_password:
            return ""
        return (
            f"postgresql://{quote(self.notice_postgres_user, safe='')}:"
            f"{quote(self.notice_postgres_password, safe='')}@{self.notice_postgres_host}:"
            f"{self.notice_postgres_port}/{quote(self.notice_postgres_database, safe='')}"
        )

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

    @model_validator(mode="after")
    def validate_langfuse_config(self) -> Self:
        """Fail startup if the enabled viewer cannot use a fixed project endpoint."""
        if not self.llm_logs_enabled:
            return self
        parsed = _parse_url(self.langfuse_url)
        if (
            parsed is None
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or not self.langfuse_public_key
            or not self.langfuse_secret_key
        ):
            raise InvalidLangfuseConfigError
        return self

    @model_validator(mode="after")
    def validate_mcp_catalog_config(self) -> Self:
        """Use one stable native team for all approved registrations."""
        if self.mcp_catalog_enabled and (
            not self.contextforge_team_id
            or len({item.id for item in self.mcp_catalog}) != len(self.mcp_catalog)
        ):
            raise InvalidMcpCatalogConfigError
        return self

    @model_validator(mode="after")
    def validate_contextforge_account_config(self) -> Self:
        """Enable only a fixed HTTPS administrative endpoint with isolated credentials."""
        if not self.contextforge_account_onboarding_enabled:
            return self
        parsed = _parse_url(self.contextforge_url)
        if (
            not self.mcp_catalog_enabled
            or parsed is None
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (
                self.contextforge_service_auth_mode == "bearer"
                and not self.contextforge_service_token.get_secret_value().strip()
            )
            or (
                self.contextforge_service_auth_mode == "trusted-proxy"
                and not self.contextforge_service_account_email
            )
            or not self.contextforge_global_role_id
            or not self.contextforge_team_role_id
            or self.contextforge_global_role_id == self.contextforge_team_role_id
        ):
            raise InvalidContextForgeAccountConfigError
        return self

    @field_validator("contextforge_service_account_email", "contextforge_operator_email")
    @classmethod
    def validate_contextforge_service_email(cls, value: str) -> str:
        """Accept only a canonical operator-configured native identity, never request input."""
        if value and (
            not value.isascii()
            or not re.fullmatch(r"[^@\s/\\?#\x00-\x1f\x7f]+@[^@\s/\\?#\x00-\x1f\x7f]+", value)
        ):
            raise InvalidContextForgeAccountConfigError
        return value.lower()

    @model_validator(mode="after")
    def validate_operator_discovery(self) -> Self:
        """Discovery needs an explicit bound identity and the existing private proxy."""
        if self.contextforge_admin_discovery_enabled and (
            self.contextforge_operator_discovery_enabled
            or not self.contextforge_account_onboarding_enabled
            or not self.mcp_connections_enabled
            or self.contextforge_service_auth_mode != "trusted-proxy"
            or not self.contextforge_publication_status_path
            or not self.contextforge_oauth_studio_origin
        ):
            raise InvalidContextForgeAccountConfigError
        if self.contextforge_operator_discovery_enabled and (
            not self.contextforge_account_onboarding_enabled
            or self.contextforge_service_auth_mode != "trusted-proxy"
            or not self.contextforge_operator_email
            or not self.contextforge_operator_subject
            or not self.contextforge_publication_status_path
            or not self.contextforge_operator_role_name
            or not self.contextforge_oauth_studio_origin
        ):
            raise InvalidContextForgeAccountConfigError
        return self

    @model_validator(mode="after")
    def validate_contextforge_oauth_config(self) -> Self:
        """Require fixed trusted-proxy authentication and approved browser destinations."""
        if not self.mcp_connections_enabled:
            return self
        studio = _parse_url(self.contextforge_oauth_studio_origin)
        callback = _parse_url(self.contextforge_oauth_callback_url)
        origins = (studio, callback)
        individual = [
            item
            for item in self.mcp_catalog
            if item.authentication_model == "individual-authentication"
        ]
        if (
            not self.contextforge_account_onboarding_enabled
            or self.contextforge_service_auth_mode != "trusted-proxy"
            or any(
                url is None
                or url.scheme != "https"
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
                for url in origins
            )
            or any(
                character.isspace() or character == "\\"
                for value in (
                    self.contextforge_oauth_studio_origin,
                    self.contextforge_oauth_callback_url,
                )
                for character in value
            )
            or studio is None
            or studio.path
            or callback is None
            or callback.path != "/oauth/callback"
            or (callback.scheme, callback.netloc) != (studio.scheme, studio.netloc)
            or (not individual and not self.contextforge_publication_status_path)
            or any(not item.oauth_authorization_origin for item in individual)
            or len({item.gateway_id for item in self.mcp_catalog if item.gateway_id})
            != sum(bool(item.gateway_id) for item in self.mcp_catalog)
            or len({item.server_id for item in self.mcp_catalog}) != len(self.mcp_catalog)
        ):
            raise InvalidContextForgeOAuthConfigError
        return self
