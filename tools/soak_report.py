"""Read-only paper soak report: expectancy E, E% and its 95 % lower bound (Task 015, registry v5.99).

  python -m tools.soak_report --start 2026-10-18T00:00:00Z
  python -m tools.soak_report --start 2026-10-18T00:00:00Z --end 2026-11-08T00:00:00Z

The figures are the ones fixed in docs/operations/TASK014_PAPER_VERIFICATION_2026-10-17.md §3 and the pre-registration
sheet in docs/operations/TASK015_SOAK_DAY0_PLAN_2026-10-17.md §1:

* Only closed positions opened at or after --start and closed before --end count. Positions still open are listed and
  excluded.
* Net P&L per trade = gross_pnl - recorded entry_fees - exit fee. The 5 bps slippage is already inside gross_pnl,
  because it is applied to the fill price. The archive stores no exit fee; paper execution books
  PAPER_FEE_RATE_PER_SIDE of the exit notional, rounded up to PAPER_FEE_QUANTUM, and on a full close the exit
  notional is cost_quote + gross_pnl. The report computes it the same way.
* E is the mean net P&L per trade; E% is the mean of net P&L / cost_quote, in percent.
* The lower bound is a one-sided 95 % percentile bootstrap of E: RESAMPLES resamples with replacement, drawn with a
  fixed seed, and the lower empirical 5 % quantile of their means.
* The verdict applies sheet lines 5-8. Line 9 (an E% floor) was set to none by the owner, so no floor is applied.

The archive is read through ClosedPositionArchiveStore.load_index, the reader Atlas itself uses at startup, so the
same sequence, retry and conflict rules apply. The financial state is read as plain JSON, not through Atlas's own
loader: only the open positions and the realized gross P&L are checked, so a pending recovery marker is not flagged.
It never writes and takes no lock. Whether a reader holding a file open can disturb Atlas's file replacement on
Windows is UNKNOWN (registry v5.99), as for the other read-only reports. An archive it cannot read as Atlas would, an
unreadable financial state or an unusable state directory is refused (exit 2, a REFUSED line), never skipped.

The archive keeps only the last leg of a position that was partly sold before its close. When the archive's gross
P&L differs from the account's realized gross P&L, or the account cannot be compared, the per-trade figures are
incomplete: the report says so, and a PASS is then reported as INCONCLUSIVE. That rule can only lower a verdict. The
check compares gross P&L only, so partial legs whose gross sums to exactly zero are not detected.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime
from decimal import ROUND_UP, Decimal, localcontext
from pathlib import Path
from typing import Any

from core.application import (
    EXECUTION_CLOSED_POSITIONS_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    ConfiguredDirectoryError,
    resolve_state_directory,
)
from core.execution_manager import PAPER_FEE_QUANTUM, PAPER_FEE_RATE_PER_SIDE
from core.execution_portfolio_foundation import ClosedPositionArchiveError, ClosedPositionArchiveStore

# Pre-registered on sheet lines 3, 5-8 and the Task 014 lower-bound rule. Not command-line options on purpose: they
# are fixed before day 0 and not changed after seeing results.
TARGET_TRADES = 100
MIN_TRADES_FOR_A_VERDICT = 30
RESAMPLES = 10_000
SEED = 20261017
LOWER_QUANTILE = 0.05
# The account's own settlement precision (core/execution_portfolio_foundation SETTLEMENT_CONTEXT_PRECISION is 50).
SUM_PRECISION = 50


class Refused(ValueError):
    pass


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timestamp {value!r} has no timezone")
    return parsed


def load_archive(path: Path) -> list[dict[str, Any]]:
    """Every closed-position record in archive order, read exactly as Atlas reads it at startup."""
    try:
        return list(ClosedPositionArchiveStore(path).load_index().by_position_id.values())
    except (ClosedPositionArchiveError, OSError, UnicodeDecodeError) as exc:
        raise Refused(f"closed-position archive {path}: {exc}") from exc


def load_account(path: Path) -> tuple[dict[str, dict[str, Any]], Decimal] | None:
    """(open positions, realized gross P&L) from the financial state, or None when the file does not exist."""
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        positions = state["positions"]
        realized = Decimal(str(state["realized_gross_pnl"]))
        if (not isinstance(positions, dict) or not all(isinstance(p, dict) for p in positions.values())
                or not realized.is_finite()):
            raise ValueError("unexpected shape")
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        raise Refused(f"financial state {path}: {exc}") from exc
    return positions, realized


def in_window(records: list[dict[str, Any]], start: datetime, end: datetime | None) -> tuple[list, int, int]:
    """(records in the window, count opened before start, count closed at or after end)."""
    kept, before, after = [], 0, 0
    for record in records:
        if parse_utc(record["opened_at"]) < start:
            before += 1
        elif end is not None and parse_utc(record["closed_at"]) >= end:
            after += 1
        else:
            kept.append(record)
    return kept, before, after


def exit_fee(record: dict[str, Any]) -> Decimal:
    """The paper exit fee as booked: rate x exit notional, rounded up to PAPER_FEE_QUANTUM (never under-charged)."""
    exit_notional = Decimal(str(record["cost_quote"])) + Decimal(str(record["gross_pnl"]))
    return (PAPER_FEE_RATE_PER_SIDE * max(exit_notional, Decimal("0"))).quantize(PAPER_FEE_QUANTUM, rounding=ROUND_UP)


def net_pnl(record: dict[str, Any]) -> Decimal:
    return Decimal(str(record["gross_pnl"])) - Decimal(str(record["entry_fees"])) - exit_fee(record)


def archive_gross(records: list[dict[str, Any]]) -> Decimal:
    with localcontext() as context:
        context.prec = SUM_PRECISION
        return sum((Decimal(str(r["gross_pnl"])) for r in records), Decimal("0"))


def lower_bound(nets: list[Decimal], resamples: int = RESAMPLES, seed: int = SEED) -> float | None:
    """One-sided 95 % percentile-bootstrap lower bound of the mean; None without trades.

    Draws use random() only, whose sequence for a given seed Python keeps reproducible across versions.
    """
    if not nets:
        return None
    values = [float(v) for v in nets]
    n = len(values)
    rng = random.Random(seed)
    means = sorted(math.fsum(values[int(rng.random() * n)] for _ in range(n)) / n for _ in range(resamples))
    return means[math.ceil(LOWER_QUANTILE * resamples) - 1]


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    nets = [net_pnl(r) for r in records]
    n = len(nets)
    return {
        "trades": n,
        "gross_pnl": sum((Decimal(str(r["gross_pnl"])) for r in records), Decimal("0")),
        "entry_fees": sum((Decimal(str(r["entry_fees"])) for r in records), Decimal("0")),
        "net_pnl": sum(nets, Decimal("0")),
        "wins": sum(1 for v in nets if v > 0),
        "e": sum(nets, Decimal("0")) / n if n else None,
        "e_pct": (sum((v / Decimal(str(r["cost_quote"])) for v, r in zip(nets, records)), Decimal("0"))
                  * 100 / n) if n else None,
        "lower_bound": lower_bound(nets),
    }


def verdict(summary: dict[str, Any], archive_complete: bool = True) -> str:
    n, e, low = summary["trades"], summary["e"], summary["lower_bound"]
    if n < MIN_TRADES_FOR_A_VERDICT:
        return f"INSUFFICIENT ({n} < {MIN_TRADES_FOR_A_VERDICT} trades)"
    if e <= 0:
        return "FAIL (E <= 0)"
    if low <= 0:
        return "INCONCLUSIVE (E > 0, lower bound <= 0)"
    if n < TARGET_TRADES:
        return f"INCONCLUSIVE (E > 0, {n} < {TARGET_TRADES} trades)"
    if not archive_complete:
        return "INCONCLUSIVE (PASS conditions hold, but the archive does not account for all realized P&L)"
    return "PASS (E > 0, lower bound > 0)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only paper soak expectancy report")
    parser.add_argument("--start", required=True, help="day-0 start, UTC ISO 8601 with timezone (sheet line 1)")
    parser.add_argument("--end", help="end of run, UTC ISO 8601 with timezone; without it the verdict is interim")
    args = parser.parse_args(argv)
    try:
        start = parse_utc(args.start)
        end = parse_utc(args.end) if args.end else None
    except ValueError as exc:
        parser.error(str(exc))
    if end is not None and end <= start:
        parser.error("--end must be after --start")

    try:
        root = resolve_state_directory()
        print(f"state root: {root}")
        archive = load_archive(root / EXECUTION_CLOSED_POSITIONS_FILE)
        account = load_account(root / EXECUTION_FINANCIAL_STATE_FILE)
    except (Refused, ConfiguredDirectoryError) as exc:
        print(f"REFUSED: {exc}. Nothing was computed.")
        return 2
    records, before, after = in_window(archive, start, end)
    print(f"window: opened at or after {start.isoformat()}, closed before "
          f"{end.isoformat() if end else 'now (run not ended)'}")
    print(f"archive: {len(archive)} closed; in window {len(records)}; opened before start {before}; "
          f"closed at or after end {after}")

    if account is None:
        archive_complete = False
        print("WARNING: no financial state: open positions UNKNOWN and the archive cannot be checked against the "
              "account")
    else:
        positions, account_gross = account
        print(f"open positions (excluded): {len(positions)}")
        for symbol, item in sorted(positions.items()):
            print(f"  {symbol} {item.get('position_id')} opened {item.get('opened_at')}")
        archived = archive_gross(archive)
        archive_complete = archived == account_gross
        if not archive_complete:
            print(f"WARNING: archive gross P&L {archived} differs from the account's realized gross P&L "
                  f"{account_gross}: partial sales or history before the archive are not in the per-trade figures")

    summary = summarize(records)
    print()
    print(f"trades: {summary['trades']}  wins after fees: {summary['wins']}")
    print(f"gross P&L: {summary['gross_pnl']:.2f}  recorded entry fees: {summary['entry_fees']:.2f}  "
          f"exit fee rate: {PAPER_FEE_RATE_PER_SIDE}  net P&L: {summary['net_pnl']:.2f}")
    if summary["trades"]:
        print(f"E (net per trade): {summary['e']:.4f}  E%: {summary['e_pct']:.4f} %")
        print(f"95 % lower bound of E (bootstrap, {RESAMPLES} resamples, seed {SEED}): {summary['lower_bound']:.4f}")
    print(f"verdict{'' if end else ' (interim; final only at the end of run with --end)'}: "
          f"{verdict(summary, archive_complete)}")
    print("Nothing was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
