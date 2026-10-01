"""Stage A1 (2026-10-01): one source of agent state for every surface.

Before: /api/command-center derived agent state from the task log only ("no
agent running") while /api/agent-states also read memory and live votes
("6/20 working"). Both now come from observability.agent_states.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import web_app
from observability import agent_states, command_center as cc

EMPTY = {"available": True}


def _states(signals=None):
    return agent_states.build({"available": True, "tasks": []}, {"available": True, "proposals": []},
                              {"available": True, "records": []}, signals)


def test_compose_uses_agent_states_when_given():
    sig = {"status": "SUCCESS", "signals": {"BTCUSDT": {"agents": {"technical": {"status": "EVALUATED"}}}}}
    brief = cc.compose(health={}, account=None, proposals=EMPTY, tasks={"available": True, "agents": {}},
                       memory=EMPTY, agent_states=_states(sig))
    assert brief["agents"]["source"] == "agent_states"
    assert "agent_technical" in brief["agents"]["working"] and "atlas_manager" in brief["agents"]["working"]
    assert brief["agents"]["statuses"]["agent_macro"] == "IDLE"  # no vote this cycle is not "working"


def test_compose_without_agent_states_keeps_task_log_behaviour():
    brief = cc.compose(health={}, account=None, proposals=EMPTY, memory=EMPTY,
                       tasks={"available": True, "agents": {"code_review": {"status": "WORKING"}}})
    assert brief["agents"] == {"working": ["code_review"], "statuses": {"code_review": "WORKING"}, "source": "task_log"}


def test_unavailable_agent_states_falls_back_instead_of_inventing():
    brief = cc.compose(health={}, account=None, proposals=EMPTY, memory=EMPTY, tasks={"available": False},
                       agent_states={"available": False})
    assert brief["agents"] == {"working": [], "statuses": {}, "source": "task_log"}


def test_command_center_and_agent_states_api_agree():
    client = TestClient(web_app.create_app())
    states = {a["id"]: a["state"] for a in client.get("/api/agent-states").json()["agents"]}
    brief = client.get("/api/command-center").json()["agents"]
    assert brief["source"] == "agent_states"
    assert brief["statuses"] == states
    assert brief["working"] == sorted(a for a, s in states.items() if s in ("WORKING", "REVIEWING"))
