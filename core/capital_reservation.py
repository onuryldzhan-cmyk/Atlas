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


class JsonReservationStore:
    """Atomic file implementation; missing/corrupt state never becomes empty state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize_empty(self) -> None:
        if self.path.exists():
            raise FileExistsError(self.path)
        self.save(())

    def load(self) -> tuple[CapitalReservation, ...]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema") != "atlas-capital-reservations-v1":
            raise ValueError("unsupported reservation state schema")
        return tuple(CapitalReservation.from_dict(item) for item in payload["reservations"])

    def save(self, reservations: tuple[CapitalReservation, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {"schema": "atlas-capital-reservations-v1",
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
    """

    _LIVE_ENCUMBRANCE_STATUSES = (ReservationStatus.RESERVED, ReservationStatus.INDETERMINATE)

    def __init__(self, store: ReservationStore, total_allocatable: Decimal) -> None:
        self.store = store
        self.total_allocatable = decimal_value(total_allocatable, "total_allocatable", allow_zero=False)
        self._lock = threading.RLock()
        self._ready = False
        self._items: dict[str, CapitalReservation] = {}
        try:
            loaded = store.load()
            items = {item.reservation_id: item for item in loaded}
            if len(items) != len(loaded):
                raise ValueError("duplicate reservation id")
            if self._live_encumbered(items) > self.total_allocatable:
                raise ValueError("reservations exceed allocatable capital")
            self._items = items
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
            existing = self._items.get(reservation_id)
            if existing is not None:
                if existing.request_id == request_id and existing.amount == amount:
                    return existing
                raise ValueError("reservation id collision")
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
            current = self._items.get(reservation_id)
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
            current = self._items.get(reservation_id)
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

    def get(self, reservation_id: str) -> CapitalReservation | None:
        with self._lock:
            return self._items.get(reservation_id)
