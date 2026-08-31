"""Block 5H: capital reservation working set & immutable archive.

Block 5F (``docs/evidence/block5f_freeze_evidence.md``) fixed live-encumbrance
double counting but explicitly deferred its own finding F4: the reservation
working-set file never removes a COMMITTED or RELEASED record, so it grows
by one entry per reservation for the runtime's entire lifetime with no
compaction or archival.

The naive fix - just deleting a terminal record from the working set once it
settles - has a defect of its own (recorded here as B5H-3, discovered during
this package's own design work, the same way 5F's F3/F4/F5 were): collision
detection in ``CapitalReservationLedger.reserve()`` only ever consulted the
live working set. Delete a COMMITTED/RELEASED record outright and its
reservation_id becomes free again - a replayed or reused id could re-arm as
a brand-new RESERVED reservation with no collision, silently re-entering a
transaction the system had already settled.

This package closes both: terminal records move to an immutable,
append-only archive (``core/capital_reservation.py``:
``ReservationArchiveStore``) instead of being deleted, so the working file's
size depends only on currently-live (RESERVED/INDETERMINATE) records
(closing F4), and ``CapitalReservationLedger.get()``/``reserve()`` both
read through the archive (closing B5H-3: an archived id can never be
re-created as RESERVED, and stays queryable forever).

Every fixture writes into pytest's tmp_path. Nothing here may touch the
operator's real runtime state.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from core.capital_reservation import (
    CapitalReservation,
    CapitalReservationLedger,
    JsonReservationStore,
    ReservationArchiveConflictError,
    ReservationArchiveCorruptError,
    ReservationArchiveStore,
    ReservationSchemaMigrationRequiredError,
    ReservationStatus,
)
from core.financial_state_bootstrap import BootstrapOutcome, bootstrap_financial_state

import tools.migrate_capital_reservations as migration_module

from tests.test_block5c_upstream_sizing_authority import application as build_flat_app
from tests.test_block5c_upstream_sizing_authority import buy_decision

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
MIGRATE_CLI_PATH = REPOSITORY_ROOT / "tools" / "migrate_capital_reservations.py"


# --------------------------------------------------------------------------
# shared fixtures / helpers - real production classes, tmp_path state only
# --------------------------------------------------------------------------


def _ledger(tmp_path, *, name: str = "reservations", archive_name: str = "archive",
            total: str = "1000"):
    store = JsonReservationStore(tmp_path / f"{name}.json")
    store.initialize_empty()
    archive = ReservationArchiveStore(tmp_path / f"{archive_name}.jsonl")
    return CapitalReservationLedger(store, D(total), archive=archive), store, archive


def _write_v1_file(path: Path, records: list[CapitalReservation]) -> None:
    payload = {
        "schema": "atlas-capital-reservations-v1",
        "reservations": [record.to_dict() for record in records],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def run_migrate_cli(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MIGRATE_CLI_PATH), *arguments],
        capture_output=True, text=True, cwd=str(REPOSITORY_ROOT),
    )


# ===========================================================================
# A/B/C/D - archival by status (section 10)
# ===========================================================================


def test_a_committed_moves_to_archive_and_get_returns_exact_record(tmp_path):
    ledger, store, archive = _ledger(tmp_path)
    ledger.reserve("a1", "req-a1", D("100"))
    ledger.commit("a1", D("96"))

    assert ledger.compact() == 1
    assert all(item.reservation_id != "a1" for item in store.load())

    reservation = ledger.get("a1")
    assert reservation.status is ReservationStatus.COMMITTED
    assert reservation.amount == D("96")
    assert reservation.request_id == "req-a1"
    assert archive.load_index()["a1"] == reservation


def test_b_released_moves_to_archive_and_remains_exact(tmp_path):
    ledger, store, archive = _ledger(tmp_path)
    ledger.reserve("b1", "req-b1", D("50"))
    ledger.release("b1")

    assert ledger.compact() == 1
    assert all(item.reservation_id != "b1" for item in store.load())

    reservation = ledger.get("b1")
    assert reservation.status is ReservationStatus.RELEASED
    assert reservation.amount == D("50")
    assert archive.load_index()["b1"] == reservation


def test_c_reserved_never_archives(tmp_path):
    ledger, store, archive = _ledger(tmp_path)
    ledger.reserve("c1", "req-c1", D("50"))

    assert ledger.compact() == 0
    assert ledger.get("c1").status is ReservationStatus.RESERVED
    assert archive.load_index() == {}
    assert len(store.load()) == 1


def test_d_indeterminate_never_archives_and_still_encumbers(tmp_path):
    ledger, store, archive = _ledger(tmp_path, total="1000")
    ledger.reserve("d1", "req-d1", D("300"))
    ledger.mark_indeterminate("d1")

    assert ledger.compact() == 0
    assert ledger.get("d1").status is ReservationStatus.INDETERMINATE
    assert ledger.active_reserved_capital() == D("300")
    assert ledger.available == D("700")
    assert archive.load_index() == {}
    assert len(store.load()) == 1


# ===========================================================================
# E - archive-aware collision protection
# ===========================================================================


def test_e_archive_aware_collision_blocks_reserve_without_changing_available(tmp_path):
    ledger, _, _ = _ledger(tmp_path, total="1000")
    ledger.reserve("e1", "req-e1", D("100"))
    ledger.commit("e1", D("96"))
    ledger.compact()

    available_before = ledger.available
    assert available_before == D("1000")

    with pytest.raises(ValueError, match="already archived"):
        ledger.reserve("e1", "req-e1", D("100"))
    assert ledger.available == available_before

    # Unlike a working-set collision, there is no idempotent same
    # -request/same-amount carve-out for an archived id.
    with pytest.raises(ValueError, match="already archived"):
        ledger.reserve("e1", "different-request", D("999"))
    assert ledger.available == available_before


# ===========================================================================
# F - MarketLoop sizing replay conflict against an archive-only historical
#     reservation
# ===========================================================================


def test_f_sizing_replay_conflict_detected_against_archived_reservation(tmp_path):
    app = build_flat_app(tmp_path)
    app.execution.start()
    manager = app.execution
    request_id = "archived-replay"

    first_decision = buy_decision(amount=0, metadata={}, request_id=request_id)
    refusal = app.market_loop._apply_position_sizing("BUY", first_decision, request_id)
    assert refusal is None

    request = manager.build_request(first_decision)
    admission = manager.risk_check(request)
    assert admission["approved"] is True

    manager.reservation_ledger.commit(request_id)
    reserved_amount = manager.reservation_ledger.get(request_id).amount
    assert manager.reservation_ledger.compact() == 1

    # Genuinely archive-only now: absent from the live working file.
    assert all(item.reservation_id != request_id
               for item in manager.reservation_ledger.store.load())
    assert manager.reservation_ledger.get(request_id).status is ReservationStatus.COMMITTED

    # Encumber unrelated capital so a fresh proposal for the same request
    # identity now prices differently than the archived amount.
    manager.reservation_ledger.reserve("unrelated", "unrelated", D("1"))

    replay_decision = buy_decision(amount=0, metadata={}, request_id=request_id)
    replay_refusal = app.market_loop._apply_position_sizing("BUY", replay_decision, request_id)

    assert replay_refusal is not None
    assert replay_refusal["reason"] == "SIZING_REPLAY_CONFLICT"
    assert replay_refusal["details"]["reserved_amount"] == format(reserved_amount, "f")


# ===========================================================================
# G/H - restart and interrupted-compaction tolerance
# ===========================================================================


def test_g_restart_after_compact_preserves_exact_historical_record(tmp_path):
    ledger, store, archive = _ledger(tmp_path, total="1000")
    ledger.reserve("g1", "req-g1", D("200"))
    ledger.commit("g1", D("180"))
    ledger.compact()

    reloaded = CapitalReservationLedger(store, D("1000"), archive=archive)
    assert reloaded.ready is True
    record = reloaded.get("g1")
    assert record.status is ReservationStatus.COMMITTED
    assert record.amount == D("180")
    assert record.request_id == "req-g1"
    assert reloaded.available == D("1000")


def test_h_interrupted_compaction_same_record_both_places_restarts_healthy(tmp_path):
    ledger, store, archive = _ledger(tmp_path, total="1000")
    ledger.reserve("h1", "req-h1", D("150"))
    committed = ledger.commit("h1", D("140"))

    # Simulate a crash between archive durability and the working-set
    # rewrite: the archive append happened, but the working-set file was
    # never rewritten to drop the record.
    archive.append(committed)

    reloaded = CapitalReservationLedger(store, D("1000"), archive=archive)
    assert reloaded.ready is True
    assert reloaded.get("h1") == committed
    assert reloaded.available == D("1000")

    # A follow-up compact() finishes the interrupted move: no duplicate
    # archive line, just the working-set removal.
    assert reloaded.compact() == 1
    assert all(item.reservation_id != "h1" for item in store.load())
    assert len(archive.load_index()) == 1


# ===========================================================================
# I/J/K - conflicting vs. identical duplicates, malformed/live-status lines
# ===========================================================================


def test_i_conflicting_duplicate_across_stores_fails_closed(tmp_path):
    ledger, store, archive = _ledger(tmp_path, total="1000")
    ledger.reserve("i1", "req-i1", D("100"))
    ledger.commit("i1", D("90"))

    # A DIFFERENT payload archived for the same id than what the working
    # set still holds (independent corruption/tamper simulation).
    conflicting = CapitalReservation("i1", "req-i1", D("90"), ReservationStatus.RELEASED)
    archive.append(conflicting)

    reloaded = CapitalReservationLedger(store, D("1000"), archive=archive)
    assert reloaded.ready is False


def test_j_identical_duplicate_archive_line_is_idempotent(tmp_path):
    archive = ReservationArchiveStore(tmp_path / "archive.jsonl")
    record = CapitalReservation("j1", "req-j1", D("42"), ReservationStatus.COMMITTED)
    archive.append(record)
    archive.append(record)  # duplicate retry, e.g. a retried compaction append

    assert archive.load_index() == {"j1": record}


def test_k1_malformed_torn_archive_line_fails_closed(tmp_path):
    path = tmp_path / "archive.jsonl"
    archive = ReservationArchiveStore(path)
    archive.append(CapitalReservation("k1", "req-k1", D("10"), ReservationStatus.COMMITTED))
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"reservation_id": "k2", "request_id": "req-k2", "amo\n')

    with pytest.raises(ReservationArchiveCorruptError):
        archive.load_index()


def test_k2_archive_containing_live_status_fails_closed(tmp_path):
    path = tmp_path / "archive.jsonl"
    live = CapitalReservation("k3", "req-k3", D("10"), ReservationStatus.RESERVED)
    path.write_text(json.dumps(live.to_dict()) + "\n", encoding="utf-8")

    with pytest.raises(ReservationArchiveCorruptError):
        ReservationArchiveStore(path).load_index()


def test_k3_conflicting_lines_within_the_archive_itself_fail_closed(tmp_path):
    archive = ReservationArchiveStore(tmp_path / "archive.jsonl")
    archive.append(CapitalReservation("k4", "req-a", D("10"), ReservationStatus.COMMITTED))
    archive.append(CapitalReservation("k4", "req-b", D("20"), ReservationStatus.COMMITTED))

    with pytest.raises(ReservationArchiveConflictError):
        archive.load_index()


def test_k4_torn_archive_makes_ledger_not_ready_never_treated_as_empty(tmp_path):
    store = JsonReservationStore(tmp_path / "reservations.json")
    store.initialize_empty()
    path = tmp_path / "archive.jsonl"
    path.write_text('{"reservation_id": "torn", "sta\n', encoding="utf-8")

    ledger = CapitalReservationLedger(store, D("1000"), archive=ReservationArchiveStore(path))
    assert ledger.ready is False


# ===========================================================================
# L - working-file size tracks live records, not lifetime terminal count
# ===========================================================================


def test_l_working_file_size_depends_on_live_records_not_lifetime_count(tmp_path):
    ledger, store, archive = _ledger(tmp_path, total="100000")
    path = tmp_path / "reservations.json"
    cycles = 40

    sizes_after_compact = []
    for i in range(cycles):
        reservation_id = f"cycle-{i}"
        ledger.reserve(reservation_id, reservation_id, D("10"))
        ledger.commit(reservation_id, D("10"))
        ledger.compact()
        assert len(store.load()) == 0
        sizes_after_compact.append(path.stat().st_size)

    # Every post-compaction working file holds zero live records, so its
    # size never grows with N regardless of lifetime terminal count.
    assert len(set(sizes_after_compact)) == 1

    assert len(archive.load_index()) == cycles
    for i in range(cycles):
        assert ledger.get(f"cycle-{i}").status is ReservationStatus.COMMITTED

    # A live (uncompacted) record does grow the working file - isolating
    # that growth tracks live record count, not lifetime terminal count.
    ledger.reserve("still-live", "still-live", D("5"))
    assert path.stat().st_size > sizes_after_compact[-1]


# ===========================================================================
# M - compaction failure never frees RESERVED/INDETERMINATE capital
# ===========================================================================


def test_m_compaction_failure_never_frees_reserved_or_indeterminate_capital(tmp_path):
    ledger, store, archive = _ledger(tmp_path, total="1000")
    ledger.reserve("m-reserved", "m-reserved", D("100"))
    ledger.reserve("m-indeterminate", "m-indeterminate", D("200"))
    ledger.mark_indeterminate("m-indeterminate")
    ledger.reserve("m-committed", "m-committed", D("50"))
    ledger.commit("m-committed", D("50"))

    available_before = ledger.available
    active_before = ledger.active_reserved_capital()
    assert active_before == D("300")

    original_append = archive.append

    def failing_append(reservation):
        raise OSError("simulated archive write failure")

    archive.append = failing_append
    try:
        with pytest.raises(OSError):
            ledger.compact()
    finally:
        archive.append = original_append

    assert ledger.ready is True
    assert ledger.available == available_before
    assert ledger.active_reserved_capital() == active_before == D("300")
    assert ledger.get("m-reserved").status is ReservationStatus.RESERVED
    assert ledger.get("m-indeterminate").status is ReservationStatus.INDETERMINATE
    # The committed record is untouched too - compaction never reached the
    # working-set removal for it.
    assert ledger.get("m-committed").status is ReservationStatus.COMMITTED
    assert any(item.reservation_id == "m-committed" for item in store.load())


# ===========================================================================
# Crash atomicity (section 5, injection points A-F)
# ===========================================================================


def test_crash_a_failure_before_archive_append_leaves_both_stores_untouched(tmp_path):
    ledger, store, archive = _ledger(tmp_path, total="1000")
    ledger.reserve("crash-a", "crash-a", D("10"))
    ledger.commit("crash-a", D("10"))

    working_path = tmp_path / "reservations.json"
    archive_path = tmp_path / "archive.jsonl"
    before_working = working_path.read_bytes()
    archive_existed_before = archive_path.exists()

    def failing_append(reservation):
        raise OSError("simulated failure before any archive write")

    archive.append = failing_append
    with pytest.raises(OSError):
        ledger.compact()

    assert working_path.read_bytes() == before_working
    assert archive_path.exists() == archive_existed_before
    assert ledger.ready is True
    assert ledger.get("crash-a").status is ReservationStatus.COMMITTED


def test_crash_b_d_working_file_save_failure_after_archive_append_then_restart_heals(tmp_path):
    ledger, store, archive = _ledger(tmp_path, total="1000")
    ledger.reserve("crash-bd", "crash-bd", D("25"))
    committed = ledger.commit("crash-bd", D("25"))

    original_save = store.save

    def failing_save(reservations):
        raise OSError("simulated working-file save failure")

    store.save = failing_save
    with pytest.raises(RuntimeError, match="recovery required"):
        ledger.compact()

    # D: the in-process ledger fails closed exactly as any other
    # _persist-backed mutation already does on save failure.
    assert ledger.ready is False

    store.save = original_save

    # The archive append durably succeeded before the working-file save
    # failed, so the record now lives in both places.
    archive_index = archive.load_index()
    assert archive_index["crash-bd"] == committed
    assert any(item.reservation_id == "crash-bd" for item in store.load())

    # B/E: restart (fresh ledger construction) tolerates the interrupted
    # compaction because the two copies agree field-for-field.
    restarted = CapitalReservationLedger(store, D("1000"), archive=archive)
    assert restarted.ready is True
    assert restarted.get("crash-bd") == committed
    assert restarted.available == D("1000")

    # A follow-up compact() finishes the interrupted move cleanly.
    assert restarted.compact() == 1
    assert all(item.reservation_id != "crash-bd" for item in store.load())


def test_crash_c_archive_fsync_failure_then_retry_produces_no_duplicate_confusion(tmp_path):
    import os

    ledger, store, archive = _ledger(tmp_path, total="1000")
    ledger.reserve("crash-c", "crash-c", D("30"))
    ledger.commit("crash-c", D("30"))

    original_fsync = os.fsync

    def failing_fsync(fd):
        raise OSError("simulated fsync failure")

    os.fsync = failing_fsync
    try:
        with pytest.raises(OSError):
            ledger.compact()
    finally:
        os.fsync = original_fsync

    # The failure is inside the archive append; the working-set file is
    # never touched until archival durably succeeds.
    assert any(item.reservation_id == "crash-c" for item in store.load())
    assert ledger.ready is True

    # Retrying with fsync healthy completes cleanly. Even if the failed
    # attempt's write()+flush() already landed bytes on disk before fsync
    # raised, load_index()'s duplicate-line tolerance (test_j) means a
    # possible leftover partial line never causes corruption or a second
    # archived copy.
    assert ledger.compact() == 1
    assert len(archive.load_index()) == 1
    assert all(item.reservation_id != "crash-c" for item in store.load())


# ===========================================================================
# N - v1 runtime load fails closed with migration-required
# ===========================================================================


def test_n1_v1_runtime_load_fails_closed_with_migration_required(tmp_path):
    path = tmp_path / "reservations.json"
    _write_v1_file(path, [
        CapitalReservation("n1", "req-n1", D("10"), ReservationStatus.RESERVED),
    ])

    with pytest.raises(ReservationSchemaMigrationRequiredError):
        JsonReservationStore(path).load()

    ledger = CapitalReservationLedger(JsonReservationStore(path), D("1000"))
    assert ledger.ready is False


def test_n2_bootstrap_reports_migration_required_for_v1_file(tmp_path):
    path = tmp_path / "capital_reservations.json"
    _write_v1_file(path, [
        CapitalReservation("n2", "req-n2", D("10"), ReservationStatus.COMMITTED),
    ])
    before = path.read_bytes()

    result = bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=D("10000"),
        allocatable_capital=D("8000"), policy_version="v1",
        today_utc=date(2026, 1, 1), verify_only=True,
    )
    reservation = result.result_for("capital_reservations")
    assert reservation.outcome is BootstrapOutcome.INVALID_EXISTING
    assert reservation.reason_code == "RESERVATION_MIGRATION_REQUIRED"
    assert path.read_bytes() == before


# ===========================================================================
# O/P - migration tool
# ===========================================================================


def test_o_migration_splits_mixed_statuses_exactly(tmp_path):
    records = [
        CapitalReservation("o-reserved", "req-1", D("111.11"), ReservationStatus.RESERVED),
        CapitalReservation("o-indeterminate", "req-2", D("222.22"), ReservationStatus.INDETERMINATE),
        CapitalReservation("o-committed", "req-3", D("333.33"), ReservationStatus.COMMITTED, version=2),
        CapitalReservation("o-released", "req-4", D("444.44"), ReservationStatus.RELEASED, version=3),
    ]
    _write_v1_file(tmp_path / "capital_reservations.json", records)

    result = migration_module.migrate(tmp_path)

    assert result.outcome is migration_module.MigrationOutcome.MIGRATED
    assert result.working_count == 2
    assert result.archive_count == 2
    assert result.archive_appended == 2

    working = JsonReservationStore(tmp_path / "capital_reservations.json").load()
    assert {item.reservation_id for item in working} == {"o-reserved", "o-indeterminate"}
    working_by_id = {item.reservation_id: item for item in working}
    assert working_by_id["o-reserved"] == records[0]
    assert working_by_id["o-indeterminate"] == records[1]

    archive_index = ReservationArchiveStore(
        tmp_path / "capital_reservations_archive.jsonl"
    ).load_index()
    assert set(archive_index) == {"o-committed", "o-released"}
    assert archive_index["o-committed"] == records[2]
    assert archive_index["o-released"] == records[3]


def test_p1_migration_refuses_when_archive_target_conflicts(tmp_path):
    _write_v1_file(tmp_path / "capital_reservations.json", [
        CapitalReservation("p1", "req-1", D("50"), ReservationStatus.COMMITTED),
    ])
    archive_path = tmp_path / "capital_reservations_archive.jsonl"
    ReservationArchiveStore(archive_path).append(
        CapitalReservation("p1", "req-1", D("999"), ReservationStatus.COMMITTED)
    )
    working_path = tmp_path / "capital_reservations.json"
    before_source = working_path.read_bytes()
    before_archive = archive_path.read_bytes()

    result = migration_module.migrate(tmp_path)

    assert result.outcome is migration_module.MigrationOutcome.REFUSED_ARCHIVE_CONFLICT
    assert working_path.read_bytes() == before_source
    assert archive_path.read_bytes() == before_archive


def test_p2_rerunning_the_exact_same_migration_is_idempotent(tmp_path):
    _write_v1_file(tmp_path / "capital_reservations.json", [
        CapitalReservation("p2", "req-2", D("77"), ReservationStatus.RELEASED),
        CapitalReservation("p2-live", "req-3", D("5"), ReservationStatus.RESERVED),
    ])

    first = migration_module.migrate(tmp_path)
    assert first.outcome is migration_module.MigrationOutcome.MIGRATED

    second = migration_module.migrate(tmp_path)
    assert second.outcome is migration_module.MigrationOutcome.ALREADY_MIGRATED

    archive_index = ReservationArchiveStore(
        tmp_path / "capital_reservations_archive.jsonl"
    ).load_index()
    assert set(archive_index) == {"p2"}


def test_p3_migration_refuses_a_corrupt_source(tmp_path):
    path = tmp_path / "capital_reservations.json"
    path.write_text("not valid json", encoding="utf-8")
    before = path.read_bytes()

    result = migration_module.migrate(tmp_path)

    assert result.outcome is migration_module.MigrationOutcome.SOURCE_INVALID
    assert path.read_bytes() == before
    assert not (tmp_path / "capital_reservations_archive.jsonl").exists()


def test_p4_migration_dry_run_touches_nothing(tmp_path):
    path = tmp_path / "capital_reservations.json"
    _write_v1_file(path, [
        CapitalReservation("p4", "req-4", D("15"), ReservationStatus.COMMITTED),
    ])
    before = path.read_bytes()

    result = migration_module.migrate(tmp_path, dry_run=True)

    assert result.outcome is migration_module.MigrationOutcome.WOULD_MIGRATE
    assert result.working_count == 0
    assert result.archive_count == 1
    assert path.read_bytes() == before
    assert not (tmp_path / "capital_reservations_archive.jsonl").exists()


def test_p5_migration_resumes_a_partially_completed_archive_append(tmp_path):
    """A prior run crashed after durably appending one of two archive
    records but before the working-file rewrite (source is still v1)."""
    records = [
        CapitalReservation("p5-a", "req-a", D("10"), ReservationStatus.COMMITTED),
        CapitalReservation("p5-b", "req-b", D("20"), ReservationStatus.RELEASED),
        CapitalReservation("p5-live", "req-c", D("5"), ReservationStatus.RESERVED),
    ]
    _write_v1_file(tmp_path / "capital_reservations.json", records)
    archive_path = tmp_path / "capital_reservations_archive.jsonl"
    ReservationArchiveStore(archive_path).append(records[0])

    result = migration_module.migrate(tmp_path)

    assert result.outcome is migration_module.MigrationOutcome.MIGRATED
    assert result.archive_appended == 1  # only the missing one
    archive_index = ReservationArchiveStore(archive_path).load_index()
    assert set(archive_index) == {"p5-a", "p5-b"}
    working = JsonReservationStore(tmp_path / "capital_reservations.json").load()
    assert {item.reservation_id for item in working} == {"p5-live"}


def test_p6_cli_exit_codes_for_absent_migrated_and_already_migrated(tmp_path):
    completed = run_migrate_cli("--state-directory", str(tmp_path))
    assert completed.returncode == 2
    assert "SOURCE_ABSENT" in completed.stdout

    _write_v1_file(tmp_path / "capital_reservations.json", [
        CapitalReservation("cli1", "req-cli1", D("1"), ReservationStatus.RESERVED),
    ])
    completed = run_migrate_cli("--state-directory", str(tmp_path))
    assert completed.returncode == 0
    assert "MIGRATED" in completed.stdout

    completed = run_migrate_cli("--state-directory", str(tmp_path), "--json")
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["outcome"] == "ALREADY_MIGRATED"


# ===========================================================================
# Q - post-migration restart/bootstrap validates successfully
# ===========================================================================


def test_q_post_migration_restart_and_bootstrap_both_validate(tmp_path):
    records = [
        CapitalReservation("q-reserved", "req-1", D("100"), ReservationStatus.RESERVED),
        CapitalReservation("q-committed", "req-2", D("50"), ReservationStatus.COMMITTED),
    ]
    _write_v1_file(tmp_path / "capital_reservations.json", records)

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.MIGRATED

    ledger = CapitalReservationLedger(
        JsonReservationStore(tmp_path / "capital_reservations.json"), D("1000"),
        archive=ReservationArchiveStore(tmp_path / "capital_reservations_archive.jsonl"),
    )
    assert ledger.ready is True
    assert ledger.get("q-reserved").status is ReservationStatus.RESERVED
    assert ledger.get("q-committed").status is ReservationStatus.COMMITTED
    assert ledger.active_reserved_capital() == D("100")

    bootstrap_result = bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=D("10000"),
        allocatable_capital=D("1000"), policy_version="v1",
        today_utc=date(2026, 1, 1), verify_only=True,
    )
    reservation = bootstrap_result.result_for("capital_reservations")
    assert reservation.outcome is BootstrapOutcome.VALID_EXISTING
