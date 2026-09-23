"""P2 of the compute-engine proposal: timestamp-bound purged splits.

Governance: registry v4.70, ``GRANT-COMPUTE-ENGINE-P2``, scoped additive
supersession of ``GRANT-COMPUTE-ENGINE-DEFER`` (v4.56/v4.57) for P2 only.
P3 (producing ``research.hypothesis_registry.CheckResult`` objects) and P4
(cost-adjusted / Monte Carlo evaluation) remain unauthorized and are not
implemented here.

Shape, extending P1 (registry v4.69) without modifying it::

    research/splitting.py                     (L4, pure, stdlib-only)
          └─ make_purged_split() -> DataSplit (index ranges only)
    core/research_market_data_bridge.py       (L3, P1)
          └─ load_window() -> real bars + expected/actual/gap_ranges
                              │
                              ▼  both read by
    core/research_timestamp_split_binding.py  (L3 -- this module)
          ├─ imports research.splitting            (L3 -> L4, allowed, ADR-0009)
          ├─ imports core.research_market_data_bridge (L3 -> L3)
          └─ imports data_layer.market_data_archive_sqlite (L3 -> L2, allowed;
                                                    the fixed bar width only)

Importing ``research.splitting`` executes ``research/__init__.py``, which
eagerly imports ``research.hypothesis_registry``. That load is a side effect
of Python package semantics, disclosed in registry v4.70; this module
references no name from it and produces no hypothesis-registry object.

**Not wired into the runtime.** Nothing in the runtime closure imports this
module (W2 remains unauthorized), and it makes no network call: its only
data source is the injected P1 bridge, which reads the local archive.

Binding rule -- indices are real bars, never grid slots
------------------------------------------------------
``make_purged_split(n_observations, spec)`` is called with ``n_observations``
equal to the number of bars the archive actually returned, and index *i* is
bound to ``bars[i]``. Every segment, buffer and separation timestamp this
module emits is therefore the open time of a real archived bar (or that open
time plus one bar width, for a half-open end; an empty buffer sits at the open
time of the next real bar). The only other timestamps in a result are passed
through from P1 and validated, never computed here: the requested window
bounds, and the missing-slot ranges of reported gaps. No timestamp is
interpolated, and a missing grid slot is never turned into an observation.

Gap policy -- fail closed at every boundary
-------------------------------------------
When the bar sequence is gap-free, "``k`` bars" and "``k`` bar-widths of
wall-clock time" are the same quantity everywhere, so the purge
(``purged_bars``) and embargo (``embargo_bars``) sealed into a pre-registered
``SplitSpec`` mean exactly what they say whichever unit a downstream label or
feature is computed in.

A gap breaks that equivalence. Index-adjacency is no longer time-adjacency:

* an embargo of ``e`` bars that contains a gap spans more than ``e``
  bar-widths of wall-clock time, so the sealed spec no longer describes the
  experiment actually run;
* a purge of ``h`` bars sized for a label horizon measured in one unit fails
  to remove the leaking window when the label is computed in the other -- for
  example a split taken over grid slots with labels taken ``h`` observations
  ahead reaches straight across a gap into the next segment, although the
  index-only ``DataSplit`` invariant is satisfied.

P3 does not exist yet, so the label and feature convention is unknown here.
The only policy correct for every convention is to refuse whenever the two
units can disagree at a boundary. Concretely, :func:`bind_split_to_timestamps`
raises :class:`GapStraddlesBoundaryError` -- and returns nothing -- when any
real gap from P1's ``gap_ranges`` lies

* inside a purge or embargo buffer,
* between a segment and its adjacent buffer, or
* directly between two segments (``purged_bars + embargo_bars == 0``).

A gap strictly inside the body of a single train, calibration or test
segment does not touch a boundary. It is returned and flagged
(:attr:`BindingStatus.BOUND_WITH_FLAGGED_GAPS`) in that segment's
``interior_gaps``, and the segment's reported wall-clock span includes it. A
gap before the first returned bar or after the last (a window edge inside a
confirmed archive gap) is likewise flagged in ``edge_gaps``. A P1 window
whose coverage is ``GAPS_PRESENT_REFUSED`` is refused outright: part of it is
indistinguishable from data not yet archived.

Every other inconsistency -- a split that does not describe exactly these
bars, a split that is not exactly what ``make_purged_split`` produces from its
own sealed ``spec`` (so a hand-built split cannot carry a smaller purge or
embargo than its pre-registration declares), bars that disagree with P1's own
``gap_ranges`` -- is also refused rather than repaired.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

# L3 -> L3. P1's result types and bridge.
from core.research_market_data_bridge import (
    CoverageStatus,
    GapRange,
    ResearchMarketDataBridge,
    WindowBarAccessResult,
)

# L3 -> L2. The fixed bar width only.
from data_layer.contracts import StorageError
from data_layer.market_data_archive_sqlite import timeframe_to_milliseconds

# L3 -> L4 (ADR-0009). Index-range splitting only; nothing from
# research.hypothesis_registry is referenced.
from research.splitting import DataSplit, SplitError, SplitSpec, make_purged_split


class TimestampSplitBindingError(RuntimeError):
    """Base for every fail-closed refusal in this module.

    No path raising a subclass of this returns a split. There is no code path
    in this module that repairs, shifts or interpolates a boundary.
    """


class CoverageRefusedError(TimestampSplitBindingError):
    """P1 reported the window as ``GAPS_PRESENT_REFUSED``."""


class SplitShapeError(TimestampSplitBindingError):
    """The split does not describe exactly the supplied bars, or its shape is
    not the one ``make_purged_split`` produces."""


class BarSequenceIntegrityError(TimestampSplitBindingError):
    """The bars are malformed or disagree with P1's own coverage report."""


