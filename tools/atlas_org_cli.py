"""Write proposals and Atlas Memory records (append-only, hash-chained JSONL).

Usage (examples):
  python -m tools.atlas_org_cli proposal-create --id P-0001 --actor code_agent --json fields.json
  python -m tools.atlas_org_cli proposal-event --id P-0001 --event SUBMIT --actor code_agent
  python -m tools.atlas_org_cli proposal-event --id P-0001 --event REVIEW --actor code_review \
      --payload '{"kind":"CODE","verdict":"PASS","summary":"..."}'
  python -m tools.atlas_org_cli proposal-event --id P-0001 --event OWNER_APPROVE --actor owner --owner-confirm P-0001
  python -m tools.atlas_org_cli memory-add --json record.json
  python -m tools.atlas_org_cli task-request "Atlas, market data bağlantısını araştır"
  python -m tools.atlas_org_cli task-event --id T-0001 --event START --actor open_source_research --payload '{"step":0}'
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
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from atlas_org import manager, memory_records, proposals, tasks

ROOT = Path(__file__).resolve().parents[1]
RECORDS_DIR = ROOT / "governance" / "records"
PROPOSALS_LOG = "proposals.jsonl"
MEMORY_LOG = "memory.jsonl"
TASKS_LOG = "tasks.jsonl"


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


class RecordLockBusy(SystemExit):
    """The log's lock is held by another writer. Still a SystemExit for the CLI (same message and
    exit), but the agent cycle catches it so one busy log fails one agent, not the whole process."""


LOCK_WAIT_S = 2.0  # a concurrent writer (CLI, another agent) usually finishes within milliseconds


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    lock = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RecordLockBusy(f"{lock.name} exists: another writer is active (or crashed; remove it after checking)")
            time.sleep(0.05)
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


OWNER_KEY_ENV = "ATLAS_OWNER_KEY_FILE"


def owner_key_path() -> Path:
    """The owner's HMAC key: outside the repository, on the owner's machine only."""

    return Path(os.environ.get(OWNER_KEY_ENV) or Path.home() / ".atlas" / "owner.key")


def load_owner_key() -> bytes | None:
    path = owner_key_path()
    try:
        if path.resolve().is_relative_to(ROOT.resolve()):
            raise SystemExit(f"refused: the owner key must not live inside the repository ({path})")
        raw = path.read_bytes()[:256].strip()
    except FileNotFoundError:
        return None
    return raw if len(raw) >= 32 else None


def owner_init() -> Path:
    import secrets

    path = owner_key_path()
    if path.resolve().is_relative_to(ROOT.resolve()):
        raise SystemExit("refused: choose a key path outside the repository")
    if path.exists():
        raise SystemExit(f"refused: {path} already exists (never overwritten: past signatures depend on it)")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(secrets.token_hex(32) + "\n")
    return path


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_proposal_event(directory: Path, *, proposal_id: str, event: str, actor: str,
                       payload: dict[str, Any] | None = None, at: str | None = None,
                       owner_key: bytes | None = None) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / PROPOSALS_LOG
    with _lock(path):
        events = read_log(path)
        if event in ("MARK_READY", "OWNER_APPROVE"):
            # Audit v5.39 F4: the evidence is re-checked before it is relied on -
            # the reviewed files must be unchanged and the review must reproduce.
            state = proposals.replay(events, owner_key).get(proposal_id)
            security = [r for r in (state.current_reviews() if state else []) if r["kind"] == "SECURITY"]
            if security:
                from tools.security_guardian import reverify

                problem = reverify(security[-1])
                if problem:
                    raise proposals.ProposalLogError(f"{proposal_id}: {problem}")
        if event == "MARK_APPLIED":
            # Nothing is marked applied on an approval this machine cannot verify.
            state = proposals.replay(events, owner_key).get(proposal_id)
            decision = state.owner_decision if state else None
            if not decision or decision.get("verified") is not True:
                raise proposals.ProposalLogError(
                    f"{proposal_id}: MARK_APPLIED needs an owner approval verified with the owner key")
        record = proposals.next_event(events, proposal_id=proposal_id, event=event, actor=actor,
                                      at=at or now(), payload=payload, owner_key=owner_key)
        _append(path, record)
    return record


def add_memory_record(directory: Path, fields: dict[str, Any], owner_key: bytes | None = None) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / MEMORY_LOG
    fields = {"at": now(), **fields}
    with _lock(path):
        record = memory_records.next_record(read_log(path), owner_key=owner_key, **fields)
        _append(path, record)
    return record


def add_task_event(directory: Path, *, task_id: str, event: str, actor: str,
                   payload: dict[str, Any] | None = None, at: str | None = None,
                   owner_key: bytes | None = None) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / TASKS_LOG
    with _lock(path):
        record = tasks.next_event(read_log(path), task_id=task_id, event=event, actor=actor,
                                  at=at or now(), payload=payload, owner_key=owner_key)
        _append(path, record)
    return record


def request_task(directory: Path, request: str, at: str | None = None) -> dict[str, Any]:
    """Atlas Manager: classify, plan, create the task and route every step."""

    plan = manager.classify(request)
    if plan.refusal:
        return {"created": False, "category": plan.category, "reason": plan.refusal}
    existing = tasks.replay(read_log(directory / TASKS_LOG))
    task_id = f"T-{len(existing) + 1:04d}"
    add_task_event(directory, task_id=task_id, event="CREATE", actor=tasks.MANAGER,
                   payload=plan.to_payload(request), at=at)
    unrouted = []
    for index, step in enumerate(plan.steps):
        unit = manager.route(step.role, step.capability)
        if unit is None:
            unrouted.append(index)
            add_task_event(directory, task_id=task_id, event="BLOCK", actor=tasks.MANAGER,
                           payload={"step": index, "reason": f"no unit holds {step.capability} for {step.role}"}, at=at)
            continue
        add_task_event(directory, task_id=task_id, event="ASSIGN", actor=tasks.MANAGER,
                       payload={"step": index, "unit": unit}, at=at)
    return {"created": True, "task_id": task_id, "category": plan.category, "unrouted_steps": unrouted}


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
    treq = sub.add_parser("task-request")
    treq.add_argument("request")
    tev = sub.add_parser("task-event")
    tev.add_argument("--id", required=True)
    tev.add_argument("--event", required=True, choices=[e.value for e in tasks.TaskEvent if e.value != "CREATE"])
    tev.add_argument("--actor", required=True)
    tev.add_argument("--payload", default="{}")
    tev.add_argument("--owner-confirm", default=None)
    sub.add_parser("verify")
    sub.add_parser("owner-init", help="create the owner's signing key outside the repository (once)")
    args = parser.parse_args(argv)
    directory = Path(args.dir)
    if args.cmd == "owner-init":
        path = owner_init()
        print(f"owner key created: {path}\nKeep it private: never commit, paste or share it. "
              "Only this machine can sign owner decisions.")
        return 0
    key = load_owner_key()

    try:
        if args.cmd == "proposal-create":
            fields = json.loads(Path(args.json).read_text(encoding="utf-8"))
            rec = add_proposal_event(directory, proposal_id=args.id, event="CREATE",
                                     actor=args.actor, payload=fields, owner_key=key)
        elif args.cmd == "proposal-event":
            if args.event == "REVIEW" and json.loads(args.payload).get("kind") == "SECURITY":
                print("refused: security reviews are recorded only by python -m tools.security_guardian --record",
                      file=sys.stderr)
                return 2
            if args.event in ("OWNER_APPROVE", "OWNER_REJECT") and args.owner_confirm != args.id:
                print("refused: an owner decision needs --owner-confirm <proposal id>", file=sys.stderr)
                return 2
            rec = add_proposal_event(directory, proposal_id=args.id, event=args.event,
                                     actor=args.actor, payload=json.loads(args.payload), owner_key=key)
        elif args.cmd == "task-request":
            out = request_task(directory, args.request)
            print(json.dumps(out, ensure_ascii=False))
            return 0 if out["created"] else 3
        elif args.cmd == "task-event":
            if args.event == "CANCEL" and args.owner_confirm != args.id:
                print("refused: cancelling needs --owner-confirm <task id>", file=sys.stderr)
                return 2
            rec = add_task_event(directory, task_id=args.id, event=args.event, actor=args.actor,
                                 payload=json.loads(args.payload), owner_key=key)
        elif args.cmd == "memory-add":
            rec = add_memory_record(directory, json.loads(Path(args.json).read_text(encoding="utf-8")), owner_key=key)
        else:
            p = proposals.replay(read_log(directory / PROPOSALS_LOG), key)
            m = memory_records.replay(read_log(directory / MEMORY_LOG), key)
            t = tasks.replay(read_log(directory / TASKS_LOG), key)
            heads = {name: (log[-1]["seq"], log[-1]["hash"][:16]) if log else (0, "-")
                     for name in (PROPOSALS_LOG, MEMORY_LOG, TASKS_LOG) for log in [read_log(directory / name)]}
            sigs = "owner signatures VERIFIED" if key else "owner signatures NOT verified (no owner key on this machine)"
            print(f"OK: {len(p)} proposals, {len(m)} memory records, {len(t)} tasks, chains intact; {sigs}")
            print("log heads (seq, hash) - note them to detect later truncation: " + json.dumps(heads))
            return 0
    except proposals.ProposalLogError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(f"appended seq {rec['seq']} {rec['hash'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
