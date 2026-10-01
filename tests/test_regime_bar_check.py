"""The pre-registered regime-filter bar is applied verbatim."""

from tools.regime_bar_check import FILTER, REFERENCE, verdict


def result(flt, ref, ds="a"):
    rows = lambda xs: [{"net_pnl": n, "max_drawdown": d, "closed_trades": c} for n, d, c in xs]
    return {"table": {FILTER: rows(flt), REFERENCE: rows(ref)}, "dataset": {"dataset_sha256": ds}}


REF = [(10, 100, 20), (10, 100, 20), (10, 100, 20)]
GOOD = [(20, 90, 12), (20, 90, 12), (5, 90, 12)]


def test_owner_v575_shape_still_needs_a_second_period():
    # v5.75 nets/drawdowns; trade counts were not printed then, 10 per window is assumed here.
    flt = [(-48.14, 150, 10), (301.10, 164, 10), (466.92, 240, 10)]
    ref = [(73.61, 158, 10), (-239.26, 314, 10), (36.09, 262, 10)]
    assert verdict([result(flt, ref)])["verdict"] == "PENDING SECOND PERIOD"  # 2/3 won, dd ok, 30 trades: item 3 open


def test_worse_drawdown_in_any_window_fails():
    bad = [(20, 90, 12), (20, 90, 12), (20, 101, 12)]
    assert verdict([result(bad, REF)])["verdict"] == "NOT PROVEN"


def test_too_few_trades_fails():
    few = [(20, 90, 5), (20, 90, 5), (20, 90, 5)]
    assert verdict([result(few, REF)])["verdict"] == "NOT PROVEN"


def test_two_periods_with_different_datasets_clear_the_bar():
    assert verdict([result(GOOD, REF, "a"), result(GOOD, REF, "b")])["verdict"] == "BAR CLEARED"
    assert verdict([result(GOOD, REF, "a"), result(GOOD, REF, "a")])["verdict"] == "PENDING SECOND PERIOD"


def test_missing_variant_is_not_proven():
    assert verdict([{"table": {REFERENCE: []}}])["verdict"] == "NOT PROVEN"
