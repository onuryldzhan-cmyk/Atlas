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