class Zone(str, Enum):
    """Every index position belongs to exactly one zone, in this order."""

    TRAIN = "TRAIN"
    EMBARGO_TRAIN_CALIBRATION = "EMBARGO_TRAIN_CALIBRATION"
    PURGE_TRAIN_CALIBRATION = "PURGE_TRAIN_CALIBRATION"
    CALIBRATION = "CALIBRATION"
    EMBARGO_CALIBRATION_TEST = "EMBARGO_CALIBRATION_TEST"
    PURGE_CALIBRATION_TEST = "PURGE_CALIBRATION_TEST"
    TEST = "TEST"


_SEGMENT_ZONES = frozenset({Zone.TRAIN, Zone.CALIBRATION, Zone.TEST})


class Boundary(str, Enum):
    TRAIN_CALIBRATION = "TRAIN_CALIBRATION"
    CALIBRATION_TEST = "CALIBRATION_TEST"


class BindingStatus(str, Enum):
    BOUND_CLEAN = "BOUND_CLEAN"
    BOUND_WITH_FLAGGED_GAPS = "BOUND_WITH_FLAGGED_GAPS"


@dataclass(frozen=True, slots=True)
class GapBoundaryViolation:
    """One real gap sitting between index ``after_index - 1`` and ``after_index``
    where at least one side is not the body of the same segment."""

    gap: GapRange
    before_zone: Zone
    after_zone: Zone
    after_index: int
    boundary: Boundary

    def describe(self) -> str:
        return (
            f"gap {_iso(self.gap.start_ms)} -> {_iso(self.gap.end_ms)} "
            f"({self.gap.missing_bars} bars) lies between {self.before_zone.value} "
            f"and {self.after_zone.value} (index {self.after_index - 1} -> "
            f"{self.after_index}, {self.boundary.value} boundary)"
        )


class GapStraddlesBoundaryError(TimestampSplitBindingError):
    """At least one real gap touches a purge, embargo or split boundary."""

    def __init__(self, violations: tuple[GapBoundaryViolation, ...]) -> None:
        self.violations = violations
        super().__init__(
            "refusing to bind split: "
            + "; ".join(violation.describe() for violation in violations)
        )


