"""P1 of the compute-engine proposal: read-only bar and coverage access.

Governance: registry v4.69, ``GRANT-COMPUTE-ENGINE-P1-BAR-ACCESS``, scoped
additive supersession of ``GRANT-COMPUTE-ENGINE-DEFER`` (v4.56/v4.57) for P1
only. P2 (applying ``research/splitting.py``'s purged splits to real
timestamps), P3 (producing ``research.hypothesis_registry.CheckResult``
objects for the five named checks) and P4 (everything else the original
proposal described) remain unauthorized and are not implemented here.

The shape this module occupies, following the precedent
``core/research_evidence_bridge.py`` established for the *other* direction
under ADR-0009::

    data_layer/market_data_archive_sqlite.py  (L2, already built, ADR-0006/0007)
          └─ archived bars + per-batch provenance
                              │
                              ▼  read by
    core/research_market_data_bridge.py       (L3 -- classify_module confirms L3
                                                 via the existing generic core/*
                                                 layer_rules pattern; no new rule
                                                 needed, unlike research/* before
                                                 ADR-0009)
          ├─ imports data_layer.market_data_archive_sqlite (L3 -> L2, allowed)
          └─ imports data_layer.contracts.StorageError      (L3 -> L1, allowed)

P1 stops here: this module produces bars plus a structured coverage report,
never a ``CheckResult``. It does **not** import ``research.hypothesis_registry``
-- that import is P3's concern, and importing it now would be exactly the
scope expansion this record's exclusions forbid.

**Not wired into the runtime.** Nothing in the runtime closure
(``core/application.py``, ``main.py``, ``web_app.py``, ``atlas_service.py``,
``atlas_supervisor.py``) imports this module. It is driven only by
``tools/inspect_research_market_data_coverage.py``, mirroring how
``tools/fetch_historical_market_data.py`` drives the archiver. Wiring
anything here into the runtime closure is W2, still not authorized.

The archive is injected as a constructor parameter, mirroring the established
``AtlasBrain`` / ``ResearchEvidenceBridge`` pattern. Unlike that bridge
(which treats its store as ``Any`` and never imports its module, because
ADR-0009's stricter line is about keeping ``research/`` itself unaware of
``data_layer``), this module is explicitly authorized to import
``data_layer.market_data_archive_sqlite`` directly -- L3 -> L2 is an allowed
edge, and P1 genuinely needs the real ``ArchivedBar`` and provenance types
rather than a duck-typed stand-in.

Gap policy (NB-4 analogue) -- COMPLETE / GAPS_PRESENT_FLAGGED /
GAPS_PRESENT_REFUSED
----------------------------------------------------------------------------
The denominator is always ``((window_end_ms - window_start_ms) //
interval_ms) + 1`` -- the requested window's own span divided by the
timeframe's bar width -- **never** ``len(bars_returned)``. This is the NB-5
analogue: a window that happens to return fewer bars than the archive
actually has recorded elsewhere must never be read as "no gap" merely
because nothing was returned to contradict it.

No gap is ever interpolated or silently treated as absent. Every requested
grid slot with no matching archived bar is surfaced as part of a
:class:`GapRange`, and the overall status is decided by a single,
threshold-free rule instead of an invented percentage cutoff:

* ``COMPLETE`` -- every expected slot in the window has an archived bar.
* ``GAPS_PRESENT_FLAGGED`` -- at least one slot is missing, but the whole
  requested window lies within ``[archive_first_open, archive_last_open]``
  for that symbol/timeframe. Every such gap is *interior*: the archiver has
  real fetched bars bracketing it on both sides, so the gap is a confirmed,
  bounded absence rather than data that simply has not been fetched yet.
* ``GAPS_PRESENT_REFUSED`` -- at least one slot is missing **and** the
  window extends past the archive's own first or last archived bar. The
  portion of the window beyond that edge is not evidence of a gap at all --
  it is indistinguishable from "not yet archived" -- so treating it with the
  same confidence as an interior gap would overstate what is actually known.
  This status is returned, not raised: the caller still receives every bar
  that *is* archived, but is told unambiguously not to treat the window as
  adequately covered.

A window with **zero** overlap with the archived range is a different,
harder failure and is raised rather than returned (see
:class:`WindowOutsideArchiveError`) -- there is nothing meaningful to hand
back for a window the archive never touched.
"""

from __future__ import annotations

import logging
import sqlite3

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

# L3 -> L1. The exception type only.
from data_layer.contracts import StorageError

