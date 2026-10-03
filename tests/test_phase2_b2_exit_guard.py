"""Phase-2 B2: ExitGuard - Brain-independent reduce-only exits.

Real AtlasApplication on tmp_path state holding 10 BTCUSDT @ 10.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from core.exit_guard import (
    ENFORCE,
    EXECUTION_UNAVAILABLE,
    EXIT_NOT_TRIGGERED,
    EXIT_PENDING_PRICE,
    EXIT_TRIGGERED,
    OBSERVED,
    PROTECTIVE_EXIT,
    RULE_MAX_LOSS_PCT,
    SAFETY_EXIT,
    ExitGuard,
    ExitRule,
    Mark,
)
from tests.test_block2_risk_service_composition_wiring import seed_valid_state
from tests.test_phase2_a3_b1_audit_policy_and_reduce_only import _fail_audit_at
from tests.test_risk_accounting_day_auto_rollover import _app

D = Decimal
RULE = ExitRule("max-loss-5", RULE_MAX_LOSS_PCT, D("0.05"))


@pytest.fixture(autouse=True)
def _isolated_roots(monkeypatch):
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)


@pytest.fixture
def held(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir, held=("BTCUSDT", "10", "10"))
    return state_dir, _app(state_dir)


def _guard(app, *, mode=ENFORCE, rules=(RULE,), clock=time.time):
    return ExitGuard(app.execution, app.portfolio_foundation, rules=rules, mode=mode, clock=clock)


def _marks(price="9", age=0.0):
    return {"BTCUSDT": Mark(D(price), time.time() - age)}


def _positions(app):
    return app.portfolio_foundation.snapshot()["positions"]


def test_defaults_are_inert(held):
    _, app = held
    guard = ExitGuard(app.execution, app.portfolio_foundation)
    assert guard.mode == "OBSERVE" and guard.rules == ()
    [outcome] = guard.run_once(_marks("1"))
    assert outcome["state"] == EXIT_NOT_TRIGGERED
    assert "BTCUSDT" in _positions(app)


def test_observe_mode_never_executes(held):
    _, app = held
    [outcome] = _guard(app, mode="OBSERVE").run_once(_marks("9"))
    assert outcome["state"] == EXIT_TRIGGERED and outcome["outcome"] == OBSERVED
    assert "BTCUSDT" in _positions(app)


def test_protective_exit_with_brain_unavailable(held):
    _, app = held
    app.brain = None  # the guard never consults the Brain

    [outcome] = _guard(app).run_once(_marks("9"))

    assert outcome["execution_status"] == "PAPER_EXECUTED", outcome
    assert _positions(app) == {}


def test_rule_not_triggered_above_threshold(held):
    _, app = held
    [outcome] = _guard(app).run_once(_marks("9.6"))
    assert outcome["state"] == EXIT_NOT_TRIGGERED
    assert "BTCUSDT" in _positions(app)


@pytest.mark.parametrize("marks", [{}, {"BTCUSDT": Mark(D("9"), time.time() - 10_000)},
                                   {"BTCUSDT": Mark(D("0"), time.time())},
                                   {"BTCUSDT": Mark(D("9"), time.time() + 3600)}])
def test_stale_or_missing_price_is_pending_not_a_blind_sale(held, marks):
    _, app = held
    [outcome] = _guard(app).run_once(marks)
    assert outcome["state"] == EXIT_PENDING_PRICE
    assert "BTCUSDT" in _positions(app)


def test_execution_unavailable_offline_manager(held):
    _, app = held
    app.execution.running = False

    [outcome] = _guard(app).run_once(_marks("9"))

    assert outcome["execution_status"] != "PAPER_EXECUTED"
    assert "BTCUSDT" in _positions(app)


def test_execution_unavailable_raising_manager(held):
    _, app = held

    class _Broken:
        def execute(self, *a, **k):
            raise ConnectionError("down")

    guard = ExitGuard(_Broken(), app.portfolio_foundation, rules=(RULE,), mode=ENFORCE)
    [outcome] = guard.run_once(_marks("9"))
    assert outcome["outcome"] == EXECUTION_UNAVAILABLE


def test_duplicate_exit_request_executes_once(held):
    _, app = held
    guard = _guard(app)
    first = guard.run_once(_marks("9"))
    request_id = first[0]["request_id"]

    # Re-submitting the very same intent (e.g. a retry) is the same request.
    from core.execution_models import ExecutionRequest

    journal_before = dict(app.transaction_journal.entries[request_id])
    again = app.execution.execute(ExecutionRequest(
        "BTCUSDT", "SELL", 9.0, "100", confidence=0, risk="HIGH",
        request_id=request_id, reduce_only=True,
    ).to_dict(), None)

    # Idempotent replay of the terminal result: same execution, no new fill.
    assert again.get("execution_id") == first[0]["execution_result"]["execution_id"]
    assert app.transaction_journal.entries[request_id] == journal_before
    assert _positions(app) == {}
    assert app.transaction_journal.entries[request_id]["state"] == "COMMITTED"


def test_request_id_is_stable_across_restart(held):
    state_dir, app = held
    before = _guard(app, mode="OBSERVE").evaluate(_marks("9"))[0].request_id
    restarted = _app(state_dir)
    after = _guard(restarted, mode="OBSERVE").evaluate(_marks("9"))[0].request_id
    assert before == after


def test_restart_after_exit_does_not_exit_again(held):
    state_dir, app = held
    _guard(app).run_once(_marks("9"))
    assert _positions(app) == {}

    restarted = _app(state_dir)
    assert _guard(restarted).run_once(_marks("9")) == []


def test_exit_executes_with_audit_degraded(held, monkeypatch):
    _, app = held
    _fail_audit_at(monkeypatch, app, "EXECUTION_REQUEST_RECEIVED", 1)  # rolled back

    [outcome] = _guard(app).run_once(_marks("9"))

    assert app.execution.audit_persistence_state() == "DEGRADED"
    assert outcome["execution_status"] == "PAPER_EXECUTED", outcome
    assert _positions(app) == {}


def test_exit_with_poisoned_audit_is_refused_before_execution(held, monkeypatch):
    """Never commit-then-halt: the realized-P&L booking needs a write-ahead
    audit record a poisoned writer cannot produce."""
    _, app = held
    _fail_audit_at(monkeypatch, app, "EXECUTION_REQUEST_RECEIVED", 2)  # poisoned

    [outcome] = _guard(app).run_once(_marks("9"))

    assert outcome["execution_status"] != "PAPER_EXECUTED"
    assert "AUDIT_PERSISTENCE_RECOVERY_REQUIRED" in str(outcome["execution_result"])
    assert "BTCUSDT" in _positions(app)
    assert app.execution.recovery_required is False


def test_journal_recovery_blocks_the_exit_without_corruption(held):
    _, app = held
    app.execution.execution_halted = True
    app.execution.recovery_required = True

    [outcome] = _guard(app).run_once(_marks("9"))

    assert outcome["execution_status"] == "RECOVERY_REQUIRED"
    assert "BTCUSDT" in _positions(app)


def test_safety_exit_sorts_before_protective():
    a = ExitRule("p", RULE_MAX_LOSS_PCT, D("0.05"), PROTECTIVE_EXIT)
    b = ExitRule("s", RULE_MAX_LOSS_PCT, D("0.5"), SAFETY_EXIT)

    class _Book:
        def snapshot(self):
            return {"positions": {"BTCUSDT": {"position_id": "long:BTCUSDT", "base_quantity": "1",
                                               "average_entry_price": "10", "mark_price": "10"}}}

    guard = ExitGuard(None, _Book(), rules=(a, b))
    assert [r.rule_id for r in guard.rules] == ["s", "p"]
    [intent] = guard.evaluate({"BTCUSDT": Mark(D("4"), time.time())})
    assert intent.priority == SAFETY_EXIT


@pytest.mark.parametrize("bad", [
    dict(rule_id="", kind=RULE_MAX_LOSS_PCT, threshold=D("0.1")),
    dict(rule_id="x", kind="TAKE_PROFIT", threshold=D("0.1")),
    dict(rule_id="x", kind=RULE_MAX_LOSS_PCT, threshold=D("0")),
    dict(rule_id="x", kind=RULE_MAX_LOSS_PCT, threshold=0.1),
    dict(rule_id="x", kind=RULE_MAX_LOSS_PCT, threshold=D("0.1"), priority="ALPHA"),
])
def test_rules_are_validated(bad):
    with pytest.raises(ValueError):
        ExitRule(**bad)


def test_guard_never_buys(held):
    """Every submission is a reduce-only SELL."""
    _, app = held
    seen = []

    class _Spy:
        def execute(self, decision, market_state):
            seen.append(decision)
            return {"status": "X"}

    ExitGuard(_Spy(), app.portfolio_foundation, rules=(RULE,), mode=ENFORCE).run_once(_marks("9"))
    assert [d["action"] for d in seen] == ["SELL"]
    assert all(d["reduce_only"] for d in seen)
