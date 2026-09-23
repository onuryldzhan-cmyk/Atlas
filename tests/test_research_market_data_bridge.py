"""Contract tests for the P1 archive-to-window bar/coverage bridge.

Governance: registry v4.69, ``GRANT-COMPUTE-ENGINE-P1-BAR-ACCESS``. These
tests pin the properties that record's Step 4 requires:

* **NB-5 analogue.** ``expected_count`` is always the requested window's own
  span divided by the timeframe -- never ``len(bars_returned)`` -- proven by
  a case where the two formulas would disagree.
* **NB-4 analogue.** A gap is never silently treated as "no gap": every
  missing grid slot in the requested window surfaces in ``gap_ranges``, and
  the three-way ``status`` (COMPLETE / GAPS_PRESENT_FLAGGED /
  GAPS_PRESENT_REFUSED) is exercised for the whole-window case, the
  sub-window-boundary case, and the archive-edge case.
* **Nothing is invented.** Every fail-closed path -- archive unreachable, a
  symbol never archived, a window with zero overlap, malformed provenance --
  is exercised and proven to never return fabricated or interpolated data.
* **The boundary holds.** A static check mirrors
  ``tests/test_research_evidence_bridge.py``'s guard from the other side:
  this module must never import ``research.hypothesis_registry`` (that is
  P3's concern), while it is explicitly expected -- unlike the evidence
  bridge -- to import ``data_layer.market_data_archive_sqlite`` directly.

Every test uses a real :class:`MarketDataSQLiteStorage` on pytest's
``tmp_path`` with synthetic, deterministic bars. Nothing here reads or
writes the real archive at ``C:\\AtlasState\\market_archive`` or any other
configured durable root.
"""

from __future__ import annotations

import ast
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.research_market_data_bridge import (
    ArchiveUnreachableError,
    CoverageStatus,
    MalformedProvenanceError,
    MalformedWindowError,
    ResearchMarketDataBridge,
    ResearchMarketDataBridgeError,
    SymbolNotArchivedError,
    WindowOutsideArchiveError,
)
from data_layer.market_data_archive_sqlite import (
    ArchivedBar,
    FetchBatch,
    MarketDataSQLiteStorage,
    timeframe_to_milliseconds,
)


SYMBOL = "BTCUSDT"
TIMEFRAME = "1h"
H = timeframe_to_milliseconds(TIMEFRAME)
FETCHED_AT = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)


def slot_ms(index: int) -> int:
    """The epoch-ms open time of the ``index``-th hourly slot from epoch 0."""
    return index * H


def slot_dt(index: int) -> datetime:
    return datetime.fromtimestamp(slot_ms(index) / 1000, tz=UTC)


def make_bar(index: int, *, symbol: str = SYMBOL, timeframe: str = TIMEFRAME) -> ArchivedBar:
    return ArchivedBar(
        symbol=symbol,
        timeframe=timeframe,
        open_time_ms=slot_ms(index),
        close_time_ms=slot_ms(index) + H - 1,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
    )


def store_slots(
    storage: MarketDataSQLiteStorage,
    indices: list[int],
    *,
    symbol: str = SYMBOL,
    timeframe: str = TIMEFRAME,
    source: str = "binance",
    endpoint: str = "/api/v3/klines",
    provider_version: str = "v1",
    fetched_at: datetime = FETCHED_AT,
) -> FetchBatch:
    bars = tuple(make_bar(i, symbol=symbol, timeframe=timeframe) for i in indices)
    batch = FetchBatch(
        source=source,
        endpoint=endpoint,
        provider_version=provider_version,
        symbol=symbol,
        timeframe=timeframe,
        fetched_at=fetched_at,
        bars=bars,
    )
    storage.store_batch(batch)
    return batch


@pytest.fixture
def storage(tmp_path: Path) -> MarketDataSQLiteStorage:
    store = MarketDataSQLiteStorage(tmp_path / "market_data.sqlite3")
    store.open()
    yield store
    store.close()


@pytest.fixture
def bridge(storage: MarketDataSQLiteStorage) -> ResearchMarketDataBridge:
    return ResearchMarketDataBridge(storage)


