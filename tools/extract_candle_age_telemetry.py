"""Read-only extraction/analysis of the durable MarketLoop telemetry log.

Governance: registry v4.72, ``GRANT-S3-M2-EXTRACTION-TOOL``.

Parses ``<ATLAS_LOG_DIRECTORY>/market_loop_telemetry.jsonl`` (filename from
``core.logger.TELEMETRY_LOG_FILE``, written by
``core.market_loop.MarketLoop._emit_cycle_telemetry`` per registry v4.71) and
reports, per symbol and overall:

- ``candle_age_seconds`` distribution over ``MEASURED`` records only (count,
  min, max, mean, median, p50/p90/p95/p99) -- the evidence S-3 (market-data
  staleness threshold) needs;
- ``candle_age_status`` / reason-code frequency counts, for every status, not
  only ``MEASURED``;
- ``cycle_duration_seconds`` distribution, de-duplicated to one value per
  (run, cycle) -- the evidence M-2 (supervisor stall-detection threshold)
  needs. A run boundary is detected wherever the file-order cycle sequence
  goes backwards, because schema_version 1 carries no run/instance id
  (checkpoints/20260924T123057Z_candle-age-durable-telemetry.md, "Deferred
  improvements"). This is an inference from write order, not a guaranteed
  identity: two runs that never advance past cycle 1 cannot be told apart.

This tool computes and reports statistics only. It writes no file, proposes
no threshold, and never writes an S-3 or M-2 value into any file -- registry
v4.41 forbids that until the owner decides. Extraction rules follow runbook
step 6 of checkpoints/20260924T123057Z_candle-age-durable-telemetry.md.

Fails closed on malformed input: a blank line, a malformed-JSON line, a
JSON value that is not an object, or an object missing a required field is
skipped and counted, never raised out of the parse loop.

Usage
-----
    python tools/extract_candle_age_telemetry.py
    python tools/extract_candle_age_telemetry.py --json
    python tools/extract_candle_age_telemetry.py --log-directory C:\\AtlasState\\logs

Exit status is 0 whenever the tool runs to completion, including a "zero
records found" outcome -- that is a legitimate, reportable result, not a
failure. It is 1 only when an explicit ``--log-directory`` does not point at
an existing directory, or when the configured ``ATLAS_LOG_DIRECTORY`` itself
is invalid (empty, relative, missing, or not a directory) per
``core.application``'s fail-closed validator.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from core.application import ConfiguredDirectoryError, resolve_log_directory  # noqa: E402
from core.logger import TELEMETRY_LOG_FILE  # noqa: E402
from core.market_loop import TELEMETRY_SCHEMA_VERSION, MarketLoop  # noqa: E402

MEASURED_STATUS = MarketLoop.CANDLE_AGE_MEASURED

REQUIRED_FIELDS = (
    "schema_version",
    "symbol",
    "cycle",
    "cycle_duration_seconds",
    "candle_age_seconds",
    "candle_age_status",
)

PERCENTILES = (50, 90, 95, 99)


# ---------------------------------------------------------------------------
# Parsing -- fails closed on every malformed shape, never raises.
# ---------------------------------------------------------------------------


class ParseStats:
    def __init__(self) -> None:
        self.total_lines = 0
        self.blank_lines = 0
        self.malformed_json_lines = 0
        self.non_object_lines = 0
        self.missing_required_field_lines = 0
        self.parsed_records = 0
        self.schema_version_counts: Counter[Any] = Counter()

    def as_dict(self) -> dict:
        return {
            "total_lines": self.total_lines,
            "blank_lines": self.blank_lines,
            "malformed_json_lines": self.malformed_json_lines,
            "non_object_lines": self.non_object_lines,
            "missing_required_field_lines": self.missing_required_field_lines,
            "parsed_records": self.parsed_records,
            "schema_version_counts": {
                str(version): count
                for version, count in sorted(
                    self.schema_version_counts.items(), key=lambda item: str(item[0])
                )
            },
            "unexpected_schema_version_present": any(
                version != TELEMETRY_SCHEMA_VERSION
                for version in self.schema_version_counts
            ),
        }


def iter_records(path: Path, stats: ParseStats) -> Iterator[dict]:
    """Yield each well-formed record; skip and count everything else."""

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            stats.total_lines += 1
            line = raw_line.strip()

            if not line:
                stats.blank_lines += 1
                continue

            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                stats.malformed_json_lines += 1
                continue

            if not isinstance(record, dict):
                stats.non_object_lines += 1
                continue

            if not all(field in record for field in REQUIRED_FIELDS):
                stats.missing_required_field_lines += 1
                continue

            stats.schema_version_counts[record.get("schema_version")] += 1
            stats.parsed_records += 1
            yield record


# ---------------------------------------------------------------------------
# S-3: candle_age_seconds distribution, per symbol, MEASURED records only.
# ---------------------------------------------------------------------------


def _is_real_number(value: Any) -> bool:
    """True for a finite int/float. Excludes bool (an int subclass) and
    NaN/Infinity -- json.loads accepts "NaN"/"Infinity"/"-Infinity" as
    literal tokens by default, so a malformed or adversarial log line can
    smuggle a non-finite float in; letting one through would corrupt
    sorted()/min/max ordering in the distribution statistics."""

    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _percentile(ordered: list[float], p: int) -> float:
    n = len(ordered)
    rank = max(1, min(n, math.ceil(p / 100 * n)))
    return ordered[rank - 1]


def _distribution(values: list[float]) -> dict:
    if not values:
        return {"count": 0}

    ordered = sorted(values)
    result = {
        "count": len(values),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": statistics.fmean(values),
        # statistics.median averages the two middle values on an even-sized
        # sample; p50 below is a single observed nearest-rank value instead.
        # They coincide on an odd-sized sample but can differ on an even
        # one -- both are individually correct, just different conventions.
        "median": statistics.median(values),
    }
    for p in PERCENTILES:
        result[f"p{p}"] = _percentile(ordered, p)
    return result


def aggregate_candle_age(records: list[dict]) -> dict:
    per_symbol_status: dict[str, Counter] = defaultdict(Counter)
    per_symbol_ages: dict[str, list[float]] = defaultdict(list)
    overall_status: Counter = Counter()
    measured_excluded_invalid_age = 0

    for record in records:
        symbol = record.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            symbol = "UNKNOWN_SYMBOL"

        # candle_age_status only needs to be *present* to pass the parse
        # layer's field check, not a particular type. A list/dict value
        # would raise TypeError as a dict/Counter key below, so it is
        # coerced to a labeled string the same way symbol is above.
        status = record.get("candle_age_status")
        if not isinstance(status, str):
            status = "UNKNOWN_STATUS_TYPE"

        per_symbol_status[symbol][status] += 1
        overall_status[status] += 1

        if status == MEASURED_STATUS:
            age = record.get("candle_age_seconds")
            if _is_real_number(age):
                per_symbol_ages[symbol].append(float(age))
            else:
                measured_excluded_invalid_age += 1

    per_symbol_report = {
        symbol: {
            "status_counts": dict(per_symbol_status[symbol]),
            "measured_distribution": _distribution(per_symbol_ages.get(symbol, [])),
        }
        for symbol in sorted(per_symbol_status)
    }

    return {
        "overall_status_counts": dict(overall_status),
        "overall_measured_distribution": _distribution(
            [age for ages in per_symbol_ages.values() for age in ages]
        ),
        # A MEASURED-status record whose candle_age_seconds is missing,
        # non-numeric or non-finite (NaN/Infinity): present in
        # overall_status_counts["MEASURED"] but absent from the
        # distribution above. Zero under the real writer (core.market_loop
        # never emits MEASURED without a valid age); non-zero here means a
        # malformed or hand-edited log line was excluded, not silently
        # merged in.
        "measured_status_excluded_invalid_age_count": measured_excluded_invalid_age,
        "per_symbol": per_symbol_report,
    }


# ---------------------------------------------------------------------------
# M-2: cycle_duration_seconds distribution, one value per (run, cycle).
# ---------------------------------------------------------------------------


def assign_run_index(records: list[dict]) -> list[tuple[int | None, dict]]:
    """Pair each record with a run index inferred from cycle-number resets.

    Records are assumed to be in file (append) order, matching the durable
    log's single-writer, append-only design (one Atlas process writes one
    file; core.logger.AtlasLogger refuses a duplicate handler attach). A
    record whose own ``cycle`` field is not a plain int gets ``None`` and is
    excluded from run/M-2 analysis, never guessed at.
    """

    run_index = 0
    previous_cycle: int | None = None
    annotated: list[tuple[int | None, dict]] = []

    for record in records:
        cycle = record.get("cycle")
        valid_cycle = isinstance(cycle, int) and not isinstance(cycle, bool)

        if not valid_cycle:
            annotated.append((None, record))
            continue

        if previous_cycle is not None and cycle < previous_cycle:
            run_index += 1

        annotated.append((run_index, record))
        previous_cycle = cycle

    return annotated


def cycle_duration_series(
    annotated_records: list[tuple[int | None, dict]],
) -> tuple[dict[tuple[int, int], float], int, int]:
    """One cycle_duration_seconds value per (run, cycle); report conflicts.

    The schema guarantees the same duration value for every symbol in a
    cycle. A conflict (two different values seen for the same (run, cycle))
    is a data-integrity anomaly worth surfacing, never silently resolved by
    picking one.

    Returns (values_by_run_and_cycle, conflict_count,
    excluded_invalid_duration_count). A record excluded because its own
    ``cycle`` field was invalid is not this function's concern -- that is
    counted by the caller from ``annotated_records`` directly, since
    ``assign_run_index`` already made that determination.
    """

    first_seen: dict[tuple[int, int], float] = {}
    conflicts = 0
    excluded_invalid_duration = 0

    for run_index, record in annotated_records:
        if run_index is None:
            continue

        cycle = record.get("cycle")
        duration = record.get("cycle_duration_seconds")
        if not _is_real_number(duration):
            excluded_invalid_duration += 1
            continue

        key = (run_index, cycle)
        if key in first_seen:
            if first_seen[key] != duration:
                conflicts += 1
            continue

        first_seen[key] = float(duration)

    return first_seen, conflicts, excluded_invalid_duration


def aggregate_cycle_duration(records: list[dict]) -> dict:
    annotated = assign_run_index(records)
    excluded_invalid_cycle = sum(1 for run_index, _ in annotated if run_index is None)
    per_run_cycle, conflicts, excluded_invalid_duration = cycle_duration_series(annotated)

    grouped: dict[int, list[float]] = defaultdict(list)
    for (run_index, _cycle), duration in per_run_cycle.items():
        grouped[run_index].append(duration)

    return {
        "run_count": len(grouped),
        "duplicate_value_conflicts_within_same_run_cycle": conflicts,
        # Records dropped before de-duplication: a non-int "cycle" field
        # (excluded by assign_run_index) or a missing/non-numeric/
        # non-finite "cycle_duration_seconds" (excluded by
        # cycle_duration_series). Zero under the real writer; non-zero
        # here means malformed input was excluded, not silently merged in.
        "excluded_records_invalid_cycle_field": excluded_invalid_cycle,
        "excluded_records_invalid_duration_field": excluded_invalid_duration,
        "per_run": {
            str(run_index): _distribution(values)
            for run_index, values in sorted(grouped.items())
        },
        "overall": _distribution(list(per_run_cycle.values())),
    }


# ---------------------------------------------------------------------------
# Report assembly and CLI.
# ---------------------------------------------------------------------------


def build_report(log_path: Path | None, parse_stats: ParseStats, records: list[dict]) -> dict:
    return {
        "log_path": str(log_path) if log_path is not None else None,
        "log_file_found": log_path is not None and log_path.exists(),
        "parse": parse_stats.as_dict(),
        "candle_age_s3": aggregate_candle_age(records),
        "cycle_duration_m2": aggregate_cycle_duration(records),
    }


def print_text_report(report: dict) -> None:
    parse = report["parse"]
    print(f"log_path: {report['log_path']}")
    print(f"log_file_found: {report['log_file_found']}")
    print(
        "parse: total_lines={total_lines} parsed_records={parsed_records} "
        "blank={blank_lines} malformed_json={malformed_json_lines} "
        "non_object={non_object_lines} missing_fields={missing_required_field_lines}".format(
            **parse
        )
    )
    if parse["unexpected_schema_version_present"]:
        print(f"  UNEXPECTED schema_version_counts: {parse['schema_version_counts']}")
    else:
        print(f"  schema_version_counts: {parse['schema_version_counts']}")

    print("\n--- S-3: candle_age_seconds (MEASURED records only) ---")
    s3 = report["candle_age_s3"]
    print(f"overall_status_counts: {s3['overall_status_counts']}")
    print(f"overall_measured_distribution: {s3['overall_measured_distribution']}")
    print(
        "measured_status_excluded_invalid_age_count: "
        f"{s3['measured_status_excluded_invalid_age_count']}"
    )
    for symbol, symbol_report in s3["per_symbol"].items():
        print(f"  {symbol}: status_counts={symbol_report['status_counts']}")
        print(f"    measured_distribution={symbol_report['measured_distribution']}")

    print("\n--- M-2: cycle_duration_seconds (one value per run/cycle) ---")
    m2 = report["cycle_duration_m2"]
    print(f"run_count: {m2['run_count']}")
    print(
        "duplicate_value_conflicts_within_same_run_cycle: "
        f"{m2['duplicate_value_conflicts_within_same_run_cycle']}"
    )
    print(f"excluded_records_invalid_cycle_field: {m2['excluded_records_invalid_cycle_field']}")
    print(
        "excluded_records_invalid_duration_field: "
        f"{m2['excluded_records_invalid_duration_field']}"
    )
    for run_index, dist in m2["per_run"].items():
        print(f"  run {run_index}: {dist}")
    print(f"overall: {m2['overall']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--log-directory",
        type=Path,
        default=None,
        help=(
            "Override ATLAS_LOG_DIRECTORY. Must already exist as a "
            "directory; never created by this tool."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.log_directory is not None:
        directory = args.log_directory
        if not directory.exists() or not directory.is_dir():
            message = f"--log-directory {str(directory)!r} does not exist or is not a directory"
            if args.json:
                print(json.dumps({"error": "LogDirectoryNotFound", "detail": message}))
            else:
                print(f"REFUSED: LogDirectoryNotFound: {message}", file=sys.stderr)
            return 1
    else:
        try:
            directory = resolve_log_directory()
        except ConfiguredDirectoryError as error:
            if args.json:
                print(json.dumps({"error": "ConfiguredDirectoryError", "detail": str(error)}))
            else:
                print(f"REFUSED: ConfiguredDirectoryError: {error}", file=sys.stderr)
            return 1

    log_path = directory / TELEMETRY_LOG_FILE if directory is not None else None

    parse_stats = ParseStats()
    records: list[dict] = []
    if log_path is not None and log_path.exists():
        records = list(iter_records(log_path, parse_stats))

    report = build_report(log_path, parse_stats, records)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_text_report(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
