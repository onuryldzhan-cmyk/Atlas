"""Agent performance attribution (owner MEGA 1 §11, MEGA 2 §10): did each agent's vote agree with the outcome?

  python -m tools.agent_attribution

Joins every closed trade to the market-loop telemetry record of the same coin
written just before the position opened (decision + each agent's vote).
Per agent: trades where it voted BUY vs SELL/HOLD, win rate after fees and
net expectancy of the trades it supported. Below MIN_SAMPLE the verdict is
INSUFFICIENT. Attribution is correlation, not causation, and it never
changes any weight or authority: evidence only.

Phase-2 F1: the join is exact - the telemetry decision whose request_id
minted the trade's position_id. Trades without that chain (recorded before
request_id was stamped) use an explicit LEGACY time fallback that accepts
only one unambiguous decision; everything else is UNATTRIBUTED, never guessed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from ai.core.intelligence.trade_evidence import net_pnl
from tools.paper_position_report import (
    EXACT,
    LEGACY_TIMESTAMP,
    UNATTRIBUTED,
    is_canonical_position_id,
    opened_by,
)

MIN_SAMPLE = 10
MATCH_WINDOW = timedelta(minutes=3)


def _ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def decisions_by_symbol(telemetry_lines: Iterable[str]) -> dict[str, list[tuple[datetime, dict]]]:
    out: dict[str, list[tuple[datetime, dict]]] = {}
    for line in telemetry_lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        dec, when = rec.get("decision"), _ts(rec.get("timestamp"))
        if isinstance(dec, dict) and str(dec.get("action", "")).upper().endswith("BUY") and when:
            out.setdefault(str(rec.get("symbol")), []).append((when, dec))
    for rows in out.values():
        rows.sort(key=lambda r: r[0])
    return out


def entry_decision(trade: dict, rows: list[tuple[datetime, dict]]) -> tuple[dict | None, str]:
    """(the decision that opened ``trade``, attribution) - EXACT, LEGACY_TIMESTAMP or UNATTRIBUTED.

    Phase-2 F1: a trade whose position_id was minted from its opening request_id
    is joined to the telemetry decision carrying that request_id, nothing else.
    LEGACY fallback, only for a trade without that chain: telemetry records
    without a request_id within MATCH_WINDOW of the open, accepted only when
    they all record the same decision (one decision repeated every cycle);
    differing decisions are ambiguous and stay UNATTRIBUTED.
    """
    position_id = trade.get("position_id")
    if is_canonical_position_id(position_id):
        exact = [d for _, d in rows if opened_by(position_id, d.get("request_id"))]
        if exact and all(d == exact[0] for d in exact[1:]):
            return exact[0], EXACT
        return None, UNATTRIBUTED
    opened = _ts(trade.get("opened_at"))
    if opened is None:
        return None, UNATTRIBUTED
    candidates = [d for t, d in rows if not d.get("request_id") and opened - MATCH_WINDOW <= t <= opened + MATCH_WINDOW]
    if candidates and all(d == candidates[0] for d in candidates[1:]):
        return candidates[0], LEGACY_TIMESTAMP
    return None, UNATTRIBUTED


def attribute(closed: list[dict], decisions: dict[str, list[tuple[datetime, dict]]]) -> dict[str, Any]:
    per_agent: dict[str, dict[str, list[Decimal]]] = {}
    unattributed = legacy = 0
    for trade in closed:
        match, how = entry_decision(trade, decisions.get(str(trade.get("symbol")), []))
        if match is None or not isinstance(match.get("votes"), dict) or not match.get("votes"):
            unattributed += 1
            continue
        legacy += how == LEGACY_TIMESTAMP
        net = net_pnl(trade)
        for agent, vote in match["votes"].items():
            side = "supported" if str(vote).upper().endswith("BUY") else "opposed"
            per_agent.setdefault(agent, {"supported": [], "opposed": []})[side].append(net)
    report = {}
    for agent, sides in sorted(per_agent.items()):
        row = {}
        for side, nets in sides.items():
            n = len(nets)
            row[side] = {"trades": n,
                         "win_rate_after_fees": round(sum(1 for x in nets if x > 0) / n, 3) if n else None,
                         "net_expectancy": round(float(sum(nets) / n), 4) if n else None,
                         "verdict": "MEASURED" if n >= MIN_SAMPLE else "INSUFFICIENT"}
        report[agent] = row
    return {"agents": report, "attributed_trades": len(closed) - unattributed, "unattributed_trades": unattributed,
            "legacy_timestamp_attributed_trades": legacy,
            "note": "correlation only; never changes weights or authority"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    from core.application import EXECUTION_CLOSED_POSITIONS_FILE, resolve_log_directory, resolve_state_directory
    from tools.exp001_report import load_closed

    closed = load_closed(resolve_state_directory() / EXECUTION_CLOSED_POSITIONS_FILE)
    log_dir = resolve_log_directory()
    log = (log_dir / "market_loop_telemetry.jsonl") if log_dir else Path("__no_log_directory__")
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    out = attribute(closed, decisions_by_symbol(lines))
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    print(f"AJAN BAŞARI ÖLÇÜMÜ — eşleşen {out['attributed_trades']} işlem, oy kaydı olmayan {out['unattributed_trades']}")
    for agent, row in out["agents"].items():
        s, o = row["supported"], row["opposed"]
        print(f"  {agent:<10} AL dediği {s['trades']:>3} işlem: kazanma {s['win_rate_after_fees']} beklenti {s['net_expectancy']} ({s['verdict']})"
              f" | karşı çıktığı {o['trades']:>3}: beklenti {o['net_expectancy']}")
    print(out["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
