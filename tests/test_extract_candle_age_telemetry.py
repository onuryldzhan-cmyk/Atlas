"""Registry v4.72, GRANT-S3-M2-EXTRACTION-TOOL: tools/extract_candle_age_telemetry.py.

Every test here is offline and uses tmp_path only. No test constructs a
runtime against a real state root or a real log root (TEST-ISO-001;
conftest.py unsets ATLAS_LOG_DIRECTORY for the pytest session, so any test
that needs it set does so explicitly via monkeypatch, scoped to that test).
"""

from __future__ import annotations

import json
from pathlib import Path

import tools.extract_candle_age_telemetry as cli_module
from core.market_loop import TELEMETRY_SCHEMA_VERSION


def write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def record(
    *,
    symbol: str = "BTCUSDT",
    cycle: int = 1,
    cycle_duration_seconds: float = 0.05,
    candle_age_seconds: float | None = 30.0,
    candle_age_status: str = "MEASURED",
    schema_version: int = TELEMETRY_SCHEMA_VERSION,
    **extra,
) -> str:
    payload = {
        "schema_version": schema_version,
        "event": "market_loop_cycle",
        "timestamp": "2026-09-24T12:00:00+00:00",
        "cycle": cycle,
        "symbol": symbol,
        "cycle_duration_seconds": cycle_duration_seconds,
        "candle_age_seconds": candle_age_seconds,
        "candle_age_status": candle_age_status,
        "candle_close_time": "2026-09-24T11:59:30+00:00",
        "processing_cutoff": "2026-09-24T12:00:00+00:00",
    }
    payload.update(extra)
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Parsing: fail-closed on malformed input.
# ---------------------------------------------------------------------------


def test_iter_records_skips_blank_lines(tmp_path):
    path = tmp_path / "log.jsonl"
    write_jsonl(path, [record(), "", "   ", record(cycle=2)])
    stats = cli_module.ParseStats()

    parsed = list(cli_module.iter_records(path, stats))

    assert len(parsed) == 2
    assert stats.blank_lines == 2
    assert stats.total_lines == 4
    assert stats.parsed_records == 2


def test_iter_records_counts_malformed_json_without_raising(tmp_path):
    path = tmp_path / "log.jsonl"
    write_jsonl(path, [record(), "{not valid json", record(cycle=2)])
    stats = cli_module.ParseStats()

    parsed = list(cli_module.iter_records(path, stats))

    assert len(parsed) == 2
    assert stats.malformed_json_lines == 1


def test_iter_records_counts_non_object_json(tmp_path):
    path = tmp_path / "log.jsonl"
    write_jsonl(path, [record(), "[1, 2, 3]", "42", '"a string"'])
    stats = cli_module.ParseStats()

    parsed = list(cli_module.iter_records(path, stats))

    assert len(parsed) == 1
    assert stats.non_object_lines == 3


def test_iter_records_counts_missing_required_fields(tmp_path):
    path = tmp_path / "log.jsonl"
    write_jsonl(path, [record(), json.dumps({"symbol": "BTCUSDT"})])
    stats = cli_module.ParseStats()

    parsed = list(cli_module.iter_records(path, stats))

    assert len(parsed) == 1
    assert stats.missing_required_field_lines == 1


def test_iter_records_a_reason_code_row_is_not_treated_as_numeric(tmp_path):
    """A row with a reason code instead of a numeric age must parse fine and
    never contribute to the numeric age distribution (checked at the
    aggregation layer, not here) -- it is not a malformed row."""

    path = tmp_path / "log.jsonl"
    write_jsonl(
        path,
        [record(candle_age_seconds=None, candle_age_status="UNAVAILABLE_CLOSE_TIME_MISSING")],
    )
    stats = cli_module.ParseStats()

    parsed = list(cli_module.iter_records(path, stats))

    assert len(parsed) == 1
    assert stats.missing_required_field_lines == 0
    assert parsed[0]["candle_age_seconds"] is None


