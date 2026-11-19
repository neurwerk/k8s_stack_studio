"""Read metadata-only MCP invocation events from a stable OpenSearch scroll."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from studio_collector.models import Dimensions, SourceError, UsageRow


class Invocation(BaseModel):
    """A gateway-generated event; arguments and results are never accepted."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    id: UUID
    occurred_at: AwareDatetime
    dimensions: Dimensions


class HitSource(BaseModel):
    """Only the usage envelope is requested from the log index."""

    studio_mcp: Invocation


class Hit(BaseModel):
    """One indexed document, potentially a duplicate of an earlier delivery."""

    source: HitSource = Field(alias="_source")
    id: str = Field(alias="_id", min_length=1)
    index: str = Field(alias="_index", min_length=1)


class Total(BaseModel):
    """Reject approximate or truncated hit totals."""

    value: int = Field(ge=0, strict=True)
    relation: Literal["eq"]


class Hits(BaseModel):
    """One page in a snapshot."""

    total: Total
    hits: list[Hit]


class Shards(BaseModel):
    """A partial shard result cannot replace a valid reporting bucket."""

    failed: Literal[0]
    total: int = Field(gt=0, strict=True)


class Cursor(BaseModel):
    """Capture the scroll handle even when validating its documents fails."""

    scroll_id: str = Field(alias="_scroll_id", min_length=1)


class Page(Cursor):
    """A successful, complete OpenSearch page."""

    timed_out: Literal[False]
    shards: Shards = Field(alias="_shards")
    hits: Hits


def _remember(
    hit: Hit,
    events: dict[UUID, Invocation],
    documents: set[tuple[str, str]],
    start: datetime,
    end: datetime,
) -> None:
    document = (hit.index, hit.id)
    if document in documents:
        raise SourceError
    documents.add(document)
    event = hit.source.studio_mcp
    if (
        not start <= event.occurred_at < end
        or not event.dimensions.server
        or not event.dimensions.tool
    ):
        raise SourceError
    previous = events.setdefault(event.id, event)
    if previous != event:
        raise SourceError


class McpEventSource:
    """Count each captured invocation once; never extrapolate sampled counters."""

    def __init__(self, client: httpx.AsyncClient, url: str) -> None:
        """Use a scoped, TLS-verifying, read-only search client."""
        self.client = client
        self.url = url.rstrip("/")

    async def collect(self, start: datetime, end: datetime) -> list[UsageRow]:
        """Read a half-open event interval from a stable snapshot, then aggregate."""
        body = {
            "size": 1000,
            "sort": ["_doc"],
            "_source": ["studio_mcp"],
            "track_total_hits": True,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"kubernetes.namespace_name.keyword": "infra-agentgateway"}},
                        {"exists": {"field": "studio_mcp.id"}},
                        {
                            "range": {
                                "studio_mcp.occurred_at": {
                                    "gte": start.isoformat(),
                                    "lt": end.isoformat(),
                                }
                            }
                        },
                    ]
                }
            },
        }
        scroll_id = None
        events: dict[UUID, Invocation] = {}
        documents: set[tuple[str, str]] = set()
        fetched = 0
        total = None
        try:
            response = await self.client.post(
                f"{self.url}/fluent-bit-*/_search",
                params={
                    "scroll": "2m",
                    "allow_partial_search_results": "false",
                    "allow_no_indices": "false",
                },
                json=body,
            )
            for _ in range(1000):
                response.raise_for_status()
                payload = response.json()
                scroll_id = Cursor.model_validate(payload).scroll_id
                page = Page.model_validate(payload)
                if total is None:
                    total = page.hits.total.value
                if page.hits.total.value != total:
                    raise SourceError
                fetched += len(page.hits.hits)
                if fetched > total:
                    raise SourceError
                for hit in page.hits.hits:
                    _remember(hit, events, documents, start, end)
                if fetched == total:
                    return self._rows(events.values())
                if not page.hits.hits:
                    raise SourceError
                response = await self.client.post(
                    f"{self.url}/_search/scroll", json={"scroll": "2m", "scroll_id": scroll_id}
                )
            raise SourceError
        except (httpx.HTTPError, ValueError) as error:
            raise SourceError from error
        finally:
            if scroll_id:
                # The bounded scroll expires even if releasing it fails.
                with suppress(httpx.HTTPError):
                    await self.client.request(
                        "DELETE", f"{self.url}/_search/scroll", json={"scroll_id": [scroll_id]}
                    )

    @staticmethod
    def _rows(events: Iterable[Invocation]) -> list[UsageRow]:
        rows: dict[Dimensions, UsageRow] = {}
        for event in events:
            row = rows.setdefault(event.dimensions, UsageRow(dimensions=event.dimensions))
            row.requests += Decimal(1)
        return list(rows.values())
