"""Crash-recovered PAPER SELLs are booked into risk accounting exactly once.

Registry v4.82 left MEDIUM-1 open: ``tools/reconcile_execution_authorities.py``
could resolve an interrupted SELL COMMITTED without its realized P&L and
equity ever reaching ``risk_accounting_state.json``. The tool now books it
through the runtime's own hook, ``ExecutionManager._record_realized_risk_accounting``,
and never books what the runtime already booked.

Where the hook sits decides what each crash window needs:

- K2 (killed inside ``apply_confirmed``): the hook never ran; the
  re-derivation books it with the genuine pre-transition and completed views.
- killed inside the hook, after its PREPARED record but before the write: the
  recovery re-runs the hook and must reproduce that record's ``new_state``.
- K4..K6 (killed after ``_finalize_durable_financial_state`` returned): the
  hook already booked it; the recovery must write nothing.
- killed before the PREPARED record: no durable figures exist; refused.

"Identically to normal execution" is proven by comparing every recovered
state with the state the same trade produces uninterrupted. Every test runs
in its own ``tmp_path`` state directory with the policy ``AtlasApplication``
actually configures - no threshold is overridden.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from core.application import (
    EXECUTION_AUDIT_EVENT_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    RISK_ACCOUNTING_STATE_FILE,
)
from core.execution_portfolio_foundation import FinancialStateStore
from core.execution_transaction_journal import CommitOutcome, ExecutionTransactionJournal
from core.risk_state_store import JsonRiskStateStore

import tools.reconcile_execution_authorities as reconcile_module
from tools.reconcile_execution_authorities import (
    ReconciliationOutcome,
    RecoveryClass,
    RiskAccounting,
    reconcile,
)

from tests.test_execution_crash_recovery_f1_f6 import (
    RECONCILE_CLI_PATH,
    RECOVERY_FILES,
    SimulatedCrash,
    _assert_restart_healthy,
    _buy,
    _crash_on,
    _fresh_state,
    _journal_state,
    _recover,
    _run_until_crash,
)
from tests.test_risk_accounting_realized_pnl_wiring import (
    PNL_COMMITTED,
    PNL_PREPARED,
    _app,
    _buy_check,
    _events,
    _sell,
    _state,
    _stored,
    _today,
    _write_risk_state,
)

D = Decimal

# Every durable file a recovery may touch, plus the two this change adds.
ALL_FILES = RECOVERY_FILES + (RISK_ACCOUNTING_STATE_FILE, EXECUTION_AUDIT_EVENT_FILE)


@pytest.fixture(autouse=True)
def _isolated_roots(monkeypatch):
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _files(state_dir: Path) -> dict[str, bytes | None]:
    return {
        name: (state_dir / name).read_bytes() if (state_dir / name).exists() else None
        for name in ALL_FILES
    }


def _risk_bytes(state_dir: Path) -> bytes:
    return (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()


def _pnl_events(state_dir: Path, request_id: str, event_type: str) -> list:
    return [e for e in _events(state_dir, event_type) if e.correlation_id == request_id]


def _figures(state_dir: Path) -> tuple:
    stored = _stored(state_dir)
    return (stored.accounting_day_utc, stored.realized_daily_pnl, stored.peak_equity,
            stored.current_equity)


def _prepare(tmp_path: Path, name: str, *, cash: str = "9000",
             risk: dict | None = None) -> Path:
    state_dir = _state(tmp_path / name, cash=cash)
    if risk is not None:
        _write_risk_state(state_dir, **risk)
    return state_dir


def _baseline(tmp_path: Path, *, base: str, price: str, cash: str = "9000",
              risk: dict | None = None) -> tuple:
    """The accounting state and book the same SELL produces uninterrupted."""
    state_dir = _prepare(tmp_path, "baseline", cash=cash, risk=risk)
    app = _app(state_dir)
    result = _sell(app, base=base, price=price, request_id="s1")
    assert result["status"] == "PAPER_EXECUTED", result
    snapshot = app.portfolio_foundation.snapshot()
    return _figures(state_dir), snapshot["equity"], snapshot["realized_net_pnl"]


def _crashed_sell(tmp_path: Path, monkeypatch, crash, *, base: str, price: str,
                  cash: str = "9000", risk: dict | None = None) -> Path:
    state_dir = _prepare(tmp_path, "crashed", cash=cash, risk=risk)
    app = _app(state_dir)
    crash(app, monkeypatch)
    _run_until_crash(app, lambda running: _sell(running, base=base, price=price,
                                                request_id="s1"))
    # The crash patches live on the dead runtime's own objects; the recovery
    # builds its own, so they are left in place.
    return state_dir


# The crash windows of one SELL, in commit order.


def _crash_k2(app, monkeypatch):
    # Inside apply_confirmed: the applied record landed, the book did not.
    _crash_on(monkeypatch, app.portfolio_foundation.applied_archive, "append", after=True)


def _crash_before_accounting_prepared(app, monkeypatch):
    # apply_confirmed committed; the hook died before its PREPARED record.
    original = app.execution.audit_store.append

    def crashing(*args, **kwargs):
        if kwargs.get("event_type") == PNL_PREPARED:
            raise SimulatedCrash("audit.append")
        return original(*args, **kwargs)

    monkeypatch.setattr(app.execution.audit_store, "append", crashing)


def _crash_before_accounting_write(app, monkeypatch):
    # PREPARED is durable; the risk-state write never happened.
    _crash_on(monkeypatch, app.risk_state_store, "save")


def _crash_after_accounting_write(app, monkeypatch):
    # The write landed; its COMMITTED record did not.
    _crash_on(monkeypatch, app.risk_state_store, "save", after=True)


def _crash_k4(app, monkeypatch):
    _crash_on(monkeypatch, app.execution, "_mirror_paper_book")


def _crash_k5(app, monkeypatch):
    _crash_on(monkeypatch, app.execution, "_complete_request")


def _crash_k6(app, monkeypatch):
    _crash_on(monkeypatch, app.execution.transaction_journal, "mark_committed")


# ==========================================================================
# K2 - the re-derivation books the realized result through the hook
# ==========================================================================


@pytest.mark.parametrize(("base", "price"), [("100", "9"), ("40", "9"), ("100", "12")],
                         ids=["full-exit-loss", "partial-reduction-loss", "full-exit-gain"])
def test_k2_rederivation_books_exactly_what_normal_execution_books(
    tmp_path, monkeypatch, base, price,
):
    expected, equity, _ = _baseline(tmp_path, base=base, price=price)
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base=base, price=price)
    # The hook never ran: nothing is booked and nothing was prepared.
    assert _stored(state_dir).realized_daily_pnl == D("0")
    assert _pnl_events(state_dir, "s1", PNL_PREPARED) == []

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED, outcome
    assert outcome.recovery_class == RecoveryClass.COMMIT_PAPER_REDERIVATION.value
    assert outcome.risk_accounting == RiskAccounting.RECORD.value
    assert _figures(state_dir) == expected
    assert _stored(state_dir).current_equity == equity
    prepared = _pnl_events(state_dir, "s1", PNL_PREPARED)
    committed = _pnl_events(state_dir, "s1", PNL_COMMITTED)
    assert len(prepared) == 1 and len(committed) == 1
    assert committed[0].causation_id == prepared[0].event_id
    assert prepared[0].payload["figures_source"] == "ExecutionPortfolioFoundation"
    restarted = _assert_restart_healthy(state_dir)
    assert _figures(state_dir) == expected
    assert restarted.portfolio_foundation.snapshot()["equity"] == equity


def test_k2_recovered_loss_crossing_the_daily_limit_fires_daily_loss_limit_breached(
    tmp_path, monkeypatch,
):
    """100 units bought at 10, sold at 4.9 and killed inside apply_confirmed:
    -510, over the 500 ceiling. Before recovery the store shows no loss at
    all; the limit fires only because the recovery booked it."""
    expected, _, _ = _baseline(tmp_path, base="100", price="4.9")
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="4.9")
    assert _stored(state_dir).realized_daily_pnl == D("0")

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED, outcome
    assert outcome.risk_accounting == RiskAccounting.RECORD.value
    assert _figures(state_dir) == expected
    app = _assert_restart_healthy(state_dir)
    ceiling = app.risk_policy.total_capital * app.risk_policy.max_daily_loss_pct
    assert -_stored(state_dir).realized_daily_pnl >= ceiling
    rejected = _buy_check(app, "after")
    assert rejected["approved"] is False
    assert rejected["reason"] == "DAILY_LOSS_LIMIT_BREACHED"
    # A rejection of new risk, not a runtime halt.
    assert app.execution.execution_halted is False
    assert app.execution.recovery_required is False


def test_k2_recovered_loss_crossing_into_drawdown_halt_fires_drawdown_halt_new_risk(
    tmp_path, monkeypatch,
):
    """Prior days left the book 14% below peak (RESTRICT). The recovered loss
    of 450 - under the daily ceiling - takes it past 15%."""
    risk = {"peak": "10000", "current": "8600"}
    expected, _, _ = _baseline(tmp_path, base="100", price="5.5", cash="7600", risk=risk)
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="5.5",
                              cash="7600", risk=risk)
    assert _stored(state_dir).current_equity == D("8600")

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED, outcome
    assert _figures(state_dir) == expected
    stored = _stored(state_dir)
    assert -stored.realized_daily_pnl < D("500")
    assert (stored.peak_equity - stored.current_equity) / stored.peak_equity >= D("0.15")
    app = _assert_restart_healthy(state_dir)
    rejected = _buy_check(app, "after")
    assert rejected["approved"] is False
    assert rejected["reason"] == "DRAWDOWN_HALT_NEW_RISK"
    assert app.execution.execution_halted is False


def test_k2_buy_books_nothing_exactly_as_normal_execution(tmp_path, monkeypatch):
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    _crash_k2(app, monkeypatch)
    _run_until_crash(app, _buy)
    before = _risk_bytes(state_dir)

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED, outcome
    assert outcome.risk_accounting == RiskAccounting.NOT_APPLICABLE.value
    assert _risk_bytes(state_dir) == before
    assert _pnl_events(state_dir, "r1", PNL_PREPARED) == []


# ==========================================================================
# Killed inside the hook
# ==========================================================================


@pytest.mark.parametrize(("base", "price"), [("100", "9"), ("40", "9")],
                         ids=["full-exit", "partial-reduction"])
def test_prepared_but_unwritten_accounting_is_redone_to_the_prepared_state(
    tmp_path, monkeypatch, base, price,
):
    expected, _, _ = _baseline(tmp_path, base=base, price=price)
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_before_accounting_write,
                              base=base, price=price)
    prepared = _pnl_events(state_dir, "s1", PNL_PREPARED)
    assert len(prepared) == 1
    assert _stored(state_dir).realized_daily_pnl == D("0")

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED, outcome
    assert outcome.recovery_class == RecoveryClass.COMMIT_APPLIED_EVIDENCE.value
    assert outcome.risk_accounting == RiskAccounting.RECORD.value
    assert _figures(state_dir) == expected
    stored = _stored(state_dir).to_dict()
    for field in ("realized_daily_pnl", "peak_equity", "current_equity"):
        assert D(stored[field]) == D(prepared[0].payload["new_state"][field])
    redone = _pnl_events(state_dir, "s1", PNL_PREPARED)[-1]
    assert D(redone.payload["realized_pnl"]) == D(prepared[0].payload["realized_pnl"])
    assert len(_pnl_events(state_dir, "s1", PNL_COMMITTED)) == 1
    _assert_restart_healthy(state_dir)


def test_redone_loss_crossing_the_daily_limit_fires_daily_loss_limit_breached(
    tmp_path, monkeypatch,
):
    expected, _, _ = _baseline(tmp_path, base="100", price="4.9")
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_before_accounting_write,
                              base="100", price="4.9")
    assert _stored(state_dir).realized_daily_pnl == D("0")

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED, outcome
    assert outcome.risk_accounting == RiskAccounting.RECORD.value
    assert _figures(state_dir) == expected
    app = _assert_restart_healthy(state_dir)
    assert _buy_check(app, "after")["reason"] == "DAILY_LOSS_LIMIT_BREACHED"
    assert app.execution.execution_halted is False


def test_redone_loss_crossing_into_drawdown_halt_fires_drawdown_halt_new_risk(
    tmp_path, monkeypatch,
):
    risk = {"peak": "10000", "current": "8600"}
    expected, _, _ = _baseline(tmp_path, base="100", price="5.5", cash="7600", risk=risk)
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_before_accounting_write,
                              base="100", price="5.5", cash="7600", risk=risk)
    assert _stored(state_dir).current_equity == D("8600")

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED, outcome
    assert outcome.risk_accounting == RiskAccounting.RECORD.value
    assert _figures(state_dir) == expected
    app = _assert_restart_healthy(state_dir)
    assert _buy_check(app, "after")["reason"] == "DRAWDOWN_HALT_NEW_RISK"


def test_redo_refuses_when_the_book_moved_since_the_prepared_record(tmp_path, monkeypatch):
    """The current book is the hook's ``after`` only while its equity is the
    one the PREPARED record saw."""
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_before_accounting_write,
                              base="40", price="9")
    store = FinancialStateStore(state_dir / EXECUTION_FINANCIAL_STATE_FILE)
    payload = store.load()
    payload["positions"]["BTCUSDT"]["mark_price"] = "11"
    store.save(payload)
    before = _files(state_dir)

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "RECOVERY_EVIDENCE_AMBIGUOUS"
    assert _files(state_dir) == before


def test_redo_on_a_later_day_is_refused_before_anything_is_written(tmp_path, monkeypatch):
    """A crash inside the hook before midnight, recovered after: the stored
    state is still the PREPARED record's previous_state, on yesterday."""
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_before_accounting_write,
                              base="100", price="9")
    prepared = _pnl_events(state_dir, "s1", PNL_PREPARED)[0]
    moment = _today()
    monkeypatch.setattr(
        reconcile_module, "datetime",
        type("Tomorrow", (reconcile_module.datetime,), {
            "now": classmethod(lambda cls, tz=None: reconcile_module.datetime.combine(
                moment + timedelta(days=1), reconcile_module.datetime.min.time(), tz)),
        }),
    )
    assert prepared.payload["previous_state"]["accounting_day_utc"] == moment.isoformat()
    before = _files(state_dir)

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "RISK_ACCOUNTING_DAY_NOT_CURRENT"
    assert _files(state_dir) == before