def test_mixed_schema_version_values_are_counted_and_flagged(tmp_path):
    path = tmp_path / "log.jsonl"
    write_jsonl(path, [record(schema_version=1), record(schema_version=2, cycle=2)])
    stats = cli_module.ParseStats()

    list(cli_module.iter_records(path, stats))
    payload = stats.as_dict()

    assert payload["schema_version_counts"] == {"1": 1, "2": 1}
    assert payload["unexpected_schema_version_present"] is True


def test_single_schema_version_is_not_flagged(tmp_path):
    path = tmp_path / "log.jsonl"
    write_jsonl(path, [record(), record(cycle=2)])
    stats = cli_module.ParseStats()

    list(cli_module.iter_records(path, stats))
    payload = stats.as_dict()

    assert payload["unexpected_schema_version_present"] is False


# ---------------------------------------------------------------------------
# S-3 aggregation.
# ---------------------------------------------------------------------------


def test_aggregate_candle_age_measured_distribution():
    records = [
        record(candle_age_seconds=10.0, cycle=1),
        record(candle_age_seconds=20.0, cycle=2),
        record(candle_age_seconds=30.0, cycle=3),
        record(
            candle_age_seconds=None,
            candle_age_status="UNAVAILABLE_NO_CLOSED_CANDLE",
            cycle=4,
        ),
    ]
    records = [json.loads(r) for r in records]

    report = cli_module.aggregate_candle_age(records)

    dist = report["per_symbol"]["BTCUSDT"]["measured_distribution"]
    assert dist["count"] == 3
    assert dist["min"] == 10.0
    assert dist["max"] == 30.0
    assert dist["mean"] == 20.0
    assert dist["median"] == 20.0
    assert report["overall_status_counts"]["MEASURED"] == 3
    assert report["overall_status_counts"]["UNAVAILABLE_NO_CLOSED_CANDLE"] == 1


def test_aggregate_candle_age_status_only_record_excluded_from_distribution():
    records = [
        json.loads(record(candle_age_seconds=None, candle_age_status="NOT_MEASURED_THIS_CYCLE"))
    ]

    report = cli_module.aggregate_candle_age(records)

    dist = report["per_symbol"]["BTCUSDT"]["measured_distribution"]
    assert dist == {"count": 0}
    assert report["overall_status_counts"] == {"NOT_MEASURED_THIS_CYCLE": 1}


def test_aggregate_candle_age_is_per_symbol():
    records = [
        json.loads(record(symbol="BTCUSDT", candle_age_seconds=10.0, cycle=1)),
        json.loads(record(symbol="ETHUSDT", candle_age_seconds=50.0, cycle=1)),
    ]

    report = cli_module.aggregate_candle_age(records)

    assert set(report["per_symbol"]) == {"BTCUSDT", "ETHUSDT"}
    assert report["per_symbol"]["BTCUSDT"]["measured_distribution"]["max"] == 10.0
    assert report["per_symbol"]["ETHUSDT"]["measured_distribution"]["max"] == 50.0
    assert report["overall_measured_distribution"]["count"] == 2


def test_distribution_single_value_percentiles_equal_the_value():
    dist = cli_module._distribution([42.0])

    assert dist["count"] == 1
    for p in cli_module.PERCENTILES:
        assert dist[f"p{p}"] == 42.0


def test_distribution_empty_is_zero_count_only():
    assert cli_module._distribution([]) == {"count": 0}


def test_is_real_number_rejects_bool():
    assert cli_module._is_real_number(True) is False
    assert cli_module._is_real_number(False) is False


def test_is_real_number_rejects_non_finite_floats():
    """json.loads accepts NaN/Infinity/-Infinity by default. A malformed or
    adversarial line carrying one must never reach the distribution -- it
    would corrupt sorted()/min/max ordering (NaN compares False to
    everything)."""

    assert cli_module._is_real_number(float("nan")) is False
    assert cli_module._is_real_number(float("inf")) is False
    assert cli_module._is_real_number(float("-inf")) is False
    assert cli_module._is_real_number(12.5) is True
    assert cli_module._is_real_number(12) is True