@dataclass(frozen=True, slots=True)
class TimestampSegment:
    """A train, calibration or test segment resolved to real bar timestamps.

    ``[start_ms, end_ms)`` is half-open: ``start_ms`` is the open time of the
    segment's first bar and ``end_ms`` is the open time of its last bar plus
    one bar width.
    """

    zone: Zone
    start_index: int
    stop_index: int
    start_ms: int
    end_ms: int
    interior_gaps: tuple[GapRange, ...]

    @property
    def bar_count(self) -> int:
        return self.stop_index - self.start_index

    @property
    def wall_clock_span_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def start(self) -> datetime:
        return _from_ms(self.start_ms)

    @property
    def end(self) -> datetime:
        return _from_ms(self.end_ms)


@dataclass(frozen=True, slots=True)
class BufferZone:
    """A purge or embargo buffer resolved to wall-clock time.

    Only ever constructed for a bound split, in which it is gap-free, so
    ``wall_clock_span_ms == bar_count * interval_ms`` exactly. An empty buffer
    (``bar_count == 0``) has ``start_ms == end_ms``, located at the open time
    of the first bar after it.
    """

    zone: Zone
    boundary: Boundary
    start_index: int
    stop_index: int
    start_ms: int
    end_ms: int

    @property
    def bar_count(self) -> int:
        return self.stop_index - self.start_index

    @property
    def wall_clock_span_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def start(self) -> datetime:
        return _from_ms(self.start_ms)

    @property
    def end(self) -> datetime:
        return _from_ms(self.end_ms)


@dataclass(frozen=True, slots=True)
class BoundarySeparation:
    """Wall-clock distance between the last kept bar of an earlier segment
    and the first bar of the following segment.

    For a bound split, ``separation_ms == (buffer_bars + 1) * interval_ms``
    exactly: the buffer is gap-free and touches both segments with no gap.
    """

    boundary: Boundary
    earlier_last_open_ms: int
    later_first_open_ms: int
    buffer_bars: int

    @property
    def separation_ms(self) -> int:
        return self.later_first_open_ms - self.earlier_last_open_ms


@dataclass(frozen=True, slots=True)
class TimestampBoundSplit:
    """A ``DataSplit`` whose every boundary has been verified in wall-clock time."""

    symbol: str
    timeframe: str
    interval_ms: int
    window_start_ms: int
    window_end_ms: int
    split: DataSplit
    train: TimestampSegment
    calibration: TimestampSegment
    test: TimestampSegment
    buffers: tuple[BufferZone, ...]
    separations: tuple[BoundarySeparation, ...]
    edge_gaps: tuple[GapRange, ...]
    coverage_status: CoverageStatus
    status: BindingStatus

    @property
    def segments(self) -> tuple[TimestampSegment, TimestampSegment, TimestampSegment]:
        return (self.train, self.calibration, self.test)

    @property
    def purge_wall_clock_ms(self) -> int:
        """The purge width the sealed spec declares, in wall-clock time."""
        return self.split.purged_bars * self.interval_ms

    @property
    def embargo_wall_clock_ms(self) -> int:
        """The embargo width the sealed spec declares, in wall-clock time."""
        return self.split.embargo_bars * self.interval_ms

    def buffer(self, zone: Zone) -> BufferZone:
        for candidate in self.buffers:
            if candidate.zone is zone:
                return candidate
        raise KeyError(zone)


def _from_ms(value_ms: int) -> datetime:
    return datetime.fromtimestamp(value_ms / 1000, tz=timezone.utc)


def _iso(value_ms: int) -> str:
    return _from_ms(value_ms).isoformat()


