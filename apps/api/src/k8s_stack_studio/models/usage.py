"""Pydantic schemas for Langfuse per-user token and cost usage."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UsagePeriod(BaseModel):
    """Aggregated token and cost usage for one time period."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class UsageResponse(BaseModel):
    """All calendar and rolling usage periods for one Langfuse user."""

    total: UsagePeriod
    this_month: UsagePeriod
    last_month: UsagePeriod
    last_30_days: UsagePeriod
    this_week: UsagePeriod
    last_week: UsagePeriod
    last_7_days: UsagePeriod
    today: UsagePeriod
    last_24_hours: UsagePeriod


class LangfuseUsageItem(BaseModel):
    """A model-specific daily Langfuse usage aggregate."""

    model_config = ConfigDict(populate_by_name=True)

    input_usage: int = Field(default=0, alias="inputUsage")
    output_usage: int = Field(default=0, alias="outputUsage")
    total_usage: int = Field(default=0, alias="totalUsage")
    total_cost: float = Field(default=0.0, alias="totalCost")


class LangfuseDailyMetric(BaseModel):
    """A daily Langfuse metric bucket."""

    model_config = ConfigDict(populate_by_name=True)

    usage: list[LangfuseUsageItem] = Field(default_factory=list)


class LangfuseCostDetails(BaseModel):
    """Cost fields returned for a Langfuse generation observation."""

    total: float = 0.0


class LangfuseObservation(BaseModel):
    """The usage fields needed from a Langfuse generation observation."""

    model_config = ConfigDict(populate_by_name=True)

    prompt_tokens: int = Field(default=0, alias="promptTokens")
    completion_tokens: int = Field(default=0, alias="completionTokens")
    total_tokens: int = Field(default=0, alias="totalTokens")
    cost_details: LangfuseCostDetails = Field(
        default_factory=LangfuseCostDetails,
        alias="costDetails",
    )


class LangfusePagination(BaseModel):
    """Page metadata returned by legacy Langfuse public endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    page: int = 1
    total_pages: int = Field(default=1, alias="totalPages")


class LangfuseDailyMetricsResponse(BaseModel):
    """Paginated daily metrics response from the Langfuse public API."""

    data: list[LangfuseDailyMetric] = Field(default_factory=list)
    meta: LangfusePagination


class LangfuseObservationsResponse(BaseModel):
    """Paginated observations response from the Langfuse public API."""

    data: list[LangfuseObservation] = Field(default_factory=list)
    meta: LangfusePagination
