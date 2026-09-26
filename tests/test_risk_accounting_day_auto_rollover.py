"""Automatic PAPER risk-accounting day rollover.

``RiskEngine.evaluate`` rejects every request whose durable risk-accounting
day is not today's UTC date, and nothing in the runtime ever rolled that day
forward: once the calendar passed the bootstrap day, every execution was
refused with RISK_ACCOUNTING_DAY_RECONCILIATION_REQUIRED forever.

``ExecutionManager.risk_check`` now rolls the day forward before deriving the
risk state - PAPER mode only, and only when the journal holds nothing
unresolved and F-2's detection finds no orphaned reservation. Anything else
leaves the stored day untouched and the rejection exactly as before.

Every test runs against its own ``tmp_path`` state directory.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import core.execution_manager as execution_manager_module
import core.risk_engine as risk_engine_module
from core.application import (
    EXECUTION_AUDIT_EVENT_FILE,
    RISK_ACCOUNTING_STATE_FILE,
    AtlasApplication,
)
from core.audit_event_store import AuditEventStore
from core.capital_reservation import ReservationStatus
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState

from tests.test_block2_risk_service_composition_wiring import (
    POLICY_VERSION,
    high_bucket_allocation,
    seed_valid_state,
)
from tests.test_execution_crash_recovery_f1_f6 import SimulatedCrash, _buy

D = Decimal

PREPARED = ExecutionManager.RISK_DAY_ROLLOVER_PREPARED
COMMITTED = ExecutionManager.RISK_DAY_ROLLOVER_COMMITTED
STALE_REASON = "RISK_ACCOUNTING_DAY_RECONCILIATION_REQUIRED"


@pytest.fixture(autouse=True)
def _isolated_roots(monkeypatch):
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)


def _today() -> date:
    return datetime.now(UTC).date()


def _store(state_dir: Path) -> JsonRiskStateStore:
    return JsonRiskStateStore(state_dir / RISK_ACCOUNTING_STATE_FILE)


def _stored(state_dir: Path, today: date | None = None) -> RestoredRiskState:
    return _store(state_dir).load(
        expected_policy_version=POLICY_VERSION, today_utc=today or _today(),
    )


def _write_risk_state(state_dir: Path, *, day: date, pnl="0", peak="10000",
                      current="10000") -> None:
    _store(state_dir).save(
        RestoredRiskState(day, D(pnl), D(peak), D(current), POLICY_VERSION)
    )


def _stale_state(tmp_path: Path, *, days_ago: int = 1, held=None, **risk) -> Path:
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir, held=held)
    _write_risk_state(state_dir, day=_today() - timedelta(days=days_ago), **risk)
    return state_dir


def _app(state_dir: Path, *, start: bool = True) -> AtlasApplication:
    app = AtlasApplication(
        state_directory=state_dir, evidence_directory=state_dir.parent / "evidence",
    )
    if start:
        app.execution.start()
    return app


def _rollover_events(state_dir: Path) -> list:
    return [
        event
        for event in AuditEventStore(state_dir / EXECUTION_AUDIT_EVENT_FILE).read_all()
        if event.event_type in {PREPARED, COMMITTED}
    ]


def _risk_check(app: AtlasApplication, request_id: str = "rc1") -> dict:
    request = ExecutionRequest(
        "BTCUSDT", "BUY", 10, str(high_bucket_allocation(app)),
        confidence=90, risk="HIGH", request_id=request_id,
    )
    result = app.execution.risk_check(request)
    if result.get("approved"):
        # Never leave a test reservation behind.
        app.execution._release_capital_reservation(request.request_id)
    return result


# ==========================================================================
# trigger (a): restart on a later UTC day
# ==========================================================================


def test_restart_on_a_later_day_rolls_over_and_executes(tmp_path):
    state_dir = _stale_state(tmp_path, pnl="-25")
    app = _app(state_dir)

    result = _buy(app)

    assert result["status"] == "PAPER_EXECUTED", result
    rolled = _stored(state_dir)
    assert rolled.accounting_day_utc == _today()
    assert rolled.realized_daily_pnl == D("0")
    assert rolled.peak_equity == D("10000")
    events = _rollover_events(state_dir)
    assert [event.event_type for event in events] == [PREPARED, COMMITTED]
    prepared, committed = events
    assert prepared.payload["from_accounting_day_utc"] == (_today() - timedelta(days=1)).isoformat()
    assert prepared.payload["to_accounting_day_utc"] == _today().isoformat()
    assert prepared.payload["previous_state"]["realized_daily_pnl"] == "-25"
    assert prepared.payload["current_equity_source"] == "ExecutionPortfolioFoundation"
    assert committed.causation_id == prepared.event_id
    assert committed.payload["new_state"] == rolled.to_dict()


def test_rollover_is_logged_at_warning(tmp_path, caplog):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)

    with caplog.at_level("WARNING", logger=execution_manager_module.logger.name):
        _risk_check(app)

    assert any(
        record.levelname == "WARNING"
        and "Automatic PAPER risk-accounting day rollover" in record.getMessage()
        for record in caplog.records
    )


def test_open_position_never_blocks_rollover(tmp_path):
    state_dir = _stale_state(tmp_path, held=("BTCUSDT", "10", "10"))
    app = _app(state_dir)

    # Whatever the verdict on this BUY, it is no longer the stale-day block.
    assert _risk_check(app).get("reason") != STALE_REASON
    assert _stored(state_dir).accounting_day_utc == _today()


def test_current_equity_comes_from_the_durable_foundation(tmp_path):
    # Book: 9000 cash + 10 BTC marked at 20 = 9200 equity; peak stays 10000.
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir, held=("BTCUSDT", "10", "20"))
    from core.application import EXECUTION_FINANCIAL_STATE_FILE
    from core.execution_portfolio_foundation import FinancialStateStore

    store = FinancialStateStore(state_dir / EXECUTION_FINANCIAL_STATE_FILE)
    payload = store.load()
    payload["cash"] = "9000"
    store.save(payload)
    _write_risk_state(state_dir, day=_today() - timedelta(days=1))
    app = _app(state_dir)
    expected = app.portfolio_foundation.snapshot()["equity"]

    app.execution._auto_rollover_risk_accounting_day()

    rolled = _stored(state_dir)
    assert rolled.current_equity == expected == D("9200")
    assert rolled.peak_equity == D("10000")


# ==========================================================================
# trigger (b): an uninterrupted run through UTC midnight
# ==========================================================================


def _advance_clock(monkeypatch, moment: datetime) -> None:
    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment if tz is None else moment.astimezone(tz)

    monkeypatch.setattr(execution_manager_module, "datetime", _Clock)
    monkeypatch.setattr(risk_engine_module, "datetime", _Clock)


def test_continuous_run_through_midnight_rolls_over_without_restart(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = _app(state_dir)
    assert _risk_check(app, "before")["approved"] is True

    tomorrow = datetime.now(UTC).replace(hour=0, minute=0, second=1, microsecond=0) + timedelta(days=1)
    _advance_clock(monkeypatch, tomorrow)

    assert _risk_check(app, "after")["approved"] is True
    assert _stored(state_dir, tomorrow.date()).accounting_day_utc == tomorrow.date()
    assert [event.event_type for event in _rollover_events(state_dir)] == [PREPARED, COMMITTED]


def test_state_derived_before_midnight_is_never_approved_after_it(tmp_path, monkeypatch):
    """A request evaluated against the old day's state is rejected, not admitted."""
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = _app(state_dir)
    stale = app.execution._derive_risk_state()

    tomorrow = datetime.now(UTC) + timedelta(days=1)
    _advance_clock(monkeypatch, tomorrow)
    app.execution._auto_rollover_risk_accounting_day()

    from core.risk_engine import RiskRequest

    decision = app.risk_engine.evaluate(
        RiskRequest("BTCUSDT", "BUY", D("0.9"), D("10"), D("10"), "HIGH"), stale,
    )
    assert decision.reason_code == STALE_REASON


