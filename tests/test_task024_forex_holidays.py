"""Task 024 (registry v5.107): Christmas and New Year close the forex market.

Owner decision 2026-10-27 'Önce tatil takvimi' (review finding T023-F3): Friday 25 December 2026 and Friday 1 January
2027 must not be traded as normal Fridays. A trading day D runs from 17:00 New York time on D-1 to 17:00 on D, so a
holiday closes that whole session; a Friday holiday moves the weekly close, the pre-close entry block and the
weekend close-out to Thursday 17:00."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from atlas_finance.forex.sessions import (
    HOLIDAYS,
    PRE_CLOSE_MINUTES,
    WEEKEND_CLOSE_MINUTES,
    is_forex_market_open,
    is_forex_pre_close,
    next_forex_open,
)
from core.exit_guard import EXIT_NOT_TRIGGERED, EXIT_TRIGGERED
from tests.test_task023_policy_manifest_v3 import fresh, guard_at


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_the_holidays_are_christmas_and_new_year_only():
    assert HOLIDAYS == ((12, 25), (1, 1))


@pytest.mark.parametrize("moment, is_open", [
    ("2026-12-24T21:59:59", True), ("2026-12-24T22:00:00", False),     # Thu 24 Dec 17:00 EST: Christmas session
    ("2026-12-25T15:00:00", False), ("2026-12-26T12:00:00", False),    # Christmas Day, Saturday
    ("2026-12-27T21:59:59", False), ("2026-12-27T22:00:00", True),     # Sunday open as usual
    ("2026-12-31T21:59:59", True), ("2026-12-31T22:00:00", False),     # Thu 31 Dec 17:00 EST: New Year session
    ("2027-01-01T15:00:00", False), ("2027-01-03T22:00:00", True),
    ("2025-12-24T21:59:59", True), ("2025-12-24T22:00:00", False),     # Thursday holiday: closed Wed 17:00 ...
    ("2025-12-25T21:59:59", False), ("2025-12-25T22:00:00", True),     # ... to Thu 17:00, then open again
    ("2028-12-24T22:00:00", False), ("2028-12-25T22:00:00", True),     # Monday holiday: Sunday open moves to Mon 17:00
    ("2027-12-24T15:00:00", True), ("2027-12-24T21:59:59", True),      # Saturday holiday: Friday is a normal Friday
    ("2026-12-23T15:00:00", True), ("2026-01-02T15:00:00", True),      # the days around are untouched
    ("2022-12-25T21:59:59", False), ("2022-12-25T22:00:00", True),     # Sunday holiday: Sunday open unchanged
    ("2022-12-31T21:59:59", False), ("2023-01-01T22:00:00", True),
])
def test_a_holiday_closes_its_whole_trading_day(moment, is_open):
    assert is_forex_market_open(at(moment)) is is_open


@pytest.mark.parametrize("moment, expected", [
    ("2026-12-24T22:00:00", "2026-12-27T22:00:00"), ("2026-12-25T10:00:00", "2026-12-27T22:00:00"),
    ("2026-12-31T23:00:00", "2027-01-03T22:00:00"), ("2025-12-25T03:00:00", "2025-12-25T22:00:00"),
    ("2028-12-24T22:00:00", "2028-12-25T22:00:00"),
])
def test_the_next_open_skips_the_holiday(moment, expected):
    assert next_forex_open(at(moment)) == at(expected)


@pytest.mark.parametrize("moment, minutes, in_window", [
    ("2026-12-24T20:59:59", PRE_CLOSE_MINUTES, False), ("2026-12-24T21:00:00", PRE_CLOSE_MINUTES, True),
    ("2026-12-24T21:29:59", WEEKEND_CLOSE_MINUTES, False), ("2026-12-24T21:30:00", WEEKEND_CLOSE_MINUTES, True),
    ("2026-12-31T21:30:00", WEEKEND_CLOSE_MINUTES, True), ("2026-12-24T22:00:00", WEEKEND_CLOSE_MINUTES, False),
    ("2025-12-24T21:30:00", WEEKEND_CLOSE_MINUTES, True),              # a weekday holiday is a closure too
    ("2026-12-31T20:59:59", PRE_CLOSE_MINUTES, False), ("2026-12-31T21:00:00", PRE_CLOSE_MINUTES, True),
])
def test_the_window_before_a_holiday_close(moment, minutes, in_window):
    assert is_forex_pre_close(at(moment), minutes) is in_window


@pytest.mark.parametrize("moment, triggered", [
    ("2026-12-24T21:29:59", False), ("2026-12-24T21:30:00", True),     # Christmas eve, Thursday
    ("2026-12-31T21:45:00", True), ("2026-12-23T21:45:00", False),
])
def test_open_positions_are_closed_before_the_holiday_not_carried_through_it(moment, triggered):
    guard, manager = guard_at(moment)
    outcome = guard.run_once(fresh(moment))[0]
    assert outcome["state"] == (EXIT_TRIGGERED if triggered else EXIT_NOT_TRIGGERED)
    assert (len(manager.calls) == 1) is triggered
    if triggered:
        assert manager.calls[0]["action"] == "SELL" and manager.calls[0]["reduce_only"] is True


def test_a_normal_friday_is_unchanged():
    assert is_forex_market_open(at("2026-10-30T20:59:59")) and not is_forex_market_open(at("2026-10-30T21:00:00"))
    assert is_forex_pre_close(at("2026-10-30T20:30:00"), WEEKEND_CLOSE_MINUTES)
    assert not is_forex_pre_close(at("2026-10-29T20:30:00"), WEEKEND_CLOSE_MINUTES)


def test_any_timezone_aware_input_gives_the_same_answer():
    eve = at("2026-12-24T22:00:00").astimezone(timezone(timedelta(hours=-5)))     # Thu 24 Dec 17:00 in New York
    assert eve.hour == 17 and not is_forex_market_open(eve)
    before = at("2026-12-24T21:30:00").astimezone(timezone(timedelta(hours=9)))
    assert is_forex_market_open(before) and is_forex_pre_close(before, WEEKEND_CLOSE_MINUTES)


def test_the_forex_application_s_loop_gates_see_the_holiday(tmp_path):
    from core.application import AtlasApplication
    from tests.test_block5c_upstream_sizing_authority import seed_state
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"), market="FOREX")
    try:
        assert app.market_loop.market_session_open(at("2026-12-25T15:00:00")) is False
        assert app.market_loop.market_entry_blocked(at("2026-12-24T21:15:00")) is True
        rule = app.market_loop.exit_guard_runner.guard.rules[0]
        assert rule.in_window(at("2026-12-24T21:45:00"), rule.minutes) is True
    finally:
        app.stop()
