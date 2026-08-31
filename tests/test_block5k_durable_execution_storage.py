"""
Block 5 / Package 5K - Durable Execution Storage.

Closes the two carried write-amplification findings and one output-safety
finding:

B5H-0-7
    ``ExecutionIdempotencyStore.save()`` rewrote its entire durable state on
    every terminal write, so completing request N cost O(N).

transaction journal write growth
    Every lifecycle transition rewrote the whole journal file, with the same
    O(history) cost.

B5J-1
    ``tools/migrate_execution_financial_state.py`` embedded truncated raw
    exception text in an operator-visible ``MIGRATION_WRITE_FAILED:`` reason
    code, deviating from ADR-0005's fixed-token rule.

Both authorities are now versioned append-only JSON-Lines logs. The tests
here prove the chosen architecture structurally - prior durable bytes are
never rewritten - and prove that nothing the earlier packages established
was weakened to get there: replay authority, COMMITTED permanence,
fail-closed corruption handling, Block 5J reconciliation, and the financial
arithmetic all still hold.

Every test uses an isolated temporary state directory; none of them
constructs a runtime that could reach the repository's real state files.
"""

from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from core.durable_append_log import DurableAppendLog
from core.execution_idempotency_store import ExecutionIdempotencyStore
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionResult
from core.execution_portfolio_foundation import (
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
    mint_long_position_id,
)
from core.execution_transaction_journal import (
    CommitOutcome,
    ExecutionTransactionJournal,
)
from data_layer.runtime_safety import FinancialRuntimeSafetyService

import tools.migrate_execution_authority_logs as authority_migration
import tools.migrate_execution_financial_state as financial_migration
from tools.migrate_execution_authority_logs import (
    AuthorityOutcome,
    migrate_authority,
)
from tools.reconcile_execution_authorities import (
    DEFAULT_APPLIED_FILE,
    DEFAULT_CLOSED_FILE,
    DEFAULT_FINANCIAL_STATE_FILE,
    DEFAULT_IDEMPOTENCY_FILE,
    DEFAULT_JOURNAL_FILE,
    ReconciliationOutcome,
    reconcile,
)

_SYMBOL = "BTCUSDT"

_SECRET_TOKENS = (
    "SECRET-EXEC-ID",
    "SECRET-REQUEST-ID",
    "SECRET-POSITION-ID",
    "SECRET-ORDER-ID",
)


# ===========================================================================
# Helpers
# ===========================================================================


def _confirmed_result(
    request_id: str,
    *,
    execution_id: str | None = None,
    position_id: str | None = None,
    symbol: str = _SYMBOL,
) -> dict[str, Any]:
    return {
        "success": True,
        "status": "PAPER_EXECUTED",
        "commit_outcome": CommitOutcome.COMMITTED.value,
        "request_id": request_id,
        "order_id": f"order-{request_id}",
        "execution_id": execution_id or f"exec-{request_id}",
        "position_id": position_id or f"position-{request_id}",
        "symbol": symbol,
        "action": "BUY",
        "filled_base_quantity": "1",
        "filled_quote_notional": "10",
        "filled_price": "10",
        "fee_amount": "0",
        "timestamp": "2026-08-25T00:00:00+00:00",
    }


def _fill(
    *, execution_id: str, position_id: str, request_id: str, symbol: str = _SYMBOL,
) -> ExecutionResult:
    return ExecutionResult(
        success=True, status="PAPER_EXECUTED", execution_id=execution_id,
        position_id=position_id, symbol=symbol, action="BUY",
        filled_price=D("10"), filled_base_quantity=D("1"),
        filled_quote_notional=D("10"), fee_amount=D("0"), fee_currency="USDT",
        idempotency_key=request_id, provenance_ref=f"transaction-journal:{request_id}",
    )


def _build_book(
    directory: Path, request_ids: list[str], *, cash: str = "1000",
) -> dict[str, dict[str, Any]]:
    """A healthy state directory holding one COMMITTED execution per id.

    Written in the runtime's own order - financial application, then the
    idempotency terminal result, then the journal COMMITTED entry - through
    the runtime's own stores, never by hand-written state JSON.
    """
    directory.mkdir(parents=True, exist_ok=True)
    store = FinancialStateStore(directory / DEFAULT_FINANCIAL_STATE_FILE)
    store.initialize(D(cash))
    foundation = ExecutionPortfolioFoundation(
        store,
        applied_archive=AppliedExecutionArchiveStore(directory / DEFAULT_APPLIED_FILE),
        closed_archive=ClosedPositionArchiveStore(directory / DEFAULT_CLOSED_FILE),
    )
    journal = ExecutionTransactionJournal(directory / DEFAULT_JOURNAL_FILE)
    idempotency = ExecutionIdempotencyStore(directory / DEFAULT_IDEMPOTENCY_FILE)

    results: dict[str, dict[str, Any]] = {}
    for index, request_id in enumerate(request_ids):
        symbol = _SYMBOL if index == 0 else f"SYM{index}USDT"
        execution_id = f"exec-{request_id}"
        position_id = mint_long_position_id(symbol, request_id)

        foundation.apply_confirmed(
            _fill(execution_id=execution_id, position_id=position_id,
                  request_id=request_id, symbol=symbol),
            risk_authorized=True, reservation_confirmed=True,
            expected_position_version=None,
        )
        result = _confirmed_result(
            request_id, execution_id=execution_id, position_id=position_id, symbol=symbol,
        )
        assert journal.prepare(request_id, {"request_id": request_id, "symbol": symbol})
        assert idempotency.record(request_id, result, save=True)
        assert journal.mark_committed(request_id, result)
        results[request_id] = result

    return results


