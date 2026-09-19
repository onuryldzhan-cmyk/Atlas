"""Durable, queryable Evidence Store for Atlas research claims.

Every significant Atlas assertion is persisted here as a ``ClaimRecord``
carrying the owner-specified chain:

    CLAIM -> SOURCE -> EVIDENCE -> TIMESTAMP -> AGENT -> CONFIDENCE
    -> COUNTER-EVIDENCE

Naming
------
The persisted unit is a *claim*, deliberately NOT called ``Evidence``.
``core.decision_intelligence.Evidence`` already exists and means something
different: one agent's per-cycle directional vote, consumed by
``SignalFusion`` and then discarded. That type is untouched by this module.
A claim is the durable statement; evidence is what stands behind it.

Immutability
------------
``claims``, ``claim_sources`` and ``claim_relations`` rows are written once
and never UPDATEd. A claim's lifecycle is an append-only sequence in
``claim_status_history``, and the current status is resolved through the
``claim_current_status`` view. This applies the project's standing
governance rule - reconcile by adding a successor record, never by editing
a historical one - to research state.

Failure posture
---------------
This store is observational: it is NOT on the decision path and carries no
trading authority. Its caller on that path (ai/core/atlas_brain.py) treats
every failure here as fail-open. The store itself still fails loudly - it
raises ``StorageError`` rather than silently discarding a write - so the
caller decides, and ``health()`` reports what happened.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any

# ClaimSource lives in contracts so a claim producer can build one without
# importing this store. Re-exported here: it is part of this module's
# established public API.
from .contracts import ClaimSource, IntegrityViolation, StorageError
from .migrations import Migration, apply_migrations


logger = logging.getLogger("AtlasAI.EvidenceStore")


# The payload contract version stamped onto every row this build writes.
# Deliberately separate from the migration id: payload shape evolves faster
# than table shape. Readers must accept any value <= this one; evolution is
# additive only, and a breaking change takes a new claim_kind rather than
# redefining an existing one.
CLAIM_SCHEMA_VERSION = 1

DATABASE_FILENAME = "evidence_store.sqlite3"


class ClaimKind(str, Enum):
    REGIME = "REGIME"
    DIRECTIONAL = "DIRECTIONAL"
    RISK = "RISK"
    CORRELATION = "CORRELATION"
    ANOMALY = "ANOMALY"
    MACRO = "MACRO"
    OTHER = "OTHER"


class SubjectScope(str, Enum):
    SYMBOL = "SYMBOL"
    MARKET = "MARKET"
    PORTFOLIO = "PORTFOLIO"
    SYSTEM = "SYSTEM"


class SourceKind(str, Enum):
    MARKET_DATA = "MARKET_DATA"
    MARKET_ARCHIVE = "MARKET_ARCHIVE"
    NEWS = "NEWS"
    ONCHAIN = "ONCHAIN"
    DERIVED = "DERIVED"
    MODEL = "MODEL"
    MANUAL = "MANUAL"


class RelationKind(str, Enum):
    CONTRADICTS = "CONTRADICTS"
    SUPPORTS = "SUPPORTS"
    SUPERSEDES = "SUPERSEDES"
    REFINES = "REFINES"
    PRECEDENT_OF = "PRECEDENT_OF"


class ClaimStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"
    EXPIRED = "EXPIRED"


# CONTRADICTS is the only semantically symmetric relation: if A contradicts
# B then B contradicts A. It is therefore stored as two rows written in one
# transaction, so every counter-evidence read stays a single index seek
# instead of a UNION over both directions. SUPERSEDES / REFINES /
# PRECEDENT_OF are directional and are stored once.
SYMMETRIC_RELATIONS = frozenset({RelationKind.CONTRADICTS})

# Statuses that remove a claim from default counter-evidence results: a
# retracted or superseded claim no longer argues against anything.
INACTIVE_STATUSES: tuple[str, ...] = (
    ClaimStatus.RETRACTED.value,
    ClaimStatus.SUPERSEDED.value,
)


_CLAIMS_TABLE = """
CREATE TABLE claims (
    claim_id TEXT PRIMARY KEY CHECK (trim(claim_id) <> ''),
    schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
    claim_text TEXT NOT NULL CHECK (trim(claim_text) <> ''),
    claim_kind TEXT NOT NULL CHECK (claim_kind IN (
        'REGIME','DIRECTIONAL','RISK','CORRELATION','ANOMALY','MACRO','OTHER'
    )),
    subject_scope TEXT NOT NULL CHECK (subject_scope IN (
        'SYMBOL','MARKET','PORTFOLIO','SYSTEM'
    )),
    subject_symbol TEXT,
    agent_id TEXT NOT NULL CHECK (trim(agent_id) <> ''),
    agent_version TEXT NOT NULL CHECK (trim(agent_version) <> ''),
    model_provider TEXT,
    model_name TEXT,
    confidence_text TEXT NOT NULL
        CHECK (CAST(confidence_text AS REAL) BETWEEN 0 AND 1),
    asserted_at_utc TEXT NOT NULL CHECK (trim(asserted_at_utc) <> ''),
    observation_start_utc TEXT,
    observation_end_utc TEXT,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    reason_codes_json TEXT NOT NULL CHECK (json_valid(reason_codes_json)),
    run_id TEXT NOT NULL CHECK (trim(run_id) <> ''),
    created_at_utc TEXT NOT NULL CHECK (trim(created_at_utc) <> ''),
    CHECK (
        subject_scope <> 'SYMBOL'
        OR (subject_symbol IS NOT NULL AND trim(subject_symbol) <> '')
    ),
    CHECK ((model_provider IS NULL) = (model_name IS NULL)),
    CHECK (
        observation_end_utc IS NULL
        OR observation_start_utc IS NULL
        OR observation_end_utc >= observation_start_utc
    )
)
"""

_CLAIM_SOURCES_TABLE = """
CREATE TABLE claim_sources (
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE RESTRICT,
    source_ordinal INTEGER NOT NULL CHECK (source_ordinal >= 0),
    source_kind TEXT NOT NULL CHECK (source_kind IN (
        'MARKET_DATA','MARKET_ARCHIVE','NEWS','ONCHAIN','DERIVED','MODEL','MANUAL'
    )),
    source_uri TEXT NOT NULL CHECK (trim(source_uri) <> ''),
    source_version TEXT NOT NULL CHECK (trim(source_version) <> ''),
    retrieved_at_utc TEXT NOT NULL CHECK (trim(retrieved_at_utc) <> ''),
    source_digest TEXT,
    PRIMARY KEY (claim_id, source_ordinal)
)
"""

_CLAIM_RELATIONS_TABLE = """
CREATE TABLE claim_relations (
    relation_id TEXT PRIMARY KEY CHECK (trim(relation_id) <> ''),
    from_claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE RESTRICT,
    to_claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE RESTRICT,
    relation_kind TEXT NOT NULL CHECK (relation_kind IN (
        'CONTRADICTS','SUPPORTS','SUPERSEDES','REFINES','PRECEDENT_OF'
    )),
    weight_text TEXT CHECK (
        weight_text IS NULL OR CAST(weight_text AS REAL) BETWEEN 0 AND 1
    ),
    created_by TEXT NOT NULL CHECK (trim(created_by) <> ''),
    created_at_utc TEXT NOT NULL CHECK (trim(created_at_utc) <> ''),
    CHECK (from_claim_id <> to_claim_id),
    UNIQUE (from_claim_id, to_claim_id, relation_kind)
)
"""

_CLAIM_STATUS_HISTORY_TABLE = """
CREATE TABLE claim_status_history (
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE RESTRICT,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    status TEXT NOT NULL CHECK (status IN (
        'ACTIVE','PARTIALLY_SUPPORTED','CONTRADICTED','SUPERSEDED','RETRACTED','EXPIRED'
    )),
    reason TEXT NOT NULL CHECK (trim(reason) <> ''),
    decided_by TEXT NOT NULL CHECK (trim(decided_by) <> ''),
    decided_at_utc TEXT NOT NULL CHECK (trim(decided_at_utc) <> ''),
    PRIMARY KEY (claim_id, sequence)
)
"""

_CLAIM_CURRENT_STATUS_VIEW = """
CREATE VIEW claim_current_status AS
SELECT h.claim_id, h.status, h.reason, h.decided_by, h.decided_at_utc
FROM claim_status_history h
JOIN (
    SELECT claim_id, MAX(sequence) AS newest
    FROM claim_status_history
    GROUP BY claim_id
) m ON m.claim_id = h.claim_id AND m.newest = h.sequence
"""


EVIDENCE_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        1,
        "evidence_store_foundation",
        (
            _CLAIMS_TABLE,
            "CREATE INDEX idx_claims_symbol_time ON claims(subject_symbol, asserted_at_utc)",
            "CREATE INDEX idx_claims_agent_time ON claims(agent_id, asserted_at_utc)",
            "CREATE INDEX idx_claims_kind_time ON claims(claim_kind, asserted_at_utc)",
            (
                "CREATE UNIQUE INDEX idx_claims_idem ON claims("
                "agent_id, subject_symbol, claim_kind, payload_digest, asserted_at_utc)"
            ),
            _CLAIM_SOURCES_TABLE,
            "CREATE INDEX idx_sources_claim ON claim_sources(claim_id)",
            _CLAIM_RELATIONS_TABLE,
            "CREATE INDEX idx_relations_to ON claim_relations(to_claim_id, relation_kind)",
            "CREATE INDEX idx_relations_from ON claim_relations(from_claim_id, relation_kind)",
            _CLAIM_STATUS_HISTORY_TABLE,
            _CLAIM_CURRENT_STATUS_VIEW,
        ),
    ),
)


# =================================================================
# VALUE COERCION
# =================================================================
#
# Mirrors core/decision_intelligence.py's _decimal()/_utc() contracts:
# a float confidence and a timezone-naive timestamp are rejected at the
# boundary rather than quietly coerced, because both silently destroy the
# provenance this store exists to preserve.


def _confidence_text(value: Any, name: str = "confidence") -> str:
    if isinstance(value, float):
        raise IntegrityViolation(f"{name} must not be float; pass Decimal or str")
    if isinstance(value, bool):
        raise IntegrityViolation(f"{name} must not be bool")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise IntegrityViolation(f"invalid {name}") from exc
    if not result.is_finite():
        raise IntegrityViolation(f"{name} must be finite")
    if not Decimal("0") <= result <= Decimal("1"):
        raise IntegrityViolation(f"{name} must be in 0..1")
    return str(result)


def _optional_weight_text(value: Any) -> str | None:
    if value is None:
        return None
    return _confidence_text(value, "weight")


def _utc_text(value: Any, name: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise IntegrityViolation(f"{name} must be a timezone-aware datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _optional_utc_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _utc_text(value, name)


def _canonical_json(payload: Any) -> str:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise IntegrityViolation("payload is not canonically serialisable") from exc


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntegrityViolation(f"{name} is required")
    return value


def _enum_value(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except ValueError as exc:
        raise IntegrityViolation(f"invalid {name}: {value!r}") from exc


# =================================================================
# RECORDS
# =================================================================


@dataclass(frozen=True)
class ClaimRecord:
    """A persisted claim as read back from the store."""

    claim_id: str
    schema_version: int
    claim_text: str
    claim_kind: str
    subject_scope: str
    subject_symbol: str | None
    agent_id: str
    agent_version: str
    model_provider: str | None
    model_name: str | None
    confidence: Decimal
    asserted_at_utc: str
    observation_start_utc: str | None
    observation_end_utc: str | None
    payload: Mapping[str, Any]
    payload_digest: str
    reason_codes: tuple[str, ...]
    run_id: str
    created_at_utc: str
    status: str = ClaimStatus.ACTIVE.value


def _claim_from_row(row: sqlite3.Row) -> ClaimRecord:
    return ClaimRecord(
        claim_id=row["claim_id"],
        schema_version=int(row["schema_version"]),
        claim_text=row["claim_text"],
        claim_kind=row["claim_kind"],
        subject_scope=row["subject_scope"],
        subject_symbol=row["subject_symbol"],
        agent_id=row["agent_id"],
        agent_version=row["agent_version"],
        model_provider=row["model_provider"],
        model_name=row["model_name"],
        confidence=Decimal(row["confidence_text"]),
        asserted_at_utc=row["asserted_at_utc"],
        observation_start_utc=row["observation_start_utc"],
        observation_end_utc=row["observation_end_utc"],
        payload=json.loads(row["payload_json"]),
        payload_digest=row["payload_digest"],
        reason_codes=tuple(json.loads(row["reason_codes_json"])),
        run_id=row["run_id"],
        created_at_utc=row["created_at_utc"],
        status=(
            row["status"]
            if "status" in row.keys() and row["status"] is not None
            else ClaimStatus.ACTIVE.value
        ),
    )


_CLAIM_COLUMNS = """
    c.claim_id, c.schema_version, c.claim_text, c.claim_kind, c.subject_scope,
    c.subject_symbol, c.agent_id, c.agent_version, c.model_provider, c.model_name,
    c.confidence_text, c.asserted_at_utc, c.observation_start_utc,
    c.observation_end_utc, c.payload_json, c.payload_digest, c.reason_codes_json,
    c.run_id, c.created_at_utc
