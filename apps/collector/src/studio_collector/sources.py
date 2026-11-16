"""Native source adapters; neither adapter writes to upstream storage."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Literal

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat

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
    'agentgateway_mcp_requests_total{gateway="infra-agentgateway/infra-agentgateway-gateway",'
    'listener="api-bindings",method="tools/call",resource_type="tool"}'
)


class Sample(BaseModel):
    """Prometheus instant-vector sample."""

    metric: dict[str, str]
    value: tuple[FiniteFloat, Amount]


class Series(BaseModel):
    """Actual scrape samples, including the boundary baseline when present."""

    metric: dict[str, str]
    values: list[tuple[FiniteFloat, Amount]] = Field(min_length=1, max_length=4000)


class Vector(BaseModel):
    """Successful, non-truncated instant-vector response."""

    result_type: Literal["vector"] = Field(alias="resultType")
    result: list[Sample] = Field(max_length=100_000)


class Matrix(BaseModel):
    """Bounded raw hourly samples; query-range lookback must not fill scrape gaps."""

    result_type: Literal["matrix"] = Field(alias="resultType")
    result: list[Series] = Field(max_length=100_000)


class PrometheusResult(BaseModel):
    """Warnings can indicate partial results and are rejected."""

    status: str = Field(pattern="^success$")
    data: Vector | Matrix
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

    async def _query(self, expression: str, end: datetime) -> Vector | Matrix:
        """Reject invalid or partial Prometheus responses."""
        try:
            response = await self.client.get(
                self.url, params={"query": expression, "time": end.timestamp(), "timeout": "30s"}
            )
            response.raise_for_status()
            return PrometheusResult.model_validate_json(response.content).data
        except (httpx.HTTPError, ValueError) as error:
            raise SourceError from error

    async def query(self, expression: str, end: datetime) -> list[Sample]:
        """Read native reset-aware estimates without accepting another result type."""
        result = await self._query(expression, end)
        if not isinstance(result, Vector):
            raise SourceError
        return result.result

    async def matrix(self, expression: str, end: datetime) -> list[Series]:
        """Read original scrape timestamps and values."""
        result = await self._query(expression, end)
        if not isinstance(result, Matrix):
            raise SourceError
        return result.result

    def _healthy_targets(
        self, series: list[Series], start: float, end: float
    ) -> dict[tuple[str, str], list[float]]:
        targets: dict[tuple[str, str], list[float]] = {}
        tolerance = self.scrape_seconds * 1.5
        for item in series:
            target = _target(item.metric)
            times = [time for time, _ in item.values]
            boundary = [index for index, time in enumerate(times) if time <= start]
            if not boundary or times != sorted(set(times)):
                raise SourceError
            values = item.values[boundary[-1] :]
            times = [time for time, _ in values]
            if (
                target in targets
                or not start - tolerance <= times[0] <= start
                or not end - tolerance <= times[-1] <= end
                or any(value != 1 for _, value in values)
                or any(b - a > tolerance for a, b in pairwise(times))
            ):
                raise SourceError
            targets[target] = times
        if not targets:
            raise SourceError
        return targets

    async def collect(self, start: datetime, end: datetime) -> list[UsageRow]:
        """Classify and count original series before aggregating reporting dimensions."""
        seconds = int((end - start).total_seconds())
        if seconds < self.scrape_seconds * 2:
            raise SourceError
        # Include boundary scrapes and jitter so absence establishes a new counter.
        # Prometheus ranges are (start, end]; a sample on a boundary belongs to the
        # preceding bucket and becomes the next bucket's baseline.
        window = f"[{seconds + 2 * self.scrape_seconds}s]"
        health = await self.matrix(f"{self.up_selector}{window}", end)
        targets = self._healthy_targets(health, start.timestamp(), end.timestamp())
        series = await self.matrix(f"{MCP_SELECTOR}{window}", end)
        samples = await self.query(f"increase({MCP_SELECTOR}[{seconds}s])", end)
        increases = {_identity(sample.metric): sample.value[1] for sample in samples}
        if len(increases) != len(samples):
            raise SourceError
        rows: dict[Dimensions, UsageRow] = {}
        seen: set[tuple[tuple[str, str], ...]] = set()
        try:
            for item in series:
                identity = _identity(item.metric)
                if identity in seen or _target(item.metric) not in targets:
                    raise SourceError
                seen.add(identity)
                amount = _counter_amount(
                    item,
                    start.timestamp(),
                    end.timestamp(),
                    increases.pop(identity, None),
                    targets[_target(item.metric)],
                )
                if amount is None:
                    continue
                dimensions = Dimensions.model_validate(
                    {name: item.metric.get(label) or None for name, label in MCP_LABELS.items()}
                )
                row = rows.setdefault(dimensions, UsageRow(dimensions=dimensions))
                row.requests += amount
        except ValueError as error:
            raise SourceError from error
        if increases:
            raise SourceError
        return list(rows.values())


def _identity(metric: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, value) for key, value in metric.items() if key != "__name__"))


def _target(metric: dict[str, str]) -> tuple[str, str]:
    if not metric.get("job") or not metric.get("instance"):
        raise SourceError
    return metric["job"], metric["instance"]


def _counter_amount(
    series: Series, start: float, end: float, increase: Decimal | None, scrapes: list[float]
) -> Decimal | None:
    times = [time for time, _ in series.values]
    if times != sorted(set(times)) or times[-1] > end:
        raise SourceError
    # Older context may belong to a process that ended before the healthy baseline.
    values = [(time, value) for time, value in series.values if time >= scrapes[0]]
    if not values:
        if increase is not None:
            raise SourceError
        return None
    times = [time for time, _ in values]
    # Persistent counters must appear in every successful target scrape after birth.
    # Missing counter samples cannot be treated as a new zero baseline.
    if times != [time for time in scrapes if time >= times[0]]:
        raise SourceError
    current = [value for time, value in values if time > start]
    if not current:
        if increase is not None:
            raise SourceError
        return None
    if times[0] <= start:
        if len(current) < 2 or increase is None:
            raise SourceError
        return increase
    # Native counters are created lazily. Their first nonzero sample is usage,
    # provided healthy boundary scrapes established that the series was absent.
    # Do not add it to increase(): that also extrapolates before the first sample.
    return current[0] + sum(
        (b - a if b >= a else b for a, b in pairwise(current)),
        Decimal(0),
    )
