"""
ATLAS EXCHANGE MANAGER v2.1

Lifecycle-safe and fail-closed exchange facade.

Responsibilities
----------------
- Select the configured exchange adapter
- Delegate market-data operations
- Validate order inputs before adapter access
- Enforce ExecutionSafetyGate before every live order submission
- Support dependency injection for deterministic offline tests
- Return structured rejection decisions
"""

from __future__ import annotations

import logging
import math
import re

from typing import Any

from exchange.adapters.binance_global import BinanceGlobalExchange
from exchange.adapters.binance_tr import BinanceTRExchange
from exchange.execution_safety_gate import ExecutionSafetyGate


logger = logging.getLogger(
    "AtlasAI.ExchangeManager"
)


_SYMBOL_PATTERN = re.compile(
    r"^[A-Z0-9]{5,30}$"
)

_ALLOWED_ORDER_SIDES = {
    "BUY",
    "SELL",
}


class ExchangeManager:
    VERSION = "2.1"

    def __init__(
        self,
        exchange_name: str = "binance_global",
        *,
        exchange: Any | None = None,
        safety_gate: ExecutionSafetyGate | None = None,
    ) -> None:
        """
        Construct the exchange facade.

        Injected exchange adapters are primarily intended for tests and
        controlled composition roots. When no adapter is injected, the
        configured production adapter is created normally.

        The safety gate defaults to a fail-closed environment-based gate.
        """

        self.exchange_name = str(
            exchange_name
        ).strip().lower()

        self.exchange = (
            exchange
            if exchange is not None
            else self._create_exchange()
        )

        self.safety_gate = (
            safety_gate
            if safety_gate is not None
            else ExecutionSafetyGate.from_environment()
        )

    def _create_exchange(
        self,
    ) -> Any:
        if self.exchange_name == "binance_tr":
            logger.info(
                "Using Binance TR"
            )

            return BinanceTRExchange()

        logger.info(
            "Using Binance Global"
        )

        return BinanceGlobalExchange()

    def connect(
        self,
    ) -> Any:
        return self.exchange.connect()

    def disconnect(
        self,
    ) -> Any:
        return self.exchange.disconnect()

    def get_price(
        self,
        symbol: str,
    ) -> Any:
        return self.exchange.get_price(
            symbol
        )

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
    ) -> Any:
        return self.exchange.get_klines(
            symbol,
            interval,
            limit,
        )

    @staticmethod
    def _rejection(
        *,
        reason: str,
        symbol: str,
        side: str,
        quantity: Any,
    ) -> dict[str, Any]:
        """
        Build a consistent fail-closed order rejection.
        """

        return {
            "status": "REJECTED",
            "allowed": False,
            "reason": reason,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
        }

    @staticmethod
    def _normalize_quantity(
        quantity: Any,
    ) -> float | None:
        """
        Convert quantity to a positive finite float.

        Invalid, zero, negative, NaN and infinite values return None.
        """

        if isinstance(
            quantity,
            bool,
        ):
            return None

        try:
            normalized = float(
                quantity
            )
        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            return None

        if not math.isfinite(
            normalized
        ):
            return None

        if normalized <= 0:
            return None

        return normalized

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: Any,
    ) -> dict[str, Any]:
        """
        Validate, authorize and submit one live exchange order.

        Validation and authorization are completed before the exchange
        adapter can be called.
        """

        normalized_symbol = str(
            symbol
            if symbol is not None
            else ""
        ).strip().upper()

        normalized_side = str(
            side
            if side is not None
            else ""
        ).strip().upper()

        normalized_quantity = self._normalize_quantity(
            quantity
        )

        if not _SYMBOL_PATTERN.fullmatch(
            normalized_symbol
        ):
            rejection = self._rejection(
                reason="INVALID_SYMBOL",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=quantity,
            )

            logger.warning(
                "Order rejected before authorization: reason=%s",
                rejection["reason"],
            )

            return rejection

        if normalized_side not in _ALLOWED_ORDER_SIDES:
            rejection = self._rejection(
                reason="INVALID_SIDE",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=quantity,
            )

            logger.warning(
                "Order rejected before authorization: "
                "symbol=%s side=%s reason=%s",
                normalized_symbol,
                normalized_side,
                rejection["reason"],
            )

            return rejection

        if normalized_quantity is None:
            rejection = self._rejection(
                reason="INVALID_QUANTITY",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=quantity,
            )

            logger.warning(
                "Order rejected before authorization: "
                "symbol=%s side=%s reason=%s",
                normalized_symbol,
                normalized_side,
                rejection["reason"],
            )

            return rejection

        authorization = (
            self.safety_gate.authorize_live_order()
        )

        if authorization.get(
            "allowed"
        ) is not True:
            rejection = self._rejection(
                reason=authorization.get(
                    "reason",
                    "LIVE_AUTHORIZATION_REJECTED",
                ),
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

            logger.warning(
                "Live order rejected: symbol=%s side=%s "
                "quantity=%s reason=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
                rejection["reason"],
            )

            return rejection

        result = self.exchange.place_order(
            normalized_symbol,
            normalized_side,
            normalized_quantity,
        )

        logger.info(
            "Live order delegated after validation and authorization: "
            "symbol=%s side=%s quantity=%s",
            normalized_symbol,
            normalized_side,
            normalized_quantity,
        )

        return result

    def status(
        self,
    ) -> dict[str, Any]:
        """
        Return non-secret manager and safety state.
        """

        exchange_status_method = getattr(
            self.exchange,
            "status",
            None,
        )

        if callable(
            exchange_status_method
        ):
            try:
                exchange_status = (
                    exchange_status_method()
                )
            except Exception as exc:
                exchange_status = {
                    "status": "ERROR",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
        else:
            exchange_status = {
                "status_supported": False,
            }

        return {
            "name": "ExchangeManager",
            "version": self.VERSION,
            "exchange_name": self.exchange_name,
            "validation": {
                "allowed_sides": sorted(
                    _ALLOWED_ORDER_SIDES
                ),
                "symbol_pattern": (
                    _SYMBOL_PATTERN.pattern
                ),
                "quantity_requires_positive_finite_number": True,
            },
            "safety": self.safety_gate.status(),
            "exchange": exchange_status,
        }
