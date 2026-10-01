"""Read-only EXP-001 results report: did the lowered confidence floor pay?

Every closed paper position is attributed to its entry approval (the
RISK_APPROVED BUY nearest in time, as tools/paper_position_report does) and
grouped: admitted under EXP-001 vs admitted at the policy floor. For each
group it prints trades, wins/losses, win rate with a 95% Wilson interval,
gross P&L, entry fees and average holding time, plus the experiment's
progress (admissions N/50, window end).

It never writes, takes no lock and is safe to run while Atlas runs.
Exit fees are not stored per closed position, so per-trade figures are
gross of exit fees; the account-level net line comes from the durable
financial state (realized gross P&L minus all fees).

The report states whether the sample is large enough to decide anything
(it never claims significance it does not have).

Usage:
  python -m tools.exp001_report
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from core.application import (
    EXECUTION_AUDIT_EVENT_FILE,
    EXECUTION_CLOSED_POSITIONS_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    resolve_state_directory,
)
from core.experiment_ledger import EXPERIMENT_LEDGER_FILE
from core.risk_engine import EXP001_PAPER_CONFIDENCE_EXPERIMENT as EXP, PAPER_CONFIDENCE_EXPERIMENTS
from tools.paper_position_report import approvals_by_symbol, entry_approval

# Below this many closed trades per group no conclusion is drawn.
MIN_TRADES_FOR_A_VERDICT = 30

# ASSUMPTION, not a measured venue fee: paper execution currently books
# zero fees, so the report also shows an estimate at a typical spot rate
# per side (entry and exit). The verdict uses the estimated net figure,
# the more conservative of the two.
ASSUMED_FEE_RATE_PER_SIDE = Decimal("0.001")


def estimated_fees(record: dict) -> Decimal:
    entry = Decimal(str(record.get("cost_quote", "0")))
    exit_value = entry + Decimal(str(record["gross_pnl"]))
    return ASSUMED_FEE_RATE_PER_SIDE * (entry + max(exit_value, Decimal("0")))


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def load_closed(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def holding_hours(record: dict) -> float | None:
    try:
        opened = datetime.fromisoformat(str(record["opened_at"]))
        closed = datetime.fromisoformat(str(record["closed_at"]))
        return (closed - opened).total_seconds() / 3600
    except (KeyError, ValueError):
        return None


def summarize(records: list[dict]) -> dict:
    n = len(records)
    gross = [Decimal(str(r["gross_pnl"])) for r in records]
    fees = sum((Decimal(str(r.get("entry_fees", "0"))) for r in records), Decimal("0"))
    wins = sum(1 for g in gross if g > 0)
    hours = [h for h in (holding_hours(r) for r in records) if h is not None]
    est_fees = sum((estimated_fees(r) for r in records), Decimal("0"))
    est_net = [Decimal(str(r["gross_pnl"])) - estimated_fees(r) for r in records]
    est_wins = sum(1 for v in est_net if v > 0)
    low, high = wilson_interval(est_wins, n)
    return {
        "trades": n,
        "wins": wins,
        "losses": n - wins,
        "win_rate": wins / n if n else None,
        "win_rate_95": (low, high),
        "est_fees": est_fees,
        "est_net_pnl": sum(est_net, Decimal("0")),
        "est_wins": est_wins,
        "gross_pnl": sum(gross, Decimal("0")),
        "entry_fees": fees,
        "avg_gross_per_trade": (sum(gross, Decimal("0")) / n) if n else None,
        "avg_holding_hours": (sum(hours) / len(hours)) if hours else None,
    }


def group_closed(closed: list[dict], approvals: dict[str, list[dict]], exp=EXP) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {exp.experiment_id: [], "policy floor": [], "unattributed": []}
    for record in closed:
        approval = entry_approval(approvals.get(record.get("symbol", ""), []), record.get("opened_at"))
        if approval is None:
            groups["unattributed"].append(record)
        elif approval.get("experiment_id") == exp.experiment_id:
            groups[exp.experiment_id].append(record)
        else:
            groups["policy floor"].append(record)
    return groups


def verdict(summary: dict) -> str:
    n = summary["trades"]
    if n < MIN_TRADES_FOR_A_VERDICT:
        return f"INSUFFICIENT SAMPLE ({n} < {MIN_TRADES_FOR_A_VERDICT} trades) - no conclusion"
    low, _ = summary["win_rate_95"]
    if summary["est_net_pnl"] <= 0:
        return "NOT PROFITABLE after estimated fees - evidence against keeping the lower floor"
    if low > 0.5:
        return "PROFITABLE, win rate above 50% at 95% - evidence for the lower floor"
    return "PROFITABLE but win rate not distinguishable from 50% - inconclusive"


def print_group(name: str, summary: dict) -> None:
    print(f"{name}")
    if summary["trades"] == 0:
        print("  no closed trades")
        return
    low, high = summary["win_rate_95"]
    print(f"  trades: {summary['trades']}  wins: {summary['wins']}  losses: {summary['losses']}")
    print(f"  win rate (gross): {summary['win_rate']:.0%}; after est. fees: "
          f"{summary['est_wins']}/{summary['trades']} (95% range {low:.0%} - {high:.0%})")
    print(f"  gross P&L: {summary['gross_pnl']:.2f}  entry fees: {summary['entry_fees']:.2f}  "
          f"avg gross/trade: {summary['avg_gross_per_trade']:.2f}")
    print(f"  est. fees @ {ASSUMED_FEE_RATE_PER_SIDE:.1%}/side (ASSUMPTION): {summary['est_fees']:.2f}  "
          f"est. net P&L: {summary['est_net_pnl']:.2f}")
    if summary["avg_holding_hours"] is not None:
        print(f"  avg holding time: {summary['avg_holding_hours']:.1f} h")
    print(f"  verdict: {verdict(summary)}")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Read-only experiment results report")
    parser.add_argument("--experiment", default="EXP-001", choices=sorted(PAPER_CONFIDENCE_EXPERIMENTS))
    args = parser.parse_args(argv)
    EXP = PAPER_CONFIDENCE_EXPERIMENTS[args.experiment]  # noqa: N806 - shadows the module default on purpose
    root = resolve_state_directory()
    closed = load_closed(root / EXECUTION_CLOSED_POSITIONS_FILE)
    approvals = approvals_by_symbol(root / EXECUTION_AUDIT_EVENT_FILE)
    groups = group_closed(closed, approvals, EXP)

    admitted = sum(1 for items in approvals.values() for a in items
                   if a.get("experiment_id") == EXP.experiment_id)
    ledger_path = root / EXPERIMENT_LEDGER_FILE
    ledger = None
    if ledger_path.exists():
        try:
            ledger = json.loads(ledger_path.read_text(encoding="utf-8")).get(EXP.experiment_id, {}).get("admissions")
        except (OSError, ValueError, AttributeError):
            ledger = "unreadable"

    print(f"state root: {root}")
    print(f"{EXP.experiment_id}: floor {EXP.minimum_confidence} for "
          f"{', '.join(sorted(b.value for b in EXP.buckets))}; window "
          f"{EXP.starts_at.isoformat()} .. {EXP.ends_at.isoformat()}")
    print(f"admissions: audit {admitted}/{EXP.max_admissions}"
          + (f", ledger {ledger}" if ledger is not None else ""))
    print()

    for name in (EXP.experiment_id, "policy floor", "unattributed"):
        if name == "unattributed" and not groups[name]:
            continue
        print_group(name, summarize(groups[name]))
        print()

    state_path = root / EXECUTION_FINANCIAL_STATE_FILE
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        gross = Decimal(str(state.get("realized_gross_pnl", "0")))
        fees = Decimal(str(state.get("fees", "0")))
        print(f"account (all trades): realized gross {gross:.2f}, all fees {fees:.2f}, "
              f"net {gross - fees:.2f}, cash {Decimal(str(state.get('cash', '0'))):.2f}")
    print(f"Nothing was changed. The keep/stop decision on {EXP.experiment_id} is the owner's.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
