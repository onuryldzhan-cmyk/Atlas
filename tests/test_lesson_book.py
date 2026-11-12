from decimal import Decimal

from tools import lesson_book as lb


def _row(action, conf, n60, regime="SIDEWAYS"):
    return {"action": action, "confidence": conf, "regime": regime, "symbol": "BTCUSDT", "bucket": "MEDIUM",
            "net_60m": n60, "net_240m": ""}


def test_groups_bands_and_marks_small_groups_insufficient():
    rows = [_row("BUY", "61.2", "0.01")] * 20 + [_row("BUY", "61.9", "-0.02")] * 10 + [_row("SELL", "72", "-0.01")] * 3
    out = {(g["action"], g["confidence"]): g for g in lb.build(rows)}
    buy = out[("BUY", "60-65")]
    assert buy["n"] == 30 and buy["verdict"] == "MEASURED"
    assert buy["net_60m_win"] == round(20 / 30, 3) and buy["net_240m_win"] is None  # missing horizon, not guessed
    sell = out[("SELL", "70-75")]
    assert sell["verdict"] == "INSUFFICIENT" and sell["net_60m_win"] == 1.0  # -1% net is a real price fall


def test_sell_is_judged_on_the_price_move_not_on_fees():
    # -0.2% net after a round trip of 0.2% fees + 0.1% slippage is a price RISE: SELL was wrong.
    out = lb.build([_row("SELL", "72", "-0.002")] * 3)
    assert out[0]["net_60m_win"] == 0.0 and out[0]["net_60m_avg_pct"] > 0


def test_fee_repricing_uses_raw_moves_bnb_fee_beats_standard():
    row = {**_row("BUY", "61", "-0.0001"), "ret_60m": "0.0025"}  # +0.25% raw move
    std = lb.build([row] * 3, slippage_bps=5, fee_bps=10)[0]["net_60m_avg_pct"]
    bnb = lb.build([row] * 3, slippage_bps=5, fee_bps=7)[0]["net_60m_avg_pct"]
    assert bnb > 0 > std  # +0.25% move: a loss at 0.10%/side, a small gain at 0.07% (BNB)
    assert lb.build([row] * 3)[0]["net_60m_avg_pct"] == -0.01  # without --fee-bps the recorded net is used


def test_barrier_stats_for_buy_groups():
    rows = [{**_row("BUY", "61", "0.001"), "tb_10m": "TP", "tbnet_10m": "0.003"}] * 2 + \
           [{**_row("BUY", "61", "0.001"), "tb_10m": "SL", "tbnet_10m": "-0.007"}] * 2
    g = lb.build(rows)[0]
    assert g["tb10_tp"] == 0.5 and g["tb10_avg_pct"] == -0.2 and g["tb5_tp"] is None


def test_live_rows_use_entry_confidence_and_regime_known_before_the_trade():
    import json
    closed = [{"symbol": "BTCUSDT", "opened_at": "2026-10-02T08:00:00+00:00", "cost_quote": "100", "gross_pnl": "1"},
              {"symbol": "ETHUSDT", "opened_at": "2026-10-02T08:00:00+00:00", "cost_quote": "100", "gross_pnl": "1"}]
    approvals = {"BTCUSDT": [{"confidence": 62.5, "at": "2026-10-02T07:59:00+00:00"}]}
    regimes = [{"created_at": "2026-10-02T07:50:00Z", "body": json.dumps({"coins": {"BTCUSDT": {"regime": "SIDEWAYS"}}})},
               {"created_at": "2026-10-02T09:00:00Z", "body": json.dumps({"coins": {"BTCUSDT": {"regime": "PANIC"}}})}]
    import tools.paper_position_report as ppr
    real = ppr.entry_approval
    # Phase-2 F1: entry_approval also takes the position_id (exact attribution); this stub ignores it.
    ppr.entry_approval = lambda items, opened, position_id=None: items[0] if items else None
    try:
        rows = lb.live_rows(closed, approvals, regimes)
    finally:
        ppr.entry_approval = real
    assert len(rows) == 1 and rows[0]["regime"] == "SIDEWAYS"  # not PANIC: that came after the entry
    assert rows[0]["confidence"] == "62.5" and Decimal(rows[0]["net_live"]) > 0  # +1 gross beats ~0.2 fees
    t = lb.live_table(rows)
    assert t[0]["n"] == 1 and t[0]["verdict"] == "INSUFFICIENT"
