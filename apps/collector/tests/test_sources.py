from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from studio_collector.models import ATTRIBUTES, SourceError
from studio_collector.sources import LlmSource, McpSource

START = datetime(2026, 11, 16, 10, tzinfo=UTC)
END = START + timedelta(hours=1)


def group(**updates):
    values = dict.fromkeys([*ATTRIBUTES.values(), "requestModel"])
    values.update(
        {
            "agentgateway.user": "person",
            "neurwerk.app_id": "editor",
            "neurwerk.credential_id": "key",
            "requestModel": "example",
            "neurwerk.token_usage_known": "true",
            "neurwerk.cost_known": "true",
        }
    )
    values.update(updates)
    return {"group": values, "requests": 2, "totalTokens": 10, "cost": 0.03}


async def collect_llm(groups):
    def handler(request):
        import json

        payload = json.loads(request.content)
        assert payload["filters"]["attributes"] == {"agentgateway.user": "person"}
        assert "neurwerk.request_id" not in str(payload["groupBy"])
        return httpx.Response(
            200,
            json={
                "timeRange": payload["timeRange"],
                "groups": groups,
                "filterOptions": {"agentgateway.user": ["unrelated"]},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await LlmSource(client, "http://gateway").collect(
            START, END, {"agentgateway.user": "person"}
        )


async def test_native_dimensions_reported_sums_and_completeness():
    rows = await collect_llm(
        [group(), group(**{"neurwerk.token_usage_known": None, "neurwerk.cost_known": False})]
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.dimensions.principal_id == "person"
    assert row.dimensions.app_id == "editor" and row.dimensions.credential_id == "key"
    assert row.requests == 4 and row.total_tokens == 20
    assert row.cost_usd == Decimal("0.06")
    assert row.cost_known == row.tokens_known == 2


@pytest.mark.parametrize(
    "groups",
    [
        [group(), group()],
        [group(**{"agentgateway.user": "other"})],
        [group(**{"neurwerk.cost_known": "yes"})],
        [{**group(), "requests": "2"}],
        [{**group(), "cost": -1}],
    ],
)
async def test_native_rejects_partial_or_malformed_data(groups):
    with pytest.raises(SourceError):
        await collect_llm(groups)


def counter(values, *, instance="one", tool="lookup", until=3600):
    observed = dict(values)
    value = values[0][1]
    samples = []
    for time in range(values[0][0], until + 1, 30):
        value = observed.get(time, value)
        samples.append([START.timestamp() + time, str(value)])
    return {
        "metric": {
            "__name__": "agentgateway_mcp_requests_total",
            "job": "gateway",
            "instance": instance,
            "gateway": "infra-agentgateway/infra-agentgateway-gateway",
            "listener": "api-bindings",
            "method": "tools/call",
            "resource_type": "tool",
            "studio_principal_id": "person",
            "server": "search",
            "resource": tool,
        },
        "values": samples,
    }


def healthy(instance="one"):
    return {
        "metric": {"__name__": "up", "job": "gateway", "instance": instance},
        "values": [[START.timestamp() + time, "1"] for time in range(0, 3601, 30)],
    }


async def collect_mcp(series, increases, *, health=None, start=START, end=END):
    if health is None:
        health = [healthy(instance) for instance in {s["metric"]["instance"] for s in series}]
    # These are recorded native counter labels, deliberately independent of MCP_SELECTOR.
    selector = (
        'agentgateway_mcp_requests_total{gateway="infra-agentgateway/infra-agentgateway-gateway",'
        'listener="api-bindings",method="tools/call",resource_type="tool"}'
    )

    def handler(request):
        query = request.url.params["query"]
        seconds = int((end - start).total_seconds())
        if query == f'up{{job="gateway"}}[{seconds + 60}s]':
            result_type, result = "matrix", health
        elif query == f"{selector}[{seconds + 60}s]":
            result_type, result = "matrix", series
        elif query == f"increase({selector}[{seconds}s])":
            result_type = "vector"
            result = [
                {
                    "metric": {k: v for k, v in s["metric"].items() if k != "__name__"},
                    "value": [end.timestamp(), str(value)],
                }
                for s, value in zip(series, increases, strict=True)
                if value is not None
            ]
        else:
            # A selector that does not match the native labels returns no series.
            result_type = "vector" if query.startswith("increase(") else "matrix"
            result = []
        return httpx.Response(
            200, json={"status": "success", "data": {"resultType": result_type, "result": result}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await McpSource(client, "http://prometheus", 'up{job="gateway"}', 30).collect(
            start, end
        )


async def test_mcp_lazy_counters_count_first_calls_without_importing_existing_baselines():
    series = [
        counter([(600, 8), (630, 8)], tool="web"),
        counter([(600, 2), (630, 2)], tool="news"),
        counter([(0, 50), (30, 50), (60, 50)], instance="existing", tool="web"),
    ]
    rows = await collect_mcp(series, [0, 0, 0])
    assert {row.dimensions.tool: row.requests for row in rows} == {"web": 8, "news": 2}
    assert all(row.dimensions.principal_id == "person" for row in rows)
    assert all(row.tokens_known == row.cost_known == 0 for row in rows)
    assert await collect_mcp(series, [0, 0, 0]) == rows


async def test_mcp_existing_series_keep_reset_aware_fractional_increases_before_aggregation():
    # Independent native increases; summing these original counters before increase
    # would hide the first target's reset behind the second target's growth.
    series = [
        counter([(0, 100), (30, 100), (60, 2), (90, 5)]),
        counter([(0, 50), (30, 50), (60, 150), (90, 150)], instance="two"),
    ]
    rows = await collect_mcp(series, ["5.125", "100.5"])
    assert len(rows) == 1 and rows[0].requests == Decimal("105.625")


@pytest.mark.parametrize(
    ("values", "native_increase", "expected"),
    [
        ([(600, 8), (630, 9), (660, 12)], "6", 12),
        ([(600, 8), (630, 9), (660, 2), (690, 3)], "6", 12),
    ],
)
async def test_mcp_growing_newborn_does_not_add_extrapolation_twice(
    values, native_increase, expected
):
    rows = await collect_mcp([counter(values)], [native_increase])
    assert rows[0].requests == expected


@pytest.mark.parametrize("fault", ["failed", "gap", "boundary", "target"])
async def test_mcp_uncertain_target_coverage_is_not_newborn_usage(fault):
    health = healthy()
    if fault == "failed":
        health["values"][20][1] = "0"
    elif fault == "gap":
        del health["values"][20]
    elif fault == "boundary":
        del health["values"][0]
    else:
        health["metric"]["instance"] = "unrelated"
    with pytest.raises(SourceError):
        await collect_mcp([counter([(600, 8), (630, 8)])], [0], health=[health])


@pytest.mark.parametrize(
    "body",
    [
        {
            "status": "success",
            "warnings": ["partial response"],
            "data": {"resultType": "vector", "result": []},
        },
        {"status": "success", "data": {"resultType": "vector", "result": []}},
        {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [{"metric": {}, "value": [END.timestamp(), "NaN"]}],
            },
        },
    ],
)
async def test_mcp_missing_scrapes_or_partial_results_are_not_empty_usage(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as client:
        with pytest.raises(SourceError):
            await McpSource(client, "http://prometheus", "up", 30).collect(START, END)


async def test_mcp_existing_sparse_series_does_not_overwrite_a_valid_bucket():
    with pytest.raises(SourceError):
        await collect_mcp([counter([(0, 8), (30, 9)], until=30)], [None])


async def test_mcp_boundary_birth_counts_once_and_next_hour_uses_it_as_baseline():
    born = counter([(3600, 8)])
    rows = await collect_mcp([born], [None])
    assert rows[0].requests == 8
    assert await collect_mcp([born], [None]) == rows
    following = counter([(3600, 8)], until=7200)
    health = healthy()
    health["values"] = [[time + 3600, value] for time, value in health["values"]]
    rows = await collect_mcp(
        [following], [0], health=[health], start=END, end=END + timedelta(hours=1)
    )
    assert rows[0].requests == 0


async def test_mcp_boundary_jitter_keeps_the_last_successful_baseline():
    health = healthy()
    health["values"] = [
        [START.timestamp() - 59, "0"],
        [START.timestamp() - 30.1, "1"],
        *[[time + 0.1, value] for time, value in health["values"][:-1]],
    ]
    item = counter([(600, 8)])
    item["values"] = [[time + 0.1, value] for time, value in item["values"][:-1]]
    rows = await collect_mcp([item], [0], health=[health])
    assert rows[0].requests == 8


@pytest.mark.parametrize("fault", ["missing", "disappeared", "conflicting_increase"])
async def test_mcp_counter_gaps_and_conflicting_queries_preserve_valid_buckets(fault):
    item = counter([(600, 8)])
    if fault == "missing":
        del item["values"][1]
    elif fault == "disappeared":
        item["values"] = item["values"][:1]
    else:
        item = counter([(0, 8)], until=0)
    with pytest.raises(SourceError):
        await collect_mcp([item], [1])
