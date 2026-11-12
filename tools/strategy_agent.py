"""Strategy agent: turns Atlas's own closed trades into evidence-backed proposals for the owner.

  python -m tools.strategy_agent            # show what it would propose (dry run)
  python -m tools.strategy_agent --apply    # file the proposals (status: SUBMITTED, owner decides)

Deterministic rules over tools.performance_report.analyse(); no model, no
network, no runtime access. Every proposal carries claim / evidence /
counter-evidence, is a recommendation only, and changes nothing: the owner
approves, and a CRITICAL runtime change still needs tests and an audit.
A rule whose proposal is still open is not filed again.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from atlas_org import proposals as P
from tools import atlas_org_cli as cli
from tools.performance_report import MIN_SAMPLE, analyse

AUTHOR = "strategy_lab"
FEE_DRAG_SHARE = Decimal("0.5")


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def fee_drag(report: dict[str, Any]) -> dict[str, Any] | None:
    total = report.get("total") or {}
    if not total.get("trades") or _d(total.get("gross_pnl", 0)) == 0:
        return None
    share = _d(total["est_fees"]) / abs(_d(total["gross_pnl"]))
    if share <= FEE_DRAG_SHARE:
        return None
    holds = report["by"].get("holding_time", {})
    short = [(k, s) for k, s in holds.items() if k in ("<15 dk", "15-60 dk")]
    longer = [(k, s) for k, s in holds.items() if k not in ("<15 dk", "15-60 dk")]
    short_net = sum((_d(s["est_net_pnl"]) for _, s in short), Decimal("0"))
    long_net = sum((_d(s["est_net_pnl"]) for _, s in longer), Decimal("0"))
    n = total["trades"]
    return {
        "key": "FEE-DRAG",
        "title": "Test a minimum holding time: fees exceed the edge",
        "problem": f"Estimated fees are {share:.0%} of gross P/L over {n} closed PAPER trades; "
                   f"trades closed within an hour netted {short_net:.2f}, longer holds {long_net:.2f}.",
        "motivation": "Round-trip cost, not direction, decides the result. A trader cuts turnover before tuning signals.",
        "proposed_changes": "Step 1 (no runtime change): replay with python -m tools.strategy_compare / "
                            "tools/backtest_replay.py --min-hold 60 and compare net P/L after fees and slippage "
                            "on walk-forward windows. Step 2, only if it wins on every window: a separate CRITICAL "
                            "proposal for a runtime minimum holding time, with tests and an independent audit.",
        "affected_components": ["tools/backtest_replay.py (step 1)", "core/execution_manager.py (step 2, separate proposal)"],
        "risk_level": "HIGH",
        "rollback_plan": "Step 1 changes nothing. Step 2 would ship behind its own proposal and be reverted by revert commit.",
        "claims": [{
            "claim": "Holding positions longer would reduce fee drag enough to improve net P/L.",
            "evidence": f"fees/gross {share:.0%}; <1h holds net {short_net:.2f}, >=1h holds net {long_net:.2f} "
                        f"(tools/performance_report.py over the closed-position archive).",
            "counter_evidence": f"Only {n} trades; every group is below the {MIN_SAMPLE}-trade evidence bar "
                                f"(INCONCLUSIVE). Longer holds also carry more adverse price risk; untested in replay.",
        }],
    }


def losing_coins(report: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for sym, book in (report.get("trader_book") or {}).items():
        if not book.get("available") or book.get("effect", 0) >= 0:
            continue
        out.append({
            "key": f"LOSING-BOOK-{sym}",
            # 2026-10-02: "proven" overclaimed - the trigger is negative expectancy over a minimum trade count,
            # not a significance test (red_team and the owner weigh the sample).
            "title": f"Review {sym}: losing book after fees ({book['trades']} trades, not a significance test)",
            "problem": f"{sym}: {book['trades']} closed trades, net expectancy {book['net_expectancy']:.2f} per trade "
                       f"after estimated fees, longest losing streak {book['longest_losing_streak']}.",
            "motivation": "The runtime already lowers BUY confidence here (BRAIN-MEM-001); the owner decides "
                          "whether the coin stays in the universe.",
            "proposed_changes": f"Owner decision: keep {sym}, or remove it at the next python -m tools.select_universe "
                                "refresh. No automatic change.",
            "affected_components": ["config/universe_selection.json", "config/instrument_rules.json"],
            "risk_level": "MEDIUM",
            "rollback_plan": "Re-add the coin with the next universe refresh.",
            "claims": [{
                "claim": f"Atlas's current strategy loses money on {sym}.",
                "evidence": f"{book['trades']} trades, expectancy {book['net_expectancy']:.2f}, "
                            f"profit factor {book['profit_factor']}.",
                "counter_evidence": "PAPER fills without slippage; fees are an estimate (0.1 %/side); "
                                    "a regime change could reverse it.",
            }],
        })
    return out


def candidates(report: dict[str, Any]) -> list[dict[str, Any]]:
    found = [fee_drag(report)] + losing_coins(report)
    return [c for c in found if c]


def open_keys(directory: Path) -> set[str]:
    state = P.replay(cli.read_log(directory / cli.PROPOSALS_LOG))
    live = {pid for pid, p in state.items()
            if p.status not in P.TERMINAL and p.status not in (P.S.APPLIED,)}
    return {pid.split(".")[0].removeprefix("SA-") for pid in live if pid.startswith("SA-")}


def file_proposals(report: dict[str, Any], directory: Path = cli.RECORDS_DIR, apply: bool = False) -> dict[str, Any]:
    existing = open_keys(directory) if (directory / cli.PROPOSALS_LOG).exists() else set()
    filed, skipped = [], []
    for c in candidates(report):
        key = c.pop("key")
        if key in existing:
            skipped.append(key)
            continue
        pid = f"SA-{key}"
        if apply:
            state = P.replay(cli.read_log(directory / cli.PROPOSALS_LOG)) if (directory / cli.PROPOSALS_LOG).exists() else {}
            n = sum(1 for p in state if p.split(".")[0] == pid)
            pid = f"{pid}.{n + 1}"
            cli.add_proposal_event(directory, proposal_id=pid, event="CREATE", actor=AUTHOR, payload=c)
        filed.append({"id": pid, "title": c["title"], "risk_level": c["risk_level"]})
    return {"filed": filed, "skipped_open": skipped, "applied": apply}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="file the proposals (default: dry run)")
    parser.add_argument("--archive", default=None)
    args = parser.parse_args(argv)
    if args.archive:
        path = Path(args.archive)
    else:
        from core.application import EXECUTION_CLOSED_POSITIONS_FILE, resolve_state_directory

        path = resolve_state_directory() / EXECUTION_CLOSED_POSITIONS_FILE
    if not path.is_file():
        print(f"no closed-position archive at {path}", file=sys.stderr)
        return 1
    from tools.exp001_report import load_closed

    out = file_proposals(analyse(load_closed(path)), apply=args.apply)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not args.apply:
        print("\nDry run: nothing was written. Add --apply to file these proposals for the owner.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
