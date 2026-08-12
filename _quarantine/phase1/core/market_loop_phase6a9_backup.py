"""
============================================================
ATLAS AI MARKET LOOP v8.0
============================================================

Institutional Market Intelligence Orchestrator

Pipeline
--------

Exchange
   |
MarketFeed
   |
Candle Processor
   |
Technical Analyzer
   |
World Analysis Engine
   |
Atlas Brain
   |
Decision Adapter
   |
Execution Manager
   |
Learning System
   |
Event Bus

Responsibilities
----------------

- Scan multiple market symbols
- Retrieve and normalize candle data
- Generate technical market analysis
- Build world and market intelligence context
- Route market context through Atlas Brain
- Normalize AI decisions into one execution contract
- Prevent HOLD decisions from reaching execution
- Coordinate paper or live execution
- Publish structured events
- Track runtime metrics and diagnostics
- Recover from symbol-level processing errors
- Support controlled startup and shutdown

============================================================
"""

from __future__ import annotations

import logging
import threading
import time
import traceback

from datetime import UTC, datetime
from typing import Any

from analysis.world_analysis_engine import WorldAnalysisEngine

from core.candle_processor import CandleProcessor
from core.decision_adapter import DecisionAdapter
from core.technical_analyzer import TechnicalAnalyzer


logger = logging.getLogger(
    "AtlasAI.MarketLoop"
)


