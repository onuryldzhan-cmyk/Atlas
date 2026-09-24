"""Registry v4.71: candle age and durable MarketLoop telemetry.

GRANT-CANDLE-AGE-COMPUTATION
    MarketLoop measures, per symbol per cycle, the age of the newest closed
    candle against the cycle's own processing cutoff. It fails closed: a
    missing, malformed, open_time-fallback, or future close_time yields no
    age at all, never a substitute value. It is a different measurement from
    the fetch-liveness staleness report and must never leak into it, into
    status()/health(), or into the pipeline's control flow.

GRANT-DURABLE-OPERATIONAL-LOGGING
    ATLAS_LOG_DIRECTORY goes through the same fail-closed validator as the
    state roots and has no default (unset = no file). AtlasLogger attaches
    one file to one non-propagating telemetry logger; one JSON-lines record
    per worker cycle per symbol is written off the worker thread.

Every test here is offline and uses tmp_path only. No test constructs a
runtime against a real state root or a real log root.
"""

from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import core.market_loop as market_loop_module
from core.application import (
    LOG_DIRECTORY_ENV,
    STATE_DIRECTORY_ENV,
    AtlasApplication,
    ConfiguredDirectoryError,
    resolve_log_directory,
    resolve_state_directory,
)
from core.candle_processor import CandleProcessor
from core.logger import (
    TELEMETRY_LOG_FILE,
    AtlasLogger,
    TelemetryHandlerConflictError,
)
from core.market_loop import (
    TELEMETRY_LOGGER_NAME,
    MarketLoop,
)

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

MINUTE_MS = 60_000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def to_ms(value: datetime) -> int:
    return (value - EPOCH) // timedelta(milliseconds=1)


def build_candle_rows(
    count: int,
    *,
    start_ms: int,
    include_close_time: bool = True,
) -> list[list[Any]]:
    """Binance-compatible kline rows, ascending, one minute apart."""

    rows: list[list[Any]] = []

    for index in range(count):
        open_ms = start_ms + index * MINUTE_MS
        base = 60_000.0 + index * 4.0
        volume = 10.0 + index * 0.05
        row: list[Any] = [
            open_ms,
            f"{base:.2f}",
            f"{base + 35.0:.2f}",
            f"{base - 25.0:.2f}",
            f"{base + 12.0:.2f}",
            f"{volume:.5f}",
        ]

        if include_close_time:
            row.extend([
                open_ms + MINUTE_MS - 1,
                "0.0",
                0,
                f"{volume * 0.4:.5f}",
                f"{(base + 12.0) * volume * 0.4:.8f}",
                "0",
            ])

        rows.append(row)

    return rows


def rows_closing_before(
    cutoff: datetime,
    *,
    age: timedelta,
    count: int = 60,
) -> list[list[Any]]:
    """Rows whose newest candle closes exactly ``age`` before ``cutoff``."""

    newest_close_ms = to_ms(cutoff) - (age // timedelta(milliseconds=1))
    newest_open_ms = newest_close_ms - (MINUTE_MS - 1)

    return build_candle_rows(
        count,
        start_ms=newest_open_ms - (count - 1) * MINUTE_MS,
    )


class SymbolFeed:
    """MarketFeed stand-in: per-symbol sequence of windows, one per call."""

    def __init__(self, windows: dict[str, list[Any]]) -> None:
        self._windows = {key: list(value) for key, value in windows.items()}
        self.calls: dict[str, int] = {}

    def candles(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int = 200,
    ) -> Any:
        windows = self._windows.get(symbol, [[]])
        call = self.calls.get(symbol, 0)
        self.calls[symbol] = call + 1
        window = windows[min(call, len(windows) - 1)]

        return window(symbol) if callable(window) else window


class FakeBrain:
    def analyze_and_decide(
        self,
        symbol: str,
        market_data: Any,
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "action": "HOLD",
            "confidence": 75.0,
            "risk": "LOW",
            "strategy": "TELEMETRY_TEST",
            "reason": "Offline v4.71 telemetry fixture.",
        }


class CycleLimiter:
    """Replaces stop_event so worker() runs N cycles synchronously."""

    def __init__(self, loop: MarketLoop, cycles: int) -> None:
        self.loop = loop
        self.remaining = cycles
        self.waits: list[float] = []

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout if timeout is not None else -1.0)
        self.remaining -= 1

        if self.remaining <= 0:
            self.loop.running = False

        return False

    def set(self) -> None:
        self.loop.running = False

    def clear(self) -> None:
        pass

    def is_set(self) -> bool:
        return not self.loop.running


def build_loop(feed: Any, symbols: tuple[str, ...]) -> MarketLoop:
    return MarketLoop(
        brain=FakeBrain(),
        market_feed=feed,
        symbols=list(symbols),
        interval=1.0,
    )


