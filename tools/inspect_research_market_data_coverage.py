"""Report P1 window coverage for archived bars, read-only, no venue contact.

Drives ``core.research_market_data_bridge.ResearchMarketDataBridge`` against
the local market data archive, mirroring how
``tools/fetch_historical_market_data.py`` drives ``HistoricalArchiver`` --
except this tool never contacts a venue and never writes to the archive.
Governance: registry v4.69, ``GRANT-COMPUTE-ENGINE-P1-BAR-ACCESS``.

Usage
-----
    python tools/inspect_research_market_data_coverage.py \\
        --symbol BTCUSDT --timeframe 1h \\
        --start 2024-01-01T00:00:00+00:00 --end 2024-01-31T23:00:00+00:00

    python tools/inspect_research_market_data_coverage.py \\
        --symbol BTCUSDT --timeframe 1h --start ... --end ... --json

Exit status is 0 when the window's coverage status is COMPLETE or
GAPS_PRESENT_FLAGGED, and 1 when it is GAPS_PRESENT_REFUSED or the bridge
raised a fail-closed error -- so a caller scripting against this tool can
treat the exit code as "is this window safe to use" without parsing output.
"""

from __future__ import annotations

import argparse
import json
import sys

from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from core.research_market_data_bridge import (  # noqa: E402
    CoverageStatus,
    ResearchMarketDataBridge,
    ResearchMarketDataBridgeError,
    WindowBarAccessResult,
)
from data_layer.market_data_archive_sqlite import MarketDataSQLiteStorage  # noqa: E402

# Same relocatable-root composition-root resolution fetch_historical_market_data.py
# uses, so this tool and the runtime never disagree about where the archive lives.
from core.application import resolve_market_archive_directory  # noqa: E402

DATABASE_FILENAME = "market_data.sqlite3"


def default_database_path() -> Path:
    return resolve_market_archive_directory() / DATABASE_FILENAME


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
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--start", required=True, type=_utc_timestamp)
    parser.add_argument("--end", required=True, type=_utc_timestamp)
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument(
        "--include-bars",
        action="store_true",
        help="Include every bar's OHLCV in JSON output. Off by default: a "
        "wide window can return tens of thousands of bars.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser


def _bar_payload(bar) -> dict:
    return {
        "open_time": datetime.fromtimestamp(bar.open_time_ms / 1000, tz=UTC).isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


def result_payload(result: WindowBarAccessResult, *, include_bars: bool) -> dict:
    coverage = result.coverage
    payload = {
        "symbol": coverage.symbol,
        "timeframe": coverage.timeframe,
        "window_start": coverage.window_start.isoformat(),
        "window_end": coverage.window_end.isoformat(),
        "expected_count": coverage.expected_count,
        "actual_count": coverage.actual_count,
        "missing_count": coverage.missing_count,
        "status": coverage.status.value,
        "gap_ranges": [
            {
                "start": gap.start.isoformat(),
                "end": gap.end.isoformat(),
                "missing_bars": gap.missing_bars,
            }
            for gap in coverage.gap_ranges
        ],
        "provenance": [
            {
                "batch_id": item.batch_id,
                "source": item.source,
                "endpoint": item.endpoint,
                "provider_version": item.provider_version,
                "fetched_at": item.fetched_at.isoformat(),
                "checksum": item.checksum,
                "bar_count_in_window": item.bar_count_in_window,
            }
            for item in coverage.provenance
        ],
    }
    if include_bars:
        payload["bars"] = [_bar_payload(bar) for bar in result.bars]
    return payload


def print_report(result: WindowBarAccessResult) -> None:
    coverage = result.coverage
    print(
        f"{coverage.symbol} {coverage.timeframe} "
        f"[{coverage.window_start.isoformat()} -> {coverage.window_end.isoformat()}]"
    )
    print(
        f"  expected={coverage.expected_count} actual={coverage.actual_count} "
        f"missing={coverage.missing_count} status={coverage.status.value}"
    )
    for gap in coverage.gap_ranges:
        print(
            f"    GAP {gap.start.isoformat()} -> {gap.end.isoformat()} "
            f"({gap.missing_bars} bars)"
        )
    for item in coverage.provenance:
        print(
            f"    BATCH {item.batch_id[:12]} source={item.source} "
            f"endpoint={item.endpoint} fetched_at={item.fetched_at.isoformat()} "
            f"bars_in_window={item.bar_count_in_window}"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database = args.database if args.database is not None else default_database_path()

    # This tool is documented as strictly read-only. MarketDataSQLiteStorage.open()
    # creates its parent directory and schema unconditionally (CREATE TABLE IF NOT
    # EXISTS), which would silently manufacture an empty archive at a mistyped or
    # not-yet-populated path instead of reporting "no archive found here" -- turning
    # a typo into new on-disk state. Refuse before that can happen, rather than
    # relying on the later SymbolNotArchivedError to catch it after the fact.
    if not database.exists():
        message = f"no archive database found at {database}"
        if args.json:
            print(json.dumps({"error": "ArchiveNotFound", "detail": message}))
        else:
            print(f"REFUSED: ArchiveNotFound: {message}", file=sys.stderr)
        return 1

    storage = MarketDataSQLiteStorage(database)
    storage.open()
    try:
        bridge = ResearchMarketDataBridge(storage)
        try:
            result = bridge.load_window(args.symbol, args.timeframe, args.start, args.end)
        except ResearchMarketDataBridgeError as error:
            if args.json:
                print(json.dumps({"error": type(error).__name__, "detail": str(error)}))
            else:
                print(f"REFUSED: {type(error).__name__}: {error}", file=sys.stderr)
            return 1

        if args.json:
            print(json.dumps(result_payload(result, include_bars=args.include_bars), indent=2))
        else:
            print_report(result)

        return 0 if result.coverage.status != CoverageStatus.GAPS_PRESENT_REFUSED else 1
    finally:
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main())
