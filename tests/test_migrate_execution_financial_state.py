"""Regression lock: migrate_execution_financial_state.py - closed-sidecar
monotonic ordering and conflict-gate invariants.

This module provides focused, self-contained characterization tests for
the three invariants that are the reference implementation of the migration
tool's correctness contract:

  1. Monotonic ordering preservation - the deterministic archive sequence is
     always `sorted(closed_positions.items())`, regardless of the insertion
     order of position-ids in the source v1 map.
  2. Conflict-gate rejection - a pre-existing closed sidecar whose records
     diverge from the source (wrong sequence, wrong payload, or both) is
     refused before any write occurs; the v1 working file is left untouched.
  3. Idempotent resume - a pre-existing closed sidecar that is a valid
     monotonic prefix of this run's deterministic output is accepted, and
     only the missing tail is appended; the re-run is indistinguishable from
     a first-time run on the final state.

These invariants were introduced as the resolution of Defect H-1 (Package
6B / commit db8bdf3). The tests here form the regression lock so that
any future refactor that degrades monotonicity or weakens the sequence-
inclusive identity check fails immediately and locally.

Every fixture uses pytest's tmp_path; nothing here touches operator
runtime state.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.execution_portfolio_foundation import (
    SCHEMA_VERSION,
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    FinancialStateStore,
    mint_long_position_id,
)
import tools.migrate_execution_financial_state as migration_module

# ---------------------------------------------------------------------------
# Shared helpers (minimal, self-contained, do not depend on block5i helpers)
# ---------------------------------------------------------------------------

_NOW = datetime.now(UTC).isoformat()

_WORKING_FILE = migration_module.DEFAULT_WORKING_FILE
_APPLIED_FILE = migration_module.DEFAULT_APPLIED_FILE
_CLOSED_FILE = migration_module.DEFAULT_CLOSED_FILE


def _closed_record(position_id: str, *, gross_pnl: str = "5") -> dict:
    return {
        "position_id": position_id,
        "symbol": "BTCUSDT",
        "base_quantity": "0",
        "cost_quote": "100",
        "entry_fees": "0",
        "average_entry_price": "10",
        "mark_price": "11",
        "version": 1,
        "opened_at": _NOW,
        "status": "CLOSED",
        "exit_price": "11",
        "gross_pnl": gross_pnl,
        "closed_at": _NOW,
    }


def _pid(tag: str) -> str:
    return mint_long_position_id("BTCUSDT", f"req-{tag}")


def _write_v1(path: Path, *, closed_positions: dict | None = None,
               applied_executions: dict | None = None) -> None:
    payload = {
        "schema_version": 1, "transition": None,
        "cash": "1000", "reserved_capital": "0",
        "realized_gross_pnl": "0", "fees": "0", "positions": {},
        "closed_positions": closed_positions or {},
        "applied_executions": applied_executions or {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _working(tmp: Path) -> Path:
    return tmp / _WORKING_FILE


def _applied(tmp: Path) -> Path:
    return tmp / _APPLIED_FILE


def _closed(tmp: Path) -> Path:
    return tmp / _CLOSED_FILE


# ===========================================================================
# 1 - Monotonic ordering preservation
# ===========================================================================


def test_ordering_is_always_sorted_by_position_id_key(tmp_path):
    """The closed archive assigns sequence numbers in ascending
    lexicographic order of position_id regardless of v1 map iteration order.
    Regression guard for Defect H-1."""
    p_a = _pid("a")
    p_b = _pid("b")
    p_c = _pid("c")
    records = {p_a: _closed_record(p_a, gross_pnl="1"),
               p_b: _closed_record(p_b, gross_pnl="2"),
               p_c: _closed_record(p_c, gross_pnl="3")}
    reversed_map = dict(sorted(records.items(), reverse=True))
    _write_v1(_working(tmp_path), closed_positions=reversed_map)

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.MIGRATED
    assert result.closed_count == 3
    assert result.closed_appended == 3

    index = ClosedPositionArchiveStore(_closed(tmp_path)).load_index()
    assert index.count == 3
    expected_ordered_ids = sorted(records)
    for i, pid in enumerate(expected_ordered_ids):
        assert index.sequence_by_position_id[pid] == i
    assert index.tail_sequence == 2
    assert index.tail_position_id == expected_ordered_ids[-1]


def test_ordering_is_stable_across_independent_re_runs(tmp_path):
    """Two completely independent migration runs on the same source must
    produce archives with identical sequence assignments."""
    p_a, p_b, p_c = _pid("x"), _pid("y"), _pid("z")
    records = {p_a: _closed_record(p_a, gross_pnl="10"),
               p_b: _closed_record(p_b, gross_pnl="20"),
               p_c: _closed_record(p_c, gross_pnl="30")}

    dir1 = tmp_path / "run1"
    dir1.mkdir()
    _write_v1(_working(dir1), closed_positions=records)
    migration_module.migrate(dir1)

    dir2 = tmp_path / "run2"
    dir2.mkdir()
    _write_v1(_working(dir2), closed_positions=records)
    migration_module.migrate(dir2)

    idx1 = ClosedPositionArchiveStore(_closed(dir1)).load_index()
    idx2 = ClosedPositionArchiveStore(_closed(dir2)).load_index()
    assert idx1.sequence_by_position_id == idx2.sequence_by_position_id
    assert idx1.tail_sequence == idx2.tail_sequence
    assert idx1.tail_position_id == idx2.tail_position_id


def test_single_closed_position_is_always_sequence_zero(tmp_path):
    """A source with exactly one closed position must produce an archive
    with that record at sequence 0."""
    p = _pid("only")
    rec = _closed_record(p, gross_pnl="7")
    _write_v1(_working(tmp_path), closed_positions={p: rec})

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.MIGRATED

    index = ClosedPositionArchiveStore(_closed(tmp_path)).load_index()
    assert index.count == 1
    assert index.sequence_by_position_id[p] == 0
    assert index.tail_sequence == 0


# ===========================================================================
# 2 - Conflict-gate rejection
# ===========================================================================


def test_conflict_gate_rejects_record_at_wrong_sequence_before_any_write(tmp_path):
    """Pre-existing closed archive with valid payload at wrong sequence must
    be refused before any write. Source and closed sidecar unchanged."""
    p_a = _pid("alpha")
    p_b = _pid("beta")
    if p_a > p_b:
        p_a, p_b = p_b, p_a
    records = {p_a: _closed_record(p_a, gross_pnl="1"),
               p_b: _closed_record(p_b, gross_pnl="2")}
    _write_v1(_working(tmp_path), closed_positions=records)
    before_source = _working(tmp_path).read_bytes()

    # p_b belongs at sequence 1 but is written at sequence 0.
    ClosedPositionArchiveStore(_closed(tmp_path)).append(0, records[p_b])
    before_closed = _closed(tmp_path).read_bytes()

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.REFUSED_SIDECAR_CONFLICT
    assert result.reason_code == "CLOSED_SIDECAR_DOES_NOT_MATCH_SOURCE"
    assert _working(tmp_path).read_bytes() == before_source
    assert _closed(tmp_path).read_bytes() == before_closed
    assert not _applied(tmp_path).exists()


def test_conflict_gate_rejects_correct_sequence_but_wrong_payload(tmp_path):
    """Pre-existing closed archive with tampered payload at the correct
    sequence must be refused. Identity is (sequence, full_payload)."""
    p_a = _pid("gamma")
    p_b = _pid("delta")
    if p_a > p_b:
        p_a, p_b = p_b, p_a
    records = {p_a: _closed_record(p_a, gross_pnl="5"),
               p_b: _closed_record(p_b, gross_pnl="10")}
    _write_v1(_working(tmp_path), closed_positions=records)
    before_source = _working(tmp_path).read_bytes()

    tampered = dict(records[p_a])
    tampered["gross_pnl"] = "999"
    ClosedPositionArchiveStore(_closed(tmp_path)).append(0, tampered)
    before_closed = _closed(tmp_path).read_bytes()

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.REFUSED_SIDECAR_CONFLICT
    assert result.reason_code == "CLOSED_SIDECAR_DOES_NOT_MATCH_SOURCE"
    assert _working(tmp_path).read_bytes() == before_source
    assert _closed(tmp_path).read_bytes() == before_closed


def test_conflict_gate_rejects_unknown_position_id_in_pre_existing_sidecar(tmp_path):
    """Pre-existing closed archive holding a position_id absent from source
    v1 must be refused as not a valid prefix of the deterministic output."""
    p_source = _pid("source-only")
    p_rogue = _pid("not-in-source")
    records = {p_source: _closed_record(p_source, gross_pnl="3")}
    _write_v1(_working(tmp_path), closed_positions=records)
    before_source = _working(tmp_path).read_bytes()

    ClosedPositionArchiveStore(_closed(tmp_path)).append(0, _closed_record(p_rogue))
    before_closed = _closed(tmp_path).read_bytes()

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.REFUSED_SIDECAR_CONFLICT
    assert result.reason_code == "CLOSED_SIDECAR_DOES_NOT_MATCH_SOURCE"
    assert _working(tmp_path).read_bytes() == before_source
    assert _closed(tmp_path).read_bytes() == before_closed


# ===========================================================================
# 3 - Idempotent resume across partially written sidecar states
# ===========================================================================


def test_idempotent_resume_empty_sidecar_is_valid_prefix(tmp_path):
    """Empty-but-present closed sidecar is a valid empty prefix; all
    records are appended and the result is the complete archive."""
    p_a = _pid("ia")
    p_b = _pid("ib")
    records = {p_a: _closed_record(p_a, gross_pnl="1"),
               p_b: _closed_record(p_b, gross_pnl="2")}
    _write_v1(_working(tmp_path), closed_positions=records)
    _closed(tmp_path).write_text("", encoding="utf-8")

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.MIGRATED
    assert result.closed_count == 2
    assert result.closed_appended == 2

    index = ClosedPositionArchiveStore(_closed(tmp_path)).load_index()
    assert index.count == 2
    assert set(index.by_position_id) == {p_a, p_b}


def test_idempotent_resume_partial_prefix_appends_only_tail(tmp_path):
    """A pre-existing archive holding the first N records in correct
    monotonic order is accepted; only the missing tail is appended.
    Sequence assignments in the final archive are gapless 0..N-1."""
    p_a, p_b, p_c, p_d = _pid("ra"), _pid("rb"), _pid("rc"), _pid("rd")
    records = {
        p_a: _closed_record(p_a, gross_pnl="1"),
        p_b: _closed_record(p_b, gross_pnl="2"),
        p_c: _closed_record(p_c, gross_pnl="3"),
        p_d: _closed_record(p_d, gross_pnl="4"),
    }
    _write_v1(_working(tmp_path), closed_positions=records)

    ordered_ids = sorted(records)
    archive = ClosedPositionArchiveStore(_closed(tmp_path))
    archive.append(0, records[ordered_ids[0]])
    archive.append(1, records[ordered_ids[1]])

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.MIGRATED
    assert result.closed_count == 4
    assert result.closed_appended == 2

    index = archive.load_index()
    assert index.count == 4
    assert set(index.by_position_id) == set(records)
    for i, pid in enumerate(ordered_ids):
        assert index.sequence_by_position_id[pid] == i
    assert index.tail_sequence == 3


def test_idempotent_resume_complete_prefix_appends_nothing_to_closed(tmp_path):
    """When the closed sidecar already holds all records in the correct
    order, closed_appended==0 and the applied sidecar is still populated."""
    p_a, p_b = _pid("ca"), _pid("cb")
    records = {p_a: _closed_record(p_a), p_b: _closed_record(p_b)}
    _write_v1(_working(tmp_path), closed_positions=records,
               applied_executions={"exec-1": "key-1", "exec-2": "key-2"})

    ordered_ids = sorted(records)
    archive = ClosedPositionArchiveStore(_closed(tmp_path))
    archive.append(0, records[ordered_ids[0]])
    archive.append(1, records[ordered_ids[1]])

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.MIGRATED
    assert result.closed_appended == 0
    assert result.applied_count == 2
    assert result.applied_appended == 2

    working = json.loads(_working(tmp_path).read_text(encoding="utf-8"))
    assert working["schema_version"] == SCHEMA_VERSION
    assert working["closed_checkpoint"]["sequence"] == 1


def test_idempotent_full_rerun_on_v2_returns_already_migrated(tmp_path):
    """A second migration run against an already-v2 state returns
    ALREADY_MIGRATED and leaves all three files bit-for-bit unchanged."""
    p = _pid("once")
    _write_v1(_working(tmp_path),
               closed_positions={p: _closed_record(p)},
               applied_executions={"exec-x": "key-x"})

    r1 = migration_module.migrate(tmp_path)
    assert r1.outcome is migration_module.MigrationOutcome.MIGRATED

    before_working = _working(tmp_path).read_bytes()
    before_closed = _closed(tmp_path).read_bytes()
    before_applied = _applied(tmp_path).read_bytes()

    r2 = migration_module.migrate(tmp_path)
    assert r2.outcome is migration_module.MigrationOutcome.ALREADY_MIGRATED
    assert r2.reason_code == "SOURCE_ALREADY_V2"
    assert _working(tmp_path).read_bytes() == before_working
    assert _closed(tmp_path).read_bytes() == before_closed
    assert _applied(tmp_path).read_bytes() == before_applied


# ===========================================================================
# 4 - Cross-invariant composition
# ===========================================================================


def test_sorted_order_is_consistent_with_resume_conflict_check(tmp_path):
    """The conflict gate's reference order is the same sorted order a fresh
    run assigns. A valid partial prefix passes; the tail is appended in the
    same sorted order; the resulting archive is gapless."""
    p_a = _pid("compose-a")
    p_b = _pid("compose-b")
    p_c = _pid("compose-c")
    records = {p_a: _closed_record(p_a, gross_pnl="10"),
               p_b: _closed_record(p_b, gross_pnl="20"),
               p_c: _closed_record(p_c, gross_pnl="30")}
    ordered_ids = sorted(records)
    _write_v1(_working(tmp_path), closed_positions=records)

    archive = ClosedPositionArchiveStore(_closed(tmp_path))
    archive.append(0, records[ordered_ids[0]])

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.MIGRATED
    assert result.closed_appended == 2

    index = archive.load_index()
    assert index.count == 3
    for i, pid in enumerate(ordered_ids):
        assert index.sequence_by_position_id[pid] == i
    assert index.tail_sequence == 2
    assert index.tail_position_id == ordered_ids[2]
