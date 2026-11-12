"""Change notes (owner 2026-10-03): what changed, what was fixed and how Atlas looks since - from git, read-only."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from atlas_org import memory_records
from tools import atlas_org_cli as cli
from tools import change_log as cl

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _commit(repo, path, subject):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(subject, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", subject)


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    return repo


def _notes(records):
    log = records / cli.MEMORY_LOG
    recs = memory_records.replay(cli.read_log(log)).values() if log.exists() else []
    return sorted((r for r in recs if r["author"] == "deployment_manager"), key=lambda r: r["seq"])


def test_new_commits_become_one_note_with_areas_fixes_and_state(tmp_path):
    repo, records = _repo(tmp_path), tmp_path / "records"
    _commit(repo, "core/risk.py", "Risk gate tidy-up")
    _commit(repo, "tools/agent.py", "Fix agent schedule bug")
    out = cl.run(records, root=repo)
    notes = _notes(records)
    assert out["verdict"] == "OK" and len(notes) == 1 and notes[0]["type"] == "DEVELOPMENT"
    body = json.loads(notes[0]["body"])
    assert [c["subject"] for c in body["commits"]] == ["Risk gate tidy-up", "Fix agent schedule bug"]  # oldest first
    assert body["fixes"] == ["Fix agent schedule bug"]
    assert body["areas"] == {"çekirdek (karar / risk / işlem)": 1, "ajanlar ve araçlar": 1}
    assert body["since_previous_note"] is None and "state_now" in body
    assert cl.run(records, root=repo)["summary"] == "yeni değişiklik yok" and len(_notes(records)) == 1


def test_the_next_note_holds_only_the_new_commits_and_what_changed_since(tmp_path):
    repo, records = _repo(tmp_path), tmp_path / "records"
    _commit(repo, "a.txt", "first")
    cl.run(records, root=repo)
    cli.add_memory_record(records, {"record_id": "PR-0100", "type": "EXPERIMENTS", "authority": "RESEARCH",
                                    "title": "Performans", "author": "quant_research", "source": "t",
                                    "body": json.dumps({"total": {"trades": 12, "est_net_pnl": "-3.5", "verdict": "WEAK"}})})
    _commit(repo, "templates/x.html", "Panel tweak")
    cl.run(records, root=repo)
    second = json.loads(_notes(records)[-1]["body"])
    assert [c["subject"] for c in second["commits"]] == ["Panel tweak"]
    assert second["state_now"]["trades"] == 12 and second["since_previous_note"]["verdict"] == "None -> WEAK"
    assert second["previous_note"] == _notes(records)[0]["id"]


def test_rewritten_history_starts_again_from_the_latest_commits(tmp_path):
    repo, records = _repo(tmp_path), tmp_path / "records"
    _commit(repo, "a.txt", "one")
    cl.run(records, root=repo)
    _git(repo, "commit", "-q", "--amend", "-m", "one, reworded")               # the noted commit no longer exists
    out = cl.run(records, root=repo)
    assert "geçmiş yeniden yazılmış" in out["summary"] and json.loads(_notes(records)[-1]["body"])["found"] == "history-changed"


def test_without_git_history_it_warns_and_writes_nothing(tmp_path):
    out = cl.run(tmp_path / "records", root=tmp_path)                          # not a repository
    assert out["verdict"] == "WARN" and _notes(tmp_path / "records") == []
