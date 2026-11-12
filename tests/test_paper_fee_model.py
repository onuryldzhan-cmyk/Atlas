"""Paper fee model (registry v5.23; owner: 0.1% per side).

The accounting chain already settles a quote-asset fee end to end; before
v5.23 the paper fill never reported one, so paper P&L was fee-free. These
tests pin: the fee on both sides, cash and closed-record arithmetic, a
production-style unsized full exit, idempotent replay, and that only the
real runtime (main.py) opts in.
"""

from __future__ import annotations

import inspect
from decimal import ROUND_UP, Decimal

import pytest

import main
from core.application import AtlasApplication
from core.execution_manager import PAPER_FEE_RATE_PER_SIDE, ExecutionManager
from core.execution_models import ExecutionRequest
from tests.test_block3_execution_exception_atomicity import (
    buy_decision,
    journal_state,
    risk_state,
    risk_state_with,
)
from tests.test_block2_risk_service_composition_wiring import seed_valid_state
from core.risk_engine import PositionExposure

D = Decimal
RATE = D("0.001")
Q = D("0.00000001")


def app_with(tmp_path, rate):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = AtlasApplication(state_directory=state_dir, paper_fee_rate=rate)
    app.execution.start()
    return app


def snapshot(app):
    return app.portfolio_foundation.snapshot()


def test_pinned_rate_and_only_main_opts_in():
    assert PAPER_FEE_RATE_PER_SIDE == D("0.001")
    assert "paper_fee_rate=PAPER_FEE_RATE_PER_SIDE" in inspect.getsource(main.AtlasProcess.start)
    assert inspect.signature(AtlasApplication.__init__).parameters["paper_fee_rate"].default == "0"


@pytest.mark.parametrize("bad", ["-0.001", "1", "2", "NaN", "inf"])
def test_invalid_rate_is_refused(bad):
    with pytest.raises(ValueError):
        ExecutionManager(paper_fee_rate=D(bad))


def test_default_application_stays_fee_free(tmp_path):
    app = app_with(tmp_path, "0")
    cash0 = D(str(snapshot(app)["cash"]))
    assert app.execution.execute(buy_decision(app), risk_state())["status"] == "PAPER_EXECUTED"
    s = snapshot(app)
    assert D(str(s["fees"])) == 0
    assert cash0 - D(str(s["cash"])) == D(str(s["positions"]["BTCUSDT"]["cost_quote"]))


def test_buy_charges_fee_within_the_approved_allocation(tmp_path):
    app = app_with(tmp_path, RATE)
    cash0 = D(str(snapshot(app)["cash"]))
    decision = buy_decision(app)
    allocation = D(str(decision["amount"]))

    result = app.execution.execute(decision, risk_state())
    assert result["status"] == "PAPER_EXECUTED"

    s = snapshot(app)
    position = s["positions"]["BTCUSDT"]
    fee = D(str(position["entry_fees"]))
    notional = D(str(position["cost_quote"]))
    assert fee == (allocation * RATE / (1 + RATE)).quantize(Q, rounding=ROUND_UP)
    assert fee >= (notional * RATE)            # never under-charged
    assert notional + fee <= allocation        # the approval is never exceeded
    assert cash0 - D(str(s["cash"])) == notional + fee
    assert D(str(s["fees"])) == fee


def test_round_trip_full_exit_pays_both_sides(tmp_path):
    app = app_with(tmp_path, RATE)
    cash0 = D(str(snapshot(app)["cash"]))
    assert app.execution.execute(buy_decision(app), risk_state())["status"] == "PAPER_EXECUTED"
    held = snapshot(app)["positions"]["BTCUSDT"]
    base, cost, entry_fee = D(str(held["base_quantity"])), D(str(held["cost_quote"])), D(str(held["entry_fees"]))

    exposure = PositionExposure("BTCUSDT", base, D("10"), base * D("10"))
    sell = ExecutionRequest("BTCUSDT", "SELL", 10, 0, confidence=90, risk="HIGH",
                            request_id="s1", reduce_only=True).to_dict()
    result = app.execution.execute(sell, risk_state_with(exposure))
    assert result["success"] is True, result
    assert journal_state(app, "s1") == "COMMITTED"

    s = snapshot(app)
    assert "BTCUSDT" not in s["positions"]
    exit_notional = base * D("10")
    exit_fee = (exit_notional * RATE).quantize(Q, rounding=ROUND_UP)
    assert D(str(s["fees"])) == entry_fee + exit_fee
    # same price in and out: gross 0, the account is down exactly the fees
    assert cash0 - D(str(s["cash"])) == entry_fee + exit_fee + (cost - exit_notional)


def test_replayed_buy_is_charged_once(tmp_path):
    app = app_with(tmp_path, RATE)
    decision = buy_decision(app)
    app.execution.execute(decision, risk_state())
    fees_after_first = D(str(snapshot(app)["fees"]))
    app.execution.execute(decision, risk_state())
    assert D(str(snapshot(app)["fees"])) == fees_after_first


