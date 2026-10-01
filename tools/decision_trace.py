"""Roadmap C-4: trace one past trade back through the chain that produced it.

  python -m tools.decision_trace                 # list recent closed trades
  python -m tools.decision_trace <position_id>   # full trace of one trade

Joins, read-only, what Atlas already recorded:
  1. the market-loop decision just before the open (action, confidence, each agent's vote);
  2. the execution audit events of the same coin around the open (risk outcome, reason);
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


def trace(trade: dict[str, Any], telemetry_lines: Iterable[str], audit_events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    from observability.learning_view import experiences

    opened, symbol = _ts(trade.get("opened_at")), str(trade.get("symbol"))
    decision = None
    if opened:
        for line in telemetry_lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            when = _ts(rec.get("timestamp"))
            if (rec.get("symbol") == symbol and isinstance(rec.get("decision"), dict) and when
                    and opened - MATCH_WINDOW <= when <= opened + MATCH_WINDOW):
                decision = {"at": rec.get("timestamp"), **rec["decision"]}  # the latest one in the window wins
    risk = []
    if opened:
        for e in audit_events:
            when, payload = _ts(e.get("timestamp")), e.get("payload") or {}
            if when and opened - MATCH_WINDOW <= when <= opened + MATCH_WINDOW and str(payload.get("symbol", "")) == symbol:
                risk.append({"at": e.get("timestamp"), "event": e.get("event_type"),
                             "outcome": payload.get("status") or payload.get("outcome"),
                             "reason": payload.get("reason_code") or payload.get("reason")})
    exp = experiences([trade], [])
    return {
        "position_id": trade.get("position_id"), "symbol": symbol, "environment": "PAPER",
        "1_decision": decision or "N/A (no telemetry decision recorded within 3 min of the open)",
        "2_risk_and_execution": risk or "N/A (no audit event for this coin within 3 min of the open)",
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
        events = [{"event_type": e.event_type, "timestamp": e.timestamp, "payload": dict(e.payload or {})} for e in store.read_all()]
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
