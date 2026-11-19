"""Native LLM source adapter; never writes to upstream storage."""

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
