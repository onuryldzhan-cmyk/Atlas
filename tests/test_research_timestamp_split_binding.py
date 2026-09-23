"""Contract and adversarial tests for P2: timestamp-bound purged splits.

Governance: registry v4.70, ``GRANT-COMPUTE-ENGINE-P2``. These tests pin:

(a) a clean, gap-free window binds to timestamps that match the index math
    of ``make_purged_split`` exactly;
(b) a window reproducing the real archive exactly, including the known gap
    P1 verified (BTCUSDT 1h, 2020-12-21 14:00 -> 17:00 UTC, 4 bars), passes
    when no gap touches a boundary, with every gap flagged rather than
    hidden -- and the same real gap is refused once a shifted window puts it
    on a boundary;
(c) a gap inside or against a purge, embargo or split boundary is refused,
    including cases where every index-only check -- the ``DataSplit``
    invariant and P1's own FLAGGED coverage status -- says the split is safe,
    and a concrete leak the naive grid-slot binding would commit;
(d) purge and embargo widths, once resolved to timestamps, are exact in
    wall-clock time, not just in index count.

Plus every fail-closed path, a no-fabricated-timestamp property, and the
architecture boundary (L3, no hypothesis-registry reference, no network, not
in the runtime closure).

Every test uses a real :class:`MarketDataSQLiteStorage` on pytest's
``tmp_path`` with synthetic, deterministic bars. Nothing here reads or writes
the real archive at ``C:\\AtlasState\\market_archive`` or any configured
durable root.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.research_market_data_bridge import (
    CoverageStatus,
    GapRange,
    ResearchMarketDataBridge,
    WindowBarAccessResult,
)
from core.research_timestamp_split_binding import (
    BarSequenceIntegrityError,
    BindingStatus,
    Boundary,
    CoverageRefusedError,
    GapStraddlesBoundaryError,
    ResearchTimestampSplitBinder,
    SplitShapeError,
    TimestampSplitBindingError,
    Zone,
    bind_split_to_timestamps,
)
from data_layer.market_data_archive_sqlite import (
    ArchivedBar,
    FetchBatch,
    MarketDataSQLiteStorage,
    timeframe_to_milliseconds,
)
from research.splitting import DataSplit, Segment, SplitError, SplitSpec, make_purged_split

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = "core/research_timestamp_split_binding.py"

SYMBOL = "BTCUSDT"
TIMEFRAME = "1h"
H = timeframe_to_milliseconds(TIMEFRAME)
FETCHED_AT = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)

# n = 100 real bars under SPEC: embargo = ceil(0.03 * 100) = 3, purge = 2,
# buffer = 5. Index layout:
#   TRAIN [0,55)  EMBARGO_TC [55,58)  PURGE_TC [58,60)  CALIBRATION [60,75)
#   EMBARGO_CT [75,78)  PURGE_CT [78,80)  TEST [80,100)
SPEC = SplitSpec(
    train_fraction=0.6,
    calibration_fraction=0.2,
    test_fraction=0.2,
    label_horizon_bars=2,
    embargo_pct=0.03,
)
N = 100


def make_bar(open_ms: int, timeframe: str = TIMEFRAME) -> ArchivedBar:
    width = timeframe_to_milliseconds(timeframe)
    return ArchivedBar(
        symbol=SYMBOL,
        timeframe=timeframe,
        open_time_ms=open_ms,
        close_time_ms=open_ms + width - 1,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
    )


def store(storage: MarketDataSQLiteStorage, opens_ms: list[int], timeframe: str = TIMEFRAME) -> None:
    storage.store_batch(
        FetchBatch(
            source="binance",
            endpoint="/api/v3/klines",
            provider_version="v1",
            symbol=SYMBOL,
            timeframe=timeframe,
            fetched_at=FETCHED_AT,
            bars=tuple(make_bar(o, timeframe) for o in opens_ms),
        )
    )


def dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def ms(value: datetime) -> int:
    return round(value.timestamp() * 1000)


def gapped_opens(n: int, gap_before_index: int, gap_slots: int, *, base_slot: int = 0) -> list[int]:
    """``n`` real hourly bars with ``gap_slots`` missing slots between real
    index ``gap_before_index - 1`` and ``gap_before_index``."""
    opens = []
    for i in range(n):
        slot = base_slot + i + (gap_slots if i >= gap_before_index else 0)
        opens.append(slot * H)
    return opens


@pytest.fixture
def storage(tmp_path: Path) -> MarketDataSQLiteStorage:
    store_ = MarketDataSQLiteStorage(tmp_path / "market_data.sqlite3")
    store_.open()
    yield store_
    store_.close()


@pytest.fixture
def bridge(storage: MarketDataSQLiteStorage) -> ResearchMarketDataBridge:
    return ResearchMarketDataBridge(storage)


@pytest.fixture
def binder(bridge: ResearchMarketDataBridge) -> ResearchTimestampSplitBinder:
    return ResearchTimestampSplitBinder(bridge)


def load(bridge: ResearchMarketDataBridge, opens: list[int], timeframe: str = TIMEFRAME) -> WindowBarAccessResult:
    return bridge.load_window(SYMBOL, timeframe, dt(opens[0]), dt(opens[-1]))


def assert_no_fabricated_timestamps(bound, opens: list[int]) -> None:
    """Every segment and buffer timestamp is exactly the real bar at its own
    index boundary: start is the open of the bar at ``start_index``; a
    non-empty end is the open of the bar at ``stop_index - 1`` plus one bar
    width; an empty buffer sits exactly at the open of the next real bar."""
    width = bound.interval_ms
    for segment in bound.segments:
        assert segment.start_ms == opens[segment.start_index]
        assert segment.end_ms == opens[segment.stop_index - 1] + width
    for buffer in bound.buffers:
        assert buffer.start_ms == opens[buffer.start_index]
        if buffer.bar_count:
            assert buffer.end_ms == opens[buffer.stop_index - 1] + width
        else:
            assert buffer.end_ms == buffer.start_ms == opens[buffer.stop_index]
    for separation, (earlier, later) in zip(
        bound.separations,
        ((bound.train, bound.calibration), (bound.calibration, bound.test)),
    ):
        assert separation.earlier_last_open_ms == opens[earlier.stop_index - 1]
        assert separation.later_first_open_ms == opens[later.start_index]


# --- (a) clean window --------------------------------------------------------


@pytest.mark.parametrize("base_slot", [0, 438_000])
def test_clean_window_matches_index_math_exactly(binder, storage, base_slot):
    opens = [(base_slot + i) * H for i in range(N)]
    store(storage, opens)

    bound = binder.bind(SYMBOL, TIMEFRAME, dt(opens[0]), dt(opens[-1]), SPEC)

    expected_split = make_purged_split(N, SPEC)
    assert bound.split == expected_split
    assert bound.status is BindingStatus.BOUND_CLEAN
    assert bound.coverage_status is CoverageStatus.COMPLETE
    assert bound.edge_gaps == ()

    origin = opens[0]
    for segment, index_segment in zip(bound.segments, expected_split.segments):
        assert segment.start_index == index_segment.start
        assert segment.stop_index == index_segment.stop
        assert segment.start_ms == origin + index_segment.start * H
        assert segment.end_ms == origin + index_segment.stop * H
        assert segment.interior_gaps == ()

    assert (bound.train.start_index, bound.train.stop_index) == (0, 55)
    assert (bound.calibration.start_index, bound.calibration.stop_index) == (60, 75)
    assert (bound.test.start_index, bound.test.stop_index) == (80, 100)
    layout = {b.zone: (b.start_index, b.stop_index, b.start_ms, b.end_ms) for b in bound.buffers}
    assert layout == {
        Zone.EMBARGO_TRAIN_CALIBRATION: (55, 58, origin + 55 * H, origin + 58 * H),
        Zone.PURGE_TRAIN_CALIBRATION: (58, 60, origin + 58 * H, origin + 60 * H),
        Zone.EMBARGO_CALIBRATION_TEST: (75, 78, origin + 75 * H, origin + 78 * H),
        Zone.PURGE_CALIBRATION_TEST: (78, 80, origin + 78 * H, origin + 80 * H),
    }
    assert_no_fabricated_timestamps(bound, opens)


def test_bind_split_to_timestamps_accepts_a_preloaded_window(bridge, storage):
    opens = [i * H for i in range(N)]
    store(storage, opens)
    access = load(bridge, opens)

    bound = bind_split_to_timestamps(make_purged_split(N, SPEC), access)

    assert bound.status is BindingStatus.BOUND_CLEAN
    assert bound.symbol == SYMBOL and bound.timeframe == TIMEFRAME
    assert (bound.window_start_ms, bound.window_end_ms) == (opens[0], opens[-1])


# --- (b) real known-gap geometry, not at a boundary ---------------------------


def test_real_known_btcusdt_gaps_inside_segments_pass_and_are_flagged(binder, storage):
    """Reproduces the real archive's BTCUSDT 1h window 2020-12-17 00:00 ->
    2020-12-26 23:00 UTC exactly, gap for gap. It holds the gap P1 verified
    (checkpoint 20260923T185339Z, Completed #8: 2020-12-21 14:00 -> 17:00,
    4 bars) and one more real gap (2020-12-25 02:00, 1 bar), both read
    read-only from the real archive in the P2 session. 240 slots - 5 = 235
    real bars: the first gap falls between real index 109 and 110, inside
    TRAIN [0, 136); the second between 189 and 190, inside TEST [188, 235).
    Neither touches a boundary, so the split binds -- with both flagged."""
    start = datetime(2020, 12, 17, 0, tzinfo=UTC)
    end = datetime(2020, 12, 26, 23, tzinfo=UTC)
    real_gaps = [
        (datetime(2020, 12, 21, 14, tzinfo=UTC), datetime(2020, 12, 21, 17, tzinfo=UTC)),
        (datetime(2020, 12, 25, 2, tzinfo=UTC), datetime(2020, 12, 25, 2, tzinfo=UTC)),
    ]
    hours = [start + timedelta(hours=k) for k in range(int((end - start).total_seconds() // 3600) + 1)]
    opens = [ms(h) for h in hours if not any(first <= h <= last for first, last in real_gaps)]
    assert len(opens) == 235
    store(storage, opens)
    spec = SplitSpec(0.6, 0.2, 0.2, label_horizon_bars=2, embargo_pct=0.01)

    bound = binder.bind(SYMBOL, TIMEFRAME, start, end, spec)

    assert bound.coverage_status is CoverageStatus.GAPS_PRESENT_FLAGGED
    assert bound.status is BindingStatus.BOUND_WITH_FLAGGED_GAPS
    assert (bound.train.start_index, bound.train.stop_index) == (0, 136)
    assert (bound.test.start_index, bound.test.stop_index) == (188, 235)
    (first, last), (second, _) = real_gaps
    assert bound.train.interior_gaps == (GapRange(ms(first), ms(last), 4),)
    assert bound.calibration.interior_gaps == ()
    assert bound.test.interior_gaps == (GapRange(ms(second), ms(second), 1),)
    # Each flagged gap is inside its segment's reported wall-clock span, not hidden.
    assert bound.train.wall_clock_span_ms == (136 + 4) * H
    assert bound.train.end_ms == ms(start) + 140 * H
    assert bound.test.wall_clock_span_ms == (47 + 1) * H
    # Boundaries are untouched by either gap and exact.
    for separation in bound.separations:
        assert separation.separation_ms == (separation.buffer_bars + 1) * H
    assert_no_fabricated_timestamps(bound, opens)


def test_the_same_real_gap_is_refused_once_the_window_puts_it_on_a_boundary(binder, storage):
    """Same real 2020-12-21 gap, window shifted 26 hours earlier
    (2020-12-15 22:00 -> 2020-12-25 21:00, one of the real windows the P2
    session found refused against the real archive): the gap now sits
    between the last TRAIN bar and the first embargo bar."""
    start = datetime(2020, 12, 15, 22, tzinfo=UTC)
    end = datetime(2020, 12, 25, 21, tzinfo=UTC)
    gap_first = datetime(2020, 12, 21, 14, tzinfo=UTC)
    gap_last = datetime(2020, 12, 21, 17, tzinfo=UTC)
    other_real_gap = datetime(2020, 12, 25, 2, tzinfo=UTC)  # inside TEST here
    hours = [start + timedelta(hours=k) for k in range(int((end - start).total_seconds() // 3600) + 1)]
    opens = [
        ms(h) for h in hours if not gap_first <= h <= gap_last and h != other_real_gap
    ]
    assert len(opens) == 235
    store(storage, opens)
    spec = SplitSpec(0.6, 0.2, 0.2, label_horizon_bars=2, embargo_pct=0.01)

    with pytest.raises(GapStraddlesBoundaryError) as excinfo:
        binder.bind(SYMBOL, TIMEFRAME, start, end, spec)

    (violation,) = excinfo.value.violations
    assert (violation.before_zone, violation.after_zone) == (
        Zone.TRAIN, Zone.EMBARGO_TRAIN_CALIBRATION,
    )
    assert violation.gap == GapRange(ms(gap_first), ms(gap_last), 4)
    assert violation.after_index == 136


@pytest.mark.parametrize(
    ("gap_before_index", "zone"),
    [(1, Zone.TRAIN), (30, Zone.TRAIN), (54, Zone.TRAIN), (61, Zone.CALIBRATION),
     (74, Zone.CALIBRATION), (81, Zone.TEST), (99, Zone.TEST)],
)
def test_gap_strictly_inside_a_segment_body_passes(bridge, storage, gap_before_index, zone):
    opens = gapped_opens(N, gap_before_index, gap_slots=4)
    store(storage, opens)

    bound = bind_split_to_timestamps(make_purged_split(N, SPEC), load(bridge, opens))

    assert bound.status is BindingStatus.BOUND_WITH_FLAGGED_GAPS
    segment = {s.zone: s for s in bound.segments}[zone]
    assert len(segment.interior_gaps) == 1
    assert segment.interior_gaps[0].missing_bars == 4
    assert segment.wall_clock_span_ms == (segment.bar_count + 4) * H
    for buffer in bound.buffers:
        assert buffer.wall_clock_span_ms == buffer.bar_count * H


# --- (c) gaps at or inside a boundary are refused ------------------------------


STRADDLE_CASES = [
    # gap between real index (p-1) and p
    (55, Zone.TRAIN, Zone.EMBARGO_TRAIN_CALIBRATION, Boundary.TRAIN_CALIBRATION),
    (56, Zone.EMBARGO_TRAIN_CALIBRATION, Zone.EMBARGO_TRAIN_CALIBRATION, Boundary.TRAIN_CALIBRATION),
    (58, Zone.EMBARGO_TRAIN_CALIBRATION, Zone.PURGE_TRAIN_CALIBRATION, Boundary.TRAIN_CALIBRATION),
    (59, Zone.PURGE_TRAIN_CALIBRATION, Zone.PURGE_TRAIN_CALIBRATION, Boundary.TRAIN_CALIBRATION),
    (60, Zone.PURGE_TRAIN_CALIBRATION, Zone.CALIBRATION, Boundary.TRAIN_CALIBRATION),
    (75, Zone.CALIBRATION, Zone.EMBARGO_CALIBRATION_TEST, Boundary.CALIBRATION_TEST),
    (77, Zone.EMBARGO_CALIBRATION_TEST, Zone.EMBARGO_CALIBRATION_TEST, Boundary.CALIBRATION_TEST),
    (78, Zone.EMBARGO_CALIBRATION_TEST, Zone.PURGE_CALIBRATION_TEST, Boundary.CALIBRATION_TEST),
    (79, Zone.PURGE_CALIBRATION_TEST, Zone.PURGE_CALIBRATION_TEST, Boundary.CALIBRATION_TEST),
    (80, Zone.PURGE_CALIBRATION_TEST, Zone.TEST, Boundary.CALIBRATION_TEST),
]


@pytest.mark.parametrize(("gap_before_index", "before", "after", "boundary"), STRADDLE_CASES)
@pytest.mark.parametrize("gap_slots", [1, 7])
def test_gap_touching_a_purge_embargo_or_split_boundary_is_refused_although_index_checks_pass(
    bridge, storage, gap_before_index, before, after, boundary, gap_slots
):
    opens = gapped_opens(N, gap_before_index, gap_slots)
    store(storage, opens)
    access = load(bridge, opens)
    split = make_purged_split(N, SPEC)

    # Everything an index-only caller could check says "safe":
    assert access.coverage.status is CoverageStatus.GAPS_PRESENT_FLAGGED  # P1 accepts it
    assert split.train_calibration_gap == split.purged_bars + split.embargo_bars
    assert split.calibration_test_gap == split.purged_bars + split.embargo_bars
    DataSplit(  # the splitter's own invariant re-validates without complaint
        train=split.train, calibration=split.calibration, test=split.test,
        n_observations=split.n_observations, spec=split.spec,
        purged_bars=split.purged_bars, embargo_bars=split.embargo_bars,
    )

    with pytest.raises(GapStraddlesBoundaryError) as excinfo:
        bind_split_to_timestamps(split, access)

    (violation,) = excinfo.value.violations
    assert (violation.before_zone, violation.after_zone) == (before, after)
    assert violation.boundary is boundary
    assert violation.after_index == gap_before_index
    assert violation.gap.missing_bars == gap_slots


def test_embargo_containing_a_gap_would_span_more_wall_clock_than_declared(bridge, storage):
    """The index view claims the train/calibration separation is 6 bars = 6h;
    in wall-clock time it is 6h plus the gap. Binding refuses rather than
    reporting a separation the sealed spec never declared."""
    gap_slots = 5
    opens = gapped_opens(N, 56, gap_slots)
    store(storage, opens)
    split = make_purged_split(N, SPEC)

    index_separation_bars = split.calibration.start - (split.train.stop - 1)
    wall_clock_separation = opens[split.calibration.start] - opens[split.train.stop - 1]
    assert index_separation_bars * H == 6 * H
    assert wall_clock_separation == (6 + gap_slots) * H  # 11h, not the declared 6h

    with pytest.raises(GapStraddlesBoundaryError):
        bind_split_to_timestamps(split, load(bridge, opens))


def test_naive_grid_slot_binding_leaks_across_a_gap_and_p2_refuses_it(bridge, storage):
    """The concrete leak index-only reasoning misses.

    Grid slots 0..99 are requested; slots 55..59 -- exactly the
    train/calibration buffer -- are missing. A naive caller splits the 100
    grid slots and maps index -> slot. The DataSplit invariant holds, yet a
    label taken ``label_horizon_bars`` observations ahead of the last real
    train bar lands inside CALIBRATION: the purge removed empty slots, not the
    leaking observations. P2 refuses both the naive grid split and the honest
    real-bar split of the same window.
    """
    missing = set(range(55, 60))
    opens = [slot * H for slot in range(100) if slot not in missing]
    store(storage, opens)
    access = bridge.load_window(SYMBOL, TIMEFRAME, dt(0), dt(99 * H))
    assert access.coverage.expected_count == 100
    assert access.coverage.actual_count == 95
    assert access.coverage.status is CoverageStatus.GAPS_PRESENT_FLAGGED

    naive = make_purged_split(access.coverage.expected_count, SPEC)  # valid DataSplit
    last_train_slot = naive.train.stop - 1  # slot 54, a real bar
    real_opens = [bar.open_time_ms for bar in access.bars]
    label_end_open = real_opens[real_opens.index(last_train_slot * H) + SPEC.label_horizon_bars]
    calibration_start_ms = naive.calibration.start * H
    calibration_stop_ms = naive.calibration.stop * H
    assert calibration_start_ms <= label_end_open < calibration_stop_ms  # the leak

    with pytest.raises(SplitShapeError, match="grid slots"):
        bind_split_to_timestamps(naive, access)

    honest = make_purged_split(access.coverage.actual_count, SPEC)
    with pytest.raises(GapStraddlesBoundaryError) as excinfo:
        bind_split_to_timestamps(honest, access)
    assert excinfo.value.violations[0].boundary is Boundary.TRAIN_CALIBRATION


def test_zero_purge_zero_embargo_gap_directly_between_segments_is_refused(bridge, storage):
    spec = SplitSpec(0.6, 0.2, 0.2, label_horizon_bars=0, embargo_pct=0.0)
    split = make_purged_split(N, spec)
    assert split.train.stop == split.calibration.start == 60
    opens = gapped_opens(N, 60, gap_slots=3)
    store(storage, opens)

    with pytest.raises(GapStraddlesBoundaryError) as excinfo:
        bind_split_to_timestamps(split, load(bridge, opens))

    (violation,) = excinfo.value.violations
    assert (violation.before_zone, violation.after_zone) == (Zone.TRAIN, Zone.CALIBRATION)


def test_zero_purge_zero_embargo_clean_window_has_empty_exact_buffers(bridge, storage):
    spec = SplitSpec(0.6, 0.2, 0.2, label_horizon_bars=0, embargo_pct=0.0)
    opens = [i * H for i in range(N)]
    store(storage, opens)

    bound = bind_split_to_timestamps(make_purged_split(N, spec), load(bridge, opens))

    for buffer in bound.buffers:
        assert buffer.bar_count == 0 and buffer.wall_clock_span_ms == 0
    assert bound.buffer(Zone.PURGE_TRAIN_CALIBRATION).start_ms == 60 * H
    for separation in bound.separations:
        assert separation.separation_ms == H


def test_every_violation_is_reported_not_just_the_first(bridge, storage):
    opens = gapped_opens(N, 59, gap_slots=2)
    second_gap_index, second_gap_slots = 77, 3
    opens = [o + (second_gap_slots * H if i >= second_gap_index else 0) for i, o in enumerate(opens)]
    store(storage, opens)

    with pytest.raises(GapStraddlesBoundaryError) as excinfo:
        bind_split_to_timestamps(make_purged_split(N, SPEC), load(bridge, opens))

    boundaries = [v.boundary for v in excinfo.value.violations]
    assert boundaries == [Boundary.TRAIN_CALIBRATION, Boundary.CALIBRATION_TEST]
    assert "PURGE_TRAIN_CALIBRATION" in str(excinfo.value)
    assert "EMBARGO_CALIBRATION_TEST" in str(excinfo.value)


def test_binder_refuses_a_boundary_gap_end_to_end(binder, storage):
    opens = gapped_opens(N, 60, gap_slots=2)
    store(storage, opens)

    with pytest.raises(GapStraddlesBoundaryError):
        binder.bind(SYMBOL, TIMEFRAME, dt(opens[0]), dt(opens[-1]), SPEC)


# --- (d) wall-clock widths ------------------------------------------------------


@pytest.mark.parametrize("timeframe", ["1m", "15m", "1h", "4h", "1d"])
def test_purge_and_embargo_widths_are_exact_in_wall_clock_time(binder, storage, timeframe):
    width = timeframe_to_milliseconds(timeframe)
    base = 1_600_000_000_000 // width * width
    opens = [base + i * width for i in range(N)]
    store(storage, opens, timeframe)
    spec = SplitSpec(0.6, 0.2, 0.2, label_horizon_bars=4, embargo_pct=0.02)

    bound = binder.bind(SYMBOL, timeframe, dt(opens[0]), dt(opens[-1]), spec)

    assert bound.interval_ms == width
    assert bound.split.purged_bars == 4 and bound.split.embargo_bars == 2
    assert bound.purge_wall_clock_ms == 4 * width
    assert bound.embargo_wall_clock_ms == 2 * width
    for zone in (Zone.PURGE_TRAIN_CALIBRATION, Zone.PURGE_CALIBRATION_TEST):
        assert bound.buffer(zone).wall_clock_span_ms == bound.purge_wall_clock_ms
    for zone in (Zone.EMBARGO_TRAIN_CALIBRATION, Zone.EMBARGO_CALIBRATION_TEST):
        assert bound.buffer(zone).wall_clock_span_ms == bound.embargo_wall_clock_ms
    # Buffers tile the space between segments with no hole and no overlap.
    tc = [bound.buffer(Zone.EMBARGO_TRAIN_CALIBRATION), bound.buffer(Zone.PURGE_TRAIN_CALIBRATION)]
    assert bound.train.end_ms == tc[0].start_ms
    assert tc[0].end_ms == tc[1].start_ms
    assert tc[1].end_ms == bound.calibration.start_ms
    ct = [bound.buffer(Zone.EMBARGO_CALIBRATION_TEST), bound.buffer(Zone.PURGE_CALIBRATION_TEST)]
    assert bound.calibration.end_ms == ct[0].start_ms
    assert ct[0].end_ms == ct[1].start_ms
    assert ct[1].end_ms == bound.test.start_ms
    for separation in bound.separations:
        assert separation.buffer_bars == 6
        assert separation.separation_ms == 7 * width
    for segment in bound.segments:
        assert segment.wall_clock_span_ms == segment.bar_count * width
    assert_no_fabricated_timestamps(bound, opens)


def test_buffers_stay_exact_when_an_interior_gap_is_present(bridge, storage):
    opens = gapped_opens(N, 20, gap_slots=9)
    store(storage, opens)

    bound = bind_split_to_timestamps(make_purged_split(N, SPEC), load(bridge, opens))

    assert bound.train.wall_clock_span_ms == (55 + 9) * H
    assert bound.buffer(Zone.EMBARGO_TRAIN_CALIBRATION).wall_clock_span_ms == 3 * H
    assert bound.buffer(Zone.PURGE_TRAIN_CALIBRATION).wall_clock_span_ms == 2 * H
    assert bound.separations[0].separation_ms == 6 * H
    assert_no_fabricated_timestamps(bound, opens)


# --- window-edge and coverage handling ------------------------------------------


def test_window_starting_inside_a_confirmed_archive_gap_is_flagged_as_edge_gap(bridge, storage):
    archived = list(range(0, 10)) + list(range(20, 130))
    store(storage, [s * H for s in archived])
    access = bridge.load_window(SYMBOL, TIMEFRAME, dt(12 * H), dt(129 * H))
    assert access.coverage.status is CoverageStatus.GAPS_PRESENT_FLAGGED

    bound = bind_split_to_timestamps(make_purged_split(access.coverage.actual_count, SPEC), access)

    assert bound.edge_gaps == (GapRange(12 * H, 19 * H, 8),)
    assert bound.status is BindingStatus.BOUND_WITH_FLAGGED_GAPS
    assert bound.train.start_ms == 20 * H  # a real bar, never the window start


def test_refused_p1_coverage_is_refused_before_splitting(binder, bridge, storage):
    store(storage, [i * H for i in range(5, N)])
    start, end = dt(0), dt((N - 1) * H)  # starts before the archive's first bar
    access = bridge.load_window(SYMBOL, TIMEFRAME, start, end)
    assert access.coverage.status is CoverageStatus.GAPS_PRESENT_REFUSED

    with pytest.raises(CoverageRefusedError):
        binder.bind(SYMBOL, TIMEFRAME, start, end, SPEC)
    with pytest.raises(CoverageRefusedError):
        bind_split_to_timestamps(make_purged_split(access.coverage.actual_count, SPEC), access)


def test_window_entirely_inside_a_gap_yields_no_split(binder, storage):
    store(storage, [s * H for s in list(range(0, 10)) + list(range(30, 40))])

    with pytest.raises(SplitError):
        binder.bind(SYMBOL, TIMEFRAME, dt(12 * H), dt(20 * H), SPEC)


# --- tampered / inconsistent inputs are refused, never repaired -----------------


def _clean_access(bridge, storage) -> WindowBarAccessResult:
    opens = [i * H for i in range(N)]
    store(storage, opens)
    return load(bridge, opens)


def test_split_over_a_different_observation_count_is_refused(bridge, storage):
    access = _clean_access(bridge, storage)
    with pytest.raises(SplitShapeError):
        bind_split_to_timestamps(make_purged_split(N - 1, SPEC), access)


def test_hand_built_split_with_oversized_buffer_is_refused(bridge, storage):
    access = _clean_access(bridge, storage)
    widened = DataSplit(
        train=Segment(0, 50), calibration=Segment(60, 75), test=Segment(80, 100),
        n_observations=N, spec=SPEC, purged_bars=2, embargo_bars=3,
    )
    with pytest.raises(SplitShapeError, match="sealed spec"):
        bind_split_to_timestamps(widened, access)


def test_split_not_starting_at_zero_is_refused(bridge, storage):
    access = _clean_access(bridge, storage)
    shifted = DataSplit(
        train=Segment(5, 55), calibration=Segment(60, 75), test=Segment(80, 100),
        n_observations=N, spec=SPEC, purged_bars=2, embargo_bars=3,
    )
    with pytest.raises(SplitShapeError, match="sealed spec"):
        bind_split_to_timestamps(shifted, access)


def test_non_datasplit_and_non_access_inputs_are_refused(bridge, storage):
    access = _clean_access(bridge, storage)
    with pytest.raises(SplitShapeError):
        bind_split_to_timestamps(make_purged_split(N, SPEC).as_dict(), access)
    with pytest.raises(BarSequenceIntegrityError):
        bind_split_to_timestamps(make_purged_split(N, SPEC), {"bars": access.bars})


def test_gap_hidden_from_p1_gap_ranges_is_detected_from_the_bars(bridge, storage):
    opens = gapped_opens(N, 58, gap_slots=3)
    store(storage, opens)
    access = load(bridge, opens)
    doctored = WindowBarAccessResult(
        bars=access.bars,
        coverage=dataclasses.replace(
            access.coverage, gap_ranges=(), status=CoverageStatus.COMPLETE,
            expected_count=access.coverage.actual_count,
        ),
    )

    with pytest.raises(BarSequenceIntegrityError, match="disagree"):
        bind_split_to_timestamps(make_purged_split(N, SPEC), doctored)


def test_complete_status_contradicting_reported_gaps_is_refused(bridge, storage):
    opens = gapped_opens(N, 30, gap_slots=2)
    store(storage, opens)
    access = load(bridge, opens)
    doctored = WindowBarAccessResult(
        bars=access.bars,
        coverage=dataclasses.replace(access.coverage, status=CoverageStatus.COMPLETE),
    )
    with pytest.raises(BarSequenceIntegrityError, match="contradicts"):
        bind_split_to_timestamps(make_purged_split(N, SPEC), doctored)


def test_string_status_is_not_accepted_as_a_coverage_status(bridge, storage):
    access = _clean_access(bridge, storage)
    doctored = WindowBarAccessResult(
        bars=access.bars, coverage=dataclasses.replace(access.coverage, status="COMPLETE")
    )
    with pytest.raises(BarSequenceIntegrityError):
        bind_split_to_timestamps(make_purged_split(N, SPEC), doctored)


def test_split_with_smaller_purge_than_its_sealed_spec_is_refused(bridge, storage):
    """Independent-audit finding (MEDIUM): a hand-built DataSplit whose
    purge/embargo are zero while its own sealed spec requires purge 2 and
    embargo 3 satisfies DataSplit's own invariant, but must not bind."""
    access = _clean_access(bridge, storage)
    no_purge = DataSplit(
        train=Segment(0, 60), calibration=Segment(60, 80), test=Segment(80, 100),
        n_observations=N, spec=SPEC, purged_bars=0, embargo_bars=0,
    )
    assert no_purge != make_purged_split(N, SPEC)
    with pytest.raises(SplitShapeError, match="sealed spec"):
        bind_split_to_timestamps(no_purge, access)


