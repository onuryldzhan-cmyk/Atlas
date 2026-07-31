"""
ATLAS EXCHANGE MANAGER v2.4

Lifecycle-safe and fail-closed exchange facade.

Order path
----------
Input validation
    -> idempotency validation
    -> LIVE safety authorization
    -> financial risk authorization
    -> exchange adapter
    -> terminal result cache

Idempotency rules
-----------------
- Every live order requires a non-empty idempotency key.
- Same key + same normalized order returns the cached result.
- Same key + different order is rejected.
- Successful and exchange-rejected terminal responses are cached.
- Adapter errors are not cached, allowing controlled retry.
- Cache is bounded by TTL and maximum entry count.
"""

from __future__ import annotations

import logging
import math
import re
import time

from collections import OrderedDict
from copy import deepcopy
from typing import Any, Callable

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
    VERSION = "2.4"

    def __init__(
        self,
        exchange_name: str = "binance_global",
        *,
        exchange: Any | None = None,
        safety_gate: ExecutionSafetyGate | None = None,
        risk_guard: ExecutionRiskGuard | None = None,
        idempotency_ttl_seconds: float = 900.0,
        idempotency_max_entries: int = 10_000,
        monotonic_provider: Callable[[], float] | None = None,
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

        self.idempotency_ttl_seconds = self._normalize_positive_float(
            idempotency_ttl_seconds,
            field_name="idempotency_ttl_seconds",
        )

        self.idempotency_max_entries = self._normalize_positive_int(
            idempotency_max_entries,
            field_name="idempotency_max_entries",
        )

        self._monotonic_provider = (
            monotonic_provider
            if monotonic_provider is not None
            else time.monotonic
        )

        self._idempotency_cache: OrderedDict[
            str,
            dict[str, Any],
        ] = OrderedDict()

    @staticmethod
    def _normalize_positive_float(
        value: Any,
        *,
        field_name: str,
    ) -> float:
        if isinstance(value, bool):
            raise ValueError(
                f"{field_name} must be a positive finite number"
            )

        try:
            normalized = float(value)
        except (
            TypeError,
            ValueError,
            OverflowError,
        ) as exc:
            raise ValueError(
                f"{field_name} must be a positive finite number"
            ) from exc

        if (
            not math.isfinite(normalized)
            or normalized <= 0
        ):
            raise ValueError(
                f"{field_name} must be a positive finite number"
            )

        return normalized

    @staticmethod
    def _normalize_positive_int(
        value: Any,
        *,
        field_name: str,
    ) -> int:
        if isinstance(value, bool):
            raise ValueError(
                f"{field_name} must be a positive integer"
            )

        try:
            normalized = int(value)
        except (
            TypeError,
            ValueError,
            OverflowError,
        ) as exc:
            raise ValueError(
                f"{field_name} must be a positive integer"
            ) from exc

        if normalized <= 0:
            raise ValueError(
                f"{field_name} must be a positive integer"
            )

        return normalized

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
    def _error_result(
        *,
        reason: str,
        symbol: str,
        side: str,
        quantity: float,
        error_type: str,
    ) -> dict[str, Any]:
        return {
            "status": "ERROR",
            "allowed": False,
            "reason": reason,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "error_type": error_type,
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

    @staticmethod
    def _normalize_idempotency_key(
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        normalized = str(
            value
        ).strip()

        if not normalized:
            return None

        return normalized

    @staticmethod
    def _order_fingerprint(
        *,
        symbol: str,
        side: str,
        quantity: float,
    ) -> tuple[str, str, float]:
        return (
            symbol,
            side,
            quantity,
        )

    def _purge_expired_idempotency_entries(
        self,
    ) -> None:
        now = float(
            self._monotonic_provider()
        )

        expired_keys = [
            key
            for key, entry in self._idempotency_cache.items()
            if (
                now - float(entry["created_at"])
                >= self.idempotency_ttl_seconds
            )
        ]

        for key in expired_keys:
            self._idempotency_cache.pop(
                key,
                None,
            )

    def _lookup_idempotency_entry(
        self,
        *,
        key: str,
        fingerprint: tuple[str, str, float],
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any] | None:
        self._purge_expired_idempotency_entries()

        entry = self._idempotency_cache.get(
            key
        )

        if entry is None:
            return None

        if entry["fingerprint"] != fingerprint:
            logger.warning(
                "Idempotency conflict rejected: "
                "symbol=%s side=%s quantity=%s",
                symbol,
                side,
                quantity,
            )

            return self._rejection(
                reason="IDEMPOTENCY_KEY_CONFLICT",
                symbol=symbol,
                side=side,
                quantity=quantity,
            )

        self._idempotency_cache.move_to_end(
            key
        )

        return deepcopy(
            entry["response"]
        )

    def _cache_idempotency_result(
        self,
        *,
        key: str,
        fingerprint: tuple[str, str, float],
        response: dict[str, Any],
    ) -> None:
        self._purge_expired_idempotency_entries()

        self._idempotency_cache[key] = {
            "fingerprint": fingerprint,
            "response": deepcopy(response),
            "created_at": float(
                self._monotonic_provider()
            ),
        }

        self._idempotency_cache.move_to_end(
            key
        )

        while (
            len(self._idempotency_cache)
            > self.idempotency_max_entries
        ):
            self._idempotency_cache.popitem(
                last=False
            )

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: Any,
        *,
        idempotency_key: Any = None,
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

        normalized_idempotency_key = (
            self._normalize_idempotency_key(
                idempotency_key
            )
        )

        if normalized_idempotency_key is None:
            return self._rejection(
                reason="IDEMPOTENCY_KEY_REQUIRED",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        fingerprint = self._order_fingerprint(
            symbol=normalized_symbol,
            side=normalized_side,
            quantity=normalized_quantity,
        )

        cached_result = self._lookup_idempotency_entry(
            key=normalized_idempotency_key,
            fingerprint=fingerprint,
            symbol=normalized_symbol,
            side=normalized_side,
            quantity=normalized_quantity,
        )

        if cached_result is not None:
            return cached_result

        safety_decision = (
            self.safety_gate.authorize_live_order()
        )

        if safety_decision.get(
            "allowed"
        ) is not True:
            return self._rejection(
                reason=safety_decision.get(
                    "reason",
                    "LIVE_AUTHORIZATION_REJECTED",
                ),
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        if self.risk_guard is None:
            logger.error(
                "Live order rejected because risk guard is missing: "
                "symbol=%s side=%s quantity=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
            )

            return self._rejection(
                reason="RISK_GUARD_NOT_CONFIGURED",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        risk_decision = (
            self.risk_guard.authorize_order()
        )

        if risk_decision.get(
            "allowed"
        ) is not True:
            return self._rejection(
                reason=risk_decision.get(
                    "reason",
                    "RISK_AUTHORIZATION_REJECTED",
                ),
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

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

            return self._error_result(
                reason="EXCHANGE_TIMEOUT",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
                error_type=type(exc).__name__,
            )
        except ConnectionError as exc:
            logger.exception(
                "Exchange connection error during order submission: "
                "symbol=%s side=%s quantity=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
            )

            return self._error_result(
                reason="EXCHANGE_CONNECTION_ERROR",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
                error_type=type(exc).__name__,
            )
        except Exception as exc:
            logger.exception(
                "Unexpected exchange adapter failure: "
                "symbol=%s side=%s quantity=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
            )

            return self._error_result(
                reason="EXCHANGE_ADAPTER_ERROR",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
                error_type=type(exc).__name__,
            )

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

            return self._error_result(
                reason="INVALID_EXCHANGE_RESPONSE",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
                error_type="InvalidExchangeResponse",
            )

        self._cache_idempotency_result(
            key=normalized_idempotency_key,
            fingerprint=fingerprint,
            response=result,
        )

        logger.info(
            "Live order delegated after validation, idempotency, "
            "safety and risk authorization: "
            "symbol=%s side=%s quantity=%s",
            normalized_symbol,
            normalized_side,
            normalized_quantity,
        )

        return deepcopy(
            result
        )

    def status(
        self,
    ) -> dict[str, Any]:
        self._purge_expired_idempotency_entries()

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
            "idempotency": {
                "enabled": True,
                "required": True,
                "cached_entries": len(
                    self._idempotency_cache
                ),
                "ttl_seconds": self.idempotency_ttl_seconds,
                "max_entries": self.idempotency_max_entries,
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
