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
    caller_auth_modes: list[Literal["legacy", "neurwerk_bearer", "proxy_basic"]] = Field(
        min_length=1, max_length=3
    )

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


class GatewayDestination(GatewayModel):
    """One canonical configured model, MCP integration or application."""

    id: Identifier
    kind: Literal["model", "mcp", "application"]
    display_name: Identifier
    endpoint_ids: list[Identifier] = Field(min_length=1, max_length=32)
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


class GatewayCatalog(GatewaySchema):
    """One effective catalog, with validated references and stable identities."""

    catalog_revision: Identifier
    policy_revision: Identifier
    endpoints: list[GatewayEndpoint] = Field(max_length=32)
    destinations: list[GatewayDestination] = Field(max_length=500)
    profiles: list[GatewayProfile] = Field(max_length=128)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        """Require unambiguous entries and references within this catalog."""
        endpoints = {item.id for item in self.endpoints}
        profiles = {item.id for item in self.profiles}
        destinations = {(item.kind, item.id) for item in self.destinations}
        if (
            len(endpoints) != len(self.endpoints)
            or len(profiles) != len(self.profiles)
            or len(destinations) != len(self.destinations)
            or any(
                not set(item.endpoint_ids) <= endpoints or not set(item.profile_ids) <= profiles
                for item in self.destinations
            )
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


class GatewayStatus(GatewaySchema):
    """Optional publisher observation; configuration cannot generate this data."""

    catalog_revision: Identifier
    applied_policy_revision: Identifier
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    endpoints: list[EndpointObservation] = Field(max_length=32)
    profiles: list[ProfileObservation] = Field(max_length=128)

    @model_validator(mode="after")
    def validate_observations(self) -> Self:
        """Reject duplicate observations and impossible validity windows."""
        if (
            self.valid_until <= self.observed_at
            or len({item.id for item in self.endpoints}) != len(self.endpoints)
            or len({item.id for item in self.profiles}) != len(self.profiles)
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


class GatewayView(GatewayModel):
    """Caller-filtered or administrator configuration and separate health evidence."""

    catalog: GatewayCatalog
    status: GatewayHealth
