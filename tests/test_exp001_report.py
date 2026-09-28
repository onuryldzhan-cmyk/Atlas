"""tools/exp001_report.py: read-only EXP-001 results (registry v5.23)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from tools import exp001_report as report


def closed(symbol, gross, opened, closed_at, fees="0.1"):
    return {"symbol": symbol, "gross_pnl": gross, "entry_fees": fees,
            "opened_at": opened, "closed_at": closed_at}


def approval(symbol, ts, experiment=True):
    details = {"experiment_id": "EXP-001"} if experiment else {}
    return {"event_type": "RISK_APPROVED", "aggregate_id": f"{symbol}|open:1|BUY",
            "timestamp": ts, "payload": {"details": details, "confidence": 60.4, "risk": "HIGH"}}


def test_wilson_interval_bounds():
    assert report.wilson_interval(0, 0) == (0.0, 1.0)
    low, high = report.wilson_interval(5, 5)
    assert 0.5 < low < 0.6 and high == 1.0
    low, high = report.wilson_interval(15, 30)
    assert low < 0.5 < high


def test_small_sample_never_gets_a_verdict():
    s = report.summarize([closed("BTCUSDT", "5", "2026-09-28T10:00:00+00:00", "2026-09-28T12:00:00+00:00")] * 29)
    assert s["trades"] == 29 and s["wins"] == 29
    assert report.verdict(s).startswith("INSUFFICIENT SAMPLE")


def test_verdicts_at_30_trades():
    win = closed("B", "2", "2026-09-28T10:00:00+00:00", "2026-09-28T11:00:00+00:00")
    loss = closed("B", "-1", "2026-09-28T10:00:00+00:00", "2026-09-28T11:00:00+00:00")
    assert report.verdict(report.summarize([win] * 25 + [loss] * 5)).startswith("PROFITABLE, win rate above")
    assert report.verdict(report.summarize([win] * 15 + [loss] * 15)).startswith("PROFITABLE but")
    assert report.verdict(report.summarize([win] * 10 + [loss] * 20 + [loss] * 0)).startswith("NOT PROFITABLE")


def test_zero_gross_is_not_a_win():
    s = report.summarize([closed("B", "0", "2026-09-28T10:00:00+00:00", "2026-09-28T11:00:00+00:00")])
    assert s["wins"] == 0 and s["losses"] == 1


def test_grouping_by_nearest_entry_approval():
    approvals = {
        "BTCUSDT": [{"timestamp": "2026-09-28T10:00:00.100+00:00", "experiment_id": "EXP-001"}],
        "ETHUSDT": [{"timestamp": "2026-09-28T10:00:00+00:00", "experiment_id": None}],
    }
    rows = [closed("BTCUSDT", "1", "2026-09-28T10:00:00+00:00", "2026-09-28T11:00:00+00:00"),
            closed("ETHUSDT", "1", "2026-09-28T10:00:00+00:00", "2026-09-28T11:00:00+00:00"),
            closed("XRPUSDT", "1", "2026-09-28T10:00:00+00:00", "2026-09-28T11:00:00+00:00")]
    groups = report.group_closed(rows, approvals)
    assert [len(groups[k]) for k in ("EXP-001", "policy floor", "unattributed")] == [1, 1, 1]


def test_main_end_to_end_and_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(tmp_path))
    rows = [closed("BTCUSDT", "3.5", "2026-09-28T11:10:41+00:00", "2026-09-28T15:00:00+00:00"),
            closed("SOLUSDT", "-1.0", "2026-09-28T11:10:42+00:00", "2026-09-28T14:37:07+00:00")]
    (tmp_path / "execution_closed_positions.jsonl").write_text(
        "".join(json.dumps({"sequence": i, **r}) + "\n" for i, r in enumerate(rows)), encoding="utf-8")
    audit = tmp_path / "audit"
    audit.mkdir()
    (audit / "atlas_audit_events.jsonl").write_text(
        json.dumps(approval("BTCUSDT", "2026-09-28T11:10:41.5+00:00")) + "\n"
        + json.dumps(approval("SOLUSDT", "2026-09-28T11:10:42.5+00:00")) + "\n", encoding="utf-8")
    (tmp_path / "execution_financial_state.json").write_text(
        json.dumps({"cash": "10017.53", "realized_gross_pnl": "20", "fees": "2.47"}), encoding="utf-8")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    assert report.main([]) == 0
    out = capsys.readouterr().out
    assert "admissions: audit 2/50" in out
    assert "trades: 2  wins: 1  losses: 1" in out
    assert "INSUFFICIENT SAMPLE" in out
    assert "net 17.53" in out
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_main_with_empty_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(tmp_path))
    assert report.main([]) == 0
    assert "no closed trades" in capsys.readouterr().out