def test_split_with_non_integer_buffer_sizes_is_refused_within_the_error_contract(bridge, storage):
    access = _clean_access(bridge, storage)
    fractional = DataSplit(
        train=Segment(0, 55), calibration=Segment(60, 75), test=Segment(80, 100),
        n_observations=N, spec=SPEC, purged_bars=2.5, embargo_bars=2.5,
    )
    with pytest.raises(SplitShapeError):
        bind_split_to_timestamps(fractional, access)


def test_unsorted_bars_are_refused(bridge, storage):
    access = _clean_access(bridge, storage)
    bars = list(access.bars)
    bars[10], bars[11] = bars[11], bars[10]
    with pytest.raises(BarSequenceIntegrityError, match="strictly increasing"):
        bind_split_to_timestamps(
            make_purged_split(N, SPEC), WindowBarAccessResult(tuple(bars), access.coverage)
        )


def test_duplicated_bar_is_refused(bridge, storage):
    """A duplicate (equal open times, not a swap) must be refused: only a
    strict ``<=`` ordering check catches it."""
    access = _clean_access(bridge, storage)
    bars = list(access.bars)
    bars[11] = bars[10]
    with pytest.raises(BarSequenceIntegrityError, match="strictly increasing"):
        bind_split_to_timestamps(
            make_purged_split(N, SPEC), WindowBarAccessResult(tuple(bars), access.coverage)
        )