# --- construction ----------------------------------------------------------


def test_archive_is_required():
    with pytest.raises(ResearchMarketDataBridgeError):
        ResearchMarketDataBridge(None)


def test_archive_is_held_as_given(storage: MarketDataSQLiteStorage):
    assert ResearchMarketDataBridge(storage).archive is storage


# --- (a) zero gaps -> COMPLETE ---------------------------------------------


def test_full_contiguous_window_is_complete(bridge, storage):
    store_slots(storage, list(range(0, 10)))

    result = bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(9))

    assert result.coverage.status == CoverageStatus.COMPLETE
    assert result.coverage.expected_count == 10
    assert result.coverage.actual_count == 10
    assert result.coverage.expected_count == result.coverage.actual_count
    assert result.coverage.gap_ranges == ()
    assert len(result.bars) == 10


# --- (b) a real gap is never silently COMPLETE -----------------------------


def test_interior_gap_is_never_reported_as_complete(bridge, storage):
    # Archive covers the whole window on both sides of the gap, so the gap
    # is confirmed and bounded -- FLAGGED, not REFUSED.
    store_slots(storage, [0, 1, 2, 5, 6, 7, 8, 9])

    result = bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(9))

    assert result.coverage.status != CoverageStatus.COMPLETE
    assert result.coverage.status == CoverageStatus.GAPS_PRESENT_FLAGGED
    assert result.coverage.gap_ranges == (
        _gap(3, 4),
    )


def _gap(start_index: int, end_index: int):
    from core.research_market_data_bridge import GapRange

    return GapRange(
        start_ms=slot_ms(start_index),
        end_ms=slot_ms(end_index),
        missing_bars=end_index - start_index + 1,
    )


# --- (c) NB-5 analogue: denominator is span/timeframe, never len(bars) ----


def test_expected_count_is_window_span_never_len_bars_returned(bridge, storage):
    # Slots 7, 8, 9 are missing at the tail; a wrong implementation using
    # len(bars_returned) as the denominator would compute expected == actual
    # == 7 and report a false COMPLETE. The archive's own last bar is slot 6,
    # so the window's tail also exceeds the archive edge (REFUSED), but the
    # property under test is the *count*, independent of the status label.
    store_slots(storage, list(range(0, 7)))

    result = bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(9))

    wrong_denominator_a_buggy_implementation_would_use = len(result.bars)
    assert wrong_denominator_a_buggy_implementation_would_use == 7

    assert result.coverage.expected_count == 10
    assert result.coverage.expected_count != wrong_denominator_a_buggy_implementation_would_use
    assert result.coverage.actual_count == 7
    assert result.coverage.missing_count == 3
    assert result.coverage.status != CoverageStatus.COMPLETE


def test_expected_count_formula_is_independent_of_archive_contents(tmp_path):
    """Same requested window, same expected_count, across two genuinely
    different archive fill levels -- a sparse archive and a fully populated
    one -- proving expected_count is a pure function of the window and
    timeframe, not of how much data happens to be archived.
    """
    sparse_storage = MarketDataSQLiteStorage(tmp_path / "sparse.sqlite3")
    sparse_storage.open()
    store_slots(sparse_storage, [0, 5, 9])  # only 3 of 10 slots archived

    full_storage = MarketDataSQLiteStorage(tmp_path / "full.sqlite3")
    full_storage.open()
    store_slots(full_storage, list(range(0, 10)))  # all 10 slots archived

    try:
        sparse_result = ResearchMarketDataBridge(sparse_storage).load_window(
            SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(9)
        )
        full_result = ResearchMarketDataBridge(full_storage).load_window(
            SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(9)
        )
    finally:
        sparse_storage.close()
        full_storage.close()

    assert sparse_result.coverage.expected_count == full_result.coverage.expected_count == 10
    assert sparse_result.coverage.actual_count == 3
    assert full_result.coverage.actual_count == 10
    assert sparse_result.coverage.actual_count != full_result.coverage.actual_count


# --- (d) a gap intersecting a requested sub-window boundary ---------------