def _log_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


# ===========================================================================
# A / N - the append-only architecture, proven structurally
# ===========================================================================


def test_a_recording_a_terminal_result_never_rewrites_prior_history(tmp_path: Path) -> None:
    """The discriminating property of the chosen architecture: the bytes an
    earlier terminal record occupies are identical before and after a later
    request completes. A whole-file rewrite could not satisfy this - it
    reserializes every record and restamps ``updated_at`` on each save."""

    path = tmp_path / "execution_idempotency.jsonl"
    store = ExecutionIdempotencyStore(path)

    for index in range(300):
        request_id = f"req-{index:05d}"
        assert store.record(request_id, _confirmed_result(request_id), save=True)

    before = path.read_bytes()

    assert store.record("req-99999", _confirmed_result("req-99999"), save=True)

    after = path.read_bytes()

    # Every byte written before this record is still exactly where it was.
    assert after.startswith(before)

    delta = after[len(before):]
    assert delta.count(b"\n") == 1

    # And the cost of that write is a single record, not the whole history.
    assert len(delta) < len(before) // 10

    # 301 records, one header, no line ever rewritten.
    assert len(_log_lines(path)) == 302


def test_n_journal_transition_never_rewrites_prior_events(tmp_path: Path) -> None:
    path = tmp_path / "execution_transaction_journal.jsonl"
    journal = ExecutionTransactionJournal(path)

    for index in range(200):
        request_id = f"req-{index:05d}"
        assert journal.prepare(request_id, {"request_id": request_id, "symbol": _SYMBOL})
        assert journal.mark_committed(request_id, _confirmed_result(request_id))

    before = path.read_bytes()

    assert journal.prepare("req-latest", {"request_id": "req-latest", "symbol": _SYMBOL})

    after = path.read_bytes()

    assert after.startswith(before)
    assert after[len(before):].count(b"\n") == 1
    assert len(after) - len(before) < len(before) // 10


def test_a_hot_path_write_cost_does_not_grow_with_history(tmp_path: Path) -> None:
    """The same logical record costs the same number of durable bytes at
    record 5 and at record 500. Structural, not timed."""

    path = tmp_path / "execution_idempotency.jsonl"
    store = ExecutionIdempotencyStore(path)

    def _append_cost(index: int) -> int:
        request_id = f"req-{index:05d}"
        result = _confirmed_result(request_id)
        # The recorded-at stamp is fixed so the two records differ only in
        # their request_id, which is fixed width, and their sequence.
        result["idempotency_recorded_at"] = "2026-08-25T00:00:00+00:00"
        before = path.stat().st_size if path.exists() else 0
        assert store.record(request_id, result, save=True)
        return path.stat().st_size - before

    for index in range(5):
        _append_cost(index)

    early = _append_cost(5)

    for index in range(6, 500):
        _append_cost(index)

    late = _append_cost(500)

    # Only the sequence field's digit count differs (1 vs 3).
    assert abs(late - early) <= 4


# ===========================================================================
# B - replay across a restart
# ===========================================================================


def test_b_old_request_replay_after_restart_returns_the_completed_result(
    tmp_path: Path,
) -> None:
    path = tmp_path / "execution_idempotency.jsonl"
    store = ExecutionIdempotencyStore(path)

    first = _confirmed_result("req-first")
    assert store.record("req-first", first, save=True)
    for index in range(200):
        request_id = f"req-{index:05d}"
        assert store.record(request_id, _confirmed_result(request_id), save=True)

    restarted = ExecutionIdempotencyStore(path)

    assert restarted.loaded is True
    assert restarted.contains("req-first") is True
    assert restarted.get("req-first") == store.get("req-first")
    assert len(restarted.completed_requests) == 201

    # And the runtime that reads it answers the replay from that record.
    manager = ExecutionManager(
        idempotency_store=restarted,
        transaction_journal=ExecutionTransactionJournal(
            tmp_path / "execution_transaction_journal.jsonl"
        ),
        audit_enabled=False,
    )

    assert manager.completed_request_results["req-first"]["execution_id"] == (
        first["execution_id"]
    )


# ===========================================================================
# C - conflicting terminal authority fails closed
# ===========================================================================


def test_c_conflicting_durable_terminal_result_is_refused_at_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "execution_idempotency.jsonl"
    store = ExecutionIdempotencyStore(path)

    assert store.record("req-c", _confirmed_result("req-c"), save=True)
    before = path.read_bytes()

    conflicting = _confirmed_result("req-c", execution_id="exec-different")

    assert store.record("req-c", conflicting, save=True) is False
    # Nothing was written, and the in-memory registry rolled back to the
    # record that is actually durable.
    assert path.read_bytes() == before
    assert store.completed_requests["req-c"]["execution_id"] == "exec-req-c"
    assert ExecutionIdempotencyStore(path).get("req-c")["execution_id"] == "exec-req-c"


