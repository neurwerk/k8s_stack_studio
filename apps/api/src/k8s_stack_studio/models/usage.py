"""Public usage schemas and private AgentGateway analytics models."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)


class UsageMetric(BaseModel):
    """Reported sums are not complete totals when any native record lacks evidence."""

    state: Literal["known", "partial", "unknown"] = "known"
    reported_sum: int | float = 0
    complete_total: int | float | None = 0
    known_records: int = 0
    total_records: int = 0

    def add(self, value: int | float, records: int, *, known: bool) -> None:
        """Retain every reported contribution, including legacy reported retry usage."""
        self.reported_sum += value
        self.total_records += records
        self.known_records += records if known else 0
        self.state = (
            "known"
            if self.known_records == self.total_records
            else "partial"
            if self.known_records
            else "unknown"
        )
        self.complete_total = self.reported_sum if self.state == "known" else None


class UsageAccounting(BaseModel):
    """Completeness applies only to selected native LLM records, not provider bills."""

    tokens: UsageMetric = Field(default_factory=UsageMetric)
    cost_usd: UsageMetric = Field(default_factory=UsageMetric)


class UsagePeriod(BaseModel):
    """Aggregated calls, tokens, and cost for one time period."""

    requests: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    request_scope: Literal["native_llm_records"] = "native_llm_records"
    accounting: UsageAccounting = Field(default_factory=UsageAccounting)

    def add(self, item: AgentGatewaySummaryGroup) -> None:
        """Combine completeness groups without counting them as extra requests."""
        self.requests += item.requests
        self.total_tokens += item.total_tokens
        self.cost_usd += item.cost or 0.0
        self.accounting.tokens.add(
            item.total_tokens, item.requests, known=item.group.token_usage_known is True
        )
        self.accounting.cost_usd.add(
            item.cost or 0.0,
            item.requests,
            known=item.group.cost_known is True and item.cost is not None,
        )


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


class AgentGatewayAccountingKey(BaseModel):
    """PostgreSQL extracts boolean JSON attributes as text; absence stays unknown."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    token_usage_known: StrictBool | None = Field(default=None, alias="neurwerk.token_usage_known")
    cost_known: StrictBool | None = Field(default=None, alias="neurwerk.cost_known")

    @field_validator("token_usage_known", "cost_known", mode="before")
    @classmethod
    def boolean_attribute(cls, value: object) -> object:
        """Accept native PostgreSQL text and JSON booleans without truthy coercion."""
        if value == "true":
            return True
        if value == "false":
            return False
        return value

    @model_validator(mode="before")
    @classmethod
    def flatten_attributes(cls, value: object) -> object:
        """Support flat and nested attributes without dropping unrequested group fields."""
        if not isinstance(value, dict):
            return value
        nested = value.get("attributes")
        if isinstance(nested, dict):
            fields = {key: item for key, item in value.items() if key != "attributes"}
            if fields.keys() & nested.keys():
                raise ValueError("Duplicate analytics group fields")  # noqa: TRY003
            return {**fields, **nested}
        return value


class AgentGatewaySummaryGroup(BaseModel):
    """Relevant values from one AgentGateway analytics summary group."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True, strict=True)

    group: AgentGatewayAccountingKey
    requests: int = Field(ge=0)
    total_tokens: int = Field(alias="totalTokens", ge=0)
    cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class AgentGatewaySummary(BaseModel):
    """Relevant fields from AgentGateway's analytics summary response."""

    model_config = ConfigDict(extra="ignore", strict=True)

    groups: list[AgentGatewaySummaryGroup] = Field(max_length=100_000)


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


class AgentGatewayModelKey(AgentGatewayAccountingKey):
    """The exact grouping requested by Studio, never upstream filter options."""

    request_model: str | None = Field(alias="requestModel")


class AgentGatewayModelGroup(AgentGatewaySummaryGroup):
    """Validated metrics grouped only by requested model."""

    group: AgentGatewayModelKey


class AgentGatewayModelBucket(AgentGatewayModelGroup):
    """A typed upstream time bucket with a timezone-aware timestamp."""

    start: AwareDatetime


class AgentGatewayDailySummary(BaseModel):
    """Private grouped summary; unscoped filterOptions are deliberately ignored."""

    model_config = ConfigDict(extra="ignore", strict=True)

    bucket_seconds: int = Field(alias="bucketSeconds", gt=0)
    groups: list[AgentGatewayModelGroup] = Field(max_length=100_000)
    buckets: list[AgentGatewayModelBucket] = Field(max_length=100_000)


class AgentGatewayUserKey(AgentGatewayAccountingKey):
    """Identity attribute produced by AgentGateway, not supplied by the browser."""

    user_id: str | None = Field(default=None, alias="agentgateway.user")


class AgentGatewayUserGroup(AgentGatewaySummaryGroup):
    """User-scoped summary without access to raw logs or prompt content."""

    group: AgentGatewayUserKey


class AgentGatewayUserSummary(BaseModel):
    """Bound the upstream grouped-user response for the admin leaderboard."""

    model_config = ConfigDict(extra="ignore", strict=True)

    groups: list[AgentGatewayUserGroup] = Field(max_length=45_000)
