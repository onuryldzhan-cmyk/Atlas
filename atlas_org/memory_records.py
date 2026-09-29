"""Atlas Memory records with provenance, as an append-only hash-chained log.

Records are immutable. A change is a new record that ``supersedes`` an older
one; the old one stays readable as HISTORICAL. Same chain rules as
``atlas_org.proposals`` (contiguous ``seq``, ``prev_hash``, ``hash``), so an
edited or truncated log is refused as a whole.

Authority: only the owner may write an AUTHORITATIVE record, so temporary
agent output can never silently become project policy. A RESEARCH record
must carry the open-source evaluation (license, maintenance, dependencies,
security observations, recommendation) and can never be AUTHORITATIVE.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterable

from atlas_org.proposals import GENESIS_HASH, OWNER, ProposalLogError, event_hash, owner_check, sign_if_owner


class RecordType(str, Enum):
    ARCHITECTURE = "ARCHITECTURE"
    GOVERNANCE = "GOVERNANCE"
    DECISION = "DECISION"
    AGENTS = "AGENTS"
    RESEARCH = "RESEARCH"
    SECURITY = "SECURITY"
    DEVELOPMENT = "DEVELOPMENT"
    TRADING = "TRADING"
    EXPERIMENTS = "EXPERIMENTS"
    PROPOSALS = "PROPOSALS"
    REVIEWS = "REVIEWS"
    ROADMAP = "ROADMAP"
    OPERATIONS = "OPERATIONS"


class Authority(str, Enum):
    AUTHORITATIVE = "AUTHORITATIVE"
    PROPOSED = "PROPOSED"
    RESEARCH = "RESEARCH"
    EXPERIMENTAL = "EXPERIMENTAL"
    TEMPORARY = "TEMPORARY"
    REJECTED = "REJECTED"


RESEARCH_FIELDS = ("project", "license", "maintenance", "dependencies",
                   "security_observations", "recommendation")


class MemoryLogError(ProposalLogError):
    pass


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise MemoryLogError(message)


def replay(events: Iterable[dict[str, Any]], owner_key: bytes | None = None) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    expected, prev = 1, GENESIS_HASH
    for ev in events:
        _check(isinstance(ev, dict), "record is not an object")
        seq = ev.get("seq")
        _check(seq == expected, f"sequence break: expected {expected}, got {seq!r}")
        _check(ev.get("prev_hash") == prev, f"seq {seq}: hash chain broken")
        _check(ev.get("hash") == event_hash(ev), f"seq {seq}: record altered")
        verified = owner_check(ev, owner_key)
        rid, author = ev.get("record_id"), ev.get("author")
        _check(isinstance(rid, str) and rid, f"seq {seq}: missing record_id")
        _check(rid not in records, f"seq {seq}: duplicate record {rid}")
        _check(isinstance(author, str) and author, f"seq {seq}: missing author")
        _check(bool(ev.get("at")) and bool(ev.get("title")) and bool(ev.get("body")),
               f"seq {seq}: at/title/body required")
        try:
            rtype, auth = RecordType(ev.get("type")), Authority(ev.get("authority"))
        except ValueError:
            raise MemoryLogError(f"seq {seq}: bad type or authority")
        _check(bool(ev.get("source")), f"seq {seq}: provenance source required")
        if auth is Authority.AUTHORITATIVE:
            _check(author == OWNER, f"seq {seq}: only the owner writes AUTHORITATIVE records")
        if rtype is RecordType.RESEARCH:
            _check(auth is not Authority.AUTHORITATIVE, f"seq {seq}: research is never authoritative")
            evaluation = ev.get("evaluation") or {}
            missing = [f for f in RESEARCH_FIELDS if not evaluation.get(f)]
            _check(not missing, f"seq {seq}: research evaluation missing {missing}")
        old = ev.get("supersedes")
        if old is not None:
            _check(old in records, f"seq {seq}: supersedes unknown record {old}")
            _check(records[old]["superseded_by"] is None, f"seq {seq}: {old} already superseded")
            if records[old]["authority"] == Authority.AUTHORITATIVE.value:
                _check(author == OWNER, f"seq {seq}: only the owner supersedes an AUTHORITATIVE record")
            records[old]["superseded_by"] = rid
        records[rid] = {
            "id": rid, "seq": seq, "type": rtype.value, "authority": auth.value,
            "title": ev["title"], "body": ev["body"], "author": author, "created_at": ev["at"],
            "source": ev["source"], "related_task": ev.get("related_task"),
            "related_proposal": ev.get("related_proposal"),
            "related_decision": ev.get("related_decision"),
            "evaluation": ev.get("evaluation"), "supersedes": old, "superseded_by": None,
            "owner_verified": verified if author == OWNER else None,
        }
        prev, expected = ev["hash"], expected + 1
    return records


def next_record(events: list[dict[str, Any]], owner_key: bytes | None = None, **fields: Any) -> dict[str, Any]:
    record = {"seq": len(events) + 1,
              "prev_hash": events[-1]["hash"] if events else GENESIS_HASH, **fields}
    sign_if_owner(record, owner_key)
    record["hash"] = event_hash(record)
    replay([*events, record], owner_key)
    return record


def public_view(records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in records.values():
        out.append({**r, "status": "HISTORICAL" if r["superseded_by"] else "CURRENT"})
    return sorted(out, key=lambda r: r["seq"], reverse=True)