def test_written_accounting_without_its_committed_record_is_never_booked_twice(
    tmp_path, monkeypatch,
):
    expected, _, _ = _baseline(tmp_path, base="100", price="9")
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_after_accounting_write,
                              base="100", price="9")
    assert _figures(state_dir) == expected
    assert _pnl_events(state_dir, "s1", PNL_COMMITTED) == []
    risk_before = _risk_bytes(state_dir)

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED, outcome
    assert outcome.risk_accounting == RiskAccounting.ALREADY_RECORDED.value
    assert _risk_bytes(state_dir) == risk_before
    assert len(_pnl_events(state_dir, "s1", PNL_PREPARED)) == 1
    _assert_restart_healthy(state_dir)
    assert _figures(state_dir) == expected


def test_no_prepared_record_means_no_figures_and_is_refused(tmp_path, monkeypatch):
    """Killed after apply_confirmed but before the hook's write-ahead record:
    the book moved and nothing durable says by how much. Refused - never
    resolved COMMITTED with the loss unbooked."""
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_before_accounting_prepared,
                              base="100", price="4.9")
    assert _pnl_events(state_dir, "s1", PNL_PREPARED) == []
    before = _files(state_dir)

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "RISK_ACCOUNTING_EVIDENCE_UNAVAILABLE"
    assert _files(state_dir) == before
    assert _journal_state(state_dir, "s1") == "PREPARED"


