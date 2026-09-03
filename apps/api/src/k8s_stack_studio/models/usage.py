"""Public usage schemas and private AgentGateway analytics models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UsagePeriod(BaseModel):
    """Aggregated calls, tokens, and cost for one time period."""

    requests: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0, allow_inf_nan=False)


class UsageResponse(BaseModel):
    """All calendar and rolling usage periods for one Studio user."""

    total: UsagePeriod
    this_month: UsagePeriod
    last_month: UsagePeriod
    last_30_days: UsagePeriod
    this_week: UsagePeriod
    last_week: UsagePeriod
    last_7_days: UsagePeriod
    today: UsagePeriod
    last_24_hours: UsagePeriod


class AgentGatewaySummaryGroup(BaseModel):
    """Relevant values from one AgentGateway analytics summary group."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True, strict=True)

    group: dict[str, object]
    requests: int = Field(ge=0)
    total_tokens: int = Field(alias="totalTokens", ge=0)
    cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class AgentGatewaySummary(BaseModel):
    """Relevant fields from AgentGateway's analytics summary response."""

    model_config = ConfigDict(extra="ignore", strict=True)

    groups: list[AgentGatewaySummaryGroup]
