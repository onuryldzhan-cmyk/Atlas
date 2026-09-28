"""tools/quarantine_audit_fork.py: move a fork branch out, never edit it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import main
from core import instance_lock
from core.audit_event_store import AuditChainIntegrityError, AuditEventStore
from main import AtlasProcess
from tools import quarantine_audit_fork as tool

KW = dict(source="t", aggregate_type="x", payload={})


@pytest.fixture(autouse=True)
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(instance_lock, "RETRY_SECONDS", 0.0)
    return tmp_path


def forked_log(tmp_path: Path) -> Path:
    """The 2026-09-28 shape: A writes 3, B forks from line 3 with 2 events,
    A carries on from line 3 with 3 more. Lines 4-5 are the fork branch."""

    path = tmp_path / "audit.jsonl"
    a = AuditEventStore(path)
    for i in range(3):
        a.append(event_type="E", aggregate_id=f"a{i}", **KW)
    b = AuditEventStore(path)
    b.append(event_type="RECEIVED", aggregate_id="b0", **KW)
    b.append(event_type="DUPLICATE", aggregate_id="b0", **KW)
    for i in range(3, 6):
        a.append(event_type="E", aggregate_id=f"a{i}", **KW)
    return path


def test_the_fixture_reproduces_the_incident(tmp_path):
    path = forked_log(tmp_path)
    with pytest.raises(AuditChainIntegrityError):
        AuditEventStore(path)


def test_dry_run_writes_nothing(tmp_path, capsys):
    path = forked_log(tmp_path)
    before = path.read_bytes()
    assert tool.main([str(path), "--lines", "4-5"]) == 0

    assert path.read_bytes() == before
    # Only the instance lock file (taken to exclude a running Atlas) appears.
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        main.INSTANCE_LOCK_FILE_NAME, "audit.jsonl",
    ]
    assert "DRY RUN" in capsys.readouterr().out


def test_apply_moves_the_branch_byte_for_byte_and_the_chain_loads(tmp_path):
    path = forked_log(tmp_path)
    original = path.read_bytes()
    raw = original.splitlines(keepends=True)

    assert tool.main([str(path), "--lines", "4-5", "--apply"]) == 0

    store = AuditEventStore(path)  # verifies on load
    assert store.status()["event_count"] == 6
    assert path.read_bytes() == b"".join(raw[:3] + raw[5:])

    quarantine = next(tmp_path.glob("audit.quarantine_*.jsonl"))
    assert quarantine.read_bytes() == b"".join(raw[3:5])
    backup = next(tmp_path.glob("audit.pre_quarantine_*.jsonl"))
    assert backup.read_bytes() == original

    manifest = json.loads(next(tmp_path.glob("audit.quarantine_*.manifest.json")).read_text())
    assert [m["original_line"] for m in manifest["moved"]] == [4, 5]
    assert [m["event_type"] for m in manifest["moved"]] == ["RECEIVED", "DUPLICATE"]


def test_appending_after_repair_keeps_a_valid_chain(tmp_path):
    path = forked_log(tmp_path)
    tool.main([str(path), "--lines", "4-5", "--apply"])

    AuditEventStore(path).append(event_type="E", aggregate_id="after", **KW)

    AuditEventStore(path)


@pytest.mark.parametrize("lines", ["4-4", "5-5", "3-5", "4-6", "6-8", "1-2"])
def test_anything_but_the_exact_branch_is_refused(tmp_path, lines, capsys):
    path = forked_log(tmp_path)
    before = path.read_bytes()

    assert tool.main([str(path), "--lines", lines, "--apply"]) == 2

    assert path.read_bytes() == before
    assert "REFUSED" in capsys.readouterr().out
    assert not list(tmp_path.glob("audit.quarantine_*"))


def test_an_intact_chain_is_refused(tmp_path, capsys):
    path = tmp_path / "audit.jsonl"
    store = AuditEventStore(path)
    for i in range(4):
        store.append(event_type="E", aggregate_id=f"a{i}", **KW)

    assert tool.main([str(path), "--lines", "2-3", "--apply"]) == 2
    assert "exactly one chain break" in capsys.readouterr().out


def test_a_tampered_event_is_refused(tmp_path, capsys):
    path = forked_log(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    data = json.loads(lines[3])
    data["payload"] = {"tampered": True}
    lines[3] = json.dumps(data, sort_keys=True) + "\n"
    path.write_text("".join(lines), encoding="utf-8")

    assert tool.main([str(path), "--lines", "4-5", "--apply"]) == 2
    assert "REFUSED" in capsys.readouterr().out


def test_refused_while_an_atlas_instance_holds_the_lock(tmp_path, capsys):
    import subprocess
    import sys

    path = forked_log(tmp_path)
    before = path.read_bytes()

    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys; from pathlib import Path; from core import instance_lock;"
         "instance_lock.acquire(Path(sys.argv[1])); print('HELD', flush=True);"
         "sys.stdin.readline()",
         str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    try:
        assert holder.stdout.readline().strip() == "HELD"
        assert tool.main([str(path), "--lines", "4-5", "--apply"]) == 2
    finally:
        holder.stdin.write("\n")
        holder.stdin.flush()
        holder.wait(timeout=10)

    assert path.read_bytes() == before
    assert "Another Atlas instance" in capsys.readouterr().out


def test_second_apply_is_refused_because_nothing_is_broken(tmp_path):
    path = forked_log(tmp_path)
    assert tool.main([str(path), "--lines", "4-5", "--apply"]) == 0
    repaired = path.read_bytes()

    assert tool.main([str(path), "--lines", "4-5", "--apply"]) == 2
    assert path.read_bytes() == repaired


def test_a_branch_holding_an_experiment_admission_is_refused(tmp_path, capsys):
    """Moving an EXP-001 RISK_APPROVED event out would lower the restored
    admission count and silently re-open the experiment."""

    path = tmp_path / "audit.jsonl"
    a = AuditEventStore(path)
    for i in range(3):
        a.append(event_type="E", aggregate_id=f"a{i}", **KW)
    b = AuditEventStore(path)
    b.append(event_type="RISK_APPROVED", source="t", aggregate_type="x", aggregate_id="b0",
             payload={"approved": True, "details": {"experiment_id": "EXP-001"}})
    b.append(event_type="DUPLICATE", aggregate_id="b0", **KW)
    for i in range(3, 5):
        a.append(event_type="E", aggregate_id=f"a{i}", **KW)
    before = path.read_bytes()

    assert tool.main([str(path), "--lines", "4-5", "--apply"]) == 2

    assert path.read_bytes() == before
    assert "experiment admission" in capsys.readouterr().out