# ==========================================================================
# K4..K6 - the runtime's hook already booked it
# ==========================================================================


@pytest.mark.parametrize("crash", [_crash_k4, _crash_k5, _crash_k6], ids=["K4", "K5", "K6"])
def test_k4_to_k6_sell_was_booked_before_the_crash_and_is_never_booked_twice(
    tmp_path, monkeypatch, crash,
):
    """K3 (the reservation commit) does not exist for a SELL. Every later
    window runs after the hook returned, so the result is already booked."""
    expected, _, _ = _baseline(tmp_path, base="100", price="4.9")
    state_dir = _crashed_sell(tmp_path, monkeypatch, crash, base="100", price="4.9")
    assert _figures(state_dir) == expected
    risk_before = _risk_bytes(state_dir)

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED, outcome
    assert outcome.recovery_class == RecoveryClass.COMMIT_APPLIED_EVIDENCE.value
    assert outcome.risk_accounting == RiskAccounting.ALREADY_RECORDED.value
    assert _risk_bytes(state_dir) == risk_before
    assert len(_pnl_events(state_dir, "s1", PNL_PREPARED)) == 1
    app = _assert_restart_healthy(state_dir)
    assert _figures(state_dir) == expected
    # The limit the runtime's own booking crossed still holds after recovery.
    assert _buy_check(app, "after")["reason"] == "DAILY_LOSS_LIMIT_BREACHED"


