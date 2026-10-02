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
    assert sell["verdict"] == "INSUFFICIENT" and sell["net_60m_win"] == 1.0  # buying would have lost -> SELL right
