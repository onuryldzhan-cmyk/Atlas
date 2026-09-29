"""Proposal lifecycle as an append-only, hash-chained event log.

A proposal's state is never stored directly: it is the replay of its events.
Each event carries ``seq`` (1..n, contiguous across the whole log),
``prev_hash`` and ``hash`` (SHA-256 of the canonical event body), so an
edited, reordered, duplicated, dropped or truncated record is detected on
replay and the log is refused as a whole (corrupted state is halted, never
silently continued through).

Authority rules enforced on every replay, not only when an event is written:

* only the actor ``owner`` can approve or reject;
* READY_FOR_OWNER needs recorded test results plus a PASS code review and a
  PASS security review of the current revision, each by a reviewer who is
  not the author;
* APPLIED only after APPROVED; ROLLED_BACK only after APPLIED;
* an agent's recommendation is a review verdict, never an approval.

Owner identity is asserted by the calling tool, not authenticated (there is
no authentication in Atlas yet); this is a documented limitation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

OWNER = "owner"
GENESIS_HASH = "0" * 64


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    READY_FOR_OWNER = "READY_FOR_OWNER"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    ROLLED_BACK = "ROLLED_BACK"
    SUPERSEDED = "SUPERSEDED"


class EventType(str, Enum):
    CREATE = "CREATE"
    SUBMIT = "SUBMIT"
    RECORD_TESTS = "RECORD_TESTS"
    REVIEW = "REVIEW"
    REQUEST_REVISION = "REQUEST_REVISION"
    REVISE = "REVISE"
    MARK_READY = "MARK_READY"
    OWNER_APPROVE = "OWNER_APPROVE"
    OWNER_REJECT = "OWNER_REJECT"
    MARK_APPLIED = "MARK_APPLIED"
    ROLL_BACK = "ROLL_BACK"
    SUPERSEDE = "SUPERSEDE"


class ReviewKind(str, Enum):
    CODE = "CODE"
    SECURITY = "SECURITY"
    PERFORMANCE = "PERFORMANCE"


class Verdict(str, Enum):
    PASS = "PASS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAIL = "FAIL"


S = ProposalStatus
E = EventType

# Which event may occur in which state, and the state it leads to (None: stay).
TRANSITIONS: dict[tuple[ProposalStatus, EventType], ProposalStatus | None] = {
    (S.DRAFT, E.SUBMIT): S.UNDER_REVIEW,
    (S.DRAFT, E.REVISE): None,
    (S.UNDER_REVIEW, E.RECORD_TESTS): None,
    (S.UNDER_REVIEW, E.REVIEW): None,
    (S.UNDER_REVIEW, E.REQUEST_REVISION): S.REVISION_REQUIRED,
    (S.UNDER_REVIEW, E.MARK_READY): S.READY_FOR_OWNER,
    (S.REVISION_REQUIRED, E.REVISE): S.UNDER_REVIEW,
    (S.READY_FOR_OWNER, E.OWNER_APPROVE): S.APPROVED,
    (S.READY_FOR_OWNER, E.OWNER_REJECT): S.REJECTED,
    (S.READY_FOR_OWNER, E.REQUEST_REVISION): S.REVISION_REQUIRED,
    (S.APPROVED, E.MARK_APPLIED): S.APPLIED,
    (S.APPLIED, E.ROLL_BACK): S.ROLLED_BACK,
}
# SUPERSEDE is allowed from any non-terminal state.
TERMINAL = frozenset({S.REJECTED, S.ROLLED_BACK, S.SUPERSEDED})
OWNER_ONLY = frozenset({E.OWNER_APPROVE, E.OWNER_REJECT})

REQUIRED_CREATE_FIELDS = (
    "title", "problem", "motivation", "proposed_changes", "affected_components",
    "risk_level", "rollback_plan",
)
RISK_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

# Protected governance surface: Atlas may not change its own rules quietly.
# A proposal touching any of these must be CRITICAL, and like every proposal
# it can only be approved by the owner.
PROTECTED_PREFIXES = ("CLAUDE.md", "AGENTS.md", "governance/", "atlas_org/",
                      "tests/architecture/", ".claude/", "packaging/atlas_architecture_map.json")


def touches_protected(paths: Iterable[str]) -> bool:
    return any(str(p).replace("\\", "/").removeprefix("./").startswith(PROTECTED_PREFIXES) for p in paths)


class ProposalLogError(ValueError):
    """The log is corrupted or an event breaks a governance rule."""


@dataclass
class Proposal:
    proposal_id: str
    author: str
    created_at: str
    fields: dict[str, Any]
    status: ProposalStatus = ProposalStatus.DRAFT
    revision: int = 1
    tests: dict[str, Any] | None = None
    reviews: list[dict[str, Any]] = field(default_factory=list)
    owner_decision: dict[str, Any] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def current_reviews(self) -> list[dict[str, Any]]:
        return [r for r in self.reviews if r["revision"] == self.revision]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.proposal_id,
            "status": self.status.value,
            "author": self.author,
            "created_at": self.created_at,
            "revision": self.revision,
            **self.fields,
            "tests": self.tests,
            "reviews": self.reviews,
            "owner_decision": self.owner_decision,
            "history": self.history,
        }


def canonical_body(event: dict[str, Any]) -> str:
    body = {k: v for k, v in event.items() if k != "hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_hash(event: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_body(event).encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProposalLogError(message)


def _apply(proposals: dict[str, Proposal], event: dict[str, Any]) -> None:
    try:
        kind = EventType(event["event"])
    except (KeyError, ValueError):
        raise ProposalLogError(f"seq {event.get('seq')}: unknown event {event.get('event')!r}")
    pid, actor, at = event.get("proposal_id"), event.get("actor"), event.get("at")
    payload = event.get("payload") or {}
    _require(isinstance(pid, str) and pid, f"seq {event['seq']}: missing proposal_id")
    _require(isinstance(actor, str) and actor, f"seq {event['seq']}: missing actor")
    _require(isinstance(at, str) and at, f"seq {event['seq']}: missing timestamp")
    _require(isinstance(payload, dict), f"seq {event['seq']}: payload must be an object")

    if kind is E.CREATE:
        _require(pid not in proposals, f"seq {event['seq']}: duplicate proposal {pid}")
        missing = [f for f in REQUIRED_CREATE_FIELDS if not payload.get(f)]
        _require(not missing, f"seq {event['seq']}: missing fields {missing}")
        _require(payload["risk_level"] in RISK_LEVELS, f"seq {event['seq']}: bad risk_level")
        _require(isinstance(payload.get("affected_files", []), list), f"seq {event['seq']}: affected_files must be a list")
        _require(not touches_protected(payload.get("affected_files", [])) or payload["risk_level"] == "CRITICAL",
                 f"seq {event['seq']}: a change to protected governance files must be CRITICAL")
        proposals[pid] = Proposal(pid, actor, at, dict(payload))
        proposals[pid].history.append({"seq": event["seq"], "event": kind.value, "actor": actor,
                                       "at": at, "status": S.DRAFT.value})
        return

    _require(pid in proposals, f"seq {event['seq']}: unknown proposal {pid}")
    p = proposals[pid]
    if kind in OWNER_ONLY:
        _require(actor == OWNER, f"seq {event['seq']}: {kind.value} by {actor!r}: only the owner decides")
    else:
        _require(actor != OWNER or kind in (E.SUPERSEDE, E.MARK_APPLIED, E.ROLL_BACK, E.REQUEST_REVISION),
                 f"seq {event['seq']}: owner cannot perform agent step {kind.value}")

    if kind is E.SUPERSEDE:
        _require(p.status not in TERMINAL, f"seq {event['seq']}: {pid} is already {p.status.value}")
        target = S.SUPERSEDED
    else:
        key = (p.status, kind)
        _require(key in TRANSITIONS, f"seq {event['seq']}: {kind.value} not allowed in {p.status.value}")
        target = TRANSITIONS[key]

    if kind is E.RECORD_TESTS:
        _require(isinstance(payload.get("passed"), int) and isinstance(payload.get("failed"), int)
                 and payload.get("command"), f"seq {event['seq']}: tests need command/passed/failed")
        p.tests = {**payload, "revision": p.revision, "recorded_by": actor}
    elif kind is E.REVIEW:
        try:
            rk, verdict = ReviewKind(payload.get("kind")), Verdict(payload.get("verdict"))
        except ValueError:
            raise ProposalLogError(f"seq {event['seq']}: bad review kind/verdict")
        _require(actor != p.author, f"seq {event['seq']}: author {actor!r} cannot review own proposal")
        _require(bool(payload.get("summary")), f"seq {event['seq']}: review needs a summary")
        if rk is ReviewKind.SECURITY:
            # "Security PASS" must be backed by an evaluation of every category
            # (atlas_org.security_review), and the verdict must be its worst.
            from atlas_org.security_review import CATEGORIES, OVERALL, _RANK

            checks = payload.get("checks") or {}
            _require(isinstance(checks, dict) and set(checks) == set(CATEGORIES)
                     and all(v in _RANK for v in checks.values()),
                     f"seq {event['seq']}: security review needs checks for {list(CATEGORIES)}")
            worst = max(checks.values(), key=_RANK.__getitem__)
            _require(verdict.value == OVERALL[worst],
                     f"seq {event['seq']}: security verdict {verdict.value} contradicts its checks ({OVERALL[worst]})")
        p.reviews.append({"kind": rk.value, "verdict": verdict.value, "reviewer": actor,
                          "summary": payload["summary"], "checks": payload.get("checks", {}),
                          "revision": p.revision, "at": at})
    elif kind is E.MARK_READY:
        _require(p.tests is not None and p.tests["revision"] == p.revision,
                 f"seq {event['seq']}: no test results for revision {p.revision}")
        _require(p.tests["failed"] == 0, f"seq {event['seq']}: tests failing")
        cur = p.current_reviews()
        for need in (ReviewKind.CODE, ReviewKind.SECURITY):
            latest = [r for r in cur if r["kind"] == need.value]
            _require(bool(latest) and latest[-1]["verdict"] == Verdict.PASS.value,
                     f"seq {event['seq']}: {need.value} review PASS missing for revision {p.revision}")
        perf = [r for r in cur if r["kind"] == ReviewKind.PERFORMANCE.value]
        _require(not perf or perf[-1]["verdict"] == Verdict.PASS.value,
                 f"seq {event['seq']}: PERFORMANCE review not PASS")
    elif kind is E.REVISE:
        _require(actor == p.author, f"seq {event['seq']}: only the author revises")
        changes = {k: v for k, v in payload.items() if k in REQUIRED_CREATE_FIELDS or k in p.fields}
        p.fields.update(changes)
        _require(not touches_protected(p.fields.get("affected_files", []))
                 or p.fields.get("risk_level") == "CRITICAL",
                 f"seq {event['seq']}: a change to protected governance files must be CRITICAL")
        if p.status is S.REVISION_REQUIRED:
            p.revision += 1
    elif kind in OWNER_ONLY:
        p.owner_decision = {"decision": target.value, "at": at, "note": payload.get("note", "")}

    if target is not None:
        p.status = target
    p.history.append({"seq": event["seq"], "event": kind.value, "actor": actor, "at": at,
                      "status": p.status.value, "note": payload.get("note", "")})


def replay(events: Iterable[dict[str, Any]]) -> dict[str, Proposal]:
    """Rebuild every proposal from the log; raise ProposalLogError on any defect."""

    proposals: dict[str, Proposal] = {}
    expected_seq, prev = 1, GENESIS_HASH
    for event in events:
        _require(isinstance(event, dict), "event is not an object")
        _require(event.get("seq") == expected_seq,
                 f"sequence break: expected {expected_seq}, got {event.get('seq')!r}")
        _require(event.get("prev_hash") == prev, f"seq {expected_seq}: hash chain broken")
        _require(event.get("hash") == event_hash(event), f"seq {expected_seq}: record altered")
        _apply(proposals, event)
        prev, expected_seq = event["hash"], expected_seq + 1
    return proposals


def next_event(events: list[dict[str, Any]], *, proposal_id: str, event: EventType | str,
               actor: str, at: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the next chained event and prove it is valid by replaying the whole log with it."""

    record: dict[str, Any] = {
        "seq": len(events) + 1,
        "prev_hash": events[-1]["hash"] if events else GENESIS_HASH,
        "proposal_id": proposal_id,
        "event": EventType(event).value,
        "actor": actor,
        "at": at,
        "payload": payload or {},
    }
    record["hash"] = event_hash(record)
    replay([*events, record])
    return record
