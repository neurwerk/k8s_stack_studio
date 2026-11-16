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


async def test_mcp_increase_before_sum_and_fractional_counts():
    queries = []

    def handler(request):
        expression = request.url.params["query"]
        queries.append(expression)
        if "min_over_time" in expression:
            result = [{"metric": {"instance": "one"}, "value": [END.timestamp(), "1"]}]
        elif "count_over_time(up" in expression:
            result = [{"metric": {"instance": "one"}, "value": [END.timestamp(), "120"]}]
        elif "< 2" in expression:
            result = []
        else:
            assert "sum by (" in expression and "(increase(" in expression
            assert 'method="tools/call"' in expression and 'listener="api-bindings"' in expression
            assert "request_id" not in expression
            result = [
                {
                    "metric": {
                        "studio_principal_id": "person",
                        "server": "search",
                        "resource": "lookup",
                    },
                    "value": [END.timestamp(), "2.125"],
                }
            ]
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": result,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await McpSource(client, "http://prometheus", 'up{job="gateway"}', 30).collect(
            START, END
        )
    assert rows[0].requests == Decimal("2.125")
    assert rows[0].dimensions.principal_id == "person"
    assert rows[0].tokens_known == rows[0].cost_known == 0
    assert any("count_over_time(agentgateway_mcp_requests_total" in q for q in queries)


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


async def test_mcp_sparse_series_does_not_overwrite_a_valid_bucket():
    def handler(request):
        query = request.url.params["query"]
        value = "120" if query.startswith("count_over_time(up") else "1"
        assert not query.startswith("sum by")
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [END.timestamp(), value]}],
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError):
            await McpSource(client, "http://prometheus", "up", 30).collect(START, END)