# ==========================================================================
# safety gate: dirty state stays fail-closed exactly as before
# ==========================================================================


def test_unresolved_journal_blocks_rollover_and_rejects_as_before(tmp_path, caplog):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    assert app.transaction_journal.prepare("pending", {"request_id": "pending"})
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()

    with caplog.at_level("WARNING", logger=execution_manager_module.logger.name):
        result = _risk_check(app)

    assert result["approved"] is False
    assert result["reason"] == STALE_REASON
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == before
    assert _rollover_events(state_dir) == []
    assert any("reason=JOURNAL_UNRESOLVED" in r.getMessage() for r in caplog.records)


def test_orphan_reservation_blocks_rollover_until_it_is_released(tmp_path):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    # Created after startup, so the F-2 sweep never saw it.
    app.reservation_ledger.reserve("orphan", "orphan", D("100"))
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()

    result = _risk_check(app)

    assert result["reason"] == STALE_REASON
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == before
    assert _rollover_events(state_dir) == []

    app.execution._release_capital_reservation("orphan")
    assert _risk_check(app, "rc2")["approved"] is True
    assert _stored(state_dir).accounting_day_utc == _today()


def test_in_flight_reservation_is_not_an_orphan(tmp_path):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    app.reservation_ledger.reserve("inflight", "inflight", D("100"))
    app.execution.pending_request_ids.add("inflight")

    app.execution._auto_rollover_risk_accounting_day()

    assert _stored(state_dir).accounting_day_utc == _today()
    assert app.reservation_ledger.get("inflight").status is ReservationStatus.RESERVED