def test_gap_fully_contained_in_a_sub_window_of_a_larger_archive(bridge, storage):
    # Archive spans slots 0..19 with an interior gap at 8..10. The requested
    # window [5, 14] is a strict sub-window of the archive, not the whole
    # thing, and its own bounds sit inside the archived range on both sides.
    indices = [i for i in range(0, 20) if i not in (8, 9, 10)]
    store_slots(storage, indices)

    result = bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(5), slot_dt(14))

    assert result.coverage.expected_count == 10
    assert result.coverage.actual_count == 7
    assert result.coverage.gap_ranges == (_gap(8, 10),)
    assert result.coverage.status == CoverageStatus.GAPS_PRESENT_FLAGGED


def test_archive_level_gap_extending_past_the_sub_window_boundary_is_clipped(bridge, storage):
    # The archive's gap is slots 3..6 (4 missing), which starts BEFORE the
    # requested window and ends INSIDE it. Only the portion intersecting the
    # requested window [5, 15] may be reported -- slots 3 and 4 are outside
    # the request and must not appear in gap_ranges.
    indices = [i for i in range(0, 20) if i not in (3, 4, 5, 6)]
    store_slots(storage, indices)

    result = bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(5), slot_dt(15))

    assert result.coverage.gap_ranges == (_gap(5, 6),)
    assert result.coverage.status == CoverageStatus.GAPS_PRESENT_FLAGGED


def test_window_edge_exceeding_the_archive_is_refused_not_flagged(bridge, storage):
    # Archive only goes up to slot 9; the window asks through slot 14. Slots
    # 10..14 are not a confirmed gap -- they are simply unarchived -- so the
    # whole window must come back REFUSED, not FLAGGED.
    store_slots(storage, list(range(0, 10)))

    result = bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(14))

    assert result.coverage.status == CoverageStatus.GAPS_PRESENT_REFUSED
    assert result.coverage.gap_ranges == (_gap(10, 14),)
    # The bars that ARE archived are still returned -- REFUSED withholds
    # confidence, it does not withhold data the caller already has a right to.
    assert result.coverage.actual_count == 10
    assert len(result.bars) == 10


def test_window_starting_before_the_archive_is_also_refused(bridge, storage):
    store_slots(storage, list(range(5, 15)))

    result = bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(9))

    assert result.coverage.status == CoverageStatus.GAPS_PRESENT_REFUSED
    assert result.coverage.gap_ranges == (_gap(0, 4),)


# --- (e) fail-closed paths --------------------------------------------------


def test_archive_unreachable_is_never_silently_treated_as_empty(tmp_path):
    unopened = MarketDataSQLiteStorage(tmp_path / "never_opened.sqlite3")
    bridge_over_unopened = ResearchMarketDataBridge(unopened)

    with pytest.raises(ArchiveUnreachableError):
        bridge_over_unopened.load_window(SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(9))


def test_archive_unreachable_wraps_sqlite_errors_too():
    class ExplodingArchive:
        def coverage(self, symbol, timeframe):
            raise sqlite3.OperationalError("disk I/O error")

    with pytest.raises(ArchiveUnreachableError):
        ResearchMarketDataBridge(ExplodingArchive()).load_window(
            SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(9)
        )


def test_symbol_never_archived_is_refused(bridge, storage):
    store_slots(storage, [0, 1, 2], symbol="ETHUSDT")

    with pytest.raises(SymbolNotArchivedError):
        bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(9))


def test_window_entirely_outside_archived_range_raises(bridge, storage):
    store_slots(storage, list(range(100, 110)))

    with pytest.raises(WindowOutsideArchiveError):
        bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(9))


def test_window_entirely_after_archived_range_raises(bridge, storage):
    store_slots(storage, list(range(0, 10)))

    with pytest.raises(WindowOutsideArchiveError):
        bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(100), slot_dt(109))


def test_malformed_provenance_empty_source_is_refused(bridge, storage):
    store_slots(storage, [0, 1, 2], source="")

    with pytest.raises(MalformedProvenanceError):
        bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(2))


def test_malformed_provenance_empty_endpoint_is_refused(bridge, storage):
    store_slots(storage, [0, 1, 2], endpoint="   ")

    with pytest.raises(MalformedProvenanceError):
        bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(2))


