from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from studio_collector.models import ATTRIBUTES, SourceError
from studio_collector.sources import LlmSource

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
