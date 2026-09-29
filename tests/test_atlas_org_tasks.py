"""Atlas Manager + task lifecycle (registry v5.35)."""

from __future__ import annotations

import pytest

from atlas_org import manager, proposals, tasks
from atlas_org.tasks import TaskLogError
from tools import atlas_org_cli as cli

from atlas_org.security_review import CATEGORIES

SEC_PASS = {c: "PASS" for c in CATEGORIES}
from atlas_org.security_review import files_digest as _files_digest

BIND = {"files_reviewed": [], "files_digest": _files_digest({}), "base": "HEAD"}
AT = "2026-09-29T00:00:00Z"


@pytest.mark.parametrize("request_text, category", [
    ("Atlas, bu kütüphaneyi GitHub'da araştır", "RESEARCH"),
    ("investigate the market-data reliability problem", "RESEARCH"),
    ("market data reconnect hatasını düzelt", "CODE_CHANGE"),
    ("güvenlik taraması yap", "SECURITY_REVIEW"),
    ("API gecikmesi neden yavaş", "PERFORMANCE"),
    ("son hafta portföy zarar analizi", "TRADING_ANALYSIS"),
])
def test_classification(request_text, category):
    assert manager.classify(request_text).category == category


@pytest.mark.parametrize("request_text", [
    "canlı işlem başlat", "deploy to production", "risk limitini yükselt",
    "bundan sonra onay gerekmesin", "governance kurallarını değiştir",
    "security ajanına yetki ver", "gerçek para ile al",
])
def test_requests_needing_owner_authority_never_become_tasks(tmp_path, request_text):
    out = cli.request_task(tmp_path, request_text, at=AT)
    assert out["created"] is False and out["category"] == "REQUIRES_OWNER"
    assert not (tmp_path / "tasks.jsonl").exists()


def test_unclear_request_is_not_guessed(tmp_path):
    assert cli.request_task(tmp_path, "merhaba", at=AT)["category"] == "UNCLEAR"


def test_every_plan_step_routes_to_an_authorized_unit():
    for category, steps in manager.PLANS.items():
        for step in steps:
            assert manager.route(step.role, step.capability), (category, step)


def _run_step(d, tid, step, verdict="PASS"):
    t = tasks.replay(cli.read_log(d / "tasks.jsonl"))[tid]
    unit = t["steps"][step]["unit"]
    cli.add_task_event(d, task_id=tid, event="START", actor=unit, payload={"step": step}, at=AT)
    cli.add_task_event(d, task_id=tid, event="RESULT", actor=unit,
                       payload={"step": step, "verdict": verdict, "summary": f"step {step}"}, at=AT)
    return unit


def test_workflow_b_code_change_reaches_owner_decision_only(tmp_path):
    out = cli.request_task(tmp_path, "market data reconnect hatasını düzelt", at=AT)
    tid = out["task_id"]
    assert out["created"] and out["unrouted_steps"] == []
    t = tasks.replay(cli.read_log(tmp_path / "tasks.jsonl"))[tid]
    units = [s["unit"] for s in t["steps"]]
    assert units == ["open_source_research", "code_engineering", "code_engineering", "code_review", "security"]
    with pytest.raises(TaskLogError, match="incomplete"):
        cli.add_task_event(tmp_path, task_id=tid, event="LINK_PROPOSAL", actor=tasks.ASSISTANT,
                           payload={"proposal_id": "P-1"}, at=AT)
    for i in range(5):
        _run_step(tmp_path, tid, i)
    cli.add_task_event(tmp_path, task_id=tid, event="LINK_PROPOSAL", actor=tasks.ASSISTANT,
                       payload={"proposal_id": "P-1"}, at=AT)
    cli.add_task_event(tmp_path, task_id=tid, event="COMPLETE", actor=tasks.ASSISTANT, at=AT)

    fields = {"title": "reconnect", "problem": "stale", "motivation": "reliability", "proposed_changes": "x",
              "affected_components": ["market data"], "affected_files": ["a.py"], "risk_level": "MEDIUM",
              "rollback_plan": "revert", "related_task": tid}
    for ev, actor, payload in [
        ("CREATE", "code_engineering", fields), ("SUBMIT", "code_engineering", {}),
        ("RECORD_TESTS", "code_engineering", {"command": "pytest", "passed": 5, "failed": 0}),
        ("REVIEW", "code_review", {"kind": "CODE", "verdict": "PASS", "summary": "ok"}),
        ("REVIEW", "security", {"kind": "SECURITY", "verdict": "PASS", "summary": "ok", "checks": SEC_PASS, "tool": "security_guardian", **BIND, "findings": []}),
        ("MARK_READY", tasks.ASSISTANT, {}),
    ]:
        cli.add_proposal_event(tmp_path, proposal_id="P-1", event=ev, actor=actor, payload=payload, at=AT)
    state = proposals.replay(cli.read_log(tmp_path / "proposals.jsonl"))["P-1"]
    assert state.status is proposals.ProposalStatus.READY_FOR_OWNER  # waits for the owner, never auto-approved
    assert tasks.replay(cli.read_log(tmp_path / "tasks.jsonl"))[tid]["status"] == "DONE"


def test_assignment_is_checked_against_permissions(tmp_path):
    tid = cli.request_task(tmp_path, "bu kütüphaneyi araştır", at=AT)["task_id"]
    t = tasks.replay(cli.read_log(tmp_path / "tasks.jsonl"))[tid]
    cli.add_task_event(tmp_path, task_id=tid, event="BLOCK", actor=tasks.MANAGER,
                       payload={"step": 0, "reason": "reassign"}, at=AT)
    with pytest.raises(TaskLogError, match="cannot web_research"):
        cli.add_task_event(tmp_path, task_id=tid, event="ASSIGN", actor=tasks.MANAGER,
                           payload={"step": 0, "unit": "agent_technical"}, at=AT)
    with pytest.raises(TaskLogError, match="only the managers"):
        cli.add_task_event(tmp_path, task_id=tid, event="ASSIGN", actor="security",
                           payload={"step": 0, "unit": "open_source_research"}, at=AT)
    assert t["steps"][0]["unit"] == "open_source_research"