def run_worker_cycles(loop: MarketLoop, cycles: int) -> None:
    loop.stop_event = CycleLimiter(loop, cycles)  # type: ignore[assignment]
    loop.running = True
    loop.worker()


class RecordCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def telemetry_capture():
    target = logging.getLogger(TELEMETRY_LOGGER_NAME)
    capture = RecordCapture()
    target.addHandler(capture)

    try:
        yield capture
    finally:
        target.removeHandler(capture)


def durable_handlers(name: str) -> list[logging.Handler]:
    """Handlers AtlasLogger attached, ignoring pytest's own capture
    handlers (pytest 9 attaches those to every non-propagating logger)."""

    return [
        handler
        for handler in logging.getLogger(name).handlers
        if getattr(handler, "_atlas_durable_telemetry_handler", False)
    ]


def parsed(capture: RecordCapture) -> list[dict[str, Any]]:
    return [json.loads(message) for message in capture.messages]


# ---------------------------------------------------------------------------
# Candle age: the pure computation
# ---------------------------------------------------------------------------

CUTOFF = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
CUTOFF_MS = to_ms(CUTOFF)


def candle(open_ms: Any, close_ms: Any) -> dict[str, Any]:
    return {"open_time": open_ms, "close_time": close_ms}


def test_candle_age_normal_case_is_cutoff_minus_close_time() -> None:
    close_ms = CUTOFF_MS - 12_345

    age, status = MarketLoop._candle_age(
        candle(close_ms - MINUTE_MS + 1, close_ms),
        CUTOFF,
    )

    assert status == MarketLoop.CANDLE_AGE_MEASURED
    assert age == pytest.approx(12.345)


def test_candle_age_accepts_an_epoch_millisecond_cutoff() -> None:
    close_ms = CUTOFF_MS - 2_000

    age, status = MarketLoop._candle_age(
        candle(close_ms - MINUTE_MS + 1, close_ms),
        CUTOFF_MS,
    )

    assert (age, status) == (2.0, MarketLoop.CANDLE_AGE_MEASURED)


def test_candle_age_boundary_close_time_equal_to_cutoff_is_zero() -> None:
    # is_closed_at is inclusive: close_time == cutoff is CLOSED, age 0.
    age, status = MarketLoop._candle_age(
        candle(CUTOFF_MS - MINUTE_MS + 1, CUTOFF_MS),
        CUTOFF,
    )

    assert status == MarketLoop.CANDLE_AGE_MEASURED
    assert age == 0.0


def test_candle_age_sub_millisecond_cutoff_floors_like_closure() -> None:
    cutoff = CUTOFF + timedelta(microseconds=999)

    age, status = MarketLoop._candle_age(
        candle(CUTOFF_MS - MINUTE_MS + 1, CUTOFF_MS),
        cutoff,
    )

    assert (age, status) == (0.0, MarketLoop.CANDLE_AGE_MEASURED)


def test_candle_age_missing_close_time_yields_no_age() -> None:
    age, status = MarketLoop._candle_age(
        candle(CUTOFF_MS - MINUTE_MS, None),
        CUTOFF,
    )

    assert age is None
    assert status == MarketLoop.CANDLE_AGE_CLOSE_TIME_MISSING


@pytest.mark.parametrize(
    "open_ms, close_ms",
    [
        (CUTOFF_MS - MINUTE_MS, str(CUTOFF_MS - 1_000)),
        (CUTOFF_MS - MINUTE_MS, float(CUTOFF_MS - 1_000)),
        (CUTOFF_MS - MINUTE_MS, True),
        (None, CUTOFF_MS - 1_000),
        ("x", CUTOFF_MS - 1_000),
        (False, CUTOFF_MS - 1_000),
    ],
)
def test_candle_age_malformed_times_yield_no_age(
    open_ms: Any,
    close_ms: Any,
) -> None:
    age, status = MarketLoop._candle_age(candle(open_ms, close_ms), CUTOFF)

    assert age is None
    assert status == MarketLoop.CANDLE_AGE_CLOSE_TIME_MALFORMED


def test_candle_age_refuses_the_processors_open_time_fallback() -> None:
    """Discriminating case: a naive implementation would report an age.

    A kline row without index 6 has no close_time. CandleProcessor then
    substitutes open_time, the candle is classified closed, and
    ``cutoff - close_time`` is a plausible positive number. That number is
    the age of the candle's OPEN, not its close - a fabricated value.
    """

    open_ms = CUTOFF_MS - 5 * MINUTE_MS
    rows = build_candle_rows(1, start_ms=open_ms, include_close_time=False)

    normalized = CandleProcessor().normalize(rows, processing_cutoff=CUTOFF)
    newest = CandleProcessor.latest_closed_candle(normalized)

    assert newest is not None
    assert newest["close_time"] == newest["open_time"]
    naive_age = (CUTOFF_MS - newest["close_time"]) / 1000
    assert naive_age == 300.0  # what a naive implementation would log

    age, status = MarketLoop._candle_age(newest, CUTOFF)

    assert age is None
    assert status == MarketLoop.CANDLE_AGE_CLOSE_TIME_NOT_PROVIDER_SUPPLIED


