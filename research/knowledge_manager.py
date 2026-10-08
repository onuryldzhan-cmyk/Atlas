"""Knowledge Manager v1 -- research only (GRANT-KNOWLEDGE-MANAGER-V1-RESEARCH-ONLY, v5.87).

Records sources, claims, evidence, validations and owner signatures, and
derives each claim's status from them. Its output is evidence for the owner,
never trading authority: it imports nothing outside ``research/``
(ADR-0009) -- in particular not ``atlas_org`` (v5.87 D1) -- no runtime
module imports it, and nothing here reaches a risk gate, capital, an order
path or the runtime brain. It is unrelated to the ``knowledge_manager``
org agent and its lesson workflow, which v5.87 leaves unchanged.

**Lineage** (v5.87 C-1)::

    SOURCE -> CLAIM -> EVIDENCE -> VALIDATION -> VALIDATED
           -> OWNER SIGNATURE -> AUTHORITATIVE

**Statuses** are derived from the log on every read, never stored:

* ``UNKNOWN`` -- no such claim, or a claim with no active evidence. Unknown
  is shown as unknown; nothing is invented to fill it.
* ``CONTESTED`` -- at least one active contradicting evidence item. It blocks
  VALIDATED and AUTHORITATIVE (D2). Unverifiable counter-evidence blocks too:
  that is the conservative direction.
* ``UNVALIDATED`` -- active evidence, not contested, no current validation.
* ``VALIDATED`` -- a current validation: by a validator who is neither the
  claim author nor the owner (D3), over an evidence set holding at least one
  active *verifiable* supporting item (D5), with no active contradiction.
* ``AUTHORITATIVE`` -- VALIDATED plus an owner signature over that same
  validation and evidence set, *verified* with the pinned owner key (D1).
  The signature is accepted only on a VALIDATED claim and never creates or
  promotes VALIDATED. Without a key that matches the pinned fingerprint a
  claim can never become AUTHORITATIVE; a signature that is present but not
  verified in this call is reported ``UNVERIFIED`` and the status stays
  VALIDATED.

**Evidence set hash.** One hash over every evidence item ever recorded for a
claim *with its withdrawal state*. A validation and a signature are bound to
it, so any later change -- new evidence, or a withdrawal (D4) -- leaves them
stale: the claim falls back to UNVALIDATED (or CONTESTED) and needs a new
validation. Because withdrawn items stay in the hash, withdrawing a
contradiction never restores an earlier validation (D2), and removing or
adding unverifiable evidence can never raise a status (NB-4).

**Verifiable** (v1 boundary, D5): an evidence item that carries a 64-hex
SHA-256 ``content_digest`` of the artefact it refers to, so anyone holding
the artefact can check it. Resolving the artefact itself is out of scope
(in memory, no I/O). Multiple independent sources are not required.

**Identity.** Actor ids are caller-asserted strings; this module has no
identity system. ``validator != author`` and ``validator != owner`` are
enforced on normalised ids. The one actor whose identity *is* checked is the
owner: signing, and withdrawing as the owner, both need the owner key whose
SHA-256 fingerprint was pinned at construction. No key is stored here.

**Owner signature bytes** match ``atlas_org.owner_auth`` (HMAC-SHA256 over the
canonical JSON of the event without ``hash`` / ``owner_sig``, sorted keys,
compact separators, UTF-8, ``ensure_ascii=False``; keys of at least 32
bytes). Re-implemented here, not imported (D1); a test pins the equality.

**Storage.** None. The log is an in-memory, append-only, SHA-256 hash-chained
(unkeyed) tuple; it is lost when the process ends and is never durable
evidence. Payloads are deep-frozen, and every public read re-verifies the
chain first.

**Fail safe.** An integrity failure (broken chain, a signature that does not
verify under the pinned key) or an unexpected error halts the manager; every
later read and write raises ``KnowledgeManagerHalted``. Only ``log`` stays
readable after a halt, as unverified forensic evidence. Malformed or refused
caller input raises without halting and without writing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

#: The owner's actor id (the same literal ``atlas_org`` uses; not imported).
OWNER = "owner"
#: Field holding the owner signature (same name as ``atlas_org.owner_auth``).
SIG_FIELD = "owner_sig"
MIN_OWNER_KEY_BYTES = 32

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ACTOR_PATTERN = re.compile(r"^[A-Za-z0-9_.:@-]{1,64}$")
_URI_PATTERN = re.compile(r"^\S{1,500}$")
_MAX_TEXT = 2000
_GENESIS = "0" * 64


class KnowledgeError(Exception):
    """Base error for Knowledge Manager contract violations."""


class KnowledgeInputError(KnowledgeError):
    """Malformed, unknown or refused caller input. Nothing is written."""


class IllegalKnowledgeTransitionError(KnowledgeError):
    """The lineage does not permit the requested step."""


class OwnerKeyError(KnowledgeError):
    """No owner key is pinned, or the supplied key does not match the pin."""


class KnowledgeIntegrityError(KnowledgeError):
    """Log chain or an owner signature failed verification. Halts."""


class KnowledgeManagerHalted(KnowledgeError):
    """The manager stopped after an integrity failure or unexpected error."""


class SourceKind(str, Enum):
    MARKET_DATA = "MARKET_DATA"
    MARKET_ARCHIVE = "MARKET_ARCHIVE"
    NEWS = "NEWS"
    ONCHAIN = "ONCHAIN"
    DERIVED = "DERIVED"
    MODEL = "MODEL"
    MANUAL = "MANUAL"


class Stance(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"


class ClaimStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    CONTESTED = "CONTESTED"
    UNVALIDATED = "UNVALIDATED"
    VALIDATED = "VALIDATED"
    AUTHORITATIVE = "AUTHORITATIVE"


class SignatureState(str, Enum):
    ABSENT = "ABSENT"
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


# -- canonical form, hashing, signing ------------------------------------


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def key_fingerprint(owner_key: bytes) -> str:
    """SHA-256 hex of the owner key bytes: what the manager pins, never the key."""
    if not isinstance(owner_key, bytes) or len(owner_key) < MIN_OWNER_KEY_BYTES:
        raise OwnerKeyError(f"owner key must be at least {MIN_OWNER_KEY_BYTES} bytes")
    return hashlib.sha256(owner_key).hexdigest()


def signing_body(event: Mapping[str, Any]) -> bytes:
    """The bytes an owner signature covers (``atlas_org.owner_auth`` layout)."""
    body = {k: v for k, v in event.items() if k not in ("hash", SIG_FIELD)}
    return _canonical(body).encode("utf-8")


def _sign(owner_key: bytes, event: Mapping[str, Any]) -> str:
    return hmac.new(owner_key, signing_body(event), hashlib.sha256).hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


# -- input validation ------------------------------------------------------


def _actor(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ACTOR_PATTERN.match(value):
        raise KnowledgeInputError(f"{name} must match {_ACTOR_PATTERN.pattern}, got {value!r}")
    return value


def _same_actor(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT:
        raise KnowledgeInputError(f"{name} must be non-empty text of at most {_MAX_TEXT} chars")
    return value.strip()


def _hash_ref(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.match(value):
        raise KnowledgeInputError(f"{name} must be a 64-hex SHA-256 reference")
    return value


def _aware_timestamp(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise KnowledgeInputError(f"{name} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise KnowledgeInputError(f"{name} is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise KnowledgeInputError(f"{name} must carry a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except ValueError as exc:
        raise KnowledgeInputError(
            f"{name} must be one of {[m.value for m in enum_type]}, got {value!r}"
        ) from exc


# -- records ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One append-only, hash-chained log entry. The payload is deep-frozen."""

    sequence: int
    kind: str
    payload: Mapping[str, Any]
    recorded_at: str
    previous_hash: str
    entry_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _freeze(self.payload))

    def hashed_body(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "payload": _thaw(self.payload),
            "recorded_at": self.recorded_at,
            "previous_hash": self.previous_hash,
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.hashed_body(), "entry_hash": self.entry_hash}


