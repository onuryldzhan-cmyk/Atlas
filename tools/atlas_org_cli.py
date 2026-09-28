"""Write proposals and Atlas Memory records (append-only, hash-chained JSONL).

Usage (examples):
  python -m tools.atlas_org_cli proposal-create --id P-0001 --actor code_agent --json fields.json
  python -m tools.atlas_org_cli proposal-event --id P-0001 --event SUBMIT --actor code_agent
  python -m tools.atlas_org_cli proposal-event --id P-0001 --event REVIEW --actor code_review \
      --payload '{"kind":"CODE","verdict":"PASS","summary":"..."}'
  python -m tools.atlas_org_cli proposal-event --id P-0001 --event OWNER_APPROVE --actor owner --owner-confirm P-0001
  python -m tools.atlas_org_cli memory-add --json record.json
  python -m tools.atlas_org_cli verify

Every write re-reads and replays the whole log first; a corrupted log is
refused (nothing is appended). An owner decision needs ``--owner-confirm``
repeating the proposal id. That is a deliberate-intent check, NOT
authentication: Atlas has no authentication yet (documented limitation).
This tool never touches trading, risk, capital or execution state.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from atlas_org import memory_records, proposals

ROOT = Path(__file__).resolve().parents[1]
RECORDS_DIR = ROOT / "governance" / "records"
PROPOSALS_LOG = "proposals.jsonl"
MEMORY_LOG = "memory.jsonl"


def read_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise proposals.ProposalLogError(f"{path.name}: last record is truncated")
    events = []
    for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            raise proposals.ProposalLogError(f"{path.name}: line {number} is not JSON")
    return events


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    lock = path.with_suffix(path.suffix + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"{lock.name} exists: another writer is active (or crashed; remove it after checking)")
    try:
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def _append(path: Path, record: dict[str, Any]) -> None:
    line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_proposal_event(directory: Path, *, proposal_id: str, event: str, actor: str,
                       payload: dict[str, Any] | None = None, at: str | None = None) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / PROPOSALS_LOG
    with _lock(path):
        events = read_log(path)
        record = proposals.next_event(events, proposal_id=proposal_id, event=event, actor=actor,
                                      at=at or now(), payload=payload)
        _append(path, record)
    return record


def add_memory_record(directory: Path, fields: dict[str, Any]) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / MEMORY_LOG
    fields = {"at": now(), **fields}
    with _lock(path):
        record = memory_records.next_record(read_log(path), **fields)
        _append(path, record)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default=str(RECORDS_DIR))
    sub = parser.add_subparsers(dest="cmd", required=True)
    create = sub.add_parser("proposal-create")
    create.add_argument("--id", required=True)
    create.add_argument("--actor", required=True)
    create.add_argument("--json", required=True, help="file with the proposal fields")
    ev = sub.add_parser("proposal-event")
    ev.add_argument("--id", required=True)
    ev.add_argument("--event", required=True, choices=[e.value for e in proposals.EventType if e.value != "CREATE"])
    ev.add_argument("--actor", required=True)
    ev.add_argument("--payload", default="{}")
    ev.add_argument("--owner-confirm", default=None)
    mem = sub.add_parser("memory-add")
    mem.add_argument("--json", required=True)
    sub.add_parser("verify")
    args = parser.parse_args(argv)
    directory = Path(args.dir)

    try:
        if args.cmd == "proposal-create":
            fields = json.loads(Path(args.json).read_text(encoding="utf-8"))
            rec = add_proposal_event(directory, proposal_id=args.id, event="CREATE",
                                     actor=args.actor, payload=fields)
        elif args.cmd == "proposal-event":
            if args.event in ("OWNER_APPROVE", "OWNER_REJECT") and args.owner_confirm != args.id:
                print("refused: an owner decision needs --owner-confirm <proposal id>", file=sys.stderr)
                return 2
            rec = add_proposal_event(directory, proposal_id=args.id, event=args.event,
                                     actor=args.actor, payload=json.loads(args.payload))
        elif args.cmd == "memory-add":
            rec = add_memory_record(directory, json.loads(Path(args.json).read_text(encoding="utf-8")))
        else:
            p = proposals.replay(read_log(directory / PROPOSALS_LOG))
            m = memory_records.replay(read_log(directory / MEMORY_LOG))
            print(f"OK: {len(p)} proposals, {len(m)} memory records, chains intact")
            return 0
    except proposals.ProposalLogError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(f"appended seq {rec['seq']} {rec['hash'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