def test_bar_for_another_symbol_is_refused(bridge, storage):
    access = _clean_access(bridge, storage)
    bars = list(access.bars)
    bars[5] = dataclasses.replace(bars[5], symbol="ETHUSDT")
    with pytest.raises(BarSequenceIntegrityError, match="does not match"):
        bind_split_to_timestamps(
            make_purged_split(N, SPEC), WindowBarAccessResult(tuple(bars), access.coverage)
        )


@pytest.mark.parametrize("bad_open", [float(20 * H), True, str(20 * H)])
def test_non_integer_open_time_is_refused(bridge, storage, bad_open):
    access = _clean_access(bridge, storage)
    bars = list(access.bars)
    bars[20] = dataclasses.replace(bars[20], open_time_ms=bad_open)
    with pytest.raises(BarSequenceIntegrityError, match="not an int"):
        bind_split_to_timestamps(
            make_purged_split(N, SPEC), WindowBarAccessResult(tuple(bars), access.coverage)
        )


def test_bar_outside_the_window_is_refused(bridge, storage):
    access = _clean_access(bridge, storage)
    bars = list(access.bars)
    bars[-1] = dataclasses.replace(bars[-1], open_time_ms=(N + 5) * H)
    with pytest.raises(BarSequenceIntegrityError, match="outside the window"):
        bind_split_to_timestamps(
            make_purged_split(N, SPEC), WindowBarAccessResult(tuple(bars), access.coverage)
        )


