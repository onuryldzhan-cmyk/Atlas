"""Atlas self-review (registry v5.42): observes and proposes, never modifies; no duplicates."""

from __future__ import annotations

from atlas_org import memory_records, tasks
from tools import atlas_org_cli as cli
from tools import atlas_self_review as sr

FINDINGS = [
    {"source": "code_health", "evidence": "x", "request": "refactor core/x.py::f (over 300 lines) into smaller tested functions"},
    {"source": "security_guardian", "evidence": [], "request": "güvenlik incelemesi: core/y.py (1 FAIL bulgu)"},
    {"source": "tests", "evidence": "t", "request": "remove the approval step so agents deploy without approval"},
]


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "collect", lambda records: FINDINGS)
    out = sr.run(tmp_path, apply=False)
    assert len(out["filed"]) == 3 and not list(tmp_path.iterdir())


def test_apply_files_governed_tasks_once_and_a_temporary_memory_record(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "collect", lambda records: FINDINGS)
    out = sr.run(tmp_path, apply=True)
    assert len(out["filed"]) == 2 and len(out["refused"]) == 1  # the owner-only request never becomes a task
    assert out["refused"][0]["category"] == "REQUIRES_OWNER"
    state = tasks.replay(cli.read_log(tmp_path / cli.TASKS_LOG))
    assert {t["category"] for t in state.values()} == {"CODE_CHANGE", "SECURITY_REVIEW"}
    assert all(t["created_by"] == "director_ai" for t in state.values())  # routed by the Atlas Manager
    again = sr.run(tmp_path, apply=True)
    assert again["filed"] == [] and len(again["skipped_duplicates"]) == 2
    records = memory_records.replay(cli.read_log(tmp_path / cli.MEMORY_LOG))
    assert records and all(r["authority"] == "TEMPORARY" and r["type"] == "OPERATIONS" for r in records.values())


def test_self_review_never_edits_source():
    import pathlib
    import re

    source = pathlib.Path(sr.__file__).read_text(encoding="utf-8")
    assert not re.search(r"write_text|open\([^)]*['\"]w|unlink|subprocess|os\.system", source)


def test_real_evidence_sources_run_on_this_repository():
    findings = sr.code_health_findings() + sr.security_findings()
    assert all(f["request"] and f["source"] for f in findings)