def test_aggregate_candle_age_excludes_nan_and_infinity_from_distribution():
    raw_lines = [
        record(candle_age_seconds=10.0, cycle=1),
        '{"schema_version": 1, "symbol": "BTCUSDT", "cycle": 2, '
        '"cycle_duration_seconds": 0.05, "candle_age_seconds": NaN, '
        '"candle_age_status": "MEASURED"}',
        '{"schema_version": 1, "symbol": "BTCUSDT", "cycle": 3, '
        '"cycle_duration_seconds": 0.05, "candle_age_seconds": Infinity, '
        '"candle_age_status": "MEASURED"}',
    ]
    records = [json.loads(line) for line in raw_lines]

    report = cli_module.aggregate_candle_age(records)

    dist = report["per_symbol"]["BTCUSDT"]["measured_distribution"]
    assert dist["count"] == 1
    assert dist["min"] == 10.0
    assert dist["max"] == 10.0


def test_cycle_duration_series_excludes_non_finite_duration(tmp_path):
    raw_lines = [
        record(cycle=1, cycle_duration_seconds=0.05),
        '{"schema_version": 1, "symbol": "BTCUSDT", "cycle": 2, '
        '"cycle_duration_seconds": NaN, "candle_age_seconds": null, '
        '"candle_age_status": "NOT_MEASURED_THIS_CYCLE"}',
    ]
    records = [json.loads(line) for line in raw_lines]
    annotated = cli_module.assign_run_index(records)

    series, conflicts, excluded_invalid_duration = cli_module.cycle_duration_series(annotated)

    assert series == {(0, 1): 0.05}
    assert conflicts == 0
    assert excluded_invalid_duration == 1


def test_percentile_ten_values_nearest_rank():
    ordered = [float(i) for i in range(1, 11)]  # 1..10

    assert cli_module._percentile(ordered, 50) == 5.0
    assert cli_module._percentile(ordered, 90) == 9.0
    assert cli_module._percentile(ordered, 99) == 10.0


# ---------------------------------------------------------------------------
# M-2 aggregation: run-boundary detection and de-duplication.
# ---------------------------------------------------------------------------


def test_assign_run_index_stays_in_one_run_when_cycle_is_non_decreasing():
    records = [
        json.loads(record(cycle=1, symbol="BTCUSDT")),
        json.loads(record(cycle=1, symbol="ETHUSDT")),
        json.loads(record(cycle=2, symbol="BTCUSDT")),
        json.loads(record(cycle=2, symbol="ETHUSDT")),
    ]

    annotated = cli_module.assign_run_index(records)

    assert [run for run, _ in annotated] == [0, 0, 0, 0]


def test_assign_run_index_detects_a_reset_as_a_new_run():
    records = [
        json.loads(record(cycle=1)),
        json.loads(record(cycle=2)),
        json.loads(record(cycle=3)),
        json.loads(record(cycle=1)),  # process restarted
        json.loads(record(cycle=2)),
    ]

    annotated = cli_module.assign_run_index(records)

    assert [run for run, _ in annotated] == [0, 0, 0, 1, 1]


def test_assign_run_index_excludes_non_int_cycle_without_crashing():
    records = [
        json.loads(record(cycle=1)),
        {**json.loads(record(cycle=1)), "cycle": "not-a-number"},
        json.loads(record(cycle=2)),
    ]

    annotated = cli_module.assign_run_index(records)

    assert annotated[1][0] is None
    assert annotated[0][0] == 0
    assert annotated[2][0] == 0


