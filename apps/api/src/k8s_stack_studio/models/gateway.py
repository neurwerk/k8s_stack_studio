"""Bounded, non-secret Base-owned gateway configuration and observation contracts."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[^\x00-\x1f\x7f]+$")]
Description = Annotated[str, Field(max_length=2000)]
Permissions = Annotated[list[Identifier], Field(max_length=128)]
ObservedState = Literal["available", "unavailable", "unknown"]
CredentialSource = Literal["company", "caller_supplied", "none"]


class GatewayDocumentError(ValueError):
    """The public projection is inconsistent; never expose its original values."""


class GatewayModel(BaseModel):
    """Reject coercions and unreviewed fields at the publication boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)


class GatewaySchema(GatewayModel):
    """Require an explicit integer schema version, not a coerced bool or float."""

    schema_version: Literal[1]

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema(cls, value: object) -> int:
        """Keep the version-1 publication boundary exact."""
        if not isinstance(value, int) or isinstance(value, bool) or value != 1:
            raise GatewayDocumentError
        return value


class GatewayEndpoint(GatewayModel):
    """Caller-facing URL, separate from any upstream or private management URL."""

    id: Identifier
    url: str = Field(min_length=1, max_length=2048)
    entry_mode: Literal["api", "forward_proxy"]
    caller_auth_modes: list[Literal["oidc_bearer", "neurwerk_bearer", "proxy_basic"]] = Field(
        min_length=1, max_length=3
    )

    @field_validator("caller_auth_modes")
    @classmethod
    def unique_auth(cls, value: list[str]) -> list[str]:
        """Reject repeated authentication choices."""
        if len(set(value)) != len(value):
            raise GatewayDocumentError
        return value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Allow credential-free HTTPS URLs and explicit local HTTP examples only."""
        parsed = urlsplit(value)
        _ = parsed.port
        local = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            (parsed.scheme != "https" and not local)
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(c.isspace() or c == "\\" or ord(c) < 32 for c in value)
        ):
            raise GatewayDocumentError
        return value


class GatewayCredentialMode(GatewayModel):
    """Provider credential source; unrelated to the kind of Neurwerk access key."""

    source: CredentialSource
    required_permissions: Permissions

    @field_validator("required_permissions")
    @classmethod
    def unique_permissions(cls, value: list[str]) -> list[str]:
        """Keep each all-of permission rule unambiguous."""
        if len(set(value)) != len(value):
            raise GatewayDocumentError
        return value


class GatewayDestination(GatewayModel):
    """One canonical configured model, MCP integration or application."""

    id: Identifier
    kind: Literal["model", "mcp", "application"]
    display_name: Identifier
    endpoint_ids: list[Identifier] = Field(min_length=1, max_length=256)
    profile_ids: list[Identifier] = Field(max_length=128)
    required_permissions: Permissions = Field(min_length=1)
    credential_modes: list[GatewayCredentialMode] = Field(max_length=3)
    provider_id: Identifier | None = None
    model: Identifier | None = None

    @model_validator(mode="after")
    def unique_modes(self) -> Self:
        """A provider source has exactly one all-of permission rule."""
        if len({mode.source for mode in self.credential_modes}) != len(self.credential_modes):
            raise GatewayDocumentError
        for values in (self.endpoint_ids, self.profile_ids, self.required_permissions):
            if len(set(values)) != len(values):
                raise GatewayDocumentError
        return self


class GatewayOperation(GatewayModel):
    """Qualification applies to this operation only, never an entire website."""

    id: Identifier
    support: Literal["supported", "unsupported", "unknown"]
    restoration_scope: Literal["request", "persistent", "none"]
    limitations: list[Description] = Field(max_length=32)
    evidence_ref: Identifier | None = None
    verified_at: AwareDatetime | None = None


class GatewayProfile(GatewayModel):
    """Declared support and limits, independent of current observed availability."""

    id: Identifier
    revision: Identifier
    operations: list[GatewayOperation] = Field(max_length=64)
    limitations: list[Description] = Field(max_length=32)

    @model_validator(mode="after")
    def unique_operations(self) -> Self:
        """Avoid conflicting support claims for the same operation."""
        if len({item.id for item in self.operations}) != len(self.operations):
            raise GatewayDocumentError
        return self


class GatewayEntry(GatewayModel):
    """One trusted binding and the destinations owned by that binding."""

    id: Identifier
    provider_id: Identifier | None
    display_name: Identifier
    routes: list[GatewayEndpoint] = Field(max_length=256)
    destinations: list[GatewayDestination] = Field(max_length=500)
    # Published configuration only, never runtime credential or billing evidence.
    company_credential_status: Literal["disabled", "missing", "configured"] | None = None


class GatewayCatalog(GatewayModel):
    """One effective catalog, with validated references and stable identities."""

    schema_version: Literal[2]
    catalog_revision: Identifier
    policy_revision: Identifier
    profiles: list[GatewayProfile] = Field(max_length=128)
    self_hosted_api_providers: list[GatewayEntry] = Field(
        alias="self-hosted-api-providers", max_length=256
    )
    external_api_providers: list[GatewayEntry] = Field(
        alias="external-api-providers", max_length=256
    )
    external_subscription_providers: list[GatewayEntry] = Field(
        alias="external-subscription-providers", max_length=256
    )
    mcp_servers: list[GatewayEntry] = Field(alias="mcp-servers", max_length=200)

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema(cls, value: object) -> int:
        """Accept only the exact grouped catalog version."""
        if type(value) is not int or value != 2:
            raise GatewayDocumentError
        return value

    def groups(self) -> dict[str, list[GatewayEntry]]:
        """Enumerate all four independently presented groups."""
        return {
            name: getattr(self, name)
            for name in (
                "self_hosted_api_providers",
                "external_api_providers",
                "external_subscription_providers",
                "mcp_servers",
            )
        }

    @property
    def endpoints(self) -> list[GatewayEndpoint]:
        """Unique physical listeners, not repeated grouped route references."""
        return list(
            {
                route.id: route
                for entries in self.groups().values()
                for entry in entries
                for route in entry.routes
            }.values()
        )

    @property
    def destinations(self) -> list[GatewayDestination]:
        """Collect owned destinations for bounded cross-catalog consumers."""
        return [
            item
            for entries in self.groups().values()
            for entry in entries
            for item in entry.destinations
        ]

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        """Require unambiguous entries and references within this catalog."""
        entries = [entry for group in self.groups().values() for entry in group]
        providers = (
            self.self_hosted_api_providers
            + self.external_api_providers
            + self.external_subscription_providers
        )
        if len(providers) > 256 or len({entry.id for entry in entries}) != len(entries):
            raise GatewayDocumentError
        routes: dict[str, GatewayEndpoint] = {}
        for entry in entries:
            owned = {route.id for route in entry.routes}
            if len(owned) != len(entry.routes):
                raise GatewayDocumentError
            for route in entry.routes:
                previous = routes.get(route.id)
                if previous is not None and (
                    route.entry_mode != "forward_proxy" or previous != route
                ):
                    raise GatewayDocumentError
                routes[route.id] = route
            if sum(item.kind == "model" for item in entry.destinations) > 32:
                raise GatewayDocumentError
            if any(
                not set(item.endpoint_ids) <= owned or item.provider_id != entry.provider_id
                for item in entry.destinations
            ):
                raise GatewayDocumentError
        profiles = {item.id for item in self.profiles}
        destinations = {(item.kind, item.id) for item in self.destinations}
        if (
            len(routes) > 256
            or len(self.destinations) > 500
            or sum(item.kind == "model" for item in self.destinations) > 256
            or sum(item.kind == "mcp" for item in self.destinations) > 200
            or len(profiles) != len(self.profiles)
            or len(destinations) != len(self.destinations)
            or any(not set(item.profile_ids) <= profiles for item in self.destinations)
        ):
            raise GatewayDocumentError
        return self


class EndpointObservation(GatewayModel):
    """Health evidence for a configured endpoint."""

    id: Identifier
    state: ObservedState


class ProfileObservation(EndpointObservation):
    """Health evidence tied to an exact configured profile revision."""

    revision: Identifier


class SignerObservation(GatewayModel):
    """Public intermediate observed on one sampled listener of a serving replica."""

    pod_uid: Identifier
    pod_name: Identifier
    listener: Identifier
    state: Literal["verified", "unknown"]
    observed_at: AwareDatetime
    fingerprint_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None
    not_after: AwareDatetime | None

    @model_validator(mode="after")
    def complete_evidence(self) -> Self:
        """A verified observation needs both public certificate facts."""
        if self.state == "verified" and (
            self.fingerprint_sha256 is None
            or self.not_after is None
            or self.not_after <= self.observed_at
        ):
            raise GatewayDocumentError
        return self


class GatewayStatus(GatewaySchema):
    """Optional publisher observation; configuration cannot generate this data."""

    catalog_revision: Identifier
    applied_policy_revision: Identifier | None
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    endpoints: list[EndpointObservation] = Field(max_length=256)
    profiles: list[ProfileObservation] = Field(max_length=128)
    signers: list[SignerObservation] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_observations(self) -> Self:
        """Reject duplicate observations and impossible validity windows."""
        if (
            self.valid_until <= self.observed_at
            or len({item.id for item in self.endpoints}) != len(self.endpoints)
            or len({item.id for item in self.profiles}) != len(self.profiles)
            or len({item.pod_uid for item in self.signers}) != len(self.signers)
            or any(
                not self.observed_at <= item.observed_at < self.valid_until for item in self.signers
            )
        ):
            raise GatewayDocumentError
        return self


class ProfileHealth(EndpointObservation):
    """Keep the observed revision even when it does not match desired state."""

    revision: Identifier | None = None


class GatewayHealth(GatewayModel):
    """Sanitized observations; every absent or untrusted observation is unknown."""

    state: Literal["current", "unknown"]
    reason: Literal["missing", "invalid", "stale", "mismatch"] | None
    catalog_revision: Identifier | None = None
    applied_policy_revision: Identifier | None = None
    observed_at: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None
    endpoints: list[EndpointObservation]
    profiles: list[ProfileHealth]
    signers: list[SignerObservation] = Field(default_factory=list)


class GatewayView(GatewayModel):
    """Caller-filtered or administrator configuration and separate health evidence."""

    catalog: GatewayCatalog
    status: GatewayHealth
