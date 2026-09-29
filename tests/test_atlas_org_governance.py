"""Governance foundation (registry v5.34): permissions, proposal lifecycle, memory provenance."""

from __future__ import annotations

import json

import pytest

from atlas_org import memory_records, permissions, proposals
from atlas_org.proposals import ProposalLogError, next_event, replay
from tools import atlas_org_cli

from atlas_org.security_review import CATEGORIES

SEC_PASS = {c: "PASS" for c in CATEGORIES}
KEY = b"k" * 32  # test-only owner key
from atlas_org.security_review import files_digest as _files_digest

BIND = {"files_reviewed": [], "files_digest": _files_digest({}), "base": "HEAD"}
AT = "2026-09-28T00:00:00Z"
FIELDS = {
    "title": "Market data reconnect", "problem": "stale feed", "motivation": "reliability",
    "proposed_changes": "bounded reconnect", "affected_components": ["market data"],
    "affected_files": ["atlas_finance/market_data/x.py"], "risk_level": "MEDIUM",
    "rollback_plan": "revert commit",
}


def _log(*steps):
    events = []
    for pid, ev, actor, payload in steps:
        events.append(next_event(events, proposal_id=pid, event=ev, actor=actor, at=AT, payload=payload))
    return events


def _ready_steps(pid="P-1"):
    return [
        (pid, "CREATE", "code_agent", FIELDS),
        (pid, "SUBMIT", "code_agent", {}),
        (pid, "RECORD_TESTS", "code_agent", {"command": "pytest", "passed": 10, "failed": 0}),
        (pid, "REVIEW", "code_review", {"kind": "CODE", "verdict": "PASS", "summary": "ok"}),
        (pid, "REVIEW", "security", {"kind": "SECURITY", "verdict": "PASS", "summary": "ok", "checks": SEC_PASS, "tool": "security_guardian", **BIND, "findings": []}),
        (pid, "MARK_READY", "executive_assistant", {}),
    ]


# ---------------------------------------------------------------- permissions

def test_ai_units_never_get_financial_execute_or_deploy_even_if_granted(monkeypatch):
    monkeypatch.setitem(permissions.GRANTS, "rogue", (permissions.Capability.DEPLOY,
                                                       permissions.Capability.FINANCIAL_EXECUTE))
    for cap in ("deploy", "financial_execute"):
        assert not permissions.authorize("rogue", cap).allowed
    assert permissions.granted("rogue") == frozenset()


def test_permissions_deny_by_default_and_unknown_capability():
    assert not permissions.authorize("nobody", "read_code").allowed
    assert not permissions.authorize("security", "modify_governance").allowed
    assert permissions.authorize("security", "read_code").allowed
    assert not permissions.authorize("agent_technical", "write_code").allowed


def test_every_grant_names_a_real_organization_unit():
    from observability.organization import ORGANIZATION

    ids = {u.unit_id for u in ORGANIZATION}
    assert set(permissions.GRANTS) <= ids


# ---------------------------------------------------------------- proposals

def test_happy_path_reaches_owner_and_only_owner_approves():
    events = _log(*_ready_steps())
    assert replay(events)["P-1"].status is proposals.ProposalStatus.READY_FOR_OWNER
    with pytest.raises(ProposalLogError, match="only the owner"):
        next_event(events, proposal_id="P-1", event="OWNER_APPROVE", actor="ceo_ai", at=AT)
    events.append(next_event(events, proposal_id="P-1", event="OWNER_APPROVE", actor="owner", at=AT, owner_key=KEY))
    events.append(next_event(events, proposal_id="P-1", event="MARK_APPLIED", actor="deployment_manager", at=AT))
    events.append(next_event(events, proposal_id="P-1", event="ROLL_BACK", actor="owner", at=AT, owner_key=KEY))
    p = replay(events)["P-1"]
    assert p.status is proposals.ProposalStatus.ROLLED_BACK
    assert p.owner_decision["decision"] == "APPROVED"


@pytest.mark.parametrize("drop", ["RECORD_TESTS", "CODE", "SECURITY"])
def test_cannot_reach_owner_without_tests_and_reviews(drop):
    steps = [s for s in _ready_steps()[:-1]
             if s[1] != drop and s[3].get("kind") != drop]
    events = _log(*steps)
    with pytest.raises(ProposalLogError):
        next_event(events, proposal_id="P-1", event="MARK_READY", actor="executive_assistant", at=AT)