def test_unverifiable_reservation_state_blocks_rollover(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)

    def unreadable():
        raise OSError("reservation store unreadable")

    monkeypatch.setattr(app.reservation_ledger, "reserved", unreadable)
    app.execution._auto_rollover_risk_accounting_day()

    assert _stored(state_dir).accounting_day_utc < _today()
    assert _rollover_events(state_dir) == []


def test_audit_disabled_blocks_rollover(tmp_path):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    app.execution.audit_enabled = False

    assert _risk_check(app)["reason"] == STALE_REASON
    assert _stored(state_dir).accounting_day_utc < _today()


def test_prepared_audit_failure_writes_nothing(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()

    def failing_append(**kwargs):
        raise OSError("audit disk full")

    monkeypatch.setattr(app.execution.audit_store, "append", failing_append)

    assert _risk_check(app)["reason"] == STALE_REASON
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == before


# ==========================================================================
# LIVE: no automatic path
# ==========================================================================


def test_live_mode_never_rolls_over(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    app.execution.mode = ExecutionManager.MODE_LIVE
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()
    gate_consulted = []
    monkeypatch.setattr(
        app.execution, "_risk_day_rollover_refusal", lambda: gate_consulted.append(1),
    )

    app.execution._auto_rollover_risk_accounting_day()
    result = _risk_check(app)

    assert result["approved"] is False
    assert result["reason"] == STALE_REASON
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == before
    assert _rollover_events(state_dir) == []
    # The branch is taken before the gate is even consulted.
    assert gate_consulted == []


def test_live_mode_constructed_manager_never_rolls_over(tmp_path):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir, start=False)
    manager = ExecutionManager(
        mode="LIVE",
        risk_engine=app.risk_engine,
        reservation_ledger=app.reservation_ledger,
        risk_state_store=app.risk_state_store,
        portfolio_foundation=app.portfolio_foundation,
        transaction_journal=app.transaction_journal,
        idempotency_store=app.idempotency_store,
        audit_store=app.audit_store,
    )
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()

    manager._auto_rollover_risk_accounting_day()

    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == before


# ==========================================================================
# idempotency: double fire and concurrent fire
# ==========================================================================


def test_second_rollover_on_the_same_day_is_a_no_op(tmp_path):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)

    app.execution._auto_rollover_risk_accounting_day()
    after_first = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()
    app.execution._auto_rollover_risk_accounting_day()
    _risk_check(app)

    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == after_first
    assert [event.event_type for event in _rollover_events(state_dir)] == [PREPARED, COMMITTED]


def test_concurrent_rollover_attempts_roll_exactly_once(tmp_path):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    barrier = threading.Barrier(8)
    errors: list[BaseException] = []

    def fire():
        try:
            barrier.wait()
            app.execution._auto_rollover_risk_accounting_day()
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=fire) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert [event.event_type for event in _rollover_events(state_dir)] == [PREPARED, COMMITTED]
    assert _stored(state_dir).accounting_day_utc == _today()


# ==========================================================================
# crash mid-rollover
# ==========================================================================


