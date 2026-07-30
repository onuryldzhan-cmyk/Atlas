"""
============================================================
ATLAS EXECUTION MANAGER v28.0
============================================================

Institutional Execution Orchestrator

Architecture
------------

Atlas Brain
    |
Decision Adapter
    |
Execution Manager
    |
    +-------------------+
    |                   |
Risk Validation    Capital Allocation
    |                   |
    +-------------------+
            |
Position Controller
            |
Paper / Live Execution
            |
Event Bus

Responsibilities
----------------

- Accept canonical Atlas decisions
- Defensively normalize execution fields
- Validate symbol, action, price and confidence
- Enforce confidence thresholds
- Apply position and risk controls
- Allocate paper-trading capital
- Coordinate PaperTrader
- Coordinate PositionController
- Block live execution by default
- Publish structured execution events
- Maintain execution history and diagnostics

Confidence Contract
-------------------

ExecutionManager uses percentage confidence:

    0.706  -> 70.6
    70.6   -> 70.6
    "70.6%" -> 70.6

============================================================
"""

from __future__ import annotations

import logging

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


logger = logging.getLogger(
    "AtlasAI.ExecutionManager"
)


# ============================================================
# INTERNAL REQUEST
# ============================================================


@dataclass(slots=True)
class ExecutionRequest:
    """
    Canonical request used internally by ExecutionManager.
    """

    symbol: str
    action: str
    price: float
    confidence: float
    timestamp: str
    strategy: str = "Atlas"
    risk_level: str = "MEDIUM"
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(
            self
        )


# ============================================================
# INTERNAL RESULT
# ============================================================


@dataclass(slots=True)
class ExecutionResult:
    """
    Canonical result returned by ExecutionManager.
    """

    status: str
    symbol: str
    action: str
    mode: str
    timestamp: str
    message: str = ""
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(
            self
        )


# ============================================================
# EXECUTION MANAGER
# ============================================================


