"""tools/paper_position_report.py: read-only, attributes each entry."""

from __future__ import annotations

import hashlib
from pathlib import Path

from tests.test_block5c_upstream_sizing_authority import application, execution_enabled_loop
from tools import paper_position_report as tool


def _digest(root: Path) -> str:
    return hashlib.sha256(b"".join(
        p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    )).hexdigest()


def test_reports_the_open_position_and_its_admission_without_writing(
    tmp_path, monkeypatch, capsys,
):
    app = application(tmp_path)
    app.execution.start()
    assert execution_enabled_loop(app, "BUY").process_symbol("BTCUSDT")["status"] == "PAPER_EXECUTED"
    root = tmp_path / "state"
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(root))
    before = _digest(root)

    assert tool.main(["--no-price"]) == 0

    out = capsys.readouterr().out
    assert "open positions: 1" in out
    assert "BTCUSDT" in out
    assert "confidence=90.0 risk=MEDIUM experiment=none (policy floor)" in out
    assert _digest(root) == before


def test_entry_approval_picks_the_latest_one_before_opening():
    approvals = [
        {"timestamp": "2026-09-28T10:00:00+00:00", "experiment_id": None},
        {"timestamp": "2026-09-28T11:00:00+00:00", "experiment_id": "EXP-001"},
        {"timestamp": "2026-09-28T12:00:00+00:00", "experiment_id": None},
    ]

    chosen = tool.entry_approval(approvals, "2026-09-28T11:30:00+00:00")

    assert chosen["experiment_id"] == "EXP-001"