def test_candle_age_close_time_after_cutoff_is_flagged_not_clamped() -> None:
    """Discriminating case: a clamping implementation would report 0.0."""

    age, status = MarketLoop._candle_age(
        candle(CUTOFF_MS - MINUTE_MS, CUTOFF_MS + 1),
        CUTOFF,
    )

    assert age is None
    assert status == MarketLoop.CANDLE_AGE_CLOSE_TIME_AFTER_CUTOFF


def test_candle_age_without_a_closed_candle() -> None:
    assert MarketLoop._candle_age(None, CUTOFF) == (
        None,
        MarketLoop.CANDLE_AGE_NO_CLOSED_CANDLE,
    )


@pytest.mark.parametrize(
    "cutoff",
    [datetime(2026, 9, 23, 12, 0, 0), "2026-09-23T12:00:00Z", 1.5e12, True],
)
def test_candle_age_malformed_cutoff_yields_no_age(cutoff: Any) -> None:
    close_ms = CUTOFF_MS - 1_000

    age, status = MarketLoop._candle_age(
        candle(close_ms - MINUTE_MS + 1, close_ms),
        cutoff,
    )

    assert age is None
    assert status == MarketLoop.CANDLE_AGE_CUTOFF_MALFORMED


# ---------------------------------------------------------------------------
# Candle age: inside process_symbol
# ---------------------------------------------------------------------------


def test_process_symbol_records_real_candle_age() -> None:
    loop = build_loop(
        SymbolFeed({"BTCUSDT": [rows_closing_before(CUTOFF, age=timedelta(seconds=7))]}),
        ("BTCUSDT",),
    )

    loop.process_symbol("BTCUSDT", processing_cutoff=CUTOFF)

    entry = loop.last_candle_age["BTCUSDT"]
    assert entry["candle_age_status"] == MarketLoop.CANDLE_AGE_MEASURED
    assert entry["candle_age_seconds"] == 7.0
    assert entry["processing_cutoff"] == CUTOFF.isoformat()
    assert entry["candle_close_time"] == (
        CUTOFF - timedelta(seconds=7)
    ).isoformat()


def test_candle_age_is_recorded_on_duplicate_and_short_history_skips() -> None:
    window = rows_closing_before(CUTOFF, age=timedelta(seconds=3))
    loop = build_loop(
        SymbolFeed({"BTCUSDT": [window], "ETHUSDT": [window[-10:]]}),
        ("BTCUSDT", "ETHUSDT"),
    )

    loop.process_symbol("BTCUSDT", processing_cutoff=CUTOFF)
    later = CUTOFF + timedelta(seconds=20)
    duplicate = loop.process_symbol("BTCUSDT", processing_cutoff=later)
    short = loop.process_symbol("ETHUSDT", processing_cutoff=CUTOFF)

    assert duplicate["reason"] == "DUPLICATE_CLOSED_CANDLE"
    assert loop.last_candle_age["BTCUSDT"]["candle_age_seconds"] == 23.0
    assert short["reason"] == "INSUFFICIENT_CLOSED_CANDLES"
    assert loop.last_candle_age["ETHUSDT"]["candle_age_seconds"] == 3.0


def test_candle_age_failure_never_changes_the_pipeline_or_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discriminating case: an unguarded helper would raise into
    process_symbol's except branch, record an error and flip health."""

    window = rows_closing_before(CUTOFF, age=timedelta(seconds=4))
    control = build_loop(SymbolFeed({"BTCUSDT": [window]}), ("BTCUSDT",))
    broken = build_loop(SymbolFeed({"BTCUSDT": [window]}), ("BTCUSDT",))

    def explode(candles: Any) -> Any:
        raise RuntimeError("synthetic candle-age failure")

    monkeypatch.setattr(broken.processor, "latest_closed_candle", explode)

    control_result = control.process_symbol("BTCUSDT", processing_cutoff=CUTOFF)
    broken_result = broken.process_symbol("BTCUSDT", processing_cutoff=CUTOFF)

    for result in (control_result, broken_result):
        result.pop("timestamp", None)

    assert broken_result == control_result
    assert broken.errors == []
    assert broken.metrics == control.metrics
    assert broken.health()["healthy"] == control.health()["healthy"]
    assert broken.last_candle_age["BTCUSDT"] == {
        "candle_age_seconds": None,
        "candle_age_status": MarketLoop.CANDLE_AGE_COMPUTATION_ERROR,
        "candle_close_time": None,
        "processing_cutoff": CUTOFF.isoformat(),
        "cycle_sequence": 0,
    }


