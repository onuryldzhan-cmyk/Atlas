"""Read-only diagnosis of a forked audit event chain.

Walks the audit JSONL file with the same rules as
AuditEventStore.verify_chain(), but instead of stopping at the first
broken link it reports, for every line whose previous_hash does not match
the line before it, which earlier line it actually chains from. That is
what distinguishes "two writers interleaved" (a fork) from a tampered or
truncated file. It never writes anything.

Usage: python -m tools.diagnose_audit_chain_fork <path-to-jsonl>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from core.audit_event_store import GENESIS_HASH, AuditEvent


def main(path: Path) -> int:
    by_hash: dict[str, int] = {GENESIS_HASH: 0}
    previous = GENESIS_HASH
    breaks = 0

    with path.open("r", encoding="utf-8") as file:
        for number, raw in enumerate(file, start=1):
            line = raw.strip()
            if not line:
                continue

            event = AuditEvent.from_dict(json.loads(line))
            hash_ok = event.verify_hash()
            linked = event.previous_hash == previous

            if not linked or not hash_ok:
                breaks += 1
                parent = by_hash.get(event.previous_hash)
                print(
                    f"line {number}: link={'OK' if linked else 'BROKEN'} "
                    f"hash={'OK' if hash_ok else 'BAD'} "
                    f"chains_from_line={parent if parent is not None else 'UNKNOWN'} "
                    f"type={event.event_type} event_id={event.event_id} "
                    f"aggregate={event.aggregate_id} at={event.timestamp}"
                )

            by_hash[event.event_hash] = number
            previous = event.event_hash

    print(f"total_lines={number} breaks={breaks}")
    return 0 if breaks == 0 else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
