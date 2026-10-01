"""Atlas HQ backbone: every agent state comes from a record; nothing is invented."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import web_app
from observability.agent_states import build

NOW = datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)
OFF = {"available": False}


def state(out, uid):
    return next(a for a in out["agents"] if a["id"] == uid)


def test_no_evidence_means_offline_not_working():
    out = build(OFF, OFF, OFF, None, NOW)
    assert {a["state"] for a in out["agents"]} == {"OFFLINE"} and out["flows"] == []


def test_assigned_steps_wait_and_hand_offs_are_flows():
    tasks = {"available": True, "tasks": [{"id": "T-1", "status": "IN_PROGRESS", "steps": [
        {"unit": "open_source_research", "status": "ASSIGNED", "goal": "g1"},
        {"unit": "code_engineering", "status": "BLOCKED", "goal": "g2"}]}]}
    out = build(tasks, OFF, OFF, None, NOW)
    assert state(out, "open_source_research")["state"] == "WAITING"
    assert "çalıştırıcı bekliyor" in state(out, "open_source_research")["doing"]
    assert state(out, "code_engineering")["state"] == "BLOCKED"
    assert {"from": "open_source_research", "to": "code_engineering", "kind": "task", "label": "T-1"} in out["flows"]


def test_open_proposal_waits_for_the_owner_and_cycle_errors_show():
    proposals = {"available": True, "proposals": [{"id": "SA-FEE-DRAG.1", "status": "DRAFT", "author": "strategy_lab", "reviews": []}]}
    body = json.dumps({"agent_cycle": [{"unit": "quant_research", "verdict": "OK", "summary": "9 işlem"},
                                       {"unit": "data_quality", "verdict": "FAIL", "summary": "archive locked"}]})
    memory = {"available": True, "records": [
        {"id": "AC-0001", "seq": 1, "type": "OPERATIONS", "created_at": "2026-09-29T17:30:00Z", "body": body, "author": "executive_assistant"},
        {"id": "RT-0002", "seq": 2, "type": "REVIEWS", "author": "red_team", "related_proposal": "SA-FEE-DRAG.1", "title": "Karşı görüş"}]}
    out = build(OFF, proposals, memory, None, NOW)
    # 2026-10-01: a DRAFT is not yet the owner's decision; only READY_FOR_OWNER waits on the
    # owner (same definition as governance_records.awaiting_owner / the Command Center counter).
    assert state(out, "owner")["state"] == "IDLE" and "hazırlık" in state(out, "owner")["doing"]
    ready = {"available": True, "proposals": [{**proposals["proposals"][0], "status": "READY_FOR_OWNER"}]}
    assert state(build(OFF, ready, memory, None, NOW), "owner")["state"] == "WAITING_FOR_HUMAN"
    assert state(out, "data_quality")["state"] == "ERROR"
    assert state(out, "quant_research")["state"] == "IDLE" and state(out, "quant_research")["source"] == "AC-0001"
    assert state(out, "red_team")["state"] == "REVIEWING"
    assert {"from": "strategy_lab", "to": "owner", "kind": "proposal", "label": "SA-FEE-DRAG.1"} in out["flows"]


def test_old_cycle_does_not_claim_activity():
    body = json.dumps({"agent_cycle": [{"unit": "quant_research", "verdict": "OK", "summary": "x"}]})
    memory = {"available": True, "records": [{"id": "AC-0001", "seq": 1, "type": "OPERATIONS",
                                               "created_at": "2026-09-28T10:00:00Z", "body": body}]}
    assert state(build(OFF, OFF, memory, None, NOW), "quant_research")["state"] == "OFFLINE"


def test_voting_agents_follow_the_market_loop():
    signals = {"status": "SUCCESS", "signals": {"BTCUSDT": {"agents": {
        "technical": {"status": "EVALUATED"}, "sentiment": {"status": "EXCLUDED"}}}}}
    out = build(OFF, OFF, OFF, signals, NOW)
    assert state(out, "agent_technical")["state"] == "WORKING"
    assert state(out, "agent_sentiment")["state"] == "IDLE"
    assert state(out, "atlas_manager")["state"] == "WORKING"


def test_endpoint_is_read_only_and_loopback_guarded():
    assert TestClient(web_app.create_app()).get("/api/agent-states").json()["available"] is True
    assert TestClient(web_app.create_app(), base_url="http://evil.example").get("/api/agent-states").status_code == 403


def test_activity_feed_is_real_records_only_and_categorised():
    from observability import agent_states

    empty = agent_states.build({"available": False}, {"available": False}, {"available": False}, None)
    assert empty["activity"] == [] and all(a["history"] == [] for a in empty["agents"])
    mem = {"available": True, "records": [
        {"id": "MR-0001", "type": "EXPERIMENTS", "author": "market_regime", "title": "Piyasa rejimi", "created_at": "2026-09-30T01:00:00+00:00"},
        {"id": "SG-0001", "type": "OPERATIONS", "author": "security", "title": "scan", "created_at": "2026-09-30T02:00:00+00:00"},
        {"id": "RT-0001", "type": "REVIEWS", "author": "red_team", "title": "review", "created_at": "2026-09-30T03:00:00+00:00", "related_proposal": "SA-X.1"}]}
    out = agent_states.build({"available": False}, {"available": False}, mem, None)
    assert [e["category"] for e in out["activity"]] == ["GOVERNANCE", "SECURITY", "RUNTIME"]
    assert next(a for a in out["agents"] if a["id"] == "market_regime")["history"][0]["source"] == "MR-0001"
