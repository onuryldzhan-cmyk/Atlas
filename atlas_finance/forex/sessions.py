"""The weekly forex session: open Sunday 17:00 New York time, closed Friday 17:00 New York time.

New York time follows US daylight saving: EDT (UTC-4) from the second Sunday of March 02:00 local to the first Sunday
of November 02:00 local, EST (UTC-5) otherwise. The rule is computed here, with no time-zone database, so it behaves
the same on Windows (where Python ships no tz data) and Linux.

This is a guard, not the authority: brokers' hours differ by a few minutes and holidays (Christmas, New Year) are not
modelled. The broker's own quotes decide whether a price is fresh.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_OPEN_HOUR = 17  # New York local time, Sunday open and Friday close


def _nth_sunday(year: int, month: int, n: int) -> datetime:
    first = datetime(year, month, 1, tzinfo=UTC)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def new_york_utc_offset_hours(moment: datetime) -> int:
    """-4 during US daylight saving, -5 otherwise (``moment`` must be timezone-aware)."""
    if moment.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
    at = moment.astimezone(UTC)
    dst_start = _nth_sunday(at.year, 3, 2) + timedelta(hours=2 + 5)    # 02:00 EST = 07:00 UTC
    dst_end = _nth_sunday(at.year, 11, 1) + timedelta(hours=2 + 4)     # 02:00 EDT = 06:00 UTC
    return -4 if dst_start <= at < dst_end else -5


def is_forex_market_open(moment: datetime) -> bool:
    """True from Sunday 17:00 to Friday 17:00 New York time."""
    local = moment.astimezone(UTC) + timedelta(hours=new_york_utc_offset_hours(moment))
    weekday, hour = local.weekday(), local.hour      # Monday = 0 ... Sunday = 6
    if weekday == 5:
        return False
    if weekday == 4:
        return hour < _OPEN_HOUR
    if weekday == 6:
        return hour >= _OPEN_HOUR
    return True


def next_forex_open(moment: datetime) -> datetime:
    """``moment`` itself when the market is open, else the next Sunday 17:00 New York time (in UTC)."""
    if is_forex_market_open(moment):
        return moment.astimezone(UTC)
    at = moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    for _ in range(24 * 8):
        at += timedelta(hours=1)
        if is_forex_market_open(at):
            return at
    raise RuntimeError("no forex open within eight days")  # unreachable for the weekly rule
