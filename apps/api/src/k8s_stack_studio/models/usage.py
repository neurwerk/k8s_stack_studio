"""Public usage schemas and private AgentGateway analytics models."""

from __future__ import annotations

from datetime import date

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


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


class ModelUsage(UsagePeriod):
    """Usage attributed to a requested model, including unknown models."""

    model: str | None


class DailyUsage(BaseModel):
    """One local calendar day, with no model entries when there is no usage."""

    date: date
    models: list[ModelUsage]


class DailyUsageResponse(BaseModel):
    """Inclusive calendar range and daily per-model usage in the configured timezone."""

    timezone: str
    start_date: date
    end_date: date
    today: date
    days: list[DailyUsage]


class UserUsageTotal(UsagePeriod):
    """One attributed principal's totals in the selected calendar range."""

    user_id: str


class UsagePeopleResponse(BaseModel):
    """Active attributed principals, without Keycloak profile information."""

    timezone: str
    start_date: date
    end_date: date
    users: list[UserUsageTotal]


class AgentGatewayModelKey(BaseModel):
    """The exact grouping requested by Studio, never upstream filter options."""

    model_config = ConfigDict(extra="forbid", strict=True)

    request_model: str | None = Field(alias="requestModel")


class AgentGatewayModelGroup(BaseModel):
    """Validated metrics grouped only by requested model."""

    model_config = ConfigDict(extra="ignore", strict=True)

    group: AgentGatewayModelKey
    requests: int = Field(ge=0)
    total_tokens: int = Field(alias="totalTokens", ge=0)
    cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class AgentGatewayModelBucket(AgentGatewayModelGroup):
    """A typed upstream time bucket with a timezone-aware timestamp."""

    start: AwareDatetime


class AgentGatewayDailySummary(BaseModel):
    """Private grouped summary; unscoped filterOptions are deliberately ignored."""

    model_config = ConfigDict(extra="ignore", strict=True)

    bucket_seconds: int = Field(alias="bucketSeconds", gt=0)
    groups: list[AgentGatewayModelGroup]
    buckets: list[AgentGatewayModelBucket]


class AgentGatewayUserKey(BaseModel):
    """Identity attribute produced by AgentGateway, not supplied by the browser."""

    model_config = ConfigDict(extra="forbid", strict=True)

    user_id: str | None = Field(default=None, alias="agentgateway.user")

    @model_validator(mode="before")
    @classmethod
    def normalize_attribute(cls, value: object) -> object:
        """Accept the two upstream encodings of one exact identity attribute."""
        if not isinstance(value, dict) or "agentgateway.user" in value:
            return value
        nested = value.get("attributes")
        if isinstance(nested, dict):
            return {"agentgateway.user": nested.get("agentgateway.user")}
        return value


class AgentGatewayUserGroup(BaseModel):
    """User-scoped summary without access to raw logs or prompt content."""

    model_config = ConfigDict(extra="ignore", strict=True)

    group: AgentGatewayUserKey
    requests: int = Field(ge=0)
    total_tokens: int = Field(alias="totalTokens", ge=0)
    cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class AgentGatewayUserSummary(BaseModel):
    """Bound the upstream grouped-user response for the admin leaderboard."""

    model_config = ConfigDict(extra="ignore", strict=True)

    groups: list[AgentGatewayUserGroup] = Field(max_length=5000)