def test_c_conflicting_duplicate_records_in_the_log_fail_closed(tmp_path: Path) -> None:
    """Two durable answers for one request_id leave the replay with no
    canonical result. The authority refuses to load rather than choosing."""

    path = tmp_path / "execution_idempotency.jsonl"
    store = ExecutionIdempotencyStore(path)
    assert store.record("req-c2", _confirmed_result("req-c2"), save=True)

    log = DurableAppendLog(
        path,
        log_name=ExecutionIdempotencyStore.LOG_NAME,
        version=ExecutionIdempotencyStore.LOG_VERSION,
    )
    log.append([
        {
            "request_id": "req-c2",
            "result": _confirmed_result("req-c2", execution_id="exec-tampered"),
        }
    ])

    reloaded = ExecutionIdempotencyStore(path)

    assert reloaded.loaded is False
    assert reloaded.completed_requests == {}

    readiness = FinancialRuntimeSafetyService(
        transaction_journal=ExecutionTransactionJournal(
            tmp_path / "execution_transaction_journal.jsonl"
        ),
        idempotency_store=reloaded,
    ).assess()

    assert readiness.ready is False
    assert readiness.decision.reason == "PERSISTED_STATE_CORRUPT"


def test_c_identical_duplicate_record_is_tolerated(tmp_path: Path) -> None:
    """A byte-identical repeat cannot change the reconstructed answer, so it
    is the one repetition the log tolerates - the same defensive allowance
    the Block 5I applied-execution archive already makes."""

    path = tmp_path / "execution_idempotency.jsonl"
    store = ExecutionIdempotencyStore(path)
    result = _confirmed_result("req-c3")
    result["idempotency_recorded_at"] = "2026-08-25T00:00:00+00:00"
    assert store.record("req-c3", result, save=True)

    lines = _log_lines(path)
    path.write_text("\n".join(lines + [lines[-1]]) + "\n", encoding="utf-8")

    reloaded = ExecutionIdempotencyStore(path)

    assert reloaded.loaded is True
    assert reloaded.get("req-c3")["execution_id"] == "exec-req-c3"


# ===========================================================================
# D - torn and malformed history fails closed
# ===========================================================================