@pytest.mark.parametrize("crash_name", ["commit", "_mirror_paper_book", "_complete_request",
                                        "mark_committed"], ids=["K3", "K4", "K5", "K6"])
def test_k3_to_k6_buy_books_nothing(tmp_path, monkeypatch, crash_name):
    state_dir = _fresh_state(tmp_path)
    app = _app(state_dir)
    target = {
        "commit": app.execution.reservation_ledger,
        "mark_committed": app.execution.transaction_journal,
    }.get(crash_name, app.execution)
    _crash_on(monkeypatch, target, crash_name)
    _run_until_crash(app, _buy)
    before = _risk_bytes(state_dir)

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED, outcome
    assert outcome.risk_accounting == RiskAccounting.NOT_APPLICABLE.value
    assert _risk_bytes(state_dir) == before


# ==========================================================================
# Fail-closed edges
# ==========================================================================


def test_accounting_day_not_today_is_refused_before_anything_is_written(
    tmp_path, monkeypatch,
):
    """A crash on an earlier UTC day: the hook books only onto today, and a
    recovery never rolls the day, so it refuses rather than misbooking."""
    yesterday = _today() - timedelta(days=1)
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")
    _write_risk_state(state_dir, day=yesterday)
    before = _files(state_dir)

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "RISK_ACCOUNTING_DAY_NOT_CURRENT"
    assert _files(state_dir) == before


