"""
ATLAS EXCHANGE MANAGER v2.0

Lifecycle-safe and fail-closed exchange facade.

Responsibilities
----------------
- Select the configured exchange adapter
- Delegate market-data operations
- Enforce ExecutionSafetyGate before every live order submission
- Support dependency injection for deterministic offline tests
- Return structured rejection decisions
"""

from __future__ import annotations

import logging
from typing import Any

from exchange.adapters.binance_global import BinanceGlobalExchange
from exchange.adapters.binance_tr import BinanceTRExchange
from exchange.execution_safety_gate import ExecutionSafetyGate


logger = logging.getLogger(
    "AtlasAI.ExchangeManager"
)


class ExchangeManager:
    VERSION = "2.0"

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

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any]:
        """
        Authorize and submit one live exchange order.

        The exchange adapter is never called unless every safety gate
        passes. Rejections are structured, non-exceptional, and auditable.
        """

        normalized_symbol = str(
            symbol
        ).strip().upper()

        normalized_side = str(
            side
        ).strip().upper()

        normalized_quantity = float(
            quantity
        )

        authorization = (
            self.safety_gate.authorize_live_order()
        )

        if authorization.get(
            "allowed"
        ) is not True:
            rejection = {
                "status": "REJECTED",
                "allowed": False,
                "reason": authorization.get(
                    "reason",
                    "LIVE_AUTHORIZATION_REJECTED",
                ),
                "symbol": normalized_symbol,
                "side": normalized_side,
                "quantity": normalized_quantity,
            }

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
            "Live order delegated after safety authorization: "
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
            "safety": self.safety_gate.status(),
            "exchange": exchange_status,
        }
