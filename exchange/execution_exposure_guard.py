"""
ATLAS EXECUTION EXPOSURE GUARD v1.0

Order-level capital and portfolio exposure protection.

Enforced limits
---------------
- Maximum order notional
- Maximum exposure per symbol
- Maximum total portfolio exposure
- Maximum open position count
- Minimum cash reserve
- Fail-closed portfolio snapshot validation

This guard does not place orders and does not permanently halt trading.
Every authorization decision is evaluated against the latest valid
portfolio snapshot.
"""

from __future__ import annotations

import math
import threading

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ExposureDecision:
    allowed: bool
    status: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "reason": self.reason,
        }


class ExecutionExposureGuard:
    VERSION = "1.0"

    def __init__(
        self,
        *,
        portfolio_equity: float,
        max_order_notional: float,
        max_symbol_exposure: float,
        max_total_exposure: float,
        max_open_positions: int,
        minimum_cash_reserve: float,
    ) -> None:
        self.portfolio_equity = self._require_positive_number(
            portfolio_equity,
            field_name="portfolio_equity",
        )

        self.max_order_notional = self._require_positive_number(
            max_order_notional,
            field_name="max_order_notional",
        )

        self.max_symbol_exposure = self._require_positive_number(
            max_symbol_exposure,
            field_name="max_symbol_exposure",
        )

        self.max_total_exposure = self._require_positive_number(
            max_total_exposure,
            field_name="max_total_exposure",
        )

        self.max_open_positions = self._require_positive_integer(
            max_open_positions,
            field_name="max_open_positions",
        )

        self.minimum_cash_reserve = self._require_non_negative_number(
            minimum_cash_reserve,
            field_name="minimum_cash_reserve",
        )

        if self.minimum_cash_reserve > self.portfolio_equity:
            raise ValueError(
                "minimum_cash_reserve cannot exceed portfolio_equity"
            )

        if self.max_order_notional > self.portfolio_equity:
            raise ValueError(
                "max_order_notional cannot exceed portfolio_equity"
            )

        if self.max_symbol_exposure > self.portfolio_equity:
            raise ValueError(
                "max_symbol_exposure cannot exceed portfolio_equity"
            )

        if self.max_total_exposure > self.portfolio_equity:
            raise ValueError(
                "max_total_exposure cannot exceed portfolio_equity"
            )

        self._portfolio_available = False

        self._cash = 0.0
        self._total_exposure = 0.0
        self._symbol_exposures: dict[str, float] = {}
        self._open_positions = 0

        # Task 010 (registry v5.94): notional held by open BUY orders, keyed by client order id.
        # A reservation is taken atomically with its own check against the snapshot AND every
        # other open reservation, and released when the order is terminal (filled, cancelled,
        # rejected, expired) or proven never dispatched. Fills reach the snapshot only through
        # update_portfolio, as before.
        self._lock = threading.RLock()
        self._reservations: dict[str, tuple[str, float, bool]] = {}

    @staticmethod
    def _normalize_number(
        value: Any,
    ) -> float | None:
        if isinstance(
            value,
            bool,
        ):
            return None

        try:
            normalized = float(
                value
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

        return normalized

    @classmethod
    def _require_positive_number(
        cls,
        value: Any,
        *,
        field_name: str,
    ) -> float:
        normalized = cls._normalize_number(
            value
        )

        if (
            normalized is None
            or normalized <= 0
        ):
            raise ValueError(
                f"{field_name} must be a positive finite number"
            )

        return normalized

    @classmethod
    def _require_non_negative_number(
        cls,
        value: Any,
        *,
        field_name: str,
    ) -> float:
        normalized = cls._normalize_number(
            value
        )

        if (
            normalized is None
            or normalized < 0
        ):
            raise ValueError(
                f"{field_name} must be a non-negative finite number"
            )

        return normalized

    @staticmethod
    def _require_positive_integer(
        value: Any,
        *,
        field_name: str,
    ) -> int:
        if isinstance(
            value,
            bool,
        ):
            raise ValueError(
                f"{field_name} must be a positive integer"
            )

        try:
            normalized = int(
                value
            )
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

    @staticmethod
    def _normalize_open_positions(
        value: Any,
    ) -> int | None:
        if isinstance(
            value,
            bool,
        ):
            return None

        try:
            normalized_float = float(
                value
            )
        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            return None

        if (
            not math.isfinite(normalized_float)
            or normalized_float < 0
            or not normalized_float.is_integer()
        ):
            return None

        return int(
            normalized_float
        )

    @classmethod
    def _normalize_symbol_exposures(
        cls,
        value: Any,
    ) -> dict[str, float] | None:
        if not isinstance(
            value,
            Mapping,
        ):
            return None

        normalized: dict[str, float] = {}

        for raw_symbol, raw_exposure in value.items():
            symbol = str(
                raw_symbol
                if raw_symbol is not None
                else ""
            ).strip().upper()

            exposure = cls._normalize_number(
                raw_exposure
            )

            if (
                not symbol
                or exposure is None
                or exposure < 0
            ):
                return None

            normalized[symbol] = exposure

        return normalized

    def update_portfolio(
        self,
        *,
        cash: Any,
        total_exposure: Any,
        symbol_exposures: Any,
        open_positions: Any,
    ) -> dict[str, Any]:
        with self._lock:
            return self._update_portfolio(
                cash=cash,
                total_exposure=total_exposure,
                symbol_exposures=symbol_exposures,
                open_positions=open_positions,
            )

    def _update_portfolio(
        self,
        *,
        cash: Any,
        total_exposure: Any,
        symbol_exposures: Any,
        open_positions: Any,
    ) -> dict[str, Any]:
        normalized_cash = self._normalize_number(
            cash
        )

        normalized_total_exposure = self._normalize_number(
            total_exposure
        )

        normalized_symbol_exposures = (
            self._normalize_symbol_exposures(
                symbol_exposures
            )
        )

        normalized_open_positions = (
            self._normalize_open_positions(
                open_positions
            )
        )

        snapshot_valid = (
            normalized_cash is not None
            and normalized_cash >= 0
            and normalized_total_exposure is not None
            and normalized_total_exposure >= 0
            and normalized_symbol_exposures is not None
            and normalized_open_positions is not None
        )

        if not snapshot_valid:
            self._portfolio_available = False

            return {
                "accepted": False,
                "status": "REJECTED",
                "reason": "INVALID_PORTFOLIO_SNAPSHOT",
            }

        if (
            normalized_cash
            + normalized_total_exposure
            > self.portfolio_equity
            + 1e-9
        ):
            self._portfolio_available = False

            return {
                "accepted": False,
                "status": "REJECTED",
                "reason": "INVALID_PORTFOLIO_SNAPSHOT",
            }

        if any(
            exposure > normalized_total_exposure + 1e-9
            for exposure in normalized_symbol_exposures.values()
        ):
            self._portfolio_available = False

            return {
                "accepted": False,
                "status": "REJECTED",
                "reason": "INVALID_PORTFOLIO_SNAPSHOT",
            }

        self._cash = normalized_cash
        self._total_exposure = normalized_total_exposure
        self._symbol_exposures = normalized_symbol_exposures
        self._open_positions = normalized_open_positions
        self._portfolio_available = True

        return {
            "accepted": True,
            "status": "RECORDED",
            "reason": "PORTFOLIO_SNAPSHOT_UPDATED",
        }

    def authorize_order(
        self,
        *,
        symbol: Any,
        order_notional: Any,
        opens_new_position: Any,
    ) -> dict[str, Any]:
        with self._lock:
            return self._authorize(
                symbol=symbol,
                order_notional=order_notional,
                opens_new_position=opens_new_position,
            )

    def reserve(
        self,
        key: str,
        *,
        symbol: Any,
        order_notional: Any,
        opens_new_position: Any,
    ) -> dict[str, Any]:
        """Task 010: check a BUY against the snapshot plus every open reservation, then hold it."""
        with self._lock:
            if key in self._reservations:
                return ExposureDecision(allowed=True, status="AUTHORIZED", reason="RESERVATION_HELD").to_dict()
            normalized_symbol = str(symbol if symbol is not None else "").strip().upper()
            held = [entry for entry in self._reservations.values()]
            decision = self._authorize(
                symbol=symbol,
                order_notional=order_notional,
                opens_new_position=opens_new_position,
                reserved_symbol=sum(n for s, n, _ in held if s == normalized_symbol),
                reserved_total=sum(n for _, n, _ in held),
                reserved_positions=sum(1 for _, _, opens in held if opens),
            )
            if decision.get("allowed") is True:
                self._reservations[key] = (normalized_symbol, float(self._normalize_number(order_notional)),
                                           opens_new_position)
            return decision

    def restore_reservation(
        self,
        key: str,
        *,
        symbol: Any,
        order_notional: Any,
        opens_new_position: Any,
    ) -> None:
        """Task 010: re-hold an order that was open before a restart (no check: it may already be live)."""
        normalized_symbol = str(symbol if symbol is not None else "").strip().upper()
        notional = self._normalize_number(order_notional)
        if not normalized_symbol or notional is None or notional <= 0 or not isinstance(opens_new_position, bool):
            raise ValueError("an open order's reservation cannot be restored from invalid fields")
        with self._lock:
            self._reservations[key] = (normalized_symbol, float(notional), opens_new_position)

    def release(self, key: str) -> bool:
        """Task 010: release an order's reservation (terminal or never dispatched); idempotent."""
        with self._lock:
            return self._reservations.pop(key, None) is not None

    def reservations(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {key: {"symbol": s, "order_notional": n, "opens_new_position": o}
                    for key, (s, n, o) in self._reservations.items()}

    def _authorize(
        self,
        *,
        symbol: Any,
        order_notional: Any,
        opens_new_position: Any,
        reserved_symbol: float = 0.0,
        reserved_total: float = 0.0,
        reserved_positions: int = 0,
    ) -> dict[str, Any]:
        if not self._portfolio_available:
            return ExposureDecision(
                allowed=False,
                status="REJECTED",
                reason="PORTFOLIO_STATE_UNAVAILABLE",
            ).to_dict()

        normalized_symbol = str(
            symbol
            if symbol is not None
            else ""
        ).strip().upper()

        normalized_notional = self._normalize_number(
            order_notional
        )

        if (
            not normalized_symbol
            or normalized_notional is None
            or normalized_notional <= 0
        ):
            return ExposureDecision(
                allowed=False,
                status="REJECTED",
                reason="INVALID_ORDER_NOTIONAL",
            ).to_dict()

        if not isinstance(
            opens_new_position,
            bool,
        ):
            return ExposureDecision(
                allowed=False,
                status="REJECTED",
                reason="INVALID_POSITION_INTENT",
            ).to_dict()

        if normalized_notional > self.max_order_notional:
            return ExposureDecision(
                allowed=False,
                status="REJECTED",
                reason="MAX_ORDER_NOTIONAL_EXCEEDED",
            ).to_dict()

        current_symbol_exposure = self._symbol_exposures.get(
            normalized_symbol,
            0.0,
        )

        projected_symbol_exposure = (
            current_symbol_exposure
            + reserved_symbol
            + normalized_notional
        )

        if projected_symbol_exposure > self.max_symbol_exposure:
            return ExposureDecision(
                allowed=False,
                status="REJECTED",
                reason="MAX_SYMBOL_EXPOSURE_EXCEEDED",
            ).to_dict()

        projected_total_exposure = (
            self._total_exposure
            + reserved_total
            + normalized_notional
        )

        if projected_total_exposure > self.max_total_exposure:
            return ExposureDecision(
                allowed=False,
                status="REJECTED",
                reason="MAX_TOTAL_EXPOSURE_EXCEEDED",
            ).to_dict()

        if (
            opens_new_position
            and self._open_positions + reserved_positions >= self.max_open_positions
        ):
            return ExposureDecision(
                allowed=False,
                status="REJECTED",
                reason="MAX_OPEN_POSITIONS_REACHED",
            ).to_dict()

        projected_cash = (
            self._cash
            - reserved_total
            - normalized_notional
        )

        if projected_cash < self.minimum_cash_reserve:
            return ExposureDecision(
                allowed=False,
                status="REJECTED",
                reason="MINIMUM_CASH_RESERVE_VIOLATION",
            ).to_dict()

        return ExposureDecision(
            allowed=True,
            status="AUTHORIZED",
            reason="EXPOSURE_LIMITS_HEALTHY",
        ).to_dict()

    def status(
        self,
    ) -> dict[str, Any]:
        with self._lock:
            reserved = list(self._reservations.values())
        return {
            "reservations": len(reserved),
            "reserved_notional": sum(n for _, n, _ in reserved),
            "name": "ExecutionExposureGuard",
            "version": self.VERSION,
            "portfolio_available": self._portfolio_available,
            "portfolio_equity": self.portfolio_equity,
            "cash": (
                self._cash
                if self._portfolio_available
                else None
            ),
            "total_exposure": (
                self._total_exposure
                if self._portfolio_available
                else None
            ),
            "open_positions": (
                self._open_positions
                if self._portfolio_available
                else None
            ),
            "tracked_symbols": (
                len(self._symbol_exposures)
                if self._portfolio_available
                else 0
            ),
            "max_order_notional": self.max_order_notional,
            "max_symbol_exposure": self.max_symbol_exposure,
            "max_total_exposure": self.max_total_exposure,
            "max_open_positions": self.max_open_positions,
            "minimum_cash_reserve": self.minimum_cash_reserve,
        }
