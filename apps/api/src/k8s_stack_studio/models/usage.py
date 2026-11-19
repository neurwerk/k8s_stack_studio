"""Public reporting schemas shared by the existing LLM and MCP dashboard."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field
from studio_collector.models import Kind, UsageRow


class Coverage(BaseModel):
    """Missing coverage is independent of known accounting in collected records."""

    activated_at: datetime | None = None
    refreshed_at: datetime | None = None
    complete: bool = False
    stale: bool = True
    provisional: bool = False
    estimated: bool = False


class UsageMetric(BaseModel):
    """Reported sums are not complete totals when evidence or coverage is missing."""

    state: Literal["known", "partial", "unknown"] = "known"
    reported_sum: int | float = 0
    complete_total: int | float | None = 0
    known_records: float = 0
    total_records: float = 0

    def add(
        self,
        value: int | float,
        records: float,
        known_records: float = 0,
        *,
        known: bool | None = None,
    ) -> None:
        """Retain reported contributions separately from accounting evidence."""
        self.reported_sum += value
        self.total_records += records
        self.known_records += records if known is True else known_records
        self.state = (
            "known"
            if self.known_records == self.total_records
            else "partial"
            if self.known_records
            else "unknown"
        )
        self.complete_total = self.reported_sum if self.state == "known" else None

    def unavailable(self) -> None:
        """Missing coverage or unsupported measurements cannot become known zero."""
        self.state = "partial" if self.known_records else "unknown"
        self.complete_total = None


class UsageAccounting(BaseModel):
    """Independent token and cost evidence."""

    tokens: UsageMetric = Field(default_factory=UsageMetric)
    cost_usd: UsageMetric = Field(default_factory=UsageMetric)


class UsagePeriod(BaseModel):
    """A single, non-overlapping set of stored usage rows."""

    requests: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0, allow_inf_nan=False)
    request_scope: Literal["native_llm_records", "mcp_calls"] = "native_llm_records"
    accounting: UsageAccounting = Field(default_factory=UsageAccounting)

    def add(self, row: UsageRow) -> None:
        """Combine whole invocation counts from the reporting store."""
        self.requests += int(row.requests)
        self.total_tokens += row.total_tokens
        self.cost_usd += float(row.cost_usd)
        self.accounting.tokens.add(row.total_tokens, float(row.requests), float(row.tokens_known))
        self.accounting.cost_usd.add(
            float(row.cost_usd), float(row.requests), float(row.cost_known)
        )

    def qualify(self, kind: Kind, coverage: Coverage) -> None:
        """Apply collection and metric availability after summing rows."""
        if kind == "mcp":
            self.request_scope = "mcp_calls"
            self.accounting.tokens.unavailable()
        if not coverage.complete:
            self.accounting.tokens.unavailable()
            self.accounting.cost_usd.unavailable()


class UsageResponse(BaseModel):
    """Existing calendar and rolling totals."""

    total: UsagePeriod
    this_month: UsagePeriod
    last_month: UsagePeriod
    last_30_days: UsagePeriod
    this_week: UsagePeriod
    last_week: UsagePeriod
    last_7_days: UsagePeriod
    today: UsagePeriod
    last_24_hours: UsagePeriod
    coverage: dict[str, Coverage] = Field(default_factory=dict)


class ModelUsage(UsagePeriod):
    """Requested model, or a server/tool pair for the same MCP charts."""

    model: str | None
    server: str | None = None
    tool: str | None = None


class DailyUsage(BaseModel):
    """One local calendar day or a bounded multi-day chart point."""

    date: date
    end_date: date | None = None
    models: list[ModelUsage]
    coverage: Coverage = Field(default_factory=Coverage)


class DailyUsageResponse(BaseModel):
    """Calendar usage, with missing periods explicitly identified."""

    timezone: str
    start_date: date
    end_date: date
    today: date
    kind: Kind = "llm"
    days: list[DailyUsage]
    coverage: Coverage = Field(default_factory=Coverage)
    previous_year: list[DailyUsage] | None = None


class UserUsageTotal(UsagePeriod):
    """Usage attributed to a trusted principal."""

    user_id: str


class UsagePeopleResponse(BaseModel):
    """Active attributed principals without directory profile information."""

    timezone: str
    start_date: date
    end_date: date
    users: list[UserUsageTotal]
    coverage: Coverage = Field(default_factory=Coverage)


class UsageSource(UsagePeriod):
    """Non-secret recorded app or credential identifier."""

    id: str | None
    kind: str | None = None
    name: str | None = None
    name_status: Literal["not_looked_up", "unavailable", "resolved"] = "not_looked_up"


class UsagePersonSources(BaseModel):
    """Independent app and credential breakdowns of the same person's usage."""

    user_id: str | None
    total: UsagePeriod = Field(default_factory=UsagePeriod)
    apps: list[UsageSource] = Field(default_factory=list)
    credentials: list[UsageSource] = Field(default_factory=list)


class UsageNameEnrichment(BaseModel):
    """Directory lookup completeness is independent of accounting completeness."""

    eligible_keys: int = 0
    looked_up_keys: int = 0
    named_keys: int = 0
    limit_reached: bool = False
    lookup_failed: bool = False


class UsageSourcesResponse(BaseModel):
    """Independent app, key and principal views; these totals must not be added."""

    timezone: str
    start_date: date
    end_date: date
    apps: list[UsageSource]
    credentials: list[UsageSource]
    origins: list[UsageSource] = Field(default_factory=list)
    people: list[UsagePersonSources] = Field(default_factory=list)
    key_name_enrichment: UsageNameEnrichment = Field(default_factory=UsageNameEnrichment)
    coverage: Coverage = Field(default_factory=Coverage)