def test_stored_state_matching_neither_side_of_the_record_is_ambiguous(
    tmp_path, monkeypatch,
):
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_before_accounting_write,
                              base="100", price="9")
    _write_risk_state(state_dir, pnl="-1")
    before = _files(state_dir)

    outcome = _recover(state_dir)

    assert outcome.reason_code == "RECOVERY_EVIDENCE_AMBIGUOUS"
    assert _files(state_dir) == before


def test_unreadable_risk_state_is_refused(tmp_path, monkeypatch):
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")
    (state_dir / RISK_ACCOUNTING_STATE_FILE).write_text("{", encoding="utf-8")
    before = _files(state_dir)

    outcome = _recover(state_dir)

    assert outcome.reason_code == "RECOVERY_AUTHORITY_UNREADABLE"
    assert _files(state_dir) == before


def test_dry_run_reports_the_booking_and_writes_nothing(tmp_path, monkeypatch):
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")
    before = _files(state_dir)

    outcome = reconcile(state_dir, apply=False, execution_mode="PAPER")

    assert outcome.outcome is ReconciliationOutcome.WOULD_RECOVER
    assert outcome.risk_accounting == RiskAccounting.RECORD.value
    assert _files(state_dir) == before
    rendered = reconcile_module._render_json(outcome, 0)
    assert '"risk_accounting": "RECORD"' in rendered
    assert "risk_accounting: RECORD" in reconcile_module._render_human(outcome, 0)


def test_failed_booking_restores_every_file_and_a_rerun_books_once(tmp_path, monkeypatch):
    expected, _, _ = _baseline(tmp_path, base="100", price="9")
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")
    before = {name: data for name, data in _files(state_dir).items()
              if name != EXECUTION_AUDIT_EVENT_FILE}

    def failing_save(self, value):
        raise OSError("disk full")

    with monkeypatch.context() as patched:
        patched.setattr(JsonRiskStateStore, "save", failing_save)
        outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.FAILED
    assert outcome.reason_code == "RISK_ACCOUNTING_UPDATE_FAILED"
    after = {name: data for name, data in _files(state_dir).items()
             if name != EXECUTION_AUDIT_EVENT_FILE}
    assert after == before
    # The append-only audit log keeps the orphan PREPARED; it is harmless.
    assert len(_pnl_events(state_dir, "s1", PNL_PREPARED)) == 1

    rerun = _recover(state_dir)

    assert rerun.outcome is ReconciliationOutcome.RECOVERED, rerun
    assert rerun.risk_accounting == RiskAccounting.RECORD.value
    assert _figures(state_dir) == expected


def test_failure_after_booking_rolls_the_booking_back_and_a_rerun_books_once(
    tmp_path, monkeypatch,
):
    """The journal resolution fails after the hook wrote and COMMITTED: the
    restored store equals the record's previous_state, so the rerun books
    again - once."""
    expected, _, _ = _baseline(tmp_path, base="100", price="9")
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")
    risk_before = _risk_bytes(state_dir)

    with monkeypatch.context() as patched:
        patched.setattr(ExecutionTransactionJournal, "mark_committed",
                        lambda self, request_id, result: False)
        outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.FAILED
    assert outcome.reason_code == "RECOVERY_WRITE_FAILED"
    assert _risk_bytes(state_dir) == risk_before
    assert len(_pnl_events(state_dir, "s1", PNL_COMMITTED)) == 1  # the rolled-back one

    rerun = _recover(state_dir)

    assert rerun.outcome is ReconciliationOutcome.RECOVERED, rerun
    assert _figures(state_dir) == expected
    assert _journal_state(state_dir, "s1") == CommitOutcome.COMMITTED.value
    _assert_restart_healthy(state_dir)


