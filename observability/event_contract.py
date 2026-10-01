"""Atlas Event Contract v1 (owner architecture 2026-10-01, accepted part (a)/(b)).

proposals/2026-10-01_atlas_hq_event_contract_owner_architecture_EVALUATION.md

One Atlas-owned event format that any view (dashboard, a future 2D/3D HQ)
may read. Rules:

* Atlas's own schema: no third-party event format or agent id is adopted.
* Strict: an unknown event_type, agent status or malformed field is REJECTED,
  never coerced into something that looks valid.
* Payloads pass the SensitiveDataGuard and are size-capped, so a secret or an
  injected instruction is carried as inert, redacted text without authority.
* Evidence only: an event describes what happened. Nothing here can execute,
  approve or change anything; a UI that reads events stays read-only.
* No I/O. Pure functions.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

SCHEMA_VERSION = "atlas.event.v1"
MAX_PAYLOAD_BYTES = 4096

EVENT_TYPES = frozenset({
    "agent.cycle.started", "agent.cycle.completed", "agent.failed",
    "agent.task.started", "agent.task.completed", "agent.task.blocked",
    "agent.tool.started", "agent.tool.completed",
    "agent.approval.requested",
    "governance.proposal.created", "governance.proposal.decided",
    "memory.record.added", "incident.opened",
    "trade.opened", "trade.closed",
    "collaboration.handoff",
})

# AtlasAgentState.status (owner list). Values with no real source today are
# listed in UNSOURCED_STATUSES: a view must never display them until a real
# emitter exists (no fake animation).
AGENT_STATUSES = frozenset({
    "offline", "idle", "thinking", "researching", "coding", "testing", "reviewing",
    "auditing", "trading_monitoring", "waiting_approval", "blocked", "error",
})
UNSOURCED_STATUSES = frozenset({"thinking", "coding", "testing"})  # wait on AI-001

_ID = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,79}$")


class EventContractError(ValueError):
    pass


def _iso(value: Any, field: str) -> str:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventContractError(f"{field} is not ISO-8601") from exc
    if stamp.tzinfo is None:
        raise EventContractError(f"{field} must carry a timezone")
    return stamp.isoformat()


def _ident(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    text = str(value or "")
    if not _ID.match(text):
        raise EventContractError(f"{field} is not a valid id")
    return text


def validate_event(raw: Any) -> dict[str, Any]:
    """Return the canonical event, or raise EventContractError. Never coerces."""
    from atlas_security import sanitize_sensitive_data

    if not isinstance(raw, dict):
        raise EventContractError("event must be an object")
    if raw.get("schema", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise EventContractError("unsupported schema")
    etype = raw.get("event_type")
    if etype not in EVENT_TYPES:
        raise EventContractError(f"unknown event_type {etype!r}")
    agent, run = raw.get("agent") or {}, raw.get("run") or {}
    if not isinstance(agent, dict) or not isinstance(run, dict):
        raise EventContractError("agent and run must be objects")
    payload = raw.get("payload", {})
    if not isinstance(payload, dict):
        raise EventContractError("payload must be an object")
    payload = sanitize_sensitive_data(payload)
    if len(json.dumps(payload, sort_keys=True, default=str).encode()) > MAX_PAYLOAD_BYTES:
        raise EventContractError("payload too large")
    return {
        "schema": SCHEMA_VERSION,
        "event_id": _ident(raw.get("event_id"), "event_id"),
        "event_type": etype,
        "timestamp": _iso(raw.get("timestamp"), "timestamp"),
        "agent": {"id": _ident(agent.get("id"), "agent.id"), "role": _ident(agent.get("role"), "agent.role", optional=True)},
        "run": {"id": _ident(run.get("id"), "run.id", optional=True), "task_id": _ident(run.get("task_id"), "run.task_id", optional=True)},
        "payload": payload,
    }


def agent_state(agent_id: str, events: list[dict[str, Any]], *, now: datetime, stale_after_s: float = 1800) -> dict[str, Any]:
    """AtlasAgentState from validated events of one agent. No event -> offline; nothing is invented."""
    mine = sorted((e for e in events if e["agent"]["id"] == agent_id), key=lambda e: e["timestamp"])
    if not mine:
        return {"id": agent_id, "status": "offline", "last_event": None, "current_task": None, "current_tool": None}
    last = mine[-1]
    age = (now - datetime.fromisoformat(last["timestamp"])).total_seconds()
    status = {
        "agent.failed": "error", "incident.opened": "error",
        "agent.task.blocked": "blocked", "agent.approval.requested": "waiting_approval",
        "agent.task.started": "researching", "agent.tool.started": "researching",
    }.get(last["event_type"], "idle")
    if age > stale_after_s and status not in ("error", "blocked", "waiting_approval"):
        status = "offline"
    tool = last["payload"].get("tool") if last["event_type"] == "agent.tool.started" else None
    task = last["run"]["task_id"] if last["event_type"] in ("agent.task.started", "agent.tool.started") else None
    return {"id": agent_id, "status": status, "last_event": last["event_id"], "last_activity": last["timestamp"],
            "current_task": task, "current_tool": tool}
