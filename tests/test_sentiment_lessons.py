"""tools/sentiment_lessons.py: observe-only check of the live Fear & Greed vote (2026-10-02)."""
from __future__ import annotations

import csv
import json

import pytest

from tools import sentiment_lessons as sl


def _body(items):
    return json.dumps({"name": "Fear and Greed Index", "data": items}).encode()


def test_parse_history_drops_malformed_entries_and_never_repairs():
    items = [{"value": "20", "timestamp": "1767225600"},          # 2026-01-01
             {"value": "101", "timestamp": "1767312000"},         # out of range
             {"value": "x", "timestamp": "1767398400"},           # not a number
             {"timestamp": "1767484800"},                         # missing value
             {"value": "80", "timestamp": "1767571200"}]          # 2026-01-05
    assert sl.parse_history(_body(items)) == {"2026-01-01": 20, "2026-01-05": 80}
    with pytest.raises(ValueError):
        sl.parse_history(b"x" * (sl.MAX_BODY + 1))


def test_history_is_cached_and_offline_reads_the_cache(tmp_path):
    body = _body([{"value": "50", "timestamp": "1767225600"}])
    assert sl.load_history(tmp_path, lambda: body) == {"2026-01-01": 50}
    assert sl.load_history(tmp_path, None) == {"2026-01-01": 50}
    assert sl.load_history(tmp_path / "empty", None) == {}


def test_evaluate_groups_by_band_skips_days_without_a_value(tmp_path):
    path = tmp_path / "s.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["symbol", "time", "action", "confidence", "regime", "net_240m"])
        w.writeheader()
        for day in range(1, 29):
            for h in (0, 8, 16):
                w.writerow({"symbol": "BTCUSDT", "time": f"2026-01-{day:02d}T{h:02d}:00:00+00:00", "action": "BUY",
                            "confidence": "61", "regime": "TREND_UP", "net_240m": "0.004" if day % 2 else "-0.004"})
    history = {f"2026-01-{d:02d}": (10 if d % 2 else 90) for d in range(1, 28)}  # day 28 has no value
    out = sl.evaluate(path, history, "2026-01-15T00:00:00+00:00")
    assert out["decisions"] == 84 and out["without_index_value"] == 3
    bands = {(g["action"], g["band"]) for g in out["groups"]}
    assert bands == {("BUY", "FEAR"), ("BUY", "GREED")}
    fear = next(g for g in out["groups"] if g["band"] == "FEAR")
    assert fear["avg240_older_pct"] > 0 and fear["win240_older"] == 1.0
    assert out["lessons"] == []  # too few independent samples per half: no lesson, by design
