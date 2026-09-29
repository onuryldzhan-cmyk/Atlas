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
    assert state(out, "owner")["state"] == "WAITING_FOR_HUMAN"
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