def test_unsupported_timeframe_is_a_malformed_window(bridge, storage):
    with pytest.raises(MalformedWindowError):
        bridge.load_window(SYMBOL, "1M", slot_dt(0), slot_dt(9))


def test_empty_symbol_is_malformed(bridge, storage):
    with pytest.raises(MalformedWindowError):
        bridge.load_window("", TIMEFRAME, slot_dt(0), slot_dt(9))


def test_window_end_before_window_start_is_malformed(bridge, storage):
    with pytest.raises(MalformedWindowError):
        bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(9), slot_dt(0))


def test_naive_window_start_is_malformed(bridge, storage):
    naive = datetime(2026, 1, 1)
    with pytest.raises(MalformedWindowError):
        bridge.load_window(SYMBOL, TIMEFRAME, naive, slot_dt(9))


def test_naive_window_end_is_malformed(bridge, storage):
    naive = datetime(2026, 1, 1)
    with pytest.raises(MalformedWindowError):
        bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(0), naive)


def test_misaligned_window_bounds_are_malformed(bridge, storage):
    misaligned = slot_dt(0).replace(minute=30)
    with pytest.raises(MalformedWindowError):
        bridge.load_window(SYMBOL, TIMEFRAME, misaligned, slot_dt(9))


# --- provenance surfacing ---------------------------------------------------


def test_provenance_summary_covers_multiple_batches(bridge, storage):
    first = store_slots(
        storage, [0, 1, 2], source="binance", endpoint="/api/v3/klines", provider_version="v1"
    )
    second = store_slots(
        storage,
        [3, 4],
        source="binance",
        endpoint="/api/v3/klines",
        provider_version="v2",
        fetched_at=datetime(2026, 9, 24, tzinfo=UTC),
    )

    result = bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(4))

    batch_ids = {item.batch_id for item in result.coverage.provenance}
    assert batch_ids == {first.batch_id, second.batch_id}

    by_id = {item.batch_id: item for item in result.coverage.provenance}
    assert by_id[first.batch_id].bar_count_in_window == 3
    assert by_id[second.batch_id].bar_count_in_window == 2
    assert by_id[second.batch_id].provider_version == "v2"
    assert by_id[second.batch_id].fetched_at == datetime(2026, 9, 24, tzinfo=UTC)


def test_provenance_checksum_and_source_are_surfaced(bridge, storage):
    batch = store_slots(storage, [0, 1, 2])

    result = bridge.load_window(SYMBOL, TIMEFRAME, slot_dt(0), slot_dt(2))

    assert len(result.coverage.provenance) == 1
    surfaced = result.coverage.provenance[0]
    assert surfaced.checksum == batch.checksum
    assert surfaced.source == "binance"
    assert surfaced.endpoint == "/api/v3/klines"


# --- architecture boundary ---------------------------------------------------


def test_module_never_imports_hypothesis_registry_p3_boundary():
    """P1 must not reach into P3's concern (CheckResult production).

    Mirrors ``tests/test_research_evidence_bridge.py``'s
    ``test_the_bridge_never_imports_the_store_it_writes_to`` from the other
    side of the boundary: that test pins the evidence bridge never importing
    its L2 store's module; this pins the P1 module never importing
    ``research.hypothesis_registry`` at all, which registry v4.69's
    exclusions explicitly forbid for this package.
    """
    source = Path("core/research_market_data_bridge.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)

    assert not any(name.startswith("research.") or name == "research" for name in imported)
    assert not any(name.startswith("research.splitting") for name in imported)
    # Unlike the evidence bridge, this module IS explicitly authorized (and
    # required) to import the L2 archive module directly.
    assert "data_layer.market_data_archive_sqlite" in imported
    assert "data_layer.contracts.StorageError" in imported


def test_module_classifies_as_l3_via_the_existing_core_rule():
    import json
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from tools.build_architecture_inventory import classify_module

    with open(repo_root / "packaging" / "atlas_architecture_map.json", encoding="utf-8") as f:
        layer_rules = json.load(f)["layer_rules"]

    assert classify_module("core/research_market_data_bridge.py", layer_rules) == "L3"