def test_failing_tests_or_failed_review_block_ready():
    steps = _ready_steps()[:-1]
    steps[2] = ("P-1", "RECORD_TESTS", "code_agent", {"command": "pytest", "passed": 9, "failed": 1})
    with pytest.raises(ProposalLogError, match="failing"):
        _log(*steps, ("P-1", "MARK_READY", "executive_assistant", {}))
    steps = _ready_steps()[:-1]
    steps[4] = ("P-1", "REVIEW", "security", {"kind": "SECURITY", "verdict": "FAIL", "summary": "secret", "checks": {**SEC_PASS, "SECRETS": "FAIL"}, "tool": "security_guardian", **BIND, "findings": [{"category": "SECRETS", "level": "FAIL"}]})
    with pytest.raises(ProposalLogError, match="SECURITY"):
        _log(*steps, ("P-1", "MARK_READY", "executive_assistant", {}))


def test_author_cannot_review_own_proposal():
    with pytest.raises(ProposalLogError, match="own proposal"):
        _log(("P-1", "CREATE", "code_agent", FIELDS), ("P-1", "SUBMIT", "code_agent", {}),
             ("P-1", "REVIEW", "code_agent", {"kind": "CODE", "verdict": "PASS", "summary": "x"}))


def test_cannot_apply_without_approval_and_rejected_is_final():
    events = _log(*_ready_steps())
    with pytest.raises(ProposalLogError):
        next_event(events, proposal_id="P-1", event="MARK_APPLIED", actor="deployment_manager", at=AT)
    events.append(next_event(events, proposal_id="P-1", event="OWNER_REJECT", actor="owner", at=AT, owner_key=KEY))
    for ev in ("MARK_APPLIED", "OWNER_APPROVE", "SUPERSEDE"):
        with pytest.raises(ProposalLogError):
            next_event(events, proposal_id="P-1", event=ev, actor="owner", at=AT, owner_key=KEY)


def test_revision_invalidates_old_reviews():
    events = _log(*_ready_steps()[:-1], ("P-1", "REQUEST_REVISION", "code_review", {}),
                  ("P-1", "REVISE", "code_agent", {"proposed_changes": "v2"}))
    assert replay(events)["P-1"].revision == 2
    with pytest.raises(ProposalLogError):
        next_event(events, proposal_id="P-1", event="MARK_READY", actor="executive_assistant", at=AT)


def test_governance_change_must_be_critical_including_after_revision():
    bad = {**FIELDS, "affected_files": ["./CLAUDE.md"]}
    with pytest.raises(ProposalLogError, match="protected"):
        _log(("P-1", "CREATE", "code_agent", bad))
    with pytest.raises(ProposalLogError, match="protected"):
        _log(("P-1", "CREATE", "code_agent", FIELDS),
             ("P-1", "REVISE", "code_agent", {"affected_files": [".claude/settings.json"]}))
    _log(("P-1", "CREATE", "code_agent", {**bad, "risk_level": "CRITICAL"}))


def test_missing_rollback_plan_and_duplicate_create_refused():
    with pytest.raises(ProposalLogError, match="rollback_plan"):
        _log(("P-1", "CREATE", "code_agent", {**FIELDS, "rollback_plan": ""}))
    with pytest.raises(ProposalLogError, match="duplicate"):
        _log(("P-1", "CREATE", "a", FIELDS), ("P-1", "CREATE", "a", FIELDS))


@pytest.mark.parametrize("tamper", ["edit", "reorder", "drop", "duplicate"])
def test_tampered_log_is_refused_as_a_whole(tamper):
    events = _log(*_ready_steps())
    if tamper == "edit":
        events[3]["payload"]["verdict"] = "PASS"
        events[3]["actor"] = "code_agent"
    elif tamper == "reorder":
        events[2], events[3] = events[3], events[2]
    elif tamper == "drop":
        del events[2]
    else:
        events.insert(3, dict(events[2]))
    with pytest.raises(ProposalLogError):
        replay(events)


# ---------------------------------------------------------------- memory

MEM = {"record_id": "M-1", "type": "DECISION", "authority": "PROPOSED", "title": "t",
       "body": "b", "author": "knowledge_manager", "source": "registry v5.34", "at": AT}
RESEARCH_EVAL = {"project": "x", "license": "MIT", "maintenance": "active", "dependencies": "none",
                 "security_observations": "none found", "recommendation": "review further"}