@dataclass(frozen=True, slots=True)
class ClaimView:
    """A claim's derived state. Evidence for the owner; it carries no authority."""

    claim_id: str
    status: ClaimStatus
    reasons: tuple[str, ...]
    evidence_set_hash: str | None
    verifiable_supporting: int
    unverifiable_supporting: int
    active_contradicting: int
    withdrawn: int
    validation_hash: str | None
    owner_signature: SignatureState


class KnowledgeManager:
    """Research-only, in-memory claim/evidence state machine."""

    def __init__(self, *, owner_key_fingerprint: str | None = None) -> None:
        if owner_key_fingerprint is not None and not (
            isinstance(owner_key_fingerprint, str) and _HEX64.match(owner_key_fingerprint)
        ):
            raise OwnerKeyError("owner_key_fingerprint must be a 64-hex SHA-256 or None")
        self._owner_fingerprint = owner_key_fingerprint
        self._log: list[LogEntry] = []
        self._halted = False

    # -- guards --------------------------------------------------------------

    @property
    def halted(self) -> bool:
        return self._halted

    def _guarded(self, operation, *args):
        if self._halted:
            raise KnowledgeManagerHalted("knowledge manager is halted")
        try:
            return operation(*args)
        except KnowledgeIntegrityError:
            self._halted = True
            raise
        except KnowledgeError:
            raise
        except Exception as exc:  # unexpected: stop rather than continue
            self._halted = True
            raise KnowledgeManagerHalted(
                f"halted on unexpected {type(exc).__name__}: {exc}"
            ) from exc

    def _require_owner_key(self, owner_key: Any) -> bytes:
        if self._owner_fingerprint is None:
            raise OwnerKeyError("no owner key is pinned; nothing can be owner-signed")
        if not hmac.compare_digest(key_fingerprint(owner_key), self._owner_fingerprint):
            raise OwnerKeyError("owner key does not match the pinned fingerprint")
        return owner_key

    # -- log -----------------------------------------------------------------

    @property
    def log(self) -> tuple[LogEntry, ...]:
        """The frozen log, verified first. After a halt: unverified, forensic only."""
        if self._halted:
            return tuple(self._log)
        return self._guarded(self._verified_log)

    def _verified_log(self) -> tuple[LogEntry, ...]:
        self._verify_log()
        return tuple(self._log)

    def verify_log(self) -> None:
        self._guarded(self._verify_log)

    def _verify_log(self) -> None:
        previous = _GENESIS
        for index, entry in enumerate(self._log):
            if entry.sequence != index or entry.previous_hash != previous:
                raise KnowledgeIntegrityError(f"log chain broken at entry {index}")
            if _sha256(entry.hashed_body()) != entry.entry_hash:
                raise KnowledgeIntegrityError(f"log entry {index} hash mismatch")
            previous = entry.entry_hash

    def _append(self, kind: str, payload: Mapping[str, Any]) -> LogEntry:
        body = {
            "sequence": len(self._log),
            "kind": kind,
            "payload": json.loads(_canonical(payload)),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "previous_hash": self._log[-1].entry_hash if self._log else _GENESIS,
        }
        entry = LogEntry(**body, entry_hash=_sha256(body))
        self._log.append(entry)
        return entry

    def _of(self, kind: str, **match: Any) -> tuple[LogEntry, ...]:
        return tuple(
            e for e in self._log
            if e.kind == kind and all(e.payload.get(k) == v for k, v in match.items())
        )

    def _one(self, kind: str, id_field: str, value: str) -> LogEntry | None:
        found = self._of(kind, **{id_field: value})
        return found[0] if found else None

    # -- writes --------------------------------------------------------------

    def register_source(
        self, *, kind: str, uri: str, retrieved_at: str, source_digest: str | None = None
    ) -> str:
        return self._guarded(self._register_source, kind, uri, retrieved_at, source_digest)

    def _register_source(self, kind, uri, retrieved_at, source_digest) -> str:
        self._verify_log()
        if not isinstance(uri, str) or not _URI_PATTERN.match(uri):
            raise KnowledgeInputError("uri must be 1-500 non-whitespace characters")
        fields = {
            "kind": _enum(kind, SourceKind, "kind"),
            "uri": uri,
            "retrieved_at": _aware_timestamp(retrieved_at, "retrieved_at"),
            "source_digest": None if source_digest is None else _hash_ref(source_digest, "source_digest"),
        }
        source_id = _sha256({"source": fields})
        if self._one("SOURCE_REGISTERED", "source_id", source_id) is None:
            self._append("SOURCE_REGISTERED", {"source_id": source_id, **fields})
        return source_id

    def register_claim(self, *, statement: str, author: str, source_ids: tuple[str, ...]) -> str:
        return self._guarded(self._register_claim, statement, author, source_ids)

    def _register_claim(self, statement, author, source_ids) -> str:
        self._verify_log()
        statement = _text(statement, "statement")
        author = _actor(author, "author")
        # Audit KM-A1: a non-sequence is malformed input, refused without halting.
        if not isinstance(source_ids, (tuple, list)) or not source_ids:
            raise KnowledgeInputError("a claim must be linked to at least one source (tuple or list)")
        refs = sorted({_hash_ref(s, "source_id") for s in source_ids})
        if len(refs) != len(tuple(source_ids)):
            raise KnowledgeInputError("duplicate source_id")
        for ref in refs:
            if self._one("SOURCE_REGISTERED", "source_id", ref) is None:
                raise KnowledgeInputError(f"source {ref} is not registered")
        claim_id = _sha256({"claim": {"statement": statement, "author": author, "source_ids": refs}})
        if self._one("CLAIM_REGISTERED", "claim_id", claim_id) is None:
            self._append(
                "CLAIM_REGISTERED",
                {"claim_id": claim_id, "statement": statement, "author": author, "source_ids": refs},
            )
        return claim_id

    def add_evidence(
        self,
        *,
        claim_id: str,
        stance: str,
        source_id: str,
        submitter: str,
        description: str,
        content_digest: str | None = None,
    ) -> str:
        return self._guarded(
            self._add_evidence, claim_id, stance, source_id, submitter, description, content_digest
        )

    def _add_evidence(self, claim_id, stance, source_id, submitter, description, content_digest) -> str:
        self._verify_log()
        claim_id = self._known_claim(claim_id)
        source_id = _hash_ref(source_id, "source_id")
        if self._one("SOURCE_REGISTERED", "source_id", source_id) is None:
            raise KnowledgeInputError(f"source {source_id} is not registered")
        fields = {
            "claim_id": claim_id,
            "stance": _enum(stance, Stance, "stance"),
            "source_id": source_id,
            "submitter": _actor(submitter, "submitter"),
            "description": _text(description, "description"),
            "content_digest": None if content_digest is None else _hash_ref(content_digest, "content_digest"),
        }
        evidence_id = _sha256({"evidence": fields})
        if self._one("EVIDENCE_ADDED", "evidence_id", evidence_id) is None:
            self._append("EVIDENCE_ADDED", {"evidence_id": evidence_id, **fields})
        return evidence_id

    def withdraw_evidence(
        self, *, evidence_id: str, actor: str, reason: str, owner_key: bytes | None = None
    ) -> LogEntry:
        return self._guarded(self._withdraw, evidence_id, actor, reason, owner_key)

    def _withdraw(self, evidence_id, actor, reason, owner_key) -> LogEntry:
        self._verify_log()
        evidence_id = _hash_ref(evidence_id, "evidence_id")
        added = self._one("EVIDENCE_ADDED", "evidence_id", evidence_id)
        if added is None:
            raise KnowledgeInputError(f"evidence {evidence_id} is not recorded")
        actor = _actor(actor, "actor")
        reason = _text(reason, "reason")
        if _same_actor(actor, OWNER):
            self._require_owner_key(owner_key)  # the owner's identity is checked
            actor = OWNER
        elif not _same_actor(actor, added.payload["submitter"]):
            raise IllegalKnowledgeTransitionError(
                "only the evidence submitter or the owner may withdraw evidence"
            )
        if self._one("EVIDENCE_WITHDRAWN", "evidence_id", evidence_id) is not None:
            raise IllegalKnowledgeTransitionError("evidence is already withdrawn")
        return self._append(
            "EVIDENCE_WITHDRAWN",
            {"evidence_id": evidence_id, "claim_id": added.payload["claim_id"],
             "actor": actor, "reason": reason},
        )

    def record_validation(self, *, claim_id: str, validator: str) -> LogEntry:
        return self._guarded(self._record_validation, claim_id, validator)

    def _record_validation(self, claim_id, validator) -> LogEntry:
        self._verify_log()
        claim_id = self._known_claim(claim_id)
        validator = _actor(validator, "validator")
        if _same_actor(validator, OWNER):
            raise IllegalKnowledgeTransitionError("the owner is never a validator")
        author = self._one("CLAIM_REGISTERED", "claim_id", claim_id).payload["author"]
        if _same_actor(validator, author):
            raise IllegalKnowledgeTransitionError("the validator must differ from the claim author")
        facts = self._facts(claim_id)
        if facts["active_contradicting"]:
            raise IllegalKnowledgeTransitionError("a CONTESTED claim cannot be validated")
        if not facts["verifiable_supporting"]:
            raise IllegalKnowledgeTransitionError(
                "VALIDATED needs at least one active verifiable supporting evidence item"
            )
        for entry in self._of("VALIDATION_RECORDED", claim_id=claim_id, validator=validator,
                              evidence_set_hash=facts["evidence_set_hash"]):
            return entry  # idempotent: the same validation of the same basis
        return self._append(
            "VALIDATION_RECORDED",
            {"claim_id": claim_id, "validator": validator,
             "evidence_set_hash": facts["evidence_set_hash"]},
        )

    def owner_sign(self, *, claim_id: str, owner_key: bytes) -> LogEntry:
        return self._guarded(self._owner_sign, claim_id, owner_key)

    def _owner_sign(self, claim_id, owner_key) -> LogEntry:
        self._verify_log()
        claim_id = self._known_claim(claim_id)
        key = self._require_owner_key(owner_key)
        view = self._view(claim_id, key)
        if view.owner_signature is SignatureState.VERIFIED:
            return self._signature_for(claim_id, view.validation_hash, view.evidence_set_hash)
        if view.status is not ClaimStatus.VALIDATED:
            raise IllegalKnowledgeTransitionError(
                f"an owner signature needs a VALIDATED claim; this one is {view.status.value}"
            )
        event = {
            "kind": "KNOWLEDGE_OWNER_SIGNATURE",
            "actor": OWNER,
            "claim_id": claim_id,
            "validation_hash": view.validation_hash,
            "evidence_set_hash": view.evidence_set_hash,
            "key_fingerprint": self._owner_fingerprint,
        }
        return self._append("OWNER_SIGNED", {**event, SIG_FIELD: _sign(key, event)})

    # -- derivation ----------------------------------------------------------

    def _known_claim(self, claim_id: Any) -> str:
        claim_id = _hash_ref(claim_id, "claim_id")
        if self._one("CLAIM_REGISTERED", "claim_id", claim_id) is None:
            raise KnowledgeInputError(f"claim {claim_id} is not registered")
        return claim_id

    def _facts(self, claim_id: str) -> dict[str, Any]:
        withdrawn = {e.payload["evidence_id"] for e in self._of("EVIDENCE_WITHDRAWN", claim_id=claim_id)}
        items = self._of("EVIDENCE_ADDED", claim_id=claim_id)
        active = [e.payload for e in items if e.payload["evidence_id"] not in withdrawn]
        support = [p for p in active if p["stance"] == Stance.SUPPORTS.value]
        return {
            # Every item ever added, with its withdrawal state: any change moves it.
            "evidence_set_hash": _sha256({
                "claim_id": claim_id,
                "evidence": sorted(
                    [e.payload["evidence_id"], e.payload["evidence_id"] in withdrawn] for e in items
                ),
            }),
            "active": len(active),
            "verifiable_supporting": sum(1 for p in support if p["content_digest"] is not None),
            "unverifiable_supporting": sum(1 for p in support if p["content_digest"] is None),
            "active_contradicting": sum(1 for p in active if p["stance"] == Stance.CONTRADICTS.value),
            "withdrawn": len(withdrawn),
        }

    def _signature_for(self, claim_id: str, validation_hash: str | None, set_hash: str | None):
        for entry in self._of("OWNER_SIGNED", claim_id=claim_id,
                              validation_hash=validation_hash, evidence_set_hash=set_hash):
            return entry
        return None

    def claim_view(self, claim_id: str, *, owner_key: bytes | None = None) -> ClaimView:
        """Derived state. AUTHORITATIVE only when the signature verifies with ``owner_key``."""
        return self._guarded(self._verified_view, claim_id, owner_key)

    def status(self, claim_id: str, *, owner_key: bytes | None = None) -> ClaimStatus:
        return self.claim_view(claim_id, owner_key=owner_key).status

    def _verified_view(self, claim_id, owner_key) -> ClaimView:
        self._verify_log()
        claim_id = _hash_ref(claim_id, "claim_id")
        key = None if owner_key is None else self._require_owner_key(owner_key)
        return self._view(claim_id, key)

    def _view(self, claim_id: str, key: bytes | None) -> ClaimView:
        if self._one("CLAIM_REGISTERED", "claim_id", claim_id) is None:
            return ClaimView(claim_id, ClaimStatus.UNKNOWN, ("CLAIM_NOT_REGISTERED",), None,
                             0, 0, 0, 0, None, SignatureState.ABSENT)
        facts = self._facts(claim_id)
        set_hash = facts["evidence_set_hash"]

        def view(status, reasons, validation_hash=None, signature=SignatureState.ABSENT):
            return ClaimView(claim_id, status, tuple(reasons), set_hash,
                             facts["verifiable_supporting"], facts["unverifiable_supporting"],
                             facts["active_contradicting"], facts["withdrawn"],
                             validation_hash, signature)

        if not facts["active"]:
            return view(ClaimStatus.UNKNOWN, ["NO_ACTIVE_EVIDENCE"])
        if facts["active_contradicting"]:
            return view(ClaimStatus.CONTESTED, ["ACTIVE_CONTRADICTING_EVIDENCE"])
        current = self._of("VALIDATION_RECORDED", claim_id=claim_id, evidence_set_hash=set_hash)
        if not current:
            stale = bool(self._of("VALIDATION_RECORDED", claim_id=claim_id))
            return view(ClaimStatus.UNVALIDATED,
                        ["VALIDATION_STALE_EVIDENCE_CHANGED" if stale else "NO_VALIDATION"])
        if not facts["verifiable_supporting"]:  # defence in depth; unreachable via writes
            return view(ClaimStatus.UNVALIDATED, ["NO_VERIFIABLE_SUPPORTING_EVIDENCE"])
        # A signature binds one validation of this exact evidence set; another
        # validator re-validating the same set does not orphan it.
        signature = None
        for validation in current:
            signature = self._signature_for(claim_id, validation.entry_hash, set_hash) or signature
        validation_hash = signature.payload["validation_hash"] if signature else current[-1].entry_hash
        if signature is None:
            return view(ClaimStatus.VALIDATED, ["VALIDATED_NOT_OWNER_SIGNED"], validation_hash)
        if key is None or signature.payload["key_fingerprint"] != self._owner_fingerprint:
            return view(ClaimStatus.VALIDATED, ["OWNER_SIGNATURE_NOT_VERIFIED"],
                        validation_hash, SignatureState.UNVERIFIED)
        event = {k: v for k, v in _thaw(signature.payload).items()}
        if not hmac.compare_digest(str(event.get(SIG_FIELD)), _sign(key, event)):
            raise KnowledgeIntegrityError(f"owner signature on claim {claim_id} does not verify")
        return view(ClaimStatus.AUTHORITATIVE, ["OWNER_SIGNED_VALIDATED_CLAIM"],
                    validation_hash, SignatureState.VERIFIED)

    def evidence_for(self, claim_id: str) -> tuple[LogEntry, ...]:
        """Every evidence item of a claim, withdrawn ones included (provenance kept)."""
        return self._guarded(self._evidence_for, claim_id)

    def _evidence_for(self, claim_id) -> tuple[LogEntry, ...]:
        self._verify_log()
        return self._of("EVIDENCE_ADDED", claim_id=self._known_claim(claim_id))