def test_tool_killed_after_booking_is_resolved_by_a_rerun_without_rebooking(
    tmp_path, monkeypatch,
):
    """This tool killed after the hook wrote but before the journal resolved:
    the rerun sees the booking landed and books nothing again."""
    expected, _, _ = _baseline(tmp_path, base="100", price="9")
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")

    def killed(self, request_id, result):
        raise SimulatedCrash("mark_committed")

    with monkeypatch.context() as patched:
        patched.setattr(ExecutionTransactionJournal, "mark_committed", killed)
        with pytest.raises(SimulatedCrash):
            _recover(state_dir)
    assert _figures(state_dir) == expected
    booked = _risk_bytes(state_dir)

    rerun = _recover(state_dir)

    assert rerun.outcome is ReconciliationOutcome.RECOVERED, rerun
    assert rerun.risk_accounting == RiskAccounting.ALREADY_RECORDED.value
    assert _risk_bytes(state_dir) == booked
    assert len(_pnl_events(state_dir, "s1", PNL_PREPARED)) == 1
    _assert_restart_healthy(state_dir)


def test_tool_killed_between_book_completion_and_booking_is_refused_accepted_window(
    tmp_path, monkeypatch,
):
    """Independent audit MEDIUM-A, accepted: the re-derived book completed,
    the hook's PREPARED never landed. Refused on rerun - fail-closed, never
    resolved COMMITTED with the loss unbooked."""
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="4.9")

    def killed(*args, **kwargs):
        raise SimulatedCrash("_book_risk_accounting")

    with monkeypatch.context() as patched:
        patched.setattr(reconcile_module, "_book_risk_accounting", killed)
        with pytest.raises(SimulatedCrash):
            _recover(state_dir)
    before = _files(state_dir)

    rerun = _recover(state_dir)

    assert rerun.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert rerun.reason_code == "RISK_ACCOUNTING_EVIDENCE_UNAVAILABLE"
    assert _files(state_dir) == before
    assert _journal_state(state_dir, "s1") == "PREPARED"


def test_cli_booking_failure_leaks_no_identifier_or_exception_text(tmp_path, monkeypatch):
    """Independent audit LOW-B: the hook's failure log line carries the
    request id, symbol and raw exception text; the CLI must print none of it."""
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")
    script = "\n".join((
        "import sys",
        "import core.risk_state_store as store",
        "def failing(self, value):",
        "    raise OSError('secret-detail')",
        "store.JsonRiskStateStore.save = failing",
        "import tools.reconcile_execution_authorities as tool",
        "sys.exit(tool.main(sys.argv[1:]))",
    ))
    completed = subprocess.run(
        [sys.executable, "-c", script, "--state-directory", str(state_dir), "--apply",
         "--execution-mode", "PAPER", "--json"],
        capture_output=True, text=True, cwd=str(RECONCILE_CLI_PATH.parent.parent),
        timeout=120,
    )

    assert completed.returncode == 3, completed.stderr
    assert "RISK_ACCOUNTING_UPDATE_FAILED" in completed.stdout
    output = completed.stdout + completed.stderr
    for rendered in (str(state_dir), str(state_dir).replace("\\", "\\\\")):
        output = output.replace(rendered, "")
    for leaked in ("s1", "BTCUSDT", "secret-detail", "OSError"):
        assert leaked not in output, leaked


def test_tool_defaults_name_the_files_the_runtime_writes():
    assert reconcile_module.DEFAULT_RISK_STATE_FILE == RISK_ACCOUNTING_STATE_FILE
    assert reconcile_module.DEFAULT_AUDIT_FILE == EXECUTION_AUDIT_EVENT_FILE


@pytest.mark.parametrize("mode", ["LIVE", None])
def test_live_or_unstated_mode_never_books(tmp_path, monkeypatch, mode):
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")
    before = _files(state_dir)

    outcome = reconcile(state_dir, apply=True, execution_mode=mode)

    assert outcome.reason_code == "JOURNAL_UNRESOLVED"
    assert outcome.risk_accounting is None
    assert _files(state_dir) == before
