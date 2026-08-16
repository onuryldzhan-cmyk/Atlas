"""Block 4 / Package 3: live market-data correctness.

The canonical live/PAPER market-data path must be semantically
deterministic, fail-closed, and metadata-correct:

- one explicit processing cutoff decides closure, and nothing below
  MarketLoop reads a clock;
- an identity collision is either an idempotent duplicate or a
  fail-closed conflict, never an order-dependent winner;
- MarketFeedService keeps ordering authority and CandleProcessor never
  silently repairs a sequence;
- naive datetimes are rejected instead of being read as local time;
- real provider metadata reaches the legacy row, and missing metadata
  fails closed rather than being fabricated as zero.

These tests are offline. They construct no ExecutionManager, no
AtlasApplication, and no durable store, so they cannot touch runtime
state.
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from atlas_finance.market_data.binance_public_provider import (
    BinancePublicDataProvider,
)
from atlas_finance.market_data.exceptions import (
    InvalidCandleError,
    MarketDataError,
)
from atlas_finance.market_data.market_feed_service import MarketFeedService
from atlas_finance.market_data.models import MarketCandle, MarketPrice
from atlas_finance.market_data.temporal import (
    TemporalContractError,
    is_closed_at,
    is_future_open_at,
    require_aware_utc,
    to_milliseconds,
)
from core.candle_processor import (
    CandleConflictError,
    CandleContractError,
    CandleOrderingError,
    CandleProcessor,
)
from core.market_loop import MarketLoop
from exchange.market_feed import MarketFeed

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# A fixed, entirely historical cutoff keeps every expectation below
# independent of when the suite runs.
CUTOFF = datetime(2026, 3, 1, tzinfo=UTC)
CUTOFF_MS = int(CUTOFF.timestamp() * 1000)

MINUTE_MS = 60_000


def row(
    open_ms: int,
    *,
    close_ms: int | None = None,
    open_price: str = "100.0",
    high: str = "110.0",
    low: str = "90.0",
    close: str = "105.0",
    volume: str = "10.0",
    quote_volume: str = "1000.0",
    trades: int = 25,
    taker_buy_base_volume: str = "4.0",
    taker_buy_quote_volume: str = "400.0",
    ignore: str = "0",
) -> list[Any]:
    """Build one Binance-compatible legacy kline row."""

    return [
        open_ms,
        open_price,
        high,
        low,
        close,
        volume,
        open_ms + MINUTE_MS - 1 if close_ms is None else close_ms,
        quote_volume,
        trades,
        taker_buy_base_volume,
        taker_buy_quote_volume,
        ignore,
    ]


def binance_kline(columns: int = 12) -> list[Any]:
    """One real-shaped Binance kline array truncated to ``columns``."""

    full: list[Any] = [
        1769947200000,
        "100.00000000",
        "110.00000000",
        "90.00000000",
        "105.00000000",
        "10.00000000",
        1769947499999,
        "1050.00000000",
        308,
        "4.00000000",
        "420.00000000",
        "17928899.62484339",
    ]

    return full[:columns]


class FakeKlineResponse:
    """Minimal requests.Response stand-in for the public provider."""

    status_code = 200
    headers: dict[str, str] = {}
    text = ""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class FakeKlineSession:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def get(self, url: str, **kwargs: Any) -> FakeKlineResponse:
        return FakeKlineResponse(self._payload)


def provider_candles(payload: Any) -> tuple[MarketCandle, ...]:
    """Run the real provider parser over a raw kline payload."""

    provider = BinancePublicDataProvider(session=FakeKlineSession(payload))

    return tuple(provider.get_candles("BTCUSDT", timeframe="5m", limit=1))


def historical_rows(count: int, *, start_ms: int | None = None) -> list[list[Any]]:
    base = CUTOFF_MS - (count + 1) * MINUTE_MS if start_ms is None else start_ms
    return [row(base + index * MINUTE_MS) for index in range(count)]


def candle(
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "5m",
    open_time: datetime,
    close_time: datetime,
    closed: bool = True,
    metadata: dict[str, Any] | None = None,
) -> MarketCandle:
    return MarketCandle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=close_time,
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=10.0,
        provider="fake_public_provider",
        closed=closed,
        metadata={
            "quote_volume": 8125000.0,
            "trades": 1500,
            "taker_buy_base_volume": 60.0,
            "taker_buy_quote_volume": 3900000.0,
        }
        if metadata is None
        else metadata,
    )


class StubProvider:
    """Minimal MarketDataProviderProtocol implementation."""

    provider_name = "fake_public_provider"

    def __init__(self, candles: tuple[MarketCandle, ...] = ()) -> None:
        self.connected = False
        self._candles = candles

    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def get_price(self, symbol: str) -> MarketPrice:
        return MarketPrice(
            symbol=symbol,
            price=100.0,
            provider=self.provider_name,
            received_at=datetime.now(UTC),
        )

    def get_candles(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 100,
    ) -> tuple[MarketCandle, ...]:
        return self._candles


def started_feed(provider: StubProvider) -> MarketFeed:
    feed = MarketFeed(
        provider=provider,
        publish_events=False,
        collect_metrics=False,
    )
    feed.start()
    return feed


def foreign_attribute_reads(path: Path, attribute: str) -> bool:
    """True if the module reads ``attribute`` off anything but ``self``.

    ``self.closed`` is a module's own state (PositionController keeps a
    list of closed positions under that name). ``candle.closed`` is a
    read of the provider's advisory flag, which is what this rejects.
    """

    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != attribute:
            continue
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            continue
        return True
    return False


def called_names(path: Path) -> set[str]:
    """Return dotted names of every call target in a module."""

    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            parts = [target.attr]
            inner = target.value
            while isinstance(inner, ast.Attribute):
                parts.append(inner.attr)
                inner = inner.value
            if isinstance(inner, ast.Name):
                parts.append(inner.id)
            names.add(".".join(reversed(parts)))
    return names


# ---------------------------------------------------------------------------
# 1-3. Same-key conflict semantics
# ---------------------------------------------------------------------------


def test_identical_duplicate_candles_collapse_idempotently():
    original = row(CUTOFF_MS - 10 * MINUTE_MS)

    single = CandleProcessor()
    once = single.normalize([original], processing_cutoff=CUTOFF)

    repeated = CandleProcessor()
    twice = repeated.normalize(
        [list(original), list(original), list(original)],
        processing_cutoff=CUTOFF,
    )

    assert len(twice) == 1
    assert twice == once
    assert single.metrics["duplicates_removed"] == 0
    assert repeated.metrics["duplicates_removed"] == 2
    assert repeated.metrics["conflicts_detected"] == 0

    # A repeated identity is never disorder: ordering authority must
    # not absorb what duplicate authority owns.
    assert repeated.metrics["ordering_violations"] == 0


def test_conflicting_payloads_for_one_identity_fail_closed():
    open_ms = CUTOFF_MS - 10 * MINUTE_MS
    processor = CandleProcessor()

    with pytest.raises(CandleConflictError) as failure:
        processor.normalize(
            [row(open_ms), row(open_ms, close="106.0")],
            processing_cutoff=CUTOFF,
        )

    assert processor.metrics["conflicts_detected"] == 1
    assert "MARKET_DATA_CONFLICT" == type(failure.value).reason


def test_reversed_conflict_order_produces_the_same_outcome():
    """No first-wins, no last-wins, no input-order-dependent winner."""

    open_ms = CUTOFF_MS - 10 * MINUTE_MS
    forward = [row(open_ms), row(open_ms, close="106.0")]
    reversed_order = [row(open_ms, close="106.0"), row(open_ms)]

    for candles in (forward, reversed_order):
        with pytest.raises(CandleConflictError):
            CandleProcessor().normalize(candles, processing_cutoff=CUTOFF)


def test_conflict_is_not_mislabelled_as_missing_closed_candles():
    """MarketLoop reports the conflict, not NO_CLOSED_CANDLES."""

    open_ms = CUTOFF_MS - 10 * MINUTE_MS

    class ConflictFeed:
        def candles(self, symbol: str, interval: str = "1m", limit: int = 500):
            return [row(open_ms), row(open_ms, close="106.0")]

    loop = MarketLoop(
        brain=object(),
        market_feed=ConflictFeed(),
        symbols=["BTCUSDT"],
    )

    result = loop.process_symbol("BTCUSDT", processing_cutoff=CUTOFF)

    assert set(result) == {"status", "reason", "symbol", "detail"}
    assert result["status"] == "SKIPPED"
    assert result["reason"] == "MARKET_DATA_CONFLICT"
    assert result["symbol"] == "BTCUSDT"
    assert f"open:{open_ms}" in result["detail"]
    assert loop.metrics["market_data_contract_violations"] == 1


# ---------------------------------------------------------------------------
# 4-5. Ordering authority
# ---------------------------------------------------------------------------


def test_out_of_order_input_is_not_silently_repaired():
    ordered = historical_rows(3)
    shuffled = [ordered[2], ordered[0], ordered[1]]

    with pytest.raises(CandleOrderingError):
        CandleProcessor().normalize(shuffled, processing_cutoff=CUTOFF)


def test_processor_never_sorts_input_into_a_new_sequence():
    """Accepted output preserves provider order rather than a sort."""

    processor = CandleProcessor()
    ordered = historical_rows(4)

    normalized = processor.normalize(ordered, processing_cutoff=CUTOFF)

    assert [item["open_time"] for item in normalized] == [
        item[0] for item in ordered
    ]

    source = (REPOSITORY_ROOT / "core/candle_processor.py").read_text(
        encoding="utf-8-sig"
    )
    assert ".sort(" not in source
    assert "sorted(" not in source


def test_market_feed_service_ordering_authority_remains_fail_closed():
    first = candle(
        open_time=datetime(2026, 2, 1, 12, 0, tzinfo=UTC),
        close_time=datetime(2026, 2, 1, 12, 4, 59, tzinfo=UTC),
    )
    earlier = candle(
        open_time=datetime(2026, 2, 1, 11, 0, tzinfo=UTC),
        close_time=datetime(2026, 2, 1, 11, 4, 59, tzinfo=UTC),
    )

    service = MarketFeedService(
        provider=StubProvider((first, earlier)),
        publish_events=False,
        collect_metrics=False,
    )
    service.start()

    try:
        with pytest.raises(MarketDataError, match="not sorted"):
            service.get_candles("BTCUSDT", timeframe="5m", limit=10)
    finally:
        service.stop()


# ---------------------------------------------------------------------------
# Same identity versus ordering
#
# Ordering authority judges primary temporal order only. Two rows that
# share an open time share one exchange candle identity, so they are a
# duplicate or conflict question. If close time were an ordering
# tiebreaker, the same ambiguous pair would be reported as
# MARKET_DATA_ORDERING in one arrival order and MARKET_DATA_CONFLICT in
# the other.
# ---------------------------------------------------------------------------


def contract_outcome(candles: list[list[Any]]) -> tuple[Any, str, int, int]:
    """Normalize ``candles`` and describe how the contract failed."""

    processor = CandleProcessor()

    with pytest.raises(CandleContractError) as failure:
        processor.normalize(candles, processing_cutoff=CUTOFF)

    return (
        type(failure.value),
        type(failure.value).reason,
        processor.metrics["conflicts_detected"],
        processor.metrics["ordering_violations"],
    )


def test_close_time_only_disagreement_is_a_conflict_in_both_orders():
    open_ms = CUTOFF_MS - 10 * MINUTE_MS
    early_close = row(open_ms, close_ms=open_ms + MINUTE_MS - 1)
    late_close = row(open_ms, close_ms=open_ms + 2 * MINUTE_MS - 1)

    forward = contract_outcome([early_close, late_close])
    reverse = contract_outcome([late_close, early_close])

    assert forward == (CandleConflictError, "MARKET_DATA_CONFLICT", 1, 0)

    # Reason code and both metrics are identical in either direction.
    assert reverse == forward


def test_genuine_open_time_disorder_remains_an_ordering_violation():
    earlier = row(CUTOFF_MS - 10 * MINUTE_MS)
    later = row(CUTOFF_MS - 9 * MINUTE_MS)

    assert contract_outcome([later, earlier]) == (
        CandleOrderingError,
        "MARKET_DATA_ORDERING",
        0,
        1,
    )


def test_ordering_authority_reads_open_time_only():
    """A descending close time alone is not a sequence defect."""

    first = CUTOFF_MS - 10 * MINUTE_MS
    second = first + MINUTE_MS

    processor = CandleProcessor()
    normalized = processor.normalize(
        [
            row(first, close_ms=first + 5 * MINUTE_MS),
            row(second, close_ms=second + MINUTE_MS),
        ],
        processing_cutoff=CUTOFF,
    )

    assert [item["open_time"] for item in normalized] == [first, second]
    assert processor.metrics["ordering_violations"] == 0


# ---------------------------------------------------------------------------
# Complete relevant payload conflict
#
# Legacy positions 0-10 are real market evidence and all take part in
# same-identity conflict detection. Position 11 is the Binance filler
# field: source inspection shows no market meaning for it, so it is
# excluded by decision and a difference there alone stays a duplicate.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, override",
    [
        ("quote_volume", {"quote_volume": "1001.0"}),
        ("trades", {"trades": 26}),
        ("taker_buy_base_volume", {"taker_buy_base_volume": "4.5"}),
        ("taker_buy_quote_volume", {"taker_buy_quote_volume": "401.0"}),
    ],
)
def test_metadata_disagreement_is_a_conflict_in_both_orders(
    field: str, override: dict[str, Any]
):
    open_ms = CUTOFF_MS - 10 * MINUTE_MS
    baseline = row(open_ms)
    variant = row(open_ms, **override)

    assert baseline != variant, f"the {field} fixture does not differ"

    forward = contract_outcome([baseline, variant])
    reverse = contract_outcome([variant, baseline])

    assert forward == (CandleConflictError, "MARKET_DATA_CONFLICT", 1, 0)
    assert reverse == forward


def test_every_evidence_position_participates_in_conflict_detection():
    """Positions 1-10 are evidence. Changing any one is a conflict.

    Position 0 is excluded because it is the identity itself: a
    different open time is a different candle, not a conflicting
    statement about the same one.
    """

    open_ms = CUTOFF_MS - 10 * MINUTE_MS
    baseline = row(open_ms)

    mutations: dict[int, Any] = {
        1: "101.0",
        2: "111.0",
        3: "91.0",
        4: "106.0",
        5: "11.0",
        6: baseline[6] + 1,
        7: "1001.0",
        8: 26,
        9: "4.5",
        10: "401.0",
    }

    for index, value in mutations.items():
        variant = list(baseline)
        variant[index] = value

        outcome = contract_outcome([list(baseline), variant])

        assert outcome[1] == "MARKET_DATA_CONFLICT", (
            f"legacy position {index} does not participate in "
            "same-identity conflict detection"
        )


def test_fully_identical_rows_collapse_to_one_candle():
    open_ms = CUTOFF_MS - 10 * MINUTE_MS
    processor = CandleProcessor()

    normalized = processor.normalize(
        [row(open_ms), row(open_ms)],
        processing_cutoff=CUTOFF,
    )

    assert len(normalized) == 1
    assert processor.metrics["duplicates_removed"] == 1
    assert processor.metrics["conflicts_detected"] == 0
    assert processor.metrics["ordering_violations"] == 0


def test_binance_ignore_field_alone_is_still_a_duplicate():
    """Documented exclusion: index 11 carries no market meaning."""

    open_ms = CUTOFF_MS - 10 * MINUTE_MS
    processor = CandleProcessor()

    normalized = processor.normalize(
        [row(open_ms, ignore="0"), row(open_ms, ignore="17928899.62")],
        processing_cutoff=CUTOFF,
    )

    assert len(normalized) == 1
    assert processor.metrics["duplicates_removed"] == 1
    assert processor.metrics["conflicts_detected"] == 0


def test_carried_metadata_is_not_promoted_to_an_analyzer_input():
    """The four values exist for conflict detection, nothing more."""

    normalized = CandleProcessor().normalize(
        [row(CUTOFF_MS - 10 * MINUTE_MS)],
        processing_cutoff=CUTOFF,
    )

    assert normalized[0]["provider_metadata"] == {
        "quote_volume": 1000.0,
        "trades": 25,
        "taker_buy_base_volume": 4.0,
        "taker_buy_quote_volume": 400.0,
    }

    for promoted in (
        "quote_volume",
        "trades",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
    ):
        assert promoted not in normalized[0]


def test_absent_metadata_is_preserved_as_absent_not_zero():
    """A short row is missing evidence; it does not gain a zero."""

    open_ms = CUTOFF_MS - 10 * MINUTE_MS
    short = row(open_ms)[:7]

    normalized = CandleProcessor().normalize([short], processing_cutoff=CUTOFF)

    assert normalized[0]["provider_metadata"] == {
        "quote_volume": None,
        "trades": None,
        "taker_buy_base_volume": None,
        "taker_buy_quote_volume": None,
    }


# ---------------------------------------------------------------------------
# 6-8. Single clock authority
# ---------------------------------------------------------------------------


def test_one_explicit_cutoff_controls_closure():
    open_ms = CUTOFF_MS - 10 * MINUTE_MS
    candles = [row(open_ms)]

    before = CandleProcessor().normalize(
        candles,
        processing_cutoff=open_ms,
    )
    after = CandleProcessor().normalize(
        candles,
        processing_cutoff=CUTOFF,
    )

    assert before[0]["is_closed"] is False
    assert after[0]["is_closed"] is True


def test_same_row_and_cutoff_always_produce_the_same_closure():
    candles = historical_rows(5)

    first = CandleProcessor().normalize(candles, processing_cutoff=CUTOFF)
    second = CandleProcessor().normalize(candles, processing_cutoff=CUTOFF)

    assert first == second


def test_closure_ignores_the_wall_clock_entirely():
    """A candle far in the real future is CLOSED at a later cutoff.

    Only a cutoff-driven implementation can produce this. A wall-clock
    read would classify it as still open.
    """

    open_time = datetime.now(UTC) + timedelta(days=10)
    open_ms = int(open_time.timestamp() * 1000)
    cutoff_ms = open_ms + 10 * MINUTE_MS

    normalized = CandleProcessor().normalize(
        [row(open_ms)],
        processing_cutoff=cutoff_ms,
    )

    assert normalized[0]["is_closed"] is True


def test_no_clock_authority_below_market_loop():
    clock_calls = {
        "time.time",
        "time.monotonic",
        "time.perf_counter",
        "datetime.now",
        "datetime.utcnow",
        "utc_now",
        "now",
        "utcnow",
    }

    for relative_path in (
        "core/candle_processor.py",
        "atlas_finance/market_data/temporal.py",
    ):
        calls = called_names(REPOSITORY_ROOT / relative_path)
        assert not (calls & clock_calls), (
            f"{relative_path} reads a clock: {sorted(calls & clock_calls)}"
        )
        assert "import time" not in (
            REPOSITORY_ROOT / relative_path
        ).read_text(encoding="utf-8-sig")


def test_market_loop_reads_the_processing_clock_once_per_cycle():
    reads: list[int] = []
    seen: list[datetime] = []

    class RecordingLoop(MarketLoop):
        @staticmethod
        def _processing_cutoff() -> datetime:
            reads.append(1)
            return CUTOFF

        def process_symbol(self, symbol, *, processing_cutoff=None):
            seen.append(processing_cutoff)
            return None

    loop = RecordingLoop(
        brain=object(),
        market_feed=object(),
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    )
    loop.running = True
    loop.run_cycle()

    assert len(reads) == 1
    assert seen == [CUTOFF, CUTOFF, CUTOFF]


def test_normalize_requires_an_explicit_cutoff():
    processor = CandleProcessor()

    with pytest.raises(TypeError):
        processor.normalize(historical_rows(2))

    with pytest.raises(ValueError, match="processing_cutoff is required"):
        processor.normalize(historical_rows(2), processing_cutoff=None)


# ---------------------------------------------------------------------------
# 9-12. Future data policy
# ---------------------------------------------------------------------------


def test_close_time_exactly_at_the_cutoff_is_closed():
    open_ms = CUTOFF_MS - MINUTE_MS

    normalized = CandleProcessor().normalize(
        [row(open_ms, close_ms=CUTOFF_MS)],
        processing_cutoff=CUTOFF,
    )

    assert normalized[0]["is_closed"] is True
    assert is_closed_at(CUTOFF_MS, CUTOFF_MS) is True


def test_currently_open_candle_is_accepted_but_not_closed():
    """open <= cutoff < close is the normal live exchange candle."""

    open_ms = CUTOFF_MS - MINUTE_MS

    normalized = CandleProcessor().normalize(
        [row(open_ms, close_ms=CUTOFF_MS + MINUTE_MS)],
        processing_cutoff=CUTOFF,
    )

    assert len(normalized) == 1
    assert normalized[0]["is_closed"] is False
    assert CandleProcessor.closed_candles(normalized) == []


def test_future_open_time_fails_closed():
    processor = CandleProcessor()
    open_ms = CUTOFF_MS + MINUTE_MS

    normalized = processor.normalize([row(open_ms)], processing_cutoff=CUTOFF)

    assert normalized == []
    assert processor.metrics["future_candles_rejected"] == 1
    assert is_future_open_at(open_ms, CUTOFF_MS) is True


def test_close_time_before_open_time_fails_closed():
    processor = CandleProcessor()
    open_ms = CUTOFF_MS - MINUTE_MS

    normalized = processor.normalize(
        [row(open_ms, close_ms=open_ms - 1)],
        processing_cutoff=CUTOFF,
    )

    assert normalized == []
    assert processor.metrics["invalid_time_range_rejected"] == 1


# ---------------------------------------------------------------------------
# 13-15. Normalization
# ---------------------------------------------------------------------------


def test_aware_non_utc_datetime_normalizes_to_utc():
    tokyo = timezone(timedelta(hours=9))
    value = datetime(2026, 3, 1, 21, 0, tzinfo=tokyo)

    normalized = require_aware_utc(value)

    assert normalized.tzinfo is UTC
    assert normalized == datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    assert to_milliseconds(value) == to_milliseconds(normalized)


def test_naive_datetime_is_rejected():
    with pytest.raises(TemporalContractError, match="timezone-aware"):
        require_aware_utc(datetime(2026, 3, 1, 12, 0))

    with pytest.raises(TemporalContractError):
        to_milliseconds(datetime(2026, 3, 1, 12, 0))

    # A naive local reading can never enter the market-data path.
    with pytest.raises(TemporalContractError):
        require_aware_utc(datetime.now())


def test_naive_datetime_in_a_candle_is_rejected_not_interpreted():
    processor = CandleProcessor()

    normalized = processor.normalize(
        [
            {
                "open_time": datetime(2026, 2, 1, 12, 0),
                "close_time": datetime(2026, 2, 1, 12, 1),
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": 105.0,
                "volume": 10.0,
            }
        ],
        processing_cutoff=CUTOFF,
    )

    assert normalized == []
    assert processor.metrics["candles_rejected"] == 1


def test_host_timezone_cannot_change_a_normalized_timestamp():
    instant = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    equivalents = [
        instant,
        instant.astimezone(timezone(timedelta(hours=9))),
        instant.astimezone(timezone(timedelta(hours=-5))),
        instant.astimezone(timezone(timedelta(minutes=330))),
    ]

    values = {to_milliseconds(value) for value in equivalents}

    assert values == {1772366400000}


# ---------------------------------------------------------------------------
# 16-19. Provider metadata
# ---------------------------------------------------------------------------


def test_real_provider_metadata_keys_reach_the_legacy_row():
    provider = StubProvider(
        (
            candle(
                open_time=datetime(2026, 2, 1, 12, 0, tzinfo=UTC),
                close_time=datetime(2026, 2, 1, 12, 4, 59, tzinfo=UTC),
            ),
        )
    )
    feed = started_feed(provider)

    try:
        rows = feed.candles("BTCUSDT", interval="5m", limit=1)
    finally:
        feed.stop()

    assert rows[0][7] == "8125000.0"
    assert rows[0][8] == 1500
    assert rows[0][9] == "60.0"
    assert rows[0][10] == "3900000.0"


def test_provider_metadata_contract_matches_the_adapter():
    """The adapter must read the keys the real provider writes."""

    provider_source = (
        REPOSITORY_ROOT / "atlas_finance/market_data/binance_public_provider.py"
    ).read_text(encoding="utf-8-sig")
    adapter_source = (REPOSITORY_ROOT / "exchange/market_feed.py").read_text(
        encoding="utf-8-sig"
    )

    for key in ("quote_volume", "trades"):
        assert f'"{key}"' in provider_source
        assert f'"{key}"' in adapter_source

    for invented in ("quote_asset_volume", "number_of_trades"):
        assert f'"{invented}"' not in adapter_source


@pytest.mark.parametrize("missing", ["quote_volume", "trades"])
def test_missing_metadata_is_not_converted_to_zero(missing: str):
    metadata = {
        "quote_volume": 8125000.0,
        "trades": 1500,
        "taker_buy_base_volume": 60.0,
        "taker_buy_quote_volume": 3900000.0,
    }
    metadata[missing] = None

    provider = StubProvider(
        (
            candle(
                open_time=datetime(2026, 2, 1, 12, 0, tzinfo=UTC),
                close_time=datetime(2026, 2, 1, 12, 4, 59, tzinfo=UTC),
                metadata=metadata,
            ),
        )
    )
    feed = started_feed(provider)

    try:
        with pytest.raises(InvalidCandleError, match=missing):
            feed.candles("BTCUSDT", interval="5m", limit=1)
    finally:
        feed.stop()


def test_absent_metadata_key_also_fails_closed():
    provider = StubProvider(
        (
            candle(
                open_time=datetime(2026, 2, 1, 12, 0, tzinfo=UTC),
                close_time=datetime(2026, 2, 1, 12, 4, 59, tzinfo=UTC),
                metadata={"taker_buy_base_volume": 60.0},
            ),
        )
    )
    feed = started_feed(provider)

    try:
        with pytest.raises(InvalidCandleError):
            feed.candles("BTCUSDT", interval="5m", limit=1)
    finally:
        feed.stop()


# ---------------------------------------------------------------------------
# Binance provider minimum-width contract
#
# The legacy adapter truthfully requires positions 7-10, so the
# provider must only emit candles that can supply them. A narrower
# kline is incomplete market data, not an array to pad.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("columns", [12, 11])
def test_provider_accepts_klines_that_carry_every_evidence_column(columns: int):
    candles = provider_candles([binance_kline(columns)])

    assert len(candles) == 1
    assert candles[0].metadata == {
        "quote_volume": 1050.0,
        "trades": 308,
        "taker_buy_base_volume": 4.0,
        "taker_buy_quote_volume": 420.0,
    }


@pytest.mark.parametrize("columns", [10, 9, 7, 6])
def test_provider_rejects_klines_that_cannot_supply_metadata(columns: int):
    with pytest.raises(InvalidCandleError) as failure:
        provider_candles([binance_kline(columns)])

    # The rejection must come from the declared width contract. A
    # parser that stumbled into an IndexError further down would also
    # raise here, and that is not the same guarantee.
    message = str(failure.value)
    assert "incomplete" in message
    assert f"{columns} columns received" in message
    assert "11 required" in message


def test_provider_never_emits_a_candle_with_absent_metadata():
    """An unreadable value is rejected, never downgraded to None."""

    for position, field in (
        (7, "quote_volume"),
        (8, "trades"),
        (9, "taker_buy_base_volume"),
        (10, "taker_buy_quote_volume"),
    ):
        broken = binance_kline()
        broken[position] = None

        with pytest.raises(InvalidCandleError, match=field):
            provider_candles([broken])

    accepted = provider_candles([binance_kline()])
    assert None not in accepted[0].metadata.values()


@pytest.mark.parametrize("columns", [12, 11])
def test_provider_output_always_converts_to_a_legacy_row(columns: int):
    """Provider -> adapter needs no fabrication under the contract."""

    source = binance_kline(columns)
    candles = provider_candles([source])

    legacy = MarketFeed._to_legacy_candle_row(candles[0])

    assert len(legacy) == 12
    assert float(legacy[7]) == float(source[7])
    assert legacy[8] == source[8]
    assert float(legacy[9]) == float(source[9])
    assert float(legacy[10]) == float(source[10])


def test_provider_metadata_survives_into_conflict_detection():
    """The full chain keeps trade count as conflict evidence."""

    candles = provider_candles([binance_kline()])
    legacy = MarketFeed._to_legacy_candle_row(candles[0])

    disagreeing = list(legacy)
    disagreeing[8] = legacy[8] + 1

    processor = CandleProcessor()

    with pytest.raises(CandleConflictError):
        processor.normalize([legacy, disagreeing], processing_cutoff=CUTOFF)

    assert processor.metrics["conflicts_detected"] == 1
    assert processor.metrics["ordering_violations"] == 0


# ---------------------------------------------------------------------------
# 20. Provider .closed is advisory only
# ---------------------------------------------------------------------------


def test_provider_closed_flag_is_not_runtime_decision_authority():
    """A provider claiming closed=True cannot make a candle eligible."""

    open_time = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
    close_time = datetime(2026, 2, 1, 12, 5, tzinfo=UTC)

    advisory = candle(
        open_time=open_time,
        close_time=close_time,
        closed=True,
    )
    provider = StubProvider((advisory,))
    feed = started_feed(provider)

    try:
        rows = feed.candles("BTCUSDT", interval="5m", limit=1)
    finally:
        feed.stop()

    # The provider really does claim the candle is closed.
    assert advisory.closed is True

    cutoff = open_time + timedelta(minutes=1)
    normalized = CandleProcessor().normalize(rows, processing_cutoff=cutoff)

    assert normalized[0]["is_closed"] is False
    assert CandleProcessor.closed_candles(normalized) == []

    # The inverse: an advisory closed=False cannot hide a closed candle.
    later = CandleProcessor().normalize(rows, processing_cutoff=close_time)
    assert later[0]["is_closed"] is True


def test_no_runtime_module_consumes_market_candle_closed():
    declared = json.loads(
        (REPOSITORY_ROOT / "packaging/atlas_runtime_closure.json").read_text(
            encoding="utf-8"
        )
    )["modules"]

    # models.py defines and serializes the field; the provider is
    # allowed to populate it. Neither decides runtime eligibility.
    authors = {
        "atlas_finance/market_data/models.py",
        "atlas_finance/market_data/binance_public_provider.py",
    }

    offenders = [
        relative_path
        for relative_path in declared
        if relative_path not in authors
        and (REPOSITORY_ROOT / relative_path).exists()
        and foreign_attribute_reads(REPOSITORY_ROOT / relative_path, "closed")
    ]

    assert offenders == [], (
        f"runtime modules read MarketCandle.closed: {offenders}"
    )

    # The guard must actually be capable of catching a violation.
    assert foreign_attribute_reads(
        Path(__file__), "closed"
    ), "the detector no longer detects a foreign .closed read"


# ---------------------------------------------------------------------------
# 21-22. Legacy compatibility
# ---------------------------------------------------------------------------


def test_legacy_row_shape_is_unchanged():
    provider = StubProvider(
        (
            candle(
                open_time=datetime(2026, 2, 1, 12, 0, tzinfo=UTC),
                close_time=datetime(2026, 2, 1, 12, 4, 59, tzinfo=UTC),
            ),
        )
    )
    feed = started_feed(provider)

    try:
        rows = feed.candles("BTCUSDT", interval="5m", limit=1)
    finally:
        feed.stop()

    assert len(rows[0]) == 12
    assert rows[0][0] == 1769947200000
    assert rows[0][6] == 1769947499000
    assert rows[0][1:6] == ["100.0", "110.0", "90.0", "105.0", "10.0"]
    assert rows[0][11] == "0"


def test_market_feed_public_api_remains_compatible():
    expected = {
        "start",
        "stop",
        "price",
        "candles",
        "get_price",
        "get_candles",
        "statistics",
        "market_feed_snapshot",
        "health",
    }

    assert expected <= {
        name for name in dir(MarketFeed) if not name.startswith("_")
    }
    assert isinstance(MarketFeed.connected, property)

    signature = inspect.signature(MarketFeed.candles)
    assert signature.parameters["interval"].default == "1m"
    assert signature.parameters["limit"].default == 500

    assert inspect.signature(MarketFeed.__init__).parameters[
        "exchange_name"
    ].default == "binance_global"


def test_candle_processor_helper_api_is_unchanged():
    for name in (
        "closed_candles",
        "latest_closed_candle",
        "latest_closed_identity",
        "latest_price",
        "latest_closed_price",
        "candle_count",
        "candle_identity",
        "health",
    ):
        assert callable(getattr(CandleProcessor, name))


# ---------------------------------------------------------------------------
# 23-25. Safety authorities
# ---------------------------------------------------------------------------


def test_paper_default_and_live_denial_are_unchanged():
    from core.execution_manager import ExecutionManager
    from core.execution_models import normalize_mode

    parameters = inspect.signature(ExecutionManager.__init__).parameters

    assert ExecutionManager.MODE_PAPER == "PAPER"
    assert parameters["mode"].default == "PAPER"
    assert parameters["live_execution_enabled"].default is False
    assert normalize_mode(None) == "PAPER"


def test_market_data_path_grants_no_execution_authority():
    for relative_path in (
        "atlas_finance/market_data/temporal.py",
        "core/candle_processor.py",
        "exchange/market_feed.py",
    ):
        source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8-sig")
        for forbidden in (
            "ExecutionManager",
            "PaperTrader",
            "place_order",
            "submit_order",
            "CapabilityGateway",
        ):
            assert forbidden not in source, (
                f"{relative_path} references {forbidden}"
            )


def test_third_evidence_provider_interlock_remains_gated():
    from ai.core.intelligence.agent_fusion import AgentFusion
    from analysis.world_analysis_engine import WorldAnalysisEngine

    assert AgentFusion.MIN_PARTICIPATING_AGENTS == 3

    engine = WorldAnalysisEngine()
    assert not hasattr(engine, "model_gateway")
    assert not hasattr(engine, "tool_gateway")


# ---------------------------------------------------------------------------
# 26-27. Package-1 and Package-2 regression
# ---------------------------------------------------------------------------


def test_package_1_and_2_classification_is_untouched():
    architecture_map = json.loads(
        (REPOSITORY_ROOT / "packaging/atlas_architecture_map.json").read_text(
            encoding="utf-8"
        )
    )
    rules = {rule["pattern"]: rule["layer"] for rule in architecture_map["layer_rules"]}

    assert rules["data_layer/market_data_models.py"] == "L1"
    assert rules["data_layer/market_data_contracts.py"] == "L1"
    assert rules["data_layer/market_data_migrations.py"] == "L2"
    assert rules["data_layer/market_data_sqlite.py"] == "L2"


def test_package_1_and_2_modules_stay_unwired():
    declared = set(
        json.loads(
            (REPOSITORY_ROOT / "packaging/atlas_runtime_closure.json").read_text(
                encoding="utf-8"
            )
        )["modules"]
    )

    for relative_path in (
        "data_layer/market_data_models.py",
        "data_layer/market_data_contracts.py",
        "data_layer/market_data_migrations.py",
        "data_layer/market_data_sqlite.py",
    ):
        assert relative_path not in declared

    assert "atlas_finance/market_data/temporal.py" in declared


def test_package_3_temporal_module_is_pure():
    """The new runtime leaf must stay stdlib-only with no I/O."""

    tree = ast.parse(
        (REPOSITORY_ROOT / "atlas_finance/market_data/temporal.py").read_text(
            encoding="utf-8-sig"
        )
    )

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= {"__future__", "datetime"}


def test_contract_errors_expose_bounded_reasons():
    assert CandleConflictError.reason == "MARKET_DATA_CONFLICT"
    assert CandleOrderingError.reason == "MARKET_DATA_ORDERING"
    assert issubclass(CandleConflictError, CandleContractError)
    assert issubclass(CandleOrderingError, CandleContractError)