def test_crash_before_the_durable_replace_recovers_on_restart(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path, pnl="-40", peak="12000", current="10000")
    app = _app(state_dir)
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()

    import os

    original_replace = os.replace

    def crash_on_risk_state(source, destination):
        if Path(destination).name == RISK_ACCOUNTING_STATE_FILE:
            raise SimulatedCrash("os.replace")
        return original_replace(source, destination)

    monkeypatch.setattr("core.risk_state_store.os.replace", crash_on_risk_state)
    with pytest.raises(SimulatedCrash):
        _risk_check(app)
    monkeypatch.undo()

    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == before
    assert not (state_dir / (RISK_ACCOUNTING_STATE_FILE + ".tmp")).exists()

    restarted = _app(state_dir)
    # 12000 -> 10000 is a real drawdown; the verdict is the engine's own.
    assert _risk_check(restarted).get("reason") != STALE_REASON
    rolled = _stored(state_dir)
    assert rolled.accounting_day_utc == _today()
    assert rolled.realized_daily_pnl == D("0")
    assert rolled.peak_equity == D("12000")
    # PREPARED from the crashed attempt, then the completed pair.
    assert [event.event_type for event in _rollover_events(state_dir)] == [
        PREPARED, PREPARED, COMMITTED,
    ]


def test_write_failure_leaves_the_old_day_and_the_next_request_retries(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()
    original = JsonRiskStateStore.save
    calls = []

    def failing_once(self, value):
        calls.append(value)
        if len(calls) == 1:
            raise OSError("disk error")
        return original(self, value)

    monkeypatch.setattr(JsonRiskStateStore, "save", failing_once)

    assert _risk_check(app)["reason"] == STALE_REASON
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == before
    assert _risk_check(app, "rc2")["approved"] is True
    assert _stored(state_dir).accounting_day_utc == _today()


def test_crash_after_the_durable_replace_is_not_rolled_twice(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path, pnl="-40")
    app = _app(state_dir)
    original = JsonRiskStateStore.save

    def save_then_crash(self, value):
        original(self, value)
        raise SimulatedCrash("after save")

    monkeypatch.setattr(JsonRiskStateStore, "save", save_then_crash)
    with pytest.raises(SimulatedCrash):
        _risk_check(app)
    monkeypatch.undo()
    rolled_bytes = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()

    restarted = _app(state_dir)
    assert _risk_check(restarted)["approved"] is True

    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == rolled_bytes
    assert [event.event_type for event in _rollover_events(state_dir)] == [PREPARED]


# ==========================================================================
# multi-day gap
# ==========================================================================


def test_a_week_offline_rolls_straight_to_today_preserving_peak(tmp_path):
    state_dir = _stale_state(tmp_path, days_ago=7, pnl="-300", peak="15000", current="10000")
    app = _app(state_dir)

    # A 33% drawdown from the preserved peak: the engine now judges the
    # request on drawdown, never on the stale day.
    assert _risk_check(app)["reason"] == "DRAWDOWN_HALT_NEW_RISK"

    rolled = _stored(state_dir)
    assert rolled.accounting_day_utc == _today()
    assert rolled.realized_daily_pnl == D("0")
    assert rolled.peak_equity == D("15000")
    assert rolled.current_equity == D("10000")
    prepared = _rollover_events(state_dir)[0]
    assert prepared.payload["from_accounting_day_utc"] == (_today() - timedelta(days=7)).isoformat()


def test_future_stored_day_is_never_rolled_backwards(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    _write_risk_state(state_dir, day=_today() + timedelta(days=1))
    app = _app(state_dir)
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()

    result = _risk_check(app)

    assert result["approved"] is False
    assert result["reason"] == "RISK_STATE_RESTORATION_FAILED"
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == before


# ==========================================================================
# gate atomicity against a concurrent journal prepare (audit MEDIUM-1)
# ==========================================================================


def test_prepare_cannot_enter_while_a_rollover_is_writing(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    writing, release = threading.Event(), threading.Event()
    original = JsonRiskStateStore.rollover
    order: list[str] = []

    def slow_rollover(self, *args, **kwargs):
        writing.set()
        assert release.wait(5)
        result = original(self, *args, **kwargs)
        order.append("rollover")
        return result

    monkeypatch.setattr(JsonRiskStateStore, "rollover", slow_rollover)
    roller = threading.Thread(target=app.execution._auto_rollover_risk_accounting_day)
    roller.start()
    assert writing.wait(5)

    def prepare():
        app.transaction_journal.prepare("late", {"request_id": "late"})
        order.append("prepare")

    preparer = threading.Thread(target=prepare)
    preparer.start()
    preparer.join(0.3)
    # prepare() is held off by the journal lock the rollover owns.
    assert preparer.is_alive()
    assert order == []

    release.set()
    roller.join(5)
    preparer.join(5)
    assert order == ["rollover", "prepare"]
    assert _stored(state_dir).accounting_day_utc == _today()


def test_rollover_waits_for_a_prepare_holding_the_journal_and_then_refuses(tmp_path):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    journal = app.transaction_journal
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()

    journal._lock.acquire()
    try:
        roller = threading.Thread(target=app.execution._auto_rollover_risk_accounting_day)
        roller.start()
        roller.join(0.3)
        assert roller.is_alive()
        # The prepare lands while the rollover is blocked on the journal.
        assert journal.prepare("racing", {"request_id": "racing"})
    finally:
        journal._lock.release()
    roller.join(5)

    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == before
    assert _rollover_events(state_dir) == []


def test_missing_journal_lock_refuses_rather_than_substituting_one(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    monkeypatch.setattr(app.transaction_journal, "_lock", None)

    app.execution._auto_rollover_risk_accounting_day()

    assert _stored(state_dir).accounting_day_utc < _today()
    assert _rollover_events(state_dir) == []


# ==========================================================================
# remaining fail-closed branches (audit MEDIUM-2, LOW-1)
# ==========================================================================


def _assert_untouched(state_dir: Path, before: bytes) -> None:
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == before
    assert _rollover_events(state_dir) == []


def test_unloaded_journal_refuses(tmp_path, monkeypatch, caplog):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()
    monkeypatch.setattr(app.transaction_journal, "load_failed", True)

    with caplog.at_level("WARNING", logger=execution_manager_module.logger.name):
        app.execution._auto_rollover_risk_accounting_day()

    _assert_untouched(state_dir, before)
    assert any("reason=JOURNAL_NOT_LOADED" in r.getMessage() for r in caplog.records)


def test_equity_authority_not_ready_refuses(tmp_path, monkeypatch, caplog):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()
    monkeypatch.setattr(app.execution, "portfolio_foundation", None)

    with caplog.at_level("WARNING", logger=execution_manager_module.logger.name):
        app.execution._auto_rollover_risk_accounting_day()

    _assert_untouched(state_dir, before)
    assert any("reason=EQUITY_AUTHORITY_NOT_READY" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("equity", ["0", "-5", "NaN", "Infinity"])
def test_non_positive_or_non_finite_equity_aborts_before_any_write(tmp_path, monkeypatch, equity):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()
    foundation = app.portfolio_foundation
    real = foundation.snapshot
    monkeypatch.setattr(foundation, "snapshot", lambda **kw: {**real(**kw), "equity": D(equity)})

    app.execution._auto_rollover_risk_accounting_day()

    _assert_untouched(state_dir, before)


def test_snapshot_failure_aborts_before_any_write(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()

    def broken(**kwargs):
        raise RuntimeError("book unreadable")

    monkeypatch.setattr(app.portfolio_foundation, "snapshot", broken)

    assert _risk_check(app)["approved"] is False
    _assert_untouched(state_dir, before)


def test_committed_audit_failure_keeps_the_rollover_and_degrades_audit(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    store = app.execution.audit_store
    original = store.append

    def fail_committed(**kwargs):
        if kwargs["event_type"] == COMMITTED:
            raise OSError("audit disk full")
        return original(**kwargs)

    monkeypatch.setattr(store, "append", fail_committed)
    failures_before = app.execution.stats["audit_write_failures"]

    app.execution._auto_rollover_risk_accounting_day()

    assert _stored(state_dir).accounting_day_utc == _today()
    assert [event.event_type for event in _rollover_events(state_dir)] == [PREPARED]
    assert app.execution.stats["audit_write_failures"] == failures_before + 1
    assert app.execution.audit_runtime_state == "AUDIT_DEGRADED"
    assert app.execution.last_audit_failure["event_type"] == COMMITTED
