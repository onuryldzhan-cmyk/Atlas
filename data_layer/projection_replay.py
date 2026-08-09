"""Idempotent relational projection from confirmed authoritative evidence.

This module deliberately has no exchange dependency.  It projects only a confirmed
full fill into order, execution, and evidenced long-only position state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from .contracts import IntegrityViolation, StorageBackend
from .models import ExecutionRecord, OrderRecord, PositionRecord


@dataclass(frozen=True, slots=True)
class ConfirmedExecutionEvidence:
    request_id: str
    order_id: str
    execution_id: str
    symbol: str
    side: str
    base_quantity: Decimal
    filled_quote_notional: Decimal
    price: Decimal
    fee: Decimal
    executed_at: datetime | str
    position_id: str
    prior_position: PositionRecord | None = None
    realized_pnl: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    externally_confirmed: bool = True


@dataclass(frozen=True, slots=True)
class ReplayResult:
    state: str
    writes: int


def _position_projection(e: ConfirmedExecutionEvidence) -> PositionRecord:
    side = e.side.upper()
    if side == "BUY":
        if e.prior_position is not None:
            raise IntegrityViolation("position averaging is not evidenced for replay")
        return PositionRecord(
            e.position_id, e.symbol, e.base_quantity, e.price, "OPEN", e.executed_at,
            Decimal("0"), {"direction": "LONG", "source_execution_id": e.execution_id},
        )
    if side != "SELL":
        raise IntegrityViolation("SHORT and unknown sides are unsupported")
    prior = e.prior_position
    if prior is None or prior.status != "OPEN":
        raise IntegrityViolation("SELL requires an evidenced open LONG position")
    if e.base_quantity != prior.quantity:
        raise IntegrityViolation("partial close is deferred; SELL must fully close")
    return PositionRecord(
        prior.position_id, prior.symbol, Decimal("0"), prior.average_price, "CLOSED",
        e.executed_at, Decimal("0") if e.realized_pnl is None else e.realized_pnl,
        {"direction": "LONG", "source_execution_id": e.execution_id}, prior.version + 1,
    )


def replay_confirmed_execution(storage: StorageBackend, evidence: ConfirmedExecutionEvidence) -> ReplayResult:
    if not evidence.externally_confirmed:
        raise IntegrityViolation("projection replay requires confirmed authoritative execution evidence")
    if evidence.base_quantity <= 0 or evidence.filled_quote_notional <= 0 or evidence.price <= 0:
        raise IntegrityViolation("explicit financial quantities and price must be positive")
    if evidence.base_quantity * evidence.price != evidence.filled_quote_notional:
        raise IntegrityViolation("base quantity and quote notional disagree with execution price")
    position = _position_projection(evidence)
    order = OrderRecord(
        evidence.order_id, evidence.symbol, evidence.side.upper(), evidence.base_quantity,
        "FILLED", evidence.executed_at, evidence.request_id,
        metadata={"projection_source": "CONFIRMED_EXECUTION", "filled_quote_notional": format(evidence.filled_quote_notional, "f")},
    )
    execution = ExecutionRecord(
        evidence.execution_id, evidence.order_id, evidence.base_quantity, evidence.price,
        evidence.fee, evidence.executed_at, evidence.realized_pnl,
        {**evidence.metadata, "filled_quote_notional": format(evidence.filled_quote_notional, "f")},
    )
    with storage.unit_of_work() as uow:
        existing_order = uow.orders.get(order.order_id)
        existing_execution = uow.executions.get(execution.execution_id)
        existing_position = uow.positions.get(position.position_id)
        if existing_order is not None and existing_order != order:
            raise IntegrityViolation("order projection disagrees with confirmed evidence")
        if existing_execution is not None and existing_execution != execution:
            raise IntegrityViolation("execution projection disagrees with confirmed evidence")
        closing_from_prior = evidence.side.upper() == "SELL" and existing_position == evidence.prior_position
        if existing_position is not None and existing_position != position and not closing_from_prior:
            raise IntegrityViolation("position projection disagrees with confirmed evidence")
        if all(item is not None for item in (existing_order, existing_execution, existing_position)):
            return ReplayResult("ALREADY_PROJECTED", 0)
        if any(item is not None for item in (existing_order, existing_execution)):
            raise IntegrityViolation("partial relational projection requires reconciliation")
        uow.orders.add(order)
        uow.executions.add(execution)
        if closing_from_prior:
            uow.positions.put_cas(position, expected_version=evidence.prior_position.version)
        else:
            uow.positions.put_cas(position, expected_version=-1)
    return ReplayResult("PROJECTED", 3)
