"""Read-only paper soak report: expectancy, robustness, benchmark and drawdown (Tasks 015-016, registry v5.100).

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

Task 016 adds three further PASS conditions and one stop condition, all pre-registered before day 0:

* Day-block bootstrap: the same bootstrap, but whole UTC closing days are resampled, because trades closed on the
  same day in correlated coins are not independent. Its lower bound must be above zero.
* E without the TOP_REMOVED best trades must stay above zero (the edge is not one or two lucky trades).
* Benchmark: for every trade, the equal-weight basket of the configured trade universe is held over the same
  [opened_at, closed_at]; the trade's gross return minus the basket's return is the excess. Fees are on neither side
  (the trade side is gross of fees). The trade's gross return does contain the paper fill slippage (5 bps adverse on
  each fill, so about 10 bps a round trip), which the basket's raw bar prices do not: the excess is therefore
  understated by about 0.1 percentage point per trade, a bias against a PASS that makes the bar stricter than a
  passive basket. The mean excess, its trade-level bootstrap lower bound and its day-block lower bound (trades closed on one
  day in correlated coins are not independent) must all be above zero. A basket held over the same windows is not
  circular, unlike the same coin over the same window, and BTC is shown beside it for information. The
  prices are 1h archived bars (the archive that tools/fetch_historical_market_data.py fills; it is opened read-only and immutable, so no
  side file is created, and an unfinished write-ahead log makes it unavailable),
  linearly interpolated inside the hour. Any missing bar makes the benchmark UNAVAILABLE and a PASS impossible.
* Drawdown: the maximum peak-to-trough fall of realized net equity (starting capital plus net P&L by closing time)
  at or above DRAWDOWN_STOP_PCT is a stop condition: it prints STOP CONDITION and exits 3. Unrealized losses are not
  in this figure.

The trade archive is read through ClosedPositionArchiveStore.load_index, the reader Atlas itself uses at startup, so
the same sequence, retry and conflict rules apply. The financial state is read as plain JSON, not through Atlas's own
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
import sqlite3
import sys
from datetime import UTC, datetime
from decimal import ROUND_UP, Decimal, localcontext
from pathlib import Path
from typing import Any

from core.application import (
    DEFAULT_INSTRUMENT_RULES_PATH,
    EXECUTION_CLOSED_POSITIONS_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    ConfiguredDirectoryError,
    resolve_market_archive_directory,
    resolve_state_directory,
)
from core.execution_manager import PAPER_FEE_QUANTUM, PAPER_FEE_RATE_PER_SIDE
from core.execution_portfolio_foundation import ClosedPositionArchiveError, ClosedPositionArchiveStore
from core.instrument_rules import load_instrument_ruleset

# Pre-registered on sheet lines 3, 5-8, the Task 014 lower-bound rule and the Task 016 additions. Not command-line
# options on purpose: they are fixed before day 0 and not changed after seeing results.
TARGET_TRADES = 100
MIN_TRADES_FOR_A_VERDICT = 30
RESAMPLES = 10_000
SEED = 20261017
LOWER_QUANTILE = 0.05
TOP_REMOVED = 3
DRAWDOWN_STOP_PCT = Decimal("10")
# The account's own settlement precision (core/execution_portfolio_foundation SETTLEMENT_CONTEXT_PRECISION is 50).
SUM_PRECISION = 50
# The bootstrap tool's default total capital (sheet line 13); --capital overrides it when the owner bootstrapped
# another amount.
DEFAULT_START_CAPITAL = Decimal("10000")
# A sane range for --capital: outside it the 10 % stop is unreachable or the arithmetic overflows.
CAPITAL_RANGE = (Decimal("1"), Decimal("1000000000000"))
BENCHMARK_TIMEFRAME = "1h"
BENCHMARK_BTC = "BTCUSDT"
# The file tools/fetch_historical_market_data.py (the archive's only writer) creates in the market archive directory.
MARKET_ARCHIVE_FILENAME = "market_data.sqlite3"
# A basket of one or two coins would be (nearly) the traded coin itself; the configured universe is at most 20.
MIN_BASKET_COINS = 10
HOUR_MS = 3_600_000


class Refused(ValueError):
    pass


class BenchmarkUnavailable(ValueError):
    pass


def capital_argument(value: str) -> Decimal:
    """argparse type for --capital: a finite number above zero, else a usage error (exit 2) rather than a traceback."""
    try:
        capital = Decimal(value)
    except ArithmeticError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number") from None
    if not capital.is_finite() or not CAPITAL_RANGE[0] <= capital <= CAPITAL_RANGE[1]:
        raise argparse.ArgumentTypeError(f"--capital must be a number from {CAPITAL_RANGE[0]} to {CAPITAL_RANGE[1]}")
    return capital


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


def lower_bound(nets: list[Any], resamples: int = RESAMPLES, seed: int = SEED) -> float | None:
    """One-sided 95 % percentile-bootstrap lower bound of the mean; None without values.

    Draws use random() only, whose sequence for a given seed Python keeps reproducible across versions.
    """
    if not nets:
        return None
    values = [float(v) for v in nets]
    n = len(values)
    rng = random.Random(seed)
    means = sorted(math.fsum(values[int(rng.random() * n)] for _ in range(n)) / n for _ in range(resamples))
    return means[math.ceil(LOWER_QUANTILE * resamples) - 1]


def day_block_lower_bound(records: list[dict[str, Any]], nets: list[Decimal], resamples: int = RESAMPLES,
                          seed: int = SEED) -> float | None:
    """Lower bound of E when whole UTC closing days are resampled (mean = resampled net sum / resampled trades)."""
    days: dict[Any, list[float]] = {}
    for record, net in zip(records, nets):
        day = parse_utc(record["closed_at"]).astimezone(UTC).date()
        total = days.setdefault(day, [0.0, 0])
        total[0] += float(net)
        total[1] += 1
    if not days:
        return None
    blocks = list(days.values())
    count = len(blocks)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        total, trades = 0.0, 0
        for _ in range(count):
            block = blocks[int(rng.random() * count)]
            total += block[0]
            trades += block[1]
        means.append(total / trades)
    means.sort()
    return means[math.ceil(LOWER_QUANTILE * resamples) - 1]


def mean_without_best(nets: list[Decimal], removed: int = TOP_REMOVED) -> Decimal | None:
    """E after dropping the `removed` largest net P&Ls; None when that would leave nothing."""
    if len(nets) <= removed:
        return None
    rest = sorted(nets, reverse=True)[removed:]
    return sum(rest, Decimal("0")) / len(rest)


def realized_drawdown_pct(records: list[dict[str, Any]], capital: Decimal) -> Decimal:
    """Maximum peak-to-trough fall of capital plus cumulative net P&L, in closing order, as a percentage."""
    equity = peak = capital
    worst = Decimal("0")
    for record in sorted(records, key=lambda r: (parse_utc(r["closed_at"]), r["position_id"])):
        equity += net_pnl(record)
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak * 100)
    return worst


def basket_symbols(rules_path: Path) -> list[str]:
    try:
        symbols = sorted(load_instrument_ruleset(rules_path).symbols)
    except Exception as exc:  # the loader raises its own config error types
        raise BenchmarkUnavailable(f"trade universe from {rules_path}: {exc}") from exc
    if len(symbols) < MIN_BASKET_COINS:
        raise BenchmarkUnavailable(f"trade universe from {rules_path} has {len(symbols)} coins, fewer than the "
                                   f"{MIN_BASKET_COINS} a basket needs to be more than the traded coin itself")
    return symbols


def read_bars(database: Path, symbol: str, start_ms: int, end_ms: int) -> dict[int, tuple[float, float]]:
    """{open_time_ms: (open, close)} of the archived 1h bars in [start_ms, end_ms], read through a read-only connection."""
    if not database.is_file():
        raise BenchmarkUnavailable(f"no market archive at {database}")
    # An immutable read takes no lock and creates no -wal/-shm side file, but it ignores a write-ahead log. So a log
    # that still holds data (a writer is running or died) makes the archive unusable here rather than silently short.
    log = database.with_name(database.name + "-wal")
    if log.exists() and log.stat().st_size > 0:
        raise BenchmarkUnavailable(f"market archive {database} has an unfinished write-ahead log: let the fetch tool "
                                   "finish, or close what has the archive open, and run this again")
    try:
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
        try:
            rows = connection.execute(
                "SELECT open_time_ms, open, close FROM market_data_bars "
                "WHERE symbol = ? AND timeframe = ? AND open_time_ms BETWEEN ? AND ?",
                (symbol, BENCHMARK_TIMEFRAME, start_ms, end_ms)).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise BenchmarkUnavailable(f"market archive {database}: {exc}") from exc
    return {int(open_ms): (float(open_), float(close)) for open_ms, open_, close in rows}


def price_at(bars: dict[int, tuple[float, float]], moment_ms: int, symbol: str) -> float:
    """The price at a moment: linear from the containing hour's open to its close. A missing bar is never guessed."""
    open_ms = moment_ms - moment_ms % HOUR_MS
    bar = bars.get(open_ms)
    if bar is None:
        stamp = datetime.fromtimestamp(open_ms / 1000, UTC).isoformat()
        raise BenchmarkUnavailable(f"no archived {BENCHMARK_TIMEFRAME} bar for {symbol} at {stamp}")
    return bar[0] + (bar[1] - bar[0]) * (moment_ms - open_ms) / HOUR_MS