"""

# Current status as a correlated, index-seekable subquery rather than a join
# against the claim_current_status view.
#
# The view is the readable definition of "current status" and stays for
# ad-hoc and dashboard use, but joining it here is a performance trap that
# EXPLAIN QUERY PLAN makes visible: SQLite MATERIALIZEs the view, which means
# a GROUP BY scan over the whole of claim_status_history on every call. That
# turns an O(log n + k) counter-evidence lookup into an O(history) one and
# defeats idx_relations_to at exactly the volume this store was chosen for.
#
# The correlated form below is a primary-key seek per candidate row
# (claim_id, sequence DESC), so traversal cost stays proportional to the
# number of related claims rather than to the size of the history table.
_STATUS_EXPR = (
    "COALESCE((SELECT h.status FROM claim_status_history h "
    "WHERE h.claim_id = c.claim_id ORDER BY h.sequence DESC LIMIT 1), 'ACTIVE')"
)

_STATUS_SELECT = f"{_STATUS_EXPR} AS status"


# =================================================================
# STORE
# =================================================================


class EvidenceStore:
    """SQLite-backed durable store for Atlas research claims.

    Connection handling mirrors ``data_layer/sqlite.py``: one short-lived
    connection per operation with ``foreign_keys`` on, an explicit
    ``busy_timeout`` and autocommit (``isolation_level=None``) so
    transaction boundaries are stated in SQL rather than inferred. WAL is
    enabled once at open() - the durable root is a local, non-synced disk
    (ADR-0007), which is the precondition WAL requires.
    """

    def __init__(
        self,
        database_path: Path | str,
        *,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        self.database_path = Path(database_path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self._opened = False
        self._lifecycle_lock = threading.Lock()
        self._schema_version: int | None = None
        self._last_error: str | None = None
        self._claims_written = 0
        self._claims_deduplicated = 0
        self._relations_written = 0
        self._write_failures = 0

    # -------------------------------------------------------------
    # LIFECYCLE
    # -------------------------------------------------------------

    def open(self) -> None:
        """Open the database and bring the schema to the current migration.

        The containing directory is NEVER created here. Creating it would
        turn a mistyped or not-yet-provisioned evidence root into a new,
        empty database that looks healthy - the same silent failure mode
        ``resolve_evidence_directory()`` exists to prevent, and the reason
        neither durable root is auto-created either. A missing directory
        raises ``StorageError``; the decision path absorbs it fail-open and
        it stays visible in ``health()``.
        """

        with self._lifecycle_lock:
            if self._opened:
                return
            try:
                parent = self.database_path.parent
                if not parent.is_dir():
                    raise StorageError(
                        f"evidence directory {str(parent)!r} does not exist. "
                        f"Create it (and set ATLAS_EVIDENCE_DIRECTORY if it "
                        f"is not the installation default) before starting "
                        f"Atlas; it is deliberately not created here."
                    )
                connection = sqlite3.connect(
                    self.database_path,
                    timeout=self.busy_timeout_ms / 1000,
                    isolation_level=None,
                )
                try:
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.execute("PRAGMA foreign_keys = ON")
                    connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
                    self._schema_version = apply_migrations(
                        connection,
                        EVIDENCE_MIGRATIONS,
                    )
                finally:
                    connection.close()
            except StorageError as exc:
                # Already a precise, actionable storage failure (such as a
                # missing evidence directory); do not bury it inside a
                # second, vaguer one.
                self._last_error = f"{type(exc).__name__}: {exc}"
                raise
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                raise StorageError(
                    f"evidence store could not be opened at {self.database_path}: {exc}"
                ) from exc
            self._opened = True
            self._last_error = None
            logger.info(
                "Evidence store opened at %s (schema_version=%s)",
                self.database_path,
                self._schema_version,
            )

    def close(self) -> None:
        with self._lifecycle_lock:
            self._opened = False

    @property
    def opened(self) -> bool:
        return self._opened

    def _connect(self) -> sqlite3.Connection:
        if not self._opened:
            raise StorageError("evidence store is not open")
        connection = sqlite3.connect(
            self.database_path,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    # -------------------------------------------------------------
    # WRITE
    # -------------------------------------------------------------

    def record_claim(
        self,
        *,
        claim_text: str,
        claim_kind: str,
        subject_scope: str,
        subject_symbol: str | None,
        agent_id: str,
        agent_version: str,
        confidence: Decimal | str,
        asserted_at: datetime,
        sources: Sequence[ClaimSource],
        payload: Mapping[str, Any],
        run_id: str,
        observation_start: datetime | None = None,
        observation_end: datetime | None = None,
        reason_codes: Sequence[str] = (),
        model_provider: str | None = None,
        model_name: str | None = None,
    ) -> str:
        """Persist one claim with its sources; return its claim_id.

        Idempotent. The claim_id is derived from the same tuple that
        ``idx_claims_idem`` is unique over, so a repeated write collides in
        the database rather than being filtered by an application-level
        pre-check that a concurrent writer could race past. On collision
        the existing row's id is returned and nothing is written.
        """

        claim_text = _required_text(claim_text, "claim_text")
        agent_id = _required_text(agent_id, "agent_id")
        agent_version = _required_text(agent_version, "agent_version")
        run_id = _required_text(run_id, "run_id")
        kind = _enum_value(claim_kind, ClaimKind, "claim_kind")
        scope = _enum_value(subject_scope, SubjectScope, "subject_scope")

        if scope == SubjectScope.SYMBOL.value and not (
            isinstance(subject_symbol, str) and subject_symbol.strip()
        ):
            raise IntegrityViolation("subject_symbol is required when scope is SYMBOL")
        if bool(model_provider) != bool(model_name):
            raise IntegrityViolation(
                "model_provider and model_name must be supplied together"
            )
        if not isinstance(payload, Mapping):
            raise IntegrityViolation("payload must be a mapping")
        if not sources:
            raise IntegrityViolation("at least one source is required")

        confidence_value = _confidence_text(confidence)
        asserted_text = _utc_text(asserted_at, "asserted_at")
        start_text = _optional_utc_text(observation_start, "observation_start")
        end_text = _optional_utc_text(observation_end, "observation_end")
        payload_text = _canonical_json(dict(payload))
        payload_digest = _digest(payload_text)
        reason_text = _canonical_json([str(code) for code in reason_codes])

        claim_id = _digest(
            _canonical_json(
                [agent_id, subject_symbol, kind, payload_digest, asserted_text]
            )
        )

        source_rows = []
        for ordinal, source in enumerate(sources):
            if not isinstance(source, ClaimSource):
                raise IntegrityViolation("sources must be ClaimSource instances")
            source_rows.append(
                (
                    claim_id,
                    ordinal,
                    _enum_value(source.source_kind, SourceKind, "source_kind"),
                    _required_text(source.source_uri, "source_uri"),
                    _required_text(source.source_version, "source_version"),
                    _utc_text(source.retrieved_at, "retrieved_at"),
                    source.source_digest,
                )
            )

        created_text = _utc_text(datetime.now(UTC), "created_at")

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO claims (
                        claim_id, schema_version, claim_text, claim_kind,
                        subject_scope, subject_symbol, agent_id, agent_version,
                        model_provider, model_name, confidence_text,
                        asserted_at_utc, observation_start_utc, observation_end_utc,
                        payload_json, payload_digest, reason_codes_json, run_id,
                        created_at_utc
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        claim_id,
                        CLAIM_SCHEMA_VERSION,
                        claim_text,
                        kind,
                        scope,
                        subject_symbol,
                        agent_id,
                        agent_version,
                        model_provider,
                        model_name,
                        confidence_value,
                        asserted_text,
                        start_text,
                        end_text,
                        payload_text,
                        payload_digest,
                        reason_text,
                        run_id,
                        created_text,
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO claim_sources (
                        claim_id, source_ordinal, source_kind, source_uri,
                        source_version, retrieved_at_utc, source_digest
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    source_rows,
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                connection.execute("ROLLBACK")
                existing = connection.execute(
                    """
                    SELECT claim_id FROM claims
                    WHERE agent_id = ? AND claim_kind = ? AND payload_digest = ?
                      AND asserted_at_utc = ?
                      AND subject_symbol IS ?
                    """,
                    (agent_id, kind, payload_digest, asserted_text, subject_symbol),
                ).fetchone()
                if existing is None:
                    self._write_failures += 1
                    self._last_error = f"IntegrityError: {exc}"
                    raise IntegrityViolation(
                        f"claim rejected by a storage invariant: {exc}"
                    ) from exc
                self._claims_deduplicated += 1
                return existing["claim_id"]
            except Exception:
                connection.execute("ROLLBACK")
                raise
        except (IntegrityViolation, StorageError):
            raise
        except Exception as exc:
            self._write_failures += 1
            self._last_error = f"{type(exc).__name__}: {exc}"
            raise StorageError(f"recording claim failed: {exc}") from exc
        finally:
            connection.close()

        self._claims_written += 1
        return claim_id

    def link(
        self,
        *,
        from_claim_id: str,
        to_claim_id: str,
        relation_kind: str,
        created_by: str,
        weight: Decimal | str | None = None,
        created_at: datetime | None = None,
    ) -> str:
        """Create a relation edge; return the (forward) relation_id.

        A symmetric kind (CONTRADICTS) writes both directions inside one
        transaction, so the pair can never half-exist and every read stays
        a single index seek. Re-linking an existing edge is idempotent.
        """

        from_claim_id = _required_text(from_claim_id, "from_claim_id")
        to_claim_id = _required_text(to_claim_id, "to_claim_id")
        created_by = _required_text(created_by, "created_by")
        kind_value = _enum_value(relation_kind, RelationKind, "relation_kind")
        kind = RelationKind(kind_value)

        if from_claim_id == to_claim_id:
            raise IntegrityViolation("a claim cannot relate to itself")

        weight_text = _optional_weight_text(weight)
        created_text = _utc_text(created_at or datetime.now(UTC), "created_at")

        pairs = [(from_claim_id, to_claim_id)]
        if kind in SYMMETRIC_RELATIONS:
            pairs.append((to_claim_id, from_claim_id))

        rows = [
            (
                _digest(_canonical_json([source, target, kind_value])),
                source,
                target,
                kind_value,
                weight_text,
                created_by,
                created_text,
            )
            for source, target in pairs
        ]

        inserted = 0
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                before = connection.total_changes
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO claim_relations (
                        relation_id, from_claim_id, to_claim_id, relation_kind,
                        weight_text, created_by, created_at_utc
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    rows,
                )
                # INSERT OR IGNORE makes re-linking idempotent, so the rows
                # actually written are counted rather than the rows offered.
                # health() is the only visibility a fail-open caller has; a
                # counter that overcounts duplicates would undermine it.
                inserted = connection.total_changes - before
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                connection.execute("ROLLBACK")
                self._write_failures += 1
                self._last_error = f"IntegrityError: {exc}"
                raise IntegrityViolation(f"relation rejected: {exc}") from exc
            except Exception:
                connection.execute("ROLLBACK")
                raise
        except (IntegrityViolation, StorageError):
            raise
        except Exception as exc:
            self._write_failures += 1
            self._last_error = f"{type(exc).__name__}: {exc}"
            raise StorageError(f"linking claims failed: {exc}") from exc
        finally:
            connection.close()

        self._relations_written += inserted
        return rows[0][0]

    def set_status(
        self,
        claim_id: str,
        status: str,
        *,
        reason: str,
        decided_by: str,
        decided_at: datetime | None = None,
    ) -> int:
        """Append a lifecycle transition; return its sequence number.

        Append-only by construction: no UPDATE is ever issued against
        ``claims`` or against an earlier history row. System-only in this
        increment (OQ-5) - no agent-facing call site is wired.
        """

        claim_id = _required_text(claim_id, "claim_id")
        reason = _required_text(reason, "reason")
        decided_by = _required_text(decided_by, "decided_by")
        status_value = _enum_value(status, ClaimStatus, "status")
        decided_text = _utc_text(decided_at or datetime.now(UTC), "decided_at")

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                exists = connection.execute(
                    "SELECT 1 FROM claims WHERE claim_id = ?",
                    (claim_id,),
                ).fetchone()
                if exists is None:
                    connection.execute("ROLLBACK")
                    raise IntegrityViolation(f"unknown claim_id {claim_id!r}")
                row = connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) AS newest "
                    "FROM claim_status_history WHERE claim_id = ?",
                    (claim_id,),
                ).fetchone()
                sequence = int(row["newest"]) + 1
                connection.execute(
                    """
                    INSERT INTO claim_status_history (
                        claim_id, sequence, status, reason, decided_by, decided_at_utc
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    (claim_id, sequence, status_value, reason, decided_by, decided_text),
                )
                connection.execute("COMMIT")
            except IntegrityViolation:
                raise
            except Exception:
                connection.execute("ROLLBACK")
                raise
        except (IntegrityViolation, StorageError):
            raise
        except Exception as exc:
            self._write_failures += 1
            self._last_error = f"{type(exc).__name__}: {exc}"
            raise StorageError(f"status transition failed: {exc}") from exc
        finally:
            connection.close()

        return sequence

    # -------------------------------------------------------------
    # READ
    # -------------------------------------------------------------

    def get(self, claim_id: str) -> ClaimRecord | None:
        connection = self._connect()
        try:
            row = connection.execute(
                f"SELECT {_CLAIM_COLUMNS}, {_STATUS_SELECT} "
                f"FROM claims c WHERE c.claim_id = ?",
                (claim_id,),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else _claim_from_row(row)

    def sources_for(self, claim_id: str) -> list[ClaimSource]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT source_kind, source_uri, source_version, retrieved_at_utc, "
                "source_digest FROM claim_sources WHERE claim_id = ? "
                "ORDER BY source_ordinal",
                (claim_id,),
            ).fetchall()
        finally:
            connection.close()
        return [
            ClaimSource(
                source_kind=row["source_kind"],
                source_uri=row["source_uri"],
                source_version=row["source_version"],
                retrieved_at=datetime.fromisoformat(
                    row["retrieved_at_utc"].replace("Z", "+00:00")
                ),
                source_digest=row["source_digest"],
            )
            for row in rows
        ]

    def query(
        self,
        *,
        symbol: str | None = None,
        agent_id: str | None = None,
        claim_kind: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        statuses: Sequence[str] | None = None,
        min_confidence: Decimal | str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[ClaimRecord]:
        clauses: list[str] = []
        params: list[Any] = []

        if symbol is not None:
            clauses.append("c.subject_symbol = ?")
            params.append(symbol)
        if agent_id is not None:
            clauses.append("c.agent_id = ?")
            params.append(agent_id)
        if claim_kind is not None:
            clauses.append("c.claim_kind = ?")
            params.append(_enum_value(claim_kind, ClaimKind, "claim_kind"))
        if since is not None:
            clauses.append("c.asserted_at_utc >= ?")
            params.append(_utc_text(since, "since"))
        if until is not None:
            clauses.append("c.asserted_at_utc <= ?")
            params.append(_utc_text(until, "until"))
        if min_confidence is not None:
            clauses.append("CAST(c.confidence_text AS REAL) >= ?")
            params.append(float(_confidence_text(min_confidence, "min_confidence")))
        if statuses:
            allowed = [_enum_value(s, ClaimStatus, "status") for s in statuses]
            placeholders = ",".join("?" for _ in allowed)
            clauses.append(f"{_STATUS_EXPR} IN ({placeholders})")
            params.extend(allowed)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([max(0, int(limit)), max(0, int(offset))])

        connection = self._connect()
        try:
            rows = connection.execute(
                f"SELECT {_CLAIM_COLUMNS}, {_STATUS_SELECT} "
                f"FROM claims c {where} "
                f"ORDER BY c.asserted_at_utc DESC, c.claim_id LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        finally:
            connection.close()
        return [_claim_from_row(row) for row in rows]

    def _related(
        self,
        claim_id: str,
        relation_kind: RelationKind,
        *,
        include_inactive: bool,
        incoming: bool = True,
        limit: int | None = None,
    ) -> list[ClaimRecord]:
        """Traverse one relation kind via the (to|from)/kind composite index."""

        anchor = "r.to_claim_id" if incoming else "r.from_claim_id"
        other = "r.from_claim_id" if incoming else "r.to_claim_id"
        params: list[Any] = [claim_id, relation_kind.value]

        status_filter = ""
        if not include_inactive:
            placeholders = ",".join("?" for _ in INACTIVE_STATUSES)
            status_filter = f"AND {_STATUS_EXPR} NOT IN ({placeholders})"
            params.extend(INACTIVE_STATUSES)

        limit_clause = ""
        if limit is not None:
            limit_clause = "LIMIT ?"
            params.append(int(limit))

        connection = self._connect()
        try:
            rows = connection.execute(
                f"SELECT {_CLAIM_COLUMNS}, {_STATUS_SELECT} "
                f"FROM claim_relations r "
                f"JOIN claims c ON c.claim_id = {other} "
                f"WHERE {anchor} = ? AND r.relation_kind = ? {status_filter} "
                f"ORDER BY CAST(c.confidence_text AS REAL) DESC, c.claim_id "
                f"{limit_clause}",
                params,
            ).fetchall()
        finally:
            connection.close()
        return [_claim_from_row(row) for row in rows]

    def counter_evidence(
        self,
        claim_id: str,
        *,
        include_inactive: bool = False,
    ) -> list[ClaimRecord]:
        """Every active claim that argues against ``claim_id``."""

        return self._related(
            claim_id,
            RelationKind.CONTRADICTS,
            include_inactive=include_inactive,
        )

    def supporting_evidence(
        self,
        claim_id: str,
        *,
        include_inactive: bool = False,
    ) -> list[ClaimRecord]:
        return self._related(
            claim_id,
            RelationKind.SUPPORTS,
            include_inactive=include_inactive,
        )

    def precedents(
        self,
        claim_id: str,
        *,
        include_inactive: bool = False,
        limit: int = 20,
    ) -> list[ClaimRecord]:
        """Past claims recorded as precedent for ``claim_id``.

        Precedent is an edge, not a column (OQ-6): what *happened* in those
        past situations is an outcome, and outcomes belong to the
        Hypothesis Registry rather than to this store.
        """

        return self._related(
            claim_id,
            RelationKind.PRECEDENT_OF,
            include_inactive=include_inactive,
            limit=limit,
        )

    # -------------------------------------------------------------
    # DIAGNOSTICS
    # -------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Report store state without raising, even when unusable.

        The decision-path caller is fail-open, so a broken store is
        invisible there by design; this is where that failure becomes
        visible instead.
        """

        report: dict[str, Any] = {
            "database_path": str(self.database_path),
            "opened": self._opened,
            "schema_version": self._schema_version,
            "claim_schema_version": CLAIM_SCHEMA_VERSION,
            "claims_written": self._claims_written,
            "claims_deduplicated": self._claims_deduplicated,
            "relations_written": self._relations_written,
            "write_failures": self._write_failures,
            "last_error": self._last_error,
            "claim_count": None,
            "relation_count": None,
        }
        if not self._opened:
            return report
        try:
            connection = self._connect()
            try:
                report["claim_count"] = connection.execute(
                    "SELECT COUNT(*) FROM claims"
                ).fetchone()[0]
                report["relation_count"] = connection.execute(
                    "SELECT COUNT(*) FROM claim_relations"
                ).fetchone()[0]
            finally:
                connection.close()
        except Exception as exc:
            report["last_error"] = f"{type(exc).__name__}: {exc}"
        return report

    def record_write_failure(self, error: BaseException) -> None:
        """Let a fail-open caller register a failure it swallowed.

        Without this the decision-path hook's exception would be logged and
        then vanish from the store's own diagnostics, which is exactly the
        silence fail-open must not buy.
        """

        self._write_failures += 1
        self._last_error = f"{type(error).__name__}: {error}"
