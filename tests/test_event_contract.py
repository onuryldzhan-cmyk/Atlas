"""Atlas Event Contract v1: strict, redacted, evidence-only, never invents agent activity."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from observability.event_contract import (
    AGENT_STATUSES, UNSOURCED_STATUSES, EventContractError, agent_state, validate_event)

NOW = datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)


def ev(**over):
    base = {"event_id": "evt_001", "event_type": "agent.tool.started", "timestamp": "2026-10-01T19:59:00Z",
            "agent": {"id": "quant_research", "role": "quant"}, "run": {"id": "run_1", "task_id": "t-1"},
            "payload": {"tool": "python"}}
    base.update(over)
    return base


def test_valid_event_is_canonical():
    e = validate_event(ev())
    assert e["schema"] == "atlas.event.v1" and e["timestamp"].endswith("+00:00")


@pytest.mark.parametrize("bad", [
    ev(event_type="agent.dance"), ev(timestamp="yesterday"), ev(timestamp="2026-10-01T19:59:00"),
    ev(agent={"id": "Quant Agent!"}), ev(event_id=""), ev(payload=["x"]), ev(schema="openclaw.v3"),
    ev(payload={"blob": "x" * 5000}), "not an event", ev(agent="quant"),
])
def test_malformed_events_are_rejected_not_coerced(bad):
    with pytest.raises(EventContractError):
        validate_event(bad)


def test_secrets_in_payload_are_redacted():
    e = validate_event(ev(payload={"note": "api_key=sk-abc123456789abcdef"}))
    assert "sk-abc123456789abcdef" not in str(e["payload"])


def test_no_events_means_offline_never_invented():
    assert agent_state("quant_research", [], now=NOW)["status"] == "offline"


def test_state_follows_the_real_last_event():
    events = [validate_event(ev()), validate_event(ev(event_id="evt_002", agent={"id": "red_team"}, event_type="agent.failed"))]
    s = agent_state("quant_research", events, now=NOW)
    assert s["status"] == "researching" and s["current_tool"] == "python" and s["current_task"] == "t-1"
    assert agent_state("red_team", events, now=NOW)["status"] == "error"


def test_stale_activity_goes_offline_but_problems_stay_visible():
    old = "2026-10-01T10:00:00Z"
    events = [validate_event(ev(timestamp=old)), validate_event(ev(event_id="e2", agent={"id": "x1"}, event_type="agent.task.blocked", timestamp=old))]
    assert agent_state("quant_research", events, now=NOW)["status"] == "offline"
    assert agent_state("x1", events, now=NOW)["status"] == "blocked"


def test_unsourced_statuses_are_declared_and_never_derived():
    assert UNSOURCED_STATUSES <= AGENT_STATUSES
    derived = {agent_state("a", [validate_event(ev(event_type=t, agent={"id": "a"}))], now=NOW)["status"]
               for t in ("agent.tool.started", "agent.task.started", "agent.failed", "agent.task.blocked",
                         "agent.approval.requested", "agent.cycle.completed")}
    assert derived <= AGENT_STATUSES and not (derived & UNSOURCED_STATUSES)


def test_adapter_turns_real_records_into_events_and_skips_misfits():
    import json as _json
    from observability.event_contract import events_from_records

    records = [
        {"id": "AC-0001", "created_at": "2026-10-01T19:00:00+00:00", "author": "executive_assistant",
         "body": _json.dumps({"agent_cycle": [{"unit": "quant_research", "verdict": "OK", "summary": "12 işlem"},
                                              {"unit": "red_team", "verdict": "FAIL", "summary": "api_key=sk-abc123456789abcdef"}]})},
        {"id": "INC-0001", "type": "INCIDENTS", "created_at": "2026-10-01T19:01:00+00:00", "author": "security", "title": "x"},
        {"id": "MEM-1", "created_at": "not a time", "author": "x", "title": "bad"},
    ]
    proposals = [{"id": "SA-1", "status": "READY_FOR_OWNER", "author": "strategy_lab", "created_at": "2026-10-01T19:02:00+00:00"}]
    out = events_from_records(records, proposals)
    types = [(e["agent"]["id"], e["event_type"]) for e in out["events"]]
    assert ("quant_research", "agent.cycle.completed") in types and ("red_team", "agent.failed") in types
    assert ("security", "incident.opened") in types and ("strategy_lab", "agent.approval.requested") in types
    assert out["skipped"] == 1
    assert all(e["payload"].get("source") for e in out["events"])  # every event has a record behind it
    assert "sk-abc123456789abcdef" not in str(out)
    now = datetime(2026, 10, 1, 19, 10, tzinfo=timezone.utc)
    assert agent_state("red_team", out["events"], now=now)["status"] == "error"
    assert agent_state("strategy_lab", out["events"], now=now)["status"] == "waiting_approval"
    assert agent_state("market_regime", out["events"], now=now)["status"] == "offline"


def test_events_api_is_read_only_and_loopback_guarded():
    from fastapi.testclient import TestClient

    import web_app

    r = TestClient(web_app.create_app()).get("/api/events")
    assert r.status_code == 200 and r.json()["schema"] == "atlas.event.v1"
    assert TestClient(web_app.create_app(), base_url="http://evil.example").get("/api/events").status_code == 403
    assert TestClient(web_app.create_app()).post("/api/events").status_code in (403, 405)
