"""
============================================================
ATLAS EXECUTION MODELS v22.0
============================================================

Unified Institutional Execution Contracts

Purpose
-------

This module defines the official execution data contracts used
throughout Project Atlas AI.

Used by
-------

- Execution Manager
- Execution Controller
- Paper Execution Engine
- Live Execution Engine
- Exchange Adapters
- Position Controller
- Portfolio Manager
- Capital Manager
- Risk Engine
- Learning Engine
- Backtest Engine
- Audit and Event systems

Design goals
------------

- Backward compatibility
- Stable serialization
- Explicit execution lifecycle
- Unified metadata handling
- UTC timestamp normalization
- Safe data validation
- Paper/live mode compatibility
- Position and learning integration readiness

============================================================
"""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4


# ============================================================
# HELPERS
# ============================================================


def utc_now_iso() -> str:
    """
    Return the current UTC time as an ISO-8601 string.
    """

    return datetime.now(
        UTC
    ).isoformat()


def normalize_timestamp(
    value: datetime | str | None,
) -> str:
    """
    Convert supported timestamp values into ISO-8601 strings.
    """

    if value is None:
        return utc_now_iso()

    if isinstance(
        value,
        datetime,
    ):
        if value.tzinfo is None:
            value = value.replace(
                tzinfo=UTC,
            )

        return value.isoformat()

    return str(
        value
    )


def normalize_symbol(
    symbol: str,
) -> str:
    """
    Normalize an exchange symbol.
    """

    normalized = str(
        symbol
    ).strip().upper()

    if not normalized:
        raise ValueError(
            "Execution symbol cannot be empty."
        )

    return normalized


def normalize_action(
    action: str,
) -> str:
    """
    Normalize and validate an execution action.
    """

    normalized = str(
        action
    ).strip().upper()

    aliases = {
        "LONG": "BUY",
        "OPEN_LONG": "BUY",
        "SHORT": "SELL",
        "CLOSE_LONG": "SELL",
        "CLOSE": "SELL",
    }

    normalized = aliases.get(
        normalized,
        normalized,
    )

    supported_actions = {
        "BUY",
        "SELL",
        "HOLD",
        "CANCEL",
    }

    if normalized not in supported_actions:
        raise ValueError(
            f"Unsupported execution action: {normalized}"
        )

    return normalized


def normalize_mode(
    mode: str | None,
) -> str:
    """
    Normalize the execution environment.
    """

    normalized = str(
        mode or "PAPER"
    ).strip().upper()

    aliases = {
        "SIMULATION": "PAPER",
        "SIMULATED": "PAPER",
        "TEST": "PAPER",
        "TESTNET": "TESTNET",
        "REAL": "LIVE",
        "PRODUCTION": "LIVE",
    }

    return aliases.get(
        normalized,
        normalized,
    )


def normalize_risk(
    risk: str | None,
) -> str:
    """
    Normalize an execution risk classification.
    """

    normalized = str(
        risk or "MEDIUM"
    ).strip().upper()

    supported_risks = {
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
        "UNKNOWN",
    }

    if normalized not in supported_risks:
        return "UNKNOWN"

    return normalized


def status_implies_success(
    status: str,
) -> bool:
    """
    Infer execution success from a status value.
    """

    successful_statuses = {
        "SUCCESS",
        "APPROVED",
        "ACCEPTED",
        "EXECUTED",
        "PAPER_EXECUTED",
        "FILLED",
        "PARTIALLY_FILLED",
        "OPEN",
        "CLOSED",
        "COMPLETED",
    }

    return str(
        status
    ).strip().upper() in successful_statuses


# ============================================================
# EXECUTION REQUEST
# ============================================================