class ExecutionManager:
    """
    Validate and coordinate Atlas execution requests.
    """

    VERSION = "28.0"
    NAME = "ExecutionManager"

    MIN_CONFIDENCE = 60.0

    VALID_ACTIONS = {
        "BUY",
        "SELL",
    }

    NON_EXECUTION_ACTIONS = {
        "HOLD",
        "WAIT",
        "NEUTRAL",
        "NONE",
        "NO_ACTION",
    }

    def __init__(
        self,
        capital_manager: Any | None = None,
        position_controller: Any | None = None,
        paper_trader: Any | None = None,
        event_bus: Any | None = None,
        mode: str = "PAPER",
    ) -> None:
        self.capital_manager = capital_manager
        self.position_controller = position_controller
        self.paper_trader = paper_trader
        self.event_bus = event_bus

        self.mode = str(
            mode
        ).strip().upper()

        self.running = False

        self.history: list[
            dict[str, Any]
        ] = []

        self.rejections: list[
            dict[str, Any]
        ] = []

        self.errors: list[
            dict[str, Any]
        ] = []

        self.stats: dict[str, int] = {
            "received": 0,
            "validated": 0,
            "executed": 0,
            "rejected": 0,
            "failed": 0,
            "paper_orders": 0,
            "live_blocked": 0,
        }

        logger.info(
            "Execution Manager v%s initialized mode=%s",
            self.VERSION,
            self.mode,
        )

    # ========================================================
    # START
    # ========================================================

    def start(self) -> bool:
        """
        Bring the execution service online.
        """

        if self.running:
            logger.info(
                "Execution Manager is already online"
            )
            return True

        self.running = True

        logger.info(
            "Execution Manager ONLINE"
        )

        return True

    # ========================================================
    # STOP
    # ========================================================

    def stop(self) -> bool:
        """
        Stop accepting new execution requests.
        """

        if not self.running:
            logger.info(
                "Execution Manager is already offline"
            )
            return True

        self.running = False

        logger.info(
            "Execution Manager OFFLINE"
        )

        return True

    # ========================================================
    # MAIN PIPELINE
    # ========================================================

    def execute(
        self,
        decision: Any,
        market_state: Any | None = None,
    ) -> dict[str, Any]:
        """
        Validate and execute one Atlas decision.
        """

        self.stats[
            "received"
        ] += 1

        if not self.running:
            return self.reject(
                reason="EXECUTION_MANAGER_OFFLINE",
            )

        try:
            request = self.build_request(
                decision
            )

            validation = self.validate_request(
                request
            )

            if not validation[
                "approved"
            ]:
                return self.reject(
                    reason=validation[
                        "reason"
                    ],
                    request=request,
                    details=validation.get(
                        "details"
                    ),
                )

            self.stats[
                "validated"
            ] += 1

            risk_validation = self.risk_check(
                request=request,
                market_state=market_state,
            )

            if not risk_validation[
                "approved"
            ]:
                return self.reject(
                    reason=risk_validation[
                        "reason"
                    ],
                    request=request,
                    details=risk_validation.get(
                        "details"
                    ),
                )

            if self.mode == "PAPER":
                result = self.paper_execute(
                    request
                )
            else:
                result = self.live_execute(
                    request
                )

            status = str(
                result.get(
                    "status",
                    "UNKNOWN",
                )
            ).upper()

            if status in {
                "PAPER_EXECUTED",
                "EXECUTED",
                "COMPLETED",
                "SUCCESS",
            }:
                self.stats[
                    "executed"
                ] += 1

            elif status in {
                "FAILED",
                "ERROR",
            }:
                self.stats[
                    "failed"
                ] += 1

            self.history.append(
                result
            )

            self._limit_collection(
                self.history
            )

            self.publish(
                "EXECUTION_COMPLETED",
                result,
            )

            return result

        except Exception as exc:
            self.stats[
                "failed"
            ] += 1

            self._record_error(
                phase="execute",
                error=exc,
            )

            logger.exception(
                "Execution pipeline failed"
            )

            return {
                "status": "FAILED",
                "reason": "EXECUTION_PIPELINE_EXCEPTION",
                "error": str(
                    exc
                ),
                "timestamp": self._utc_now(),
            }

    # ========================================================
    # REQUEST BUILDER
    # ========================================================

    def build_request(
        self,
        decision: Any,
    ) -> ExecutionRequest:
        """
        Build a defensive canonical execution request.
        """

        data = self._decision_to_dict(
            decision
        )

        metadata = data.get(
            "metadata",
            {},
        )

        if not isinstance(
            metadata,
            dict,
        ):
            metadata = {
                "original_metadata": repr(
                    metadata
                )
            }

        return ExecutionRequest(
            symbol=self._normalize_symbol(
                data.get(
                    "symbol",
                    "UNKNOWN",
                )
            ),

            action=self._normalize_action(
                data.get(
                    "action",
                    data.get(
                        "decision",
                        "HOLD",
                    ),
                )
            ),

            price=self._normalize_price(
                data.get(
                    "price",
                    0,
                )
            ),

            confidence=self._normalize_confidence(
                data.get(
                    "confidence",
                    0,
                )
            ),

            timestamp=str(
                data.get(
                    "created_at",
                    data.get(
                        "timestamp",
                        self._utc_now(),
                    ),
                )
            ),

            strategy=str(
                data.get(
                    "strategy",
                    "Atlas",
                )
            ),

            risk_level=self._normalize_risk_level(
                data.get(
                    "risk_level",
                    data.get(
                        "risk",
                        "MEDIUM",
                    ),
                )
            ),

            metadata=dict(
                metadata
            ),
        )

    # ========================================================
    # REQUEST VALIDATION
    # ========================================================

    def validate_request(
        self,
        request: ExecutionRequest,
    ) -> dict[str, Any]:
        """
        Validate the canonical execution request.
        """

        if (
            not request.symbol
            or request.symbol == "UNKNOWN"
        ):
            return {
                "approved": False,
                "reason": "INVALID_SYMBOL",
                "details": {
                    "symbol": request.symbol,
                },
            }

        if request.action in self.NON_EXECUTION_ACTIONS:
            return {
                "approved": False,
                "reason": "NON_EXECUTION_ACTION",
                "details": {
                    "action": request.action,
                },
            }

        if request.action not in self.VALID_ACTIONS:
            return {
                "approved": False,
                "reason": "INVALID_ACTION",
                "details": {
                    "action": request.action,
                    "valid_actions": sorted(
                        self.VALID_ACTIONS
                    ),
                },
            }

        if request.price <= 0:
            return {
                "approved": False,
                "reason": "INVALID_PRICE",
                "details": {
                    "price": request.price,
                },
            }

        if request.confidence < self.MIN_CONFIDENCE:
            return {
                "approved": False,
                "reason": "LOW_CONFIDENCE",
                "details": {
                    "confidence": request.confidence,
                    "minimum_confidence": (
                        self.MIN_CONFIDENCE
                    ),
                },
            }

        return {
            "approved": True,
            "reason": "APPROVED",
            "details": {
                "confidence": request.confidence,
                "minimum_confidence": (
                    self.MIN_CONFIDENCE
                ),
            },
        }

    # ========================================================
    # RISK VALIDATION
    # ========================================================

    def risk_check(
        self,
        request: ExecutionRequest,
        market_state: Any | None = None,
    ) -> dict[str, Any]:
        """
        Apply available portfolio and position controls.
        """

        del market_state

        if request.action == "BUY":
            allowed = self._can_open_position(
                request.symbol
            )

            if not allowed:
                return {
                    "approved": False,
                    "reason": "POSITION_LIMIT",
                    "details": {
                        "symbol": request.symbol,
                    },
                }

        return {
            "approved": True,
            "reason": "RISK_APPROVED",
        }

    def _can_open_position(
        self,
        symbol: str,
    ) -> bool:
        """
        Query PositionController using supported contracts.
        """

        if self.position_controller is None:
            return True

        for method_name in (
            "can_open",
            "can_open_position",
        ):
            method = getattr(
                self.position_controller,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                result = method(
                    symbol
                )

                if isinstance(
                    result,
                    dict,
                ):
                    return bool(
                        result.get(
                            "approved",
                            result.get(
                                "allowed",
                                False,
                            ),
                        )
                    )

                return bool(
                    result
                )

            except TypeError:
                try:
                    result = method()

                    return bool(
                        result
                    )

                except Exception:
                    logger.exception(
                        "Position limit check failed"
                    )
                    return False

            except Exception:
                logger.exception(
                    "Position limit check failed"
                )
                return False

        return True

    # ========================================================
    # PAPER EXECUTION
    # ========================================================

    def paper_execute(
        self,
        request: ExecutionRequest,
    ) -> dict[str, Any]:
        """
        Execute an approved order in paper mode.
        """

        logger.info(
            "[PAPER ORDER] %s %s @ %.8f | confidence=%.2f%%",
            request.action,
            request.symbol,
            request.price,
            request.confidence,
        )

        result = ExecutionResult(
            status="PAPER_EXECUTED",
            symbol=request.symbol,
            action=request.action,
            mode="PAPER",
            timestamp=request.timestamp,
            message="Paper execution completed",
            data={
                "confidence": request.confidence,
                "strategy": request.strategy,
                "risk_level": request.risk_level,
            },
        )

        if request.action == "BUY":
            self._execute_paper_buy(
                request=request,
                result=result,
            )

        elif request.action == "SELL":
            self._execute_paper_sell(
                request=request,
                result=result,
            )

        self.stats[
            "paper_orders"
        ] += 1

        return result.to_dict()

    # ========================================================
    # PAPER BUY
    # ========================================================

    def _execute_paper_buy(
        self,
        *,
        request: ExecutionRequest,
        result: ExecutionResult,
    ) -> None:
        """
        Coordinate a paper BUY.
        """

        allocation = self.allocate_capital(
            request
        )

        result.data = result.data or {}
        result.data[
            "allocation"
        ] = allocation

        if self.paper_trader is not None:
            open_trade = getattr(
                self.paper_trader,
                "open_trade",
                None,
            )

            if callable(
                open_trade
            ):
                try:
                    trade = open_trade(
                        request.symbol,
                        request.price,
                        allocation,
                    )

                    result.data[
                        "paper_trade"
                    ] = trade

                except Exception as exc:
                    self._record_error(
                        phase="paper_buy",
                        error=exc,
                    )

                    logger.exception(
                        "PaperTrader BUY failed"
                    )

                    result.data[
                        "paper_trader_error"
                    ] = str(
                        exc
                    )

        if self.position_controller is not None:
            open_position = getattr(
                self.position_controller,
                "open_position",
                None,
            )

            if callable(
                open_position
            ):
                try:
                    position = open_position(
                        symbol=request.symbol,
                        price=request.price,
                        side="LONG",
                    )

                    result.data[
                        "position"
                    ] = position

                except TypeError:
                    try:
                        position = open_position(
                            request.symbol,
                            request.price,
                        )

                        result.data[
                            "position"
                        ] = position

                    except Exception as exc:
                        self._record_error(
                            phase="position_open",
                            error=exc,
                        )

                        logger.exception(
                            "PositionController open failed"
                        )

                except Exception as exc:
                    self._record_error(
                        phase="position_open",
                        error=exc,
                    )

                    logger.exception(
                        "PositionController open failed"
                    )

        self.publish(
            "TRADE_OPENED",
            result.to_dict(),
        )

    # ========================================================
    # PAPER SELL
    # ========================================================

    def _execute_paper_sell(
        self,
        *,
        request: ExecutionRequest,
        result: ExecutionResult,
    ) -> None:
        """
        Coordinate a paper SELL or position close.
        """

        result.data = result.data or {}

        if self.paper_trader is not None:
            close_trade = getattr(
                self.paper_trader,
                "close_trade",
                None,
            )

            if callable(
                close_trade
            ):
                try:
                    trade = close_trade(
                        request.symbol
                    )

                    result.data[
                        "paper_trade"
                    ] = trade

                except Exception as exc:
                    self._record_error(
                        phase="paper_sell",
                        error=exc,
                    )

                    logger.exception(
                        "PaperTrader SELL failed"
                    )

                    result.data[
                        "paper_trader_error"
                    ] = str(
                        exc
                    )

        if self.position_controller is not None:
            close_position = getattr(
                self.position_controller,
                "close_position",
                None,
            )

            if callable(
                close_position
            ):
                try:
                    position = close_position(
                        request.symbol
                    )

                    result.data[
                        "position"
                    ] = position

                except Exception as exc:
                    self._record_error(
                        phase="position_close",
                        error=exc,
                    )

                    logger.exception(
                        "PositionController close failed"
                    )

                    result.data[
                        "position_error"
                    ] = str(
                        exc
                    )

        self.publish(
            "TRADE_CLOSED",
            result.to_dict(),
        )

    # ========================================================
    # CAPITAL ALLOCATION
    # ========================================================

    def allocate_capital(
        self,
        request: ExecutionRequest,
    ) -> float:
        """
        Calculate paper position capital.
        """

        default_amount = 100.0

        if self.capital_manager is None:
            return default_amount

        calculate_position_size = getattr(
            self.capital_manager,
            "calculate_position_size",
            None,
        )

        if callable(
            calculate_position_size
        ):
            try:
                value = calculate_position_size(
                    request.to_dict()
                )

                amount = self._normalize_price(
                    value
                )

                if amount > 0:
                    return amount

            except TypeError:
                try:
                    value = calculate_position_size(
                        confidence=request.confidence,
                        risk_level=request.risk_level,
                        price=request.price,
                    )

                    amount = self._normalize_price(
                        value
                    )

                    if amount > 0:
                        return amount

                except Exception:
                    logger.exception(
                        "Capital position sizing failed"
                    )

            except Exception:
                logger.exception(
                    "Capital position sizing failed"
                )

        available_capital = getattr(
            self.capital_manager,
            "available_capital",
            None,
        )

        if available_capital is None:
            get_available_capital = getattr(
                self.capital_manager,
                "get_available_capital",
                None,
            )

            if callable(
                get_available_capital
            ):
                try:
                    available_capital = (
                        get_available_capital()
                    )

                except Exception:
                    logger.exception(
                        "Available capital query failed"
                    )

        try:
            if available_capital is not None:
                return max(
                    0.0,
                    min(
                        default_amount,
                        float(
                            available_capital
                        ),
                    ),
                )

        except (
            TypeError,
            ValueError,
        ):
            pass

        return default_amount

    # ========================================================
    # LIVE EXECUTION
    # ========================================================

    def live_execute(
        self,
        request: ExecutionRequest,
    ) -> dict[str, Any]:
        """
        Block live execution until explicitly implemented and approved.
        """

        self.stats[
            "live_blocked"
        ] += 1

        logger.warning(
            "LIVE execution requested but disabled"
        )

        result = ExecutionResult(
            status="LIVE_DISABLED",
            symbol=request.symbol,
            action=request.action,
            mode="LIVE",
            timestamp=request.timestamp,
            message=(
                "Live trading is disabled by the "
                "execution safety policy"
            ),
            data={
                "confidence": request.confidence,
            },
        )

        payload = result.to_dict()

        self.publish(
            "LIVE_EXECUTION_BLOCKED",
            payload,
        )

        return payload

    # ========================================================
    # REJECTION
    # ========================================================

    def reject(
        self,
        reason: str,
        request: ExecutionRequest | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Return and publish a structured execution rejection.
        """

        self.stats[
            "rejected"
        ] += 1

        result: dict[str, Any] = {
            "status": "REJECTED",
            "reason": reason,
            "timestamp": self._utc_now(),
        }

        if request is not None:
            result.update(
                {
                    "symbol": request.symbol,
                    "action": request.action,
                    "price": request.price,
                    "confidence": (
                        request.confidence
                    ),
                }
            )

        if details:
            result[
                "details"
            ] = details

        self.rejections.append(
            result
        )

        self._limit_collection(
            self.rejections
        )

        if reason == "LOW_CONFIDENCE":
            logger.warning(
                "[EXECUTION REJECTED] %s | "
                "confidence=%.2f%% minimum=%.2f%%",
                reason,
                (
                    request.confidence
                    if request is not None
                    else 0.0
                ),
                self.MIN_CONFIDENCE,
            )
        else:
            logger.warning(
                "[EXECUTION REJECTED] %s",
                reason,
            )

        self.publish(
            "EXECUTION_REJECTED",
            result,
        )

        return result

    # ========================================================
    # EVENT BUS
    # ========================================================

    def publish(
        self,
        event_name: str,
        payload: Any,
    ) -> bool:
        """
        Publish using the current or legacy EventBus contract.
        """

        if self.event_bus is None:
            return False

        publish_method = getattr(
            self.event_bus,
            "publish",
            None,
        )

        if not callable(
            publish_method
        ):
            return False

        event_payload = {
            "event": event_name,
            "payload": payload,
            "timestamp": self._utc_now(),
            "source": self.NAME,
        }

        try:
            publish_method(
                event_payload
            )

            return True

        except TypeError:
            try:
                publish_method(
                    event_name,
                    payload,
                )

                return True

            except Exception:
                logger.exception(
                    "Legacy EventBus publish failed"
                )

                return False

        except Exception:
            logger.exception(
                "EventBus publish failed"
            )

            return False

    # ========================================================
    # NORMALIZATION
    # ========================================================

    @staticmethod
    def _decision_to_dict(
        decision: Any,
    ) -> dict[str, Any]:
        """
        Convert supported decision representations to a dictionary.
        """

        if isinstance(
            decision,
            dict,
        ):
            return dict(
                decision
            )

        to_dict = getattr(
            decision,
            "to_dict",
            None,
        )

        if callable(
            to_dict
        ):
            result = to_dict()

            if isinstance(
                result,
                dict,
            ):
                return result

        if hasattr(
            decision,
            "__dict__",
        ):
            return dict(
                vars(
                    decision
                )
            )

        raise TypeError(
            "Unsupported execution decision type: "
            f"{type(decision).__name__}"
        )

    @staticmethod
    def _normalize_symbol(
        value: Any,
    ) -> str:
        return str(
            value
        ).strip().upper()

    @classmethod
    def _normalize_action(
        cls,
        value: Any,
    ) -> str:
        """
        Normalize strings and Enum actions.
        """

        if isinstance(
            value,
            Enum,
        ):
            enum_value = value.value

            value = (
                enum_value
                if isinstance(
                    enum_value,
                    str,
                )
                else value.name
            )

        action = str(
            value
        ).strip().upper()

        if "." in action:
            action = action.rsplit(
                ".",
                maxsplit=1,
            )[-1]

        aliases = {
            "LONG": "BUY",
            "OPEN_LONG": "BUY",
            "SHORT": "SELL",
            "OPEN_SHORT": "SELL",
            "WAIT": "HOLD",
            "NEUTRAL": "HOLD",
        }

        return aliases.get(
            action,
            action,
        )

    @staticmethod
    def _normalize_price(
        value: Any,
    ) -> float:
        try:
            return float(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            return 0.0

    @staticmethod
    def _normalize_confidence(
        value: Any,
    ) -> float:
        """
        Normalize confidence to percentage scale.
        """

        if isinstance(
            value,
            str,
        ):
            value = value.strip().replace(
                "%",
                "",
            )

        try:
            confidence = float(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            return 0.0

        if 0 <= confidence <= 1:
            confidence *= 100

        return round(
            max(
                0.0,
                min(
                    confidence,
                    100.0,
                ),
            ),
            2,
        )

    @staticmethod
    def _normalize_risk_level(
        value: Any,
    ) -> str:
        if isinstance(
            value,
            Enum,
        ):
            value = value.value

        risk_level = str(
            value
        ).strip().upper()

        if "." in risk_level:
            risk_level = risk_level.rsplit(
                ".",
                maxsplit=1,
            )[-1]

        if risk_level not in {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }:
            return "MEDIUM"

        return risk_level

    # ========================================================
    # ERROR MANAGEMENT
    # ========================================================

    def _record_error(
        self,
        *,
        phase: str,
        error: Exception,
    ) -> None:
        self.errors.append(
            {
                "timestamp": self._utc_now(),
                "phase": phase,
                "type": type(
                    error
                ).__name__,
                "error": str(
                    error
                ),
            }
        )

        self._limit_collection(
            self.errors
        )

    @staticmethod
    def _limit_collection(
        collection: list[Any],
        maximum: int = 500,
    ) -> None:
        if len(
            collection
        ) > maximum:
            del collection[
                :-maximum
            ]

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(
            UTC
        ).isoformat()

    # ========================================================
    # HISTORY
    # ========================================================

    def get_history(
        self,
    ) -> list[dict[str, Any]]:
        return list(
            self.history
        )

    # ========================================================
    # RESET
    # ========================================================

    def reset(self) -> None:
        self.history.clear()
        self.rejections.clear()
        self.errors.clear()

        self.stats = {
            "received": 0,
            "validated": 0,
            "executed": 0,
            "rejected": 0,
            "failed": 0,
            "paper_orders": 0,
            "live_blocked": 0,
        }

        logger.info(
            "Execution Manager reset"
        )

    # ========================================================
    # HEALTH
    # ========================================================

    def health(self) -> dict[str, Any]:
        return {
            "healthy": self.running,
            "running": self.running,
            "version": self.VERSION,
            "mode": self.mode,
            "statistics": dict(
                self.stats
            ),
            "errors": len(
                self.errors
            ),
        }

    # ========================================================
    # STATUS
    # ========================================================

    def status(self) -> dict[str, Any]:
        return {
            "name": self.NAME,
            "version": self.VERSION,
            "mode": self.mode,
            "running": self.running,
            "minimum_confidence": (
                self.MIN_CONFIDENCE
            ),
            "history": len(
                self.history
            ),
            "rejections": len(
                self.rejections
            ),
            "errors": {
                "count": len(
                    self.errors
                ),
                "latest": (
                    self.errors[-1]
                    if self.errors
                    else None
                ),
            },
            "statistics": dict(
                self.stats
            ),
            "dependencies": {
                "capital_manager": (
                    self.capital_manager
                    is not None
                ),
                "position_controller": (
                    self.position_controller
                    is not None
                ),
                "paper_trader": (
                    self.paper_trader
                    is not None
                ),
                "event_bus": (
                    self.event_bus
                    is not None
                ),
            },
        }

    # ========================================================
    # REPRESENTATION
    # ========================================================

    def __repr__(self) -> str:
        return (
            f"<{self.NAME} "
            f"version={self.VERSION} "
            f"mode={self.mode} "
            f"running={self.running}>"
        )