def test_only_owner_writes_or_supersedes_authoritative_memory():
    with pytest.raises(ProposalLogError, match="owner"):
        memory_records.next_record([], **{**MEM, "authority": "AUTHORITATIVE"})
    log = [memory_records.next_record([], owner_key=KEY, **{**MEM, "authority": "AUTHORITATIVE", "author": "owner"})]
    with pytest.raises(ProposalLogError, match="owner"):
        memory_records.next_record(log, **{**MEM, "record_id": "M-2", "supersedes": "M-1"})
    log.append(memory_records.next_record(log, owner_key=KEY, **{**MEM, "record_id": "M-2", "supersedes": "M-1",
                                                  "author": "owner", "authority": "AUTHORITATIVE"}))
    view = {r["id"]: r for r in memory_records.public_view(memory_records.replay(log))}
    assert view["M-1"]["status"] == "HISTORICAL" and view["M-2"]["status"] == "CURRENT"


def test_research_needs_full_evaluation_and_is_never_authoritative():
    base = {**MEM, "type": "RESEARCH", "authority": "RESEARCH"}
    with pytest.raises(ProposalLogError, match="evaluation"):
        memory_records.next_record([], **base)
    memory_records.next_record([], **base, evaluation=RESEARCH_EVAL)
    with pytest.raises(ProposalLogError, match="never authoritative"):
        memory_records.next_record([], owner_key=KEY, **{**base, "authority": "AUTHORITATIVE", "author": "owner"},
                                   evaluation=RESEARCH_EVAL)


def test_memory_requires_provenance_source():
    with pytest.raises(ProposalLogError, match="source"):
        memory_records.next_record([], **{**MEM, "source": ""})


# ---------------------------------------------------------------- store + API

def test_cli_writes_chain_and_refuses_truncated_log(tmp_path):
    atlas_org_cli.add_proposal_event(tmp_path, proposal_id="P-1", event="CREATE", actor="a", payload=FIELDS)
    atlas_org_cli.add_proposal_event(tmp_path, proposal_id="P-1", event="SUBMIT", actor="a")
    assert atlas_org_cli.main(["--dir", str(tmp_path), "verify"]) == 0
    path = tmp_path / "proposals.jsonl"
    path.write_bytes(path.read_bytes()[:-5])
    with pytest.raises(ProposalLogError, match="truncated"):
        atlas_org_cli.add_proposal_event(tmp_path, proposal_id="P-1", event="REVISE", actor="a")
    assert atlas_org_cli.main(["--dir", str(tmp_path), "verify"]) == 1


def test_cli_owner_decision_needs_explicit_confirmation(tmp_path, monkeypatch):
    keyfile = tmp_path.parent / f"{tmp_path.name}_owner.key"
    keyfile.write_text("a" * 64)
    monkeypatch.setenv("ATLAS_OWNER_KEY_FILE", str(keyfile))
    for step in _ready_steps():
        atlas_org_cli.add_proposal_event(tmp_path, proposal_id=step[0], event=step[1], actor=step[2], payload=step[3])
    args = ["--dir", str(tmp_path), "proposal-event", "--id", "P-1", "--event", "OWNER_APPROVE", "--actor", "owner"]
    assert atlas_org_cli.main(args) == 2
    assert atlas_org_cli.main([*args, "--owner-confirm", "P-1"]) == 0


def test_readers_show_state_and_report_corruption_unavailable(tmp_path):
    from observability import governance_records as gr

    records = tmp_path / "governance" / "records"
    for step in _ready_steps():
        atlas_org_cli.add_proposal_event(records, proposal_id=step[0], event=step[1], actor=step[2], payload=step[3])
    atlas_org_cli.add_memory_record(records, MEM)
    out = gr.read_proposals(tmp_path)
    assert out["available"] and out["awaiting_owner"] == ["P-1"]
    assert gr.read_memory(tmp_path)["records"][0]["id"] == "M-1"
    lines = (records / "proposals.jsonl").read_text().splitlines()
    tampered = json.loads(lines[0]); tampered["actor"] = "owner"
    (records / "proposals.jsonl").write_text("\n".join([json.dumps(tampered), *lines[1:]]) + "\n")
    bad = gr.read_proposals(tmp_path)
    assert bad["available"] is False and "altered" in bad["reason"]


def test_api_routes_are_read_only_and_loopback(monkeypatch):
    from fastapi.testclient import TestClient

    import web_app

    client = TestClient(web_app.create_app())
    for path in ("/api/proposals", "/api/memory", "/api/permissions"):
        response = client.get(path)
        assert response.status_code in (200, 403)
        assert client.post(path).status_code == 405