def test_expected_count_disagreeing_with_bars_and_gaps_is_refused(bridge, storage):
    access = _clean_access(bridge, storage)
    doctored = WindowBarAccessResult(
        bars=access.bars,
        coverage=dataclasses.replace(access.coverage, expected_count=N + 3),
    )
    with pytest.raises(BarSequenceIntegrityError, match="expected_count"):
        bind_split_to_timestamps(make_purged_split(N, SPEC), doctored)


def test_unknown_timeframe_in_coverage_is_refused(bridge, storage):
    access = _clean_access(bridge, storage)
    doctored = WindowBarAccessResult(
        bars=access.bars,
        coverage=dataclasses.replace(access.coverage, timeframe="1M"),
    )
    with pytest.raises(BarSequenceIntegrityError):
        bind_split_to_timestamps(make_purged_split(N, SPEC), doctored)


def test_reported_gap_with_no_matching_hole_in_the_bars_is_refused(bridge, storage):
    """The reverse of the hidden-gap case: P1 reports a gap on a boundary the
    bars do not actually show. It is refused as an inconsistency, never
    trusted either way."""
    access = _clean_access(bridge, storage)
    doctored = WindowBarAccessResult(
        bars=access.bars,
        coverage=dataclasses.replace(
            access.coverage,
            gap_ranges=(GapRange(59 * H, 59 * H, 1),),
            status=CoverageStatus.GAPS_PRESENT_FLAGGED,
            expected_count=N + 1,
        ),
    )
    with pytest.raises(BarSequenceIntegrityError, match="disagree"):
        bind_split_to_timestamps(make_purged_split(N, SPEC), doctored)


