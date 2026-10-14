"""Public inspection-root snapshots and their derived download manifest."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from k8s_stack_studio.models.gateway import GatewayModel, GatewaySchema

SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", min_length=64, max_length=64)]


class TrustCertificate(GatewayModel):
    """Exactly one public certificate; validity is derived, never trusted input."""

    fingerprint_sha256: SHA256
    pem: str = Field(min_length=1, max_length=16_384)
    purpose: Literal["inspection-root"]
    state: Literal["active", "transitional"]


class TrustSnapshot(GatewayModel):
    """One content-addressed bundle in declared certificate order."""

    version: SHA256
    published_at: AwareDatetime
    bundle_sha256: SHA256
    certificates: list[TrustCertificate] = Field(min_length=1, max_length=16)


class TrustSnapshots(GatewaySchema):
    """Single atomic publisher document; the current version must be retained."""

    current_version: SHA256
    versions: list[TrustSnapshot] = Field(min_length=1, max_length=64)


class TrustCertificateInfo(GatewayModel):
    """Independently checked metadata, with no publisher-supplied file paths."""

    fingerprint_sha256: SHA256
    purpose: Literal["inspection-root"]
    state: Literal["active", "transitional"]
    not_before: AwareDatetime
    not_after: AwareDatetime


class TrustVersionInfo(GatewayModel):
    """Metadata for downloading and checking an exact retained bundle."""

    version: SHA256
    published_at: AwareDatetime
    bundle_sha256: SHA256
    certificates: list[TrustCertificateInfo]


class TrustManifest(GatewaySchema):
    """Current and retained assets; callers construct only fixed same-origin URLs."""

    schema_version: Literal[1] = 1
    current_version: SHA256
    versions: list[TrustVersionInfo]
