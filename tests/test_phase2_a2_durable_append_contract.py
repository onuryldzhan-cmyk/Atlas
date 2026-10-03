"""Phase-2 A2: durable append contract (I-A1..I-A7).

Real file I/O on pytest temp dirs. Fault injection only replaces ``os.fsync``
(or appends foreign bytes) to provoke the failure being tested.
"""

from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path

import pytest

from core import durable_append_contract as contract
from core.audit_event_store import (
    AUDIT_DEGRADED,
    AUDIT_HEALTHY,
    AUDIT_RECOVERY_REQUIRED,
    AuditChainIntegrityError,
    AuditEventStore,
    AuditRecoveryRequiredError,
)
from core.durable_append_contract import (
    DurableAppendIndeterminateError,
    DurableAppendNotWrittenError,
    DurableWriterPoisonedError,
)
from core.durable_append_log import (
    DurableAppendLog,
    DurableAppendLogCorruptError,
    DurableAppendLogRecoveryRequiredError,
)
from core.execution_idempotency_store import ExecutionIdempotencyStore
from core.execution_transaction_journal import ExecutionTransactionJournal

KW = dict(source="t", aggregate_type="x", payload={})


class FsyncFault:
    """Fail the first ``failures`` fsync calls, then pass through."""

    def __init__(self, failures: int) -> None:
        self.remaining = failures
        self.calls = 0
        self._real = os.fsync

    def __call__(self, fd: int) -> None:
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise OSError(5, "injected EIO")
        self._real(fd)


def _inject(monkeypatch: pytest.MonkeyPatch, failures: int) -> FsyncFault:
    fault = FsyncFault(failures)
    monkeypatch.setattr(contract.os, "fsync", fault)
    return fault


def _log(path: Path) -> DurableAppendLog:
    return DurableAppendLog(path, log_name="t", version=1)


def _sequences(path: Path) -> list[int]:
    lines = path.read_text("utf-8").splitlines()[1:]
    return [json.loads(line)["sequence"] for line in lines if line.strip()]


# ---------------------------------------------------------------- baseline


def test_clean_append_and_reload_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    log = _log(path)
    log.append([{"a": 1}])
    log.append([{"a": 2}, {"a": 3}])

    assert _log(path).read() == [{"a": 1}, {"a": 2}, {"a": 3}]
    assert _sequences(path) == [0, 1, 2]

    audit = AuditEventStore(tmp_path / "audit.jsonl")
    for i in range(3):
        audit.append(event_type="E", aggregate_id=str(i), **KW)
    reloaded = AuditEventStore(tmp_path / "audit.jsonl")
    assert reloaded.event_count == 3
    assert reloaded.persistence_state() == AUDIT_HEALTHY


# ---------------------------------------------------------------- I-A1 / I-A4


def test_single_fsync_fault_is_rolled_back_not_written(tmp_path, monkeypatch) -> None:
    path = tmp_path / "log.jsonl"
    log = _log(path)
    log.append([{"a": 0}])
    before = path.read_bytes()

    _inject(monkeypatch, 1)
    with pytest.raises(DurableAppendNotWrittenError):
        log.append([{"a": 1}])

    assert path.read_bytes() == before
    log.append([{"a": 2}])
    assert _sequences(path) == [0, 1]
    assert _log(path).read() == [{"a": 0}, {"a": 2}]


def test_unrecoverable_fault_is_indeterminate_and_poisons(tmp_path, monkeypatch) -> None:
    path = tmp_path / "log.jsonl"
    log = _log(path)
    log.append([{"a": 0}])

    _inject(monkeypatch, 2)  # the append and its rollback both fail
    with pytest.raises(DurableAppendIndeterminateError):
        log.append([{"a": 1}])

    with pytest.raises(DurableWriterPoisonedError):
        log.append([{"a": 2}])
    with pytest.raises(DurableWriterPoisonedError):
        log.rewrite([{"a": 9}])

    # Never two different records with one sequence.
    sequences = _sequences(path)
    assert len(sequences) == len(set(sequences))

    # I-A5: restart fails closed on the marker.
    with pytest.raises(DurableAppendLogRecoveryRequiredError):
        _log(path).read()


