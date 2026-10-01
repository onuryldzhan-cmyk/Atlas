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
