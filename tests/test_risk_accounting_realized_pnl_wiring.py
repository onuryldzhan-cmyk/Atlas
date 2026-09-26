"""Realized P&L and equity wired into durable risk accounting (PAPER).

Before this, nothing in production ever changed ``realized_daily_pnl`` in the
risk-accounting store, and ``current_equity``/``peak_equity`` were refreshed
only at bootstrap and at the day rollover. RiskEngine's daily-loss limit and
drawdown ladder therefore read figures that never moved.

``ExecutionManager._finalize_durable_financial_state`` now folds each
committed SELL's realized P&L - derived only from
ExecutionPortfolioFoundation's own snapshots either side of the commit - into
the store, and refreshes equity from the post-commit snapshot, under the same
manager + journal locks and PREPARED/COMMITTED audit discipline as the day
rollover. The rollover gate also refuses while the runtime is halted (LOW-3).

Every test runs against its own ``tmp_path`` state directory and the policy
``AtlasApplication`` actually configures - no threshold is overridden.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import core.execution_manager as execution_manager_module
from core.application import (
    EXECUTION_AUDIT_EVENT_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    RISK_ACCOUNTING_STATE_FILE,
    AtlasApplication,
)
from core.audit_event_store import AuditEventStore
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from core.execution_portfolio_foundation import FinancialStateStore
from core.risk_engine import PositionExposure
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState

from tests.test_block2_risk_service_composition_wiring import (
    POLICY_VERSION,
    high_bucket_allocation,
    seed_valid_state,
)
from tests.test_execution_crash_recovery_f1_f6 import _buy, _risk_state

D = Decimal

PNL_PREPARED = ExecutionManager.RISK_REALIZED_PNL_PREPARED
PNL_COMMITTED = ExecutionManager.RISK_REALIZED_PNL_COMMITTED
ROLL_PREPARED = ExecutionManager.RISK_DAY_ROLLOVER_PREPARED
ROLL_COMMITTED = ExecutionManager.RISK_DAY_ROLLOVER_COMMITTED
STALE_REASON = "RISK_ACCOUNTING_DAY_RECONCILIATION_REQUIRED"


@pytest.fixture(autouse=True)
def _isolated_roots(monkeypatch):
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _today() -> date:
    return datetime.now(UTC).date()


def _risk_store(state_dir: Path) -> JsonRiskStateStore:
    return JsonRiskStateStore(state_dir / RISK_ACCOUNTING_STATE_FILE)


def _stored(state_dir: Path, today: date | None = None) -> RestoredRiskState:
    return _risk_store(state_dir).load(
        expected_policy_version=POLICY_VERSION, today_utc=today or _today(),
    )


def _write_risk_state(state_dir: Path, *, day: date | None = None, pnl="0",
                      peak="10000", current="10000") -> None:
    _risk_store(state_dir).save(
        RestoredRiskState(day or _today(), D(pnl), D(peak), D(current), POLICY_VERSION)
    )


def _state(tmp_path: Path, *, base="100", mark="10", entry=None, cash="9000") -> Path:
    """A durable book holding ``base`` BTCUSDT marked at ``mark``.

    By default 9000 cash + 100 x 10 = 10000 equity, matching the seeded
    risk-accounting peak and current equity.

    ``entry`` sets the average entry price (cost basis) when it differs from
    the mark, so a sale at the mark realizes a gain or a loss.
    """
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir, held=("BTCUSDT", base, mark))
    store = FinancialStateStore(state_dir / EXECUTION_FINANCIAL_STATE_FILE)
    payload = store.load()
    payload["cash"] = cash
    if entry is not None:
        position = payload["positions"]["BTCUSDT"]
        position["cost_quote"] = format(D(base) * D(entry), "f")
        position["average_entry_price"] = entry
    store.save(payload)
    return state_dir


def _app(state_dir: Path) -> AtlasApplication:
    app = AtlasApplication(
        state_directory=state_dir, evidence_directory=state_dir.parent / "evidence",
    )
    app.execution.start()
    return app


def _sell(app: AtlasApplication, *, base, price, request_id: str) -> dict:
    """A reduce-only SELL of ``base`` BTCUSDT filled at ``price``.

    The approved reduction is sized at the durable mark, which is how the
    paper SELL converts it back into base units; ``price`` is the fill.
    """
    position = app.portfolio_foundation.snapshot()["positions"]["BTCUSDT"]
    exposure = D(position["base_quantity"]) * D(position["mark_price"])
    decision = ExecutionRequest(
        "BTCUSDT", "SELL", float(price),
        format(D(str(base)) * D(position["mark_price"]), "f"),
        confidence=90, risk="HIGH", request_id=request_id, reduce_only=True,
    ).to_dict()
    return app.execution.execute(
        decision,
        _risk_state(PositionExposure("BTCUSDT", D(position["base_quantity"]),
                                     D(position["mark_price"]), exposure)),
    )


def _buy_check(app: AtlasApplication, request_id: str, symbol: str = "ETHUSDT") -> dict:
    """Risk-check a new-risk BUY without executing it or keeping capital."""
    request = ExecutionRequest(
        symbol, "BUY", 10, str(high_bucket_allocation(app)),
        confidence=90, risk="HIGH", request_id=request_id,
    )
    result = app.execution.risk_check(request)
    if result.get("approved"):
        app.execution._release_capital_reservation(request.request_id)
    return result


def _events(state_dir: Path, *types: str) -> list:
    return [
        event
        for event in AuditEventStore(state_dir / EXECUTION_AUDIT_EVENT_FILE).read_all()
        if event.event_type in set(types)
    ]


def _net(app: AtlasApplication) -> Decimal:
    return app.portfolio_foundation.snapshot()["realized_net_pnl"]


# ==========================================================================
# LOW-3: the rollover gate refuses while the runtime is halted
# ==========================================================================


@pytest.mark.parametrize(
    ("halted", "recovery", "reason"),
    [
        (True, False, "EXECUTION_HALTED"),
        (False, True, "RECOVERY_REQUIRED"),
        (True, True, "EXECUTION_HALTED"),
    ],
)
def test_halted_runtime_refuses_rollover_like_any_dirty_state(tmp_path, caplog, halted,
                                                              recovery, reason):
    state_dir = _state(tmp_path)
    _write_risk_state(state_dir, day=_today() - timedelta(days=1), pnl="-25")
    app = _app(state_dir)
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()
    app.execution.execution_halted = halted
    app.execution.recovery_required = recovery

    with caplog.at_level("WARNING", logger=execution_manager_module.logger.name):
        result = _buy_check(app, "rc-halted")

    assert result["approved"] is False
    assert result["reason"] == STALE_REASON
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == before
    assert _events(state_dir, ROLL_PREPARED, ROLL_COMMITTED) == []
    assert any(
        record.levelname == "WARNING"
        and "rollover REFUSED" in record.getMessage()
        and f"reason={reason}" in record.getMessage()
        for record in caplog.records
    )
    assert app.execution._risk_day_rollover_refusal() == reason


def test_rollover_proceeds_once_the_halt_is_cleared(tmp_path):
    """The refusal is caused by the flags themselves, nothing else."""
    state_dir = _state(tmp_path)
    _write_risk_state(state_dir, day=_today() - timedelta(days=1))
    app = _app(state_dir)
    app.execution.execution_halted = True
    _buy_check(app, "rc-halted")
    assert _stored(state_dir).accounting_day_utc < _today()

    app.execution.execution_halted = False
    _buy_check(app, "rc-clear")

    assert _stored(state_dir).accounting_day_utc == _today()
    assert [e.event_type for e in _events(state_dir, ROLL_PREPARED, ROLL_COMMITTED)] == [
        ROLL_PREPARED, ROLL_COMMITTED,
    ]


# ==========================================================================
# realized P&L accumulation
# ==========================================================================


def test_full_exit_loss_is_recorded_from_the_foundation(tmp_path):
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    before = app.portfolio_foundation.snapshot()

    result = _sell(app, base="100", price="9", request_id="s1")

    assert result["status"] == "PAPER_EXECUTED", result
    after = app.portfolio_foundation.snapshot()
    stored = _stored(state_dir)
    expected = (after["realized_gross_pnl"] - before["realized_gross_pnl"]) - (
        after["fees"] - before["fees"]
    )  # seeded entry fees are zero
    assert expected <= D("-100")  # a 1.00 drop on 100 units, plus any exit fee
    assert stored.realized_daily_pnl == expected
    assert stored.current_equity == after["equity"]
    assert stored.peak_equity == D("10000")
    assert app.execution.execution_halted is False


def test_multiple_closes_in_one_day_accumulate(tmp_path):
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    start = app.portfolio_foundation.snapshot()

    assert _sell(app, base="40", price="9", request_id="s1")["status"] == "PAPER_EXECUTED"
    first = _stored(state_dir).realized_daily_pnl
    assert _sell(app, base="60", price="8", request_id="s2")["status"] == "PAPER_EXECUTED"
    end = app.portfolio_foundation.snapshot()

    total = _stored(state_dir).realized_daily_pnl
    assert first < 0 and total < first
    # The whole position is gone, so the day's total is exactly the book's
    # own net realized change over the round trip.
    assert "BTCUSDT" not in end["positions"]
    assert total == end["realized_net_pnl"] - start["realized_net_pnl"]
    assert _stored(state_dir).current_equity == end["equity"]
    assert len(_events(state_dir, PNL_PREPARED)) == 2
    assert len(_events(state_dir, PNL_COMMITTED)) == 2


def test_round_trip_from_a_real_buy_charges_its_entry_fee_at_the_exit(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = _app(state_dir)
    start_net = _net(app)
    assert _buy(app)["status"] == "PAPER_EXECUTED"
    # A BUY realizes nothing.
    assert _stored(state_dir).realized_daily_pnl == D("0")
    base = app.portfolio_foundation.snapshot()["positions"]["BTCUSDT"]["base_quantity"]

    assert _sell(app, base=base, price="10", request_id="s1")["status"] == "PAPER_EXECUTED"

    assert _stored(state_dir).realized_daily_pnl == _net(app) - start_net


def test_partial_reduction_charges_only_the_released_entry_fees(tmp_path):
    state_dir = _state(tmp_path)
    store = FinancialStateStore(state_dir / EXECUTION_FINANCIAL_STATE_FILE)
    payload = store.load()
    payload["positions"]["BTCUSDT"]["entry_fees"] = "4"
    store.save(payload)
    app = _app(state_dir)
    before = app.portfolio_foundation.snapshot()

    assert _sell(app, base="25", price="10", request_id="s1")["status"] == "PAPER_EXECUTED"

    after = app.portfolio_foundation.snapshot()
    exit_fee = after["fees"] - before["fees"]
    # Sold at cost: no gross result, a quarter of the entry fees released.
    assert after["realized_gross_pnl"] == before["realized_gross_pnl"]
    assert D(after["positions"]["BTCUSDT"]["entry_fees"]) == D("3")
    assert _stored(state_dir).realized_daily_pnl == -exit_fee - D("1")
    prepared = _events(state_dir, PNL_PREPARED)[0]
    assert prepared.payload["position_closed"] is False
    assert D(prepared.payload["components"]["released_entry_fees"]) == D("1")


def test_prepared_then_committed_audit_pair_carries_the_inputs(tmp_path):
    state_dir = _state(tmp_path)
    app = _app(state_dir)

    _sell(app, base="100", price="9", request_id="s1")

    prepared, committed = _events(state_dir, PNL_PREPARED, PNL_COMMITTED)
    assert prepared.event_type == PNL_PREPARED and committed.event_type == PNL_COMMITTED
    assert committed.causation_id == prepared.event_id
    assert prepared.correlation_id == "s1"
    assert prepared.payload["figures_source"] == "ExecutionPortfolioFoundation"
    assert prepared.payload["position_closed"] is True
    assert prepared.payload["previous_state"]["realized_daily_pnl"] == "0"
    assert committed.payload["new_state"] == _stored(state_dir).to_dict()


def test_replayed_execution_is_never_counted_twice(tmp_path):
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    _sell(app, base="100", price="9", request_id="s1")
    recorded = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()

    _sell_replay(app, "s1")

    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == recorded
    assert len(_events(state_dir, PNL_PREPARED)) == 1


def _sell_replay(app: AtlasApplication, request_id: str) -> dict:
    decision = ExecutionRequest(
        "BTCUSDT", "SELL", 9.0, "900", confidence=90, risk="HIGH",
        request_id=request_id, reduce_only=True,
    ).to_dict()
    return app.execution.execute(decision, _risk_state())


def test_buy_leaves_risk_accounting_untouched(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = _app(state_dir)
    recorded = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()

    assert _buy(app)["status"] == "PAPER_EXECUTED"

    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == recorded
    assert _events(state_dir, PNL_PREPARED, PNL_COMMITTED) == []


# ==========================================================================
# next-day reset and peak equity
# ==========================================================================


def test_next_day_rollover_resets_the_accumulated_loss(tmp_path, monkeypatch):
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    _sell(app, base="50", price="9", request_id="s1")
    today_state = _stored(state_dir)
    assert today_state.realized_daily_pnl < 0

    tomorrow = datetime.now(UTC).replace(hour=0, minute=0, second=1, microsecond=0) + timedelta(days=1)
    _advance_clock(monkeypatch, tomorrow)
    _buy_check(app, "rc-next-day")

    rolled = _stored(state_dir, tomorrow.date())
    assert rolled.accounting_day_utc == tomorrow.date()
    assert rolled.realized_daily_pnl == D("0")
    assert rolled.peak_equity == today_state.peak_equity
    assert rolled.current_equity == app.portfolio_foundation.snapshot()["equity"]

    # The next day's closes accumulate from zero, not from yesterday.
    net_before = _net(app)
    _sell(app, base="50", price="9", request_id="s2")
    assert _stored(state_dir, tomorrow.date()).realized_daily_pnl == _net(app) - net_before < 0


def _advance_clock(monkeypatch, moment: datetime) -> None:
    import core.risk_engine as risk_engine_module

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment if tz is None else moment.astimezone(tz)

    monkeypatch.setattr(execution_manager_module, "datetime", _Clock)
    monkeypatch.setattr(risk_engine_module, "datetime", _Clock)


def test_profitable_exit_raises_peak_to_the_new_equity(tmp_path):
    # Bought at 8, marked and sold at 10: equity 10000 + 1000 before the sale.
    state_dir = _state(tmp_path, entry="8", cash="10000")
    app = _app(state_dir)

    assert _sell(app, base="100", price="10", request_id="s1")["status"] == "PAPER_EXECUTED"

    stored = _stored(state_dir)
    equity = app.portfolio_foundation.snapshot()["equity"]
    assert stored.realized_daily_pnl > D("190")
    assert stored.current_equity == equity > D("10000")
    assert stored.peak_equity == equity


def test_losing_exit_never_lowers_the_peak(tmp_path):
    state_dir = _state(tmp_path)
    _write_risk_state(state_dir, peak="12000", current="11000")
    app = _app(state_dir)

    _sell(app, base="100", price="9", request_id="s1")

    stored = _stored(state_dir)
    assert stored.peak_equity == D("12000")
    assert stored.current_equity == app.portfolio_foundation.snapshot()["equity"] < D("11000")


# ==========================================================================
# the configured thresholds actually fire
# ==========================================================================


def test_configured_thresholds_are_the_ones_under_test(tmp_path):
    app = _app(_state(tmp_path))
    policy = app.risk_policy
    assert policy.total_capital == D("10000")
    assert policy.max_daily_loss_pct == D("0.05")
    assert policy.max_daily_loss_amount is None
    assert policy.drawdown_restrict_pct == D("0.10")
    assert policy.drawdown_halt_pct == D("0.15")


def test_realized_loss_below_the_daily_limit_does_not_block(tmp_path):
    # 100 units bought at 10, sold at 5.5: -450 gross, under the 500 ceiling.
    state_dir = _state(tmp_path)
    app = _app(state_dir)

    _sell(app, base="100", price="5.5", request_id="s1")

    loss = -_stored(state_dir).realized_daily_pnl
    assert D("450") <= loss < D("500")
    assert _buy_check(app, "after")["approved"] is True


def test_crossing_the_daily_loss_limit_rejects_new_risk_safely(tmp_path):
    # 100 units bought at 10, sold at 4.9: -510 gross, over the 500 ceiling.
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    assert _buy_check(app, "before")["approved"] is True

    result = _sell(app, base="100", price="4.9", request_id="s1")

    assert result["status"] == "PAPER_EXECUTED", result
    stored = _stored(state_dir)
    assert -stored.realized_daily_pnl >= app.risk_policy.total_capital * app.risk_policy.max_daily_loss_pct
    rejected = _buy_check(app, "after")
    assert rejected["approved"] is False
    assert rejected["reason"] == "DAILY_LOSS_LIMIT_BREACHED"
    # A rejection of new risk, not a runtime halt, and nothing was mutated
    # by evaluating it: a second attempt sees exactly the same state.
    assert app.execution.execution_halted is False
    assert app.execution.recovery_required is False
    recorded = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()
    assert _buy_check(app, "again")["reason"] == "DAILY_LOSS_LIMIT_BREACHED"
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == recorded
    assert _stored(state_dir) == stored


def test_crossing_into_drawdown_halt_fires_drawdown_halt_new_risk(tmp_path):
    """Prior days left the book 14% below its peak (RESTRICT). Today's realized
    loss of 450 - under the 500 daily ceiling - takes it past 15%, and the
    recorded equity is what moves RiskEngine from RESTRICT to HALT_NEW_RISK.
    """
    # 7600 cash + 100 units marked at 10 = 8600 equity against a 10000 peak.
    state_dir = _state(tmp_path, cash="7600")
    _write_risk_state(state_dir, peak="10000", current="8600")
    app = _app(state_dir)
    assert _buy_check(app, "before")["reason"] == "DRAWDOWN_RESTRICT_NEW_RISK"

    result = _sell(app, base="100", price="5.5", request_id="s1")

    assert result["status"] == "PAPER_EXECUTED", result
    stored = _stored(state_dir)
    assert -stored.realized_daily_pnl < D("500")
    assert stored.current_equity == app.portfolio_foundation.snapshot()["equity"]
    assert (stored.peak_equity - stored.current_equity) / stored.peak_equity >= D("0.15")
    rejected = _buy_check(app, "after")
    assert rejected["approved"] is False
    assert rejected["reason"] == "DRAWDOWN_HALT_NEW_RISK"
    assert app.execution.execution_halted is False
    assert app.execution.recovery_required is False
    assert _buy_check(app, "again")["reason"] == "DRAWDOWN_HALT_NEW_RISK"


def test_exits_stay_possible_after_the_limits_fire(tmp_path):
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    _sell(app, base="60", price="1.5", request_id="s1")  # -510 gross
    assert _buy_check(app, "after")["reason"] == "DAILY_LOSS_LIMIT_BREACHED"

    result = _sell(app, base="40", price="1.5", request_id="s2")

    assert result["status"] == "PAPER_EXECUTED", result
    assert "BTCUSDT" not in app.portfolio_foundation.snapshot()["positions"]
    assert app.execution.execution_halted is False


def test_limit_state_survives_restart(tmp_path):
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    _sell(app, base="100", price="4.9", request_id="s1")
    app.execution.stop()

    restarted = _app(state_dir)

    assert _buy_check(restarted, "after-restart")["reason"] == "DAILY_LOSS_LIMIT_BREACHED"


# ==========================================================================
# failure handling: the trade stands, the request resolves durably unknown
# ==========================================================================


def _assert_durable_finalization_failure(app: AtlasApplication, result: dict) -> None:
    # The trade is committed in the durable book...
    assert "BTCUSDT" not in app.portfolio_foundation.snapshot()["positions"]
    # ...but the request is not reported as a clean success: it resolves
    # through the post-apply finalization-failure path, leaving the journal
    # entry unresolved on disk and the runtime halted.
    assert result["status"] == "COMMIT_STATUS_UNKNOWN", result
    assert result["error_code"] == "DURABLE_FINANCIAL_FINALIZATION_FAILED"
    assert result["recovery_required"] is True
    assert app.transaction_journal.has_unresolved()
    assert app.execution.execution_halted is True
    assert app.execution.recovery_required is True
    assert app.execution.halt_reason == "DURABLE_FINANCIAL_FINALIZATION_FAILED"


def test_risk_store_write_failure_resolves_durably_and_halts(tmp_path, monkeypatch):
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    recorded = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()

    def failing_save(self, value):
        raise OSError("disk full")

    monkeypatch.setattr(JsonRiskStateStore, "save", failing_save)
    result = _sell(app, base="100", price="9", request_id="s1")

    _assert_durable_finalization_failure(app, result)
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == recorded
    monkeypatch.undo()
    refused = app.execution.execute(
        ExecutionRequest("BTCUSDT", "BUY", 10, "100", confidence=90, risk="HIGH",
                         request_id="next").to_dict(),
        _risk_state(),
    )
    assert refused.get("status") != "PAPER_EXECUTED"


def test_unrecorded_loss_never_silently_resumes_after_restart(tmp_path, monkeypatch):
    """Audit HIGH-1: the halt must survive a restart, not just this process."""
    state_dir = _state(tmp_path)
    app = _app(state_dir)

    def failing_save(self, value):
        raise OSError("disk full")

    monkeypatch.setattr(JsonRiskStateStore, "save", failing_save)
    _sell(app, base="100", price="4.9", request_id="s1")  # -510: over the limit
    monkeypatch.undo()
    app.execution.stop()
    assert _stored(state_dir).realized_daily_pnl == D("0")  # the loss is unrecorded

    restarted = _app(state_dir)

    assert restarted.execution.execution_halted is True
    assert restarted.execution.recovery_required is True
    refused = restarted.execution.execute(
        ExecutionRequest("ETHUSDT", "BUY", 10, str(high_bucket_allocation(restarted)),
                         confidence=90, risk="HIGH", request_id="after-restart").to_dict(),
        _risk_state(),
    )
    assert refused.get("status") != "PAPER_EXECUTED"
    assert refused.get("success") is not True


def test_prepared_audit_failure_writes_nothing_and_resolves_durably(tmp_path, monkeypatch):
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    recorded = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()
    original = app.execution.audit_store.append

    def failing_prepared(**kwargs):
        if kwargs["event_type"] == PNL_PREPARED:
            raise OSError("audit unavailable")
        return original(**kwargs)

    monkeypatch.setattr(app.execution.audit_store, "append", failing_prepared)
    result = _sell(app, base="100", price="9", request_id="s1")

    _assert_durable_finalization_failure(app, result)
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == recorded


def test_committed_audit_failure_keeps_the_update_and_degrades_audit(tmp_path, monkeypatch):
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    original = app.execution.audit_store.append

    def failing_committed(**kwargs):
        if kwargs["event_type"] == PNL_COMMITTED:
            raise OSError("audit unavailable")
        return original(**kwargs)

    monkeypatch.setattr(app.execution.audit_store, "append", failing_committed)
    result = _sell(app, base="100", price="9", request_id="s1")

    assert result["status"] == "PAPER_EXECUTED", result
    assert _stored(state_dir).realized_daily_pnl < 0
    assert app.execution.execution_halted is False
    assert app.execution.stats["audit_write_failures"] >= 1


def test_midnight_between_admission_and_commit_is_not_booked_to_yesterday(tmp_path, monkeypatch):
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    recorded = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()
    original = app.execution._finalize_durable_financial_state
    tomorrow = datetime.now(UTC) + timedelta(days=1)

    def finalize_after_midnight(**kwargs):
        _advance_clock(monkeypatch, tomorrow)
        return original(**kwargs)

    monkeypatch.setattr(app.execution, "_finalize_durable_financial_state",
                        finalize_after_midnight)
    result = _sell(app, base="100", price="9", request_id="s1")

    _assert_durable_finalization_failure(app, result)
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == recorded


def test_accounting_failure_raises_rather_than_setting_flags_itself(tmp_path, monkeypatch):
    """The halt belongs to execute()'s durable failure path, which never
    overwrites an earlier halt reason on its own."""
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    before = app.portfolio_foundation.snapshot()

    monkeypatch.setattr(JsonRiskStateStore, "load",
                        lambda self, **kw: (_ for _ in ()).throw(ValueError("corrupt")))
    with pytest.raises(RuntimeError, match=ExecutionManager.RISK_ACCOUNTING_UPDATE_FAILED):
        app.execution._record_realized_risk_accounting(
            request=ExecutionRequest("BTCUSDT", "SELL", 9.0, "900", request_id="x"),
            evidence=_evidence(), before=before, after=before,
        )

    assert app.execution.execution_halted is False


def test_replayed_apply_is_never_folded_in(tmp_path, monkeypatch):
    """Audit LOW-1: exercise the ``finalized["replayed"]`` guard directly."""
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    recorded = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()
    foundation = app.portfolio_foundation

    def replayed_apply(result, **kwargs):
        return foundation.snapshot(replayed=True)

    monkeypatch.setattr(foundation, "apply_confirmed", replayed_apply)
    result = _sell(app, base="100", price="9", request_id="s1")

    assert result["status"] == "PAPER_EXECUTED", result
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == recorded
    assert _events(state_dir, PNL_PREPARED, PNL_COMMITTED) == []


def _evidence():
    class _E:
        symbol = "BTCUSDT"
        execution_id = "e"
        position_id = "long:BTCUSDT"
    return _E()


def test_live_mode_never_records(tmp_path, monkeypatch):
    state_dir = _state(tmp_path)
    app = _app(state_dir)
    recorded = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()
    before = app.portfolio_foundation.snapshot()
    monkeypatch.setattr(app.execution, "mode", ExecutionManager.MODE_LIVE)

    app.execution._record_realized_risk_accounting(
        request=ExecutionRequest("BTCUSDT", "SELL", 9.0, "900", request_id="x"),
        evidence=_evidence(), before=before, after=before,
    )

    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == recorded
    assert app.execution.execution_halted is False


def test_rollover_cannot_interleave_with_the_accounting_write(tmp_path, monkeypatch):
    """The update holds the manager and journal locks the rollover needs."""
    import threading

    state_dir = _state(tmp_path)
    app = _app(state_dir)
    entered, release = threading.Event(), threading.Event()
    original = JsonRiskStateStore.save
    observed = {}

    def slow_save(self, value):
        entered.set()
        release.wait(5)
        original(self, value)

    def contender():
        entered.wait(5)
        got = app.execution._lock.acquire(timeout=0.2)
        observed["manager_lock_free_during_write"] = got
        if got:
            app.execution._lock.release()
        got = app.transaction_journal._lock.acquire(timeout=0.2)
        observed["journal_lock_free_during_write"] = got
        if got:
            app.transaction_journal._lock.release()
        release.set()

    monkeypatch.setattr(JsonRiskStateStore, "save", slow_save)
    thread = threading.Thread(target=contender)
    thread.start()
    _sell(app, base="100", price="9", request_id="s1")
    thread.join(5)

    assert observed == {
        "manager_lock_free_during_write": False,
        "journal_lock_free_during_write": False,
    }
