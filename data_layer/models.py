"""Validated persistence records with lossless financial decimal handling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .contracts import IntegrityViolation

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SYMBOL = re.compile(r"^[A-Z0-9]{2,24}$")
ORDER_STATUSES = frozenset({"NEW", "ACCEPTED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"})
POSITION_STATUSES = frozenset({"OPEN", "CLOSED"})
SIDES = frozenset({"BUY", "SELL"})


def validate_id(value: str, name: str) -> str:
    value = str(value).strip()
    if not _ID.fullmatch(value):
        raise IntegrityViolation(f"invalid {name}")
    return value


def normalize_symbol(value: str) -> str:
    value = str(value).strip().upper()
    if not _SYMBOL.fullmatch(value):
        raise IntegrityViolation("invalid symbol")
    return value


def decimal_text(value: Decimal | str | int, name: str, *, positive: bool = False, nonnegative: bool = False) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise IntegrityViolation(f"invalid {name}") from exc
    if not number.is_finite():
        raise IntegrityViolation(f"{name} must be finite")
    if positive and number <= 0:
        raise IntegrityViolation(f"{name} must be positive")
    if nonnegative and number < 0:
        raise IntegrityViolation(f"{name} must be nonnegative")
    text = format(number, "f")
    if len(text) > 80:
        raise IntegrityViolation(f"{name} exceeds precision policy")
    return text


def utc_text(value: datetime | str) -> str:
    if isinstance(value, str):
        candidate = value.replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise IntegrityViolation("invalid timestamp") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise IntegrityViolation("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def metadata_text(value: dict[str, Any]) -> str:
    if not isinstance(value, dict):
        raise IntegrityViolation("metadata must be an object")
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise IntegrityViolation("metadata must be finite JSON") from exc
    if not isinstance(decoded, dict):
        raise IntegrityViolation("metadata must be an object")
    return encoded


def parse_metadata(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise IntegrityViolation("corrupted metadata JSON") from exc
    if not isinstance(decoded, dict):
        raise IntegrityViolation("metadata root is not an object")
    metadata_text(decoded)
    return decoded


@dataclass(frozen=True, slots=True)
class OrderRecord:
    order_id: str
    symbol: str
    side: str
    quantity: Decimal
    status: str
    created_at: datetime | str
    idempotency_key: str
    limit_price: Decimal | None = None
    strategy: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validated()

    def validated(self) -> "OrderRecord":
        object.__setattr__(self, "order_id", validate_id(self.order_id, "order_id"))
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        if self.side not in SIDES or self.status not in ORDER_STATUSES:
            raise IntegrityViolation("invalid order side/status")
        object.__setattr__(
            self, "quantity",
            Decimal(decimal_text(self.quantity, "quantity", positive=True)),
        )
        if self.limit_price is not None:
            object.__setattr__(
                self, "limit_price",
                Decimal(decimal_text(self.limit_price, "limit_price", positive=True)),
            )
        object.__setattr__(
            self, "idempotency_key",
            validate_id(self.idempotency_key, "idempotency_key"),
        )
        if self.strategy is not None and not str(self.strategy).strip():
            raise IntegrityViolation("strategy cannot be blank")
        object.__setattr__(self, "created_at", utc_text(self.created_at))
        object.__setattr__(self, "metadata", parse_metadata(metadata_text(self.metadata)))
        return self


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    execution_id: str
    order_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    executed_at: datetime | str
    realized_pnl: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validated()

    def validated(self) -> "ExecutionRecord":
        object.__setattr__(self, "execution_id", validate_id(self.execution_id, "execution_id"))
        object.__setattr__(self, "order_id", validate_id(self.order_id, "order_id"))
        object.__setattr__(self, "quantity", Decimal(decimal_text(self.quantity, "quantity", positive=True)))
        object.__setattr__(self, "price", Decimal(decimal_text(self.price, "price", positive=True)))
        object.__setattr__(self, "fee", Decimal(decimal_text(self.fee, "fee", nonnegative=True)))
        if self.realized_pnl is not None:
            object.__setattr__(self, "realized_pnl", Decimal(decimal_text(self.realized_pnl, "realized_pnl")))
        object.__setattr__(self, "executed_at", utc_text(self.executed_at))
        object.__setattr__(self, "metadata", parse_metadata(metadata_text(self.metadata)))
        return self


@dataclass(frozen=True, slots=True)
class PositionRecord:
    position_id: str
    symbol: str
    quantity: Decimal
    average_price: Decimal
    status: str
    updated_at: datetime | str
    realized_pnl: Decimal = Decimal("0")
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validated()

    def validated(self) -> "PositionRecord":
        object.__setattr__(self, "position_id", validate_id(self.position_id, "position_id"))
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        object.__setattr__(self, "quantity", Decimal(decimal_text(self.quantity, "quantity", nonnegative=True)))
        object.__setattr__(self, "average_price", Decimal(decimal_text(self.average_price, "average_price", nonnegative=True)))
        object.__setattr__(self, "realized_pnl", Decimal(decimal_text(self.realized_pnl, "realized_pnl")))
        if self.status not in POSITION_STATUSES:
            raise IntegrityViolation("invalid position status")
        if self.status == "OPEN" and Decimal(str(self.quantity)) <= 0:
            raise IntegrityViolation("open position quantity must be positive")
        object.__setattr__(self, "updated_at", utc_text(self.updated_at))
        object.__setattr__(self, "metadata", parse_metadata(metadata_text(self.metadata)))
        return self
