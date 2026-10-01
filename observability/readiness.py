"""Readiness evaluation over the public runtime status (master command §24/§26).

Liveness answers "is the web process up" and needs no runtime at all.
Readiness answers "may Atlas be trusted to act right now" and is computed
only from the allowlisted /api/status payload:

* runtime healthy, not in emergency mode;
* market loop running and its last cycle at most MAX_CYCLE_AGE_S old
  (the supervisor's own stale threshold);
* no coin's market data flagged stale;
* execution not halted and no recovery required;
* venue rules FRESH.

Anything missing counts as NOT ready (unknown is never ready). Pure: no I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

MAX_CYCLE_AGE_S = 30.0


def _age(stamp: Any, now: datetime) -> float | None:
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (now - when).total_seconds())


def evaluate(status: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"check": name, "ok": ok is True, "state": "OK" if ok is True else ("UNKNOWN" if ok is None else "FAIL"),
                       "detail": detail})

    if not isinstance(status, dict) or status.get("available") is False:
        reason = status.get("reason") if isinstance(status, dict) else "no status"
        check("runtime", None, f"status unavailable: {reason}")
        return {"ready": False, "checks": checks, "evaluated_at": now.isoformat()}

    runtime = status.get("runtime") or {}
    healthy = runtime.get("healthy")
    check("runtime", None if healthy is None else (healthy is True and not runtime.get("emergency_mode")),
          f"state {runtime.get('state')}, emergency {runtime.get('emergency_mode')}")

    loop = status.get("market_loop") or {}
    age = _age(loop.get("last_cycle"), now) if loop.get("last_cycle") else None
    running = loop.get("running")
    check("market_loop", None if running is None or age is None else (running is True and age <= MAX_CYCLE_AGE_S),
          f"running {running}, last cycle {'?' if age is None else f'{age:.0f} s'} ago (limit {MAX_CYCLE_AGE_S:.0f} s)")

    staleness = loop.get("market_data_staleness")
    if isinstance(staleness, dict) and staleness:
        stale = sorted(s for s, v in staleness.items() if not isinstance(v, dict) or v.get("stale") is not False)
        check("market_data", not stale, "all coins fresh" if not stale else f"stale or unknown: {', '.join(stale)}")
    else:
        check("market_data", None, "no per-coin staleness reported")

    execution = status.get("execution") or {}
    op = execution.get("operational_state") or {}
    halted, recovery = op.get("execution_halted"), op.get("recovery_required")
    check("execution", None if halted is None or recovery is None else (halted is False and recovery is False),
          f"mode {execution.get('mode')}, halted {halted}, recovery required {recovery}")

    buckets = execution.get("position_risk_buckets")
    if isinstance(buckets, dict) and buckets.get("corrupt"):
        # S1 re-audit R-2: every bucket reads UNKNOWN (the strictest sleeve use) until the owner repairs the file.
        check("position_risk_buckets", False, "risk-bucket sidecar unreadable: every position counts against every sleeve; "
              "repair: python -m core.position_risk_buckets repair <state>/position_risk_buckets.jsonl")

    rules = (execution.get("venue_rules") or {}).get("status")
    check("venue_rules", None if rules is None else rules == "FRESH", f"status {rules}")

    return {"ready": all(c["ok"] for c in checks), "checks": checks, "evaluated_at": now.isoformat(),
            "live_authority": "DENIED"}
