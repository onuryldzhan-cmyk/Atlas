"""Executes the dashboard's portfolio-performance JavaScript in node.

The panel is read-only and fed by /api/trades. These tests run the real
functions sliced from templates/dashboard.html (no source-text pinning):
KPIs, cumulative P&L series, trade table ordering, escaping, and the
empty / malformed-input cases. Skipped when node is not on PATH.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "dashboard.html"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")


def _function(body: str, name: str) -> str:
    start = body.index(f"        function {name}(")
    end = body.index("\n        }\n", start) + len("\n        }\n")
    return body[start:end]


def _script() -> str:
    body = TEMPLATE.read_text(encoding="utf-8")
    names = ["esc", "isNumber", "toNum", "hoursBetween", "pnlSpan", "kpi", "renderPerformance"]
    return "\n".join(_function(body, n) for n in names)


def _run(payload: dict) -> dict:
    harness = (
        "const els = {};\n"
        "global.document = { getElementById: (id) => (els[id] = els[id] || { innerHTML: '', textContent: '' }) };\n"
        "let chart = null;\n"
        "function drawChart(id, cfg) { chart = cfg; return true; }\n"
        "function cssVar(n) { return '#0a0'; }\n"
        + _script()
        + f"\nrenderPerformance({json.dumps(payload)});\n"
        "console.log(JSON.stringify({ kpis: els['performance-kpis'].innerHTML,"
        " trades: els['performance-trades'].innerHTML, note: els['performance-chart-note'].textContent,"
        " data: chart && chart.data.datasets[0] ? chart.data.datasets[0].data : [] }));\n"
    )
    out = subprocess.run([NODE, "-e", harness], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


TRADES = [
    {"symbol": "XRPUSDT", "gross_pnl": "4.70", "opened_at": "2026-09-28T10:46:06+00:00", "closed_at": "2026-09-28T14:37:07+00:00"},
    {"symbol": "BNBUSDT", "gross_pnl": "-1.25", "opened_at": "2026-09-28T10:47:04+00:00", "closed_at": "2026-09-28T14:37:06+00:00"},
    {"symbol": "BTCUSDT", "gross_pnl": "2.76", "opened_at": "2026-09-28T11:10:41+00:00", "closed_at": "2026-09-28T16:00:00+00:00"},
]


def test_cumulative_series_is_ordered_by_close_time():
    r = _run({"total_trades": 3, "win_rate": 66.67, "total_gross_pnl": "6.21", "recent_trades": TRADES})
    assert r["data"] == pytest.approx([-1.25, 3.45, 6.21])


def test_kpis_show_totals_best_worst_and_duration():
    r = _run({"total_trades": 3, "win_rate": 66.67, "total_gross_pnl": "6.21", "recent_trades": TRADES})
    assert "66.67%" in r["kpis"]
    assert "+6.21" in r["kpis"] and "+4.70" in r["kpis"] and "-1.25" in r["kpis"]
    assert "text-success" in r["kpis"] and "text-danger" in r["kpis"]
    assert " sa" in r["kpis"]


def test_table_newest_first_and_escaped():
    trades = TRADES + [{"symbol": "<img src=x>", "gross_pnl": "1", "opened_at": "2026-09-28T17:00:00+00:00",
                        "closed_at": "2026-09-28T18:00:00+00:00"}]
    r = _run({"total_trades": 4, "win_rate": 75, "total_gross_pnl": "7.21", "recent_trades": trades})
    assert "<img" not in r["trades"] and "&lt;img" in r["trades"]
    assert r["trades"].index("&lt;img") < r["trades"].index("XRPUSDT")


def test_empty_history_is_stated_not_invented():
    r = _run({"total_trades": 0, "win_rate": None, "total_gross_pnl": "0", "recent_trades": []})
    assert "Henüz kapanan işlem yok" in r["trades"] and "Henüz" in r["note"]
    assert "n/a" in r["kpis"] and r["data"] == []


def test_malformed_rows_are_dropped_not_counted_as_zero():
    trades = TRADES + [{"symbol": "ETHUSDT", "gross_pnl": "abc", "opened_at": "x", "closed_at": "y"},
                       {"symbol": "SOLUSDT", "gross_pnl": None}]
    r = _run({"total_trades": 3, "win_rate": 66.67, "total_gross_pnl": "6.21", "recent_trades": trades})
    assert r["data"] == pytest.approx([-1.25, 3.45, 6.21])
    assert "ETHUSDT" not in r["trades"]
