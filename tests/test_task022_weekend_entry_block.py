"""Task 022 (registry v5.105): no new forex risk in the last hour before the Friday 17:00 New York close.

Owner decision 2026-10-26 'Cuma kapat'. This task delivers the entry block; closing open positions before the
weekend needs the exit guard in ENFORCE with a time rule, which the policy manifest pins (OBSERVE, no rules), so it
is part of the manifest v3 package for owner approval."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atlas_finance.forex.sessions import PRE_CLOSE_MINUTES, is_forex_market_open, is_forex_pre_close
from core.application import AtlasApplication
from core.market_loop import MarketLoop
from tests.intelligence.test_task009_regime_tracking import T0, Brain, Execution, Feed
from tests.test_block5c_upstream_sizing_authority import seed_state


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize("moment, in_window", [
    ("2026-10-30T19:59:59", False), ("2026-10-30T20:00:00", True),     # EDT: close 21:00 UTC
    ("2026-10-30T20:59:59", True), ("2026-10-30T21:00:00", False),     # closed is not "pre-close"
    ("2026-11-13T20:59:59", False), ("2026-11-13T21:00:00", True),     # EST: close 22:00 UTC
    ("2026-11-13T21:59:59", True), ("2026-10-29T20:30:00", False),     # Thursday
    ("2026-10-31T12:00:00", False), ("2026-11-01T21:30:00", False),    # Saturday; Sunday after the open
])
def test_the_pre_close_window_is_the_last_hour_of_the_forex_week(moment, in_window):
    assert PRE_CLOSE_MINUTES == 60
    assert is_forex_pre_close(at(moment)) is in_window
    if in_window:
        assert is_forex_market_open(at(moment))


def loop_with(blocked, session=None):
    loop = MarketLoop(brain=Brain(), market_feed=Feed(), execution=Execution(), symbols=["EURUSD"])
    loop._sell_symbol_known_flat = lambda symbol: False
    loop.market_entry_blocked = blocked
    loop.market_session_open = session
    return loop


def gate(loop, action):
    cutoff = datetime.fromtimestamp(T0 / 1000, UTC)
    return loop._symbol_execution_gate("EURUSD", {"action": action, "symbol": "EURUSD", "metadata": {}},
                                       [{"open_time": T0 - 60_000, "close_time": T0 - 1}], cutoff)


@pytest.mark.parametrize("blocked", [lambda now: True, lambda now: None, lambda now: "no", lambda now: 1 / 0])
def test_no_buy_in_the_window_or_when_the_check_is_unsure(blocked):
    loop = loop_with(blocked)
    result = gate(loop, "BUY")
    assert result["status"] == "SKIPPED" and result["reason"] == "PRE_CLOSE_NO_NEW_RISK"
    assert loop.metrics["buy_pre_close_skipped"] == 1 and loop.execution.calls == 0


def test_a_sell_is_never_held_back_by_the_window():
    result = gate(loop_with(lambda now: True), "SELL")
    assert not (isinstance(result, dict) and result.get("reason") == "PRE_CLOSE_NO_NEW_RISK")


def test_outside_the_window_or_without_a_check_the_gate_is_unchanged():
    for blocked in (None, lambda now: False):
        result = gate(loop_with(blocked), "BUY")
        assert not (isinstance(result, dict) and result.get("reason") == "PRE_CLOSE_NO_NEW_RISK")
    assert "buy_pre_close_skipped" not in loop_with(None).metrics


def test_a_closed_market_is_reported_as_closed_not_as_pre_close():
    result = gate(loop_with(lambda now: True, session=lambda now: False), "BUY")
    assert result["reason"] == "MARKET_CLOSED"


def test_the_check_reads_the_cycle_cutoff():
    seen = []
    gate(loop_with(lambda now: seen.append(now) or False), "BUY")
    assert seen == [datetime.fromtimestamp(T0 / 1000, UTC)]


@pytest.mark.parametrize("market, wired", [("FOREX", True), ("CRYPTO", False)])
def test_only_forex_has_the_window(tmp_path, market, wired):
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"), market=market)
    try:
        assert (app.market_loop.market_entry_blocked is is_forex_pre_close) is wired
        assert (app.market_loop.market_entry_blocked is None) is (not wired)
    finally:
        app.stop()