def test_cycle_duration_series_deduplicates_per_run_and_cycle():
    records = [
        json.loads(record(cycle=1, symbol="BTCUSDT", cycle_duration_seconds=0.10)),
        json.loads(record(cycle=1, symbol="ETHUSDT", cycle_duration_seconds=0.10)),
        json.loads(record(cycle=2, symbol="BTCUSDT", cycle_duration_seconds=0.20)),
        json.loads(record(cycle=2, symbol="ETHUSDT", cycle_duration_seconds=0.20)),
    ]
    annotated = cli_module.assign_run_index(records)

    series, conflicts, excluded_invalid_duration = cli_module.cycle_duration_series(annotated)

    assert series == {(0, 1): 0.10, (0, 2): 0.20}
    assert conflicts == 0
    assert excluded_invalid_duration == 0


def test_cycle_duration_series_reports_conflicts_without_crashing():
    records = [
        json.loads(record(cycle=1, symbol="BTCUSDT", cycle_duration_seconds=0.10)),
        json.loads(record(cycle=1, symbol="ETHUSDT", cycle_duration_seconds=0.15)),
    ]
    annotated = cli_module.assign_run_index(records)

    series, conflicts, excluded_invalid_duration = cli_module.cycle_duration_series(annotated)

    assert conflicts == 1
    assert excluded_invalid_duration == 0
    assert series[(0, 1)] == 0.10  # first-seen value wins; both are counted, not averaged


def test_aggregate_cycle_duration_splits_runs_on_reset():
    records = [
        json.loads(record(cycle=1, cycle_duration_seconds=0.10)),
        json.loads(record(cycle=2, cycle_duration_seconds=0.30)),
        json.loads(record(cycle=1, cycle_duration_seconds=0.50)),  # new run
    ]

    report = cli_module.aggregate_cycle_duration(records)

    assert report["run_count"] == 2
    assert report["per_run"]["0"]["count"] == 2
    assert report["per_run"]["1"]["count"] == 1
    assert report["overall"]["count"] == 3


def test_aggregate_cycle_duration_empty_input():
    report = cli_module.aggregate_cycle_duration([])

    assert report["run_count"] == 0
    assert report["overall"] == {"count": 0}
    assert report["duplicate_value_conflicts_within_same_run_cycle"] == 0
    assert report["excluded_records_invalid_cycle_field"] == 0
    assert report["excluded_records_invalid_duration_field"] == 0


def test_aggregate_cycle_duration_reports_exclusion_counters():
    records = [
        json.loads(record(cycle=1, cycle_duration_seconds=0.10)),
        {**json.loads(record(cycle=2)), "cycle": "not-a-number"},
        {
            **json.loads(record(cycle=3)),
            "cycle_duration_seconds": None,
        },
    ]

    report = cli_module.aggregate_cycle_duration(records)

    assert report["excluded_records_invalid_cycle_field"] == 1
    assert report["excluded_records_invalid_duration_field"] == 1
    assert report["run_count"] == 1  # only the cycle=1 record produced a value


# ---------------------------------------------------------------------------
# candle_age_status must never crash aggregation regardless of its type.
# ---------------------------------------------------------------------------


def test_aggregate_candle_age_non_hashable_status_does_not_crash():
    """A malformed/adversarial line can carry a list/dict candle_age_status.
    It must be coerced to a labeled string, never used as a raw dict/Counter
    key (which would raise TypeError: unhashable type)."""

    records = [
        {**json.loads(record(cycle=1)), "candle_age_status": ["not", "a", "string"]},
        {**json.loads(record(cycle=2)), "candle_age_status": {"nested": "dict"}},
    ]

    report = cli_module.aggregate_candle_age(records)

    assert report["overall_status_counts"]["UNKNOWN_STATUS_TYPE"] == 2
    assert report["per_symbol"]["BTCUSDT"]["status_counts"]["UNKNOWN_STATUS_TYPE"] == 2


def test_aggregate_candle_age_reports_measured_excluded_invalid_age_count():
    records = [
        json.loads(record(cycle=1, candle_age_seconds=10.0)),
        {**json.loads(record(cycle=2)), "candle_age_seconds": "not-a-number"},
    ]

    report = cli_module.aggregate_candle_age(records)

    assert report["measured_status_excluded_invalid_age_count"] == 1
    assert report["overall_measured_distribution"]["count"] == 1


