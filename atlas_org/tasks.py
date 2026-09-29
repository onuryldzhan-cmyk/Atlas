"""Task lifecycle for the Atlas organization, as a hash-chained event log.

A task is created by the Atlas Manager from a plan (``atlas_org.manager``):
an ordered list of steps, each naming a role and the capability it needs.
Every assignment is re-checked against ``atlas_org.permissions`` on replay,
so a step can never be carried out by a unit that lacks the capability.
Same chain rules as proposals (contiguous seq, prev_hash, hash).

Step states: PENDING -> ASSIGNED -> WORKING -> DONE | FAILED | BLOCKED.
A task is DONE only when every step is DONE and the Assistant Manager's
completeness check finds no conflict; CANCELLED only by the owner.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterable

from atlas_org import permissions
from atlas_org.proposals import GENESIS_HASH, OWNER, ProposalLogError, event_hash, owner_check, sign_if_owner


class TaskLogError(ProposalLogError):
    pass


class TaskStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    WORKING = "WORKING"
    DONE = "DONE"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class TaskEvent(str, Enum):
    CREATE = "CREATE"
    ASSIGN = "ASSIGN"
    START = "START"
    RESULT = "RESULT"
    BLOCK = "BLOCK"
    LINK_PROPOSAL = "LINK_PROPOSAL"
    COMPLETE = "COMPLETE"
    CANCEL = "CANCEL"


VERDICTS = ("PASS", "REVIEW_REQUIRED", "FAIL", "INFO")
MANAGER = "director_ai"
ASSISTANT = "executive_assistant"


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise TaskLogError(message)


def _new_task(ev: dict[str, Any]) -> dict[str, Any]:
    p = ev.get("payload") or {}
    steps = p.get("steps")
    _check(isinstance(steps, list) and steps, f"seq {ev['seq']}: a task needs a plan")
    clean = []
    for i, s in enumerate(steps):
        _check(isinstance(s, dict) and s.get("role") and s.get("capability") and s.get("goal"),
               f"seq {ev['seq']}: step {i} needs role/capability/goal")
        permissions.Capability(s["capability"])  # unknown capability -> ValueError
        clean.append({"index": i, "role": s["role"], "capability": s["capability"], "goal": s["goal"],
                      "status": StepStatus.PENDING.value, "unit": None, "result": None})
    _check(bool(p.get("request")) and bool(p.get("category")), f"seq {ev['seq']}: request/category required")
    return {"id": ev["task_id"], "request": p["request"], "category": p["category"],
            "classification": p.get("classification"), "created_by": ev["actor"],
            "created_at": ev["at"], "status": TaskStatus.PLANNED.value, "steps": clean,
            "proposal_id": None, "history": []}


def completeness(task: dict[str, Any]) -> dict[str, Any]:
    """Assistant Manager check: missing steps and conflicting review verdicts."""

    missing = [s["index"] for s in task["steps"] if s["status"] != StepStatus.DONE.value]
    by_goal: dict[str, set[str]] = {}
    for s in task["steps"]:
        r = s["result"]
        if r and r.get("verdict") in ("PASS", "FAIL"):
            by_goal.setdefault(s["capability"], set()).add(r["verdict"])
    conflicts = sorted(cap for cap, v in by_goal.items() if len(v) > 1)
    failed = [s["index"] for s in task["steps"] if (s["result"] or {}).get("verdict") == "FAIL"]
    return {"complete": not missing and not conflicts, "missing_steps": missing,
            "conflicts": conflicts, "failed_steps": failed}


def _apply(tasks: dict[str, dict[str, Any]], ev: dict[str, Any]) -> None:
    seq = ev["seq"]
    try:
        kind = TaskEvent(ev.get("event"))
    except ValueError:
        raise TaskLogError(f"seq {seq}: unknown event {ev.get('event')!r}")
    tid, actor, at = ev.get("task_id"), ev.get("actor"), ev.get("at")
    _check(isinstance(tid, str) and tid and isinstance(actor, str) and actor and bool(at),
           f"seq {seq}: task_id/actor/at required")
    payload = ev.get("payload") or {}

    if kind is TaskEvent.CREATE:
        _check(tid not in tasks, f"seq {seq}: duplicate task {tid}")
        _check(actor in (MANAGER, OWNER), f"seq {seq}: only the Atlas Manager or the owner creates tasks")
        try:
            tasks[tid] = _new_task(ev)
        except ValueError as exc:
            raise TaskLogError(f"seq {seq}: {exc}")
    else:
        _check(tid in tasks, f"seq {seq}: unknown task {tid}")
        t = tasks[tid]
        _check(t["status"] not in (TaskStatus.DONE.value, TaskStatus.CANCELLED.value),
               f"seq {seq}: task {tid} is {t['status']}")
        step = None
        if kind in (TaskEvent.ASSIGN, TaskEvent.START, TaskEvent.RESULT, TaskEvent.BLOCK):
            idx = payload.get("step")
            _check(isinstance(idx, int) and 0 <= idx < len(t["steps"]), f"seq {seq}: bad step")
            step = t["steps"][idx]
        if kind is TaskEvent.ASSIGN:
            _check(actor in (MANAGER, ASSISTANT), f"seq {seq}: only the managers assign work")
            _check(step["status"] in (StepStatus.PENDING.value, StepStatus.BLOCKED.value, StepStatus.FAILED.value),
                   f"seq {seq}: step {step['index']} is {step['status']}")
            unit = payload.get("unit")
            auth = permissions.authorize(str(unit), step["capability"])
            _check(auth.allowed, f"seq {seq}: {unit} cannot {step['capability']}: {auth.reason}")
            step.update(unit=unit, status=StepStatus.ASSIGNED.value, result=None)
            t["status"] = TaskStatus.IN_PROGRESS.value
        elif kind is TaskEvent.START:
            _check(actor == step["unit"] and step["status"] == StepStatus.ASSIGNED.value,
                   f"seq {seq}: only the assigned unit starts its step")
            step["status"] = StepStatus.WORKING.value
        elif kind is TaskEvent.RESULT:
            _check(actor == step["unit"] and step["status"] == StepStatus.WORKING.value,
                   f"seq {seq}: only the working unit reports its result")
            _check(payload.get("verdict") in VERDICTS and bool(payload.get("summary")),
                   f"seq {seq}: result needs verdict and summary")
            step["result"] = {"verdict": payload["verdict"], "summary": payload["summary"],
                              "evidence": payload.get("evidence", []), "at": at}
            step["status"] = StepStatus.DONE.value
        elif kind is TaskEvent.BLOCK:
            _check(actor in (step["unit"], MANAGER, ASSISTANT), f"seq {seq}: not allowed to block")
            _check(bool(payload.get("reason")), f"seq {seq}: block needs a reason")
            step["status"] = StepStatus.BLOCKED.value
            t["status"] = TaskStatus.BLOCKED.value
        elif kind is TaskEvent.LINK_PROPOSAL:
            _check(actor == ASSISTANT, f"seq {seq}: the Assistant Manager packages proposals")
            _check(bool(payload.get("proposal_id")), f"seq {seq}: proposal_id required")
            _check(completeness(t)["complete"], f"seq {seq}: task incomplete or conflicting; no proposal")
            t["proposal_id"] = payload["proposal_id"]
        elif kind is TaskEvent.COMPLETE:
            _check(actor in (ASSISTANT, MANAGER), f"seq {seq}: only the managers complete a task")
            _check(completeness(t)["complete"], f"seq {seq}: task incomplete or conflicting")
            t["status"] = TaskStatus.DONE.value
        elif kind is TaskEvent.CANCEL:
            _check(actor == OWNER, f"seq {seq}: only the owner cancels a task")
            t["status"] = TaskStatus.CANCELLED.value
    tasks[tid]["history"].append({"seq": seq, "event": kind.value, "actor": actor, "at": at,
                                  "step": payload.get("step"), "note": payload.get("reason") or payload.get("summary", "")})


def replay(events: Iterable[dict[str, Any]], owner_key: bytes | None = None) -> dict[str, dict[str, Any]]:
    tasks: dict[str, dict[str, Any]] = {}
    expected, prev = 1, GENESIS_HASH
    for ev in events:
        _check(isinstance(ev, dict), "event is not an object")
        _check(ev.get("seq") == expected, f"sequence break: expected {expected}, got {ev.get('seq')!r}")
        _check(ev.get("prev_hash") == prev, f"seq {expected}: hash chain broken")
        _check(ev.get("hash") == event_hash(ev), f"seq {expected}: record altered")
        owner_check(ev, owner_key)
        _apply(tasks, ev)
        prev, expected = ev["hash"], expected + 1
    return tasks


def next_event(events: list[dict[str, Any]], *, task_id: str, event: TaskEvent | str, actor: str,
               at: str, payload: dict[str, Any] | None = None, owner_key: bytes | None = None) -> dict[str, Any]:
    record = {"seq": len(events) + 1, "prev_hash": events[-1]["hash"] if events else GENESIS_HASH,
              "task_id": task_id, "event": TaskEvent(event).value, "actor": actor, "at": at,
              "payload": payload or {}}
    sign_if_owner(record, owner_key)
    record["hash"] = event_hash(record)
    replay([*events, record], owner_key)
    return record


def agent_activity(tasks: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per unit: its live status and current task, derived only from the log."""

    state: dict[str, dict[str, Any]] = {}
    for t in tasks.values():
        for s in t["steps"]:
            if not s["unit"]:
                continue
            entry = state.setdefault(s["unit"], {"status": "IDLE", "current_task": None, "recent": []})
            entry["recent"].append({"task": t["id"], "step": s["index"], "status": s["status"]})
            if s["status"] in (StepStatus.ASSIGNED.value, StepStatus.WORKING.value, StepStatus.BLOCKED.value):
                entry["status"] = {"ASSIGNED": "WAITING", "WORKING": "WORKING", "BLOCKED": "BLOCKED"}[s["status"]]
                entry["current_task"] = t["id"]
    for entry in state.values():
        entry["recent"] = entry["recent"][-5:]
    return state