def test_window_ending_inside_a_confirmed_archive_gap_is_flagged_as_trailing_edge_gap(bridge, storage):
    archived = list(range(0, 110)) + list(range(120, 130))
    store(storage, [slot * H for slot in archived])
    access = bridge.load_window(SYMBOL, TIMEFRAME, dt(0), dt(115 * H))
    assert access.coverage.status is CoverageStatus.GAPS_PRESENT_FLAGGED

    bound = bind_split_to_timestamps(make_purged_split(access.coverage.actual_count, SPEC), access)

    assert bound.edge_gaps == (GapRange(110 * H, 115 * H, 6),)
    assert bound.status is BindingStatus.BOUND_WITH_FLAGGED_GAPS
    assert bound.test.end_ms == 110 * H  # the last real bar's end, not the window end
    assert_no_fabricated_timestamps(bound, [slot * H for slot in archived if slot <= 115])


def test_misaligned_bar_is_refused(bridge, storage):
    access = _clean_access(bridge, storage)
    bars = list(access.bars)
    bars[40] = dataclasses.replace(bars[40], open_time_ms=bars[40].open_time_ms + 1)
    with pytest.raises(BarSequenceIntegrityError, match="aligned"):
        bind_split_to_timestamps(
            make_purged_split(N, SPEC), WindowBarAccessResult(tuple(bars), access.coverage)
        )