@dataclass(slots=True)
class ExecutionRequest:
    """
    Canonical request sent to the Atlas execution pipeline.

    Compatibility
    -------------

    The first four fields preserve the historical constructor:

        ExecutionRequest(
            symbol,
            action,
            price,
            amount,
        )

    The ``risk_level`` property is provided as an alias for
    older modules that expect that name.
    """

    symbol: str
    action: str
    price: float
    amount: float

    strategy: str = "UNKNOWN"
    confidence: float = 0.0
    risk: str = "MEDIUM"

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    mode: str = "PAPER"

    request_id: str = field(
        default_factory=lambda: str(
            uuid4()
        )
    )

    timestamp: datetime | str = field(
        default_factory=utc_now_iso
    )

    source: str = "ATLAS"
    order_type: str = "MARKET"

    stop_loss: float | None = None
    take_profit: float | None = None
    trailing_stop: float | None = None

    time_in_force: str = "GTC"
    reduce_only: bool = False

    def __post_init__(
        self,
    ) -> None:
        """
        Normalize and validate request values.
        """

        self.symbol = normalize_symbol(
            self.symbol
        )

        self.action = normalize_action(
            self.action
        )

        self.price = float(
            self.price
        )

        self.amount = float(
            self.amount
        )

        self.confidence = float(
            self.confidence
        )

        self.strategy = str(
            self.strategy or "UNKNOWN"
        ).strip().upper()

        self.risk = normalize_risk(
            self.risk
        )

        self.mode = normalize_mode(
            self.mode
        )

        self.timestamp = normalize_timestamp(
            self.timestamp
        )

        self.source = str(
            self.source or "ATLAS"
        ).strip().upper()

        self.order_type = str(
            self.order_type or "MARKET"
        ).strip().upper()

        self.time_in_force = str(
            self.time_in_force or "GTC"
        ).strip().upper()

        if self.price < 0:
            raise ValueError(
                "Execution price cannot be negative."
            )

        if self.amount < 0:
            raise ValueError(
                "Execution amount cannot be negative."
            )

        if not 0.0 <= self.confidence <= 100.0:
            raise ValueError(
                "Confidence must be between 0 and 100."
            )

        self.metadata = dict(
            self.metadata or {}
        )

        if self.stop_loss is not None:
            self.stop_loss = float(
                self.stop_loss
            )

        if self.take_profit is not None:
            self.take_profit = float(
                self.take_profit
            )

        if self.trailing_stop is not None:
            self.trailing_stop = float(
                self.trailing_stop
            )

    @property
    def risk_level(
        self,
    ) -> str:
        """
        Backward-compatible alias for ``risk``.
        """

        return self.risk

    @risk_level.setter
    def risk_level(
        self,
        value: str,
    ) -> None:
        self.risk = normalize_risk(
            value
        )

    @property
    def side(
        self,
    ) -> str:
        """
        Return the execution action as a side alias.
        """

        return self.action

    @property
    def quantity(
        self,
    ) -> float:
        """
        Backward-compatible alias for ``amount``.
        """

        return self.amount

    @quantity.setter
    def quantity(
        self,
        value: float,
    ) -> None:
        self.amount = float(
            value
        )

    @property
    def notional(
        self,
    ) -> float:
        """
        Return the nominal value of the request.
        """

        return self.price * self.amount

    def normalized_action(
        self,
    ) -> str:
        """
        Return the normalized execution action.
        """

        return self.action

    def validate(
        self,
    ) -> tuple[bool, list[str]]:
        """
        Validate the request without raising an exception.

        Returns
        -------

        tuple
            ``(is_valid, errors)``
        """

        errors: list[str] = []

        if not self.symbol:
            errors.append(
                "SYMBOL_REQUIRED"
            )

        if self.action not in {
            "BUY",
            "SELL",
            "HOLD",
            "CANCEL",
        }:
            errors.append(
                "INVALID_ACTION"
            )

        if self.action in {
            "BUY",
            "SELL",
        }:
            if self.price <= 0:
                errors.append(
                    "PRICE_MUST_BE_POSITIVE"
                )

            if self.amount <= 0:
                errors.append(
                    "AMOUNT_MUST_BE_POSITIVE"
                )

        if not 0.0 <= self.confidence <= 100.0:
            errors.append(
                "INVALID_CONFIDENCE"
            )

        return (
            not errors,
            errors,
        )

    def to_dict(
        self,
    ) -> dict[str, Any]:
        """
        Serialize the request into a stable dictionary.
        """

        payload = asdict(
            self
        )

        payload[
            "timestamp"
        ] = normalize_timestamp(
            self.timestamp
        )

        payload[
            "risk_level"
        ] = self.risk

        payload[
            "quantity"
        ] = self.amount

        payload[
            "notional"
        ] = self.notional

        return payload

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> ExecutionRequest:
        """
        Create an ExecutionRequest from a dictionary.

        Historical field aliases are supported.
        """

        data = dict(
            payload or {}
        )

        if (
            "amount" not in data
            and "quantity" in data
        ):
            data[
                "amount"
            ] = data.pop(
                "quantity"
            )

        if (
            "risk" not in data
            and "risk_level" in data
        ):
            data[
                "risk"
            ] = data.pop(
                "risk_level"
            )

        if (
            "action" not in data
            and "side" in data
        ):
            data[
                "action"
            ] = data.pop(
                "side"
            )

        supported_fields = {
            field_name
            for field_name in cls.__dataclass_fields__
        }

        filtered_data = {
            key: value
            for key, value in data.items()
            if key in supported_fields
        }

        return cls(
            **filtered_data
        )