def _all_keys(value: Any) -> set[str]:
    keys: set[str] = set()

    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys |= _all_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys |= _all_keys(item)

    return keys


def test_candle_age_never_leaks_into_status_health_or_staleness() -> None:
    """A lagging-but-advancing feed: candle age is large, but the existing
    fetch-liveness report must be exactly what it was before v4.71 -
    fresh, because the fetch succeeded."""

    window = rows_closing_before(CUTOFF, age=timedelta(hours=2))
    loop = build_loop(SymbolFeed({"BTCUSDT": [window]}), ("BTCUSDT",))

    loop.process_symbol("BTCUSDT", processing_cutoff=CUTOFF)

    assert loop.last_candle_age["BTCUSDT"]["candle_age_seconds"] == 7200.0

    health = loop.health()
    status = loop.status()

    assert health["market_data_stale"] is False
    assert status["market_data_staleness"]["BTCUSDT"]["stale"] is False

    for surface in (health, status):
        assert not any("candle_age" in key for key in _all_keys(surface))


# ---------------------------------------------------------------------------
# Telemetry emission from worker()
# ---------------------------------------------------------------------------


def test_worker_emits_one_record_per_symbol_per_cycle(
    telemetry_capture: RecordCapture,
) -> None:
    now = datetime.now(UTC)
    feed = SymbolFeed({
        "BTCUSDT": [rows_closing_before(now, age=timedelta(seconds=30))],
        "ETHUSDT": [[]],
    })
    loop = build_loop(feed, ("BTCUSDT", "ETHUSDT"))

    run_worker_cycles(loop, 2)

    records = parsed(telemetry_capture)
    assert [(r["cycle"], r["symbol"]) for r in records] == [
        (1, "BTCUSDT"), (1, "ETHUSDT"), (2, "BTCUSDT"), (2, "ETHUSDT"),
    ]

    for record in records:
        assert record["schema_version"] == 1
        assert record["event"] == "market_loop_cycle"
        assert isinstance(record["cycle_duration_seconds"], float)
        assert record["cycle_duration_seconds"] >= 0.0
        datetime.fromisoformat(record["timestamp"])

    btc = [r for r in records if r["symbol"] == "BTCUSDT"]
    eth = [r for r in records if r["symbol"] == "ETHUSDT"]

    for record in btc:
        assert record["candle_age_status"] == "MEASURED"
        # `now` is taken before the worker reads its cutoff, so the age
        # is 30 s plus the few ms in between - never less than 30 s.
        assert 30.0 <= record["candle_age_seconds"] < 32.0

    for record in eth:
        assert record["candle_age_seconds"] is None
        assert record["candle_age_status"] == "NOT_MEASURED_THIS_CYCLE"


def test_worker_never_reports_a_previous_cycles_age_as_current(
    telemetry_capture: RecordCapture,
) -> None:
    """Discriminating case: a naive emitter reading last_candle_age would
    repeat cycle 1's age in cycle 2, when no data arrived at all."""

    now = datetime.now(UTC)
    feed = SymbolFeed({
        "BTCUSDT": [rows_closing_before(now, age=timedelta(seconds=10)), []],
    })
    loop = build_loop(feed, ("BTCUSDT",))

    run_worker_cycles(loop, 2)

    first, second = parsed(telemetry_capture)
    assert first["candle_age_status"] == "MEASURED"
    assert loop.last_candle_age["BTCUSDT"]["candle_age_status"] == "MEASURED"
    assert second["candle_age_seconds"] is None
    assert second["candle_age_status"] == "NOT_MEASURED_THIS_CYCLE"
    assert second["processing_cutoff"] is None


def test_telemetry_logger_does_not_propagate() -> None:
    target = logging.getLogger(TELEMETRY_LOGGER_NAME)

    assert target.propagate is False
    assert target.level == logging.INFO


CONSOLE_PROBE = """
import logging, sys
from datetime import UTC, datetime, timedelta
sys.path.insert(0, {tests!r})
sys.path.insert(0, {root!r})

# The same shape as main.py configure_logging(): one root console handler.
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout,
                    format="%(levelname)s | %(name)s | %(message)s")

import test_market_loop_candle_age_telemetry as t

loop = t.build_loop(
    t.SymbolFeed({{"BTCUSDT": [t.rows_closing_before(
        datetime.now(UTC), age=timedelta(seconds=5))]}}),
    ("BTCUSDT",),
)
t.run_worker_cycles(loop, 2)
print("PROBE-DONE cycles=%s" % loop.metrics["cycles"])
"""


