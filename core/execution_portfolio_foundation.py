"""Canonical Phase-4 LONG-only execution/position/portfolio foundation.

External execution determination remains owned by the transaction journal and
reconciliation.  This module consumes confirmed evidence; it never retries an
exchange operation and never claims filesystem atomicity is exchange atomicity.

Block 5I moved ``closed_positions`` and ``applied_executions`` out of the
working snapshot (``execution_financial_state.json``, now schema_version 2)
into two immutable, append-only JSON-Lines sidecars -
``AppliedExecutionArchiveStore`` and ``ClosedPositionArchiveStore``. The
working file now tracks only current operational state plus two small
checkpoints (``applied_checkpoint`` / ``closed_checkpoint``) pointing at the
exact sidecar tail it last durably wrote. This bounds the working file's size
by *live* state rather than by lifetime execution/close count; the sidecars
themselves are O(1) appends, and rebuilding their in-memory indexes at
startup is O(history) once, not on every mutation. There is no runtime
auto-migration from schema_version 1 - see ``FinancialStateMigrationRequiredError``
and ``tools/migrate_execution_financial_state.py``.

Task 025 (registry v5.108) adds schema_version 3, the margin book, for forex PAPER state only: the working file
carries the account ``leverage`` L (2..5) and every position its ``margin`` (notional / L). A BUY debits margin + fee
instead of notional + fee; a reduction credits the released margin plus the realized gross P&L minus the fee, so
a realized loss larger than the account can leave the cash negative (recorded, never hidden; new risk is then
refused). Equity is cash + used margin + unrealized P&L. Schema 2 (every crypto book) is unchanged and is never
migrated: a schema 2 book loaded where leverage is expected, or a schema 3 book where it is not, is refused
(FINANCIAL_LEVERAGE_CONFLICT).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

from core.execution_models import ExecutionResult

D = Decimal
SCHEMA_VERSION = 2
MARGIN_SCHEMA_VERSION = 3   # Task 025: the margin book (forex PAPER state only)
MAX_LEVERAGE = 5


def book_leverage(state: dict[str, Any]) -> int:
    """The account leverage a working state carries: 1 for schema 2, the stored L for schema 3."""
    if state.get("schema_version") == MARGIN_SCHEMA_VERSION:
        value = state.get("leverage")
        if isinstance(value, bool) or not isinstance(value, int) or not 2 <= value <= MAX_LEVERAGE:
            raise ValueError("CORRUPT_FINANCIAL_STATE")
        return value
    return 1

# Block 5E: the fixed precision the whole confirmed-execution settlement
# slice - BUY debit/fee accumulation, SELL gross P&L/cash/fee accumulation,
# the partial-close cost/entry-fee pro-rata split, and both sides'
# average-entry-price division - is computed under, explicit and pinned
# rather than whatever precision happens to be ambient in the caller's
# thread (F5's settlement slice; widened to `_open` and to the whole of
# `_close` at final review, MEDIUM #2). ``ExecutionManager`` reuses this
# same constant for the settled-amount sums it computes around this
# foundation, so the whole slice shares one precision. 50 significant
# digits is generous headroom above the Decimal module's 28-digit default
# for any realistic cost/fee/quantity magnitude this book holds.
SETTLEMENT_CONTEXT_PRECISION = 50


def _decimal(value: Any, name: str, *, allow_zero: bool = True) -> Decimal:
    if isinstance(value, float):
        raise ValueError(f"{name} must not be float")
    try:
        result = D(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
        raise ValueError(f"invalid {name}")
    return result


def _utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC).isoformat()


# Block 5G: the canonical position-identity contract, identical to
# ``data_layer.models``' generic `_ID` pattern (the repository's one formal
# identity-format contract) - first character alphanumeric, every following
# character alphanumeric or one of "._:-", 1-128 characters total. Kept
# local rather than imported to avoid an L1-to-L1 import across domains;
# ExecutionManager mints against ``mint_long_position_id`` below rather than
# duplicating the pattern, the same precedent set by its reuse of
# ``SETTLEMENT_CONTEXT_PRECISION``.
_POSITION_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def mint_long_position_id(symbol: str, request_id: str) -> str:
    """Deterministically mint a flat-book LONG position lifetime identity.

    ``long:<symbol>:<sha256(request_id).hexdigest()>`` is reproducible from
    the opening request alone - never random - so a later re-derivation
    from the same confirmed evidence always agrees: recomputing the digest
    of the same ``request_id`` always yields the same identity.

    The digest is hashed, not embedded raw (Block 5G final hardening): an
    earlier version of this function embedded ``request_id`` directly and
    had to widen the identity charset to accommodate MarketLoop's real
    ``f"{symbol}|{candle_identity}|{action}"`` request_id convention
    (core/market_loop.py). Hashing removes that coupling entirely - a
    fixed-length, fixed-charset SHA-256 hex digest satisfies
    ``data_layer.models``' canonical `_ID` contract and stays comfortably
    inside its 128-character bound regardless of what characters or how
    much text ``request_id`` itself contains, with no special-casing for
    any particular caller's request_id shape. ``request_id`` keeps its own
    existing, unrelated validation (``ExecutionManager`` requires only
    non-blank); this function owns solely the safe, deterministic
    projection of it into a durable position identity, never a truncation
    or sanitization of the raw value into that identity.
    """
    digest = hashlib.sha256(str(request_id).encode("utf-8")).hexdigest()
    candidate = f"long:{symbol}:{digest}"
    if not _POSITION_IDENTITY_PATTERN.fullmatch(candidate):
        raise ValueError("INVALID_POSITION_IDENTITY")
    return candidate


@dataclass(frozen=True, slots=True)
class LongPosition:
    position_id: str
    symbol: str
    base_quantity: Decimal
    cost_quote: Decimal
    entry_fees: Decimal
    average_entry_price: Decimal
    mark_price: Decimal
    version: int
    opened_at: str

    def to_dict(self) -> dict[str, Any]:
        return {name: (format(value, "f") if isinstance(value, D) else value)
                for name, value in asdict(self).items()}


class FinancialStateMigrationRequiredError(ValueError):
    """Raised when execution_financial_state.json is still schema_version 1.

    Block 5I moved ``closed_positions`` and ``applied_executions`` out of the
    working snapshot into the two immutable sidecars below. A v1 file is
    real, valuable accounting history; silently reinterpreting it under the
    v2 contract (where those two collections are expected to live in the
    sidecars, not the working file) would risk misplacing or losing it.
    Runtime never auto-migrates - ``tools/migrate_execution_financial_state.py``
    is the only supported path from v1 to v2 + sidecars.
    """


class FinancialStateStore:
    """Atomic JSON state store; missing/corrupt state is never healthy-empty."""
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def initialize(self, initial_cash: Decimal, *, leverage: int = 1) -> None:
        if isinstance(leverage, bool) or not isinstance(leverage, int) or not 1 <= leverage <= MAX_LEVERAGE:
            raise ValueError("leverage must be an integer from 1 to 5")
        if self.path.exists():
            raise FileExistsError(self.path)
        payload = {
            "schema_version": SCHEMA_VERSION, "transition": None,
            "cash": format(initial_cash, "f"), "reserved_capital": "0",
            "realized_gross_pnl": "0", "fees": "0", "positions": {},
            "applied_checkpoint": None, "closed_checkpoint": None,
        }
        if leverage > 1:   # Task 025: the margin book; leverage 1 stays schema 2, byte-identical
            payload.update(schema_version=MARGIN_SCHEMA_VERSION, leverage=leverage)
        self.save(payload)

    def load(self, *, allow_transition: bool = False) -> dict[str, Any]:
        """Load the working state; a pending transition marker refuses by default.

        ``allow_transition`` exists for operator recovery only
        (``inspect_interrupted_transition``), which must read the marker it
        is resolving. The runtime never passes it.
        """
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("FINANCIAL_STATE_RECOVERY_REQUIRED") from exc
        schema = payload.get("schema_version")
        if schema == 1:
            raise FinancialStateMigrationRequiredError("FINANCIAL_MIGRATION_REQUIRED")
        if schema not in (SCHEMA_VERSION, MARGIN_SCHEMA_VERSION):
            raise RuntimeError("FINANCIAL_STATE_RECOVERY_REQUIRED")
        if payload.get("transition") is not None and not allow_transition:
            raise RuntimeError("FINANCIAL_TRANSITION_RECOVERY_REQUIRED")
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, self.path)


# ---------------------------------------------------------------------------
# Block 5I - applied-execution authority (immutable, append-only)
# ---------------------------------------------------------------------------


class AppliedExecutionArchiveError(RuntimeError):
    """Base class for immutable applied-execution authority failures."""


class AppliedExecutionArchiveCorruptError(AppliedExecutionArchiveError):
    """A line in the applied-execution archive is malformed, torn, or its
    sequence is not the deterministic append order this store requires."""


class AppliedExecutionArchiveConflictError(AppliedExecutionArchiveError):
    """Two archive lines disagree about execution_id/idempotency_key identity."""


@dataclass(frozen=True, slots=True)
class AppliedExecutionRecord:
    sequence: int
    execution_id: str
    idempotency_key: str
    applied_at: str

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if not self.execution_id or not self.idempotency_key:
            raise ValueError("execution_id and idempotency_key are required")
        _utc(self.applied_at)

    def to_dict(self) -> dict[str, Any]:
        return {"sequence": self.sequence, "execution_id": self.execution_id,
                "idempotency_key": self.idempotency_key, "applied_at": self.applied_at}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AppliedExecutionRecord":
        return cls(int(value["sequence"]), str(value["execution_id"]),
                   str(value["idempotency_key"]), str(value["applied_at"]))


@dataclass(frozen=True, slots=True)
class AppliedExecutionIndex:
    by_execution_id: dict[str, AppliedExecutionRecord]
    by_idempotency_key: dict[str, AppliedExecutionRecord]
    tail: AppliedExecutionRecord | None
    count: int


class AppliedExecutionArchiveStore:
    """Immutable, append-only JSON-Lines authority of every applied execution.

    One canonical record per line - ``sequence``, ``execution_id``,
    ``idempotency_key``, ``applied_at`` - written durably (write -> flush ->
    fsync) before the call returns, mirroring ``ReservationArchiveStore``
    (Block 5H) / ``AuditEventStore``'s existing jsonl pattern. ``append`` is
    the only write operation this store performs: no line is ever rewritten,
    reordered, or deleted, and there is no retention or pruning.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, record: AppliedExecutionRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def load_index(self) -> AppliedExecutionIndex:
        """Rebuild the O(1) execution_id / idempotency_key indexes.

        O(history) once, at construction - see the module docstring's
        asymptotic note. Consecutive byte-identical duplicate lines are
        tolerated idempotently, as defensive equality logic against a torn
        write duplicating a line at the storage layer; any other repetition
        of a sequence, execution_id, or idempotency_key is corruption and
        fails closed rather than being silently resolved by picking a side.
        This tolerance is not known to be reachable via any live
        ``apply_confirmed``-driven path: ``applied_at`` is stamped fresh on
        every append, so two genuine retries of the same logical execution
        never produce byte-identical records, and same-process replay of an
        already-durable ``execution_id`` short-circuits in
        ``apply_confirmed`` before a second append is ever attempted.
        """
        if not self.path.exists():
            return AppliedExecutionIndex({}, {}, None, 0)
        by_execution_id: dict[str, AppliedExecutionRecord] = {}
        by_idempotency_key: dict[str, AppliedExecutionRecord] = {}
        tail: AppliedExecutionRecord | None = None
        expected_next = 0
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        raise ValueError("archive line is not an object")
                    record = AppliedExecutionRecord.from_dict(payload)
                except Exception as exc:
                    raise AppliedExecutionArchiveCorruptError(
                        f"FINANCIAL_APPLIED_AUTHORITY_CORRUPT: line {line_number}"
                    ) from exc
                if record.sequence == expected_next:
                    if record.execution_id in by_execution_id:
                        raise AppliedExecutionArchiveConflictError(
                            f"APPLIED_EXECUTION_CONFLICT: execution_id={record.execution_id!r}"
                        )
                    if record.idempotency_key in by_idempotency_key:
                        raise AppliedExecutionArchiveConflictError(
                            f"IDEMPOTENCY_IDENTITY_CONFLICT: idempotency_key={record.idempotency_key!r}"
                        )
                    by_execution_id[record.execution_id] = record
                    by_idempotency_key[record.idempotency_key] = record
                    tail = record
                    expected_next += 1
                elif record.sequence == expected_next - 1 and tail == record:
                    continue  # tolerated retry of the immediately preceding append
                else:
                    raise AppliedExecutionArchiveCorruptError(
                        f"FINANCIAL_APPLIED_AUTHORITY_CORRUPT: non-deterministic "
                        f"sequence at line {line_number}"
                    )
        return AppliedExecutionIndex(by_execution_id, by_idempotency_key, tail, len(by_execution_id))


