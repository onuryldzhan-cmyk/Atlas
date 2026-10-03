"""Roadmap C-4: trace one past trade back through the chain that produced it.

  python -m tools.decision_trace                 # list recent closed trades
  python -m tools.decision_trace <position_id>   # full trace of one trade

Joins, read-only, what Atlas already recorded (Phase-2 F1: by identity - the
opening request_id that minted the position_id - never by nearest time):
  1. the market-loop decision of the opening request (action, confidence, each agent's vote);
  2. the execution audit events of that request (risk outcome, reason) and the close event;
  3. the closed trade itself with its post-trade analysis (net after fees, counterfactuals).

This is a reconstruction from logs, not a re-execution: candles at decision
time are not stored, so the brain is not re-run. A missing link is shown as
N/A, never guessed. Nothing is written.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

MATCH_WINDOW = timedelta(minutes=3)


def _ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


_CLOSE_EVENT = "RISK_ACCOUNTING_REALIZED_PNL_PREPARED"


def trace(trade: dict[str, Any], telemetry_lines: Iterable[str], audit_events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Phase-2 F1: joined by identity. The opening request_id is the one that
    minted the trade's position_id; its decision, risk approval and execution
    events carry that request_id, and the close is the realized-P&L event that
    names the position_id. A trade without that chain (older records) uses an
    explicit LEGACY time fallback that accepts only an unambiguous match."""
    from observability.learning_view import experiences
    from tools.agent_attribution import decisions_by_symbol, entry_decision
    from tools.paper_position_report import EXACT, LEGACY_TIMESTAMP, UNATTRIBUTED, is_canonical_position_id, opened_by

    symbol, position_id = str(trade.get("symbol")), trade.get("position_id")
    events = list(audit_events)
    match, how = entry_decision(trade, decisions_by_symbol(telemetry_lines).get(symbol, []))
    decision = match
    request_id = None
    risk: list[dict[str, Any]] = []
    close = None
    risk_how = UNATTRIBUTED
    if is_canonical_position_id(position_id):
        ids = {e.get("aggregate_id") for e in events if e.get("event_type") == "RISK_APPROVED"}
        ids |= {e.get("correlation_id") for e in events}
        opening = sorted(r for r in ids if isinstance(r, str) and opened_by(position_id, r))
        if len(opening) == 1:
            request_id = opening[0]
            risk = [e for e in events if request_id in (e.get("correlation_id"), e.get("aggregate_id"))]
            risk_how = EXACT
        closes = [e for e in events if e.get("event_type") == _CLOSE_EVENT
                  and (e.get("payload") or {}).get("position_id") == position_id
                  and (e.get("payload") or {}).get("position_closed") is True]
        if len(closes) == 1:
            pay = closes[0].get("payload") or {}
            close = {"at": closes[0].get("timestamp"), "close_request_id": pay.get("request_id"),
                     "close_execution_id": pay.get("execution_id"), "attribution": EXACT}
    else:
        opened = _ts(trade.get("opened_at"))
        if opened:
            near = [e for e in events if (lambda w: w is not None and opened - MATCH_WINDOW <= w <= opened + MATCH_WINDOW)(
                _ts(e.get("timestamp"))) and str((e.get("payload") or {}).get("symbol", "")) == symbol]
            requests = {e.get("correlation_id") for e in near}
            if near and len(requests) == 1:  # one request only; two overlapping requests stay unattributed
                risk, risk_how = near, LEGACY_TIMESTAMP
    risk_rows = [{"at": e.get("timestamp"), "event": e.get("event_type"),
                  "outcome": (e.get("payload") or {}).get("status") or (e.get("payload") or {}).get("outcome"),
                  "reason": (e.get("payload") or {}).get("reason_code") or (e.get("payload") or {}).get("reason")}
                 for e in risk]
    exp = experiences([trade], [])
    return {
        "position_id": position_id, "symbol": symbol, "environment": "PAPER",
        "request_id": request_id,
        "attribution": {"decision": how, "risk_and_execution": risk_how, "close": close["attribution"] if close else UNATTRIBUTED},
        "1_decision": (dict(decision) if decision else
                       f"N/A ({UNATTRIBUTED}: no telemetry decision linked to this position)"),
        "2_risk_and_execution": risk_rows or f"N/A ({UNATTRIBUTED}: no audit event linked to this position)",
        "2b_close": close or f"N/A ({UNATTRIBUTED}: no close event names this position)",
        "3_outcome": exp[0] if exp else "N/A (trade record incomplete)",
        "note": "reconstruction from logs, not a re-execution; evidence only",
    }


def _load(state_dir: Path, log_dir: Path | None) -> tuple[list[dict], list[str], list[dict]]:
    from core.application import EXECUTION_AUDIT_EVENT_FILE, EXECUTION_CLOSED_POSITIONS_FILE
    from core.audit_event_store import AuditEventStore
    from tools.exp001_report import load_closed

    closed = load_closed(state_dir / EXECUTION_CLOSED_POSITIONS_FILE)
    log = (log_dir / "market_loop_telemetry.jsonl") if log_dir else None
    lines = log.read_text(encoding="utf-8").splitlines() if log and log.exists() else []
    audit_path = state_dir / EXECUTION_AUDIT_EVENT_FILE
    events = []
    if audit_path.exists():
        store = AuditEventStore(audit_path, verify_on_load=True)
        events = [{"event_type": e.event_type, "timestamp": e.timestamp, "payload": dict(e.payload or {}),
                   "aggregate_id": e.aggregate_id, "correlation_id": e.correlation_id} for e in store.read_all()]
    return closed, lines, events


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    from core.application import resolve_log_directory, resolve_state_directory

    closed, lines, events = _load(resolve_state_directory(), resolve_log_directory())
    if not args:
        for t in closed[-20:]:
            print(f"{t.get('position_id')}  {t.get('symbol')}  {t.get('opened_at')} -> {t.get('closed_at')}")
        print(f"{len(closed)} kapanmış işlem. Birini izlemek için: python -m tools.decision_trace <position_id>")
        return 0
    match = [t for t in closed if t.get("position_id") == args[0]]
    if not match:
        print(f"HATA: {args[0]} bulunamadı")
        return 2
    print(json.dumps(trace(match[-1], lines, events), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
