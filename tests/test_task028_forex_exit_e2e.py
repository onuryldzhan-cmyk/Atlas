"""Task 028 (registry v5.111): the forex exits end to end, the pending-price alert, and a forex-safe report price.

Owner 2026-11-11 'Hepsini düzelt (Önerilen)' and 'Her adımı profesyonel bitir'.
- T023-F6: the weekend close-out and the stop-out run through the real FOREX application - its own runner, exit
  guard, ExecutionManager and margin book - for a long and a short.
- T023-F4: a position the guard cannot price raises an alert after 3 cycles in a row, or at once inside the
  close-out window. Observability only: positions are held, never sold at a guessed price.
- tools/paper_position_report never asks the crypto ticker for a forex pair."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

import core.application as application_module
from atlas_finance.market_data.mt5_provider import Mt5MarketDataProvider
from core.application import AtlasApplication
from core.exit_guard import EXIT_NOT_TRIGGERED, EXIT_PENDING_PRICE, EXIT_TRIGGERED
from tests.test_block5c_upstream_sizing_authority import seed_state
from tests.test_task018_forex_foundation import NOW, FakeMt5
from tools.refresh_mt5_instrument_rules import refresh_mt5_instrument_rules

FRIDAY_IN_WINDOW = datetime(2026, 10, 30, 20, 45, tzinfo=UTC)        # 15 minutes before the 17:00 EDT close
WEDNESDAY = datetime(2026, 10, 28, 15, 0, tzinfo=UTC)


class Bus:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


@pytest.fixture
def forex_app(tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)
    rules = tmp_path / "instrument_rules_mt5.json"
    refresh_mt5_instrument_rules(destination=rules, now=datetime.now(UTC),
                                 provider=Mt5MarketDataProvider(mt5_module=FakeMt5(), clock=lambda: NOW))
    monkeypatch.setattr(application_module, "FOREX_INSTRUMENT_RULES_PATH", rules)
    app = AtlasApplication(state_directory=seed_state(tmp_path / "forex" / "state", leverage=2), market="FOREX")
    app.execution.start()
    app.market_loop.event_bus = Bus()
    yield app
    app.stop()


def decision(symbol, action, request_id, *, price, proposed="2000"):
    return {"symbol": symbol, "action": action, "price": price, "amount": 0, "confidence": 80, "risk": "HIGH",
            "request_id": request_id, "strategy": "T", "proposed_quote_allocation": proposed}


def open_long_and_short(app):
    assert app.execution.execute(decision("EURUSD", "BUY", "l-1", price=1.08))["status"] == "PAPER_EXECUTED"
    assert app.execution.execute(decision("GBPUSD", "SELL", "s-1", price=1.30))["status"] == "PAPER_EXECUTED"
    positions = app.portfolio_foundation.snapshot()["positions"]
    assert "side" not in positions["EURUSD"] and positions["GBPUSD"]["side"] == "SHORT"


def candles_at(app, moment, prices):
    open_ms = int((moment - timedelta(seconds=30)).timestamp() * 1000)
    app.market_loop.recent_candles = {s: ((open_ms, p, p, p, p),) for s, p in prices.items()}


def run_at(app, moment):
    app.exit_guard.clock = lambda: moment.timestamp()
    return {o["symbol"]: o for o in app.market_loop.exit_guard_runner(moment)}


def alerts(app):
    return [e["payload"] for e in app.market_loop.event_bus.events if e["event"] == "EXIT_GUARD_PRICE_UNAVAILABLE"]


# ---------------------------------------------------------------- T023-F6: end to end


def test_the_weekend_close_out_closes_a_long_and_a_short_through_the_real_application(forex_app):
    open_long_and_short(forex_app)
    candles_at(forex_app, FRIDAY_IN_WINDOW, {"EURUSD": 1.081, "GBPUSD": 1.299})
    outcomes = run_at(forex_app, FRIDAY_IN_WINDOW)
    assert {s: o["state"] for s, o in outcomes.items()} == {"EURUSD": EXIT_TRIGGERED, "GBPUSD": EXIT_TRIGGERED}
    assert {s: o["rule_id"] for s, o in outcomes.items()} == {"EURUSD": "forex-weekend-close",
                                                             "GBPUSD": "forex-weekend-close"}
    assert all(o["execution_status"] == "PAPER_EXECUTED" for o in outcomes.values()), outcomes
    snap = forex_app.portfolio_foundation.snapshot()
    assert snap["positions"] == {} and snap["used_margin"] == 0
    # the next cycle finds the book empty, so there is nothing left to close
    assert run_at(forex_app, FRIDAY_IN_WINDOW) == {}


def test_a_replayed_exit_request_never_closes_twice(forex_app, monkeypatch):
    # review T028-F2: the guard's request ids make a repeated exit a duplicate in ExecutionManager
    open_long_and_short(forex_app)
    submitted = []
    real_execute = forex_app.execution.execute
    monkeypatch.setattr(forex_app.execution, "execute",
                        lambda decision_, state=None: (submitted.append(dict(decision_)), real_execute(decision_, state))[1])
    candles_at(forex_app, FRIDAY_IN_WINDOW, {"EURUSD": 1.081, "GBPUSD": 1.299})
    run_at(forex_app, FRIDAY_IN_WINDOW)
    after = forex_app.portfolio_foundation.snapshot()
    assert len(submitted) == 2 and after["positions"] == {}
    for decision_ in submitted:
        replay = real_execute(dict(decision_), None)
        assert replay.get("duplicate_reason") == "DUPLICATE_REQUEST_COMPLETED", replay
    assert forex_app.portfolio_foundation.snapshot()["cash"] == after["cash"]


def test_an_alert_failure_never_loses_the_exits(forex_app, monkeypatch, caplog):
    # review T028-F1: the exits are submitted before the alert runs, and an alert failure is reported as such
    open_long_and_short(forex_app)
    monkeypatch.setattr(forex_app.market_loop, "_increment_metric", lambda *a, **k: 1 / 0)
    candles_at(forex_app, FRIDAY_IN_WINDOW, {"EURUSD": 1.081})                    # GBPUSD unpriced: alert path
    outcomes = run_at(forex_app, FRIDAY_IN_WINDOW)
    assert outcomes["EURUSD"]["execution_status"] == "PAPER_EXECUTED"
    assert outcomes["GBPUSD"]["state"] == EXIT_PENDING_PRICE
    assert "pending-price alert failed" in caplog.text


def test_outside_the_window_nothing_is_closed(forex_app):
    open_long_and_short(forex_app)
    candles_at(forex_app, WEDNESDAY, {"EURUSD": 1.081, "GBPUSD": 1.299})
    outcomes = run_at(forex_app, WEDNESDAY)
    assert {o["state"] for o in outcomes.values()} == {EXIT_NOT_TRIGGERED}
    assert len(forex_app.portfolio_foundation.snapshot()["positions"]) == 2


def test_the_stop_out_closes_the_book_largest_loss_first(forex_app):
    open_long_and_short(forex_app)
    snap = forex_app.portfolio_foundation.snapshot()
    # book: 1000 EURUSD long at 1.08 and 1000 GBPUSD short at 1.30, used margin 1190, equity 10000. At 0.10 / 9.30
    # the losses are 980 + 8000, so equity is 1020 and the margin level 1020 / 1190 = 0.857, below 100 %.
    # (At 9.00 it would be 1320 / 1190 = 1.109: no stop-out - checked in the next test.)
    candles_at(forex_app, WEDNESDAY, {"EURUSD": 0.10, "GBPUSD": 9.30})
    outcomes = run_at(forex_app, WEDNESDAY)
    assert {o["rule_id"] for o in outcomes.values()} == {"forex-stop-out"}
    assert all(o["state"] == EXIT_TRIGGERED and o["priority"] == "SAFETY_EXIT" for o in outcomes.values())
    losses = {s: D(o["detail"]["loss_quote"]) for s, o in outcomes.items()}
    order = [o["symbol"] for o in forex_app.exit_guard.last_run]
    assert order == sorted(losses, key=lambda s: -losses[s])
    assert snap["used_margin"] > 0 and forex_app.portfolio_foundation.snapshot()["positions"] == {}


def test_just_above_100_percent_there_is_no_stop_out(forex_app):
    open_long_and_short(forex_app)
    candles_at(forex_app, WEDNESDAY, {"EURUSD": 0.10, "GBPUSD": 9.00})            # level 1320 / 1190 = 1.109
    assert {o["state"] for o in run_at(forex_app, WEDNESDAY).values()} == {EXIT_NOT_TRIGGERED}
    assert len(forex_app.portfolio_foundation.snapshot()["positions"]) == 2


# ---------------------------------------------------------------- T023-F4: the pending-price alert


def test_a_pending_price_alerts_after_three_cycles_and_never_sells(forex_app):
    open_long_and_short(forex_app)
    candles_at(forex_app, WEDNESDAY - timedelta(minutes=10), {"EURUSD": 1.08, "GBPUSD": 1.30})   # stale
    for cycle in (1, 2):
        assert {o["state"] for o in run_at(forex_app, WEDNESDAY).values()} == {EXIT_PENDING_PRICE}
        assert alerts(forex_app) == [] and forex_app.market_loop.metrics.get("exit_pending_price_alerts") is None
    run_at(forex_app, WEDNESDAY)
    [alert] = alerts(forex_app)
    assert alert["symbols"] == ["EURUSD", "GBPUSD"] and alert["in_close_out_window"] is False
    assert alert["consecutive_cycles"] == {"EURUSD": 3, "GBPUSD": 3}
    assert forex_app.market_loop.metrics["exit_pending_price_alerts"] == 1
    assert len(forex_app.portfolio_foundation.snapshot()["positions"]) == 2                     # held, not sold


def test_a_fresh_price_resets_the_streak(forex_app):
    open_long_and_short(forex_app)
    for _ in range(2):
        candles_at(forex_app, WEDNESDAY - timedelta(minutes=10), {"EURUSD": 1.08, "GBPUSD": 1.30})
        run_at(forex_app, WEDNESDAY)
    candles_at(forex_app, WEDNESDAY, {"EURUSD": 1.08, "GBPUSD": 1.30})
    run_at(forex_app, WEDNESDAY)
    assert forex_app.market_loop.exit_guard_runner.pending_streaks == {}
    candles_at(forex_app, WEDNESDAY - timedelta(minutes=10), {"EURUSD": 1.08, "GBPUSD": 1.30})
    run_at(forex_app, WEDNESDAY)
    assert alerts(forex_app) == []


def test_inside_the_close_out_window_a_pending_price_alerts_at_once(forex_app):
    open_long_and_short(forex_app)
    candles_at(forex_app, FRIDAY_IN_WINDOW, {"EURUSD": 1.08})                     # GBPUSD has no candle at all
    outcomes = run_at(forex_app, FRIDAY_IN_WINDOW)
    assert outcomes["GBPUSD"]["state"] == EXIT_PENDING_PRICE and outcomes["EURUSD"]["state"] == EXIT_TRIGGERED
    [alert] = alerts(forex_app)
    assert alert["symbols"] == ["GBPUSD"] and alert["in_close_out_window"] is True


def test_an_unsure_window_check_counts_as_inside_the_window(forex_app):
    open_long_and_short(forex_app)
    candles_at(forex_app, WEDNESDAY - timedelta(minutes=10), {"EURUSD": 1.08, "GBPUSD": 1.30})
    forex_app.exit_guard.clock = lambda: WEDNESDAY.timestamp()
    with pytest.raises(ValueError):                                     # the real window check refuses naive time
        __import__("atlas_finance.forex.sessions", fromlist=["x"]).is_forex_pre_close(WEDNESDAY.replace(tzinfo=None))
    forex_app.market_loop.exit_guard_runner(WEDNESDAY.replace(tzinfo=None))
    assert alerts(forex_app)[0]["in_close_out_window"] is True


def test_crypto_has_no_runner_and_no_alert(tmp_path):
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"))
    try:
        assert app.market_loop.exit_guard_runner is None
    finally:
        app.stop()


# ---------------------------------------------------------------- the report's live price


def test_the_report_never_asks_the_crypto_ticker_in_forex(monkeypatch):
    import tools.paper_position_report as report

    asked = []
    monkeypatch.setattr(report.urllib.request, "urlopen", lambda *a, **k: asked.append(a) or (_ for _ in ()).throw(
        OSError("offline")))
    monkeypatch.setenv("ATLAS_MARKET", "FOREX")
    assert report.live_price("EURUSD") is None and asked == []
    monkeypatch.setenv("ATLAS_MARKET", "CRYPTO")
    assert report.live_price("BTCUSDT") is None and len(asked) == 1          # crypto still asks (offline here)
