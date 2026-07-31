"""
ATLAS EXCHANGE MANAGER v2.9

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
- Concurrent in-flight requests are coordinated to prevent duplicate adapter submissions.
- Indeterminate outcome quarantine guarantees fail-closed protection on uncertain order submission.
- Fingerprints include normalized economic and exposure intent.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time

from collections import OrderedDict
from copy import deepcopy
from typing import Any, Callable

from exchange.adapters.binance_global import BinanceGlobalExchange
from exchange.adapters.binance_tr import BinanceTRExchange
from exchange.execution_exposure_guard import (
    ExecutionExposureGuard,
)
from exchange.execution_risk_guard import ExecutionRiskGuard
from exchange.execution_safety_gate import ExecutionSafetyGate
from exchange.persistent_idempotency_store import (
    PersistentIdempotencyStore,
)


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
    VERSION = "2.9"

    def __init__(
        self,
        exchange_name: str = "binance_global",
        *,
        exchange: Any | None = None,
        safety_gate: ExecutionSafetyGate | None = None,
        risk_guard: ExecutionRiskGuard | None = None,
        exposure_guard: ExecutionExposureGuard | None = None,
        idempotency_ttl_seconds: float = 900.0,
        idempotency_max_entries: int = 10_000,
        monotonic_provider: Callable[[], float] | None = None,
        idempotency_store_path: str | Path | None = None,
        wall_time_provider: Callable[[], float] | None = None,
        in_flight_wait_timeout_seconds: float = 30.0,
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
        self.exposure_guard = exposure_guard

        self.idempotency_ttl_seconds = self._normalize_positive_float(
            idempotency_ttl_seconds,
            field_name="idempotency_ttl_seconds",
        )

        self.idempotency_max_entries = self._normalize_positive_int(
            idempotency_max_entries,
            field_name="idempotency_max_entries",
        )

        self.in_flight_wait_timeout_seconds = (
            self._normalize_positive_float(
                in_flight_wait_timeout_seconds,
                field_name="in_flight_wait_timeout_seconds",
            )
        )

        self._idempotency_lock = threading.RLock()

        self._in_flight_requests: dict[
            str,
            dict[str, Any],
        ] = {}

        self._monotonic_provider = (
            monotonic_provider
            if monotonic_provider is not None
            else time.monotonic
        )

        self._wall_time_provider = (
            wall_time_provider
            if wall_time_provider is not None
            else time.time
        )

        self._idempotency_cache: OrderedDict[
            str,
            dict[str, Any],
        ] = OrderedDict()

        self._quarantined_keys: OrderedDict[
            str,
            dict[str, Any],
        ] = OrderedDict()

        self._idempotency_store = (
            PersistentIdempotencyStore(
                path=idempotency_store_path,
                ttl_seconds=self.idempotency_ttl_seconds,
                max_entries=self.idempotency_max_entries,
                time_provider=self._wall_time_provider,
            )
            if idempotency_store_path is not None
            else None
        )

        self._load_persistent_idempotency_entries()

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
        order_notional: float,
        opens_new_position: bool,
    ) -> tuple[str, str, float, float, bool]:
        return (
            symbol,
            side,
            quantity,
            order_notional,
            opens_new_position,
        )

    def _load_persistent_idempotency_entries(
        self,
    ) -> None:
        if self._idempotency_store is None:
            return

        entries = self._idempotency_store.load()

        if not self._idempotency_store.available:
            return

        monotonic_now = float(
            self._monotonic_provider()
        )

        wall_now = float(
            self._wall_time_provider()
        )

        for key, entry in entries.items():
            remaining_ttl = max(
                0.0,
                float(entry["expires_at"]) - wall_now,
            )

            if remaining_ttl <= 0:
                continue

            age = max(
                0.0,
                self.idempotency_ttl_seconds
                - remaining_ttl,
            )

            self._idempotency_cache[key] = {
                "fingerprint": entry["fingerprint"],
                "response": deepcopy(
                    entry["response"]
                ),
                "created_at": monotonic_now - age,
            }

    def _persist_idempotency_entries(
        self,
    ) -> bool:
        if self._idempotency_store is None:
            return True

        monotonic_now = float(
            self._monotonic_provider()
        )

        wall_now = float(
            self._wall_time_provider()
        )

        entries: dict[str, dict[str, Any]] = {}

        for key, entry in self._idempotency_cache.items():
            age = max(
                0.0,
                monotonic_now
                - float(entry["created_at"]),
            )

            remaining_ttl = max(
                0.0,
                self.idempotency_ttl_seconds - age,
            )

            if remaining_ttl <= 0:
                continue

            entries[key] = {
                "fingerprint": entry["fingerprint"],
                "response": deepcopy(
                    entry["response"]
                ),
                "expires_at": wall_now + remaining_ttl,
            }

        return self._idempotency_store.save(
            entries
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
        fingerprint: tuple[str, str, float, float, bool],
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
        fingerprint: tuple[str, str, float, float, bool],
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

        self._persist_idempotency_entries()

    def _purge_expired_quarantine_entries(
        self,
    ) -> None:
        now = float(
            self._monotonic_provider()
        )

        expired_keys = [
            key
            for key, entry in self._quarantined_keys.items()
            if (
                now - float(entry["created_at"])
                >= self.idempotency_ttl_seconds
            )
        ]

        for key in expired_keys:
            self._quarantined_keys.pop(
                key,
                None,
            )

    def _quarantine_key(
        self,
        *,
        key: str,
        fingerprint: tuple[str, str, float, float, bool],
        reason: str = "IDEMPOTENCY_OUTCOME_UNKNOWN",
        status_code: str = "REJECTED",
    ) -> None:
        self._purge_expired_quarantine_entries()

        self._quarantined_keys[key] = {
            "fingerprint": fingerprint,
            "reason": reason,
            "status_code": status_code,
            "created_at": float(
                self._monotonic_provider()
            ),
        }

        self._quarantined_keys.move_to_end(
            key
        )

        while (
            len(self._quarantined_keys)
            > self.idempotency_max_entries
        ):
            self._quarantined_keys.popitem(
                last=False
            )

    def _lookup_quarantined_entry(
        self,
        *,
        key: str,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any] | None:
        self._purge_expired_quarantine_entries()

        entry = self._quarantined_keys.get(
            key
        )

        if entry is None:
            return None

        self._quarantined_keys.move_to_end(
            key
        )

        reason = str(
            entry.get(
                "reason",
                "IDEMPOTENCY_OUTCOME_UNKNOWN",
            )
        )

        status_code = str(
            entry.get(
                "status_code",
                "REJECTED",
            )
        )

        if status_code == "ERROR":
            return self._error_result(
                reason=reason,
                symbol=symbol,
                side=side,
                quantity=quantity,
                error_type="IdempotencyLeaderAborted",
            )

        return self._rejection(
            reason=reason,
            symbol=symbol,
            side=side,
            quantity=quantity,
        )

    def _coordinate_in_flight_request(
        self,
        *,
        key: str,
        fingerprint: tuple[str, str, float, float, bool],
        symbol: str,
        side: str,
        quantity: float,
    ) -> tuple[
        bool,
        dict[str, Any] | None,
        dict[str, Any] | None,
    ]:
        with self._idempotency_lock:
            quarantined_result = self._lookup_quarantined_entry(
                key=key,
                symbol=symbol,
                side=side,
                quantity=quantity,
            )

            if quarantined_result is not None:
                return (
                    False,
                    quarantined_result,
                    None,
                )

            cached_result = self._lookup_idempotency_entry(
                key=key,
                fingerprint=fingerprint,
                symbol=symbol,
                side=side,
                quantity=quantity,
            )

            if cached_result is not None:
                return (
                    False,
                    cached_result,
                    None,
                )

            existing = self._in_flight_requests.get(
                key
            )

            if existing is None:
                entry: dict[str, Any] = {
                    "fingerprint": fingerprint,
                    "event": threading.Event(),
                    "response": None,
                }

                self._in_flight_requests[key] = entry

                return (
                    True,
                    None,
                    entry,
                )

            if existing.get(
                "fingerprint"
            ) != fingerprint:
                return (
                    False,
                    self._rejection(
                        reason="IDEMPOTENCY_KEY_CONFLICT",
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                    ),
                    None,
                )

            entry = existing
            event = entry["event"]

        completed = event.wait(
            timeout=self.in_flight_wait_timeout_seconds
        )

        if not completed:
            return (
                False,
                self._rejection(
                    reason=(
                        "IDEMPOTENCY_REQUEST_IN_FLIGHT_TIMEOUT"
                    ),
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                ),
                None,
            )

        response = entry.get(
            "response"
        )

        if not isinstance(
            response,
            dict,
        ):
            return (
                False,
                self._error_result(
                    reason="IDEMPOTENCY_IN_FLIGHT_RESULT_UNAVAILABLE",
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    error_type="InFlightResultUnavailable",
                ),
                None,
            )

        return (
            False,
            deepcopy(response),
            None,
        )

    def _complete_in_flight_request(
        self,
        *,
        key: str,
        entry: dict[str, Any],
        response: dict[str, Any],
    ) -> dict[str, Any]:
        result = deepcopy(
            response
        )

        with self._idempotency_lock:
            entry["response"] = deepcopy(
                result
            )

            current = self._in_flight_requests.get(
                key
            )

            if current is entry:
                self._in_flight_requests.pop(
                    key,
                    None,
                )

            event = entry.get(
                "event"
            )

            if isinstance(
                event,
                threading.Event,
            ):
                event.set()

        return result

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: Any,
        *,
        idempotency_key: Any = None,
        order_notional: Any = None,
        opens_new_position: Any = None,
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

        if (
            self._idempotency_store is not None
            and not self._idempotency_store.available
        ):
            return self._rejection(
                reason="IDEMPOTENCY_STORE_UNAVAILABLE",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        normalized_order_notional = (
            self._normalize_quantity(
                order_notional
            )
        )

        if normalized_order_notional is None:
            return self._rejection(
                reason="INVALID_ORDER_NOTIONAL",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        if not isinstance(
            opens_new_position,
            bool,
        ):
            return self._rejection(
                reason="INVALID_POSITION_INTENT",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        normalized_opens_new_position = (
            opens_new_position
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
            order_notional=normalized_order_notional,
            opens_new_position=(
                normalized_opens_new_position
            ),
        )

        with self._idempotency_lock:
            quarantined_result = self._lookup_quarantined_entry(
                key=normalized_idempotency_key,
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

            if quarantined_result is not None:
                return quarantined_result

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

        if self.exposure_guard is None:
            logger.error(
                "Live order rejected because exposure guard is missing: "
                "symbol=%s side=%s quantity=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
            )

            return self._rejection(
                reason="EXPOSURE_GUARD_NOT_CONFIGURED",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        exposure_decision = (
            self.exposure_guard.authorize_order(
                symbol=normalized_symbol,
                order_notional=normalized_order_notional,
                opens_new_position=(
                    normalized_opens_new_position
                ),
            )
        )

        if exposure_decision.get(
            "allowed"
        ) is not True:
            rejection = self._rejection(
                reason=exposure_decision.get(
                    "reason",
                    "EXPOSURE_AUTHORIZATION_REJECTED",
                ),
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

            logger.warning(
                "Live order rejected by exposure guard: "
                "symbol=%s side=%s quantity=%s reason=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
                rejection["reason"],
            )

            return rejection

        is_leader, coordinated_result, in_flight_entry = (
            self._coordinate_in_flight_request(
                key=normalized_idempotency_key,
                fingerprint=fingerprint,
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )
        )

        if not is_leader:
            if coordinated_result is None:
                return self._error_result(
                    reason="IDEMPOTENCY_COORDINATION_FAILED",
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                    error_type="IdempotencyCoordinationError",
                )

            return coordinated_result

        if in_flight_entry is None:
            return self._error_result(
                reason="IDEMPOTENCY_COORDINATION_FAILED",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
                error_type="IdempotencyCoordinationError",
            )

        leader_completed = False
        try:
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

                error_result = self._error_result(
                    reason="EXCHANGE_TIMEOUT",
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                    error_type=type(exc).__name__,
                )

                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=error_result,
                )
                leader_completed = True
                return completed_result
            except ConnectionError as exc:
                logger.exception(
                    "Exchange connection error during order submission: "
                    "symbol=%s side=%s quantity=%s",
                    normalized_symbol,
                    normalized_side,
                    normalized_quantity,
                )

                error_result = self._error_result(
                    reason="EXCHANGE_CONNECTION_ERROR",
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                    error_type=type(exc).__name__,
                )

                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=error_result,
                )
                leader_completed = True
                return completed_result
            except Exception as exc:
                logger.exception(
                    "Unexpected exchange adapter failure: "
                    "symbol=%s side=%s quantity=%s",
                    normalized_symbol,
                    normalized_side,
                    normalized_quantity,
                )

                error_result = self._error_result(
                    reason="EXCHANGE_ADAPTER_ERROR",
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                    error_type=type(exc).__name__,
                )

                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=error_result,
                )
                leader_completed = True
                return completed_result

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

                error_result = self._error_result(
                    reason="INVALID_EXCHANGE_RESPONSE",
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                    error_type="InvalidExchangeResponse",
                )

                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=error_result,
                )
                leader_completed = True
                return completed_result

            try:
                with self._idempotency_lock:
                    self._cache_idempotency_result(
                        key=normalized_idempotency_key,
                        fingerprint=fingerprint,
                        response=result,
                    )

                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=result,
                )
                leader_completed = True

                logger.info(
                    "Live order delegated after validation, idempotency, "
                    "safety and risk authorization: "
                    "symbol=%s side=%s quantity=%s",
                    normalized_symbol,
                    normalized_side,
                    normalized_quantity,
                )

                return completed_result

            except Exception as finalization_exc:
                logger.exception(
                    "Idempotency finalization/caching failure after exchange order submission: "
                    "symbol=%s side=%s quantity=%s",
                    normalized_symbol,
                    normalized_side,
                    normalized_quantity,
                )

                with self._idempotency_lock:
                    self._quarantine_key(
                        key=normalized_idempotency_key,
                        fingerprint=fingerprint,
                    )

                finalization_error_result = self._error_result(
                    reason="IDEMPOTENCY_FINALIZATION_FAILED",
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                    error_type=type(finalization_exc).__name__,
                )

                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=finalization_error_result,
                )
                leader_completed = True
                return finalization_error_result

        except BaseException as base_exc:
            if not leader_completed:
                with self._idempotency_lock:
                    self._quarantine_key(
                        key=normalized_idempotency_key,
                        fingerprint=fingerprint,
                        reason="IDEMPOTENCY_LEADER_ABORTED",
                        status_code="ERROR",
                    )

                abort_error_result = self._error_result(
                    reason="IDEMPOTENCY_LEADER_ABORTED",
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                    error_type=type(base_exc).__name__,
                )

                self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=abort_error_result,
                )
            raise
        finally:
            with self._idempotency_lock:
                current = self._in_flight_requests.get(
                    normalized_idempotency_key
                )
                if current is in_flight_entry:
                    self._in_flight_requests.pop(
                        normalized_idempotency_key,
                        None,
                    )
                    event = in_flight_entry.get("event")
                    if isinstance(event, threading.Event) and not event.is_set():
                        event.set()

    def status(
        self,
    ) -> dict[str, Any]:
        with self._idempotency_lock:
            self._purge_expired_idempotency_entries()
            self._purge_expired_quarantine_entries()

            cached_entries = len(
                self._idempotency_cache
            )

            in_flight_entries = len(
                self._in_flight_requests
            )

            indeterminate_entries = len(
                self._quarantined_keys
            )

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
                "cached_entries": cached_entries,
                "in_flight_entries": in_flight_entries,
                "indeterminate_entries": indeterminate_entries,
                "in_flight_wait_timeout_seconds": (
                    self.in_flight_wait_timeout_seconds
                ),
                "ttl_seconds": self.idempotency_ttl_seconds,
                "max_entries": self.idempotency_max_entries,
                "persistent": (
                    self._idempotency_store is not None
                ),
                "store_available": (
                    self._idempotency_store.available
                    if self._idempotency_store is not None
                    else None
                ),
                "store_error_type": (
                    self._idempotency_store.error_type
                    if self._idempotency_store is not None
                    else None
                ),
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
            "exposure_guard": (
                self.exposure_guard.status()
                if self.exposure_guard is not None
                else {
                    "configured": False,
                    "status": "FAIL_CLOSED",
                }
            ),
            "exchange": exchange_status,
        }
