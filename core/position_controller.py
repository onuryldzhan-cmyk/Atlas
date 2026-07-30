"""
============================================================
ATLAS AI POSITION CONTROLLER v6.0
============================================================

Institutional Position Lifecycle Engine


Responsibilities
----------------

- Open and close positions
- Maintain one active position per symbol
- Track current market prices
- Calculate percentage and monetary PnL
- Manage take-profit and stop-loss levels
- Support trailing-stop management
- Persist position state through ExecutionState
- Publish lifecycle events
- Provide ExecutionManager-compatible methods
- Maintain thread-safe position state


Architecture
------------

ExecutionManager
        |
        v
PositionController
        |
        +---- ExecutionState
        |
        +---- Audit
        |
        +---- EventBus


Lifecycle Ownership
-------------------

PositionController is the authoritative in-memory position registry.

PaperTrader may simulate fills and account balances, but it must not be
treated as the authoritative source for position lifecycle state.


============================================================
"""

from __future__ import annotations

import logging
import threading
import uuid

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


logger = logging.getLogger(
    "AtlasAI.PositionController"
)


class PositionStatus:
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PositionSide:
    BUY = "BUY"
    SELL = "SELL"
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Position:
    id: str
    symbol: str
    side: str
    entry_price: float
    amount: float

    confidence: float = 0.0
    strategy: str = "Atlas"
    risk: str = "MEDIUM"

    current_price: float = 0.0

    stop_loss: float | None = None
    take_profit: float | None = None
    trailing_stop: float | None = None

    highest_price: float = 0.0
    lowest_price: float = 0.0

    unrealized_pnl: float = 0.0
    unrealized_pnl_amount: float = 0.0

    realized_pnl: float = 0.0
    realized_pnl_amount: float = 0.0

    status: str = PositionStatus.OPEN

    opened_at: str = ""
    closed_at: str | None = None
    exit_price: float | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.opened_at:
            self.opened_at = datetime.now(
                UTC
            ).isoformat()

        self.symbol = str(
            self.symbol
        ).upper()

        self.side = str(
            self.side
        ).upper()

        self.entry_price = float(
            self.entry_price
        )

        self.current_price = float(
            self.current_price or self.entry_price
        )

        self.amount = float(
            self.amount
        )

        if self.highest_price <= 0:
            self.highest_price = self.entry_price

        if self.lowest_price <= 0:
            self.lowest_price = self.entry_price