def window_returns(records: list[dict[str, Any]], symbols: list[str], database: Path) -> list[float]:
    """Per trade, the equal-weight mean return of `symbols` held over the trade's own [opened_at, closed_at]."""
    if not records or not symbols:
        return []
    spans = [(round(parse_utc(r["opened_at"]).timestamp() * 1000), round(parse_utc(r["closed_at"]).timestamp() * 1000))
             for r in records]
    first = min(s for s, _ in spans)
    last = max(e for _, e in spans)
    per_symbol = {}
    for symbol in symbols:
        bars = read_bars(database, symbol, first - first % HOUR_MS, last)
        per_symbol[symbol] = [price_at(bars, end, symbol) / price_at(bars, start, symbol) - 1 for start, end in spans]
    return [sum(per_symbol[s][i] for s in symbols) / len(symbols) for i in range(len(records))]


def excess_summary(records: list[dict[str, Any]], benchmark: list[float]) -> dict[str, Any]:
    """Mean excess return (fraction) with its trade-level and day-block lower bounds: gross return minus the benchmark's."""
    excess = [float(Decimal(str(r["gross_pnl"])) / Decimal(str(r["cost_quote"]))) - b
              for r, b in zip(records, benchmark)]
    return {"mean": math.fsum(excess) / len(excess) if excess else None, "lower_bound": lower_bound(excess),
            "day_lower_bound": day_block_lower_bound(records, excess)}


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
        "day_lower_bound": day_block_lower_bound(records, nets),
        "top_removed_e": mean_without_best(nets),
    }


