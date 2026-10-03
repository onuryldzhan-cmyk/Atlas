"""
============================================================
ATLAS SYSTEM HEALTH MODEL v1 (Phase-2 D1)
============================================================

Separates "the process is alive" from "the trading system is healthy".

Every signal is one of OK / DEGRADED / FAILED / UNKNOWN. UNKNOWN is never
OK: a signal that cannot be read blocks ``safe_to_trade`` exactly like a
failed one. The model is a pure function of a plain input mapping, so it
never blocks, never raises on malformed input, and is trivially testable.

System states (most severe wins):

    RECOVERY_REQUIRED          durable financial or audit state needs an
                               operator; a restart would not fix it
    STALLED                    the process is up but MarketLoop has made no
                               progress within the stall window
    STARTING                   not yet running / no loop progress seen yet
    DEGRADED_NEW_RISK_BLOCKED  running, but at least one signal needed for
                               new risk is not OK
    READY                      every signal OK

``safe_to_reduce`` deliberately needs less than ``safe_to_trade``: a
risk-reducing exit needs a live loop, a working execution path, fresh
market data and an audit writer that is at worst DEGRADED, but not a
healthy brain (Phase-2 A3/B1/B2).

Nothing here changes trading. It only reports.
============================================================
"""

from __future__ import annotations

import math
from typing import Any, Mapping

OK = "OK"
DEGRADED = "DEGRADED"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"

STARTING = "STARTING"
READY = "READY"
DEGRADED_NEW_RISK_BLOCKED = "DEGRADED_NEW_RISK_BLOCKED"
RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
STALLED = "STALLED"

# A loop that has not finished a cycle within this many intervals (and at
# least MIN_STALL_SECONDS) is stalled.
STALL_INTERVALS = 3.0
MIN_STALL_SECONDS = 90.0


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def stall_after_seconds(interval: Any) -> float:
    seconds = _number(interval)
    if seconds is None or seconds <= 0:
        return MIN_STALL_SECONDS
    return max(MIN_STALL_SECONDS, STALL_INTERVALS * seconds + 30.0)


def _flag(value: Any, *, bad: str = FAILED) -> str:
    """True -> OK, False -> ``bad``, anything else -> UNKNOWN."""
    if value is True:
        return OK
    if value is False:
        return bad
    return UNKNOWN


def assess(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Derive every health signal and the system state from raw inputs.

    Recognised inputs (all optional; absent means UNKNOWN):
      running, loop_running, loop_thread_alive, loop_progress_age_seconds,
      loop_interval_seconds, market_data_stale, execution_running,
      execution_halted, recovery_required, audit_persistence_state,
      brain_healthy
    """

    data = inputs if isinstance(inputs, Mapping) else {}

    process_alive = _flag(data.get("running"))

    # ---------------------------------------------------- loop progress
    age = _number(data.get("loop_progress_age_seconds"))
    stall_after = stall_after_seconds(data.get("loop_interval_seconds"))
    if data.get("loop_running") is False:
        # Not started (or stopped): no progress is expected, so it is not a
        # stall - the system is simply not ready.
        loop_progressing = UNKNOWN
    elif data.get("loop_thread_alive") is False:
        # The loop believes it runs but its worker is dead.
        loop_progressing = FAILED
    elif age is None:
        loop_progressing = UNKNOWN
    elif age < 0:
        loop_progressing = UNKNOWN
    elif age <= stall_after:
        loop_progressing = OK
    else:
        loop_progressing = FAILED

    # ---------------------------------------------------- market data
    stale = data.get("market_data_stale")
    market_data_healthy = (
        OK if stale is False else DEGRADED if stale is True else UNKNOWN
    )

    # ---------------------------------------------------- execution
    recovery_required = data.get("recovery_required") is True
    if data.get("execution_running") is False:
        execution_healthy = FAILED
    elif recovery_required or data.get("execution_halted") is True:
        execution_healthy = FAILED
    elif (
        data.get("execution_running") is True
        and data.get("execution_halted") is False
        and data.get("recovery_required") is False
    ):
        execution_healthy = OK
    else:
        execution_healthy = UNKNOWN

    # ---------------------------------------------------- audit
    audit_state = data.get("audit_persistence_state")
    audit_healthy = {
        "HEALTHY": OK,
        "DEGRADED": DEGRADED,
        "RECOVERY_REQUIRED": FAILED,
    }.get(audit_state if isinstance(audit_state, str) else "", UNKNOWN)

    # ---------------------------------------------------- brain
    brain_healthy = _flag(data.get("brain_healthy"), bad=DEGRADED)

    # ---------------------------------------------------- derived
    # A reduction tolerates a DEGRADED audit (writer intact) but not a FAILED
    # one: every SELL's realized-P&L booking needs a write-ahead audit record,
    # so ExecutionManager refuses exits while audit is RECOVERY_REQUIRED.
    safe_to_reduce = all(
        signal == OK
        for signal in (process_alive, loop_progressing, execution_healthy, market_data_healthy)
    ) and audit_healthy in {OK, DEGRADED}

    safe_to_trade = safe_to_reduce and audit_healthy == OK and brain_healthy == OK

    system_ready = process_alive == OK and loop_progressing == OK

    if recovery_required or audit_healthy == FAILED:
        state = RECOVERY_REQUIRED
    elif process_alive == OK and loop_progressing == FAILED:
        state = STALLED
    elif not system_ready:
        state = STARTING
    elif not safe_to_trade:
        state = DEGRADED_NEW_RISK_BLOCKED
    else:
        state = READY

    return {
        "system_state": state,
        "process_alive": process_alive,
        "loop_progressing": loop_progressing,
        "loop_progress_age_seconds": age,
        "loop_stall_after_seconds": stall_after,
        "market_data_healthy": market_data_healthy,
        "execution_healthy": execution_healthy,
        "audit_healthy": audit_healthy,
        "brain_healthy": brain_healthy,
        "system_ready": system_ready,
        "safe_to_trade": safe_to_trade,
        "safe_to_reduce": safe_to_reduce,
    }
