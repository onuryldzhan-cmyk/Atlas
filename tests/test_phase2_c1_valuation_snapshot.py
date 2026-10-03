"""Phase-2 C1: ValuationSnapshot / conservative mark-to-market."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.application import AtlasApplication
from core.valuation_snapshot import COMPLETE, INCOMPLETE, build_valuation_snapshot
from tests.test_block2_risk_service_composition_wiring import seed_valid_state
from tests.test_execution_crash_recovery_f1_f6 import _full_exit_sell

D = Decimal


@pytest.fixture(autouse=True)
def _isolated_roots(monkeypatch):
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)


def _pos(base, price, fees="0", mark=None):
    return {"base_quantity": str(base), "cost_quote": str(D(base) * D(price)),
            "entry_fees": fees, "mark_price": str(mark or price)}


def _snap(book, marks, *, ledger="10000", peak="10000", realized="0", fee=0):
    return build_valuation_snapshot(
        book_positions=book, marks=marks, ledger_equity=D(ledger), peak_equity=D(peak),
        realized_daily=D(realized), close_fee_rate=fee, as_of="t",
    )


def test_no_positions():
    s = _snap({}, {})
    assert s.completeness == COMPLETE
    assert s.unrealized_net == 0 and s.marked_equity == D("10000") and s.drawdown == 0


def test_profitable_position_never_raises_equity():
    s = _snap({"BTCUSDT": _pos(10, 10)}, {"BTCUSDT": "12"})
    assert s.unrealized_net == D("20")
    assert s.marked_equity == D("10000")  # loss-only (NB-4)


def test_losing_position_lowers_equity():
    s = _snap({"BTCUSDT": _pos(10, 10)}, {"BTCUSDT": "8"})
    assert s.unrealized_net == D("-20")
    assert s.marked_equity == D("9980")
    assert s.drawdown == D("20")


def test_multiple_positions_net_then_floor():
    s = _snap({"BTCUSDT": _pos(10, 10), "ETHUSDT": _pos(1, 100)},
              {"BTCUSDT": "8", "ETHUSDT": "130"})
    assert s.unrealized_net == D("10")  # -20 + 30
    assert s.marked_equity == D("10000")
    assert s.market_value == D("210")
    assert s.exposure_cost == D("200")


def test_entry_and_close_fees_are_counted():
    s = _snap({"BTCUSDT": _pos(10, 10, fees="1")}, {"BTCUSDT": "10"}, fee=D("0.001"))
    assert s.unrealized_net == D("-1.1")


@pytest.mark.parametrize("marks", [{}, {"BTCUSDT": "0"}, {"BTCUSDT": "nan"}, {"BTCUSDT": None}])
def test_incomplete_mark_is_never_zero_filled(marks):
    s = _snap({"BTCUSDT": _pos(10, 10)}, marks)
    assert s.completeness == INCOMPLETE
    assert s.missing_marks == ("BTCUSDT",)
    assert s.unrealized_net is None and s.marked_equity is None and s.drawdown is None


def test_realized_and_unrealized_combination():
    s = _snap({"BTCUSDT": _pos(10, 10)}, {"BTCUSDT": "9"}, ledger="9950", realized="-50")
    assert s.realized_daily == D("-50")
    assert s.marked_equity == D("9940")
    assert s.drawdown == D("60") and s.drawdown_pct == D("0.006")


def test_malformed_book_raises():
    with pytest.raises(ValueError):
        _snap({"BTCUSDT": {"base_quantity": "x"}}, {})


def test_snapshot_is_immutable():
    s = _snap({}, {})
    with pytest.raises(Exception):
        s.marked_equity = D("1")  # type: ignore[misc]


# ------------------------------------------------------------ integration


def _app(tmp_path, held=("BTCUSDT", "10", "10")):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir, held=held)
    app = AtlasApplication(state_directory=state_dir, evidence_directory=tmp_path / "ev",
                           count_unrealized_in_daily_loss=True)
    app.execution.start()
    return app


def test_risk_state_uses_marked_equity_under_f3(tmp_path):
    app = _app(tmp_path)
    app.execution.mark_price_provider = lambda: {"BTCUSDT": D("8")}

    state = app.execution._derive_risk_state()

    assert state.unrealized_pnl == D("-20")
    assert state.current_equity == D("9980")  # drawdown/sleeves see the open loss
    assert app.execution.last_valuation_snapshot.completeness == COMPLETE


def test_open_gain_does_not_loosen_drawdown(tmp_path):
    app = _app(tmp_path)
    app.execution.mark_price_provider = lambda: {"BTCUSDT": D("50")}
    state = app.execution._derive_risk_state()
    assert state.current_equity == D("10000")


def test_new_risk_with_unrealized_loss_is_refused(tmp_path):
    app = _app(tmp_path, held=("BTCUSDT", "900", "10"))
    app.execution.mark_price_provider = lambda: {"BTCUSDT": D("1")}
    from core.risk_engine import RiskRequest

    state = app.execution._derive_risk_state()
    decision = app.risk_engine.evaluate(
        RiskRequest("ETHUSDT", "BUY", D("0.99"), D("100"), D("10"), "HIGH"), state,
    )
    assert decision.status.value != "APPROVE"
    assert decision.reason_code in {"DAILY_LOSS_LIMIT_BREACHED", "DRAWDOWN_HALT_NEW_RISK",
                                    "DRAWDOWN_RESTRICT_NEW_RISK", "SLEEVE_FULL"}


def test_incomplete_valuation_blocks_new_risk(tmp_path):
    app = _app(tmp_path)
    app.execution.mark_price_provider = lambda: {}
    from core.risk_engine import RiskRequest

    state = app.execution._derive_risk_state()
    assert state.unrealized_pnl is None
    assert app.execution.unpriced_held_symbols == ["BTCUSDT"]
    decision = app.risk_engine.evaluate(
        RiskRequest("ETHUSDT", "BUY", D("0.99"), D("100"), D("10"), "LOW"), state,
    )
    assert decision.status.value != "APPROVE"


def test_reduce_only_exit_with_incomplete_valuation(tmp_path):
    app = _app(tmp_path)
    app.execution.mark_price_provider = lambda: {}

    result = _full_exit_sell(app, "s-incomplete")

    assert result["status"] == "PAPER_EXECUTED", result
    assert app.portfolio_foundation.snapshot()["positions"] == {}
