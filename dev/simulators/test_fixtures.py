"""Guard the local usage simulator against Studio analytics contract drift."""

from datetime import UTC, datetime, timedelta

import pytest

from fixtures import usage_summary


COMPLETENESS = [
    {"field": "attributes", "key": "neurwerk.token_usage_known"},
    {"field": "attributes", "key": "neurwerk.cost_known"},
]


@pytest.mark.parametrize(
    "primary,group_field",
    [
        ([], None),
        ([{"field": "requestModel"}], "requestModel"),
        ([{"field": "attributes", "key": "agentgateway.user"}], "agentgateway.user"),
    ],
)
def test_usage_summary_supports_studio_completeness_groups(primary, group_field):
    start = datetime.now(UTC) - timedelta(days=28)
    payload = {
        "timeRange": {"from": start.isoformat(), "to": datetime.now(UTC).isoformat()},
        "groupBy": primary,
    }
    baseline = usage_summary(payload)
    complete = usage_summary({**payload, "groupBy": primary + COMPLETENESS})
    assert sum(row["requests"] for row in complete["groups"]) == sum(
        row["requests"] for row in baseline["groups"]
    )
    for row in [*complete["groups"], *complete["buckets"]]:
        assert row["group"]["neurwerk.token_usage_known"] is True
        assert row["group"]["neurwerk.cost_known"] is True
        if group_field:
            assert group_field in row["group"]


@pytest.mark.parametrize(
    "suffix",
    [COMPLETENESS[::-1], COMPLETENESS[:1], COMPLETENESS + [{"field": "requestModel"}]],
)
def test_usage_summary_rejects_other_groupings(suffix):
    start = datetime.now(UTC) - timedelta(days=1)
    with pytest.raises(ValueError, match="unsupported grouping"):
        usage_summary(
            {
                "timeRange": {
                    "from": start.isoformat(),
                    "to": datetime.now(UTC).isoformat(),
                },
                "groupBy": suffix,
            }
        )
