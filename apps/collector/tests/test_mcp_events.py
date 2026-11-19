import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from studio_collector.mcp_events import McpEventSource
from studio_collector.models import SourceError
from studio_collector.pricing import Account, Catalogue, Price

START = datetime(2026, 11, 19, 14, tzinfo=UTC)
END = START + timedelta(hours=1)


def hit(*, event_id=None, timestamp=None, server="brave"):
    return {
        "_index": "fluent-bit-2026.11.19",
        "_id": str(uuid4()),
        "_source": {
            "studio_mcp": {
                "version": 1,
                "id": event_id or str(uuid4()),
                "occurred_at": timestamp or START.isoformat(),
                "dimensions": {
                    "server": server,
                    "tool": f"neurwerk-contextforge-{server}-brave-web-search",
                    "principal_id": "person",
                    "app_id": "studio",
                },
            }
        },
    }


def page(hits, total):
    return {
        "_scroll_id": "snapshot",
        "timed_out": False,
        "_shards": {"total": 1, "successful": 1, "failed": 0},
        "hits": {"total": {"value": total, "relation": "eq"}, "hits": hits},
    }


async def collect(pages):
    pending = iter(pages)
    cleared = []

    def handler(request):
        if request.method == "DELETE":
            cleared.append(True)
            return httpx.Response(200, json={"succeeded": True})
        if request.url.path.endswith("/_search"):
            body = json.loads(request.content)
            assert body["_source"] == ["studio_mcp"]
            assert body["track_total_hits"]
            assert body["query"]["bool"]["filter"][-1] == {
                "range": {
                    "studio_mcp.occurred_at": {"gte": START.isoformat(), "lt": END.isoformat()}
                }
            }
        value = next(pending)
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        try:
            return await McpEventSource(client, "https://logs").collect(START, END)
        finally:
            assert cleared


async def test_snapshot_pages_deduplicate_deliveries_but_not_separate_invocations():
    first = hit()
    duplicate = deepcopy(first)
    duplicate["_id"] = str(uuid4())
    second = hit()
    rows = await collect([page([first], 3), page([duplicate, second], 3)])
    assert len(rows) == 1 and rows[0].requests == 2
    assert rows[0].dimensions.app_id == "studio"
    catalogue = Catalogue(
        default_rate=Decimal(0),
        accounts=[
            Account(
                server="brave",
                billing_account="search",
                prices=[
                    Price(
                        effective_from=START,
                        tools={
                            "neurwerk-contextforge-brave-brave-web-search": Decimal(5),
                        },
                    )
                ],
            )
        ],
    )
    assert catalogue.apply(rows[0], START).cost_usd == Decimal("0.010")
    free = (await collect([page([hit(server="free")], 1)]))[0]
    assert catalogue.apply(free, START).cost_known == 1
    assert catalogue.apply(free, START).cost_usd == 0
    assert Catalogue().apply(free, START).cost_known == 0


@pytest.mark.parametrize(
    "fault",
    [
        "timeout",
        "shard",
        "approximate",
        "total",
        "empty",
        "repeated",
        "conflict",
        "http",
    ],
)
async def test_incomplete_or_conflicting_snapshots_never_return_partial_counts(fault):
    first = hit()
    next_hit = hit()
    second = page([next_hit], 2)
    if fault == "timeout":
        second["timed_out"] = True
    elif fault == "shard":
        second["_shards"]["failed"] = 1
    elif fault == "approximate":
        second["hits"]["total"]["relation"] = "gte"
    elif fault == "total":
        second["hits"]["total"]["value"] = 3
    elif fault == "empty":
        second["hits"]["hits"] = []
    elif fault == "repeated":
        second["hits"]["hits"] = [first]
    elif fault == "conflict":
        next_hit["_source"]["studio_mcp"]["id"] = first["_source"]["studio_mcp"]["id"]
        next_hit["_source"]["studio_mcp"]["dimensions"]["app_id"] = "other"
    elif fault == "http":
        second = httpx.Response(503)
    with pytest.raises(SourceError):
        await collect([page([first], 2), second])


@pytest.mark.parametrize(
    "updates",
    [
        {"id": "not-a-uuid"},
        {"occurred_at": "2026-11-19T14:00:00"},
        {"arguments": {"private": "not accepted"}},
    ],
)
async def test_invalid_event_rejects_the_entire_bucket(updates):
    invalid = hit()
    invalid["_source"]["studio_mcp"].update(updates)
    with pytest.raises(SourceError):
        await collect([page([hit(), invalid], 2)])


async def test_event_boundaries_and_late_recollection_are_whole_calls():
    first = hit(timestamp="2026-11-19T15:00:00+01:00")
    late = hit(timestamp="2026-11-19T14:59:59.999999Z")
    assert (await collect([page([first], 1)]))[0].requests == 1
    assert (await collect([page([first, late], 2)]))[0].requests == 2
    for timestamp in [END.isoformat(), (START - timedelta(microseconds=1)).isoformat()]:
        with pytest.raises(SourceError):
            await collect([page([hit(timestamp=timestamp)], 1)])


async def test_empty_complete_snapshot_is_empty_usage():
    assert await collect([page([], 0)]) == []
