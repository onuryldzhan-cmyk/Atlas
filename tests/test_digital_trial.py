"""Digital trial: same data twice -> same result; injected faults never crash, leak NaN or add trades."""

import sys

sys.path.insert(0, "tests")
from test_backtest_replay import _Flip, _rows  # noqa: E402

from tools import digital_trial as dt


def test_trial_invariants_hold_under_injected_faults():
    out = dt.run({"BTCUSDT": _rows(420)}, brain_factory=_Flip, step=10)
    assert out["deterministic"] is True and out["clean"]["completed"] is True
    for name, f in out["faults"].items():
        assert f["contained"], (name, f)
        assert f["finite"] is not False, (name, f)
    assert out["verdict"] == "PASS", out
