from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest

from studio_collector.calendar import date_range, hours, midnight
from studio_collector.models import Dimensions, InvalidUsageRangeError, UsageRow
from studio_collector.pricing import Account, Catalogue, Price, billing_period, monthly_cost

START = datetime(2026, 11, 1, tzinfo=UTC)


def catalogue():
    return Catalogue(
        accounts=[
            Account(
                server="search",
                billing_account="search-account",
                prices=[
                    Price(
                        effective_from=START,
                        default=Decimal(5),
                        tools={
                            "free": Decimal(0),
                            "unknown": None,
                            "premium": Decimal(10),
                        },
                    ),
                    Price(effective_from=START + timedelta(days=1), default=Decimal(20)),
                ],
            )
        ]
    )


@pytest.mark.parametrize(
    "server,tool,rate",
    [
        ("search", "new-tool", 5),
        ("search", "premium", 10),
        ("search", "free", 0),
        ("search", "unknown", None),
        ("other", "free", None),
    ],
)
def test_tool_default_explicit_unknown_and_free(server, tool, rate):
    row = catalogue().apply(
        UsageRow(
            dimensions=Dimensions(server=server, tool=tool),
            requests=Decimal("10.5"),
        ),
        START,
    )
    assert row.rate == rate
    assert row.cost_usd == (Decimal("10.5") * rate / 1000 if rate is not None else 0)
    assert row.cost_known == (Decimal("10.5") if rate is not None else 0)


def test_prices_use_usage_instant_not_collection_instant():
    row = UsageRow(dimensions=Dimensions(server="search", tool="new"), requests=Decimal(1000))
    assert catalogue().apply(row, START).cost_usd == 5
    assert catalogue().apply(row, START + timedelta(days=1)).cost_usd == 20


@pytest.mark.parametrize(
    "calls,expected", [(0, 10), (1500, 10), (2000, 10), (2500, Decimal("12.5"))]
)
def test_once_per_account_allowance(calls, expected):
    price = Price(
        effective_from=START,
        default=Decimal(5),
        monthly_fee=Decimal(10),
        included_calls=Decimal(2000),
    )
    assert monthly_cost(price, Decimal(calls), Decimal(calls) * 5 / 1000) == expected


def test_credit_cannot_make_usage_negative_and_month_rollover():
    price = Price(effective_from=START, monthly_credit=Decimal(5))
    assert monthly_cost(price, Decimal(100), Decimal("0.5")) == 0
    account = Account(server="search", billing_account="shared", billing_day=15, prices=[price])
    assert billing_period(account, date(2027, 1, 2)) == (
        datetime(2026, 12, 15, tzinfo=UTC),
        datetime(2027, 1, 15, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "zone,day,seconds,buckets",
    [
        ("Europe/Berlin", date(2026, 3, 29), 23 * 3600, 23),
        ("Europe/Berlin", date(2026, 10, 25), 25 * 3600, 25),
        ("Asia/Kathmandu", date(2026, 11, 1), 24 * 3600, 24),
        ("Australia/Lord_Howe", date(2026, 10, 4), 84600, 24),
    ],
)
def test_calendar_partitions_dst_and_fractional_offsets(zone, day, seconds, buckets):
    tz = ZoneInfo(zone)
    a, b = midnight(day, tz), midnight(day + timedelta(days=1), tz)
    spans = list(hours(a, b, tz))
    assert len(spans) == buckets
    assert sum((end - start).total_seconds() for start, end in spans) == seconds
    assert all(first[1] == second[0] for first, second in pairwise(spans))


def test_long_reports_and_invalid_calendar_ranges():
    assert date_range(date(2020, 1, 1), date(2026, 1, 1), START, ZoneInfo("UTC"))[0].year == 2020
    with pytest.raises(InvalidUsageRangeError):
        date_range(date(2027, 1, 1), None, START, ZoneInfo("UTC"))