def above_zero(value: Any) -> bool:
    """True only for a number greater than zero; None and NaN are not (a comparison with NaN must not pass)."""
    if value is None:
        return False
    try:
        return bool(value > 0)
    except (ArithmeticError, TypeError):  # an ordering comparison with a Decimal NaN raises
        return False


def verdict(summary: dict[str, Any], archive_complete: bool = True) -> str:
    """Sheet lines 5-8 plus the Task 016 PASS conditions. A condition that was not computed counts as not met."""
    n, e, low = summary["trades"], summary["e"], summary["lower_bound"]
    if n < MIN_TRADES_FOR_A_VERDICT:
        return f"INSUFFICIENT ({n} < {MIN_TRADES_FOR_A_VERDICT} trades)"
    if not above_zero(e):
        return "FAIL (E <= 0)"
    if not above_zero(low):
        return "INCONCLUSIVE (E > 0, lower bound <= 0)"
    if n < TARGET_TRADES:
        return f"INCONCLUSIVE (E > 0, {n} < {TARGET_TRADES} trades)"
    reasons = []
    if not archive_complete:
        reasons.append("the archive does not account for all realized P&L")
    if not above_zero(summary.get("day_lower_bound")):
        reasons.append("the day-block lower bound of E is not above zero")
    if not above_zero(summary.get("top_removed_e")):
        reasons.append(f"E without the {TOP_REMOVED} best trades is not above zero")
    excess_figures = [summary.get(k) for k in ("excess_mean", "excess_lower_bound", "excess_day_lower_bound")]
    if any(figure is None for figure in excess_figures):
        reasons.append("the benchmark is unavailable")
    elif not all(above_zero(figure) for figure in excess_figures):
        reasons.append("the trades do not beat the basket held over the same windows")
    if reasons:
        return "INCONCLUSIVE (PASS conditions on E hold, but " + "; ".join(reasons) + ")"
    return "PASS (E > 0, lower bounds > 0, beats the basket)"