# ---------------------------------------------------------------------------
# Block 5I - closed-position archive (immutable, append-only)
# ---------------------------------------------------------------------------


class ClosedPositionArchiveError(RuntimeError):
    """Base class for immutable closed-position archive failures."""


class ClosedPositionArchiveCorruptError(ClosedPositionArchiveError):
    """A line in the closed-position archive is malformed, torn, shape-invalid,
    or its sequence is not the deterministic append order this store requires."""


class ClosedPositionArchiveConflictError(ClosedPositionArchiveError):
    """Two archive lines disagree about the same position_id."""


# Every field the current `_close` full-exit semantics actually produce
# (see `_close` below) - never a subset of the old `closed_positions`
# working-map check, and never a new economic field this module does not
# already compute.
_CLOSED_POSITION_REQUIRED_FIELDS = (
    "position_id", "symbol", "base_quantity", "cost_quote", "entry_fees",
    "average_entry_price", "mark_price", "version", "opened_at",
    "status", "exit_price", "gross_pnl", "closed_at",
)
_CLOSED_POSITION_POSITIVE_DECIMAL_FIELDS = (
    "cost_quote", "average_entry_price", "mark_price", "exit_price",
)


def validate_closed_position_record(record: dict[str, Any]) -> None:
    """Validate a closed-position archive record's shape strongly.

    Stronger than the pre-5I ``closed_positions`` working-map check (which
    validated only ``position_id`` identity and pattern): every field
    ``_close`` actually produces for a full exit is checked for presence and
    type/range correctness.
    """
    # Task 025: a margin-book (schema 3) full exit also carries the position's ``margin``.
    if not isinstance(record, dict) or set(record) - {"margin"} != set(_CLOSED_POSITION_REQUIRED_FIELDS):
        raise ValueError("CORRUPT_CLOSED_POSITION_RECORD")
    position_id = record["position_id"]
    if not isinstance(position_id, str) or not _POSITION_IDENTITY_PATTERN.fullmatch(position_id):
        raise ValueError("CORRUPT_CLOSED_POSITION_RECORD")
    if not isinstance(record["symbol"], str) or not record["symbol"]:
        raise ValueError("CORRUPT_CLOSED_POSITION_RECORD")
    if record["status"] != "CLOSED":
        raise ValueError("CORRUPT_CLOSED_POSITION_RECORD")
    try:
        if _decimal(record["base_quantity"], "base_quantity") != 0:
            raise ValueError("CORRUPT_CLOSED_POSITION_RECORD")
        for name in _CLOSED_POSITION_POSITIVE_DECIMAL_FIELDS:
            _decimal(record[name], name, allow_zero=False)
        _decimal(record["entry_fees"], "entry_fees", allow_zero=True)
        if "margin" in record:
            _decimal(record["margin"], "margin", allow_zero=False)
        gross_pnl = D(str(record["gross_pnl"]))
        if not gross_pnl.is_finite():
            raise ValueError("CORRUPT_CLOSED_POSITION_RECORD")
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("CORRUPT_CLOSED_POSITION_RECORD") from exc
    if (not isinstance(record["version"], int) or isinstance(record["version"], bool)
            or record["version"] < 1):
        raise ValueError("CORRUPT_CLOSED_POSITION_RECORD")
    for name in ("opened_at", "closed_at"):
        try:
            _utc(record[name])
        except Exception as exc:
            raise ValueError("CORRUPT_CLOSED_POSITION_RECORD") from exc


