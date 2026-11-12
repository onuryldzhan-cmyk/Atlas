"""Task 029 (registry v5.112): the findings of the 2026-11-12 review of the forex branch, fixed.

Owner 2026-11-12 'Kodları gözden geçir stratejileri karşılaştır ve kalan adımları tamamla'.
- R-1: with negative cash in the margin book, every remaining exit failed in finalization and the runtime halted
  with the positions open. A reservation that does not grow is now accepted, so exits settle.
- R-2: ExecutionManager remembers a clean refusal under the request id, so one transient refusal (a stale quote in
  the BOOK fill model) disabled that position's exit for ever. The guard now retries a REJECTED exit under a new id
  each minute; an indeterminate answer is never retried.
- R-3: the pending-price alert repeats once an hour outside the close-out window, not every cycle."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal as D

import pytest

from core.execution_portfolio_foundation import (
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
)
from core.exit_guard import ENFORCE, EXIT_PENDING_PRICE, EXIT_TRIGGERED, RULE_MAX_LOSS_PCT, ExitGuard, ExitRule, Mark
from tests.test_task028_forex_exit_e2e import (  # noqa: F401  (forex_app is a fixture)
    FRIDAY_IN_WINDOW,
    WEDNESDAY,
    alerts,
    candles_at,
    forex_app,
    open_long_and_short,
    run_at,
)


def events(app, name):
    return [e["payload"] for e in app.market_loop.event_bus.events if e["event"] == name]


def force_cash(app, value):
    """Leave the book as a blow-out close would: negative cash (a direct state edit, for the test only)."""
    foundation = app.portfolio_foundation
    payload = json.loads(foundation.store.path.read_text(encoding="utf-8"))
    payload["cash"] = value
    foundation.store.save(payload)
    foundation._state = payload


# ---------------------------------------------------------------- R-1: negative cash never traps an exit


def test_with_negative_cash_the_remaining_positions_still_close(forex_app):
    open_long_and_short(forex_app)
    force_cash(forex_app, "-500")
    candles_at(forex_app, FRIDAY_IN_WINDOW, {"EURUSD": 1.081, "GBPUSD": 1.299})
    outcomes = run_at(forex_app, FRIDAY_IN_WINDOW)
    assert {o["execution_status"] for o in outcomes.values()} == {"PAPER_EXECUTED"}, outcomes
    snap = forex_app.portfolio_foundation.snapshot()
    assert snap["positions"] == {} and snap["used_margin"] == 0
    assert forex_app.execution.execution_halted is False


def test_with_negative_cash_new_risk_is_still_refused(forex_app):
    force_cash(forex_app, "-500")
    result = forex_app.execution.execute({"symbol": "EURUSD", "action": "BUY", "price": 1.08, "amount": 0,
                                          "confidence": 80, "risk": "HIGH", "request_id": "n-1", "strategy": "T",
                                          "proposed_quote_allocation": "2000"})
    assert result["status"] == "REJECTED" and result["reason"] == "INSUFFICIENT_DURABLE_CAPITAL"
    assert forex_app.portfolio_foundation.snapshot()["positions"] == {}


def book(tmp_path, leverage):
    store = FinancialStateStore(tmp_path / f"b{leverage}.json")
    store.initialize(D("1000"), leverage=leverage)
    return ExecutionPortfolioFoundation(
        store, applied_archive=AppliedExecutionArchiveStore(tmp_path / f"b{leverage}-a.jsonl"),
        closed_archive=ClosedPositionArchiveStore(tmp_path / f"b{leverage}-c.jsonl"), leverage=leverage)


def test_a_growing_reservation_is_never_accepted_beyond_cash(tmp_path):
    margin = book(tmp_path, 2)
    margin.set_reserved_capital(D("400"))
    payload = json.loads(margin.store.path.read_text(encoding="utf-8"))
    payload["cash"] = "-50"
    margin.store.save(payload)
    margin._state = payload
    margin.set_reserved_capital(D("400"))                       # unchanged: accepted, so an exit can settle
    margin.set_reserved_capital(D("0"))                         # shrinking: accepted
    with pytest.raises(ValueError, match="NEGATIVE_AVAILABLE_CAPITAL"):
        margin.set_reserved_capital(D("1"))                     # growing: refused
    cash = book(tmp_path, 1)
    with pytest.raises(ValueError, match="NEGATIVE_AVAILABLE_CAPITAL"):
        cash.set_reserved_capital(D("1001"))                    # the cash book is unchanged
    cash.set_reserved_capital(D("400"))
    payload = json.loads(cash.store.path.read_text(encoding="utf-8"))
    payload["cash"] = "300"
    cash.store.save(payload)
    cash._state = payload
    with pytest.raises(ValueError, match="NEGATIVE_AVAILABLE_CAPITAL"):
        cash.set_reserved_capital(D("400"))                     # ... even for a reservation that does not grow


# ---------------------------------------------------------------- R-2: a rejected exit is retried


def test_a_transiently_rejected_exit_is_retried_and_closes(forex_app):
    open_long_and_short(forex_app)
    manager = forex_app.execution
    healthy = manager.audit_persistence_state
    manager.audit_persistence_state = lambda: "RECOVERY_REQUIRED"          # a transient refusal of every exit
    candles_at(forex_app, FRIDAY_IN_WINDOW, {"EURUSD": 1.081, "GBPUSD": 1.299})
    first = run_at(forex_app, FRIDAY_IN_WINDOW)
    assert {o["execution_status"] for o in first.values()} == {"REJECTED"}
    assert forex_app.exit_guard.stats["rejected"] == 2
    [alert] = events(forex_app, "EXIT_GUARD_EXIT_NOT_EXECUTED")
    assert alert["symbols"] == {"EURUSD": "REJECTED", "GBPUSD": "REJECTED"}
    assert forex_app.market_loop.metrics["exit_not_executed_alerts"] == 1

    manager.audit_persistence_state = healthy
    later = FRIDAY_IN_WINDOW + timedelta(minutes=1)
    candles_at(forex_app, later, {"EURUSD": 1.081, "GBPUSD": 1.299})
    second = run_at(forex_app, later)
    assert {o["execution_status"] for o in second.values()} == {"PAPER_EXECUTED"}, second
    assert all(":retry:" in o["request_id"] for o in second.values())
    assert {s: first[s]["request_id"] for s in first} == {s: o["request_id"].split(":retry:")[0]
                                                         for s, o in second.items()}
    assert forex_app.portfolio_foundation.snapshot()["positions"] == {}


def test_after_a_restart_a_remembered_rejection_costs_one_cycle(forex_app):
    open_long_and_short(forex_app)
    manager = forex_app.execution
    healthy = manager.audit_persistence_state
    manager.audit_persistence_state = lambda: "RECOVERY_REQUIRED"
    candles_at(forex_app, FRIDAY_IN_WINDOW, {"EURUSD": 1.081, "GBPUSD": 1.299})
    run_at(forex_app, FRIDAY_IN_WINDOW)
    manager.audit_persistence_state = healthy
    forex_app.exit_guard._rejected_ids.clear()                             # what a restart forgets
    replayed = run_at(forex_app, FRIDAY_IN_WINDOW)                         # the stable id: answered from memory
    assert {o["execution_status"] for o in replayed.values()} == {"REJECTED"}
    later = FRIDAY_IN_WINDOW + timedelta(minutes=1)
    candles_at(forex_app, later, {"EURUSD": 1.081, "GBPUSD": 1.299})
    assert {o["execution_status"] for o in run_at(forex_app, later).values()} == {"PAPER_EXECUTED"}


class Book:
    def snapshot(self):
        return {"positions": {"EURUSD": {"base_quantity": "1000", "average_entry_price": "1.10",
                                         "position_id": "p1", "opened_at": "2026-10-28T10:00:00+00:00",
                                         "mark_price": "1.10"}}}


class Manager:
    def __init__(self, statuses):
        self.statuses, self.ids = list(statuses), []

    def execute(self, decision, _):
        self.ids.append(decision["request_id"])
        return {"status": self.statuses.pop(0), "reason": "X"}


CLOCK = 1_800_000_000.0


def guard_with(statuses):
    manager = Manager(statuses)
    clock = {"now": CLOCK}
    guard = ExitGuard(manager, Book(), rules=(ExitRule("ml", RULE_MAX_LOSS_PCT, D("0.05")),), mode=ENFORCE,
                      clock=lambda: clock["now"])
    return guard, manager, clock


def run(guard, clock, seconds):
    clock["now"] = CLOCK + seconds
    return guard.run_once({"EURUSD": Mark(D("1.00"), clock["now"] - 5)})[0]


def test_only_a_clean_rejection_is_retried_under_a_new_id():
    guard, manager, clock = guard_with(["COMMIT_STATUS_UNKNOWN", "RECOVERY_REQUIRED", "PAPER_EXECUTED"])
    for seconds in (0, 60, 120):
        assert run(guard, clock, seconds)["state"] == EXIT_TRIGGERED
    assert len(set(manager.ids)) == 1 and guard.stats["rejected"] == 0     # never a second id for these


def test_the_retry_id_changes_per_minute_not_per_call():
    guard, manager, clock = guard_with(["REJECTED"] * 4)
    for seconds in (0, 1, 2, 70):
        run(guard, clock, seconds)
    base, same_minute_a, same_minute_b, next_minute = manager.ids
    assert ":retry:" not in base and same_minute_a == same_minute_b != next_minute
    assert same_minute_a.startswith(base + ":retry:") and next_minute.startswith(base + ":retry:")
    assert guard.stats["rejected"] == 4


def test_an_executed_exit_keeps_the_historical_stable_id():
    guard, manager, clock = guard_with(["PAPER_EXECUTED", "PAPER_EXECUTED"])
    run(guard, clock, 0), run(guard, clock, 60)
    assert manager.ids[0] == manager.ids[1] and ":retry:" not in manager.ids[0]


# ---------------------------------------------------------------- R-3: the alert repeats hourly, not every cycle


def test_outside_the_window_the_pending_alert_repeats_once_an_hour(forex_app):
    open_long_and_short(forex_app)
    candles_at(forex_app, WEDNESDAY - timedelta(minutes=10), {"EURUSD": 1.08, "GBPUSD": 1.30})   # stale
    fired = []
    for cycle in range(1, 64):
        before = len(alerts(forex_app))
        assert {o["state"] for o in run_at(forex_app, WEDNESDAY).values()} == {EXIT_PENDING_PRICE}
        if len(alerts(forex_app)) > before:
            fired.append(cycle)
    assert fired == [3, 63]
    assert forex_app.market_loop.metrics["exit_pending_price_alerts"] == 2


# ---------------------------------------------------------------- the independent audit's findings (T029-F1..F6)


def test_after_an_indeterminate_answer_the_exit_is_never_sent_under_a_new_id():
    # T029-F2: REJECTED opens the retry ids; the first indeterminate answer pins the id it was given to
    guard, manager, clock = guard_with(["REJECTED", "COMMIT_STATUS_UNKNOWN", "RECOVERY_REQUIRED", "REJECTED",
                                        "PAPER_EXECUTED"])
    for seconds in (0, 60, 120, 180, 240):
        run(guard, clock, seconds)
    base, retried, *later = manager.ids
    assert retried.startswith(base + ":retry:") and later == [retried] * 3


def test_a_raised_submission_pins_the_id_too():
    guard, manager, clock = guard_with(["REJECTED"])
    run(guard, clock, 0)

    def boom(decision, _):
        manager.ids.append(decision["request_id"])
        raise RuntimeError("venue down")

    manager.execute = boom
    run(guard, clock, 60), run(guard, clock, 120), run(guard, clock, 180)
    assert len(set(manager.ids[1:])) == 1 and manager.ids[1].startswith(manager.ids[0] + ":retry:")


def test_with_negative_cash_a_short_is_refused_like_a_long(forex_app):
    # T029-F3: a SELL of a pair not held opens a short; it is new risk and negative cash refuses it
    force_cash(forex_app, "-500")
    result = forex_app.execution.execute({"symbol": "GBPUSD", "action": "SELL", "price": 1.30, "amount": 0,
                                          "confidence": 80, "risk": "HIGH", "request_id": "n-2", "strategy": "T",
                                          "proposed_quote_allocation": "2000"})
    assert result["status"] == "REJECTED", result
    assert forex_app.portfolio_foundation.snapshot()["positions"] == {}


def test_the_not_executed_alert_fires_at_once_and_then_once_an_hour(forex_app):
    # T029-F5: a persistent refusal must be seen at once, but not on every cycle
    open_long_and_short(forex_app)
    forex_app.execution.audit_persistence_state = lambda: "RECOVERY_REQUIRED"
    fired = []
    for cycle in range(1, 63):
        moment = FRIDAY_IN_WINDOW + timedelta(seconds=cycle)
        candles_at(forex_app, moment, {"EURUSD": 1.081, "GBPUSD": 1.299})
        before = len(events(forex_app, "EXIT_GUARD_EXIT_NOT_EXECUTED"))
        run_at(forex_app, moment)
        if len(events(forex_app, "EXIT_GUARD_EXIT_NOT_EXECUTED")) > before:
            fired.append(cycle)
    assert fired == [1, 61]
    assert events(forex_app, "EXIT_GUARD_EXIT_NOT_EXECUTED")[-1]["consecutive_cycles"] == {"EURUSD": 61, "GBPUSD": 61}


def test_a_recovered_exit_resets_the_not_executed_streak(forex_app):
    # a symbol that fails again after recovering alerts at once, not 60 cycles later
    open_long_and_short(forex_app)
    manager = forex_app.execution
    healthy = manager.audit_persistence_state
    manager.audit_persistence_state = lambda: "RECOVERY_REQUIRED"
    for second in (1, 2):
        candles_at(forex_app, FRIDAY_IN_WINDOW + timedelta(seconds=second), {"EURUSD": 1.081, "GBPUSD": 1.299})
        run_at(forex_app, FRIDAY_IN_WINDOW + timedelta(seconds=second))
    assert len(events(forex_app, "EXIT_GUARD_EXIT_NOT_EXECUTED")) == 1
    manager.audit_persistence_state = healthy
    run_at(forex_app, WEDNESDAY)                                    # a cycle with no failed exit: the streak ends
    manager.audit_persistence_state = lambda: "RECOVERY_REQUIRED"
    moment = FRIDAY_IN_WINDOW + timedelta(seconds=3)
    candles_at(forex_app, moment, {"EURUSD": 1.081, "GBPUSD": 1.299})
    run_at(forex_app, moment)
    latest = events(forex_app, "EXIT_GUARD_EXIT_NOT_EXECUTED")
    assert len(latest) == 2 and latest[-1]["consecutive_cycles"] == {"EURUSD": 1, "GBPUSD": 1}


def test_one_alert_failing_never_costs_the_other(forex_app, monkeypatch, caplog):
    # T029-F6: the pending-price alert raises (GBPUSD unpriced, in the window); the not-executed alert still fires
    open_long_and_short(forex_app)
    forex_app.execution.audit_persistence_state = lambda: "RECOVERY_REQUIRED"
    real = forex_app.market_loop._increment_metric

    def metric(name, *args, **kwargs):
        if name == "exit_pending_price_alerts":
            raise RuntimeError("metrics down")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(forex_app.market_loop, "_increment_metric", metric)
    candles_at(forex_app, FRIDAY_IN_WINDOW, {"EURUSD": 1.081})
    run_at(forex_app, FRIDAY_IN_WINDOW)
    assert "pending-price alert failed" in caplog.text
    assert [e["symbols"] for e in events(forex_app, "EXIT_GUARD_EXIT_NOT_EXECUTED")] == [{"EURUSD": "REJECTED"}]


@pytest.mark.xfail(strict=True, reason="T029-F1 (HIGH, open, owner decision required): when a close leaves the "
                                       "book's equity at or below zero, risk accounting refuses the figures "
                                       "(DURABLE_FIGURES_NOT_ACCOUNTABLE) and the runtime halts fail-closed with "
                                       "the other positions open. Registry v5.112 records it; Task 029 does not "
                                       "claim to fix it.")
def test_open_finding_a_blow_out_past_zero_equity_should_still_close_everything(forex_app):
    open_long_and_short(forex_app)                                  # 1000 GBPUSD short at 1.30
    candles_at(forex_app, WEDNESDAY, {"EURUSD": 1.08, "GBPUSD": 13.0})
    run_at(forex_app, WEDNESDAY)
    later = WEDNESDAY + timedelta(minutes=1)
    candles_at(forex_app, later, {"EURUSD": 1.08, "GBPUSD": 13.0})
    run_at(forex_app, later)
    assert forex_app.portfolio_foundation.snapshot()["positions"] == {}
    assert forex_app.execution.execution_halted is False