# ============================================================
# EXECUTION RESULT
# ============================================================


@dataclass(slots=True)
class ExecutionResult:
    """
    Canonical result returned by the Atlas execution pipeline.

    The model accepts both modern and historical fields:

    - ``data`` for execution payloads
    - ``metadata`` for contextual information
    - ``mode`` for paper/testnet/live routing
    - optional success inference from execution status
    """

    success: bool | None = None

    status: str = "UNKNOWN"
    message: str = ""

    execution_id: str | None = None
    position_id: str | None = None

    symbol: str | None = None
    action: str | None = None

    filled_price: float | None = None
    # Legacy compatibility only.  On the canonical PAPER BUY path this is the
    # quote-currency allocation; it is never a base-asset quantity contract.
    filled_amount: float | None = None

    requested_quote_allocation: Decimal | None = None
    requested_base_quantity: Decimal | None = None
    filled_base_quantity: Decimal | None = None
    filled_quote_notional: Decimal | None = None

    fee: float = 0.0
    fee_amount: Decimal = Decimal("0")
    fee_currency: str | None = None
    pnl: float = 0.0

    mode: str = "PAPER"

    data: dict[str, Any] = field(
        default_factory=dict
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    timestamp: datetime | str = field(
        default_factory=utc_now_iso
    )

    error_code: str | None = None
    error_details: str | None = None

    order_id: str | None = None
    trade_id: str | None = None

    requested_price: float | None = None
    requested_amount: float | None = None

    slippage: float = 0.0
    latency_ms: float = 0.0

    def __post_init__(
        self,
    ) -> None:
        """
        Normalize execution result values.
        """

        self.status = str(
            self.status or "UNKNOWN"
        ).strip().upper()

        self.message = str(
            self.message or ""
        )

        self.mode = normalize_mode(
            self.mode
        )

        self.timestamp = normalize_timestamp(
            self.timestamp
        )

        if self.symbol is not None:
            self.symbol = normalize_symbol(
                self.symbol
            )

        if self.action is not None:
            self.action = normalize_action(
                self.action
            )

        if self.filled_price is not None:
            self.filled_price = float(
                self.filled_price
            )

        if self.filled_amount is not None:
            self.filled_amount = float(
                self.filled_amount
            )

        for field_name in (
            "requested_quote_allocation", "requested_base_quantity",
            "filled_base_quantity", "filled_quote_notional", "fee_amount",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            try:
                number = Decimal(str(value))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"Invalid {field_name}") from exc
            if not number.is_finite() or number < 0:
                raise ValueError(f"Invalid {field_name}")
            setattr(self, field_name, number)

        if self.requested_price is not None:
            self.requested_price = float(
                self.requested_price
            )

        if self.requested_amount is not None:
            self.requested_amount = float(
                self.requested_amount
            )

        self.fee = float(
            self.fee
        )

        self.pnl = float(
            self.pnl
        )

        self.slippage = float(
            self.slippage
        )

        self.latency_ms = float(
            self.latency_ms
        )

        self.data = dict(
            self.data or {}
        )

        self.metadata = dict(
            self.metadata or {}
        )

        if self.success is None:
            self.success = status_implies_success(
                self.status
            )
        else:
            self.success = bool(
                self.success
            )

    @property
    def risk_level(
        self,
    ) -> str:
        """
        Read risk information from data or metadata.
        """

        value = self.data.get(
            "risk_level",
            self.metadata.get(
                "risk_level",
                self.metadata.get(
                    "risk",
                    "UNKNOWN",
                ),
            ),
        )

        return normalize_risk(
            value
        )

    @property
    def quantity(
        self,
    ) -> float | None:
        """
        Backward-compatible alias for ``filled_amount``.
        """

        return self.filled_amount

    @property
    def price(
        self,
    ) -> float | None:
        """
        Backward-compatible alias for ``filled_price``.
        """

        return self.filled_price

    def mark_success(
        self,
        *,
        status: str = "EXECUTED",
        message: str | None = None,
    ) -> ExecutionResult:
        """
        Mark the result as successful.
        """

        self.success = True
        self.status = str(
            status
        ).strip().upper()

        if message is not None:
            self.message = str(
                message
            )

        return self

    def mark_failure(
        self,
        *,
        status: str = "FAILED",
        message: str,
        error_code: str | None = None,
        error_details: str | None = None,
    ) -> ExecutionResult:
        """
        Mark the result as failed.
        """

        self.success = False
        self.status = str(
            status
        ).strip().upper()

        self.message = str(
            message
        )

        self.error_code = error_code
        self.error_details = error_details

        return self

    def add_data(
        self,
        key: str,
        value: Any,
    ) -> ExecutionResult:
        """
        Add an execution payload value.
        """

        self.data[
            str(key)
        ] = value

        return self

    def add_metadata(
        self,
        key: str,
        value: Any,
    ) -> ExecutionResult:
        """
        Add contextual metadata.
        """

        self.metadata[
            str(key)
        ] = value

        return self

    def to_dict(
        self,
    ) -> dict[str, Any]:
        """
        Serialize the execution result.
        """

        payload = asdict(
            self
        )

        payload[
            "timestamp"
        ] = normalize_timestamp(
            self.timestamp
        )

        payload[
            "quantity"
        ] = self.filled_amount

        payload[
            "price"
        ] = self.filled_price

        payload[
            "risk_level"
        ] = self.risk_level

        for field_name in (
            "requested_quote_allocation", "requested_base_quantity",
            "filled_base_quantity", "filled_quote_notional", "fee_amount",
        ):
            value = payload.get(field_name)
            if value is not None:
                payload[field_name] = format(value, "f")

        return payload

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> ExecutionResult:
        """
        Create an ExecutionResult from a dictionary.

        Historical field aliases are supported.
        """

        data = dict(
            payload or {}
        )

        if (
            "filled_amount" not in data
            and "quantity" in data
        ):
            data[
                "filled_amount"
            ] = data.pop(
                "quantity"
            )

        if (
            "filled_price" not in data
            and "price" in data
        ):
            data[
                "filled_price"
            ] = data.pop(
                "price"
            )

        if (
            "metadata" not in data
            and "meta" in data
        ):
            data[
                "metadata"
            ] = data.pop(
                "meta"
            )

        supported_fields = {
            field_name
            for field_name in cls.__dataclass_fields__
        }

        filtered_data = {
            key: value
            for key, value in data.items()
            if key in supported_fields
        }

        return cls(
            **filtered_data
        )


# ============================================================
# COMPATIBILITY ALIASES
# ============================================================


OrderRequest = ExecutionRequest
OrderResult = ExecutionResult


__all__ = [
    "ExecutionRequest",
    "ExecutionResult",
    "OrderRequest",
    "OrderResult",
    "normalize_action",
    "normalize_mode",
    "normalize_risk",
    "normalize_symbol",
    "normalize_timestamp",
    "status_implies_success",
    "utc_now_iso",
]
