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
    """Serializes reserve/transitions and rolls memory back on save failure."""

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
            if self._encumbered(items) > self.total_allocatable:
                raise ValueError("reservations exceed allocatable capital")
            self._items = items
            self._ready = True
        except Exception:
            self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    @staticmethod
    def _encumbered(items: dict[str, CapitalReservation]) -> Decimal:
        return sum((item.amount for item in items.values()
                    if item.status in {ReservationStatus.RESERVED, ReservationStatus.COMMITTED,
                                       ReservationStatus.INDETERMINATE}), Decimal("0"))

    @property
    def available(self) -> Decimal:
        with self._lock:
            if not self._ready:
                raise RuntimeError("reservation state recovery required")
            return self.total_allocatable - self._encumbered(self._items)

    def active_reserved_capital(self, *, exclude: str | None = None) -> Decimal:
        """Capital still reserved or indeterminate, excluding invested commits."""
        with self._lock:
            if not self._ready:
                raise RuntimeError("reservation state recovery required")
            return sum(
                (
                    item.amount
                    for reservation_id, item in self._items.items()
                    if reservation_id != exclude
                    and item.status
                    in {ReservationStatus.RESERVED, ReservationStatus.INDETERMINATE}
                ),
                Decimal("0"),
            )

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
                (ReservationStatus.RESERVED, ReservationStatus.COMMITTED),
                (ReservationStatus.RESERVED, ReservationStatus.RELEASED),
                (ReservationStatus.RESERVED, ReservationStatus.INDETERMINATE),
            }
            if (current.status, target) not in allowed:
                raise ValueError(f"invalid reservation transition {current.status.value}->{target.value}")
            updated = replace(current, status=target, version=current.version + 1)
            candidate = dict(self._items); candidate[reservation_id] = updated
            self._persist(candidate)
            return updated

    def commit(self, reservation_id: str) -> CapitalReservation:
        return self._transition(reservation_id, ReservationStatus.COMMITTED)

    def release(self, reservation_id: str) -> CapitalReservation:
        return self._transition(reservation_id, ReservationStatus.RELEASED)

    def mark_indeterminate(self, reservation_id: str) -> CapitalReservation:
        return self._transition(reservation_id, ReservationStatus.INDETERMINATE)

    def get(self, reservation_id: str) -> CapitalReservation | None:
        with self._lock:
            return self._items.get(reservation_id)