def agent_scorecards(tasks: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per unit, from the log only: finished steps, verdicts, blocks and time per step.

    A scorecard is evidence about how the organization works, never an
    authority: it changes no routing and grants nothing (registry v5.50).
    """

    from datetime import datetime

    def when(stamp: str) -> datetime | None:
        try:
            return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            return None

    cards: dict[str, dict[str, Any]] = {}
    for t in tasks.values():
        started: dict[int, datetime] = {}
        for h in t["history"]:
            step = h.get("step")
            if h["event"] == TaskEvent.START.value and isinstance(step, int):
                moment = when(h["at"])
                if moment:
                    started[step] = moment
            elif h["event"] == TaskEvent.RESULT.value and isinstance(step, int):
                unit = t["steps"][step]["unit"]
                card = cards.setdefault(unit, {"steps_done": 0, "verdicts": {}, "blocked": 0, "minutes": []})
                card["steps_done"] += 1
                verdict = (t["steps"][step]["result"] or {}).get("verdict", "UNKNOWN")
                card["verdicts"][verdict] = card["verdicts"].get(verdict, 0) + 1
                end = when(h["at"])
                if step in started and end:
                    card["minutes"].append((end - started[step]).total_seconds() / 60)
            elif h["event"] == TaskEvent.BLOCK.value and isinstance(step, int) and t["steps"][step]["unit"]:
                unit = t["steps"][step]["unit"]
                cards.setdefault(unit, {"steps_done": 0, "verdicts": {}, "blocked": 0, "minutes": []})["blocked"] += 1
    for card in cards.values():
        minutes = card.pop("minutes")
        card["avg_minutes_per_step"] = round(sum(minutes) / len(minutes), 1) if minutes else None
        done = card["steps_done"]
        card["fail_rate"] = round(card["verdicts"].get("FAIL", 0) / done, 2) if done else None
    return cards
