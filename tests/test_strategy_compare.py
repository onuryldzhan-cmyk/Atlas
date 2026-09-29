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


def test_dataset_manifest_is_deterministic_and_detects_change():
    a = {"BTCUSDT": _rows(200)}
    m1, m2 = sc.dataset_manifest(a), sc.dataset_manifest({"BTCUSDT": _rows(200)})
    assert m1 == m2 and m1["symbols"]["BTCUSDT"]["rows"] == 200
    b = {"BTCUSDT": _rows(200)}
    b["BTCUSDT"][5] = list(b["BTCUSDT"][5])
    b["BTCUSDT"][5][4] = "999999"
    assert sc.dataset_manifest(b)["dataset_sha256"] != m1["dataset_sha256"]


def test_saved_dataset_replays_and_corruption_is_refused(tmp_path, monkeypatch):
    import json

    saved = tmp_path / "ds.json"
    data = {"BTCUSDT": _rows(1500)}
    saved.write_text(json.dumps({"manifest": sc.dataset_manifest(data), "data": data}), encoding="utf-8")
    monkeypatch.setattr(sc, "compare", lambda *a, **k: {"table": {}, "verdicts": {}})
    assert sc.main(["--dataset", str(saved), "--symbols", "BTCUSDT", "--json"]) == 0
    bad = json.loads(saved.read_text(encoding="utf-8"))
    bad["data"]["BTCUSDT"][0][4] = "1"
    saved.write_text(json.dumps(bad), encoding="utf-8")
    assert sc.main(["--dataset", str(saved), "--symbols", "BTCUSDT"]) == 2