def test_fee_survives_restart(tmp_path):
    app = app_with(tmp_path, RATE)
    app.execution.execute(buy_decision(app), risk_state())
    fees = D(str(snapshot(app)["fees"]))
    app.stop() if hasattr(app, "stop") else None
    reopened = AtlasApplication(state_directory=tmp_path / "state", paper_fee_rate=RATE)
    assert D(str(reopened.portfolio_foundation.snapshot()["fees"])) == fees


# --------------------------------------------- recovery re-derives the fee

def test_crash_recovery_rederives_the_fee_the_execution_charged(tmp_path, monkeypatch):
    """Audit MEDIUM-1 (v5.23): a fee-charged BUY killed in the inconclusive
    window is re-derived with the rate its approval recorded, so the
    recovered book equals an uninterrupted fee-charging run."""
    import tests.test_execution_crash_recovery_f1_f6 as k

    def fee_app(state_dir):
        app = AtlasApplication(state_directory=state_dir,
                               evidence_directory=state_dir.parent / "evidence",
                               paper_fee_rate=RATE)
        app.execution.start()
        return app

    base_dir = tmp_path / "baseline" / "state"
    seed_valid_state(base_dir)
    baseline_app = fee_app(base_dir)
    assert k._buy(baseline_app)["status"] == "PAPER_EXECUTED"
    baseline = baseline_app.portfolio_foundation.snapshot()
    assert D(baseline["positions"]["BTCUSDT"]["entry_fees"]) > 0

    state_dir = k._fresh_state(tmp_path)
    app = fee_app(state_dir)
    k._crash_on(monkeypatch, app.portfolio_foundation.applied_archive, "append", after=True)
    k._run_until_crash(app, k._buy)

    outcome = k._recover(state_dir)
    assert outcome.recovery_class == k.RecoveryClass.COMMIT_PAPER_REDERIVATION.value

    recovered = AtlasApplication(state_directory=state_dir,
                                 evidence_directory=state_dir.parent / "evidence",
                                 paper_fee_rate=RATE).portfolio_foundation.snapshot()
    for field in ("base_quantity", "cost_quote", "entry_fees"):
        assert recovered["positions"]["BTCUSDT"][field] == baseline["positions"]["BTCUSDT"][field]
    assert recovered["cash"] == baseline["cash"]
    assert recovered["fees"] == baseline["fees"]


def test_approval_records_the_rate_only_when_charged(tmp_path):
    fee = app_with(tmp_path / "a", RATE)
    free = app_with(tmp_path / "b", "0")
    check = lambda app: app.execution.risk_check(ExecutionRequest.from_dict(buy_decision(app)))
    assert check(fee)["details"]["paper_fee_rate"] == "0.001"
    assert "paper_fee_rate" not in check(free)["details"]


def test_fee_that_would_push_a_fill_below_min_notional_is_refused_at_admission(tmp_path):
    """Audit LOW-2 (v5.23): admission sizes with the fee, so a fill the fee
    would push below the venue minimum is refused cleanly - never admitted
    and then halted after the side-effect boundary."""
    app = app_with(tmp_path, RATE)
    # 5.004 at price 10: fee-free notional 5.004 >= 5, after the fee < 5
    decision = ExecutionRequest("BTCUSDT", "BUY", 10, "5.004", confidence=90, risk="HIGH",
                                request_id="tiny").to_dict()
    result = app.execution.execute(decision, risk_state())
    assert result["success"] is False
    # refused before any side effect, not failed after the fill
    assert result["status"] == "REJECTED"
    assert result["reason"] == "NOTIONAL_BELOW_VENUE_MINIMUM"
    assert app.execution.execution_halted is False
    assert app.execution.recovery_required is False
    assert "BTCUSDT" not in snapshot(app)["positions"]


def test_partial_sell_charges_exit_fee_and_apportions_entry_fees(tmp_path):
    """Audit LOW (v5.23): a partial exit pays its own exit fee and releases
    entry fees pro rata; the rest stays on the remaining position."""
    app = app_with(tmp_path, RATE)
    assert app.execution.execute(buy_decision(app), risk_state())["status"] == "PAPER_EXECUTED"
    held = snapshot(app)["positions"]["BTCUSDT"]
    base, entry_fee = D(str(held["base_quantity"])), D(str(held["entry_fees"]))
    step = app.execution.instrument_rules.get("BTCUSDT").quantity_step
    sold = (base / 2 // step) * step
    fees_before = D(str(snapshot(app)["fees"]))

    exposure = PositionExposure("BTCUSDT", base, D("10"), base * D("10"))
    sell = ExecutionRequest("BTCUSDT", "SELL", 10, format(sold * D("10"), "f"), confidence=90,
                            risk="HIGH", request_id="p1", reduce_only=True).to_dict()
    result = app.execution.execute(sell, risk_state_with(exposure))
    assert result["success"] is True, result

    s = snapshot(app)
    remaining = s["positions"]["BTCUSDT"]
    assert D(str(remaining["base_quantity"])) == base - sold
    exit_fee = (sold * D("10") * RATE).quantize(Q, rounding=ROUND_UP)
    assert D(str(s["fees"])) == fees_before + exit_fee
    # remaining entry fees are the unsold share (within rounding of one quantum)
    expected_remaining = entry_fee * (base - sold) / base
    assert abs(D(str(remaining["entry_fees"])) - expected_remaining) <= D("0.00000002")
