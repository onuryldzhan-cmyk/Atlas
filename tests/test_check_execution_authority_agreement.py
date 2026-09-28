"""tools/check_execution_authority_agreement.py: read-only pre-flight."""

from __future__ import annotations

import hashlib

from core.application import AtlasApplication, EXECUTION_TRANSACTION_JOURNAL_FILE
from tests.test_block5c_upstream_sizing_authority import execution_enabled_loop, seed_state
from tools import check_execution_authority_agreement as tool


def _digest(root):
    return sorted(
        (p.name, hashlib.sha256(p.read_bytes()).hexdigest())
        for p in root.rglob("*") if p.is_file() and p.name != "atlas.instance.lock"
    )


def _book(tmp_path):
    root = seed_state(tmp_path / "state")
    app = AtlasApplication(state_directory=root)
    app.execution.start()
    execution_enabled_loop(app, "BUY").process_symbol("BTCUSDT")
    app.stop()
    return root


def test_healthy_state_passes_and_nothing_is_written(tmp_path, capsys):
    root = _book(tmp_path)
    before = _digest(root)

    assert tool.main(["--state-dir", str(root)]) == 0
    assert "ready=True" in capsys.readouterr().out
    assert _digest(root) == before


def test_deleted_journal_is_reported_before_atlas_starts(tmp_path, capsys):
    root = _book(tmp_path)
    (root / EXECUTION_TRANSACTION_JOURNAL_FILE).unlink()
    before = _digest(root)

    assert tool.main(["--state-dir", str(root)]) == 1
    out = capsys.readouterr().out
    assert "idempotency_committed_without_journal: 1" in out
    assert "SOURCE_DISAGREEMENT" in out
    assert _digest(root) == before