def test_operator_acknowledgement_revalidates_from_scratch(tmp_path, monkeypatch) -> None:
    path = tmp_path / "log.jsonl"
    log = _log(path)
    log.append([{"a": 0}])
    _inject(monkeypatch, 2)
    with pytest.raises(DurableAppendIndeterminateError):
        log.append([{"a": 1}])
    monkeypatch.undo()

    fresh = _log(path)
    fresh._writer.acknowledge_recovery()
    # The rollback truncate ran but its fsync failed, so the outcome stayed
    # INDETERMINATE. Acknowledging only re-enables a full validating read
    # of whatever is on disk - it never repairs or guesses.
    assert fresh.read() == [{"a": 0}]
    fresh.append([{"a": 2}])
    assert _sequences(path) == [0, 1]


# ---------------------------------------------------------------- I-A6


def test_torn_tail_is_never_glued_onto(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    log = _log(path)
    log.append([{"a": 0}])
    with path.open("ab") as stream:
        stream.write(b'{"a":1,"seq')  # torn record, no newline
    torn = path.read_bytes()

    with pytest.raises(DurableWriterPoisonedError):
        log.append([{"a": 2}])

    assert path.read_bytes() == torn
    with pytest.raises(DurableAppendLogCorruptError):
        _log(path).read()


def test_audit_torn_tail_fails_closed_on_restart(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    store = AuditEventStore(path)
    store.append(event_type="E", aggregate_id="0", **KW)
    with path.open("ab") as stream:
        stream.write(b'{"event_id":"half')

    with pytest.raises(DurableWriterPoisonedError):
        store.append(event_type="E", aggregate_id="1", **KW)
    assert store.persistence_state() == AUDIT_RECOVERY_REQUIRED
    with pytest.raises(AuditChainIntegrityError):
        AuditEventStore(path)


# ---------------------------------------------------------------- audit


def test_audit_fsync_fault_does_not_fork_the_chain(tmp_path, monkeypatch) -> None:
    path = tmp_path / "audit.jsonl"
    store = AuditEventStore(path)
    store.append(event_type="E", aggregate_id="0", **KW)
    head = store.last_event_hash

    _inject(monkeypatch, 1)
    with pytest.raises(DurableAppendNotWrittenError):
        store.append(event_type="E", aggregate_id="1", **KW)
    assert store.last_event_hash == head
    assert store.persistence_state() == AUDIT_DEGRADED

    store.append(event_type="E", aggregate_id="2", **KW)
    reloaded = AuditEventStore(path)
    assert reloaded.verify_chain()["valid"]
    assert reloaded.event_count == 2


def test_audit_indeterminate_fault_poisons_and_requires_recovery(tmp_path, monkeypatch) -> None:
    path = tmp_path / "audit.jsonl"
    store = AuditEventStore(path)
    store.append(event_type="E", aggregate_id="0", **KW)

    _inject(monkeypatch, 2)
    with pytest.raises(DurableAppendIndeterminateError):
        store.append(event_type="E", aggregate_id="1", **KW)
    with pytest.raises(DurableWriterPoisonedError):
        store.append(event_type="E", aggregate_id="2", **KW)

    assert store.persistence_state() == AUDIT_RECOVERY_REQUIRED
    monkeypatch.undo()
    with pytest.raises(AuditRecoveryRequiredError):
        AuditEventStore(path, verify_on_load=False)
    with pytest.raises(AuditRecoveryRequiredError):
        AuditEventStore(path)
    assert issubclass(AuditRecoveryRequiredError, AuditChainIntegrityError)


def test_second_in_process_writer_cannot_fork(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    first = AuditEventStore(path)
    first.append(event_type="E", aggregate_id="a0", **KW)
    second = AuditEventStore(path)
    first.append(event_type="E", aggregate_id="a1", **KW)

    with pytest.raises(DurableWriterPoisonedError):
        second.append(event_type="E", aggregate_id="b0", **KW)

    assert AuditEventStore(path).verify_chain()["valid"]


# ---------------------------------------------------------------- journal


def test_journal_fault_cannot_reuse_a_sequence(tmp_path, monkeypatch) -> None:
    path = tmp_path / "journal.jsonl"
    journal = ExecutionTransactionJournal(path)
    assert journal.prepare("r1", {"symbol": "BTCUSDT"})

    _inject(monkeypatch, 1)
    assert journal.mark_committed("r1", {"status": "FILLED"}) is False
    # Recovery append after a verified rollback lands on the next free
    # sequence exactly once.
    assert journal.mark_unknown("r1", reason="commit write failed") is True

    sequences = _sequences(path)
    assert sequences == sorted(set(sequences))
    reloaded = ExecutionTransactionJournal(path)
    assert reloaded.loaded
    assert reloaded.entries["r1"]["state"] == "COMMIT_STATUS_UNKNOWN"


def test_journal_indeterminate_fault_blocks_recovery_append_and_restart(tmp_path, monkeypatch) -> None:
    path = tmp_path / "journal.jsonl"
    journal = ExecutionTransactionJournal(path)
    assert journal.prepare("r1", {"symbol": "BTCUSDT"})

    _inject(monkeypatch, 2)
    assert journal.mark_committed("r1", {"status": "FILLED"}) is False
    # A1b reproduced "seq 3 COMMITTED / seq 3 COMMIT_STATUS_UNKNOWN" here.
    assert journal.mark_unknown("r1", reason="commit write failed") is False
    monkeypatch.undo()

    sequences = _sequences(path)
    assert len(sequences) == len(set(sequences))

    reloaded = ExecutionTransactionJournal(path)
    assert reloaded.load_failed
    assert reloaded.has_unresolved()


# ---------------------------------------------------------------- idempotency


def test_idempotency_rolled_back_record_is_not_resurrected(tmp_path, monkeypatch) -> None:
    path = tmp_path / "idem.jsonl"
    store = ExecutionIdempotencyStore(path)

    _inject(monkeypatch, 1)
    assert store.record("r1", {"status": "FILLED"}) is False
    monkeypatch.undo()

    reloaded = ExecutionIdempotencyStore(path)
    assert reloaded.loaded
    assert reloaded.get("r1") is None


def test_idempotency_indeterminate_record_fails_closed_on_restart(tmp_path, monkeypatch) -> None:
    path = tmp_path / "idem.jsonl"
    store = ExecutionIdempotencyStore(path)

    _inject(monkeypatch, 2)
    assert store.record("r1", {"status": "FILLED"}) is False
    assert store.record("r2", {"status": "FILLED"}) is False  # poisoned
    monkeypatch.undo()

    reloaded = ExecutionIdempotencyStore(path)
    # Not a silent contradictory reload: the store refuses to load at all.
    assert reloaded.loaded is False
    assert reloaded.get("r1") is None


def test_idempotency_duplicate_writer_cannot_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "idem.jsonl"
    a = ExecutionIdempotencyStore(path)
    b = ExecutionIdempotencyStore(path)
    assert a.record("r1", {"status": "FILLED"})
    # b never saw a's write: it must fail closed, not append blind.
    assert b.record("r2", {"status": "FILLED"}) is False

    reloaded = ExecutionIdempotencyStore(path)
    assert reloaded.loaded
    assert reloaded.get("r1") is not None
    assert reloaded.get("r2") is None


# ---------------------------------------------------------------- I-A7


def _process_writer(path: str, tag: str, count: int, barrier) -> None:
    log = DurableAppendLog(path, log_name="t", version=1)
    log.read()
    barrier.wait()
    for i in range(count):
        try:
            log.append([{"w": tag, "i": i}])
        except Exception:
            return


def test_concurrent_processes_cannot_corrupt_the_log(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    _log(path).append([{"w": "seed"}])

    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    workers = [
        ctx.Process(target=_process_writer, args=(str(path), tag, 50, barrier))
        for tag in ("A", "B")
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(60)
        assert worker.exitcode == 0

    records = _log(path).read()  # raises on any fork/duplicate/torn line
    assert records[0] == {"w": "seed"}
    sequences = _sequences(path)
    assert sequences == list(range(len(sequences)))
