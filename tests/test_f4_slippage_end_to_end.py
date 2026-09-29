"""F-4 end to end: with PAPER slippage on, a real BUY -> SELL through ExecutionManager stays accountable.

Adverse fills: BUY above and SELL below the request price; the reservation never
settles above what was approved; realized P&L reflects the slippage; the book
has no position left and no NaN anywhere.
"""

from decimal import Decimal as D

from tests.test_block5e_fee_settlement_accounting import application


def _run(tmp_path, bps):
    app = application(tmp_path)
    app.execution.start()
    app.execution.paper_slippage_bps = D(bps)
    m = app.execution
    buy = m.execute({"symbol": "BTCUSDT", "action": "BUY", "price": 10.0, "amount": 1000,
                     "confidence": 90.0, "risk": "MEDIUM", "request_id": "b1"})
    sell = m.execute({"symbol": "BTCUSDT", "action": "SELL", "price": 10.0, "amount": 0,
                      "confidence": 90.0, "risk": "MEDIUM", "request_id": "s1"})
    return app, buy, sell


def test_slippage_is_adverse_and_accounting_stays_consistent(tmp_path):
    app, buy, sell = _run(tmp_path / "a", "20")
    assert buy["status"] == "PAPER_EXECUTED" and buy["commit_outcome"] == "COMMITTED", buy
    assert D(str(buy["filled_price"])) > D("10") and D(str(sell["filled_price"])) < D("10")
    reservation = app.execution.reservation_ledger.get("b1")
    assert reservation.amount <= D("1000")
    snap = app.portfolio_foundation.snapshot()
    assert "BTCUSDT" not in snap["positions"]
    assert D(snap["realized_gross_pnl"]) < 0  # buying high, selling low at the same mark loses


def test_zero_slippage_is_unchanged_and_loses_less(tmp_path):
    _, _, _ = _run(tmp_path / "z", "0")
    app0, buy0, _ = _run(tmp_path / "z2", "0")
    app1, _, _ = _run(tmp_path / "s", "20")
    assert D(str(buy0["filled_price"])) == D("10")
    assert D(app0.portfolio_foundation.snapshot()["realized_gross_pnl"]) > D(app1.portfolio_foundation.snapshot()["realized_gross_pnl"])
