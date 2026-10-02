from tools import meta_filter as mf


def _row(t, regime, conf, net):
    return {"time": t, "action": "BUY", "regime": regime, "confidence": conf, "symbol": "X", "bucket": "M",
            "net_60m": "", "net_240m": "", "net_1440m": net}


def test_filter_is_learnt_on_older_data_and_judged_on_newer_only():
    rows = []
    for i in range(100):  # older: TREND_UP wins, SIDEWAYS loses
        rows += [_row(f"a{i:04d}", "TREND_UP", "61", "0.01"), _row(f"a{i:04d}", "SIDEWAYS", "61", "-0.01")]
    for i in range(40):   # newer: same pattern
        rows += [_row(f"b{i:04d}", "TREND_UP", "61", "0.005"), _row(f"b{i:04d}", "SIDEWAYS", "61", "-0.02")]
    out = mf.evaluate(rows, train=200 / 280)
    assert out["kept_groups"] == [("TREND_UP", "60-65")]
    assert out["test_filtered"]["win"] == 1.0 and out["test_all"]["win"] == 0.5
    assert out["test_filtered"]["n"] == 40 and out["test_all"]["n"] == 80


def test_nothing_profitable_means_nothing_kept():
    rows = [_row(f"{i:04d}", "SIDEWAYS", "61", "-0.01") for i in range(200)]
    out = mf.evaluate(rows)
    assert out["kept_groups"] == [] and out["test_filtered"]["n"] == 0
