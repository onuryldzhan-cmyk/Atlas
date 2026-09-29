"""Strategy comparison (registry v5.54): one download, every variant, every window."""

from __future__ import annotations

import sys

sys.path.insert(0, "tests")
from test_backtest_replay import _Flip, _rows  # noqa: E402

from tools import strategy_compare as sc


def test_every_variant_runs_on_every_window_and_verdicts_are_strict():
    data = {"BTCUSDT": _rows(1500)}
    small = {k: sc.VARIANTS[k] for k in ("bugün (iyimser dolum)", sc.REFERENCE, "min tutma 60 dk", "satış onayı 2")}
    out = sc.compare(data, windows=2, step=10, exp001=False, brain_factory=_Flip, variants=small)
    assert set(out["table"]) == set(small) and all(len(rows) == 2 for rows in out["table"].values())
    assert out["verdicts"][sc.REFERENCE] == "-" and out["verdicts"]["bugün (iyimser dolum)"] == "-"
    assert out["verdicts"]["min tutma 60 dk"] in ("BETTER", "NOT PROVEN")


def test_too_short_windows_are_refused():
    try:
        sc.split({"BTCUSDT": _rows(300)}, 3)
    except ValueError as exc:
        assert "too short" in str(exc)
    else:
        raise AssertionError("short windows accepted")