@pytest.mark.parametrize("damage", ["torn_tail", "garbage_line", "no_header", "bad_version"])
def test_d_damaged_terminal_history_fails_closed(tmp_path: Path, damage: str) -> None:
    path = tmp_path / "execution_idempotency.jsonl"
    store = ExecutionIdempotencyStore(path)
    for index in range(3):
        request_id = f"req-d{index}"
        assert store.record(request_id, _confirmed_result(request_id), save=True)

    lines = _log_lines(path)

    if damage == "torn_tail":
        # A crash part-way through the final append.
        text = path.read_text(encoding="utf-8")
        path.write_text(text[: -len(lines[-1]) // 2], encoding="utf-8")
    elif damage == "garbage_line":
        path.write_text("\n".join(lines + ["{ not json"]) + "\n", encoding="utf-8")
    elif damage == "no_header":
        path.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    else:
        header = json.loads(lines[0])
        header["version"] = 99
        path.write_text(
            "\n".join([json.dumps(header, sort_keys=True, separators=(",", ":"))] + lines[1:])
            + "\n",
            encoding="utf-8",
        )

    reloaded = ExecutionIdempotencyStore(path)

    assert reloaded.loaded is False
    assert reloaded.completed_requests == {}


def test_d_non_deterministic_sequence_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "execution_idempotency.jsonl"
    store = ExecutionIdempotencyStore(path)
    for index in range(3):
        request_id = f"req-d{index}"
        assert store.record(request_id, _confirmed_result(request_id), save=True)

    lines = _log_lines(path)
    record = json.loads(lines[-1])
    record["sequence"] = 42
    lines[-1] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert ExecutionIdempotencyStore(path).loaded is False


def test_d_damaged_journal_history_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "execution_transaction_journal.jsonl"
    journal = ExecutionTransactionJournal(path)
    assert journal.prepare("req-d", {"request_id": "req-d", "symbol": _SYMBOL})
    assert journal.mark_committed("req-d", _confirmed_result("req-d"))

    text = path.read_text(encoding="utf-8")
    path.write_text(text[: len(text) - 20], encoding="utf-8")

    reloaded = ExecutionTransactionJournal(path)

    assert reloaded.loaded is False
    assert reloaded.load_failed is True
    # A journal that could not be read is treated as unresolved, so the
    # runtime halts instead of running on an unknown commit outcome.
    assert reloaded.has_unresolved() is True


# ===========================================================================
# E / F / G - journal state machine
# ===========================================================================


def test_e_journal_logical_state_reconstructs_identically_after_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "execution_transaction_journal.jsonl"
    journal = ExecutionTransactionJournal(path)

    assert journal.prepare("req-committed", {"request_id": "req-committed"})
    assert journal.mark_committed("req-committed", _confirmed_result("req-committed"))

    assert journal.prepare("req-not-committed", {"request_id": "req-not-committed"})
    assert journal.mark_not_committed("req-not-committed", reason="LIVE_DISABLED")

    assert journal.prepare("req-unknown", {"request_id": "req-unknown"})
    assert journal.mark_unknown("req-unknown", reason="INTERRUPTED")

    assert journal.prepare("req-prepared", {"request_id": "req-prepared"})

    # A NOT_COMMITTED request stays retryable: its second prepare is a legal
    # transition and the replay must land on the later state.
    assert journal.prepare("req-not-committed", {"request_id": "req-not-committed", "retry": True})

    restarted = ExecutionTransactionJournal(path)

    assert restarted.loaded is True
    assert restarted.load_failed is False
    assert restarted.entries == journal.entries
    assert restarted.entries["req-committed"]["state"] == CommitOutcome.COMMITTED.value
    assert restarted.entries["req-not-committed"]["state"] == "PREPARED"
    assert restarted.entries["req-not-committed"]["request"]["retry"] is True
    assert restarted.has_unresolved() is True


def test_f_committed_state_cannot_be_downgraded_by_a_write(tmp_path: Path) -> None:
    path = tmp_path / "execution_transaction_journal.jsonl"
    journal = ExecutionTransactionJournal(path)
    result = _confirmed_result("req-f")

    assert journal.prepare("req-f", {"request_id": "req-f"})
    assert journal.mark_committed("req-f", result)

    committed_entry = dict(journal.entries["req-f"])
    before = path.read_bytes()

    assert journal.prepare("req-f", {"request_id": "req-f", "attempt": 2}) is False
    assert journal.mark_not_committed("req-f", reason="LATE_FAILURE") is False
    assert journal.mark_unknown("req-f", reason="LATE_INTERRUPTION") is False

    assert journal.entries["req-f"] == committed_entry
    assert path.read_bytes() == before

    # A repeat of the same committed fact is the no-op success it is, and
    # still writes nothing.
    assert journal.mark_committed("req-f", result) is True
    assert path.read_bytes() == before

    # A different result for the same committed request is refused outright.
    assert journal.mark_committed(
        "req-f", _confirmed_result("req-f", execution_id="exec-other")
    ) is False
    assert journal.entries["req-f"] == committed_entry
    assert path.read_bytes() == before


def test_f_committed_state_cannot_be_downgraded_by_a_log_event(tmp_path: Path) -> None:
    """Even a hand-written downgrade event is refused: the replay fails
    closed rather than reconstructing a journal in which money that moved
    looks like money that did not."""

    path = tmp_path / "execution_transaction_journal.jsonl"
    journal = ExecutionTransactionJournal(path)
    assert journal.prepare("req-f2", {"request_id": "req-f2"})
    assert journal.mark_committed("req-f2", _confirmed_result("req-f2"))

    log = DurableAppendLog(
        path,
        log_name=ExecutionTransactionJournal.LOG_NAME,
        version=ExecutionTransactionJournal.LOG_VERSION,
        json_default_str=True,
    )
    log.append([
        {
            "request_id": "req-f2",
            "state": CommitOutcome.NOT_COMMITTED.value,
            "entry": {"state": CommitOutcome.NOT_COMMITTED.value, "reason": "TAMPERED"},
        }
    ])

    reloaded = ExecutionTransactionJournal(path)

    assert reloaded.loaded is False
    assert reloaded.load_failed is True
    assert reloaded.entries == {}


def test_g_illegal_journal_transition_refuses(tmp_path: Path) -> None:
    path = tmp_path / "execution_transaction_journal.jsonl"
    journal = ExecutionTransactionJournal(path)
    assert journal.prepare("req-g", {"request_id": "req-g"})
    assert journal.mark_committed("req-g", _confirmed_result("req-g"))

    log = DurableAppendLog(
        path,
        log_name=ExecutionTransactionJournal.LOG_NAME,
        version=ExecutionTransactionJournal.LOG_VERSION,
        json_default_str=True,
    )
    log.append([
        {
            "request_id": "req-g",
            "state": "PREPARED",
            "entry": {"state": "PREPARED", "prepared_at": "2026-08-25T00:00:00+00:00"},
        }
    ])

    assert ExecutionTransactionJournal(path).load_failed is True


def test_g_event_whose_state_disagrees_with_its_entry_refuses(tmp_path: Path) -> None:
    path = tmp_path / "execution_transaction_journal.jsonl"
    log = DurableAppendLog(
        path,
        log_name=ExecutionTransactionJournal.LOG_NAME,
        version=ExecutionTransactionJournal.LOG_VERSION,
        json_default_str=True,
    )
    log.append([
        {
            "request_id": "req-g2",
            "state": CommitOutcome.COMMITTED.value,
            "entry": {"state": "PREPARED"},
        }
    ])

    assert ExecutionTransactionJournal(path).load_failed is True


def test_g_state_outside_the_lifecycle_refuses(tmp_path: Path) -> None:
    path = tmp_path / "execution_transaction_journal.jsonl"
    log = DurableAppendLog(
        path,
        log_name=ExecutionTransactionJournal.LOG_NAME,
        version=ExecutionTransactionJournal.LOG_VERSION,
        json_default_str=True,
    )
    log.append([
        {"request_id": "req-g3", "state": "SOMETHING_ELSE", "entry": {"state": "SOMETHING_ELSE"}}
    ])

    assert ExecutionTransactionJournal(path).load_failed is True


# ===========================================================================
# H - crash between the two authorities
# ===========================================================================


def test_h_crash_between_journal_and_idempotency_still_fails_closed(
    tmp_path: Path,
) -> None:
    """A crash after the journal's COMMITTED event but before the terminal
    result's append leaves a COMMITTED entry with no replay answer. That must
    stay a fail-closed disagreement - it is exactly the state in which a
    silently "clean" start would execute an already-executed request again."""

    journal_path = tmp_path / "execution_transaction_journal.jsonl"
    idempotency_path = tmp_path / "execution_idempotency.jsonl"

    journal = ExecutionTransactionJournal(journal_path)
    assert journal.prepare("req-h", {"request_id": "req-h"})
    assert journal.mark_committed("req-h", _confirmed_result("req-h"))

    # The idempotency append never happened.
    assert not idempotency_path.exists()

    restarted_journal = ExecutionTransactionJournal(journal_path)
    restarted_store = ExecutionIdempotencyStore(idempotency_path)

    readiness = FinancialRuntimeSafetyService(
        transaction_journal=restarted_journal,
        idempotency_store=restarted_store,
    ).assess()

    assert readiness.ready is False
    assert readiness.decision.reason == "SOURCE_DISAGREEMENT"

    manager = ExecutionManager(
        idempotency_store=restarted_store,
        transaction_journal=restarted_journal,
        audit_enabled=False,
    )

    assert manager.start()
    assert manager.execution_halted is True
    assert manager.recovery_required is True
    assert manager.halt_reason == "SOURCE_DISAGREEMENT"


def test_h_crash_before_the_journal_prepare_leaves_no_entry(tmp_path: Path) -> None:
    """A crash before the prepare barrier leaves no durable trace at all, so
    a restart neither halts nor believes anything happened."""

    journal_path = tmp_path / "execution_transaction_journal.jsonl"
    idempotency_path = tmp_path / "execution_idempotency.jsonl"

    journal = ExecutionTransactionJournal(journal_path)
    store = ExecutionIdempotencyStore(idempotency_path)

    readiness = FinancialRuntimeSafetyService(
        transaction_journal=journal, idempotency_store=store,
    ).assess()

    assert readiness.ready is True
    assert journal.entries == {}
    assert store.completed_requests == {}


def test_h_crash_after_the_journal_prepare_halts_for_recovery(tmp_path: Path) -> None:
    journal_path = tmp_path / "execution_transaction_journal.jsonl"
    journal = ExecutionTransactionJournal(journal_path)
    assert journal.prepare("req-h3", {"request_id": "req-h3"})

    restarted = ExecutionTransactionJournal(journal_path)

    assert restarted.entries["req-h3"]["state"] == "PREPARED"
    assert restarted.has_unresolved() is True

    readiness = FinancialRuntimeSafetyService(
        transaction_journal=restarted,
        idempotency_store=ExecutionIdempotencyStore(
            tmp_path / "execution_idempotency.jsonl"
        ),
    ).assess()

    assert readiness.ready is False
    assert readiness.decision.reason == "UNRESOLVED_JOURNAL"


# ===========================================================================
# I / J - Block 5J reconciliation still works against the new storage
# ===========================================================================


def test_i_safe_reconciliation_still_repairs_its_one_permitted_case(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "state"
    results = _build_book(directory, ["req-i"])

    store = ExecutionIdempotencyStore(directory / DEFAULT_IDEMPOTENCY_FILE)
    assert store.remove("req-i", save=True)

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.RECONCILED
    assert outcome.reason_code == "RECONCILIATION_COMPLETE"
    assert outcome.repaired == 1

    repaired = ExecutionIdempotencyStore(directory / DEFAULT_IDEMPOTENCY_FILE)
    assert repaired.loaded is True
    assert repaired.get("req-i")["execution_id"] == results["req-i"]["execution_id"]

    readiness = FinancialRuntimeSafetyService(
        transaction_journal=ExecutionTransactionJournal(directory / DEFAULT_JOURNAL_FILE),
        idempotency_store=repaired,
    ).assess()

    assert readiness.ready is True


def test_j_reconciliation_against_conflicting_authority_still_refuses(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "state"
    _build_book(directory, ["req-j"])

    store = ExecutionIdempotencyStore(directory / DEFAULT_IDEMPOTENCY_FILE)
    diverged = dict(store.completed_requests["req-j"])
    diverged["filled_quote_notional"] = "999999"
    assert store.remove("req-j", save=True)
    assert store.record("req-j", diverged, save=True)

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.RECONCILIATION_REQUIRED
    assert outcome.reason_code == "AUTHORITY_RESULT_CONFLICT"
    assert outcome.repaired == 0


def test_j_legacy_state_sends_the_operator_to_the_migration_tool(tmp_path: Path) -> None:
    directory = tmp_path / "state"
    directory.mkdir()
    (directory / "execution_transaction_journal.json").write_text(
        json.dumps({"version": "1.0", "entries": {}}), encoding="utf-8",
    )

    outcome = reconcile(directory, apply=True)

    assert outcome.outcome is ReconciliationOutcome.STATE_INVALID
    assert outcome.reason_code == "JOURNAL_MIGRATION_REQUIRED"


# ===========================================================================
# K / L / M - operator migration from the v1 whole-file format
# ===========================================================================


def _write_legacy_idempotency(directory: Path, request_ids: list[str]) -> Path:
    path = directory / "execution_idempotency.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "completed_requests": {
                    request_id: _confirmed_result(request_id) for request_id in request_ids
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_k_migration_converts_verifies_and_retires_the_legacy_source(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "state"
    directory.mkdir()
    legacy = _write_legacy_idempotency(directory, ["req-k1", "req-k2"])

    dry = migrate_authority(directory, authority_migration.IDEMPOTENCY_AUTHORITY)

    assert dry.outcome is AuthorityOutcome.WOULD_MIGRATE
    assert dry.reason_code == "DRY_RUN"
    assert dry.records == 2
    assert legacy.exists()
    assert not (directory / "execution_idempotency.jsonl").exists()

    applied = migrate_authority(
        directory, authority_migration.IDEMPOTENCY_AUTHORITY, apply=True,
    )

    assert applied.outcome is AuthorityOutcome.MIGRATED
    assert applied.reason_code == "MIGRATION_COMPLETE"

    # The legacy file is retired by rename, never deleted or truncated.
    assert not legacy.exists()
    assert (directory / "execution_idempotency.json.migrated").exists()

    store = ExecutionIdempotencyStore(directory / "execution_idempotency.jsonl")
    assert store.loaded is True
    assert store.migration_required is False
    assert sorted(store.completed_requests) == ["req-k1", "req-k2"]
    assert store.get("req-k1")["execution_id"] == "exec-req-k1"


def test_k_migration_is_idempotent_and_resumable(tmp_path: Path) -> None:
    directory = tmp_path / "state"
    directory.mkdir()
    _write_legacy_idempotency(directory, ["req-k3"])

    assert migrate_authority(
        directory, authority_migration.IDEMPOTENCY_AUTHORITY, apply=True,
    ).outcome is AuthorityOutcome.MIGRATED

    # Re-running a completed migration writes nothing and reports it.
    log_bytes = (directory / "execution_idempotency.jsonl").read_bytes()
    again = migrate_authority(
        directory, authority_migration.IDEMPOTENCY_AUTHORITY, apply=True,
    )

    assert again.outcome is AuthorityOutcome.ALREADY_MIGRATED
    assert again.reason_code == "ALREADY_ON_V2"
    assert (directory / "execution_idempotency.jsonl").read_bytes() == log_bytes

    # A run interrupted after the destination was written but before the
    # legacy source was retired resumes rather than refusing.
    (directory / "execution_idempotency.json.migrated").rename(
        directory / "execution_idempotency.json"
    )
    resumed = migrate_authority(
        directory, authority_migration.IDEMPOTENCY_AUTHORITY, apply=True,
    )

    assert resumed.outcome is AuthorityOutcome.MIGRATED
    assert (directory / "execution_idempotency.jsonl").read_bytes() == log_bytes
    assert (directory / "execution_idempotency.json.migrated").exists()


def test_l_migration_conflict_leaves_the_legacy_source_intact(tmp_path: Path) -> None:
    directory = tmp_path / "state"
    directory.mkdir()
    legacy = _write_legacy_idempotency(directory, ["req-l"])
    legacy_bytes = legacy.read_bytes()

    # A destination that is not this source's deterministic output.
    store = ExecutionIdempotencyStore(directory / "execution_idempotency.jsonl")
    assert store.record("req-unrelated", _confirmed_result("req-unrelated"), save=True)
    destination_bytes = (directory / "execution_idempotency.jsonl").read_bytes()

    result = migrate_authority(
        directory, authority_migration.IDEMPOTENCY_AUTHORITY, apply=True,
    )

    assert result.outcome is AuthorityOutcome.REFUSED
    assert result.reason_code == "DESTINATION_CONFLICT"
    assert legacy.read_bytes() == legacy_bytes
    assert (directory / "execution_idempotency.jsonl").read_bytes() == destination_bytes


def test_l_malformed_legacy_source_is_refused_untouched(tmp_path: Path) -> None:
    directory = tmp_path / "state"
    directory.mkdir()
    legacy = directory / "execution_idempotency.json"
    legacy.write_text("{ not json", encoding="utf-8")

    result = migrate_authority(
        directory, authority_migration.IDEMPOTENCY_AUTHORITY, apply=True,
    )

    assert result.outcome is AuthorityOutcome.REFUSED
    assert result.reason_code == "LEGACY_SOURCE_UNREADABLE"
    assert legacy.read_text(encoding="utf-8") == "{ not json"
    assert not (directory / "execution_idempotency.jsonl").exists()


def test_l_legacy_journal_state_outside_the_lifecycle_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "state"
    directory.mkdir()
    legacy = directory / "execution_transaction_journal.json"
    legacy.write_text(
        json.dumps({"version": "1.0", "entries": {"req-l2": {"state": "WHO_KNOWS"}}}),
        encoding="utf-8",
    )

    result = migrate_authority(
        directory, authority_migration.JOURNAL_AUTHORITY, apply=True,
    )

    assert result.outcome is AuthorityOutcome.REFUSED
    assert result.reason_code == "LEGACY_SOURCE_INVALID"
    assert legacy.exists()
    assert not (directory / "execution_transaction_journal.jsonl").exists()


def test_m_destination_is_validated_before_the_legacy_source_is_retired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Damage landing on the destination after its write but before the
    mandatory reload must be caught by that reload, and must never let the
    legacy source - still the only complete authority - be retired."""

    directory = tmp_path / "state"
    directory.mkdir()
    legacy = _write_legacy_idempotency(directory, ["req-m"])
    legacy_bytes = legacy.read_bytes()

    real_rewrite = DurableAppendLog.rewrite

    def _rewrite_then_corrupt(self, payloads):
        real_rewrite(self, payloads)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write("{ not json\n")

    monkeypatch.setattr(
        authority_migration.DurableAppendLog, "rewrite", _rewrite_then_corrupt,
    )

    result = migrate_authority(
        directory, authority_migration.IDEMPOTENCY_AUTHORITY, apply=True,
    )

    assert result.outcome is AuthorityOutcome.FAILED
    assert result.reason_code == "POST_WRITE_VERIFICATION_FAILED"
    assert legacy.read_bytes() == legacy_bytes
    assert not (directory / "execution_idempotency.json.migrated").exists()


def test_m_journal_migration_reconstructs_the_same_authority(tmp_path: Path) -> None:
    directory = tmp_path / "state"
    directory.mkdir()
    committed_result = _confirmed_result("req-m2")
    (directory / "execution_transaction_journal.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "entries": {
                    "req-m2": {
                        "state": CommitOutcome.COMMITTED.value,
                        "prepared_at": "2026-01-01T00:00:00+00:00",
                        "request": {"request_id": "req-m2"},
                        "result": committed_result,
                    },
                    "req-m3": {
                        "state": "PREPARED",
                        "prepared_at": "2026-01-01T00:00:00+00:00",
                        "request": {"request_id": "req-m3"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    result = migrate_authority(
        directory, authority_migration.JOURNAL_AUTHORITY, apply=True,
    )

    assert result.outcome is AuthorityOutcome.MIGRATED

    journal = ExecutionTransactionJournal(directory / "execution_transaction_journal.jsonl")

    assert journal.loaded is True
    assert journal.entries["req-m2"]["state"] == CommitOutcome.COMMITTED.value
    assert journal.entries["req-m2"]["result"] == committed_result
    assert journal.has_unresolved() is True

    # And the migrated COMMITTED entry is as permanent as a natively written
    # one: it cannot be reopened.
    assert journal.prepare("req-m2", {"request_id": "req-m2"}) is False


def test_m_migration_never_runs_automatically(tmp_path: Path) -> None:
    """The runtime halts on legacy state; it never converts it itself."""

    directory = tmp_path / "state"
    directory.mkdir()
    legacy = _write_legacy_idempotency(directory, ["req-m4"])
    legacy_bytes = legacy.read_bytes()

    store = ExecutionIdempotencyStore(directory / "execution_idempotency.jsonl")
    journal = ExecutionTransactionJournal(directory / "execution_transaction_journal.jsonl")

    assert store.migration_required is True
    assert store.loaded is False
    assert legacy.read_bytes() == legacy_bytes
    assert not (directory / "execution_idempotency.jsonl").exists()

    readiness = FinancialRuntimeSafetyService(
        transaction_journal=journal, idempotency_store=store,
    ).assess()

    assert readiness.ready is False
    assert readiness.decision.reason == "SCHEMA_OR_MIGRATION_INVALID"


# ===========================================================================
# O - B5J-1 output safety
# ===========================================================================


def _assert_output_is_safe(text: str) -> None:
    for token in _SECRET_TOKENS:
        assert token not in text, token
    for fragment in ("Traceback", "Exception", "filled_quote_notional", "PAPER_EXECUTED"):
        assert fragment not in text, fragment


def _write_legacy_financial_state(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1, "transition": None,
                "cash": "1000", "reserved_capital": "0",
                "realized_gross_pnl": "0", "fees": "0",
                "positions": {}, "closed_positions": {},
                "applied_executions": {"SECRET-EXEC-ID": "SECRET-REQUEST-ID"},
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("target", "attribute", "expected_reason"),
    [
        ("AppliedExecutionArchiveStore", "append", "MIGRATION_WRITE_FAILED:SIDECAR_APPEND"),
        ("FinancialStateStore", "save", "MIGRATION_WRITE_FAILED:WORKING_STATE_REWRITE"),
    ],
)
def test_o_migration_write_failures_report_fixed_tokens_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    target: str, attribute: str, expected_reason: str,
) -> None:
    """B5J-1. A write failure's reason code is a fixed token. The exception
    behind it carries identifiers and raw prose, and none of it may reach the
    operator's output - truncating it would not have made it safe."""

    path = tmp_path / "execution_financial_state.json"
    _write_legacy_financial_state(path)

    def _raise(*arguments: Any, **keywords: Any) -> None:
        raise RuntimeError(
            "disk failure while writing SECRET-EXEC-ID / SECRET-REQUEST-ID "
            "for SECRET-POSITION-ID order SECRET-ORDER-ID"
        )

    monkeypatch.setattr(getattr(financial_migration, target), attribute, _raise)

    result = financial_migration.migrate(tmp_path)

    assert result.outcome is financial_migration.MigrationOutcome.FAILED
    assert result.reason_code == expected_reason
    _assert_output_is_safe(result.reason_code)
    _assert_output_is_safe(financial_migration._render_human(result, 3))
    _assert_output_is_safe(financial_migration._render_json(result, 3))


def test_o_authority_migration_output_exposes_no_identifiers(tmp_path: Path) -> None:
    directory = tmp_path / "state"
    directory.mkdir()
    _write_legacy_idempotency(directory, ["SECRET-REQUEST-ID"])

    for arguments in (
        ["--state-directory", str(directory)],
        ["--state-directory", str(directory), "--json"],
        ["--state-directory", str(directory), "--apply"],
        ["--state-directory", str(directory), "--apply", "--json"],
    ):
        results = authority_migration.migrate(
            directory, apply="--apply" in arguments,
        )
        rendered = (
            authority_migration._render_json(results, 0)
            if "--json" in arguments
            else authority_migration._render_human(results, 0)
        )
        _assert_output_is_safe(rendered)


# ===========================================================================
# P / Q - nothing else moved
# ===========================================================================


def test_p_financial_arithmetic_is_unchanged(tmp_path: Path) -> None:
    """5K touched storage framing only. The book's arithmetic - cash, fees,
    exposure, equity - is asserted here against exact Decimals so a storage
    change that quietly altered a financial value cannot pass."""

    directory = tmp_path / "state"
    _build_book(directory, ["req-p1", "req-p2"], cash="1000")

    foundation = ExecutionPortfolioFoundation(
        FinancialStateStore(directory / DEFAULT_FINANCIAL_STATE_FILE),
        applied_archive=AppliedExecutionArchiveStore(directory / DEFAULT_APPLIED_FILE),
        closed_archive=ClosedPositionArchiveStore(directory / DEFAULT_CLOSED_FILE),
    )

    assert foundation.ready is True

    snapshot = foundation.snapshot()

    assert snapshot["cash"] == D("980")
    assert snapshot["fees"] == D("0")
    assert snapshot["realized_gross_pnl"] == D("0")
    assert snapshot["committed_capital"] == D("20")
    assert snapshot["gross_exposure"] == D("20")
    assert snapshot["equity"] == D("1000")
    assert snapshot["available_capital"] == D("980")


def test_q_applied_and_closed_authorities_are_untouched_by_5k(tmp_path: Path) -> None:
    """The Block 5H/5I authorities keep their own format and semantics: 5K
    added a log beside them, it did not restructure them."""

    directory = tmp_path / "state"
    _build_book(directory, ["req-q1", "req-q2"])

    applied = AppliedExecutionArchiveStore(directory / DEFAULT_APPLIED_FILE).load_index()

    assert applied.count == 2
    assert sorted(applied.by_idempotency_key) == ["req-q1", "req-q2"]
    assert applied.tail is not None and applied.tail.sequence == 1

    # No header line and no version header: the 5I archives are unchanged
    # plain JSON-Lines, not DurableAppendLog files.
    first_line = json.loads(_log_lines(directory / DEFAULT_APPLIED_FILE)[0])
    assert set(first_line) == {"sequence", "execution_id", "idempotency_key", "applied_at"}

    assert ClosedPositionArchiveStore(directory / DEFAULT_CLOSED_FILE).load_index().count == 0


def test_q_no_retention_or_pruning_policy_was_introduced(tmp_path: Path) -> None:
    """Both 5K authorities are permanent. Nothing prunes, truncates, or ages
    a record out on any production path."""

    idempotency_path = tmp_path / "execution_idempotency.jsonl"
    store = ExecutionIdempotencyStore(idempotency_path)

    assert store.max_records is None

    for index in range(400):
        request_id = f"req-{index:05d}"
        assert store.record(request_id, _confirmed_result(request_id), save=True)

    assert store.stats["records_pruned"] == 0
    assert len(ExecutionIdempotencyStore(idempotency_path).completed_requests) == 400

    journal_path = tmp_path / "execution_transaction_journal.jsonl"
    journal = ExecutionTransactionJournal(journal_path)

    for index in range(200):
        request_id = f"req-{index:05d}"
        assert journal.prepare(request_id, {"request_id": request_id})
        assert journal.mark_committed(request_id, _confirmed_result(request_id))

    assert len(ExecutionTransactionJournal(journal_path).entries) == 200
    # Every event is still on disk: 200 prepares + 200 commits + one header.
    assert len(_log_lines(journal_path)) == 401