def test_only_assigned_unit_reports_and_conflicts_block_completion(tmp_path):
    tid = cli.request_task(tmp_path, "güvenlik taraması yap", at=AT)["task_id"]
    with pytest.raises(TaskLogError, match="only the assigned unit"):
        cli.add_task_event(tmp_path, task_id=tid, event="START", actor="code_review", payload={"step": 0}, at=AT)
    _run_step(tmp_path, tid, 0, "PASS")
    _run_step(tmp_path, tid, 1, "FAIL")  # both steps read_code: PASS vs FAIL is a conflict
    t = tasks.replay(cli.read_log(tmp_path / "tasks.jsonl"))[tid]
    assert tasks.completeness(t)["conflicts"] == ["read_code"]
    with pytest.raises(TaskLogError, match="conflicting"):
        cli.add_task_event(tmp_path, task_id=tid, event="COMPLETE", actor=tasks.ASSISTANT, at=AT)


def test_only_owner_cancels_and_agent_activity_is_derived(tmp_path, monkeypatch):
    keyfile = tmp_path.parent / f"{tmp_path.name}_owner.key"
    keyfile.write_text("a" * 64)
    monkeypatch.setenv("ATLAS_OWNER_KEY_FILE", str(keyfile))
    tid = cli.request_task(tmp_path, "bu kütüphaneyi araştır", at=AT)["task_id"]
    cli.add_task_event(tmp_path, task_id=tid, event="START", actor="open_source_research", payload={"step": 0}, at=AT)
    state = tasks.replay(cli.read_log(tmp_path / "tasks.jsonl"))
    activity = tasks.agent_activity(state)
    assert activity["open_source_research"]["status"] == "WORKING"
    assert activity["security"]["status"] == "WAITING"
    with pytest.raises(TaskLogError, match="owner"):
        cli.add_task_event(tmp_path, task_id=tid, event="CANCEL", actor=tasks.MANAGER, at=AT)
    assert cli.main(["--dir", str(tmp_path), "task-event", "--id", tid, "--event", "CANCEL", "--actor", "owner"]) == 2
    assert cli.main(["--dir", str(tmp_path), "task-event", "--id", tid, "--event", "CANCEL",
                     "--actor", "owner", "--owner-confirm", tid]) == 0


def test_only_manager_or_owner_creates_and_tampering_refused(tmp_path):
    with pytest.raises(TaskLogError, match="only the Atlas Manager"):
        tasks.next_event([], task_id="T-1", event="CREATE", actor="security", at=AT,
                         payload=manager.classify("güvenlik taraması").to_payload("x"))
    cli.request_task(tmp_path, "güvenlik taraması yap", at=AT)
    events = cli.read_log(tmp_path / "tasks.jsonl")
    events[1]["payload"]["unit"] = "agent_technical"
    with pytest.raises(TaskLogError, match="altered"):
        tasks.replay(events)


def test_tasks_reader(tmp_path):
    from observability import governance_records as gr

    d = tmp_path / "governance" / "records"
    cli.request_task(d, "bu kütüphaneyi araştır", at=AT)
    out = gr.read_tasks(tmp_path)
    assert out["available"] and out["tasks"][0]["category"] == "RESEARCH"
    assert out["agents"]["open_source_research"]["status"] == "WAITING"


def test_workflow_a_research_ends_in_a_provenanced_memory_record(tmp_path):
    from atlas_org import memory_records

    tid = cli.request_task(tmp_path, "Atlas, TradingView lightweight-charts kütüphanesini araştır", at=AT)["task_id"]
    t = tasks.replay(cli.read_log(tmp_path / "tasks.jsonl"))[tid]
    assert [s["unit"] for s in t["steps"]] == ["open_source_research", "security", "knowledge_manager"]
    evaluation = {"project": "tradingview/lightweight-charts", "license": "Apache-2.0 + attribution",
                  "maintenance": "active", "dependencies": "none at runtime",
                  "security_observations": "static JS, vendor with SHA-256", "recommendation": "review further"}
    for i in range(3):
        unit = t["steps"][i]["unit"]
        cli.add_task_event(tmp_path, task_id=tid, event="START", actor=unit, payload={"step": i}, at=AT)
        if unit == "knowledge_manager":
            cli.add_memory_record(tmp_path, {"record_id": "M-R1", "type": "RESEARCH", "authority": "RESEARCH",
                                             "title": "lightweight-charts", "body": "evaluation",
                                             "author": unit, "source": "task " + tid, "related_task": tid,
                                             "evaluation": evaluation, "at": AT})
        cli.add_task_event(tmp_path, task_id=tid, event="RESULT", actor=unit,
                           payload={"step": i, "verdict": "INFO" if i != 1 else "PASS", "summary": f"s{i}",
                                    "evidence": ["M-R1"] if unit == "knowledge_manager" else []}, at=AT)
    cli.add_task_event(tmp_path, task_id=tid, event="COMPLETE", actor=tasks.ASSISTANT, at=AT)
    record = memory_records.replay(cli.read_log(tmp_path / "memory.jsonl"))["M-R1"]
    assert record["related_task"] == tid and record["authority"] == "RESEARCH"
    assert tasks.replay(cli.read_log(tmp_path / "tasks.jsonl"))[tid]["status"] == "DONE"
