"""
ATLAS EXCHANGE MANAGER v2.2

Lifecycle-safe and fail-closed exchange facade.

Order path
----------
Input validation
    -> LIVE safety authorization
    -> financial risk authorization
    -> exchange adapter
"""

from __future__ import annotations

import logging
import math
import re

from typing import Any

from exchange.adapters.binance_global import BinanceGlobalExchange
from exchange.adapters.binance_tr import BinanceTRExchange
from exchange.execution_risk_guard import ExecutionRiskGuard
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
    VERSION = "2.3"

    def __init__(
        self,
        exchange_name: str = "binance_global",
        *,
        exchange: Any | None = None,
        safety_gate: ExecutionSafetyGate | None = None,
        risk_guard: ExecutionRiskGuard | None = None,
    ) -> None:
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

        self.risk_guard = risk_guard

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
            return self._rejection(
                reason="INVALID_SYMBOL",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=quantity,
            )

        if normalized_side not in _ALLOWED_ORDER_SIDES:
            return self._rejection(
                reason="INVALID_SIDE",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=quantity,
            )

        if normalized_quantity is None:
            return self._rejection(
                reason="INVALID_QUANTITY",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=quantity,
            )

        safety_decision = (
            self.safety_gate.authorize_live_order()
        )

        if safety_decision.get(
            "allowed"
        ) is not True:
            rejection = self._rejection(
                reason=safety_decision.get(
                    "reason",
                    "LIVE_AUTHORIZATION_REJECTED",
                ),
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

            logger.warning(
                "Live order rejected by safety gate: "
                "symbol=%s side=%s quantity=%s reason=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
                rejection["reason"],
            )

            return rejection

        if self.risk_guard is None:
            rejection = self._rejection(
                reason="RISK_GUARD_NOT_CONFIGURED",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

            logger.error(
                "Live order rejected because risk guard is missing: "
                "symbol=%s side=%s quantity=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
            )

            return rejection

        risk_decision = (
            self.risk_guard.authorize_order()
        )

        if risk_decision.get(
            "allowed"
        ) is not True:
            rejection = self._rejection(
                reason=risk_decision.get(
                    "reason",
                    "RISK_AUTHORIZATION_REJECTED",
                ),
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

            logger.warning(
                "Live order rejected by risk guard: "
                "symbol=%s side=%s quantity=%s reason=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
                rejection["reason"],
            )

            return rejection

        try:
            result = self.exchange.place_order(
                normalized_symbol,
                normalized_side,
                normalized_quantity,
            )
        except TimeoutError as exc:
            logger.exception(
                "Exchange timeout during order submission: "
                "symbol=%s side=%s quantity=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
            )

            return {
                "status": "ERROR",
                "allowed": False,
                "reason": "EXCHANGE_TIMEOUT",
                "symbol": normalized_symbol,
                "side": normalized_side,
                "quantity": normalized_quantity,
                "error_type": type(exc).__name__,
            }
        except ConnectionError as exc:
            logger.exception(
                "Exchange connection error during order submission: "
                "symbol=%s side=%s quantity=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
            )

            return {
                "status": "ERROR",
                "allowed": False,
                "reason": "EXCHANGE_CONNECTION_ERROR",
                "symbol": normalized_symbol,
                "side": normalized_side,
                "quantity": normalized_quantity,
                "error_type": type(exc).__name__,
            }
        except Exception as exc:
            logger.exception(
                "Unexpected exchange adapter failure: "
                "symbol=%s side=%s quantity=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
            )

            return {
                "status": "ERROR",
                "allowed": False,
                "reason": "EXCHANGE_ADAPTER_ERROR",
                "symbol": normalized_symbol,
                "side": normalized_side,
                "quantity": normalized_quantity,
                "error_type": type(exc).__name__,
            }

        if not isinstance(
            result,
            dict,
        ):
            logger.error(
                "Invalid exchange response type: "
                "symbol=%s side=%s quantity=%s response_type=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
                type(result).__name__,
            )

            return {
                "status": "ERROR",
                "allowed": False,
                "reason": "INVALID_EXCHANGE_RESPONSE",
                "symbol": normalized_symbol,
                "side": normalized_side,
                "quantity": normalized_quantity,
                "error_type": "InvalidExchangeResponse",
            }

        logger.info(
            "Live order delegated after validation, safety and risk "
            "authorization: symbol=%s side=%s quantity=%s",
            normalized_symbol,
            normalized_side,
            normalized_quantity,
        )

        return result

    def status(
        self,
    ) -> dict[str, Any]:
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
            "risk_guard": (
                self.risk_guard.status()
                if self.risk_guard is not None
                else {
                    "configured": False,
                    "status": "FAIL_CLOSED",
                }
            ),
            "exchange": exchange_status,
        }