# L3 -> L2. Explicitly authorized by registry v4.69's architecture
# constraints, unlike the evidence-bridge precedent which avoided importing
# its store's concrete module.
from data_layer.market_data_archive_sqlite import (
    ArchivedBar,
    MarketDataSQLiteStorage,
    timeframe_to_milliseconds,
)

logger = logging.getLogger("AtlasAI.ResearchMarketDataBridge")

#: Exceptions raised by the injected archive that this module treats as
#: "archive unreachable" rather than letting propagate raw. ``StorageError``
#: covers this repository's own storage-layer contract; ``OSError`` and
#: ``sqlite3.Error`` cover the lower-level failures (locked file, disk I/O, a
#: corrupt database) that a local SQLite backend can surface directly. Three
#: ``sqlite3.Error`` subclasses are deliberately excluded below --
#: ``ProgrammingError``, ``InterfaceError`` and ``NotSupportedError`` --
#: because they signal a defect in *this module's own query usage* (wrong
#: bind-parameter count/type, use of a closed connection, an unsupported
#: API call), never a genuinely unreachable or corrupt archive. Masking
#: those as "archive unreachable" would hide a real code bug behind a
#: message that tells the operator to blame the archive instead.
_ARCHIVE_FAILURE_TYPES = (StorageError, sqlite3.Error, OSError)
_ARCHIVE_FAILURE_EXCLUDED_SQLITE_TYPES = (
    sqlite3.ProgrammingError,
    sqlite3.InterfaceError,
    sqlite3.NotSupportedError,
)


class ResearchMarketDataBridgeError(RuntimeError):
    """Base for every fail-closed refusal in this module.

    Every path raising a subclass of this refuses to return fabricated,
    interpolated or silently-optimistic data. There is no code path in this
    module that fills a gap with a guessed value.
    """


class ArchiveUnreachableError(ResearchMarketDataBridgeError):
    """The injected archive could not be queried."""


class SymbolNotArchivedError(ResearchMarketDataBridgeError):
    """No bar has ever been archived for this (symbol, timeframe) pair."""


class WindowOutsideArchiveError(ResearchMarketDataBridgeError):
    """The requested window has zero overlap with what is archived."""


class MalformedWindowError(ResearchMarketDataBridgeError):
    """The requested symbol, timeframe or window bounds are not well-formed."""


class MalformedProvenanceError(ResearchMarketDataBridgeError):
    """A bar's stored provenance failed structural validation."""


class CoverageStatus(str, Enum):
    """The three-way status defined and justified in the module docstring."""

    COMPLETE = "COMPLETE"
    GAPS_PRESENT_FLAGGED = "GAPS_PRESENT_FLAGGED"
    GAPS_PRESENT_REFUSED = "GAPS_PRESENT_REFUSED"


@dataclass(frozen=True, slots=True)
class GapRange:
    """A run of consecutive missing grid slots within the requested window."""

    start_ms: int
    end_ms: int
    missing_bars: int

    @property
    def start(self) -> datetime:
        return _from_ms(self.start_ms)

    @property
    def end(self) -> datetime:
        return _from_ms(self.end_ms)


@dataclass(frozen=True, slots=True)
class ProvenanceSummary:
    """One distinct fetch batch contributing bars to the requested window."""

    batch_id: str
    source: str
    endpoint: str
    provider_version: str
    fetched_at: datetime
    checksum: str
    bar_count_in_window: int


@dataclass(frozen=True, slots=True)
class WindowCoverageReport:
    """Expected-vs-actual accounting for one requested symbol/timeframe/window."""

    symbol: str
    timeframe: str
    window_start_ms: int
    window_end_ms: int
    expected_count: int
    actual_count: int
    gap_ranges: tuple[GapRange, ...]
    provenance: tuple[ProvenanceSummary, ...]
    status: CoverageStatus

    @property
    def window_start(self) -> datetime:
        return _from_ms(self.window_start_ms)

    @property
    def window_end(self) -> datetime:
        return _from_ms(self.window_end_ms)

    @property
    def missing_count(self) -> int:
        return self.expected_count - self.actual_count


@dataclass(frozen=True, slots=True)
class WindowBarAccessResult:
    """The bars for a requested window, plus their coverage report."""

    bars: tuple[ArchivedBar, ...]
    coverage: WindowCoverageReport


def _from_ms(value_ms: int) -> datetime:
    return datetime.fromtimestamp(value_ms / 1000, tz=timezone.utc)


def _to_ms(value: datetime, field_name: str) -> int:
    if not isinstance(value, datetime):
        raise MalformedWindowError(
            f"{field_name} must be a datetime, got {value!r}"
        )
    if value.tzinfo is None:
        raise MalformedWindowError(
            f"{field_name} must be timezone-aware, got naive {value!r}"
        )
    return round(value.timestamp() * 1000)


