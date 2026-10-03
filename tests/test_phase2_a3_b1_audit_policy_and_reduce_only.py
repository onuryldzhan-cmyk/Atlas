"""Phase-2 A3 (audit failure policy) and B1 (reduce-only exit safety).

Every test runs a real AtlasApplication on its own tmp_path state. Audit
faults are injected by failing ``os.fsync`` only while the targeted audit
event is being appended; everything else is real file I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from core import durable_append_contract as contract
from core.application import EXECUTION_AUDIT_EVENT_FILE
from core.audit_event_store import AuditEventStore, AuditRecoveryRequiredError
from core.durable_append_contract import DurableAppendWriter
from core.execution_models import ExecutionRequest
from core.risk_engine import RiskEngine, RiskRequest
from tests.test_block2_risk_service_composition_wiring import seed_valid_state
from tests.test_execution_crash_recovery_f1_f6 import _buy, _full_exit_sell, _risk_state
from tests.test_risk_accounting_day_auto_rollover import _app, _stale_state

D = Decimal


@pytest.fixture(autouse=True)
def _isolated_roots(monkeypatch):
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)


def _fresh(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    return state_dir, _app(state_dir)


def _fail_audit_at(monkeypatch, app, event_type: str, fsync_failures: int) -> None:
    """Fail fsync ``fsync_failures`` times while ``event_type`` is appended.

    1 failure -> rolled back (NOT_WRITTEN); 2 -> INDETERMINATE (poisoned).
    """
    store = app.execution.audit_store
    original = store.append
    real_fsync = contract.os.fsync
    armed = {"done": False}

    def append(**kwargs):
        if kwargs.get("event_type") != event_type or armed["done"]:
            return original(**kwargs)
        armed["done"] = True
        remaining = {"n": fsync_failures}

        def fsync(fd):
            if remaining["n"] > 0:
                remaining["n"] -= 1
                raise OSError(5, "injected EIO")
            real_fsync(fd)

        monkeypatch.setattr(contract.os, "fsync", fsync)
        try:
            return original(**kwargs)
        finally:
            monkeypatch.setattr(contract.os, "fsync", real_fsync)

    monkeypatch.setattr(store, "append", append)


def _audit_chain_is_linear(state_dir) -> bool:
    path = state_dir / EXECUTION_AUDIT_EVENT_FILE
    DurableAppendWriter(path).acknowledge_recovery()  # inspection only
    return AuditEventStore(path).verify_chain()["valid"]


# ======================================================================= A3


@pytest.mark.parametrize(
    "stage",
    ["EXECUTION_REQUEST_RECEIVED", "EXECUTION_REQUEST_VALIDATED"],
)
def test_pre_execution_indeterminate_audit_blocks_the_buy(tmp_path, monkeypatch, stage):
    state_dir, app = _fresh(tmp_path)
    _fail_audit_at(monkeypatch, app, stage, 2)

    result = _buy(app)

    assert result["status"] != "PAPER_EXECUTED"
    assert result.get("error_code", result.get("reason")) == "AUDIT_PERSISTENCE_RECOVERY_REQUIRED" \
        or "AUDIT_PERSISTENCE_RECOVERY_REQUIRED" in str(result)
    assert app.portfolio_foundation.snapshot()["positions"] == {}
    assert app.execution.audit_persistence_state() == "RECOVERY_REQUIRED"
    assert _audit_chain_is_linear(state_dir)


def test_risk_approved_audit_failure_is_reported_beside_a_known_outcome(tmp_path, monkeypatch):
    state_dir, app = _fresh(tmp_path)
    _fail_audit_at(monkeypatch, app, "RISK_APPROVED", 2)

    result = _buy(app)

    # The pre-existing fail-closed path (no RISK_APPROVED record -> no
    # execution) still decides; whichever way it decides, the audit state is
    # reported and never hidden.
    assert result["audit_persistence_state"] == "RECOVERY_REQUIRED"
    assert _audit_chain_is_linear(state_dir)


def test_completed_audit_failure_keeps_the_execution_and_blocks_new_risk(tmp_path, monkeypatch):
    state_dir, app = _fresh(tmp_path)
    _fail_audit_at(monkeypatch, app, "EXECUTION_COMPLETED", 2)

    first = _buy(app, "r1")
    # A1b: r2 = COMMITTED, audit = DEGRADED, r3 = COMMITTED, hash fork.
    assert first["status"] == "PAPER_EXECUTED"
    assert first["audit_persistence_state"] == "RECOVERY_REQUIRED"
    assert "BTCUSDT" in app.portfolio_foundation.snapshot()["positions"]

    second = _buy(app, "r2")
    assert second["status"] != "PAPER_EXECUTED"
    assert "AUDIT_PERSISTENCE_RECOVERY_REQUIRED" in str(second)

    health = app.execution.health()
    assert health["healthy"] is False
    assert health["operational_state"]["audit_persistence_state"] == "RECOVERY_REQUIRED"
    assert _audit_chain_is_linear(state_dir)


def test_reduce_only_exit_still_executes_with_audit_degraded(tmp_path, monkeypatch):
    state_dir, app = _fresh(tmp_path)
    assert _buy(app, "r1")["status"] == "PAPER_EXECUTED"
    _fail_audit_at(monkeypatch, app, "EXECUTION_REQUEST_RECEIVED", 1)
    blocked = _buy(app, "r2")
    assert "AUDIT_PERSISTENCE_DEGRADED" in str(blocked)

    exit_result = _full_exit_sell(app, "s1")

    assert exit_result["status"] == "PAPER_EXECUTED", exit_result
    assert app.portfolio_foundation.snapshot()["positions"] == {}


def test_restart_after_indeterminate_audit_is_recovery_not_a_fork(tmp_path, monkeypatch):
    state_dir, app = _fresh(tmp_path)
    _fail_audit_at(monkeypatch, app, "EXECUTION_COMPLETED", 2)
    assert _buy(app)["status"] == "PAPER_EXECUTED"

    with pytest.raises(AuditRecoveryRequiredError):
        _app(state_dir)


def test_restart_after_rolled_back_audit_fault_is_clean(tmp_path, monkeypatch):
    state_dir, app = _fresh(tmp_path)
    _fail_audit_at(monkeypatch, app, "EXECUTION_REQUEST_VALIDATED", 1)
    _buy(app, "r1")
    assert app.execution.audit_persistence_state() == "DEGRADED"

    restarted = _app(state_dir)
    assert restarted.execution.audit_persistence_state() == "HEALTHY"
    assert restarted.execution.audit_store.verify_chain()["valid"]


# ======================================================================= B1


def _engine_request(**overrides) -> RiskRequest:
    fields = dict(
        symbol="BTCUSDT", action="SELL", confidence=D("0"),
        requested_quote_allocation=D("100"), execution_price=D("10"),
        risk_bucket="HIGH", reduce_only=True,
    )
    fields.update(overrides)
    return RiskRequest(**fields)


@pytest.fixture
def engine_and_state(tmp_path):
    state_dir, app = _fresh(tmp_path)
    from core.risk_engine import PositionExposure

    held = PositionExposure("BTCUSDT", D("10"), D("10"), D("100"))
    return app.risk_engine, _risk_state(held)


def _replace(state, **changes):
    from dataclasses import replace

    return replace(state, **changes)


def test_reduce_only_sell_refused_cleanly_on_policy_mismatch(engine_and_state):
    """Durable-state-unknown for the realized-P&L booking: a clean refusal
    beats a committed exit that cannot be booked (see RiskEngine.evaluate)."""
    engine, state = engine_and_state
    decision = engine.evaluate(_engine_request(), _replace(state, policy_version="other"))
    assert decision.reason_code == "RISK_POLICY_STATE_MISMATCH"


def test_reduce_only_sell_ignores_confidence(engine_and_state):
    engine, state = engine_and_state
    decision = engine.evaluate(_engine_request(confidence=D("5")), state)  # malformed > 1
    assert decision.status.value == "APPROVE"


def test_reduce_only_sell_passes_drawdown_halt(engine_and_state):
    engine, state = engine_and_state
    deep = _replace(state, current_equity=D("1"))
    assert engine.evaluate(_engine_request(), deep).status.value == "APPROVE"
    buy = engine.evaluate(_engine_request(action="BUY", reduce_only=False, confidence=D("0.99")), deep)
    assert buy.status.value != "APPROVE"


def test_reduce_only_sell_still_refused_for_invalid_quantity(engine_and_state):
    engine, state = engine_and_state
    oversized = engine.evaluate(_engine_request(requested_quote_allocation=D("1000")), state)
    assert oversized.reason_code == "INVALID_RISK_REDUCTION"
    malformed = engine.evaluate(_engine_request(execution_price=D("0")), state)
    assert malformed.reason_code == "INVALID_FINANCIAL_INPUT"


def test_reduce_only_sell_still_refused_when_durable_state_unknown(engine_and_state):
    engine, state = engine_and_state
    decision = engine.evaluate(_engine_request(), _replace(state, state_ready=False))
    assert decision.reason_code == "RISK_STATE_NOT_READY"


def test_low_confidence_sell_exits_end_to_end(tmp_path):
    state_dir, app = _fresh(tmp_path)
    assert _buy(app)["status"] == "PAPER_EXECUTED"
    position = app.portfolio_foundation.snapshot()["positions"]["BTCUSDT"]
    exposure = D(position["base_quantity"]) * D(position["mark_price"])
    from core.risk_engine import PositionExposure

    decision = ExecutionRequest(
        "BTCUSDT", "SELL", 10, format(exposure, "f"), confidence=10, risk="HIGH",
        request_id="s-low", reduce_only=True,
    ).to_dict()
    result = app.execution.execute(
        decision,
        _risk_state(PositionExposure("BTCUSDT", D(position["base_quantity"]),
                                     D(position["mark_price"]), exposure)),
    )
    assert result["status"] == "PAPER_EXECUTED", result


def test_low_confidence_buy_is_still_refused(tmp_path):
    state_dir, app = _fresh(tmp_path)
    decision = ExecutionRequest(
        "BTCUSDT", "BUY", 10, "100", confidence=10, risk="HIGH", request_id="b-low",
    ).to_dict()
    result = app.execution.execute(decision, _risk_state())
    assert result["status"] != "PAPER_EXECUTED"
    assert "LOW_CONFIDENCE" in str(result)


def test_stale_accounting_day_is_rolled_and_the_exit_executes(tmp_path):
    state_dir = _stale_state(tmp_path, held=("BTCUSDT", "10", "10"))
    app = _app(state_dir)

    result = _full_exit_sell(app, "s-stale")

    assert result["status"] == "PAPER_EXECUTED", result


def test_unrollable_stale_day_refuses_the_exit_cleanly(tmp_path):
    """Refused before anything executes - never committed-then-halted."""
    state_dir = _stale_state(tmp_path, held=("BTCUSDT", "10", "10"))
    app = _app(state_dir)
    app.execution._auto_rollover_risk_accounting_day = lambda: None

    result = _full_exit_sell(app, "s-stale")

    assert result["status"] != "PAPER_EXECUTED"
    assert "RISK_ACCOUNTING_DAY_RECONCILIATION_REQUIRED" in str(result)
    assert "BTCUSDT" in app.portfolio_foundation.snapshot()["positions"]
    assert app.execution.recovery_required is False
