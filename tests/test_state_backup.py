"""DR drill (audit F-6): a real backup -> verify -> restore, and a corrupted backup is never used."""

import json
from datetime import datetime, timezone

import pytest

from tools import state_backup as sb


def make_state(root):
    (root / "audit").mkdir(parents=True)
    (root / "financial_state.json").write_text(json.dumps({"schema": "fin-v1", "cash": "9000.00"}), encoding="utf-8")
    (root / "audit" / "events.jsonl").write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    (root / ".env").write_text("API_KEY=do-not-copy", encoding="utf-8")
    (root / "api_key.txt").write_text("secret", encoding="utf-8")


def test_backup_restore_roundtrip_is_byte_identical_and_skips_secrets(tmp_path):
    state = tmp_path / "state"
    make_state(state)
    dest = sb.backup({"state": state}, tmp_path / "bk", now=datetime(2026, 9, 30, tzinfo=timezone.utc))
    manifest = sb.verify(dest)
    paths = {e["path"] for e in manifest["files"]}
    assert paths == {"state/financial_state.json", "state/audit/events.jsonl"}
    assert next(e for e in manifest["files"] if e["path"].endswith("financial_state.json"))["schema"] == "fin-v1"
    out = sb.restore(dest, tmp_path / "restored")
    assert out["restored_files"] == 2
    assert (tmp_path / "restored" / "state" / "financial_state.json").read_bytes() == (state / "financial_state.json").read_bytes()


def test_corrupted_backup_is_refused(tmp_path):
    state = tmp_path / "state"
    make_state(state)
    dest = sb.backup({"state": state}, tmp_path / "bk")
    (dest / "state" / "financial_state.json").write_text('{"cash": "999999"}', encoding="utf-8")
    with pytest.raises(sb.BackupError, match="CORRUPTED"):
        sb.restore(dest, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_missing_or_extra_file_and_nonempty_target_are_refused(tmp_path):
    state = tmp_path / "state"
    make_state(state)
    dest = sb.backup({"state": state}, tmp_path / "bk")
    (dest / "state" / "planted.json").write_text("{}", encoding="utf-8")
    with pytest.raises(sb.BackupError, match="CORRUPTED"):
        sb.verify(dest)
    (dest / "state" / "planted.json").unlink()
    live = tmp_path / "live"
    live.mkdir()
    (live / "x").write_text("in use", encoding="utf-8")
    with pytest.raises(sb.BackupError, match="REFUSED"):
        sb.restore(dest, live)