class ResearchMarketDataBridge:
    """P1 read-only access to archived bars over a requested window.

    The archive is injected and required, mirroring ``ResearchEvidenceBridge``'s
    conservative default: this module sits on no decision path, so a missing
    archive is a misconstructed bridge, refused at construction, rather than
    a degraded one that would silently return empty results forever::

        bridge = ResearchMarketDataBridge(archive)
        result = bridge.load_window("BTCUSDT", "1h", window_start, window_end)
        result.coverage.status  # CoverageStatus.COMPLETE / _FLAGGED / _REFUSED
    """

    def __init__(self, archive: MarketDataSQLiteStorage) -> None:
        if archive is None:
            raise ResearchMarketDataBridgeError(
                "archive is required; a bridge with no archive would have "
                "nothing to read"
            )
        self.archive = archive

    def load_window(
        self,
        symbol: str,
        timeframe: str,
        window_start: datetime,
        window_end: datetime,
    ) -> WindowBarAccessResult:
        """Return archived bars for ``[window_start, window_end]`` plus coverage.

        Fails closed -- raises rather than returning fabricated or optimistic
        data -- on: a malformed symbol/timeframe/window, an unreachable
        archive, a (symbol, timeframe) pair with no archived history at all,
        and a window with zero overlap with what is archived. A window that
        partially overlaps the archive, or that lies fully within it but
        contains a confirmed interior gap, is returned normally with its
        ``coverage.status`` set per the policy documented on this module.
        """

        if not isinstance(symbol, str) or not symbol.strip():
            raise MalformedWindowError(
                f"symbol must be a non-empty string, got {symbol!r}"
            )
        if not isinstance(timeframe, str) or not timeframe.strip():
            raise MalformedWindowError(
                f"timeframe must be a non-empty string, got {timeframe!r}"
            )

        try:
            interval_ms = timeframe_to_milliseconds(timeframe)
        except StorageError as exc:
            raise MalformedWindowError(str(exc)) from exc

        window_start_ms = _to_ms(window_start, "window_start")
        window_end_ms = _to_ms(window_end, "window_end")

        if window_end_ms < window_start_ms:
            raise MalformedWindowError(
                f"window_end ({window_end.isoformat()}) precedes window_start "
                f"({window_start.isoformat()})"
            )
        if window_start_ms % interval_ms != 0 or window_end_ms % interval_ms != 0:
            raise MalformedWindowError(
                f"window bounds must align to the {timeframe} bar grid "
                f"(epoch-ms multiple of {interval_ms}); got "
                f"window_start_ms={window_start_ms} window_end_ms={window_end_ms}"
            )

        # NB-5 analogue: the denominator is the requested window's own span
        # divided by the timeframe, computed before a single bar is read and
        # never touched again -- it cannot be influenced by how many bars
        # the archive happens to return.
        expected_count = ((window_end_ms - window_start_ms) // interval_ms) + 1

        archive_coverage = self._call_archive(
            "coverage", self.archive.coverage, symbol, timeframe
        )

        if archive_coverage.first_open_time_ms is None:
            raise SymbolNotArchivedError(
                f"no bar has ever been archived for {symbol} {timeframe}"
            )

        archive_first_ms = archive_coverage.first_open_time_ms
        archive_last_ms = archive_coverage.last_open_time_ms

        if window_end_ms < archive_first_ms or window_start_ms > archive_last_ms:
            raise WindowOutsideArchiveError(
                f"requested window [{window_start.isoformat()}, "
                f"{window_end.isoformat()}] has no overlap with the archived "
                f"range for {symbol} {timeframe} "
                f"[{_from_ms(archive_first_ms).isoformat()}, "
                f"{_from_ms(archive_last_ms).isoformat()}]"
            )

        bars = self._call_archive(
            "get_bars",
            self.archive.get_bars,
            symbol,
            timeframe,
            start_ms=window_start_ms,
            end_ms=window_end_ms,
        )

        actual_open_times = {bar.open_time_ms for bar in bars}
        actual_count = len(bars)

        gap_ranges = _compute_gap_ranges(
            window_start_ms, window_end_ms, interval_ms, actual_open_times
        )

        edge_exceeded = (
            window_start_ms < archive_first_ms or window_end_ms > archive_last_ms
        )

        if not gap_ranges:
            status = CoverageStatus.COMPLETE
        elif edge_exceeded:
            status = CoverageStatus.GAPS_PRESENT_REFUSED
        else:
            status = CoverageStatus.GAPS_PRESENT_FLAGGED

        provenance = self._provenance_summary(symbol, timeframe, bars)

        coverage = WindowCoverageReport(
            symbol=symbol,
            timeframe=timeframe,
            window_start_ms=window_start_ms,
            window_end_ms=window_end_ms,
            expected_count=expected_count,
            actual_count=actual_count,
            gap_ranges=gap_ranges,
            provenance=provenance,
            status=status,
        )

        return WindowBarAccessResult(bars=bars, coverage=coverage)

    def _call_archive(self, operation: str, method: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs)
        except _ARCHIVE_FAILURE_EXCLUDED_SQLITE_TYPES:
            # A defect in this module's own query usage, not an unreachable
            # or corrupt archive. Propagate as-is rather than mislabeling it.
            raise
        except _ARCHIVE_FAILURE_TYPES as exc:
            raise ArchiveUnreachableError(
                f"archive is unreachable during {operation}: {exc}"
            ) from exc

    def _provenance_summary(
        self, symbol: str, timeframe: str, bars: tuple[ArchivedBar, ...]
    ) -> tuple[ProvenanceSummary, ...]:
        seen: dict[str, Any] = {}
        counts: dict[str, int] = {}

        for bar in bars:
            batch = self._call_archive(
                "provenance_for_bar",
                self.archive.provenance_for_bar,
                symbol,
                timeframe,
                bar.open_time_ms,
            )

            if batch is None:
                raise MalformedProvenanceError(
                    f"bar {symbol} {timeframe} at {bar.open_time_ms} is "
                    f"archived but carries no provenance batch"
                )

            counts[batch.batch_id] = counts.get(batch.batch_id, 0) + 1
            if batch.batch_id in seen:
                continue

            for field_name, value in (
                ("source", batch.source),
                ("endpoint", batch.endpoint),
                ("provider_version", batch.provider_version),
                ("checksum", batch.checksum),
            ):
                if not isinstance(value, str) or not value.strip():
                    raise MalformedProvenanceError(
                        f"batch {batch.batch_id} has malformed {field_name}: "
                        f"{value!r}"
                    )
            if not isinstance(batch.fetched_at, datetime) or batch.fetched_at.tzinfo is None:
                raise MalformedProvenanceError(
                    f"batch {batch.batch_id} fetched_at is not a "
                    f"timezone-aware datetime: {batch.fetched_at!r}"
                )

            seen[batch.batch_id] = batch

        return tuple(
            ProvenanceSummary(
                batch_id=batch.batch_id,
                source=batch.source,
                endpoint=batch.endpoint,
                provider_version=batch.provider_version,
                fetched_at=batch.fetched_at,
                checksum=batch.checksum,
                bar_count_in_window=counts[batch.batch_id],
            )
            for batch in seen.values()
        )


def _compute_gap_ranges(
    window_start_ms: int,
    window_end_ms: int,
    interval_ms: int,
    actual_open_times: set[int],
) -> tuple[GapRange, ...]:
    """Walk the requested window's own grid, independent of what is archived.

    This is deliberately not derived from :meth:`MarketDataSQLiteStorage.coverage`,
    which only ever reports gaps *between two archived bars* over the whole
    archive. A window whose edge falls before the first archived bar or after
    the last would be invisible to that method entirely; walking the
    requested grid directly is what lets an edge-exceeding gap be reported at
    all, which is what :data:`CoverageStatus.GAPS_PRESENT_REFUSED` depends on.
    """

    gaps: list[GapRange] = []
    run_start: int | None = None
    run_end: int | None = None

    slot = window_start_ms
    while slot <= window_end_ms:
        if slot in actual_open_times:
            if run_start is not None:
                gaps.append(
                    GapRange(
                        start_ms=run_start,
                        end_ms=run_end,
                        missing_bars=((run_end - run_start) // interval_ms) + 1,
                    )
                )
                run_start = None
                run_end = None
        else:
            if run_start is None:
                run_start = slot
            run_end = slot
        slot += interval_ms

    if run_start is not None:
        gaps.append(
            GapRange(
                start_ms=run_start,
                end_ms=run_end,
                missing_bars=((run_end - run_start) // interval_ms) + 1,
            )
        )

    return tuple(gaps)


__all__ = [
    "ArchiveUnreachableError",
    "CoverageStatus",
    "GapRange",
    "MalformedProvenanceError",
    "MalformedWindowError",
    "ProvenanceSummary",
    "ResearchMarketDataBridge",
    "ResearchMarketDataBridgeError",
    "SymbolNotArchivedError",
    "WindowBarAccessResult",
    "WindowCoverageReport",
    "WindowOutsideArchiveError",
]
