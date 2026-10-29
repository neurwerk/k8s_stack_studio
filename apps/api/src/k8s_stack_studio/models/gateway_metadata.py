"""Fixed, bounded presentation dimensions; never an arbitrary upstream filter."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

MetadataValue = Annotated[
    str, Field(min_length=1, max_length=255, pattern=r"^[^\s\x00-\x1f\x7f]+$")
]
BillingClassification = Literal["global_api", "override_api", "subscription", "unknown"]


class GatewayFilters(BaseModel):
    """Exact matches on approved normalized metadata, with no caller-selected owner."""

    model_config = ConfigDict(extra="forbid")

    entry_mode: Literal["api", "forward_proxy"] | None = None
    destination_kind: Literal["model", "mcp", "application"] | None = None
    destination_id: MetadataValue | None = None
    provider_id: MetadataValue | None = None
    binding_id: MetadataValue | None = None
    protocol_profile: MetadataValue | None = None
    operation_id: MetadataValue | None = None
    provider_credential_source: Literal["global", "override", "none"] | None = None
    policy_revision: MetadataValue | None = None
    requested_model: MetadataValue | None = None
    resolved_model: MetadataValue | None = None
    billing_classification: BillingClassification | None = None
    request_id: MetadataValue | None = None
    app_id: MetadataValue | None = None
    credential_id: MetadataValue | None = None
    credential_kind: Literal["personal", "managed"] | None = None

    def attributes(self) -> dict[str, str]:
        """Map only declared fields, including when a route extends this model."""
        return {
            f"neurwerk.{name}": value
            for name in GatewayFilters.model_fields
            if (value := getattr(self, name)) is not None
        }


class UsageQuery(GatewayFilters):
    """Inclusive calendar bounds plus the same display filters."""

    start: Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")] | None = None
    end: Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")] | None = None


class GatewayMetadata(GatewayFilters):
    """Allowlisted trace context; absent or malformed evidence remains unknown."""

    billing_classification: BillingClassification = "unknown"
    request_text_inspection: Literal[
        "scanned", "cached_decision", "not_scanned", "disabled", "unknown"
    ] = "unknown"
    dispatch_binding_id: MetadataValue | None = None
    dispatch_destination_id: MetadataValue | None = None
    dispatch_attempted: StrictBool | None = None
    request_outcome: Literal["http_error", "gateway_error", "unknown"] = "unknown"
    target_credential_mode: Literal["global", "override", "none", "unknown"] = "unknown"
    token_usage_known: StrictBool | None = None
    cost_known: StrictBool | None = None

    @classmethod
    def from_metadata(cls, metadata: dict[str, object]) -> GatewayMetadata:
        """Read only normalized top-level scalars, never raw headers or nested payloads."""
        values: dict[str, object] = {}
        for name in cls.model_fields:
            value = metadata.get(f"neurwerk.{name}")
            if value is None:
                continue
            try:
                cls.model_validate({name: value})
            except ValidationError:
                continue
            values[name] = value
        return cls.model_validate(values)