class MarketLoop:
    """
    Continuous Atlas market intelligence and execution loop.

    The MarketLoop owns market-cycle coordination only. It does not
    contain portfolio, risk, or exchange execution business logic.
    """

    VERSION = "8.0"
    NAME = "MarketLoop"

    DEFAULT_SYMBOLS = (
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "XRPUSDT",
    )

    VALID_EXECUTION_ACTIONS = {
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
        brain: Any,
        market_feed: Any,
        execution: Any | None = None,
        event_bus: Any | None = None,
        symbols: list[str] | tuple[str, ...] | None = None,
        interval: float = 10.0,
    ) -> None:
        self.brain = brain
        self.market_feed = market_feed
        self.execution = execution
        self.event_bus = event_bus

        self.symbols = self._normalize_symbols(
            symbols or self.DEFAULT_SYMBOLS
        )

        self.interval = max(
            1.0,
            float(interval),
        )

        self.processor = CandleProcessor()
        self.technical = TechnicalAnalyzer()
        self.world = WorldAnalysisEngine()
        self.decision_adapter = DecisionAdapter()

        self.running = False
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.RLock()

        self.started_at: str | None = None
        self.stopped_at: str | None = None
        self.last_cycle: str | None = None
        self.last_cycle_duration = 0.0

        self.last_signals: dict[str, dict[str, Any]] = {}
        self.last_executions: dict[str, dict[str, Any]] = {}

        self.metrics: dict[str, int | float] = {
            "cycles": 0,
            "symbols_scanned": 0,
            "symbols_skipped": 0,
            "decisions_received": 0,
            "decisions_normalized": 0,
            "decisions_rejected": 0,
            "hold_decisions": 0,
            "execution_requests": 0,
            "executions_completed": 0,
            "executions_rejected": 0,
            "execution_failures": 0,
            "errors": 0,
            "latency": 0.0,
        }

        self.errors: list[dict[str, Any]] = []

        logger.info(
            "Atlas Market Loop v%s initialized",
            self.VERSION,
        )

    # =========================================================
    # START
    # =========================================================

    def start(self) -> bool:
        """
        Start the market worker thread.

        Returns:
            True when the loop starts or is already running.
        """

        with self.lock:
            if self.running:
                logger.warning(
                    "Market Loop is already running"
                )
                return True

            self.running = True
            self.stop_event.clear()

            self.started_at = datetime.now(
                UTC
            ).isoformat()

            self.stopped_at = None

            self.thread = threading.Thread(
                target=self.worker,
                name="AtlasMarketLoop",
                daemon=True,
            )

            self.thread.start()

        logger.info(
            "Market Loop started"
        )

        return True

    # =========================================================
    # STOP
    # =========================================================

    def stop(self) -> bool:
        """
        Stop the worker thread gracefully.
        """

        with self.lock:
            if not self.running:
                logger.info(
                    "Market Loop is already stopped"
                )
                return True

            self.running = False
            self.stop_event.set()

            thread = self.thread

        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(
                timeout=max(
                    5.0,
                    self.interval + 1.0,
                )
            )

        with self.lock:
            still_alive = bool(
                self.thread
                and self.thread.is_alive()
            )

            self.stopped_at = datetime.now(
                UTC
            ).isoformat()

            if not still_alive:
                self.thread = None

        if still_alive:
            logger.warning(
                "Market Loop thread did not stop within timeout"
            )
            return False

        logger.info(
            "Market Loop stopped"
        )

        return True

    # =========================================================
    # WORKER
    # =========================================================

    def worker(self) -> None:
        """
        Execute continuous market cycles until shutdown.
        """

        logger.debug(
            "Market Loop worker entered"
        )

        while self.running:
            cycle_started = time.perf_counter()

            try:
                self.run_cycle()

            except Exception as exc:
                self._record_error(
                    phase="cycle",
                    error=exc,
                )

                logger.exception(
                    "Market cycle failed"
                )

            cycle_duration = (
                time.perf_counter()
                - cycle_started
            )

            with self.lock:
                self.metrics["cycles"] += 1
                self.metrics["latency"] = round(
                    cycle_duration,
                    4,
                )

                self.last_cycle_duration = round(
                    cycle_duration,
                    4,
                )

                self.last_cycle = datetime.now(
                    UTC
                ).isoformat()

            self.stop_event.wait(
                self.interval
            )

        logger.debug(
            "Market Loop worker exited"
        )

    # =========================================================
    # CYCLE
    # =========================================================

    def run_cycle(self) -> None:
        """
        Process one complete multi-symbol market cycle.
        """

        for symbol in tuple(self.symbols):
            if not self.running:
                break

            self.process_symbol(
                symbol
            )

    # =========================================================
    # SYMBOL PIPELINE
    # =========================================================

    def process_symbol(
        self,
        symbol: str,
    ) -> dict[str, Any] | None:
        """
        Execute the full intelligence pipeline for one symbol.
        """

        symbol = str(
            symbol
        ).strip().upper()

        try:
            candles = self._load_candles(
                symbol
            )

            if not candles:
                self._increment_metric(
                    "symbols_skipped"
                )
                return None

            normalized_candles = self.processor.normalize(
                candles
            )

            if not normalized_candles:
                self._increment_metric(
                    "symbols_skipped"
                )
                return None

            if len(normalized_candles) < 50:
                logger.warning(
                    "%s skipped: insufficient candles=%s",
                    symbol,
                    len(normalized_candles),
                )

                self._increment_metric(
                    "symbols_skipped"
                )

                return None

            analysis = self.technical.analyze(
                normalized_candles
            )

            if not isinstance(
                analysis,
                dict,
            ):
                logger.warning(
                    "%s skipped: invalid technical analysis",
                    symbol,
                )

                self._increment_metric(
                    "symbols_skipped"
                )

                return None

            price = self.processor.latest_price(
                normalized_candles
            )

            price = self._safe_float(
                price
            )

            if price <= 0:
                logger.warning(
                    "%s skipped: invalid price=%s",
                    symbol,
                    price,
                )

                self._increment_metric(
                    "symbols_skipped"
                )

                return None

            score = self.calculate_score(
                analysis
            )

            market_data = self.world.build_market_data(
                symbol,
                price,
                analysis,
                score,
            )

            raw_decision = self.brain.analyze_and_decide(
                symbol,
                market_data,
            )

            self._increment_metric(
                "decisions_received"
            )

            normalized_decision = (
                self.normalize_decision(
                    raw_decision=raw_decision,
                    symbol=symbol,
                    price=price,
                    market_data=market_data,
                )
            )

            if normalized_decision is None:
                self._increment_metric(
                    "decisions_rejected"
                )

                logger.warning(
                    "%s decision normalization failed",
                    symbol,
                )

                self.publish(
                    "DECISION_NORMALIZATION_FAILED",
                    {
                        "symbol": symbol,
                        "raw_decision": self._safe_payload(
                            raw_decision
                        ),
                        "timestamp": datetime.now(
                            UTC
                        ).isoformat(),
                    },
                )

                return None

            self._increment_metric(
                "decisions_normalized"
            )

            with self.lock:
                self.last_signals[
                    symbol
                ] = normalized_decision

            self.publish(
                "ATLAS_DECISION",
                normalized_decision,
            )

            action = normalized_decision.get(
                "action",
                "HOLD",
            )

            if action in self.NON_EXECUTION_ACTIONS:
                self._increment_metric(
                    "hold_decisions"
                )

                logger.info(
                    "%s decision HOLD | execution skipped",
                    symbol,
                )

                result = {
                    "status": "SKIPPED",
                    "reason": "NON_EXECUTION_ACTION",
                    "symbol": symbol,
                    "action": action,
                    "timestamp": datetime.now(
                        UTC
                    ).isoformat(),
                }

                with self.lock:
                    self.last_executions[
                        symbol
                    ] = result

                return result

            if action not in self.VALID_EXECUTION_ACTIONS:
                self._increment_metric(
                    "decisions_rejected"
                )

                logger.warning(
                    "%s invalid normalized action: %s",
                    symbol,
                    action,
                )

                return {
                    "status": "REJECTED",
                    "reason": "INVALID_NORMALIZED_ACTION",
                    "symbol": symbol,
                    "action": action,
                }

            if self.execution is None:
                logger.warning(
                    "%s execution skipped: manager unavailable",
                    symbol,
                )

                return {
                    "status": "SKIPPED",
                    "reason": "EXECUTION_MANAGER_UNAVAILABLE",
                    "symbol": symbol,
                    "action": action,
                }

            market_state = self.world.build_market_state(
                market_data
            )

            result = self.route_execution(
                decision=normalized_decision,
                market_state=market_state,
            )

            with self.lock:
                self.last_executions[
                    symbol
                ] = result

            self._increment_metric(
                "symbols_scanned"
            )

            return result

        except Exception as exc:
            self._record_error(
                phase=f"symbol:{symbol}",
                error=exc,
            )

            logger.exception(
                "%s processing failed",
                symbol,
            )

            return None

    # =========================================================
    # CANDLE LOADING
    # =========================================================

    def _load_candles(
        self,
        symbol: str,
    ) -> Any:
        """
        Retrieve candles from the configured MarketFeed.
        """

        candles_method = getattr(
            self.market_feed,
            "candles",
            None,
        )

        if not callable(
            candles_method
        ):
            raise AttributeError(
                "MarketFeed does not provide candles()"
            )

        return candles_method(
            symbol,
            interval="1m",
            limit=200,
        )

    # =========================================================
    # DECISION NORMALIZATION
    # =========================================================

    def normalize_decision(
        self,
        *,
        raw_decision: Any,
        symbol: str,
        price: float,
        market_data: Any,
    ) -> dict[str, Any] | None:
        """
        Convert Brain output into the canonical execution decision schema.
        """

        source = self._decision_to_dict(
            raw_decision
        )

        if source is None:
            return None

        enriched_decision = dict(
            source
        )

        enriched_decision["symbol"] = symbol
        enriched_decision["price"] = price

        if "market_state" not in enriched_decision:
            enriched_decision[
                "market_state"
            ] = (
                market_data
                if isinstance(
                    market_data,
                    dict,
                )
                else {}
            )

        normalized = self.decision_adapter.normalize(
            enriched_decision
        )

        if not isinstance(
            normalized,
            dict,
        ):
            return None

        action = str(
            normalized.get(
                "action",
                "HOLD",
            )
        ).strip().upper()

        normalized["action"] = action
        normalized["symbol"] = str(
            normalized.get(
                "symbol",
                symbol,
            )
        ).strip().upper()

        normalized["price"] = self._safe_float(
            normalized.get(
                "price",
                price,
            )
        )

        normalized["confidence"] = (
            self._normalize_confidence(
                normalized.get(
                    "confidence",
                    0,
                )
            )
        )

        normalized.setdefault(
            "strategy",
            "Atlas",
        )

        normalized.setdefault(
            "risk_level",
            "MEDIUM",
        )

        metadata = normalized.get(
            "metadata"
        )

        if not isinstance(
            metadata,
            dict,
        ):
            metadata = {}

        metadata.update(
            {
                "market_loop_version": self.VERSION,
                "raw_decision_type": type(
                    raw_decision
                ).__name__,
                "normalized_at": datetime.now(
                    UTC
                ).isoformat(),
            }
        )

        normalized["metadata"] = metadata

        return normalized

    # =========================================================
    # DECISION CONVERSION
    # =========================================================

    @staticmethod
    def _decision_to_dict(
        decision: Any,
    ) -> dict[str, Any] | None:
        """
        Convert supported Brain decision objects into a dictionary.
        """

        if decision is None:
            return None

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
            converted = to_dict()

            if isinstance(
                converted,
                dict,
            ):
                return converted

        if hasattr(
            decision,
            "__dict__",
        ):
            return dict(
                vars(
                    decision
                )
            )

        return None

    # =========================================================
    # CONFIDENCE NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalize_confidence(
        value: Any,
    ) -> float:
        """
        Normalize confidence values to the 0-100 execution scale.

        Brain modules may return either:
        - 0.706
        - 70.6
        """

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

    # =========================================================
    # EXECUTION ROUTING
    # =========================================================

    def route_execution(
        self,
        *,
        decision: dict[str, Any],
        market_state: Any,
    ) -> dict[str, Any]:
        """
        Route one canonical decision to ExecutionManager.
        """

        self._increment_metric(
            "execution_requests"
        )

        try:
            result = self.execution.execute(
                decision,
                market_state,
            )

        except Exception as exc:
            self._increment_metric(
                "execution_failures"
            )

            self._record_error(
                phase="execution",
                error=exc,
            )

            logger.exception(
                "%s execution routing failed",
                decision.get(
                    "symbol",
                    "UNKNOWN",
                ),
            )

            return {
                "status": "FAILED",
                "reason": "EXECUTION_EXCEPTION",
                "error": str(
                    exc
                ),
                "symbol": decision.get(
                    "symbol",
                    "UNKNOWN",
                ),
                "action": decision.get(
                    "action",
                    "UNKNOWN",
                ),
                "timestamp": datetime.now(
                    UTC
                ).isoformat(),
            }

        result_dict = self._normalize_execution_result(
            result
        )

        status = str(
            result_dict.get(
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
            self._increment_metric(
                "executions_completed"
            )

        elif status == "REJECTED":
            self._increment_metric(
                "executions_rejected"
            )

        elif status in {
            "FAILED",
            "ERROR",
        }:
            self._increment_metric(
                "execution_failures"
            )

        logger.info(
            "%s execution %s | action=%s",
            decision.get(
                "symbol",
                "UNKNOWN",
            ),
            status,
            decision.get(
                "action",
                "UNKNOWN",
            ),
        )

        return result_dict

    # =========================================================
    # EXECUTION RESULT NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalize_execution_result(
        result: Any,
    ) -> dict[str, Any]:
        """
        Convert execution results into a dictionary.
        """

        if isinstance(
            result,
            dict,
        ):
            return result

        to_dict = getattr(
            result,
            "to_dict",
            None,
        )

        if callable(
            to_dict
        ):
            converted = to_dict()

            if isinstance(
                converted,
                dict,
            ):
                return converted

        if hasattr(
            result,
            "__dict__",
        ):
            return dict(
                vars(
                    result
                )
            )

        return {
            "status": "UNKNOWN",
            "result": str(
                result
            ),
        }

    # =========================================================
    # SCORE
    # =========================================================

    @staticmethod
    def calculate_score(
        analysis: dict[str, Any],
    ) -> float:
        """
        Produce a bounded market quality score between 0 and 1.
        """

        score = 0.5

        rsi = analysis.get(
            "rsi"
        )

        trend = str(
            analysis.get(
                "trend",
                "",
            )
        ).upper()

        try:
            rsi_value = float(
                rsi
            )
        except (
            TypeError,
            ValueError,
        ):
            rsi_value = None

        if rsi_value is not None:
            if 40 <= rsi_value <= 60:
                score += 0.15

            elif rsi_value < 30:
                score += 0.10

            elif rsi_value > 70:
                score -= 0.10

        if trend == "BULLISH":
            score += 0.20

        elif trend == "BEARISH":
            score -= 0.20

        return round(
            max(
                0.0,
                min(
                    score,
                    1.0,
                ),
            ),
            2,
        )

    # =========================================================
    # EVENT BUS
    # =========================================================

    def publish(
        self,
        event_name: str,
        payload: Any,
    ) -> bool:
        """
        Publish an event using the current or legacy EventBus contract.
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
            "timestamp": datetime.now(
                UTC
            ).isoformat(),
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
                    "Legacy event publish failed: %s",
                    event_name,
                )

                return False

        except Exception:
            logger.exception(
                "Event publish failed: %s",
                event_name,
            )

            return False

    # =========================================================
    # METRICS
    # =========================================================

    def _increment_metric(
        self,
        name: str,
        amount: int = 1,
    ) -> None:
        """
        Increment one numeric runtime metric safely.
        """

        with self.lock:
            current = self.metrics.get(
                name,
                0,
            )

            if not isinstance(
                current,
                (
                    int,
                    float,
                ),
            ):
                current = 0

            self.metrics[name] = (
                current + amount
            )

    # =========================================================
    # ERRORS
    # =========================================================

    def _record_error(
        self,
        *,
        phase: str,
        error: Exception,
    ) -> None:
        """
        Store a structured diagnostic error.
        """

        error_record = {
            "time": datetime.now(
                UTC
            ).isoformat(),
            "phase": phase,
            "type": type(
                error
            ).__name__,
            "error": str(
                error
            ),
            "traceback": traceback.format_exc(),
        }

        with self.lock:
            self.metrics["errors"] += 1
            self.errors.append(
                error_record
            )

            if len(
                self.errors
            ) > 100:
                self.errors = self.errors[
                    -100:
                ]

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _normalize_symbols(
        symbols: Any,
    ) -> list[str]:
        """
        Normalize, validate, and deduplicate market symbols.
        """

        result: list[str] = []

        for symbol in symbols:
            normalized = str(
                symbol
            ).strip().upper()

            if (
                normalized
                and normalized not in result
            ):
                result.append(
                    normalized
                )

        if not result:
            raise ValueError(
                "MarketLoop requires at least one symbol"
            )

        return result

    @staticmethod
    def _safe_float(
        value: Any,
    ) -> float:
        """
        Convert a value into a finite float-compatible number.
        """

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
    def _safe_payload(
        value: Any,
    ) -> Any:
        """
        Return a diagnostic-safe representation.
        """

        if isinstance(
            value,
            (
                dict,
                list,
                tuple,
                str,
                int,
                float,
                bool,
                type(None),
            ),
        ):
            return value

        return repr(
            value
        )

    # =========================================================
    # HEALTH
    # =========================================================

    def health(self) -> dict[str, Any]:
        """
        Return concise health information.
        """

        with self.lock:
            thread_alive = bool(
                self.thread
                and self.thread.is_alive()
            )

            healthy = bool(
                (
                    not self.running
                    or thread_alive
                )
                and self.metrics[
                    "errors"
                ] == 0
            )

            return {
                "healthy": healthy,
                "running": self.running,
                "thread_alive": thread_alive,
                "version": self.VERSION,
                "errors": self.metrics[
                    "errors"
                ],
            }

    # =========================================================
    # STATUS
    # =========================================================

    def status(self) -> dict[str, Any]:
        """
        Return complete MarketLoop runtime diagnostics.
        """

        with self.lock:
            thread_alive = bool(
                self.thread
                and self.thread.is_alive()
            )

            return {
                "name": self.NAME,
                "version": self.VERSION,
                "running": self.running,
                "thread_alive": thread_alive,
                "started_at": self.started_at,
                "stopped_at": self.stopped_at,
                "symbols": list(
                    self.symbols
                ),
                "symbol_count": len(
                    self.symbols
                ),
                "interval": self.interval,
                "last_cycle": self.last_cycle,
                "last_cycle_duration": (
                    self.last_cycle_duration
                ),
                "metrics": dict(
                    self.metrics
                ),
                "last_signals": dict(
                    self.last_signals
                ),
                "last_executions": dict(
                    self.last_executions
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
                "dependencies": {
                    "brain": self.brain is not None,
                    "market_feed": (
                        self.market_feed
                        is not None
                    ),
                    "execution": (
                        self.execution
                        is not None
                    ),
                    "event_bus": (
                        self.event_bus
                        is not None
                    ),
                    "decision_adapter": True,
                },
            }

    # =========================================================
    # REPRESENTATION
    # =========================================================

    def __repr__(self) -> str:
        return (
            f"<{self.NAME} "
            f"version={self.VERSION} "
            f"running={self.running} "
            f"symbols={len(self.symbols)}>"
        )