def test_bar_count_disagreeing_with_actual_count_is_refused(bridge, storage):
    access = _clean_access(bridge, storage)
    with pytest.raises(BarSequenceIntegrityError):
        bind_split_to_timestamps(
            make_purged_split(N - 1, SPEC),
            WindowBarAccessResult(access.bars[:-1], access.coverage),
        )


def test_binder_requires_a_bridge_and_a_real_spec(bridge):
    with pytest.raises(TimestampSplitBindingError):
        ResearchTimestampSplitBinder(None)
    with pytest.raises(SplitShapeError):
        ResearchTimestampSplitBinder(bridge).bind(
            SYMBOL, TIMEFRAME, dt(0), dt(H), SPEC.as_dict()
        )


def test_results_are_immutable(bridge, storage):
    bound = bind_split_to_timestamps(make_purged_split(N, SPEC), _clean_access(bridge, storage))
    with pytest.raises(dataclasses.FrozenInstanceError):
        bound.train.start_ms = 0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        bound.status = BindingStatus.BOUND_CLEAN  # type: ignore[misc]


# --- architecture boundary --------------------------------------------------------


def _imports_and_names() -> tuple[set[str], set[str]]:
    tree = ast.parse((REPO_ROOT / MODULE_PATH).read_text(encoding="utf-8"))
    imported: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return imported, names