@dataclass(frozen=True, slots=True)
class ClosedPositionIndex:
    by_position_id: dict[str, dict[str, Any]]
    sequence_by_position_id: dict[str, int]
    tail_sequence: int | None
    tail_position_id: str | None
    count: int


class ClosedPositionArchiveStore:
    """Immutable, append-only JSON-Lines archive of fully-closed positions.

    One canonical closed-position record per line - exactly what ``_close``
    produces for a full exit, keyed by Block 5G's deterministic
    ``position_id`` - plus the deterministic ``sequence`` this package's
    checkpoint contract needs. Durable (write -> flush -> fsync) before the
    call returns; ``append`` is the only write operation, no retention or
    pruning, mirroring ``AppliedExecutionArchiveStore`` / ``ReservationArchiveStore``.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, sequence: int, record: dict[str, Any]) -> None:
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ValueError("sequence must be a non-negative int")
        validate_closed_position_record(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"sequence": sequence, **record}
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def load_index(self) -> ClosedPositionIndex:
        """Rebuild the O(1) position_id index. O(history) once, at construction."""
        if not self.path.exists():
            return ClosedPositionIndex({}, {}, None, None, 0)
        by_position_id: dict[str, dict[str, Any]] = {}
        sequence_by_position_id: dict[str, int] = {}
        tail_sequence: int | None = None
        tail_position_id: str | None = None
        expected_next = 0
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    if not isinstance(payload, dict) or "sequence" not in payload:
                        raise ValueError("archive line is not a sequenced object")
                    sequence = payload["sequence"]
                    if not isinstance(sequence, int) or isinstance(sequence, bool):
                        raise ValueError("sequence must be an int")
                    record = {key: value for key, value in payload.items() if key != "sequence"}
                    validate_closed_position_record(record)
                except Exception as exc:
                    raise ClosedPositionArchiveCorruptError(
                        f"FINANCIAL_CLOSED_AUTHORITY_CORRUPT: line {line_number}"
                    ) from exc
                position_id = record["position_id"]
                if sequence == expected_next:
                    if position_id in by_position_id:
                        raise ClosedPositionArchiveConflictError(
                            f"CLOSED_POSITION_ARCHIVE_CONFLICT: position_id={position_id!r}"
                        )
                    by_position_id[position_id] = record
                    sequence_by_position_id[position_id] = sequence
                    tail_sequence, tail_position_id = sequence, position_id
                    expected_next += 1
                elif (sequence == expected_next - 1 and tail_position_id == position_id
                        and by_position_id.get(position_id) == record):
                    continue  # tolerated retry of the immediately preceding append
                else:
                    raise ClosedPositionArchiveCorruptError(
                        f"FINANCIAL_CLOSED_AUTHORITY_CORRUPT: non-deterministic "
                        f"sequence at line {line_number}"
                    )
        return ClosedPositionIndex(
            by_position_id, sequence_by_position_id, tail_sequence, tail_position_id, len(by_position_id)
        )


class ExecutionPortfolioFoundation:
    """Idempotent durable LONG lifecycle and portfolio accounting.

    ``leverage`` is the account leverage the caller expects the book to carry (1: a schema 2 cash book; 2..5: a
    schema 3 margin book). A book that disagrees is not ready (FINANCIAL_LEVERAGE_CONFLICT). ``None`` accepts the
    book's own value and is for operator recovery only; the runtime always passes its pinned value.
    """
    def __init__(self, store: FinancialStateStore, *,
                 applied_archive: AppliedExecutionArchiveStore,
                 closed_archive: ClosedPositionArchiveStore,
                 leverage: int | None = 1):
        self.store = store
        self.applied_archive = applied_archive
        self.closed_archive = closed_archive
        self.expected_leverage = leverage   # read by core.policy_manifest (manifest v4 book_leverage)
        self._recovery_reason: str | None = None
        self._applied_by_execution_id: dict[str, AppliedExecutionRecord] = {}
        self._applied_by_idempotency_key: dict[str, AppliedExecutionRecord] = {}
        self._applied_tail: AppliedExecutionRecord | None = None
        self._closed_by_position_id: dict[str, dict[str, Any]] = {}
        self._closed_tail_sequence: int | None = None
        try:
            self._state = store.load()
            self._validate_state(self._state)
            if leverage is not None and book_leverage(self._state) != leverage:
                raise RuntimeError("FINANCIAL_LEVERAGE_CONFLICT")
            self._hydrate_sidecars()
        except Exception as exc:
            self._state = {}
            self._recovery_reason = str(exc) or "FINANCIAL_STATE_RECOVERY_REQUIRED"

    def _hydrate_sidecars(self) -> None:
        """Cross-check each checkpoint against its sidecar's durable tail.

        Both checkpoints are validated the same way: a ``None`` checkpoint
        requires an empty (missing or zero-record) sidecar - a freshly
        bootstrapped book - and a non-``None`` checkpoint requires the
        sidecar's exact tail record to match it field-for-field. Any
        disagreement - a corrupt/conflicting sidecar, a missing sidecar the
        checkpoint proves must exist, or an orphan record the sidecar holds
        beyond what the checkpoint confirms was ever durably committed -
        fails closed. This is what protects against a sidecar append
        surviving a crash while the working-state commit that would confirm
        it never landed, and an operator later clearing the transition
        marker without reconciling the checkpoint to match.
        """
        applied_index = self.applied_archive.load_index()
        applied_checkpoint = self._state["applied_checkpoint"]
        if applied_checkpoint is None:
            if applied_index.count != 0:
                raise RuntimeError("FINANCIAL_APPLIED_AUTHORITY_DIVERGENT")
        else:
            tail = applied_index.tail
            if (tail is None or tail.sequence != applied_checkpoint["sequence"]
                    or tail.execution_id != applied_checkpoint["execution_id"]
                    or tail.idempotency_key != applied_checkpoint["idempotency_key"]):
                raise RuntimeError(
                    "FINANCIAL_APPLIED_AUTHORITY_MISSING" if applied_index.count == 0
                    else "FINANCIAL_APPLIED_AUTHORITY_DIVERGENT"
                )

        closed_index = self.closed_archive.load_index()
        closed_checkpoint = self._state["closed_checkpoint"]
        if closed_checkpoint is None:
            if closed_index.count != 0:
                raise RuntimeError("FINANCIAL_CLOSED_AUTHORITY_DIVERGENT")
        else:
            if (closed_index.tail_sequence != closed_checkpoint["sequence"]
                    or closed_index.tail_position_id != closed_checkpoint["position_id"]):
                raise RuntimeError(
                    "FINANCIAL_CLOSED_AUTHORITY_MISSING" if closed_index.count == 0
                    else "FINANCIAL_CLOSED_AUTHORITY_DIVERGENT"
                )

        live_ids = {item["position_id"] for item in self._state["positions"].values()}
        if live_ids & closed_index.by_position_id.keys():
            raise RuntimeError("FINANCIAL_CLOSED_POSITION_LIVE_CONFLICT")
        # Task 025 (review LOW-1): a margin book's closed records carry ``margin``, a cash book's never do.
        margin_book = book_leverage(self._state) > 1
        if any(("margin" in record) != margin_book for record in closed_index.by_position_id.values()):
            raise RuntimeError("FINANCIAL_CLOSED_AUTHORITY_CORRUPT")

        self._applied_by_execution_id = dict(applied_index.by_execution_id)
        self._applied_by_idempotency_key = dict(applied_index.by_idempotency_key)
        self._applied_tail = applied_index.tail
        self._closed_by_position_id = dict(closed_index.by_position_id)
        self._closed_tail_sequence = closed_index.tail_sequence

    @property
    def ready(self) -> bool:
        return self._recovery_reason is None

    def _require_ready(self) -> None:
        if not self.ready:
            raise RuntimeError(self._recovery_reason)

    @staticmethod
    def _validate_state(state: dict[str, Any]) -> None:
        margin_book = book_leverage(state) > 1
        if margin_book and set(state) != {"schema_version", "transition", "cash", "reserved_capital",
                                          "realized_gross_pnl", "fees", "positions", "applied_checkpoint",
                                          "closed_checkpoint", "leverage"}:
            raise ValueError("CORRUPT_FINANCIAL_STATE")
        for name in ("cash", "reserved_capital", "realized_gross_pnl", "fees"):
            value = D(str(state[name]))
            # Task 025: a margin book's cash may go below zero after a realized loss larger than the account.
            negative_allowed = name == "realized_gross_pnl" or (margin_book and name == "cash")
            if not value.is_finite() or (not negative_allowed and value < 0):
                raise ValueError("CORRUPT_FINANCIAL_STATE")
        seen: set[str] = set()
        for symbol, item in state["positions"].items():
            if symbol in seen or item["symbol"] != symbol or item["position_id"] in seen:
                raise ValueError("DUPLICATE_POSITION_STATE")
            seen.update((symbol, item["position_id"]))
            for name in ("base_quantity", "cost_quote", "entry_fees", "average_entry_price", "mark_price"):
                _decimal(item[name], name, allow_zero=name == "entry_fees")
            if margin_book:
                _decimal(item["margin"], "margin", allow_zero=False)
            elif "margin" in item:
                raise ValueError("CORRUPT_FINANCIAL_STATE")
        for checkpoint, keys in (
            (state["applied_checkpoint"], ("sequence", "execution_id", "idempotency_key")),
            (state["closed_checkpoint"], ("sequence", "position_id")),
        ):
            if checkpoint is None:
                continue
            if not isinstance(checkpoint, dict) or set(checkpoint) != set(keys):
                raise ValueError("CORRUPT_CHECKPOINT_STATE")
            sequence = checkpoint["sequence"]
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
                raise ValueError("CORRUPT_CHECKPOINT_STATE")

    def set_reserved_capital(self, value: Decimal) -> None:
        self._require_ready()
        candidate = dict(self._state)
        candidate["reserved_capital"] = format(_decimal(value, "reserved_capital"), "f")
        if self.available_capital(candidate) < 0:
            raise ValueError("NEGATIVE_AVAILABLE_CAPITAL")
        self.store.save(candidate); self._state = candidate

    def apply_confirmed(self, result: ExecutionResult, *, risk_authorized: bool,
                        reservation_confirmed: bool, expected_position_version: int | None = None,
                        before_closed_archive_append: Callable[[], None] | None = None,
                        before_applied_archive_append: Callable[[], None] | None = None,
                        before_final_persist: Callable[[], None] | None = None) -> dict[str, Any]:
        self._require_ready()
        if not risk_authorized or not reservation_confirmed:
            raise PermissionError("RISK_AND_RESERVATION_REQUIRED")
        result.validate_financial_evidence(position_mutation=True)
        assert result.execution_id and result.position_id and result.symbol and result.action
        identity = result.idempotency_key
        prior = self._applied_by_execution_id.get(result.execution_id)
        if prior is not None:
            if prior.idempotency_key != identity:
                raise ValueError("EXECUTION_IDENTITY_CONFLICT")
            return self.snapshot(replayed=True)
        if identity in self._applied_by_idempotency_key:
            raise ValueError("IDEMPOTENCY_IDENTITY_CONFLICT")

        # F-6: the settlement is computed and validated before the transition
        # marker is persisted. Every refusal `_open`/`_close` can raise
        # (DUPLICATE_OPEN_POSITION, STALE_POSITION_MUTATION, INSUFFICIENT_CASH,
        # NEGATIVE_AVAILABLE_CAPITAL, REDUCTION_EXCEEDS_POSITION,
        # CLOSED_POSITION_IDENTITY_CONFLICT, LONG_ONLY_ACTION_REJECTED) mutates
        # nothing, so it must leave nothing behind either: a marker written
        # first would turn a pure refusal into a book that needs operator
        # recovery. Both methods only read the durable indexes and write the
        # private candidate copy.
        candidate = json.loads(json.dumps(self._state))
        closed_record: dict[str, Any] | None = None
        if result.action == "BUY":
            self._open(candidate, result, expected_position_version)
        elif result.action == "SELL":
            closed_record = self._close(candidate, result, expected_position_version)
        else:
            raise ValueError("LONG_ONLY_ACTION_REJECTED")

        transition = dict(self._state)
        transition["transition"] = {"execution_id": result.execution_id, "idempotency_key": identity,
                                    "stage": "CONFIRMED_EXECUTION"}
        self.store.save(transition)
        applied_record: AppliedExecutionRecord | None = None
        try:
            # Block 5I crash-safety ordering: the closed-position archive
            # (if this apply produced one) is appended and fsynced before
            # the applied-execution authority record, which is itself
            # appended and fsynced before the final working-state commit
            # below - so a crash at any point leaves at most an orphan
            # sidecar record, never an uncommitted financial mutation with
            # no durable applied-execution proof.
            if closed_record is not None:
                if before_closed_archive_append:
                    before_closed_archive_append()
                closed_sequence = 0 if self._closed_tail_sequence is None else self._closed_tail_sequence + 1
                self.closed_archive.append(closed_sequence, closed_record)
                candidate["closed_checkpoint"] = {
                    "sequence": closed_sequence, "position_id": closed_record["position_id"],
                }

            if before_applied_archive_append:
                before_applied_archive_append()
            applied_sequence = 0 if self._applied_tail is None else self._applied_tail.sequence + 1
            applied_record = AppliedExecutionRecord(
                applied_sequence, result.execution_id, identity, datetime.now(UTC).isoformat(),
            )
            self.applied_archive.append(applied_record)
            candidate["applied_checkpoint"] = {
                "sequence": applied_record.sequence, "execution_id": applied_record.execution_id,
                "idempotency_key": applied_record.idempotency_key,
            }

            candidate["transition"] = None
            self._validate_state(candidate)
            if before_final_persist:
                before_final_persist()
            self.store.save(candidate)
        except Exception:
            self._recovery_reason = "FINANCIAL_TRANSITION_RECOVERY_REQUIRED"
            raise
        self._state = candidate
        if closed_record is not None:
            self._closed_by_position_id[closed_record["position_id"]] = closed_record
            self._closed_tail_sequence = candidate["closed_checkpoint"]["sequence"]
        self._applied_by_execution_id[applied_record.execution_id] = applied_record
        self._applied_by_idempotency_key[applied_record.idempotency_key] = applied_record
        self._applied_tail = applied_record
        return self.snapshot()

    def _open(self, state: dict[str, Any], result: ExecutionResult, expected: int | None) -> None:
        """Apply a confirmed BUY, whole open or an add to an existing LONG.

        The debit, fee accumulation, and average-entry-price division all
        settle inside one explicitly pinned Decimal context (Block 5E,
        final-review MEDIUM #2) - the same context ``_close`` uses - so this
        side of the settlement slice is immune to whatever precision
        happens to be ambient in the caller's thread exactly as the other
        side already was.
        """
        assert result.symbol and result.position_id and result.execution_price
        assert result.filled_base_quantity is not None and result.filled_quote_notional is not None
        current = state["positions"].get(result.symbol)
        with localcontext() as context:
            context.prec = SETTLEMENT_CONTEXT_PRECISION
            context.rounding = ROUND_HALF_EVEN
            if current is not None:
                if current["position_id"] != result.position_id:
                    raise ValueError("DUPLICATE_OPEN_POSITION")
                if expected is None or expected != current["version"]:
                    raise ValueError("STALE_POSITION_MUTATION")
                base = D(current["base_quantity"]) + result.filled_base_quantity
                cost = D(current["cost_quote"]) + result.filled_quote_notional
                version = current["version"] + 1
                opened_at = current["opened_at"]
                fees = D(current["entry_fees"]) + result.fee_amount
            else:
                if expected not in (None, 0): raise ValueError("STALE_POSITION_MUTATION")
                base, cost, version, opened_at, fees = (result.filled_base_quantity,
                    result.filled_quote_notional, 1, _utc(str(result.timestamp)), result.fee_amount)
            leverage = book_leverage(state)
            if leverage == 1:
                debit = result.filled_quote_notional + result.fee_amount
            else:
                # Task 025: the margin book reserves notional / L and pays the fee; nothing else leaves cash.
                added_margin = result.filled_quote_notional / leverage
                margin = added_margin + (D(current["margin"]) if current is not None else D("0"))
                debit = added_margin + result.fee_amount
            cash = D(state["cash"])
            if debit > cash: raise ValueError("INSUFFICIENT_CASH")
            new_cash = cash - debit
            if new_cash < D(state["reserved_capital"]):
                raise ValueError("NEGATIVE_AVAILABLE_CAPITAL")
            new_fees = D(state["fees"]) + result.fee_amount
            average_entry_price = cost / base
        state["cash"] = format(new_cash, "f")
        state["fees"] = format(new_fees, "f")
        state["positions"][result.symbol] = {
            "position_id": result.position_id, "symbol": result.symbol,
            "base_quantity": format(base, "f"), "cost_quote": format(cost, "f"),
            "entry_fees": format(fees, "f"), "average_entry_price": format(average_entry_price, "f"),
            "mark_price": format(result.execution_price, "f"), "version": version, "opened_at": opened_at,
        }
        if leverage > 1:
            state["positions"][result.symbol]["margin"] = format(margin, "f")

    def _close(self, state: dict[str, Any], result: ExecutionResult, expected: int | None) -> dict[str, Any] | None:
        """Apply a confirmed LONG reduction, whole or partial.

        The executed base quantity is authoritative: this book records the
        reduction that actually happened and never substitutes the whole
        holding for a smaller one. Selling more than is held stays impossible.

        A partial reduction releases cost basis pro rata, so the remaining
        position keeps the average entry price it already had and realized P&L
        is charged only against the fraction actually sold. The remainder is
        re-marked at the price it just traded at - the same convention ``_open``
        uses - which is realized execution evidence, not a market-data feed.

        ``entry_fees`` is released at the identical ``sold/held`` ratio as
        cost basis (Block 5E), computed under an explicitly pinned Decimal
        context rather than whatever precision happens to be ambient (F5's
        settlement slice). Both the cost-basis remainder and the entry-fees
        remainder are the complement of their released figure - ``cost -
        released`` and ``entry_fees - released_entry_fees`` - never
        independently recomputed, so released + remaining equals the
        original exactly regardless of the division's own rounding.

        Every other figure this settlement writes - gross P&L, the cash and
        fee accumulation, and the remaining position's average entry price -
        is computed inside that same pinned context (final-review MEDIUM
        #2), not just the pro-rata split: an addition or subtraction is
        rounded to its *active* context exactly as a division is, so
        leaving any one of them outside the ``with`` block would still have
        exposed it to whatever precision is ambient in the caller's thread.

        Returns the closed-position record for a full exit, ready for the
        caller to durably archive (Block 5I: this method computes it but
        never persists it - ``apply_confirmed`` owns sequencing and
        archiving), or ``None`` for a partial reduction, which archives
        nothing.
        """
        assert result.symbol and result.position_id
        assert result.filled_base_quantity is not None and result.filled_quote_notional is not None
        current = state["positions"].get(result.symbol)
        if current is None or current["position_id"] != result.position_id:
            raise ValueError("POSITION_NOT_FOUND")
        if expected is None or expected != current["version"]:
            raise ValueError("STALE_POSITION_MUTATION")
        held, sold = D(current["base_quantity"]), result.filled_base_quantity
        if sold > held:
            raise ValueError("REDUCTION_EXCEEDS_POSITION")
        cost = D(current["cost_quote"])
        entry_fees = D(current["entry_fees"])
        margin_book = book_leverage(state) > 1
        with localcontext() as context:
            context.prec = SETTLEMENT_CONTEXT_PRECISION
            context.rounding = ROUND_HALF_EVEN
            if sold == held:
                released, released_entry_fees = cost, entry_fees
            else:
                released = cost * sold / held
                released_entry_fees = entry_fees * sold / held
                basis = cost - released
                remaining_entry_fees = entry_fees - released_entry_fees
            gross = result.filled_quote_notional - released
            if margin_book:
                # Task 025: the released margin comes back with the realized gross P&L, minus the fee. Released
                # and remaining margin are complements, like the cost basis above.
                margin = D(current["margin"])
                released_margin = margin if sold == held else margin * sold / held
                remaining_margin = margin - released_margin
                new_cash = D(state["cash"]) + released_margin + gross - result.fee_amount
            else:
                new_cash = D(state["cash"]) + result.filled_quote_notional - result.fee_amount
            new_fees = D(state["fees"]) + result.fee_amount
            new_realized_gross_pnl = D(state["realized_gross_pnl"]) + gross
            if sold != held:
                base = held - sold
                average_entry_price = basis / base
        state["cash"] = format(new_cash, "f")
        state["fees"] = format(new_fees, "f")
        state["realized_gross_pnl"] = format(new_realized_gross_pnl, "f")
        if sold != held:
            state["positions"][result.symbol] = {**current,
                "base_quantity": format(base, "f"), "cost_quote": format(basis, "f"),
                "entry_fees": format(remaining_entry_fees, "f"),
                "average_entry_price": format(average_entry_price, "f"),
                "mark_price": format(result.execution_price, "f"),
                "version": current["version"] + 1}
            if margin_book:
                state["positions"][result.symbol]["margin"] = format(remaining_margin, "f")
            return None
        if result.position_id in self._closed_by_position_id:
            # Block 5G/5I: a lifetime archives exactly once. The immutable
            # closed-position authority - not the working state, which no
            # longer even holds this collection - is the source of truth
            # for this check, so it still holds across restart. Overwriting
            # a prior closed record would silently destroy its historical
            # gross_pnl, entry_fees, exit_price, and timestamps, so a
            # collision fails closed here rather than replacing it.
            raise ValueError("CLOSED_POSITION_IDENTITY_CONFLICT")
        closed = dict(current); closed.update({"status": "CLOSED", "base_quantity": "0",
            "exit_price": format(result.execution_price, "f"), "gross_pnl": format(gross, "f"),
            "closed_at": _utc(str(result.timestamp)), "version": current["version"] + 1})
        del state["positions"][result.symbol]
        return closed

    def mark(self, symbol: str, price: Decimal) -> None:
        self._require_ready(); value = _decimal(price, "mark_price", allow_zero=False)
        if symbol not in self._state["positions"]: raise KeyError(symbol)
        candidate = json.loads(json.dumps(self._state)); candidate["positions"][symbol]["mark_price"] = format(value, "f")
        self.store.save(candidate); self._state = candidate

    @staticmethod
    def available_capital(state: dict[str, Any]) -> Decimal:
        # Block 5L: derived under an explicit local context for the same
        # reason `_open`/`_close` are. Free capital is read by sizing and
        # risk admission, so computing it under whatever `decimal` precision
        # the calling process happens to have set could silently understate
        # or overstate it rather than fail closed.
        with localcontext() as context:
            context.prec = SETTLEMENT_CONTEXT_PRECISION
            context.rounding = ROUND_HALF_EVEN
            return D(state["cash"]) - D(state["reserved_capital"])

    def snapshot(self, *, replayed: bool = False) -> dict[str, Any]:
        self._require_ready()
        # Every figure below is derived from the durable book by arithmetic,
        # so it carries the same context requirement as the settlement path
        # that produced the book (Block 5L).
        with localcontext() as context:
            context.prec = SETTLEMENT_CONTEXT_PRECISION
            context.rounding = ROUND_HALF_EVEN
            exposure = sum((D(p["base_quantity"]) * D(p["mark_price"]) for p in self._state["positions"].values()), D("0"))
            unrealized = sum((D(p["base_quantity"]) * D(p["mark_price"]) - D(p["cost_quote"]) for p in self._state["positions"].values()), D("0"))
            cash, fees = D(self._state["cash"]), D(self._state["fees"])
            committed = sum((D(p["cost_quote"]) for p in self._state["positions"].values()), D("0"))
            realized_net = D(self._state["realized_gross_pnl"]) - fees
            leverage = book_leverage(self._state)
            if leverage == 1:
                equity = cash + exposure
                used_margin, spendable, margin_level = committed, cash, None
            else:
                # Task 025: equity = cash + used margin + unrealized P&L. New risk may spend only cash less any
                # unrealized loss (a paper gain never funds a new position).
                used_margin = sum((D(p["margin"]) for p in self._state["positions"].values()), D("0"))
                equity = cash + used_margin + unrealized
                spendable = cash + min(unrealized, D("0"))
                margin_level = equity / used_margin if used_margin > 0 else None
        return {"ready": True, "recovery_required": False, "cash": cash,
            "leverage": leverage, "used_margin": used_margin, "spendable_cash": spendable,
            "margin_level": margin_level,
            "reserved_capital": D(self._state["reserved_capital"]),
            "committed_capital": committed,
            "gross_exposure": exposure, "realized_gross_pnl": D(self._state["realized_gross_pnl"]),
            "fees": fees, "realized_net_pnl": realized_net,
            "unrealized_pnl": unrealized, "equity": equity,
            "available_capital": self.available_capital(self._state),
            "positions": json.loads(json.dumps(self._state["positions"])), "replayed": replayed}

    def diagnostics(self) -> dict[str, Any]:
        if not self.ready: return {"ready": False, "recovery_required": True, "reason": self._recovery_reason}
        snap = self.snapshot()
        return {key: snap[key] for key in ("ready", "recovery_required", "cash", "reserved_capital",
            "gross_exposure", "realized_gross_pnl", "realized_net_pnl", "unrealized_pnl", "fees", "equity")}

    @classmethod
    def _pre_transition_view(cls, transition: "InterruptedTransition") -> "ExecutionPortfolioFoundation":
        """The book exactly as ``apply_confirmed`` saw it before the marker.

        Hydrated from the marker-free working state and from the sidecar
        indexes *up to their checkpoints* - an orphan record the interrupted
        call appended is excluded, because at the moment ``_open``/``_close``
        ran it did not exist yet. Used only to re-run that same settlement
        arithmetic when resuming; it is never saved through.
        """
        view = cls.__new__(cls)
        view.store = None  # type: ignore[assignment]
        view.applied_archive = None  # type: ignore[assignment]
        view.closed_archive = None  # type: ignore[assignment]
        view.expected_leverage = None
        view._recovery_reason = None
        view._state = json.loads(json.dumps(transition.pre_state))
        view._applied_by_execution_id = dict(transition.applied_by_execution_id)
        view._applied_by_idempotency_key = {
            record.idempotency_key: record for record in transition.applied_by_execution_id.values()
        }
        view._applied_tail = transition.applied_tail
        view._closed_by_position_id = dict(transition.closed_by_position_id)
        view._closed_tail_sequence = transition.closed_tail_sequence
        return view


# ---------------------------------------------------------------------------
# F-1 - operator resolution of an interrupted ``apply_confirmed``
# ---------------------------------------------------------------------------
#
# ``apply_confirmed`` persists a transition marker, then (for a full exit)
# appends the closed-position record, then the applied-execution record, then
# commits the working state with the marker cleared. A process killed between
# the first and the last of those writes leaves the marker on disk, and the
# foundation refuses to load (FINANCIAL_TRANSITION_RECOVERY_REQUIRED) until an
# operator resolves it. These helpers are that resolution. They are never
# called by the runtime: ``tools/reconcile_execution_authorities.py`` is their
# only caller, and it decides which one applies from the other durable
# authorities first.
#
# Exactly two resolutions exist, because the sidecars are append-only:
#
# - nothing was appended beyond either checkpoint: the call provably changed
#   nothing, and the marker is simply removed (``abandon``);
# - a sidecar record was appended: it can never be removed, so the only
#   consistent end state is the one the call was writing, and it is completed
#   from confirmed execution evidence (``complete``) - every record already on
#   disk must match that evidence exactly, or nothing is written.


class InterruptedTransitionError(RuntimeError):
    """A pending transition cannot be resolved from the evidence given."""


@dataclass(frozen=True, slots=True)
class InterruptedTransition:
    """What a working state left mid-``apply_confirmed`` durably shows."""

    execution_id: str
    idempotency_key: str
    pre_state: dict[str, Any]
    applied_orphan: AppliedExecutionRecord | None
    closed_orphan: dict[str, Any] | None
    applied_by_execution_id: dict[str, AppliedExecutionRecord]
    applied_tail: AppliedExecutionRecord | None
    closed_by_position_id: dict[str, dict[str, Any]]
    closed_tail_sequence: int | None


def _checkpoint_orphan_count(checkpoint_sequence: int | None, count: int) -> int:
    orphans = count - (0 if checkpoint_sequence is None else checkpoint_sequence + 1)
    if orphans not in (0, 1):
        # Zero or one: apply_confirmed appends at most one record to each
        # sidecar per call, and only the last call can be interrupted.
        raise InterruptedTransitionError("SIDECAR_CHECKPOINT_DIVERGENT")
    return orphans


def inspect_interrupted_transition(
    store: FinancialStateStore, *,
    applied_archive: AppliedExecutionArchiveStore,
    closed_archive: ClosedPositionArchiveStore,
) -> InterruptedTransition | None:
    """Read a pending transition marker and classify each sidecar against it.

    Returns ``None`` when no marker is present. Raises
    ``InterruptedTransitionError`` whenever the state is anything other than
    one interrupted ``apply_confirmed`` with at most one record beyond each
    checkpoint, every one of which belongs to the marker's execution. Reads
    only; writes nothing.
    """
    payload = store.load(allow_transition=True)
    marker = payload.get("transition")
    if marker is None:
        return None
    if (not isinstance(marker, dict)
            or set(marker) != {"execution_id", "idempotency_key", "stage"}
            or marker["stage"] != "CONFIRMED_EXECUTION"
            or not isinstance(marker["execution_id"], str) or not marker["execution_id"]
            or not isinstance(marker["idempotency_key"], str) or not marker["idempotency_key"]):
        raise InterruptedTransitionError("TRANSITION_MARKER_MALFORMED")
    execution_id, idempotency_key = marker["execution_id"], marker["idempotency_key"]

    pre_state = dict(payload)
    pre_state["transition"] = None
    try:
        ExecutionPortfolioFoundation._validate_state(pre_state)
    except Exception as exc:
        raise InterruptedTransitionError("FINANCIAL_STATE_INVALID") from exc

    applied_index = applied_archive.load_index()
    applied_checkpoint = pre_state["applied_checkpoint"]
    applied_checkpoint_sequence = None
    if applied_checkpoint is not None:
        confirmed = applied_index.by_execution_id.get(applied_checkpoint["execution_id"])
        if (confirmed is None or confirmed.sequence != applied_checkpoint["sequence"]
                or confirmed.idempotency_key != applied_checkpoint["idempotency_key"]):
            raise InterruptedTransitionError("SIDECAR_CHECKPOINT_DIVERGENT")
        applied_checkpoint_sequence = confirmed.sequence
    applied_orphan = None
    if _checkpoint_orphan_count(applied_checkpoint_sequence, applied_index.count):
        applied_orphan = applied_index.tail
        if (applied_orphan is None or applied_orphan.execution_id != execution_id
                or applied_orphan.idempotency_key != idempotency_key):
            raise InterruptedTransitionError("SIDECAR_CHECKPOINT_DIVERGENT")
    elif (execution_id in applied_index.by_execution_id
            or idempotency_key in applied_index.by_idempotency_key):
        # Already durably applied by an earlier, committed call: this marker
        # is not an interrupted first application of it.
        raise InterruptedTransitionError("SIDECAR_CHECKPOINT_DIVERGENT")

    closed_index = closed_archive.load_index()
    closed_checkpoint = pre_state["closed_checkpoint"]
    closed_checkpoint_sequence = None
    if closed_checkpoint is not None:
        if closed_index.sequence_by_position_id.get(closed_checkpoint["position_id"]) != closed_checkpoint["sequence"]:
            raise InterruptedTransitionError("SIDECAR_CHECKPOINT_DIVERGENT")
        closed_checkpoint_sequence = closed_checkpoint["sequence"]
    closed_orphan = None
    if _checkpoint_orphan_count(closed_checkpoint_sequence, closed_index.count):
        closed_orphan = closed_index.by_position_id[closed_index.tail_position_id]  # type: ignore[index]

    applied_confirmed = {
        key: record for key, record in applied_index.by_execution_id.items()
        if applied_orphan is None or key != applied_orphan.execution_id
    }
    applied_tail = None
    if applied_checkpoint is not None:
        applied_tail = applied_confirmed[applied_checkpoint["execution_id"]]
    closed_confirmed = {
        key: record for key, record in closed_index.by_position_id.items()
        if closed_orphan is None or key != closed_orphan["position_id"]
    }
    live_ids = {item["position_id"] for item in pre_state["positions"].values()}
    if live_ids & closed_confirmed.keys():
        raise InterruptedTransitionError("SIDECAR_CHECKPOINT_DIVERGENT")

    return InterruptedTransition(
        execution_id, idempotency_key, pre_state, applied_orphan, closed_orphan,
        applied_confirmed, applied_tail, closed_confirmed, closed_checkpoint_sequence,
    )


def _open_foundation(
    store: FinancialStateStore, applied_archive: AppliedExecutionArchiveStore,
    closed_archive: ClosedPositionArchiveStore,
) -> ExecutionPortfolioFoundation:
    foundation = ExecutionPortfolioFoundation(
        store, applied_archive=applied_archive, closed_archive=closed_archive,
        leverage=None,   # Task 025: operator recovery keeps the book's own leverage (schema 2 or 3)
    )
    if not foundation.ready:
        raise InterruptedTransitionError("POST_RESOLUTION_NOT_READY")
    return foundation


def abandon_interrupted_transition(
    store: FinancialStateStore, *,
    applied_archive: AppliedExecutionArchiveStore,
    closed_archive: ClosedPositionArchiveStore,
    idempotency_key: str,
) -> None:
    """Remove the marker of a transition that provably changed nothing.

    Allowed only when neither sidecar holds a record beyond its checkpoint:
    the working state under the marker is then byte-for-byte the pre-call
    book, so clearing the marker restores exactly what was there. Verified by
    reloading through the runtime's own loader.
    """
    transition = inspect_interrupted_transition(
        store, applied_archive=applied_archive, closed_archive=closed_archive,
    )
    if transition is None or transition.idempotency_key != idempotency_key:
        raise InterruptedTransitionError("TRANSITION_NOT_FOUND")
    if transition.applied_orphan is not None or transition.closed_orphan is not None:
        raise InterruptedTransitionError("TRANSITION_PARTIALLY_APPLIED")
    store.save(transition.pre_state)
    _open_foundation(store, applied_archive, closed_archive)


def complete_interrupted_transition(
    store: FinancialStateStore, *,
    applied_archive: AppliedExecutionArchiveStore,
    closed_archive: ClosedPositionArchiveStore,
    evidence: ExecutionResult,
    verify_only: bool = False,
) -> dict[str, Any] | None:
    """Finish an interrupted ``apply_confirmed`` from confirmed evidence.

    Re-runs the same ``_open``/``_close`` settlement on the pre-call book,
    then requires every sidecar record the interrupted call already appended
    to equal what that settlement produces - the closed-position record field
    for field, the applied record by execution_id and idempotency_key - before
    appending only what is still missing and committing the working state in
    the original order. Any disagreement raises before anything is written.
    ``verify_only`` runs every one of those checks and returns ``None``
    without writing.
    """
    transition = inspect_interrupted_transition(
        store, applied_archive=applied_archive, closed_archive=closed_archive,
    )
    if transition is None:
        raise InterruptedTransitionError("TRANSITION_NOT_FOUND")
    try:
        evidence.validate_financial_evidence(position_mutation=True)
    except Exception as exc:
        raise InterruptedTransitionError("TRANSITION_EVIDENCE_INVALID") from exc
    if (evidence.execution_id != transition.execution_id
            or evidence.idempotency_key != transition.idempotency_key):
        raise InterruptedTransitionError("TRANSITION_EVIDENCE_MISMATCH")

    view = ExecutionPortfolioFoundation._pre_transition_view(transition)
    candidate = json.loads(json.dumps(transition.pre_state))
    current = candidate["positions"].get(evidence.symbol)
    expected_version = None if current is None else current["version"]
    closed_record: dict[str, Any] | None = None
    try:
        if evidence.action == "BUY":
            view._open(candidate, evidence, expected_version)
        elif evidence.action == "SELL":
            closed_record = view._close(candidate, evidence, expected_version)
        else:
            raise ValueError("LONG_ONLY_ACTION_REJECTED")
    except Exception as exc:
        raise InterruptedTransitionError("TRANSITION_EVIDENCE_INVALID") from exc

    # A closed record already on disk must be exactly the one this settlement
    # produces - which also refuses evidence that settles as a partial
    # reduction (no record at all) against an archived full exit.
    if transition.closed_orphan is not None and transition.closed_orphan != closed_record:
        raise InterruptedTransitionError("TRANSITION_EVIDENCE_MISMATCH")
    if verify_only:
        return None

    if closed_record is not None:
        closed_sequence = (0 if transition.closed_tail_sequence is None
                           else transition.closed_tail_sequence + 1)
        if transition.closed_orphan is None:
            closed_archive.append(closed_sequence, closed_record)
        candidate["closed_checkpoint"] = {
            "sequence": closed_sequence, "position_id": closed_record["position_id"],
        }

    applied_record = transition.applied_orphan
    if applied_record is None:
        applied_sequence = 0 if transition.applied_tail is None else transition.applied_tail.sequence + 1
        applied_record = AppliedExecutionRecord(
            applied_sequence, transition.execution_id, transition.idempotency_key,
            datetime.now(UTC).isoformat(),
        )
        applied_archive.append(applied_record)
    candidate["applied_checkpoint"] = {
        "sequence": applied_record.sequence, "execution_id": applied_record.execution_id,
        "idempotency_key": applied_record.idempotency_key,
    }
    candidate["transition"] = None
    ExecutionPortfolioFoundation._validate_state(candidate)
    store.save(candidate)
    return _open_foundation(store, applied_archive, closed_archive).snapshot()
