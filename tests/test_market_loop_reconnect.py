"""Package RECONNECT: market-data resilience regression tests.

Covers three additive observability/correctness gaps in the sole live
market-data ingestion path (MarketLoop -> MarketFeed -> MarketFeedService
-> BinancePublicDataProvider), found during a prior PLAN MODE
investigation:

- GAP #1: MarketLoop.health() must derive "healthy" from recent error
  state (the timestamped self.errors list), not the lifetime-cumulative
  metrics["errors"] counter, so one historical transient error does not
  permanently latch healthy=False.
- GAP #2: MarketLoop must report per-symbol market-data staleness
  (seconds since the last successful fetch) independent of whether the
  most recent request technically "succeeded" - observability only, it
  must never gate or block trading/decisions.
- GAP #3: MarketLoop must detect and report (never silently repair) an
  outage longer than one cycle's backfill window, which otherwise drops
  candles permanently with no trace.

These tests are offline. They construct only in-memory MarketLoop
instances with fake feeds/brains, so they cannot touch runtime state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from core.market_loop import MarketLoop

MINUTE_MS = 60_000

FAR_FUTURE_CUTOFF = datetime(2030, 1, 1, tzinfo=UTC)


def build_candle_rows(
    count: int,
    *,
    start_ms: int,
    start_price: float = 60_000.0,
) -> list[list[Any]]:
    """Build Binance-compatible legacy kline rows, ascending by open time."""

    rows: list[list[Any]] = []

    for index in range(count):
        open_ms = start_ms + index * MINUTE_MS
        close_ms = open_ms + MINUTE_MS - 1
        base = start_price + (index * 4.0)
        volume = 10.0 + (index * 0.05)

        rows.append([
            open_ms,
            f"{base:.2f}",
            f"{base + 35.0:.2f}",
            f"{base - 25.0:.2f}",
            f"{base + 12.0:.2f}",
            f"{volume:.5f}",
            close_ms,
            "0.0",
            0,
            f"{volume * 0.4:.5f}",
            f"{(base + 12.0) * volume * 0.4:.8f}",
            "0",
        ])

    return rows


class SequencedFeed:
    """Legacy MarketFeed stand-in returning one fixed window call."""

    def __init__(self, windows: list[list[list[Any]]]) -> None:
        self._windows = list(windows)
        self.calls = 0

    def candles(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int = 200,
    ) -> list[list[Any]]:
        window = self._windows[
            min(self.calls, len(self._windows) - 1)
        ]
        self.calls += 1
        return window


class FakeBrain:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def analyze_and_decide(
        self,
        symbol: str,
        market_data: Any,
    ) -> dict[str, Any]:
        self.calls.append({"symbol": symbol, "market_data": market_data})
        return {
            "symbol": symbol,
            "action": "HOLD",
            "confidence": 75.0,
            "risk": "LOW",
            "strategy": "RECONNECT_TEST",
            "reason": "Offline RECONNECT regression fixture.",
        }


class RecordingEventBus:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, event_payload: dict[str, Any]) -> bool:
        self.events.append(event_payload)
        return True


# ---------------------------------------------------------------------------
# GAP #1: health() reflects recent state, not lifetime-cumulative state
# ---------------------------------------------------------------------------


def test_health_recovers_after_transient_error_ages_out() -> None:
    loop = MarketLoop(
        brain=object(),
        market_feed=object(),
        symbols=["BTCUSDT"],
    )

    assert loop.health()["healthy"] is True

    loop._record_error(phase="test", error=RuntimeError("transient"))

    # A just-recorded error still latches healthy=False.
    assert loop.health()["healthy"] is False
    assert loop.metrics["errors"] == 1

    # Age the recorded error past the recovery window - simulating
    # clean cycles having elapsed since - without touching the
    # cumulative counter at all.
    stale_time = datetime.now(UTC) - timedelta(
        seconds=loop.HEALTH_ERROR_RECOVERY_SECONDS + 1
    )
    loop.errors[-1]["time"] = stale_time.isoformat()

    result = loop.health()

    assert result["healthy"] is True
    # metrics["errors"] stays lifetime-cumulative for other consumers.
    assert loop.metrics["errors"] == 1
    assert result["errors"] == 1


def test_health_stays_unhealthy_while_error_is_within_the_window() -> None:
    loop = MarketLoop(
        brain=object(),
        market_feed=object(),
        symbols=["BTCUSDT"],
    )

    loop._record_error(phase="test", error=RuntimeError("transient"))

    recent_time = datetime.now(UTC) - timedelta(
        seconds=max(0.0, loop.HEALTH_ERROR_RECOVERY_SECONDS - 5)
    )
    loop.errors[-1]["time"] = recent_time.isoformat()

    assert loop.health()["healthy"] is False


# ---------------------------------------------------------------------------
# GAP #2: per-symbol staleness reporting, observability only
# ---------------------------------------------------------------------------


def test_staleness_reports_seconds_since_last_success() -> None:
    start_ms = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)
    feed = SequencedFeed([build_candle_rows(200, start_ms=start_ms)])
    brain = FakeBrain()

    loop = MarketLoop(
        brain=brain,
        market_feed=feed,
        symbols=["BTCUSDT"],
    )

    result = loop.process_symbol("BTCUSDT", processing_cutoff=FAR_FUTURE_CUTOFF)
    assert result is not None

    staleness = loop.status()["market_data_staleness"]["BTCUSDT"]
    assert staleness["stale"] is False
    assert staleness["seconds_since_last_success"] is not None
    assert 0.0 <= staleness["seconds_since_last_success"] < loop.STALENESS_THRESHOLD_SECONDS

    # Backdate the recorded success to simulate elapsed wall-clock time
    # with no new request having failed - this must surface as stale.
    loop.last_symbol_fetch_success_at["BTCUSDT"] = datetime.now(UTC) - timedelta(
        seconds=loop.STALENESS_THRESHOLD_SECONDS + 30
    )

    health_result = loop.health()

    assert health_result["market_data_stale"] is True
    # Staleness is reporting only - it must never gate/block healthy.
    assert health_result["healthy"] is True


def test_staleness_true_for_symbol_never_fetched() -> None:
    loop = MarketLoop(
        brain=object(),
        market_feed=object(),
        symbols=["BTCUSDT", "ETHUSDT"],
    )

    snapshot = loop.status()["market_data_staleness"]

    assert snapshot["BTCUSDT"]["stale"] is True
    assert snapshot["BTCUSDT"]["seconds_since_last_success"] is None
    assert snapshot["ETHUSDT"]["stale"] is True

    # A never-fetched symbol must not itself flip the loop unhealthy.
    assert loop.health()["healthy"] is True


# ---------------------------------------------------------------------------
# M-1: an empty provider response is not evidence of freshness
#
# last_symbol_fetch_success_at was assigned immediately after _load_candles()
# returned, before the "if not candles:" guard, so a provider returning []
# forever - a delisted symbol, a silently failing API, empty-response rate
# limiting - refreshed the timestamp on every cycle and staleness reported
# False indefinitely. That is the NB-4 shape: absence of data rendered as
# positive evidence of data, propagating to the operator surface.
# ---------------------------------------------------------------------------


def test_repeated_empty_responses_report_stale_not_fresh() -> None:
    """A provider that only ever returns [] must never look fresh."""

    feed = SequencedFeed([[]])
    loop = MarketLoop(
        brain=FakeBrain(),
        market_feed=feed,
        symbols=["BTCUSDT"],
    )

    for _ in range(5):
        result = loop.process_symbol("BTCUSDT", processing_cutoff=FAR_FUTURE_CUTOFF)
        assert result is None

    assert feed.calls == 5, "the fixture must actually have been polled"

    # No successful fetch was ever recorded, so the never-fetched path applies.
    assert "BTCUSDT" not in loop.last_symbol_fetch_success_at

    staleness = loop.status()["market_data_staleness"]["BTCUSDT"]
    assert staleness["stale"] is True
    assert staleness["seconds_since_last_success"] is None
    assert loop.health()["market_data_stale"] is True

    # Staleness stays reporting-only even in this case.
    assert loop.health()["healthy"] is True


def test_empty_responses_do_not_refresh_an_aging_timestamp() -> None:
    """The operational case: a symbol goes fresh, then its provider dries up.

    Pre-fix, each empty response re-stamped the symbol as freshly fetched, so
    it could never age into staleness no matter how long the data stopped.
    """

    start_ms = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)
    feed = SequencedFeed([build_candle_rows(200, start_ms=start_ms), []])
    loop = MarketLoop(
        brain=FakeBrain(),
        market_feed=feed,
        symbols=["BTCUSDT"],
    )

    # Cycle 1 delivers real bars and legitimately records freshness.
    assert loop.process_symbol("BTCUSDT", processing_cutoff=FAR_FUTURE_CUTOFF) is not None
    assert loop.status()["market_data_staleness"]["BTCUSDT"]["stale"] is False

    # Age that success past the threshold, then let the provider return [].
    aged_at = datetime.now(UTC) - timedelta(
        seconds=loop.STALENESS_THRESHOLD_SECONDS + 30
    )
    loop.last_symbol_fetch_success_at["BTCUSDT"] = aged_at

    for _ in range(3):
        assert loop.process_symbol("BTCUSDT", processing_cutoff=FAR_FUTURE_CUTOFF) is None

    # The aged timestamp must be untouched by the empty responses.
    assert loop.last_symbol_fetch_success_at["BTCUSDT"] == aged_at

    staleness = loop.status()["market_data_staleness"]["BTCUSDT"]
    assert staleness["stale"] is True
    assert staleness["seconds_since_last_success"] > loop.STALENESS_THRESHOLD_SECONDS
    assert loop.health()["market_data_stale"] is True


def test_real_candles_still_record_freshness_unchanged() -> None:
    """The normal path is untouched: delivered bars still mark the symbol fresh."""

    start_ms = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)
    feed = SequencedFeed([build_candle_rows(200, start_ms=start_ms)])
    loop = MarketLoop(
        brain=FakeBrain(),
        market_feed=feed,
        symbols=["BTCUSDT"],
    )

    before = datetime.now(UTC)
    assert loop.process_symbol("BTCUSDT", processing_cutoff=FAR_FUTURE_CUTOFF) is not None
    after = datetime.now(UTC)

    recorded = loop.last_symbol_fetch_success_at["BTCUSDT"]
    assert before <= recorded <= after

    staleness = loop.status()["market_data_staleness"]["BTCUSDT"]
    assert staleness["stale"] is False
    assert staleness["seconds_since_last_success"] is not None


# ---------------------------------------------------------------------------
# GAP #3: outage longer than the backfill window is detected and reported
# ---------------------------------------------------------------------------


def test_backfill_gap_exceeding_window_is_detected_and_logged() -> None:
    start_a = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)
    window_a = build_candle_rows(200, start_ms=start_a)  # minutes 0..199

    # Simulated outage: the next window starts far beyond the first
    # window's span, well past what one cycle's backfill can self-heal.
    start_b = start_a + 1000 * MINUTE_MS  # minute 1000
    window_b = build_candle_rows(200, start_ms=start_b)  # minutes 1000..1199

    feed = SequencedFeed([window_a, window_b])
    brain = FakeBrain()
    event_bus = RecordingEventBus()

    loop = MarketLoop(
        brain=brain,
        market_feed=feed,
        event_bus=event_bus,
        symbols=["BTCUSDT"],
    )

    first_result = loop.process_symbol(
        "BTCUSDT", processing_cutoff=FAR_FUTURE_CUTOFF
    )
    assert first_result is not None
    assert loop.metrics["backfill_gap_exceeded"] == 0

    second_result = loop.process_symbol(
        "BTCUSDT", processing_cutoff=FAR_FUTURE_CUTOFF
    )

    # Normal processing still resumes correctly after the gap.
    assert second_result is not None
    assert loop.metrics["errors"] == 0
    assert loop.metrics["backfill_gap_exceeded"] == 1

    gap_events = [
        event
        for event in event_bus.events
        if event.get("event") == "MARKET_DATA_BACKFILL_GAP_EXCEEDED"
    ]

    assert len(gap_events) == 1
    payload = gap_events[0]["payload"]
    assert payload["symbol"] == "BTCUSDT"
    assert payload["gap_minutes"] > 199.0


def test_backfill_within_window_is_not_flagged() -> None:
    """A normal, self-healed gap under the fetched window must not fire."""

    start_ms = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)
    window_a = build_candle_rows(200, start_ms=start_ms)

    # Shift forward by less than the 200-candle window span - the kind
    # of gap the refetch-latest-200 behavior already self-heals.
    window_b = build_candle_rows(200, start_ms=start_ms + 50 * MINUTE_MS)

    feed = SequencedFeed([window_a, window_b])
    brain = FakeBrain()
    event_bus = RecordingEventBus()

    loop = MarketLoop(
        brain=brain,
        market_feed=feed,
        event_bus=event_bus,
        symbols=["BTCUSDT"],
    )

    loop.process_symbol("BTCUSDT", processing_cutoff=FAR_FUTURE_CUTOFF)
    loop.process_symbol("BTCUSDT", processing_cutoff=FAR_FUTURE_CUTOFF)

    assert loop.metrics["backfill_gap_exceeded"] == 0
    assert not any(
        event.get("event") == "MARKET_DATA_BACKFILL_GAP_EXCEEDED"
        for event in event_bus.events
    )
