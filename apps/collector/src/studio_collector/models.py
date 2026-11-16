"""Bounded, normalized reporting dimensions and source-independent measures."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["llm", "mcp"]
Identifier = Annotated[str, Field(min_length=1, max_length=255)]
Amount = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class Dimensions(BaseModel):
    """Stable identifiers only; request IDs never become aggregate dimensions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_id: Identifier | None = None
    app_id: Identifier | None = None
    credential_id: Identifier | None = None
    credential_kind: Identifier | None = None
    model: Identifier | None = None
    server: Identifier | None = None
    tool: Identifier | None = None
    entry_mode: Identifier | None = None
    destination_kind: Identifier | None = None
    destination_id: Identifier | None = None
    provider_id: Identifier | None = None
    binding_id: Identifier | None = None
    protocol_profile: Identifier | None = None
    operation_id: Identifier | None = None
    provider_credential_source: Identifier | None = None
    policy_revision: Identifier | None = None
    requested_model: Identifier | None = None
    resolved_model: Identifier | None = None
    billing_classification: Identifier | None = None

    @property
    def key(self) -> str:
        """Use a bounded unique key even when metadata exceeds B-tree tuple limits."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


ATTRIBUTES = {
    name: "agentgateway.user" if name == "principal_id" else f"neurwerk.{name}"
    for name in Dimensions.model_fields
    if name not in {"model", "server", "tool"}
}


class UsageRow(BaseModel):
    """Reported sums plus independent evidence counts; MCP calls remain fractional."""

    model_config = ConfigDict(extra="forbid")

    dimensions: Dimensions
    requests: Amount = Decimal(0)
    total_tokens: int = Field(default=0, ge=0, strict=True)
    tokens_known: Amount = Decimal(0)
    cost_usd: Amount = Decimal(0)
    cost_known: Amount = Decimal(0)
    rate: Amount | None = None
    price_revision: str | None = None
    billing_account: str | None = None


class SourceError(RuntimeError):
    """The source did not return a complete, valid result."""


class StoreError(RuntimeError):
    """Reporting schema is missing or incompatible."""


class InvalidUsageRangeError(ValueError):
    """The requested inclusive date range is invalid."""