def _zone_layout(split: DataSplit) -> tuple[tuple[Zone, int, int], ...]:
    """The seven ``(zone, start, stop)`` index ranges, in index order."""

    purge = split.purged_bars
    return (
        (Zone.TRAIN, split.train.start, split.train.stop),
        (Zone.EMBARGO_TRAIN_CALIBRATION, split.train.stop, split.calibration.start - purge),
        (Zone.PURGE_TRAIN_CALIBRATION, split.calibration.start - purge, split.calibration.start),
        (Zone.CALIBRATION, split.calibration.start, split.calibration.stop),
        (Zone.EMBARGO_CALIBRATION_TEST, split.calibration.stop, split.test.start - purge),
        (Zone.PURGE_CALIBRATION_TEST, split.test.start - purge, split.test.start),
        (Zone.TEST, split.test.start, split.test.stop),
    )


def _zone_of(layout: tuple[tuple[Zone, int, int], ...], index: int) -> Zone:
    for zone, start, stop in layout:
        if start <= index < stop:
            return zone
    raise SplitShapeError(f"index {index} falls in no zone")  # unreachable after validation


_ZONE_ORDER = tuple(Zone)


def _boundary_for(before: Zone) -> Boundary:
    # A violating gap never has both sides in the same segment body, so a gap
    # whose earlier side precedes CALIBRATION touches the train/calibration
    # boundary; every other violating gap touches calibration/test.
    if _ZONE_ORDER.index(before) < _ZONE_ORDER.index(Zone.CALIBRATION):
        return Boundary.TRAIN_CALIBRATION
    return Boundary.CALIBRATION_TEST


def _validate_split_shape(split: DataSplit, bar_count: int) -> None:
    if not isinstance(split, DataSplit):
        raise SplitShapeError(f"split must be a research.splitting.DataSplit, got {split!r}")

    if split.n_observations != bar_count:
        raise SplitShapeError(
            f"split.n_observations ({split.n_observations}) does not equal the number "
            f"of real archived bars ({bar_count}); indices must bind to real bars, "
            f"never to grid slots"
        )
    if not isinstance(split.spec, SplitSpec):
        raise SplitShapeError(f"split.spec must be a SplitSpec, got {split.spec!r}")
    try:
        canonical = make_purged_split(split.n_observations, split.spec)
    except SplitError as exc:
        raise SplitShapeError(f"split's own spec cannot produce a split: {exc}") from exc
    if split != canonical:
        raise SplitShapeError(
            "split is not the split its own sealed spec produces via make_purged_split "
            f"(expected train={canonical.train.as_dict()} calibration="
            f"{canonical.calibration.as_dict()} test={canonical.test.as_dict()} "
            f"purged_bars={canonical.purged_bars} embargo_bars={canonical.embargo_bars}); "
            "a hand-built split may not carry a different purge or embargo"
        )
    # Given equality with make_purged_split, the checks below always hold;
    # they are kept as explicit statements of the shape this module relies on.
    if split.train.start != 0 or split.test.stop != split.n_observations:
        raise SplitShapeError(
            "split must cover the whole bar sequence (train starts at 0, test stops "
            f"at n_observations), got train.start={split.train.start} "
            f"test.stop={split.test.stop} n={split.n_observations}"
        )

    buffer_bars = split.purged_bars + split.embargo_bars
    if split.purged_bars < 0 or split.embargo_bars < 0:
        raise SplitShapeError("purged_bars and embargo_bars must be >= 0")
    if (
        split.calibration.start - split.train.stop != buffer_bars
        or split.test.start - split.calibration.stop != buffer_bars
    ):
        raise SplitShapeError(
            "each inter-segment gap must equal purged_bars + embargo_bars exactly "
            f"({buffer_bars}), as make_purged_split produces; got "
            f"{split.calibration.start - split.train.stop} and "
            f"{split.test.start - split.calibration.stop}"
        )


