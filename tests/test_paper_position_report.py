"""tools/paper_position_report.py: read-only, attributes each entry."""

from __future__ import annotations

import hashlib
from pathlib import Path

from tests.test_block5c_upstream_sizing_authority import application, execution_enabled_loop
from tools import paper_position_report as tool


def _digest(root: Path) -> str:
    # The instance lock file is skipped: Windows refuses to read a byte
    # range another handle has locked, and it carries no state anyway.
    return hashlib.sha256(b"".join(
        p.read_bytes() for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "atlas.instance.lock"
    )).hexdigest()


def test_reports_the_open_position_and_its_admission_without_writing(
    tmp_path, monkeypatch, capsys,
):
    app = application(tmp_path)
    app.execution.start()
    assert execution_enabled_loop(app, "BUY").process_symbol("BTCUSDT")["status"] == "PAPER_EXECUTED"
    app.stop()
    root = tmp_path / "state"
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(root))
    before = _digest(root)

    assert tool.main(["--no-price"]) == 0

    out = capsys.readouterr().out
    assert "open positions: 1" in out
    assert "BTCUSDT" in out
    assert "confidence=90.0 risk=MEDIUM experiment=none (policy floor)" in out
    assert _digest(root) == before


def test_legacy_entry_approval_never_picks_the_nearest_of_several():
    """Phase-2 F1 (replaces test_entry_approval_picks_the_latest_one_before_opening, which
    asserted that a 30-minutes-away approval was chosen over an equally distant one - the
    timestamp guessing F1 removes). A legacy record far from every approval is UNATTRIBUTED."""
    approvals = [
        {"timestamp": "2026-09-28T10:00:00+00:00", "experiment_id": None},
        {"timestamp": "2026-09-28T11:00:00+00:00", "experiment_id": "EXP-001"},
        {"timestamp": "2026-09-28T12:00:00+00:00", "experiment_id": None},
    ]

    assert tool.entry_approval(approvals, "2026-09-28T11:30:00+00:00") is None


def test_an_approval_written_just_after_the_fill_is_still_the_one_chosen():
    """Owner run 2026-09-28: BNB opened 10:47:04.397, approved 10:47:04.409."""

    approvals = [
        {"timestamp": "2026-09-27T09:00:00+00:00", "confidence": 67.7, "experiment_id": None},
        {"timestamp": "2026-09-28T10:47:04.409057+00:00", "confidence": 60.43, "experiment_id": "EXP-001"},
    ]

    chosen = tool.entry_approval(approvals, "2026-09-28T10:47:04.397057+00:00")

    assert chosen["experiment_id"] == "EXP-001"
    assert chosen["attribution"] == tool.LEGACY_TIMESTAMP