def test_telemetry_never_reaches_the_console_outside_pytest(
    tmp_path: Path,
) -> None:
    """pytest itself attaches capture handlers to non-propagating loggers,
    so the console property is proven in a plain interpreter configured the
    way main.py configures the live console."""

    probe = tmp_path / "console_probe.py"
    probe.write_text(
        CONSOLE_PROBE.format(
            tests=str(REPOSITORY_ROOT / "tests"),
            root=str(REPOSITORY_ROOT),
        ),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env.pop(LOG_DIRECTORY_ENV, None)

    completed = subprocess.run(
        [sys.executable, str(probe)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "PROBE-DONE cycles=2" in completed.stdout
    assert "AtlasAI.MarketLoop" in completed.stdout  # console is live
    assert "market_loop_cycle" not in output
    assert TELEMETRY_LOGGER_NAME not in output
    assert list(tmp_path.iterdir()) == [probe]


def test_telemetry_failure_never_stops_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    loop = build_loop(
        SymbolFeed({"BTCUSDT": [rows_closing_before(now, age=timedelta(seconds=5))]}),
        ("BTCUSDT",),
    )

    def explode(*args: Any, **kwargs: Any) -> None:
        raise OSError("synthetic telemetry failure")

    monkeypatch.setattr(market_loop_module.telemetry_logger, "info", explode)

    run_worker_cycles(loop, 3)

    assert loop.metrics["cycles"] == 3
    assert loop.errors == []


# ---------------------------------------------------------------------------
# AtlasLogger
# ---------------------------------------------------------------------------

TEST_LOGGER_NAME = "AtlasAI.Test.V471Telemetry"


def test_atlas_logger_disabled_writes_nothing(tmp_path: Path) -> None:
    manager = AtlasLogger(telemetry_logger_name=TEST_LOGGER_NAME)
    manager.initialize()

    assert manager.enabled is False
    assert manager.log_file is None
    assert durable_handlers(TEST_LOGGER_NAME) == []
    manager.close()
    assert list(tmp_path.iterdir()) == []


def test_atlas_logger_record_round_trips_through_the_file(tmp_path: Path) -> None:
    target = logging.getLogger(TEST_LOGGER_NAME)
    target.propagate = False
    target.setLevel(logging.INFO)

    manager = AtlasLogger(
        log_directory=tmp_path,
        telemetry_logger_name=TEST_LOGGER_NAME,
    )
    manager.initialize()

    try:
        assert manager.enabled is True
        assert manager.log_file == tmp_path / TELEMETRY_LOG_FILE
        assert manager.log_file.exists()  # opened at initialize()

        record = {"symbol": "BTCUSDT", "candle_age_seconds": 1.5}
        target.info("%s", json.dumps(record))
    finally:
        manager.close()

    assert durable_handlers(TEST_LOGGER_NAME) == []
    lines = (tmp_path / TELEMETRY_LOG_FILE).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [record]


def test_atlas_logger_appends_across_runs(tmp_path: Path) -> None:
    target = logging.getLogger(TEST_LOGGER_NAME)
    target.propagate = False
    target.setLevel(logging.INFO)

    for index in range(2):
        manager = AtlasLogger(
            log_directory=tmp_path,
            telemetry_logger_name=TEST_LOGGER_NAME,
        )
        manager.initialize()
        target.info("%s", json.dumps({"run": index}))
        manager.close()

    lines = (tmp_path / TELEMETRY_LOG_FILE).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [{"run": 0}, {"run": 1}]


def test_atlas_logger_leaves_root_handlers_and_level_untouched(
    tmp_path: Path,
) -> None:
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    level_before = root.level

    manager = AtlasLogger(
        log_directory=tmp_path,
        telemetry_logger_name=TEST_LOGGER_NAME,
    )
    manager.initialize()

    try:
        assert root.handlers == handlers_before
        assert root.level == level_before
    finally:
        manager.close()


def test_atlas_logger_refuses_a_second_concurrent_handler(tmp_path: Path) -> None:
    first = AtlasLogger(log_directory=tmp_path, telemetry_logger_name=TEST_LOGGER_NAME)
    first.initialize()

    try:
        second = AtlasLogger(
            log_directory=tmp_path,
            telemetry_logger_name=TEST_LOGGER_NAME,
        )
        with pytest.raises(TelemetryHandlerConflictError):
            second.initialize()
        assert len(durable_handlers(TEST_LOGGER_NAME)) == 1
    finally:
        first.close()

    third = AtlasLogger(log_directory=tmp_path, telemetry_logger_name=TEST_LOGGER_NAME)
    third.initialize()
    third.close()


def test_atlas_logger_unusable_directory_fails_loudly_and_attaches_nothing(
    tmp_path: Path,
) -> None:
    manager = AtlasLogger(
        log_directory=tmp_path / "does_not_exist",
        telemetry_logger_name=TEST_LOGGER_NAME,
    )

    with pytest.raises(OSError):
        manager.initialize()

    assert manager.enabled is False
    assert durable_handlers(TEST_LOGGER_NAME) == []
    assert not (tmp_path / "does_not_exist").exists()


def test_atlas_logger_close_is_idempotent(tmp_path: Path) -> None:
    manager = AtlasLogger(log_directory=tmp_path, telemetry_logger_name=TEST_LOGGER_NAME)
    manager.initialize()
    manager.close()
    manager.close()
    assert manager.enabled is False


def test_atlas_logger_directory_without_logger_name_is_refused(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError):
        AtlasLogger(log_directory=tmp_path).initialize()


# ---------------------------------------------------------------------------
# ATLAS_LOG_DIRECTORY resolution
# ---------------------------------------------------------------------------


def test_log_directory_unset_is_disabled_not_repository_relative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(LOG_DIRECTORY_ENV, raising=False)
    assert resolve_log_directory() is None


def test_log_directory_valid_override_resolves(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(LOG_DIRECTORY_ENV, str(tmp_path))
    assert resolve_log_directory() == tmp_path.resolve()


@pytest.mark.parametrize("raw", ["", "   ", "relative/logs", "logs"])
def test_log_directory_empty_or_relative_override_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    monkeypatch.setenv(LOG_DIRECTORY_ENV, raw)

    with pytest.raises(ConfiguredDirectoryError) as caught:
        resolve_log_directory()

    if not raw.strip():
        assert "leave it unconfigured" in str(caught.value)
        assert "None" not in str(caught.value)


def test_log_directory_missing_override_fails_closed_and_is_not_created(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "not_yet_created"
    monkeypatch.setenv(LOG_DIRECTORY_ENV, str(missing))

    with pytest.raises(ConfiguredDirectoryError):
        resolve_log_directory()

    assert not missing.exists()


def test_log_directory_file_override_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    a_file = tmp_path / "a_file.txt"
    a_file.write_text("x", encoding="utf-8")
    monkeypatch.setenv(LOG_DIRECTORY_ENV, str(a_file))

    with pytest.raises(ConfiguredDirectoryError):
        resolve_log_directory()


def test_state_directory_empty_message_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STATE_DIRECTORY_ENV, "")

    with pytest.raises(ConfiguredDirectoryError) as caught:
        resolve_state_directory()

    message = str(caught.value)
    assert message.startswith(
        "ATLAS_STATE_DIRECTORY is set but empty. Unset it to use the default ("
    )
    assert message.endswith(
        "), or set it to an absolute path to an existing directory."
    )


# ---------------------------------------------------------------------------
# Composition root wiring
# ---------------------------------------------------------------------------


def build_application(tmp_path: Path, **kwargs: Any) -> AtlasApplication:
    state = tmp_path / "state"
    evidence = tmp_path / "evidence"
    state.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)

    return AtlasApplication(
        state_directory=state,
        evidence_directory=evidence,
        **kwargs,
    )


def test_application_without_log_directory_writes_no_telemetry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(LOG_DIRECTORY_ENV, raising=False)

    app = build_application(tmp_path)

    assert app.log_directory is None
    assert app.logger_manager.enabled is False
    assert durable_handlers(TELEMETRY_LOGGER_NAME) == []


def test_application_env_override_activates_the_file_handler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setenv(LOG_DIRECTORY_ENV, str(logs))

    app = build_application(tmp_path)

    try:
        assert app.log_directory == logs.resolve()
        assert app.logger_manager.enabled is True
        assert (logs / TELEMETRY_LOG_FILE).exists()
        assert len(durable_handlers(TELEMETRY_LOGGER_NAME)) == 1
    finally:
        app.logger_manager.close()


def test_application_invalid_env_override_refuses_to_construct(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(LOG_DIRECTORY_ENV, str(tmp_path / "typo"))

    with pytest.raises(ConfiguredDirectoryError):
        build_application(tmp_path)

    assert durable_handlers(TELEMETRY_LOGGER_NAME) == []


def test_application_explicit_log_directory_wins_over_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(LOG_DIRECTORY_ENV, str(tmp_path / "typo"))
    logs = tmp_path / "explicit_logs"
    logs.mkdir()

    app = build_application(tmp_path, log_directory=logs)

    try:
        assert app.log_directory == logs
        assert app.logger_manager.log_file == logs / TELEMETRY_LOG_FILE
    finally:
        app.logger_manager.close()


# ---------------------------------------------------------------------------
# TEST-ISO-001 extension
# ---------------------------------------------------------------------------


def test_pytest_session_runs_with_log_directory_unset() -> None:
    assert LOG_DIRECTORY_ENV not in os.environ


def test_nested_pytest_never_inherits_an_exported_log_directory(
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "sentinel_log_root"
    sentinel.mkdir()

    probe_path = (
        REPOSITORY_ROOT
        / "tests"
        / f"test_zz_generated_log_isolation_probe_{uuid.uuid4().hex}.py"
    )
    probe_path.write_text(
        "import os\n"
        "\n"
        "\n"
        "def test_log_directory_is_not_inherited() -> None:\n"
        f"    assert {LOG_DIRECTORY_ENV!r} not in os.environ\n",
        encoding="utf-8",
    )

    try:
        env = dict(os.environ)
        env[LOG_DIRECTORY_ENV] = str(sentinel)

        completed = subprocess.run(
            [sys.executable, "-m", "pytest", str(probe_path), "-q", "-p", "no:cacheprovider"],
            capture_output=True,
            text=True,
            cwd=str(REPOSITORY_ROOT),
            env=env,
        )

        assert completed.returncode == 0, completed.stdout + completed.stderr
    finally:
        probe_path.unlink(missing_ok=True)

    assert list(sentinel.iterdir()) == []


# ---------------------------------------------------------------------------
# Local smoke test: real composition root, real worker, real file
# ---------------------------------------------------------------------------


def test_smoke_real_application_writes_parseable_telemetry(
    tmp_path: Path,
) -> None:
    """End to end: AtlasApplication wires the telemetry file, the real
    MarketLoop worker runs real cycles over real-shaped kline rows (only the
    network feed is replaced), stop() drains the queue, and every line of
    the file parses back with real computed values."""

    logs = tmp_path / "logs"
    logs.mkdir()
    app = build_application(tmp_path, log_directory=logs)

    loop = app.market_loop
    symbols = tuple(loop.symbols)

    def fresh_window(symbol: str) -> list[list[Any]]:
        return rows_closing_before(
            datetime.now(UTC),
            age=timedelta(seconds=42),
        )

    loop.market_feed = SymbolFeed(
        {symbol: [fresh_window] for symbol in symbols}
    )

    try:
        run_worker_cycles(loop, 3)
    finally:
        app.stop()

    assert app.logger_manager.enabled is False
    assert durable_handlers(TELEMETRY_LOGGER_NAME) == []

    text = (logs / TELEMETRY_LOG_FILE).read_text(encoding="utf-8")
    records = [json.loads(line) for line in io.StringIO(text)]

    assert len(records) == 3 * len(symbols)
    assert {r["cycle"] for r in records} == {1, 2, 3}
    assert {r["symbol"] for r in records} == set(symbols)

    for record in records:
        assert record["candle_age_status"] == "MEASURED"
        # Windows are built at fetch time, just after the cycle cutoff is
        # read, so the measured age is a few ms under the fixture's 42 s.
        assert 40.0 <= record["candle_age_seconds"] <= 42.0
        assert record["cycle_duration_seconds"] >= 0.0
        close = datetime.fromisoformat(record["candle_close_time"])
        cutoff = datetime.fromisoformat(record["processing_cutoff"])
        assert (cutoff - close).total_seconds() == pytest.approx(
            record["candle_age_seconds"],
            abs=0.001,
        )


# ---------------------------------------------------------------------------
# Independent-audit remediation (F1-F4, F6)
# ---------------------------------------------------------------------------


def _enabled_manager(tmp_path: Path) -> AtlasLogger:
    target = logging.getLogger(TEST_LOGGER_NAME)
    target.propagate = False
    target.setLevel(logging.INFO)
    manager = AtlasLogger(
        log_directory=tmp_path,
        telemetry_logger_name=TEST_LOGGER_NAME,
    )
    manager.initialize()
    return manager


def test_f1_failed_file_writes_never_print_records_to_the_console(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Against a stdlib FileHandler this prints '--- Logging error ---'
    plus the record text to stderr once per failed write."""

    manager = _enabled_manager(tmp_path)
    handler = manager._file_handler
    assert handler is not None
    assert not isinstance(handler, logging.Handler)
    handler._stream.close()  # every following write now fails

    target = logging.getLogger(TEST_LOGGER_NAME)
    with caplog.at_level(logging.WARNING, logger="AtlasAI.Logger"):
        for index in range(3):
            target.info("%s", json.dumps({"event": "market_loop_cycle", "n": index}))

        manager.close()

    captured = capfd.readouterr()
    assert "market_loop_cycle" not in captured.out + captured.err
    assert "Logging error" not in captured.err
    assert handler.write_failures == 3
    warnings = [
        r for r in caplog.records
        if r.name == "AtlasAI.Logger" and "write failed" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert "market_loop_cycle" not in warnings[0].getMessage()


def test_f2_close_is_bounded_when_the_writer_is_stuck(tmp_path: Path) -> None:
    """Against QueueListener.stop() this blocks until the write returns."""

    import threading
    import time

    manager = _enabled_manager(tmp_path)
    handler = manager._file_handler
    listener = manager._listener
    assert handler is not None and listener is not None

    release = threading.Event()
    entered = threading.Event()

    def stuck_handle(record: logging.LogRecord) -> None:
        entered.set()
        release.wait(30)

    handler.handle = stuck_handle  # type: ignore[method-assign]
    logging.getLogger(TEST_LOGGER_NAME).info("%s", "{}")
    assert entered.wait(5)

    started = time.monotonic()
    try:
        assert manager.close(timeout=0.2) is False
        assert time.monotonic() - started < 3.0
        assert durable_handlers(TEST_LOGGER_NAME) == []
    finally:
        release.set()
        thread = listener._thread
        if thread is not None:
            thread.join(5)
        handler.close()


def test_f3_telemetry_close_failure_never_changes_stop_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(LOG_DIRECTORY_ENV, raising=False)
    control = build_application(tmp_path / "control")

    logs = tmp_path / "logs"
    logs.mkdir()
    broken = build_application(tmp_path / "broken", log_directory=logs)
    handler = broken.logger_manager._file_handler
    assert handler is not None
    real_close = handler.close

    def failing_close() -> None:
        real_close()
        raise OSError("synthetic telemetry close failure")

    handler.close = failing_close  # type: ignore[method-assign]

    assert broken.stop() == control.stop()
    assert broken.errors == control.errors
    assert broken.logger_manager.enabled is False


def test_f4_measurement_is_tagged_with_its_own_workers_cycle() -> None:
    """A measurement taken by the worker running cycle 5 must not be
    reported as cycle 4's, even though the shared counter says 4 (as it
    would if another worker had advanced it). Tagging from the shared
    counter reports it under cycle 4."""

    import threading

    loop = build_loop(SymbolFeed({}), ("BTCUSDT",))
    window = rows_closing_before(CUTOFF, age=timedelta(seconds=9))
    closed = loop.processor.closed_candles(
        loop.processor.normalize(window, processing_cutoff=CUTOFF)
    )

    def measure_as_worker_cycle_5() -> None:
        loop._telemetry_cycle.sequence = 5
        loop._record_candle_age("BTCUSDT", closed, CUTOFF)

    worker = threading.Thread(target=measure_as_worker_cycle_5)
    worker.start()
    worker.join(5)

    loop._telemetry_cycle_sequence = 4
    assert loop.last_candle_age["BTCUSDT"]["cycle_sequence"] == 5

    capture = RecordCapture()
    target = logging.getLogger(TELEMETRY_LOGGER_NAME)
    target.addHandler(capture)
    try:
        loop._emit_cycle_telemetry(4)
        loop._emit_cycle_telemetry(5)
    finally:
        target.removeHandler(capture)

    as_cycle_4, as_cycle_5 = parsed(capture)
    assert as_cycle_4["candle_age_status"] == "NOT_MEASURED_THIS_CYCLE"
    assert as_cycle_4["candle_age_seconds"] is None
    assert as_cycle_5["candle_age_status"] == "MEASURED"
    assert as_cycle_5["candle_age_seconds"] == 9.0


@pytest.mark.parametrize("relative", ["", "logs", "relative/logs"])
def test_f6_explicit_relative_log_directory_is_refused(
    tmp_path: Path,
    relative: str,
) -> None:
    manager = AtlasLogger(
        log_directory=relative,
        telemetry_logger_name=TEST_LOGGER_NAME,
    )

    with pytest.raises(ValueError):
        manager.initialize()

    assert durable_handlers(TEST_LOGGER_NAME) == []

    with pytest.raises(ValueError):
        build_application(tmp_path, log_directory=relative)


N1_EXIT_PROBE = """
import logging, sys, time
sys.path.insert(0, {root!r})
from core.logger import AtlasLogger

target = logging.getLogger("AtlasAI.Test.N1ExitProbe")
target.propagate = False
target.setLevel(logging.INFO)

manager = AtlasLogger(
    log_directory={logs!r},
    telemetry_logger_name="AtlasAI.Test.N1ExitProbe",
)
manager.initialize()

def stuck(record):
    time.sleep(20)  # a write to a hung volume

manager._file_handler.handle = stuck
target.info("%s", "{{}}")
time.sleep(0.3)  # let the writer thread enter the stuck write
print("close-returned", manager.close(timeout=0.3), flush=True)
"""


def test_n1_a_stuck_write_never_blocks_process_exit(tmp_path: Path) -> None:
    """Audit N1. With a logging.Handler as the sink, logging.shutdown() at
    interpreter exit waits on the stuck writer's lock, so this process
    would take the full 20 s to exit. With a plain writer it exits at once
    (the writer is a daemon thread)."""

    import time

    logs = tmp_path / "logs"
    logs.mkdir()
    probe = tmp_path / "n1_exit_probe.py"
    probe.write_text(
        N1_EXIT_PROBE.format(root=str(REPOSITORY_ROOT), logs=str(logs)),
        encoding="utf-8",
    )

    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, str(probe)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=60,
    )
    elapsed = time.monotonic() - started

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "close-returned False" in completed.stdout
    assert elapsed < 12.0, f"process exit took {elapsed:.1f}s"