# ---------------------------------------------------------------------------
# CLI / main(): missing directory, missing file, empty file, JSON output.
# ---------------------------------------------------------------------------


def test_main_reports_zero_records_when_atlas_log_directory_is_unset(monkeypatch, capsys):
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)

    exit_code = cli_module.main(["--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["log_path"] is None
    assert payload["log_file_found"] is False
    assert payload["parse"]["parsed_records"] == 0


def test_main_reports_zero_records_when_file_does_not_exist_yet(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ATLAS_LOG_DIRECTORY", str(tmp_path))

    exit_code = cli_module.main(["--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["log_file_found"] is False
    assert payload["parse"]["parsed_records"] == 0


def test_main_reports_zero_records_for_an_empty_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ATLAS_LOG_DIRECTORY", str(tmp_path))
    (tmp_path / cli_module.TELEMETRY_LOG_FILE).write_text("", encoding="utf-8")

    exit_code = cli_module.main(["--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["log_file_found"] is True
    assert payload["parse"]["parsed_records"] == 0


def test_main_configured_directory_error_return_value(monkeypatch, capsys):
    monkeypatch.setenv("ATLAS_LOG_DIRECTORY", "relative/not/absolute")

    exit_code = cli_module.main(["--json"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "ConfiguredDirectoryError"


def test_main_explicit_log_directory_that_does_not_exist_returns_one(tmp_path, capsys):
    missing = tmp_path / "does_not_exist"

    exit_code = cli_module.main(["--log-directory", str(missing), "--json"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "LogDirectoryNotFound"


def test_main_explicit_log_directory_overrides_env(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)
    (tmp_path / cli_module.TELEMETRY_LOG_FILE).write_text(record() + "\n", encoding="utf-8")

    exit_code = cli_module.main(["--log-directory", str(tmp_path), "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["parse"]["parsed_records"] == 1


def test_main_text_output_does_not_raise(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ATLAS_LOG_DIRECTORY", str(tmp_path))
    write_jsonl(
        tmp_path / cli_module.TELEMETRY_LOG_FILE,
        [record(cycle=1, candle_age_seconds=12.5), record(cycle=2, candle_age_seconds=15.0)],
    )

    exit_code = cli_module.main([])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "S-3" in out
    assert "M-2" in out


def test_main_end_to_end_with_realistic_mixed_data(monkeypatch, tmp_path, capsys):
    """Two symbols, one restart, one UNAVAILABLE row, one malformed line."""

    monkeypatch.setenv("ATLAS_LOG_DIRECTORY", str(tmp_path))
    lines = [
        record(symbol="BTCUSDT", cycle=1, candle_age_seconds=10.0, cycle_duration_seconds=0.05),
        record(symbol="ETHUSDT", cycle=1, candle_age_seconds=40.0, cycle_duration_seconds=0.05),
        record(symbol="BTCUSDT", cycle=2, candle_age_seconds=70.0, cycle_duration_seconds=0.06),
        record(
            symbol="ETHUSDT",
            cycle=2,
            candle_age_seconds=None,
            candle_age_status="UNAVAILABLE_NO_CLOSED_CANDLE",
            cycle_duration_seconds=0.06,
        ),
        "not json at all",
        record(symbol="BTCUSDT", cycle=1, candle_age_seconds=5.0, cycle_duration_seconds=0.04),
    ]
    write_jsonl(tmp_path / cli_module.TELEMETRY_LOG_FILE, lines)

    exit_code = cli_module.main(["--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["parse"]["malformed_json_lines"] == 1
    assert payload["parse"]["parsed_records"] == 5
    assert payload["candle_age_s3"]["per_symbol"]["BTCUSDT"]["measured_distribution"]["count"] == 3
    assert payload["candle_age_s3"]["per_symbol"]["ETHUSDT"]["status_counts"][
        "UNAVAILABLE_NO_CLOSED_CANDLE"
    ] == 1
    assert payload["cycle_duration_m2"]["run_count"] == 2
