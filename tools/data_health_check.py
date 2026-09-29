"""Atlas data health check: is every piece of data Atlas relies on sound and realistic?

  python -m tools.data_health_check          # human-readable
  python -m tools.data_health_check --json

Owner request 2026-09-29: "tüm verileri sağlıklı ve gerçekçi istiyorum".
Read-only. The durable financial files are COPIED to a temporary directory
and loaded from there through the runtime's own ExecutionPortfolioFoundation,
so this tool can never write to the real book, even by accident.

Checks (each OK / WARN / FAIL / UNKNOWN; UNKNOWN is never counted as OK):
1. Binance venue rules: load through the canonical loader, freshness policy,
   symbol count vs the 20-coin universe.
2. Financial state: the foundation loads without a recovery marker; cash,
   fees and reserved capital are non-negative; every position has positive
   quantity and cost and average entry = cost / quantity; starting capital
   (book identity) is positive; equity at cost is consistent.
3. Trade realism: every closed trade closes after it opens, prices are
   positive, and no single trade moves more than MAX_TRADE_MOVE (a fill that
   far from its entry on liquid pairs means bad data, not a trade).
4. Governance logs: proposals, tasks and memory replay with intact chains.
5. Telemetry: the durable market-loop telemetry file (if configured) is
   recent and its candle age / cycle duration are plausible.
Exit code: 0 all OK, 1 any WARN/UNKNOWN, 2 any FAIL.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAX_TRADE_MOVE = Decimal("0.5")
TELEMETRY_MAX_AGE_S = 15 * 60


def _result(name: str, status: str, detail: str, **facts: Any) -> dict[str, Any]:
    return {"check": name, "status": status, "detail": detail, **({"facts": facts} if facts else {})}


def check_venue_rules() -> dict[str, Any]:
    from core.application import DEFAULT_INSTRUMENT_RULES_PATH
    from core.instrument_rules import InstrumentRulesConfigError, load_instrument_ruleset
    from core.venue_rule_freshness import VenueRuleFreshnessService

    try:
        ruleset = load_instrument_ruleset(DEFAULT_INSTRUMENT_RULES_PATH)
    except InstrumentRulesConfigError as exc:
        return _result("venue_rules", "FAIL", f"rules do not load: {exc}")
    freshness = VenueRuleFreshnessService().assess(ruleset)
    symbols = sorted(ruleset.symbols)
    status = "OK" if freshness.status.value == "FRESH" else "WARN"
    detail = f"{len(symbols)} coins, freshness {freshness.status.value}"
    if len(symbols) < 20:
        status = "WARN" if status == "OK" else status
        detail += " - fewer than the owner's 20 (run tools/refresh_venue_instrument_rules.py --preset owner-20)"
    return _result("venue_rules", status, detail, symbols=symbols, age_seconds=freshness.age_seconds)


def _load_book(state_dir: Path):
    from core.application import (EXECUTION_APPLIED_EXECUTIONS_FILE, EXECUTION_CLOSED_POSITIONS_FILE,
                                  EXECUTION_FINANCIAL_STATE_FILE)
    from core.execution_portfolio_foundation import (AppliedExecutionArchiveStore, ClosedPositionArchiveStore,
                                                     ExecutionPortfolioFoundation, FinancialStateStore)

    names = (EXECUTION_FINANCIAL_STATE_FILE, EXECUTION_APPLIED_EXECUTIONS_FILE, EXECUTION_CLOSED_POSITIONS_FILE)
    if not (state_dir / EXECUTION_FINANCIAL_STATE_FILE).is_file():
        return None, None
    copy = Path(tempfile.mkdtemp(prefix="atlas_health_"))
    for name in names:
        if (state_dir / name).is_file():
            shutil.copy2(state_dir / name, copy / name)
    foundation = ExecutionPortfolioFoundation(
        FinancialStateStore(copy / names[0]),
        applied_archive=AppliedExecutionArchiveStore(copy / names[1]),
        closed_archive=ClosedPositionArchiveStore(copy / names[2]))
    return foundation, copy


def check_financial_state(state_dir: Path) -> list[dict[str, Any]]:
    try:
        foundation, copy = _load_book(state_dir)
    except Exception as exc:  # the loader's own refusal is the finding
        return [_result("financial_state", "FAIL", f"book does not load: {type(exc).__name__}: {exc}")]
    if foundation is None:
        return [_result("financial_state", "UNKNOWN", f"no financial state in {state_dir} (Atlas not started here?)")]
    try:
        if not foundation.ready:
            return [_result("financial_state", "FAIL", f"recovery required: {foundation.diagnostics().get('reason')}")]
        snap = foundation.snapshot()
        problems = []
        for key in ("cash", "fees", "reserved_capital"):
            if Decimal(str(snap[key])) < 0:
                problems.append(f"{key} is negative ({snap[key]})")
        for symbol, pos in snap["positions"].items():
            qty, cost, avg = (Decimal(str(pos[k])) for k in ("base_quantity", "cost_quote", "average_entry_price"))
            if qty <= 0 or cost <= 0 or avg <= 0:
                problems.append(f"{symbol}: non-positive quantity/cost/price")
            elif abs(avg * qty - cost) > max(cost * Decimal("0.000001"), Decimal("0.00000001")):
                problems.append(f"{symbol}: average entry x quantity != cost")
        starting = snap["cash"] + snap["committed_capital"] + snap["fees"] - snap["realized_gross_pnl"]
        if starting <= 0:
            problems.append(f"starting capital from the book identity is not positive ({starting})")
        results = [_result("financial_state", "FAIL" if problems else "OK",
                           "; ".join(problems) if problems else
                           f"book loads cleanly; starting capital {starting:.2f}, cash {snap['cash']:.2f}, "
                           f"{len(snap['positions'])} open positions, realized net {snap['realized_net_pnl']:.2f}")]
        results.append(check_trade_realism(foundation))
        return results
    finally:
        shutil.rmtree(copy, ignore_errors=True)


def check_trade_realism(foundation) -> dict[str, Any]:
    closed = list(getattr(foundation, "_closed_by_position_id", {}).values())
    if not closed:
        return _result("trade_realism", "OK", "no closed trades yet")
    bad = []
    for trade in closed:
        try:
            entry, exit_ = Decimal(str(trade["average_entry_price"])), Decimal(str(trade["exit_price"]))
            opened = datetime.fromisoformat(str(trade["opened_at"]).replace("Z", "+00:00"))
            closed_at = datetime.fromisoformat(str(trade["closed_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError, ArithmeticError):
            bad.append(f"{trade.get('position_id')}: unreadable fields")
            continue
        if entry <= 0 or exit_ <= 0:
            bad.append(f"{trade.get('symbol')}: non-positive price")
        elif abs(exit_ / entry - 1) > MAX_TRADE_MOVE:
            bad.append(f"{trade.get('symbol')}: {entry} -> {exit_} moves more than {MAX_TRADE_MOVE:.0%}")
        if closed_at < opened:
            bad.append(f"{trade.get('symbol')}: closed before it opened")
    return _result("trade_realism", "FAIL" if bad else "OK",
                   "; ".join(bad[:10]) if bad else f"{len(closed)} closed trades: prices positive, times ordered, moves plausible")


def check_governance_logs() -> dict[str, Any]:
    from atlas_org import memory_records, proposals, tasks
    from tools import atlas_org_cli as cli

    counts = {}
    try:
        counts["proposals"] = len(proposals.replay(cli.read_log(cli.RECORDS_DIR / cli.PROPOSALS_LOG), cli.load_owner_key()))
        counts["tasks"] = len(tasks.replay(cli.read_log(cli.RECORDS_DIR / cli.TASKS_LOG), cli.load_owner_key()))
        counts["memory"] = len(memory_records.replay(cli.read_log(cli.RECORDS_DIR / cli.MEMORY_LOG), cli.load_owner_key()))
    except proposals.ProposalLogError as exc:
        return _result("governance_logs", "FAIL", f"log refused: {exc}")
    return _result("governance_logs", "OK", f"chains intact ({counts})", **counts)


def check_telemetry() -> dict[str, Any]:
    directory = os.environ.get("ATLAS_LOG_DIRECTORY")
    if not directory:
        return _result("telemetry", "UNKNOWN", "ATLAS_LOG_DIRECTORY not set in this shell (durable telemetry location unknown)")
    path = Path(directory) / "market_loop_telemetry.jsonl"
    if not path.is_file():
        return _result("telemetry", "UNKNOWN", f"{path} missing")
    age = datetime.now(UTC).timestamp() - path.stat().st_mtime
    last = None
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 8192))
        for line in handle.read().decode("utf-8", "replace").splitlines()[1:] or []:
            try:
                last = json.loads(line)
            except ValueError:
                continue
    status = "OK" if age <= TELEMETRY_MAX_AGE_S else "WARN"
    detail = f"last write {age:.0f} s ago" + ("" if status == "OK" else " - is Atlas running?")
    if isinstance(last, dict):
        for key, limit in (("candle_age_seconds", 120), ("cycle_duration_seconds", 30)):
            value = last.get(key)
            if isinstance(value, (int, float)) and (value < 0 or value > limit):
                status, detail = "WARN", detail + f"; {key} {value} outside 0..{limit}"
    return _result("telemetry", status, detail)


def run(state_dir: Path | None = None) -> list[dict[str, Any]]:
    from core.application import resolve_state_directory

    state_dir = state_dir or resolve_state_directory()
    results = [check_venue_rules()]
    results += check_financial_state(state_dir)
    results.append(check_governance_logs())
    results.append(check_telemetry())
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--state-dir", default=None)
    args = parser.parse_args(argv)
    results = run(Path(args.state_dir) if args.state_dir else None)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    else:
        print("ATLAS DATA HEALTH")
        for r in results:
            print(f"  {r['status']:<8}{r['check']:<18}{r['detail']}")
    statuses = {r["status"] for r in results}
    return 2 if "FAIL" in statuses else (1 if statuses & {"WARN", "UNKNOWN"} else 0)


if __name__ == "__main__":
    raise SystemExit(main())
