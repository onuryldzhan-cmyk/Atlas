"""Strategy registry and lifecycle (owner MEGA TASK 1 §8, Strategy Factory §4, §7, §8).

A strategy moves only forward through evidence stages, and never to
PRODUCTION_CANDIDATE or ENABLED without a certification that names the owner's
approved proposal. Failure states (REJECTED / SUSPENDED / DEPRECATED) are
reachable from anywhere. The registry is data: nothing in the runtime reads
it to switch a strategy on, and live authority stays DENIED regardless.

Pure validation; the file lives at config/strategy_registry.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STAGES = ("DISCOVERED", "DEFINED", "BACKTESTED", "VALIDATED", "WALK_FORWARD", "STRESS_TESTED",
          "PAPER", "CERTIFIED", "PRODUCTION_CANDIDATE", "ENABLED")
FAILURE = ("WARNING", "SUSPENDED", "REJECTED", "DEPRECATED")
STATUSES = STAGES + FAILURE
NEEDS_CERTIFICATION = ("CERTIFIED", "PRODUCTION_CANDIDATE", "ENABLED")
SPEC_FIELDS = ("entry", "exit", "risk", "timeframe", "instruments", "required_data", "assumptions", "invalidation")
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "strategy_registry.json"


class StrategyRegistryError(ValueError):
    pass


def _check(ok: bool, msg: str) -> None:
    if not ok:
        raise StrategyRegistryError(msg)


def allowed(old: str, new: str) -> bool:
    if new in FAILURE:
        return old != "DEPRECATED"
    if old == "WARNING" or old == "SUSPENDED":
        return new == "PAPER"  # back to observation only, never straight to enabled
    if old in FAILURE:
        return False
    return new in STAGES and STAGES.index(new) == STAGES.index(old) + 1


def validate(registry: dict[str, Any]) -> dict[str, Any]:
    _check(isinstance(registry.get("strategies"), list), "strategies must be a list")
    seen = set()
    for s in registry["strategies"]:
        sid, ver = s.get("id"), s.get("version")
        _check(bool(sid) and bool(ver), "each strategy needs id and version")
        _check((sid, ver) not in seen, f"duplicate {sid} {ver}")
        seen.add((sid, ver))
        status = s.get("status")
        _check(status in STATUSES, f"{sid}: unknown status {status}")
        history = s.get("history") or []
        _check(bool(history) and history[0].get("status") == "DISCOVERED", f"{sid}: history must start at DISCOVERED")
        for a, b in zip(history, history[1:]):
            _check(allowed(a["status"], b["status"]), f"{sid}: illegal transition {a['status']} -> {b['status']}")
            _check(str(b.get("at", "")) >= str(a.get("at", "")), f"{sid}: history out of order")
        _check(history[-1]["status"] == status, f"{sid}: status disagrees with history")
        for h in history:
            _check(bool(h.get("evidence")), f"{sid}: every transition needs evidence ({h['status']})")
        reached = {h["status"] for h in history}
        if reached & {"DEFINED", "BACKTESTED"}:
            spec = s.get("specification") or {}
            missing = [f for f in SPEC_FIELDS if not spec.get(f)]
            _check(not missing, f"{sid}: specification missing {missing}")
        if reached & set(NEEDS_CERTIFICATION):
            cert = s.get("certification") or {}
            _check(bool(cert.get("owner_approved_proposal")) and bool(cert.get("independent_audit")),
                   f"{sid}: {status} requires certification with owner_approved_proposal and independent_audit")
        _check(status != "ENABLED" or registry.get("live_authority") != "DENIED" or s.get("environment") == "PAPER",
               f"{sid}: ENABLED outside PAPER while live authority is DENIED")
    return registry


def load(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return validate(json.loads(path.read_text(encoding="utf-8")))
