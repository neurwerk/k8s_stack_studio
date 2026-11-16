"""Calendar boundaries shared by collection and reporting."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from studio_collector.models import InvalidUsageRangeError


def midnight(day: date, timezone: ZoneInfo) -> datetime:
    """Return the UTC instant of a local calendar boundary."""
    return datetime.combine(day, time.min, timezone).astimezone(UTC)


def hours(
    start: datetime, end: datetime, timezone: ZoneInfo
) -> Iterator[tuple[datetime, datetime]]:
    """Partition local days into at-most-hourly buckets, including short DST hours."""
    day = start.astimezone(timezone).date()
    while midnight(day, timezone) < end:
        boundary = midnight(day + timedelta(days=1), timezone)
        current = midnight(day, timezone)
        while current < boundary:
            until = min(current + timedelta(hours=1), boundary)
            if until > start and current < end:
                yield current, until
            current = until
        day += timedelta(days=1)


def date_range(
    start: date | None, end: date | None, now: datetime, timezone: ZoneInfo
) -> tuple[date, date]:
    """Bound reports to ten years; older missing periods remain missing."""
    today = now.astimezone(timezone).date()
    end = end or today
    start = start or end - timedelta(days=min(29, end.toordinal() - 1))
    if start > end or end > today or (end - start).days >= 3660:
        raise InvalidUsageRangeError
    return start, end


def periods(
    now: datetime, timezone: ZoneInfo, activation: datetime
) -> dict[str, tuple[datetime, datetime]]:
    """Preserve Studio's calendar and rolling period names."""
    local = now.astimezone(timezone)
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    return {
        "total": (activation, now),
        "this_month": (month, now),
        "last_month": ((month - timedelta(days=1)).replace(day=1), month),
        "last_30_days": (now - timedelta(days=30), now),
        "this_week": (week, now),
        "last_week": (week - timedelta(days=7), week),
        "last_7_days": (now - timedelta(days=7), now),
        "today": (today, now),
        "last_24_hours": (now - timedelta(hours=24), now),
    }