def test_module_imports_only_the_authorized_dependencies():
    imported, names = _imports_and_names()
    first_party = {
        name for name in imported
        if name.split(".")[0] in {"core", "data_layer", "research", "execution", "risk", "ai", "analysis"}
    }
    assert first_party == {
        "core.research_market_data_bridge",
        "data_layer.contracts",
        "data_layer.market_data_archive_sqlite",
        "research.splitting",
    }
    # P3's concern is never touched: no import and no reference.
    assert not any("hypothesis_registry" in name for name in imported)
    assert not {"CheckResult", "HypothesisRegistry", "hypothesis_registry"} & names
    # No network capability of any kind.
    network = {"socket", "requests", "urllib", "http", "httpx", "aiohttp", "websocket", "websockets"}
    assert not {name.split(".")[0] for name in imported} & network


def test_module_classifies_as_l3_via_the_existing_core_rule():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.build_architecture_inventory import classify_module

    with open(REPO_ROOT / "packaging" / "atlas_architecture_map.json", encoding="utf-8") as f:
        layer_rules = json.load(f)["layer_rules"]

    assert classify_module(MODULE_PATH, layer_rules) == "L3"


def test_neither_p1_nor_p2_is_in_the_committed_runtime_closure():
    with open(REPO_ROOT / "packaging" / "atlas_runtime_closure.json", encoding="utf-8") as f:
        closure = json.load(f)
    modules = closure["modules"] if isinstance(closure, dict) else closure
    assert MODULE_PATH not in modules
    assert "core/research_market_data_bridge.py" not in modules
    assert not any(module.startswith("research/") for module in modules)


def test_neither_p1_nor_p2_is_in_the_live_computed_runtime_closure():
    """Computed from the code (git-tracked files), not read from the
    committed closure artifact."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.build_architecture_inventory import compute_runtime_closure

    closure = compute_runtime_closure(REPO_ROOT)
    assert MODULE_PATH not in closure
    assert "core/research_market_data_bridge.py" not in closure
    assert not any(module.startswith("research/") for module in closure)
