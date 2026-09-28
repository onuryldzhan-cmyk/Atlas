"""Read-only pre-flight: will Atlas's startup agreement check pass on this state?

Registry v5.13 made FinancialRuntimeSafetyService require agreement in
both directions between the idempotency log and the transaction journal.
Run this before starting a new build on an existing state root. It loads
both stores exactly as Atlas does, runs the same assessment, and lists
every request that would disagree. It writes nothing and takes no lock.

Usage:
  python -m tools.check_execution_authority_agreement [--state-dir PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.application import (
    EXECUTION_IDEMPOTENCY_STATE_FILE,
    EXECUTION_TRANSACTION_JOURNAL_FILE,
    resolve_state_directory,
)
from core.execution_idempotency_store import ExecutionIdempotencyStore
from core.execution_transaction_journal import ExecutionTransactionJournal
from data_layer.runtime_safety import FinancialRuntimeSafetyService


def _norm(value) -> str:
    return str(value or "").strip().upper()


def disagreements(journal, idempotency) -> dict[str, list[str]]:
    entries = getattr(journal, "entries", {}) or {}
    completed = getattr(idempotency, "completed_requests", {}) or {}
    journal_only = [
        rid for rid, entry in entries.items()
        if isinstance(entry, dict) and _norm(entry.get("state")) == "COMMITTED" and rid not in completed
    ]
    idempotency_only = [
        rid for rid, result in completed.items()
        if isinstance(result, dict) and _norm(result.get("commit_outcome")) == "COMMITTED"
        and not (isinstance(entries.get(rid), dict) and _norm(entries[rid].get("state")) == "COMMITTED")
    ]
    return {"journal_committed_without_idempotency": journal_only,
            "idempotency_committed_without_journal": idempotency_only}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    root = args.state_dir or resolve_state_directory()
    journal = ExecutionTransactionJournal(root / EXECUTION_TRANSACTION_JOURNAL_FILE)
    idempotency = ExecutionIdempotencyStore(root / EXECUTION_IDEMPOTENCY_STATE_FILE)
    readiness = FinancialRuntimeSafetyService(
        transaction_journal=journal, idempotency_store=idempotency,
    ).assess()

    found = disagreements(journal, idempotency)
    print(f"state root: {root}")
    print(f"journal entries: {len(journal.entries)}  idempotency results: {len(idempotency.completed_requests)}")
    for name, ids in found.items():
        print(f"{name}: {len(ids)}")
        for rid in ids[:20]:
            print(f"  {rid}")
        if len(ids) > 20:
            print(f"  ... {len(ids) - 20} more")
    print(f"startup readiness: ready={readiness.ready} reason={readiness.decision.reason}")
    if readiness.ready:
        print("OK - Atlas will pass the agreement check on this state.")
        return 0
    print("NOT READY - Atlas would halt execution. Do not start it; paste this output.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
