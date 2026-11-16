"""Native source adapters; neither adapter writes to upstream storage."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from studio_collector.models import ATTRIBUTES, Amount, Dimensions, SourceError, UsageRow


class NativeGroup(BaseModel):
    """Validate native accounting without coercing request/token counts."""

    model_config = ConfigDict(extra="ignore")
    group: dict[str, str | bool | None]
    requests: int = Field(ge=0, strict=True)
    total_tokens: int = Field(alias="totalTokens", ge=0, strict=True)
    cost: Amount | None = None


class NativeWindow(BaseModel):
    """The upstream must acknowledge the exact requested interval."""

    start: AwareDatetime = Field(alias="from")
    end: AwareDatetime = Field(alias="to")


class NativeSummary(BaseModel):
    """Ignore unscoped filterOptions; never return them to the API."""

    time_range: NativeWindow = Field(alias="timeRange")
    groups: list[NativeGroup] = Field(max_length=100_000)


def _known(value: str | bool | None) -> bool:
    if value not in (None, True, False, "true", "false"):
        raise SourceError
    return value is True or value == "true"


class LlmSource:
    """Import complete grouped responses from the existing analytics endpoint."""

    def __init__(self, client: httpx.AsyncClient, url: str) -> None:
        """Keep the separately managed HTTP client."""
        self.client = client
        self.url = url.rstrip("/") + "/api/logs/analytics/summary"

    async def collect(
        self, start: datetime, end: datetime, attributes: dict[str, str] | None = None
    ) -> list[UsageRow]:
        """Read a half-open interval, optionally narrowed for request-ID lookup."""
        keys = [*ATTRIBUTES.values(), "neurwerk.token_usage_known", "neurwerk.cost_known"]
        payload = {
            "timeRange": {
                "from": start.astimezone(UTC).isoformat(),
                "to": end.astimezone(UTC).isoformat(),
            },
            "filters": {"attributes": attributes or {}},
            "groupBy": [{"field": "requestModel"}]
            + [{"field": "attributes", "key": key} for key in keys],
            "bucketCount": 1,
        }
        try:
            response = await self.client.post(self.url, json=payload)
            response.raise_for_status()
            summary = NativeSummary.model_validate_json(response.content)
            if summary.time_range.start != start or summary.time_range.end != end:
                raise SourceError
            return self._rows(summary, set(keys) | {"requestModel"}, attributes or {})
        except (httpx.HTTPError, ValueError) as error:
            raise SourceError from error

    @staticmethod
    def _rows(summary: NativeSummary, keys: set[str], attributes: dict[str, str]) -> list[UsageRow]:
        result: dict[Dimensions, UsageRow] = {}
        seen: set[tuple[tuple[str, str | bool | None], ...]] = set()
        for item in summary.groups:
            group = item.group
            identity = tuple(sorted(group.items()))
            if group.keys() != keys or identity in seen:
                raise SourceError
            seen.add(identity)
            # The source must not widen an authenticated request-ID lookup.
            if any(group.get(key) != value for key, value in attributes.items() if key in keys):
                raise SourceError
            dimensions = Dimensions.model_validate(
                {
                    "model": group["requestModel"],
                    **{name: group[key] for name, key in ATTRIBUTES.items()},
                }
            )
            row = result.setdefault(dimensions, UsageRow(dimensions=dimensions))
            row.requests += item.requests
            row.total_tokens += item.total_tokens
            row.cost_usd += item.cost or Decimal(0)
            if _known(group["neurwerk.token_usage_known"]):
                row.tokens_known += item.requests
            if _known(group["neurwerk.cost_known"]) and item.cost is not None:
                row.cost_known += item.requests
        return list(result.values())


MCP_LABELS = {
    name: f"studio_{name}"
    for name in Dimensions.model_fields
    if name not in {"model", "server", "tool", "requested_model", "resolved_model"}
}
MCP_LABELS.update(server="server", tool="resource")
MCP_SELECTOR = (
    'agentgateway_mcp_requests_total{gateway="infra-agentgateway-gateway",'
    'listener="api-bindings",method="tools/call",resource_type="tool"}'
)


class Sample(BaseModel):
    """Prometheus instant-vector sample."""

    metric: dict[str, str]
    value: tuple[float, Amount]


class Vector(BaseModel):
    """Successful, non-truncated instant-vector response."""

    result_type: str = Field(alias="resultType", pattern="^vector$")
    result: list[Sample] = Field(max_length=100_000)


class PrometheusResult(BaseModel):
    """Warnings can indicate partial results and are rejected."""

    status: str = Field(pattern="^success$")
    data: Vector
    warnings: list[str] = Field(default_factory=list, max_length=0)
    infos: list[str] = Field(default_factory=list, max_length=0)


class McpSource:
    """Reset-aware tool-call estimates from caller-facing native counter series."""

    def __init__(
        self, client: httpx.AsyncClient, url: str, up_selector: str, scrape_seconds: int
    ) -> None:
        """Configure the exact gateway scrape target and its expected interval."""
        self.client = client
        self.url = url.rstrip("/") + "/api/v1/query"
        self.up_selector = up_selector
        self.scrape_seconds = scrape_seconds

    async def query(self, expression: str, end: datetime) -> list[Sample]:
        """Reject invalid or partial Prometheus responses."""
        try:
            response = await self.client.get(
                self.url, params={"query": expression, "time": end.timestamp(), "timeout": "30s"}
            )
            response.raise_for_status()
            return PrometheusResult.model_validate_json(response.content).data.result
        except (httpx.HTTPError, ValueError) as error:
            raise SourceError from error

    async def collect(self, start: datetime, end: datetime) -> list[UsageRow]:
        """Increase each original series before aggregation; never round counter estimates."""
        seconds = int((end - start).total_seconds())
        if seconds < self.scrape_seconds * 2:
            raise SourceError
        window = f"[{seconds}s]"
        health = await self.query(f"min_over_time({self.up_selector}{window})", end)
        samples = await self.query(f"count_over_time({self.up_selector}{window})", end)
        minimum = max(2, seconds // self.scrape_seconds - 1)
        if (
            not health
            or len(health) != len(samples)
            or any(sample.value[1] != 1 for sample in health)
            or any(sample.value[1] < minimum for sample in samples)
        ):
            raise SourceError
        # One-sample series cannot establish an increase. Do not replace a valid
        # bucket with the partial vector returned by increase() for those series.
        sparse = await self.query(f"count_over_time({MCP_SELECTOR}{window}) < 2", end)
        if sparse:
            raise SourceError
        labels = ",".join(MCP_LABELS.values())
        samples = await self.query(f"sum by ({labels}) (increase({MCP_SELECTOR}{window}))", end)
        rows: list[UsageRow] = []
        seen: set[Dimensions] = set()
        try:
            for sample in samples:
                dimensions = Dimensions.model_validate(
                    {name: sample.metric.get(label) or None for name, label in MCP_LABELS.items()}
                )
                if dimensions in seen:
                    raise SourceError
                seen.add(dimensions)
                rows.append(UsageRow(dimensions=dimensions, requests=sample.value[1]))
        except ValueError as error:
            raise SourceError from error
        return rows