def _validated_gap_positions(
    access: WindowBarAccessResult, interval_ms: int
) -> tuple[tuple[GapRange, int], ...]:
    """Pair each P1 gap with the index of the first real bar after it.

    Re-derives every gap from the bars themselves and requires the result to
    match P1's ``gap_ranges`` exactly, so a gap P1 reported but the bars do
    not show -- or the reverse -- is refused rather than trusted.
    """

    coverage = access.coverage
    bars = access.bars
    window_start_ms = coverage.window_start_ms
    window_end_ms = coverage.window_end_ms

    previous_ms: int | None = None
    for bar in bars:
        if bar.symbol != coverage.symbol or bar.timeframe != coverage.timeframe:
            raise BarSequenceIntegrityError(
                f"bar {bar.symbol} {bar.timeframe} does not match the coverage "
                f"report's {coverage.symbol} {coverage.timeframe}"
            )
        open_ms = bar.open_time_ms
        if isinstance(open_ms, bool) or not isinstance(open_ms, int):
            raise BarSequenceIntegrityError(f"bar open_time_ms is not an int: {open_ms!r}")
        if not window_start_ms <= open_ms <= window_end_ms:
            raise BarSequenceIntegrityError(
                f"bar at {open_ms} lies outside the window [{window_start_ms}, {window_end_ms}]"
            )
        if (open_ms - window_start_ms) % interval_ms != 0:
            raise BarSequenceIntegrityError(
                f"bar at {open_ms} is not aligned to the {coverage.timeframe} grid"
            )
        if previous_ms is not None and open_ms <= previous_ms:
            raise BarSequenceIntegrityError(
                f"bars are not strictly increasing in open time ({previous_ms} -> {open_ms})"
            )
        previous_ms = open_ms

    derived: list[tuple[GapRange, int]] = []
    if bars[0].open_time_ms > window_start_ms:
        end_ms = bars[0].open_time_ms - interval_ms
        derived.append(
            (GapRange(window_start_ms, end_ms, (end_ms - window_start_ms) // interval_ms + 1), 0)
        )
    for index in range(1, len(bars)):
        step = bars[index].open_time_ms - bars[index - 1].open_time_ms
        if step != interval_ms:
            start_ms = bars[index - 1].open_time_ms + interval_ms
            end_ms = bars[index].open_time_ms - interval_ms
            derived.append(
                (GapRange(start_ms, end_ms, (end_ms - start_ms) // interval_ms + 1), index)
            )
    if bars[-1].open_time_ms < window_end_ms:
        start_ms = bars[-1].open_time_ms + interval_ms
        derived.append(
            (
                GapRange(start_ms, window_end_ms, (window_end_ms - start_ms) // interval_ms + 1),
                len(bars),
            )
        )

    reported = tuple(
        (gap.start_ms, gap.end_ms, gap.missing_bars) for gap in coverage.gap_ranges
    )
    rederived = tuple((gap.start_ms, gap.end_ms, gap.missing_bars) for gap, _ in derived)
    if reported != rederived:
        raise BarSequenceIntegrityError(
            f"P1 gap_ranges {reported} disagree with the gaps visible in the bars "
            f"themselves {rederived}"
        )

    missing = sum(gap.missing_bars for gap, _ in derived)
    if coverage.expected_count != len(bars) + missing:
        raise BarSequenceIntegrityError(
            f"expected_count {coverage.expected_count} != bars {len(bars)} + "
            f"missing {missing}"
        )

    # Pair P1's own GapRange objects (not the re-derived copies) with positions.
    return tuple(
        (reported_gap, position)
        for reported_gap, (_, position) in zip(coverage.gap_ranges, derived)
    )


def _refuse_unusable_coverage(access: WindowBarAccessResult) -> None:
    coverage = access.coverage
    if not isinstance(coverage.status, CoverageStatus):
        raise BarSequenceIntegrityError(
            f"coverage.status is not a P1 CoverageStatus: {coverage.status!r}"
        )
    if coverage.status is CoverageStatus.GAPS_PRESENT_REFUSED:
        raise CoverageRefusedError(
            f"P1 refused coverage for {coverage.symbol} {coverage.timeframe} "
            f"[{_iso(coverage.window_start_ms)}, {_iso(coverage.window_end_ms)}]: the "
            f"window extends past the archive's own edge"
        )
    if (coverage.status is CoverageStatus.COMPLETE) != (not coverage.gap_ranges):
        raise BarSequenceIntegrityError(
            f"coverage.status {coverage.status.value} contradicts "
            f"{len(coverage.gap_ranges)} reported gap range(s)"
        )


def bind_split_to_timestamps(
    split: DataSplit, access: WindowBarAccessResult
) -> TimestampBoundSplit:
    """Bind an index-range ``DataSplit`` onto the real bars of a P1 window.

    Raises -- never returns a partially trusted split -- per the gap policy in
    this module's docstring.
    """

    if not isinstance(access, WindowBarAccessResult):
        raise BarSequenceIntegrityError(
            f"access must be a P1 WindowBarAccessResult, got {access!r}"
        )

    coverage = access.coverage
    _refuse_unusable_coverage(access)

    bars = access.bars
    if len(bars) != coverage.actual_count:
        raise BarSequenceIntegrityError(
            f"{len(bars)} bars returned but coverage.actual_count is {coverage.actual_count}"
        )
    if not bars:
        raise SplitShapeError("the window contains no real bars to split")

    try:
        interval_ms = timeframe_to_milliseconds(coverage.timeframe)
    except StorageError as exc:
        raise BarSequenceIntegrityError(str(exc)) from exc

    _validate_split_shape(split, len(bars))
    gap_positions = _validated_gap_positions(access, interval_ms)

    layout = _zone_layout(split)
    n = len(bars)

    violations: list[GapBoundaryViolation] = []
    interior: dict[Zone, list[GapRange]] = {zone: [] for zone in _SEGMENT_ZONES}
    edge_gaps: list[GapRange] = []

    for gap, after_index in gap_positions:
        if after_index == 0 or after_index == n:
            edge_gaps.append(gap)
            continue
        before_zone = _zone_of(layout, after_index - 1)
        after_zone = _zone_of(layout, after_index)
        if before_zone is after_zone and before_zone in _SEGMENT_ZONES:
            interior[before_zone].append(gap)
            continue
        violations.append(
            GapBoundaryViolation(
                gap=gap,
                before_zone=before_zone,
                after_zone=after_zone,
                after_index=after_index,
                boundary=_boundary_for(before_zone),
            )
        )

    if violations:
        raise GapStraddlesBoundaryError(tuple(violations))

    def open_ms(index: int) -> int:
        return bars[index].open_time_ms

    segments: dict[Zone, TimestampSegment] = {}
    buffers: list[BufferZone] = []
    for zone, start, stop in layout:
        if zone in _SEGMENT_ZONES:
            segment = TimestampSegment(
                zone=zone,
                start_index=start,
                stop_index=stop,
                start_ms=open_ms(start),
                end_ms=open_ms(stop - 1) + interval_ms,
                interior_gaps=tuple(interior[zone]),
            )
            expected_span = (
                segment.bar_count + sum(g.missing_bars for g in segment.interior_gaps)
            ) * interval_ms
            if segment.wall_clock_span_ms != expected_span:
                raise BarSequenceIntegrityError(
                    f"{zone.value} spans {segment.wall_clock_span_ms} ms, expected "
                    f"{expected_span} ms"
                )
            segments[zone] = segment
            continue

        boundary = (
            Boundary.TRAIN_CALIBRATION
            if zone in (Zone.EMBARGO_TRAIN_CALIBRATION, Zone.PURGE_TRAIN_CALIBRATION)
            else Boundary.CALIBRATION_TEST
        )
        if stop > start:
            buffer = BufferZone(
                zone=zone,
                boundary=boundary,
                start_index=start,
                stop_index=stop,
                start_ms=open_ms(start),
                end_ms=open_ms(stop - 1) + interval_ms,
            )
        else:
            # Empty buffer: pinned to the first real bar after it. ``start``
            # is always < n here because the test segment is non-empty.
            buffer = BufferZone(
                zone=zone,
                boundary=boundary,
                start_index=start,
                stop_index=stop,
                start_ms=open_ms(start),
                end_ms=open_ms(start),
            )
        if buffer.wall_clock_span_ms != buffer.bar_count * interval_ms:
            raise BarSequenceIntegrityError(
                f"{zone.value} spans {buffer.wall_clock_span_ms} ms for "
                f"{buffer.bar_count} bars"
            )
        buffers.append(buffer)

    buffer_bars = split.purged_bars + split.embargo_bars
    separations = (
        BoundarySeparation(
            boundary=Boundary.TRAIN_CALIBRATION,
            earlier_last_open_ms=open_ms(split.train.stop - 1),
            later_first_open_ms=open_ms(split.calibration.start),
            buffer_bars=buffer_bars,
        ),
        BoundarySeparation(
            boundary=Boundary.CALIBRATION_TEST,
            earlier_last_open_ms=open_ms(split.calibration.stop - 1),
            later_first_open_ms=open_ms(split.test.start),
            buffer_bars=buffer_bars,
        ),
    )
    for separation in separations:
        if separation.separation_ms != (buffer_bars + 1) * interval_ms:
            raise BarSequenceIntegrityError(
                f"{separation.boundary.value} separation is {separation.separation_ms} ms, "
                f"expected {(buffer_bars + 1) * interval_ms} ms"
            )

    has_flagged = bool(edge_gaps) or any(interior[zone] for zone in _SEGMENT_ZONES)

    return TimestampBoundSplit(
        symbol=coverage.symbol,
        timeframe=coverage.timeframe,
        interval_ms=interval_ms,
        window_start_ms=coverage.window_start_ms,
        window_end_ms=coverage.window_end_ms,
        split=split,
        train=segments[Zone.TRAIN],
        calibration=segments[Zone.CALIBRATION],
        test=segments[Zone.TEST],
        buffers=tuple(buffers),
        separations=separations,
        edge_gaps=tuple(edge_gaps),
        coverage_status=coverage.status,
        status=(
            BindingStatus.BOUND_WITH_FLAGGED_GAPS if has_flagged else BindingStatus.BOUND_CLEAN
        ),
    )


class ResearchTimestampSplitBinder:
    """Load a real bar window through P1 and bind a purged split onto it.

    The P1 bridge is injected and required, mirroring P1's own required
    archive::

        binder = ResearchTimestampSplitBinder(ResearchMarketDataBridge(archive))
        bound = binder.bind("BTCUSDT", "1h", window_start, window_end, spec)
        bound.status  # BindingStatus.BOUND_CLEAN / BOUND_WITH_FLAGGED_GAPS
    """

    def __init__(self, bridge: ResearchMarketDataBridge) -> None:
        if bridge is None:
            raise TimestampSplitBindingError(
                "bridge is required; a binder with no bridge has no bars to bind"
            )
        self.bridge = bridge

    def bind(
        self,
        symbol: str,
        timeframe: str,
        window_start: datetime,
        window_end: datetime,
        spec: SplitSpec,
    ) -> TimestampBoundSplit:
        """Split the window's real bars with ``make_purged_split`` and bind it.

        ``n_observations`` is the number of real bars returned, never P1's
        ``expected_count``. Propagates P1's own fail-closed errors and
        ``research.splitting.SplitError`` unchanged.
        """

        if not isinstance(spec, SplitSpec):
            raise SplitShapeError(f"spec must be a research.splitting.SplitSpec, got {spec!r}")

        access = self.bridge.load_window(symbol, timeframe, window_start, window_end)
        # Refuse before splitting: a refused window is not split at all.
        _refuse_unusable_coverage(access)
        split = make_purged_split(access.coverage.actual_count, spec)
        return bind_split_to_timestamps(split, access)


__all__ = [
    "BarSequenceIntegrityError",
    "BindingStatus",
    "Boundary",
    "BoundarySeparation",
    "BufferZone",
    "CoverageRefusedError",
    "GapBoundaryViolation",
    "GapStraddlesBoundaryError",
    "ResearchTimestampSplitBinder",
    "SplitShapeError",
    "TimestampBoundSplit",
    "TimestampSegment",
    "TimestampSplitBindingError",
    "Zone",
    "bind_split_to_timestamps",
]
