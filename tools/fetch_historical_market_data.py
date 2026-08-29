"""Acquire and archive real historical OHLCV bars from Binance's public API.

Read-only with respect to the venue: this uses the unauthenticated klines
endpoint, holds no API key and cannot place orders.

Usage
-----
    python tools/fetch_historical_market_data.py
    python tools/fetch_historical_market_data.py --symbols BTCUSDT ETHUSDT
    python tools/fetch_historical_market_data.py --coverage-only

Re-running is safe: bars already archived are not duplicated and their
recorded provenance is not overwritten.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from atlas_finance.market_data.binance_public_provider import (  # noqa: E402
    BinancePublicDataProvider,
)
from atlas_finance.market_data.historical_archive import (  # noqa: E402
    ArchiveRunResult,
    HistoricalArchiver,
    StopReason,
)
from data_layer.market_data_sqlite import (  # noqa: E402
    CoverageReport,
    MarketDataSQLiteStorage,
)

DEFAULT_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
)

DEFAULT_TIMEFRAME = "1h"
DEFAULT_DATABASE = REPOSITORY_ROOT / "data" / "market_archive" / "market_data.sqlite3"

logger = logging.getLogger("atlas.tools.fetch_historical_market_data")


def _utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"expected an ISO-8601 timestamp, got {value!r}"
        ) from error
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument(
        "--request-interval-seconds",
        type=float,
        default=0.25,
        help="Delay between paged requests. Raise it to be gentler on the venue.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=1000,
        help="Candles per request. Binance caps klines at 1000.",
    )
    parser.add_argument(
        "--max-requests-per-symbol",
        type=int,
        default=2000,
        help="Hard ceiling on requests per symbol, as a runaway guard.",
    )
    parser.add_argument(
        "--start",
        type=_utc_timestamp,
        default=None,
        help=(
            "ISO-8601 UTC start. Overrides resuming from the archive; use it "
            "to re-attempt a reported gap."
        ),
    )
    parser.add_argument(
        "--end",
        type=_utc_timestamp,
        default=None,
        help="ISO-8601 UTC end. Defaults to now.",
    )
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="Report archived coverage without contacting the venue.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser


def coverage_payload(report: CoverageReport) -> dict:
    return {
        "symbol": report.symbol,
        "timeframe": report.timeframe,
        "bar_count": report.bar_count,
        "first_open_time": (
            report.first_open_time.isoformat() if report.first_open_time else None
        ),
        "last_open_time": (
            report.last_open_time.isoformat() if report.last_open_time else None
        ),
        "expected_bars": report.expected_bars,
        "missing_bars": report.missing_bars,
        "gaps": [
            {
                "gap_start": datetime.fromtimestamp(
                    gap.gap_start_ms / 1000, tz=UTC
                ).isoformat(),
                "gap_end": datetime.fromtimestamp(
                    gap.gap_end_ms / 1000, tz=UTC
                ).isoformat(),
                "missing_bars": gap.missing_bars,
            }
            for gap in report.gaps
        ],
    }


def run_payload(result: ArchiveRunResult) -> dict:
    return {
        "symbol": result.symbol,
        "requests_made": result.requests_made,
        "bars_fetched": result.bars_fetched,
        "bars_inserted": result.bars_inserted,
        "bars_already_present": result.bars_already_present,
        "batches_recorded": result.batches_recorded,
        "conflicts": len(result.conflicts),
        "stop_reason": result.stop_reason,
        "rate_limit_detail": result.rate_limit_detail,
    }


def print_report(report: CoverageReport) -> None:
    first = report.first_open_time.isoformat() if report.first_open_time else "-"
    last = report.last_open_time.isoformat() if report.last_open_time else "-"
    print(
        f"  {report.symbol:<10} bars={report.bar_count:>7}  "
        f"{first}  ->  {last}  "
        f"missing={report.missing_bars}  gaps={len(report.gaps)}"
    )
    for gap in report.gaps:
        gap_start = datetime.fromtimestamp(gap.gap_start_ms / 1000, tz=UTC)
        gap_end = datetime.fromtimestamp(gap.gap_end_ms / 1000, tz=UTC)
        print(
            f"      GAP {gap_start.isoformat()} -> {gap_end.isoformat()} "
            f"({gap.missing_bars} bars)"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    storage = MarketDataSQLiteStorage(args.database)
    storage.open()

    runs: list[ArchiveRunResult] = []
    rate_limited = False

    try:
        if not args.coverage_only:
            provider = BinancePublicDataProvider(timeout_seconds=20.0)
            archiver = HistoricalArchiver(
                provider,
                storage,
                page_size=args.page_size,
                request_interval_seconds=args.request_interval_seconds,
                max_requests_per_symbol=args.max_requests_per_symbol,
            )
            try:
                for symbol in args.symbols:
                    logger.info("Archiving %s %s", symbol, args.timeframe)
                    result = archiver.archive_symbol(
                        symbol,
                        args.timeframe,
                        start=args.start,
                        end=args.end,
                    )
                    runs.append(result)
                    if result.stop_reason == StopReason.RATE_LIMITED:
                        rate_limited = True
                        logger.error(
                            "Stopping the run: %s was rate limited (%s)",
                            symbol,
                            result.rate_limit_detail,
                        )
                        break
            finally:
                provider.disconnect()

        reports = [
            storage.coverage(symbol, args.timeframe) for symbol in args.symbols
        ]

        if args.json:
            print(
                json.dumps(
                    {
                        "database": str(storage.database_path),
                        "timeframe": args.timeframe,
                        "runs": [run_payload(run) for run in runs],
                        "coverage": [coverage_payload(report) for report in reports],
                        "health": storage.health(),
                    },
                    indent=2,
                )
            )
        else:
            for run in runs:
                print(
                    f"  {run.symbol:<10} requests={run.requests_made:<5} "
                    f"fetched={run.bars_fetched:<7} inserted={run.bars_inserted:<7} "
                    f"present={run.bars_already_present:<7} "
                    f"conflicts={len(run.conflicts)} stop={run.stop_reason}"
                )
            print(f"\nCoverage ({args.timeframe}) in {storage.database_path}:")
            for report in reports:
                print_report(report)
    finally:
        storage.close()

    return 2 if rate_limited else 0


if __name__ == "__main__":
    raise SystemExit(main())