def fetch_hint(symbols: list[str], records: list[dict[str, Any]]) -> str:
    first = min(parse_utc(r["opened_at"]) for r in records).replace(minute=0, second=0, microsecond=0)
    last = max(parse_utc(r["closed_at"]) for r in records)
    return (f"python tools/fetch_historical_market_data.py --symbols {' '.join(symbols)} --timeframe "
            f"{BENCHMARK_TIMEFRAME} --start {first.isoformat()} --end {last.replace(minute=59, second=59).isoformat()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only paper soak expectancy report")
    parser.add_argument("--start", required=True, help="day-0 start, UTC ISO 8601 with timezone (sheet line 1)")
    parser.add_argument("--end", help="end of run, UTC ISO 8601 with timezone; without it the verdict is interim")
    parser.add_argument("--capital", type=capital_argument, default=DEFAULT_START_CAPITAL,
                        help="starting capital for the drawdown (sheet line 13; default is the bootstrap default)")
    parser.add_argument("--instrument-rules", type=Path, default=DEFAULT_INSTRUMENT_RULES_PATH,
                        help="rules file whose symbols are the benchmark basket (the trade universe)")
    parser.add_argument("--market-archive", type=Path, default=None,
                        help=f"market archive database (default: {MARKET_ARCHIVE_FILENAME} in the market archive "
                             "directory)")
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
    print(f"inputs in effect: --capital {args.capital}; --instrument-rules {args.instrument_rules}; "
          f"--market-archive {args.market_archive if args.market_archive else 'default'}")

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
        closing_days = len({parse_utc(r["closed_at"]).astimezone(UTC).date() for r in records})
        print(f"day-block lower bound of E (whole UTC closing days resampled; {closing_days} distinct closing days): "
              f"{summary['day_lower_bound']:.4f}")
        if summary["top_removed_e"] is None:
            print(f"E without the {TOP_REMOVED} best trades: not computable (too few trades)")
        else:
            print(f"E without the {TOP_REMOVED} best trades: {summary['top_removed_e']:.4f}")

    if records:
        database = args.market_archive
        try:
            if database is None:
                database = resolve_market_archive_directory() / MARKET_ARCHIVE_FILENAME
            symbols = basket_symbols(args.instrument_rules)
            basket = excess_summary(records, window_returns(records, symbols, database))
            summary["excess_mean"], summary["excess_lower_bound"] = basket["mean"], basket["lower_bound"]
            summary["excess_day_lower_bound"] = basket["day_lower_bound"]
            print(f"benchmark: equal-weight basket of {len(symbols)} universe coins over each trade's own window "
                  f"({BENCHMARK_TIMEFRAME} archived bars, interpolated)")
            print(f"  mean excess return per trade: {basket['mean'] * 100:.4f} %  95 % lower bound: "
                  f"{basket['lower_bound'] * 100:.4f} %  day-block lower bound: {basket['day_lower_bound'] * 100:.4f} %")
            try:
                btc = excess_summary(records, window_returns(records, [BENCHMARK_BTC], database))
                print(f"  for information, against {BENCHMARK_BTC} alone: mean excess {btc['mean'] * 100:.4f} %, "
                      f"lower bound {btc['lower_bound'] * 100:.4f} % (not part of the verdict)")
            except BenchmarkUnavailable as exc:
                print(f"  {BENCHMARK_BTC} comparison unavailable ({exc}); not part of the verdict")
        except (BenchmarkUnavailable, ConfiguredDirectoryError) as exc:
            print(f"benchmark: UNAVAILABLE ({exc}); a PASS is not possible without it")
            try:
                print(f"  fetch the bars (public data, no key): {fetch_hint(sorted(set(basket_symbols(args.instrument_rules)) | {BENCHMARK_BTC}), records)}")
            except BenchmarkUnavailable:
                pass
        except Exception as exc:  # noqa: BLE001 - whatever the data holds, the stop condition below must still be reported
            for key in ("excess_mean", "excess_lower_bound", "excess_day_lower_bound"):
                summary.pop(key, None)  # a half-computed benchmark must not count as met
            print(f"benchmark: UNAVAILABLE (unexpected {type(exc).__name__}: {exc}); a PASS is not possible without it")
    drawdown = realized_drawdown_pct(records, args.capital)
    print(f"realized drawdown: {drawdown:.2f} % of peak (starting capital {args.capital}; stop at "
          f"{DRAWDOWN_STOP_PCT} %; unrealized losses are not included)")
    print(f"verdict{'' if end else ' (interim; final only at the end of run with --end)'}: "
          f"{verdict(summary, archive_complete)}")
    stopped = drawdown >= DRAWDOWN_STOP_PCT
    if stopped:
        print(f"STOP CONDITION: realized drawdown {drawdown:.2f} % is at or above {DRAWDOWN_STOP_PCT} %")
    print("Nothing was changed.")
    return 3 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