class PositionController:
    """
    Authoritative position lifecycle controller.

    Supports both the native methods:

        open(trade)
        close(symbol, price)

    and the ExecutionManager compatibility methods:

        open_position(...)
        close_position(...)
    """

    VERSION = "6.0"

    NAME = "PositionController"

    def __init__(
        self,
        execution_state: Any = None,
        audit: Any = None,
        event_bus: Any = None,
    ) -> None:
        self.lock = threading.RLock()

        self.positions: dict[str, Position] = {}
        self.closed: list[Position] = []

        self.execution_state = execution_state
        self.audit = audit
        self.event_bus = event_bus

        self.open_count = 0
        self.close_count = 0
        self.update_count = 0
        self.rejected_count = 0
        self.error_count = 0

        self.last_error: dict[str, Any] | None = None

        logger.info(
            "Atlas Position Controller v%s initialized",
            self.VERSION,
        )

    # =========================================================
    # NATIVE OPEN
    # =========================================================

    def open(
        self,
        trade: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Open a new position from a normalized trade dictionary.
        """

        try:
            normalized = self._normalize_trade(
                trade
            )

            symbol = normalized[
                "symbol"
            ]

            with self.lock:
                if symbol in self.positions:
                    self.rejected_count += 1

                    existing = asdict(
                        self.positions[symbol]
                    )

                    return {
                        "status": "BLOCKED",
                        "success": False,
                        "reason": "POSITION_ALREADY_EXISTS",
                        "symbol": symbol,
                        "position": existing,
                    }

                position = Position(
                    id=str(
                        normalized.get(
                            "id"
                        )
                        or uuid.uuid4()
                    ),
                    symbol=symbol,
                    side=normalized[
                        "side"
                    ],
                    entry_price=normalized[
                        "price"
                    ],
                    amount=normalized[
                        "amount"
                    ],
                    confidence=normalized[
                        "confidence"
                    ],
                    strategy=normalized[
                        "strategy"
                    ],
                    risk=normalized[
                        "risk"
                    ],
                    current_price=normalized[
                        "price"
                    ],
                    stop_loss=normalized[
                        "stop_loss"
                    ],
                    take_profit=normalized[
                        "take_profit"
                    ],
                    trailing_stop=normalized[
                        "trailing_stop"
                    ],
                    highest_price=normalized[
                        "price"
                    ],
                    lowest_price=normalized[
                        "price"
                    ],
                    metadata=normalized[
                        "metadata"
                    ],
                )

                self.positions[
                    symbol
                ] = position

                self.open_count += 1

                position_data = asdict(
                    position
                )

                self._persist_open(
                    position_data
                )

                self._audit(
                    action="POSITION_OPENED",
                    data=position_data,
                )

                self._event(
                    name="POSITION_OPENED",
                    data=position_data,
                )

                logger.info(
                    "Position opened symbol=%s side=%s "
                    "price=%.8f amount=%.8f",
                    symbol,
                    position.side,
                    position.entry_price,
                    position.amount,
                )

                return {
                    "status": "OPENED",
                    "success": True,
                    "position": position_data,
                }

        except Exception as exc:
            self._record_error(
                phase="open",
                error=exc,
            )

            logger.exception(
                "Position open failed"
            )

            return {
                "status": "FAILED",
                "success": False,
                "reason": str(
                    exc
                ),
            }

    # =========================================================
    # EXECUTION MANAGER OPEN COMPATIBILITY
    # =========================================================

    def open_position(
        self,
        symbol: str,
        price: float,
        side: str = "LONG",
        amount: float = 0.0,
        confidence: float = 0.0,
        strategy: str = "Atlas",
        risk: str = "MEDIUM",
        stop_loss: float | None = None,
        take_profit: float | None = None,
        trailing_stop: float | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Compatibility entry point used by ExecutionManager.
        """

        return self.open(
            {
                "symbol": symbol,
                "price": price,
                "side": side,
                "amount": amount,
                "confidence": confidence,
                "strategy": strategy,
                "risk": risk,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "trailing_stop": trailing_stop,
                "metadata": metadata or {},
                **kwargs,
            }
        )

    # =========================================================
    # PRICE UPDATE
    # =========================================================

    def update_price(
        self,
        symbol: str,
        price: float,
    ) -> dict[str, Any] | None:
        """
        Update position price and recalculate unrealized PnL.
        """

        normalized_symbol = str(
            symbol
        ).upper()

        normalized_price = float(
            price
        )

        if normalized_price <= 0:
            raise ValueError(
                "Price must be greater than zero"
            )

        with self.lock:
            position = self.positions.get(
                normalized_symbol
            )

            if position is None:
                return None

            position.current_price = normalized_price

            position.highest_price = max(
                position.highest_price,
                normalized_price,
            )

            position.lowest_price = min(
                position.lowest_price,
                normalized_price,
            )

            position.unrealized_pnl = (
                self.calculate_pnl_percent(
                    position
                )
            )

            position.unrealized_pnl_amount = (
                self.calculate_pnl_amount(
                    position
                )
            )

            self._update_trailing_stop(
                position
            )

            self.update_count += 1

            position_data = asdict(
                position
            )

            self._persist_update(
                position_data
            )

            return position_data

    # =========================================================
    # PNL
    # =========================================================

    @staticmethod
    def calculate_pnl_percent(
        position: Position,
    ) -> float:
        """
        Calculate position return percentage.
        """

        if position.entry_price <= 0:
            return 0.0

        if position.side in {
            PositionSide.BUY,
            PositionSide.LONG,
        }:
            pnl = (
                (
                    position.current_price
                    - position.entry_price
                )
                / position.entry_price
            ) * 100

        else:
            pnl = (
                (
                    position.entry_price
                    - position.current_price
                )
                / position.entry_price
            ) * 100

        return round(
            pnl,
            4,
        )

    @staticmethod
    def calculate_pnl_amount(
        position: Position,
    ) -> float:
        """
        Calculate monetary PnL.

        Position amount is treated as quote-currency exposure.
        """

        if position.entry_price <= 0:
            return 0.0

        quantity = (
            position.amount
            / position.entry_price
        )

        if position.side in {
            PositionSide.BUY,
            PositionSide.LONG,
        }:
            pnl = (
                position.current_price
                - position.entry_price
            ) * quantity

        else:
            pnl = (
                position.entry_price
                - position.current_price
            ) * quantity

        return round(
            pnl,
            8,
        )

    def calculate_pnl(
        self,
        position: Position,
    ) -> float:
        """
        Backward-compatible percentage PnL method.
        """

        return self.calculate_pnl_percent(
            position
        )

    # =========================================================
    # EXIT LEVELS
    # =========================================================

    def set_exit(
        self,
        symbol: str,
        take_profit: float | None = None,
        stop_loss: float | None = None,
        trailing_stop: float | None = None,
    ) -> bool:
        normalized_symbol = str(
            symbol
        ).upper()

        with self.lock:
            position = self.positions.get(
                normalized_symbol
            )

            if position is None:
                return False

            position.take_profit = (
                float(
                    take_profit
                )
                if take_profit is not None
                else None
            )

            position.stop_loss = (
                float(
                    stop_loss
                )
                if stop_loss is not None
                else None
            )

            position.trailing_stop = (
                float(
                    trailing_stop
                )
                if trailing_stop is not None
                else position.trailing_stop
            )

            self._persist_update(
                asdict(
                    position
                )
            )

            return True

    # =========================================================
    # NATIVE CLOSE
    # =========================================================

    def close(
        self,
        symbol: str,
        price: float | None = None,
    ) -> dict[str, Any]:
        """
        Close a position using the supplied or latest known price.
        """

        normalized_symbol = str(
            symbol
        ).upper()

        with self.lock:
            position = self.positions.get(
                normalized_symbol
            )

            if position is None:
                self.rejected_count += 1

                return {
                    "status": "FAILED",
                    "success": False,
                    "reason": "POSITION_NOT_FOUND",
                    "symbol": normalized_symbol,
                }

            close_price = float(
                price
                if price is not None
                else position.current_price
            )

            if close_price <= 0:
                return {
                    "status": "FAILED",
                    "success": False,
                    "reason": "INVALID_CLOSE_PRICE",
                    "symbol": normalized_symbol,
                }

            self.positions.pop(
                normalized_symbol,
                None,
            )

            position.current_price = close_price
            position.exit_price = close_price

            position.realized_pnl = (
                self.calculate_pnl_percent(
                    position
                )
            )

            position.realized_pnl_amount = (
                self.calculate_pnl_amount(
                    position
                )
            )

            position.unrealized_pnl = 0.0
            position.unrealized_pnl_amount = 0.0

            position.status = PositionStatus.CLOSED

            position.closed_at = datetime.now(
                UTC
            ).isoformat()

            self.closed.append(
                position
            )

            self.close_count += 1

            position_data = asdict(
                position
            )

            self._persist_close(
                symbol=normalized_symbol,
                position=position_data,
            )

            self._audit(
                action="POSITION_CLOSED",
                data=position_data,
            )

            self._event(
                name="POSITION_CLOSED",
                data=position_data,
            )

            logger.info(
                "Position closed symbol=%s price=%.8f "
                "pnl_pct=%.4f pnl_amount=%.8f",
                normalized_symbol,
                close_price,
                position.realized_pnl,
                position.realized_pnl_amount,
            )

            return {
                "status": "CLOSED",
                "success": True,
                "position": position_data,
            }

    # =========================================================
    # EXECUTION MANAGER CLOSE COMPATIBILITY
    # =========================================================

    def close_position(
        self,
        symbol: str,
        price: float | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """
        Compatibility entry point used by ExecutionManager.
        """

        return self.close(
            symbol=symbol,
            price=price,
        )

    # =========================================================
    # AUTOMATIC EXIT CHECK
    # =========================================================

    def check_exit(
        self,
        symbol: str,
    ) -> str | None:
        normalized_symbol = str(
            symbol
        ).upper()

        with self.lock:
            position = self.positions.get(
                normalized_symbol
            )

            if position is None:
                return None

            price = position.current_price

            if position.side in {
                PositionSide.BUY,
                PositionSide.LONG,
            }:
                if (
                    position.take_profit is not None
                    and price >= position.take_profit
                ):
                    return "TAKE_PROFIT"

                if (
                    position.stop_loss is not None
                    and price <= position.stop_loss
                ):
                    return "STOP_LOSS"

            else:
                if (
                    position.take_profit is not None
                    and price <= position.take_profit
                ):
                    return "TAKE_PROFIT"

                if (
                    position.stop_loss is not None
                    and price >= position.stop_loss
                ):
                    return "STOP_LOSS"

            return None

    # =========================================================
    # TRAILING STOP
    # =========================================================

    @staticmethod
    def _update_trailing_stop(
        position: Position,
    ) -> None:
        """
        Move the stop only in the profitable direction.

        trailing_stop is interpreted as a percentage distance.
        Example: 0.5 means 0.5 percent.
        """

        if (
            position.trailing_stop is None
            or position.trailing_stop <= 0
        ):
            return

        distance = (
            position.trailing_stop
            / 100
        )

        if position.side in {
            PositionSide.BUY,
            PositionSide.LONG,
        }:
            candidate = (
                position.highest_price
                * (
                    1 - distance
                )
            )

            if (
                position.stop_loss is None
                or candidate > position.stop_loss
            ):
                position.stop_loss = candidate

        else:
            candidate = (
                position.lowest_price
                * (
                    1 + distance
                )
            )

            if (
                position.stop_loss is None
                or candidate < position.stop_loss
            ):
                position.stop_loss = candidate

    # =========================================================
    # QUERY
    # =========================================================

    def exists(
        self,
        symbol: str,
    ) -> bool:
        return (
            str(
                symbol
            ).upper()
            in self.positions
        )

    def get(
        self,
        symbol: str,
    ) -> dict[str, Any] | None:
        position = self.positions.get(
            str(
                symbol
            ).upper()
        )

        return (
            asdict(
                position
            )
            if position is not None
            else None
        )

    def get_all(
        self,
    ) -> list[dict[str, Any]]:
        with self.lock:
            return [
                asdict(
                    position
                )
                for position in self.positions.values()
            ]

    def get_closed(
        self,
    ) -> list[dict[str, Any]]:
        with self.lock:
            return [
                asdict(
                    position
                )
                for position in self.closed
            ]

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalize_trade(
        trade: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(
            trade,
            dict,
        ):
            raise TypeError(
                "Trade must be a dictionary"
            )

        symbol = str(
            trade.get(
                "symbol",
                "",
            )
        ).upper()

        if not symbol:
            raise ValueError(
                "Trade symbol is required"
            )

        price = float(
            trade.get(
                "price",
                trade.get(
                    "entry_price",
                    0,
                ),
            )
        )

        if price <= 0:
            raise ValueError(
                "Entry price must be greater than zero"
            )

        amount = float(
            trade.get(
                "amount",
                trade.get(
                    "allocation",
                    0,
                ),
            )
        )

        if amount < 0:
            raise ValueError(
                "Position amount cannot be negative"
            )

        side = str(
            trade.get(
                "side",
                "BUY",
            )
        ).upper()

        if side == "LONG":
            side = PositionSide.LONG

        elif side == "SHORT":
            side = PositionSide.SHORT

        elif side not in {
            PositionSide.BUY,
            PositionSide.SELL,
        }:
            side = PositionSide.BUY

        return {
            "id": trade.get(
                "id"
            ),
            "symbol": symbol,
            "side": side,
            "price": price,
            "amount": amount,
            "confidence": float(
                trade.get(
                    "confidence",
                    0,
                )
            ),
            "strategy": str(
                trade.get(
                    "strategy",
                    "Atlas",
                )
            ),
            "risk": str(
                trade.get(
                    "risk",
                    trade.get(
                        "risk_level",
                        "MEDIUM",
                    ),
                )
            ).upper(),
            "stop_loss": trade.get(
                "stop_loss"
            ),
            "take_profit": trade.get(
                "take_profit"
            ),
            "trailing_stop": trade.get(
                "trailing_stop"
            ),
            "metadata": dict(
                trade.get(
                    "metadata",
                    {},
                )
                or {}
            ),
        }

    # =========================================================
    # PERSISTENCE
    # =========================================================

    def _persist_open(
        self,
        position: dict[str, Any],
    ) -> None:
        if self.execution_state is None:
            return

        method = getattr(
            self.execution_state,
            "add",
            None,
        )

        if callable(
            method
        ):
            method(
                position
            )

    def _persist_update(
        self,
        position: dict[str, Any],
    ) -> None:
        if self.execution_state is None:
            return

        for method_name in (
            "update",
            "save_position",
            "set",
        ):
            method = getattr(
                self.execution_state,
                method_name,
                None,
            )

            if callable(
                method
            ):
                try:
                    method(
                        position
                    )
                    return
                except TypeError:
                    try:
                        method(
                            position[
                                "symbol"
                            ],
                            position,
                        )
                        return
                    except TypeError:
                        continue

    def _persist_close(
        self,
        *,
        symbol: str,
        position: dict[str, Any],
    ) -> None:
        if self.execution_state is None:
            return

        method = getattr(
            self.execution_state,
            "close",
            None,
        )

        if callable(
            method
        ):
            method(
                symbol,
                position,
            )

    # =========================================================
    # AUDIT
    # =========================================================

    def _audit(
        self,
        *,
        action: str,
        data: dict[str, Any],
    ) -> None:
        if self.audit is None:
            return

        for method_name in (
            "record",
            "write",
            "log",
            "add",
        ):
            method = getattr(
                self.audit,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                method(
                    action,
                    data,
                )
                return

            except TypeError:
                try:
                    method(
                        {
                            "action": action,
                            "data": data,
                            "timestamp": datetime.now(
                                UTC
                            ).isoformat(),
                        }
                    )
                    return

                except TypeError:
                    continue

            except Exception as exc:
                logger.warning(
                    "Position audit failed: %s",
                    exc,
                )
                return

    # =========================================================
    # EVENT
    # =========================================================

    def _event(
        self,
        *,
        name: str,
        data: dict[str, Any],
    ) -> None:
        if self.event_bus is None:
            return

        publish = getattr(
            self.event_bus,
            "publish",
            None,
        )

        if callable(
            publish
        ):
            try:
                publish(
                    name,
                    data,
                )

            except TypeError:
                try:
                    publish(
                        event_type=name,
                        payload=data,
                    )

                except Exception as exc:
                    logger.warning(
                        "Position event failed: %s",
                        exc,
                    )

            except Exception as exc:
                logger.warning(
                    "Position event failed: %s",
                    exc,
                )

    # =========================================================
    # ERROR
    # =========================================================

    def _record_error(
        self,
        *,
        phase: str,
        error: Exception,
    ) -> None:
        self.error_count += 1

        self.last_error = {
            "timestamp": datetime.now(
                UTC
            ).isoformat(),
            "phase": phase,
            "type": type(
                error
            ).__name__,
            "message": str(
                error
            ),
        }

    # =========================================================
    # STATUS
    # =========================================================

    def status(
        self,
    ) -> dict[str, Any]:
        with self.lock:
            unrealized_pnl = sum(
                position.unrealized_pnl_amount
                for position in self.positions.values()
            )

            realized_pnl = sum(
                position.realized_pnl_amount
                for position in self.closed
            )

            total_exposure = sum(
                position.amount
                for position in self.positions.values()
            )

            return {
                "name": self.NAME,
                "version": self.VERSION,
                "active": len(
                    self.positions
                ),
                "closed": len(
                    self.closed
                ),
                "symbols": list(
                    self.positions.keys()
                ),
                "total_exposure": round(
                    total_exposure,
                    8,
                ),
                "unrealized_pnl": round(
                    unrealized_pnl,
                    8,
                ),
                "realized_pnl": round(
                    realized_pnl,
                    8,
                ),
                "open_count": self.open_count,
                "close_count": self.close_count,
                "update_count": self.update_count,
                "rejected_count": self.rejected_count,
                "error_count": self.error_count,
                "last_error": self.last_error,
            }

    def health(
        self,
    ) -> dict[str, Any]:
        return {
            "healthy": self.error_count == 0,
            "version": self.VERSION,
            "active_positions": len(
                self.positions
            ),
            "errors": self.error_count,
        }


PositionManager = PositionController