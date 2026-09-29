"""Reality check: calibration by confidence band, Monte Carlo drawdowns, cost coverage; honest on small samples."""

from __future__ import annotations

from tools import reality_check as rc


def trade(gross, conf_time="2026-09-29T10:00:00+00:00", symbol="BTCUSDT"):
    return {"symbol": symbol, "cost_quote": "1000", "gross_pnl": str(gross), "opened_at": conf_time}


def test_calibration_bands_and_unattributed():
    approvals = {"BTCUSDT": [{"timestamp": "2026-09-29T10:00:00+00:00", "confidence": 63.6}]}
    rows = rc.calibration([trade(5)] * 3 + [trade(5, symbol="ETHUSDT")], approvals)
    band = next(r for r in rows if r["band"] == "60-70")
    assert band["trades"] == 3 and band["verdict"] == "INSUFFICIENT" and band["win_rate_after_fees"] == 1.0
    assert rows[-1] == {"band": "confidence unknown", "trades": 1}


def test_worse_execution_never_improves_the_stress_numbers():
    records = [trade(g) for g in (8, -6, 3, -4, 5, -7, 2, 6, -3, 1)]
    mc = rc.monte_carlo(records, runs=500, horizon=30)
    assert [r["extra_cost_bps"] for r in mc] == [0, 10, 20]
    assert mc[0]["p95_max_drawdown"] >= mc[2]["p95_max_drawdown"]  # drawdowns are negative: worse = lower
    assert mc[0]["chance_of_loss"] <= mc[2]["chance_of_loss"]
    assert rc.monte_carlo(records, runs=200) == rc.monte_carlo(records, runs=200)  # fixed seed


def test_cost_check_flags_fee_eaten_edge_and_empty_book():
    assert rc.cost_check([trade(1)] * 10)["edge_covers_costs"] is False  # +1 gross pays ~2 in fees
    assert rc.cost_check([]) == {"trades": 0}
    assert rc.run([], {})["sample_ok"] is False and rc.monte_carlo([]) == []


def test_max_drawdown():
    assert rc.max_drawdown([5, -3, -4, 10, -1]) == -7
