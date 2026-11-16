from datetime import UTC, datetime
from decimal import Decimal

import pytest
from studio_collector.models import Dimensions, UsageRow

from k8s_stack_studio.lib.usage import source_breakdown
from k8s_stack_studio.models.usage import Coverage


def test_app_key_and_person_views_conserve_measures_and_evidence():
    instant = datetime(2026, 11, 16, tzinfo=UTC)
    rows = [
        UsageRow(
            dimensions=Dimensions(principal_id="self", app_id="studio", credential_id="key"),
            requests=Decimal(2),
            tokens_known=Decimal(2),
            cost_known=Decimal(2),
        ),
        UsageRow(
            dimensions=Dimensions(principal_id="self", app_id="editor", credential_id="key"),
            requests=Decimal(1),
            total_tokens=7,
            tokens_known=Decimal(1),
        ),
        UsageRow(
            dimensions=Dimensions(principal_id="self", credential_id="second"),
            requests=Decimal(1),
            total_tokens=3,
            cost_usd=Decimal("0.25"),
        ),
        UsageRow(dimensions=Dimensions(principal_id="other"), requests=Decimal(1)),
        UsageRow(dimensions=Dimensions(), requests=Decimal(1)),
    ]
    result = source_breakdown(
        [(instant, r) for r in rows],
        "llm",
        Coverage(complete=True),
        "UTC",
        instant.date(),
        instant.date(),
    )
    people = {p.user_id: p for p in result.people}
    assert set(people) == {"self", "other", None}
    for dimension in ("apps", "credentials"):
        for metric in ("requests", "total_tokens", "cost_usd"):
            assert sum(getattr(row, metric) for row in getattr(result, dimension)) == pytest.approx(
                sum(getattr(person.total, metric) for person in people.values())
            )
            for person in people.values():
                assert sum(
                    getattr(row, metric) for row in getattr(person, dimension)
                ) == pytest.approx(getattr(person.total, metric))
    own = people["self"].total
    assert own.requests == 4 and own.total_tokens == 10
    assert own.accounting.tokens.state == "partial"
    assert own.accounting.cost_usd.known_records == 2
    assert own.accounting.cost_usd.complete_total is None
    assert people[None].total.requests == 1
