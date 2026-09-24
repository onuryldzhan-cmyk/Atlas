"""Backend-neutral durable capital reservation state machine."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
import json
import os
from pathlib import Path
import threading
from typing import Protocol

from core.risk_engine import decimal_value


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class CapitalReservation:
    reservation_id: str
    request_id: str
    amount: Decimal
    status: ReservationStatus
    version: int = 1

    def __post_init__(self) -> None:
        if not self.reservation_id or not self.request_id:
            raise ValueError("reservation_id and request_id are required")
        object.__setattr__(self, "amount", decimal_value(self.amount, "amount", allow_zero=False))

    def to_dict(self) -> dict[str, str | int]:
        return {"reservation_id": self.reservation_id, "request_id": self.request_id,
                "amount": str(self.amount), "status": self.status.value, "version": self.version}

    @classmethod
    def from_dict(cls, value: dict) -> "CapitalReservation":
        return cls(str(value["reservation_id"]), str(value["request_id"]),
                   Decimal(str(value["amount"])), ReservationStatus(str(value["status"])),
                   int(value.get("version", 1)))


class ReservationStore(Protocol):
    def load(self) -> tuple[CapitalReservation, ...]: ...
    def save(self, reservations: tuple[CapitalReservation, ...]) -> None: ...


class ReservationArchive(Protocol):
    def append(self, reservation: CapitalReservation) -> None: ...
    def load_index(self) -> dict[str, CapitalReservation]: ...


class ReservationSchemaMigrationRequiredError(ValueError):
    """Raised when a working-set file is still on the legacy v1 schema.

    Block 5H made the working-set store version-gated rather than
    auto-migrating: a v1 file is real, valuable reservation history, and
    silently reinterpreting it under the v2 contract (where a COMMITTED or
    RELEASED entry is expected to live in the archive, not the working set)
    would risk misclassifying it. ``tools/migrate_capital_reservations.py``
    is the only supported path from v1 to v2 + archive.
    """


class JsonReservationStore:
    """Atomic file implementation; missing/corrupt state never becomes empty state.

    ``SCHEMA_V2`` working-set files hold any reservation status, but by
    convention (enforced by ``CapitalReservationLedger.compact()``, not by
    this store) only RESERVED/INDETERMINATE remain once a ledger with an
    archive has compacted its terminal records out. A file still tagged
    ``SCHEMA_V1`` is refused outright - see
    ``ReservationSchemaMigrationRequiredError``.
    """

    SCHEMA_V1 = "atlas-capital-reservations-v1"
    SCHEMA_V2 = "atlas-capital-reservations-v2"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize_empty(self) -> None:
        if self.path.exists():
            raise FileExistsError(self.path)
        self.save(())

    def load(self) -> tuple[CapitalReservation, ...]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        schema = payload.get("schema")
        if schema == self.SCHEMA_V1:
            raise ReservationSchemaMigrationRequiredError(
                "reservation state schema v1 requires migration to v2 "
                "(run tools/migrate_capital_reservations.py)"
            )
        if schema != self.SCHEMA_V2:
            raise ValueError("unsupported reservation state schema")
        return tuple(CapitalReservation.from_dict(item) for item in payload["reservations"])

    def save(self, reservations: tuple[CapitalReservation, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {"schema": self.SCHEMA_V2,
                   "reservations": [item.to_dict() for item in reservations]}
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()


class ReservationArchiveError(RuntimeError):
    """Base class for immutable capital-reservation archive failures."""


class ReservationArchiveCorruptError(ReservationArchiveError):
    """A line in the archive is malformed, torn, or holds a live status."""


class ReservationArchiveConflictError(ReservationArchiveError):
    """Two archive lines disagree about the same reservation_id."""


# Statuses ever allowed to appear in the immutable archive. RESERVED and
# INDETERMINATE are live encumbrance (Block 5F) and must never leave the
# working set - see CapitalReservationLedger.compact().
_ARCHIVABLE_STATUSES = (ReservationStatus.COMMITTED, ReservationStatus.RELEASED)


class ReservationArchiveStore:
    """Immutable, append-only JSON-Lines archive of terminal reservations.

    One canonical ``CapitalReservation.to_dict()`` payload per line, for a
    COMMITTED or RELEASED reservation only. A line is written durably
    (write -> flush -> fsync, mirroring ``AuditEventStore``) and the file is
    never rewritten or truncated - ``append`` is the only write operation.
    This is what lets ``CapitalReservationLedger.get()`` answer a
    reservation_id forever, long after ``compact()`` has removed it from the
    live working-set file.

    Duplicate lines for the same reservation_id are tolerated only when
    field-equivalent (an interrupted compaction retried the same append);
    disagreeing duplicates or a malformed/torn line fail ``load_index()``
    closed rather than being silently treated as empty or as the newest
    line winning.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, reservation: CapitalReservation) -> None:
        if reservation.status not in _ARCHIVABLE_STATUSES:
            raise ValueError(
                f"cannot archive reservation in status {reservation.status.value}"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(reservation.to_dict(), sort_keys=True, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def load_index(self) -> dict[str, CapitalReservation]:
        if not self.path.exists():
            return {}
        index: dict[str, CapitalReservation] = {}
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        raise ValueError("archive line is not an object")
                    record = CapitalReservation.from_dict(payload)
                    if record.status not in _ARCHIVABLE_STATUSES:
                        raise ValueError(
                            f"archive contains live status {record.status.value}"
                        )
                except Exception as exc:
                    raise ReservationArchiveCorruptError(
                        f"malformed capital reservation archive line {line_number}"
                    ) from exc
                existing = index.get(record.reservation_id)
                if existing is None:
                    index[record.reservation_id] = record
                elif existing != record:
                    raise ReservationArchiveConflictError(
                        "conflicting archive records for "
                        f"reservation_id={record.reservation_id!r}"
                    )
        return index


class CapitalReservationLedger:
    """Serializes reserve/transitions and rolls memory back on save failure.

    Live encumbrance - capital this ledger treats as still spoken for - is
    RESERVED and INDETERMINATE only (Block 5F). COMMITTED is durable
    settlement history: once a reservation settles, the capital it spent is
    accounted for through the durable cash balance
    ``ExecutionPortfolioFoundation`` maintains from that point on, not
    through this ledger. Counting a COMMITTED reservation as encumbrance too
    would double-encumber the same capital forever, shrinking ``available``
    on every trade the book ever settles. RELEASED is likewise history, not
    encumbrance. ``_live_encumbered`` is the single definition both
    ``available`` and ``active_reserved_capital`` are computed from, so the
    two can never drift into independently-maintained formulas.

    Block 5H adds an optional immutable ``archive``: a durable,
    append-only record of every COMMITTED/RELEASED reservation that
    ``compact()`` has moved out of the live working-set file. ``get()``
    reads through to it, so historical reservations remain queryable
    forever even after compaction, and ``reserve()`` treats any
    reservation_id already in the archive as permanently consumed - it can
    never be re-created as RESERVED. Neither ``available`` nor
    ``active_reserved_capital`` is affected by the archive: both are still
    computed from the live working set alone, exactly as in 5F. An
    ``archive`` of ``None`` (the default, and every pre-5H call site)
    behaves exactly as an always-empty archive.
    """

    _LIVE_ENCUMBRANCE_STATUSES = (ReservationStatus.RESERVED, ReservationStatus.INDETERMINATE)

    def __init__(
        self,
        store: ReservationStore,
        total_allocatable: Decimal,
        archive: ReservationArchive | None = None,
    ) -> None:
        self.store = store
        self.archive = archive
        self.total_allocatable = decimal_value(total_allocatable, "total_allocatable", allow_zero=False)
        self._lock = threading.RLock()
        self._ready = False
        self._items: dict[str, CapitalReservation] = {}
        self._archive_index: dict[str, CapitalReservation] = {}
        try:
            loaded = store.load()
            items = {item.reservation_id: item for item in loaded}
            if len(items) != len(loaded):
                raise ValueError("duplicate reservation id")
            archive_index: dict[str, CapitalReservation] = {}
            if archive is not None:
                # Working set and archive may legitimately share a
                # reservation_id for one call (an interrupted compaction -
                # Block 5H crash window B/D/E): the archive append durably
                # succeeded but the working-set rewrite that would have
                # dropped the record never completed. Tolerated only when
                # the two copies agree field-for-field; any disagreement is
                # corruption, not a race, and must fail closed rather than
                # picking a side.
                archive_index = dict(archive.load_index())
                for reservation_id, archived_item in archive_index.items():
                    live_item = items.get(reservation_id)
                    if live_item is not None and live_item != archived_item:
                        raise ValueError(
                            "reservation present in both working set and "
                            "archive with disagreeing payloads"
                        )
            if self._live_encumbered(items) > self.total_allocatable:
                raise ValueError("reservations exceed allocatable capital")
            self._items = items
            self._archive_index = archive_index
            self._ready = True
        except Exception:
            self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    @classmethod
    def _live_encumbered(
        cls, items: dict[str, CapitalReservation], *, exclude: str | None = None
    ) -> Decimal:
        """Capital still live-encumbered: RESERVED or INDETERMINATE only.

        COMMITTED and RELEASED reservations are history and never counted
        here, regardless of amount. ``exclude`` names one reservation id to
        omit entirely, for a caller measuring capacity for the request that
        already holds that reservation.
        """
        return sum(
            (
                item.amount
                for reservation_id, item in items.items()
                if reservation_id != exclude
                and item.status in cls._LIVE_ENCUMBRANCE_STATUSES
            ),
            Decimal("0"),
        )

    @property
    def available(self) -> Decimal:
        with self._lock:
            if not self._ready:
                raise RuntimeError("reservation state recovery required")
            return self.total_allocatable - self._live_encumbered(self._items)

    def active_reserved_capital(self, *, exclude: str | None = None) -> Decimal:
        """Capital still reserved or indeterminate, excluding invested commits.

        Same live-encumbrance definition ``available`` uses (Block 5F): with
        no ``exclude``, ``available == total_allocatable -
        active_reserved_capital()`` holds exactly.
        """
        with self._lock:
            if not self._ready:
                raise RuntimeError("reservation state recovery required")
            return self._live_encumbered(self._items, exclude=exclude)

    def _persist(self, candidate: dict[str, CapitalReservation]) -> None:
        try:
            self.store.save(tuple(sorted(candidate.values(), key=lambda item: item.reservation_id)))
        except Exception:
            self._ready = False
            raise RuntimeError("reservation persistence failed; recovery required")
        self._items = candidate

    def reserve(self, reservation_id: str, request_id: str, amount: Decimal) -> CapitalReservation:
        amount = decimal_value(amount, "amount", allow_zero=False)
        with self._lock:
            if not self._ready:
                raise RuntimeError("reservation state recovery required")
            # Block 5H: a reservation_id already archived is consumed
            # history, unconditionally - unlike the working-set collision
            # check just below, there is no idempotent same-request/same
            # -amount carve-out here, because an archived id can never be
            # re-armed as RESERVED regardless of what is requested.
            if reservation_id in self._archive_index:
                raise ValueError("reservation id already archived")
            existing = self._items.get(reservation_id)
            if existing is not None:
                if existing.request_id != request_id:
                    raise ValueError("reservation id collision")
                if existing.status is ReservationStatus.RESERVED:
                    # Idempotent adoption of the live reservation this same
                    # request already holds - never a second encumbrance.
                    if existing.amount == amount:
                        return existing
                    raise ValueError("reservation id collision")
                if existing.status is ReservationStatus.RELEASED:
                    # F-3: a RELEASED reservation is history, not encumbrance,
                    # so returning it would admit a retried request with no
                    # live capital behind it (and its settlement would then
                    # fail on the RELEASED->COMMITTED transition). A retry of
                    # a request whose earlier attempt provably never crossed
                    # the side-effect boundary is re-armed instead: a fresh
                    # RESERVED version, capacity-checked exactly like a new
                    # reservation.
                    if amount > self.available:
                        raise ValueError("insufficient unreserved capital")
                    item = replace(existing, amount=amount, status=ReservationStatus.RESERVED,
                                   version=existing.version + 1)
                    candidate = dict(self._items); candidate[reservation_id] = item
                    self._persist(candidate)
                    return item
                # COMMITTED means the request already settled; INDETERMINATE
                # means its outcome is unresolved. Neither may ever be
                # reserved again.
                raise ValueError(f"reservation already {existing.status.value}")
            if amount > self.available:
                raise ValueError("insufficient unreserved capital")
            item = CapitalReservation(reservation_id, request_id, amount, ReservationStatus.RESERVED)
            candidate = dict(self._items); candidate[reservation_id] = item
            self._persist(candidate)
            return item

    def _transition(self, reservation_id: str, target: ReservationStatus) -> CapitalReservation:
        with self._lock:
            if not self._ready:
                raise RuntimeError("reservation state recovery required")
            # Archive-aware (Block 5H): an id already compacted out of the
            # working set is looked up the same way get() finds it, so a
            # replayed release()/mark_indeterminate() call against an
            # already-archived (necessarily terminal) record hits the
            # idempotent same-status return below or the ordinary invalid
            # -transition error, never a spurious KeyError - which for
            # release() would otherwise halt the runtime.
            current = self.get(reservation_id)
            if current is None:
                raise KeyError(reservation_id)
            if current.status is target:
                return current
            allowed = {
                (ReservationStatus.RESERVED, ReservationStatus.RELEASED),
                (ReservationStatus.RESERVED, ReservationStatus.INDETERMINATE),
            }
            if (current.status, target) not in allowed:
                raise ValueError(f"invalid reservation transition {current.status.value}->{target.value}")
            updated = replace(current, status=target, version=current.version + 1)
            candidate = dict(self._items); candidate[reservation_id] = updated
            self._persist(candidate)
            return updated

    def commit(self, reservation_id: str, settled_amount: Decimal | None = None) -> CapitalReservation:
        """Commit a reservation, optionally settling it to an exact amount.

        ``settled_amount`` (Block 5E) is the amount durable settlement
        actually spent - ``filled_quote_notional + quote_fee`` on the BUY
        path. It is always at or below the reserved amount, because the fee
        is taken out of the approved allocation, never added on top of it
        (``ExecutionManager._resolve_base_fill``). The COMMITTED reservation
        is recorded at that settled figure rather than at the full
        reservation, so the deterministic sub-quantum remainder the fill
        never spent stops being permanently encumbered by this reservation.

        A COMMITTED reservation is durable settlement history, not live
        encumbrance (Block 5F): the instant this call returns, its amount
        stops counting toward ``available`` and ``active_reserved_capital``
        the way a RESERVED or INDETERMINATE amount does - the capital it
        held is now tracked through the durable cash balance
        ``ExecutionPortfolioFoundation`` maintains, not through a second
        ledger. A COMMITTED reservation still never transitions to RELEASED
        and is never linked back to the position it funded; partial or full
        exit of that position leaves this record untouched. There is no
        lifecycle beyond COMMITTED for this ledger to run - reclaiming the
        capital does not require one.

        Idempotent: a reservation already COMMITTED is returned unchanged,
        regardless of ``settled_amount`` - a replayed commit must not be
        able to re-price an already-settled reservation.
        """
        with self._lock:
            if not self._ready:
                raise RuntimeError("reservation state recovery required")
            # Archive-aware (Block 5H): see _transition's identical rationale.
            current = self.get(reservation_id)
            if current is None:
                raise KeyError(reservation_id)
            if current.status is ReservationStatus.COMMITTED:
                return current
            if current.status is not ReservationStatus.RESERVED:
                raise ValueError(
                    f"invalid reservation transition {current.status.value}->COMMITTED"
                )
            amount = current.amount
            if settled_amount is not None:
                settled_amount = decimal_value(settled_amount, "settled_amount", allow_zero=False)
                if settled_amount > current.amount:
                    raise ValueError("settled_amount exceeds reserved amount")
                amount = settled_amount
            updated = replace(
                current, status=ReservationStatus.COMMITTED, amount=amount,
                version=current.version + 1,
            )
            candidate = dict(self._items); candidate[reservation_id] = updated
            self._persist(candidate)
            return updated

    def release(self, reservation_id: str) -> CapitalReservation:
        return self._transition(reservation_id, ReservationStatus.RELEASED)

    def mark_indeterminate(self, reservation_id: str) -> CapitalReservation:
        return self._transition(reservation_id, ReservationStatus.INDETERMINATE)

    def reserved(self) -> tuple[CapitalReservation, ...]:
        """Every RESERVED record in the live working set, in id order."""
        with self._lock:
            if not self._ready:
                raise RuntimeError("reservation state recovery required")
            return tuple(
                item for _, item in sorted(self._items.items())
                if item.status is ReservationStatus.RESERVED
            )

    def get(self, reservation_id: str) -> CapitalReservation | None:
        """Look up a reservation: live working set first, then archive.

        A COMMITTED/RELEASED reservation ``compact()`` has moved out of the
        working set is still returned exactly - this is what keeps
        ``MarketLoop``'s sizing-replay-conflict check (which compares a
        fresh proposal against whatever this returns) correct for a request
        identity whose only surviving record is in the archive.
        """
        with self._lock:
            found = self._items.get(reservation_id)
            if found is not None:
                return found
            return self._archive_index.get(reservation_id)

    def compact(self) -> int:
        """Durably move every terminal working-set record into the archive.

        For each RESERVED->...->COMMITTED/RELEASED record still in the
        live working set: append it to the archive (durable: write ->
        flush -> fsync) before removing it from the working set and
        atomically rewriting the working-set file without it. The two
        steps are ordered so that a crash between them never loses the
        record - the record ends up durably in both places, and the next
        ``CapitalReservationLedger`` construction accepts that as an
        interrupted compaction (Block 5H) rather than a conflict, because
        the archived copy and the still-present working-set copy agree
        field-for-field. Calling ``compact()`` again after such an
        interruption finishes it: the record is already archived
        identically, so this call only removes it from the working set.

        Never touches a RESERVED or INDETERMINATE record - both remain
        live encumbrance in the working set exactly as before, so no
        compaction failure (partial or total) can ever free capital that
        is still reserved or indeterminate. Returns the number of records
        archived by this call.
        """
        with self._lock:
            if not self._ready:
                raise RuntimeError("reservation state recovery required")
            if self.archive is None:
                raise RuntimeError("reservation archive not configured")

            terminal_ids = [
                reservation_id for reservation_id, item in self._items.items()
                if item.status in _ARCHIVABLE_STATUSES
            ]

            archived = 0
            for reservation_id in terminal_ids:
                item = self._items[reservation_id]
                already_archived = self._archive_index.get(reservation_id)
                if already_archived is None:
                    self.archive.append(item)
                    self._archive_index[reservation_id] = item
                elif already_archived != item:
                    # Defense in depth: reserve()'s archive-collision guard
                    # and __init__'s cross-store check should make this
                    # unreachable in practice. Fail closed rather than
                    # silently keep or overwrite either copy.
                    raise RuntimeError(
                        "reservation archive conflict during compaction: "
                        f"reservation_id={reservation_id!r}"
                    )

                candidate = {
                    rid: it for rid, it in self._items.items() if rid != reservation_id
                }
                self._persist(candidate)
                archived += 1

            return archived
