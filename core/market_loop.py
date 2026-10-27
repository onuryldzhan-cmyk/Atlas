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

import json
import math
import logging
import threading
import time
import traceback

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

from atlas_security import sanitize_sensitive_data

from analysis.evidence_status import MarketDataEvidenceStatus
from analysis.world_analysis_engine import WorldAnalysisEngine

from atlas_finance.market_data.fear_greed_provider import (
    classify_fear_greed_band,
)
from atlas_finance.market_data.treasury_yield_provider import (
    classify_ten_year_move,
)

from core.candle_processor import (
    CandleContractError,
    CandleProcessor,
)
from core.brain_decision_contract import BrainDecisionPayload, ContractViolation
from core.decision_adapter import DecisionAdapter
from core.market_cycle import MarketCycleTracker, RegimeGateConfig, permission
from core.execution_models import normalize_risk
from core.position_sizing import PositionSizingService, SizingInputs, SizingStatus
from core.technical_analyzer import TechnicalAnalyzer


logger = logging.getLogger(
    "AtlasAI.MarketLoop"
)

# Durable operational telemetry (registry v4.71,
# GRANT-DURABLE-OPERATIONAL-LOGGING): one JSON-lines record per worker
# cycle per symbol carrying candle age and cycle duration, the evidence
# the open S-3 and M-2 threshold decisions need.
#
# It never propagates, so no telemetry record reaches the console
# handlers - with or without a durable file attached (a failed file write
# yields at most one generic warning from core.logger, never a record).
# The composition root attaches the file only when ATLAS_LOG_DIRECTORY is
# set.
# The level is pinned so an unconfigured root level cannot silently
# drop records once a file is attached.
TELEMETRY_LOGGER_NAME = "AtlasAI.MarketLoop.Telemetry"
TELEMETRY_SCHEMA_VERSION = 1

telemetry_logger = logging.getLogger(
    TELEMETRY_LOGGER_NAME
)
telemetry_logger.propagate = False
telemetry_logger.setLevel(
    logging.INFO
)

_EPOCH = datetime(
    1970,
    1,
    1,
    tzinfo=UTC,
)


class _Continue:
    """Marker a MarketLoop ``_symbol_*`` phase returns to let process_symbol go on (T-0015).

    None cannot be the marker: process_symbol returns None as a real result ("skip this symbol").
    """

    __slots__ = ()


_CONTINUE = _Continue()


class MarketLoop:
    """
    Continuous Atlas market intelligence and execution loop.

    The MarketLoop owns market-cycle coordination only. It does not
    contain portfolio, risk, or exchange execution business logic.
    """

    VERSION = "8.2"
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

    # Recovery window for health(): an error older than this no longer
    # latches healthy=False. Cumulative metrics["errors"] is unaffected.
    HEALTH_ERROR_RECOVERY_SECONDS: float = 300.0

    # A symbol is reported stale in status()/health() when no market-data
    # fetch has succeeded for it within this many seconds. That fetch-
    # liveness flag is observability only and never gates trading. The same
    # 180s value is, separately, the BUY candle-age limit below (v5.14).
    STALENESS_THRESHOLD_SECONDS: float = 180.0

    # Registry v5.14 (owner: "ikisini de değiştir"): new risk needs fresh
    # data. A BUY is routed only when the newest closed candle's measured
    # age is within this bound; an unmeasurable age refuses too. SELL is
    # never gated here - reducing risk must not wait for a fresh feed.
    # Same bound as the fetch staleness above, so the two agree.
    BUY_MAX_CANDLE_AGE_SECONDS: float = STALENESS_THRESHOLD_SECONDS

    # Task 019 (registry v5.103): the trading-session guard of a market that closes (forex: Sunday 17:00 to
    # Friday 17:00 New York). None - the crypto default - means the market never closes and nothing changes.
    # Set by the composition root in forex mode; while it reports the market closed, neither a BUY nor a SELL is
    # routed (a paper fill at a weekend's stale price would be fiction). A guard that raises counts as closed.
    market_session_open: Callable[[datetime], bool] | None = None

    # Task 022 (registry v5.105): the window before a market's weekly close in which no new risk is opened
    # (forex: the last hour before Friday 17:00 New York). None - the crypto default - means no such window.
    # Only a BUY is held back; a SELL (a reduction) is never blocked by it. A check that raises counts as "in the
    # window" (fail closed).
    market_entry_blocked: Callable[[datetime], bool] | None = None

    # Task 023 (registry v5.106, policy manifest v3): the exit guard's run for this market, called once at the start
    # of every cycle - before any symbol's decision, so a protective exit precedes new-risk decisions. None (crypto)
    # means the guard is not run from the cycle. A runner that raises is logged; the cycle continues.
    exit_guard_runner: Callable[[datetime], Any] | None = None

    # Candle age (registry v4.71): time from the newest closed candle's
    # own exchange close_time to the cycle's processing cutoff. This is
    # a different measurement from the fetch-liveness staleness above
    # and is deliberately kept apart from it: it is measured and logged
    # only, compared against nothing, and never reaches status(),
    # health(), decisions, or execution. Every status other than
    # MEASURED carries no age at all - an age is never guessed.
    CANDLE_AGE_MEASURED = "MEASURED"
    CANDLE_AGE_NO_CLOSED_CANDLE = "UNAVAILABLE_NO_CLOSED_CANDLE"
    CANDLE_AGE_CLOSE_TIME_MISSING = "UNAVAILABLE_CLOSE_TIME_MISSING"
    CANDLE_AGE_CLOSE_TIME_MALFORMED = "UNAVAILABLE_CLOSE_TIME_MALFORMED"
    CANDLE_AGE_CLOSE_TIME_NOT_PROVIDER_SUPPLIED = (
        "UNAVAILABLE_CLOSE_TIME_NOT_PROVIDER_SUPPLIED"
    )
    CANDLE_AGE_CLOSE_TIME_AFTER_CUTOFF = (
        "UNAVAILABLE_CLOSE_TIME_AFTER_CUTOFF"
    )
    CANDLE_AGE_CUTOFF_MALFORMED = "UNAVAILABLE_CUTOFF_MALFORMED"
    CANDLE_AGE_COMPUTATION_ERROR = "UNAVAILABLE_COMPUTATION_ERROR"
    CANDLE_AGE_NOT_MEASURED_THIS_CYCLE = "NOT_MEASURED_THIS_CYCLE"

    def __init__(
        self,
        brain: Any,
        market_feed: Any,
        execution: Any | None = None,
        event_bus: Any | None = None,
        symbols: list[str] | tuple[str, ...] | None = None,
        interval: float = 10.0,
        position_sizing_service: PositionSizingService | None = None,
        sentiment_provider: Any | None = None,
        macro_provider: Any | None = None,
        market_risk_provider: Any | None = None,
        regime_observation: bool = False,
        regime_gate: RegimeGateConfig | None = None,
        regime_feed: Any | None = None,
    ) -> None:
        self.brain = brain
        self.market_feed = market_feed
        self.execution = execution
        self.event_bus = event_bus
        self.position_sizing_service = position_sizing_service

        # Fear & Greed provider (registry v4.66). Injected by the
        # composition root; None keeps sentiment UNAVAILABLE_NO_PROVIDER.
        # Only plain values derived from it ever reach WorldAnalysisEngine.
        self.sentiment_provider = sentiment_provider

        # Treasury yield provider and realized-volatility regime provider
        # (registry v4.79). Injected by the composition root exactly like
        # the sentiment provider; None keeps the macro / market_risk slot
        # UNAVAILABLE_NO_PROVIDER. The market-risk provider is a
        # fusion-input vote only and has no connection to RiskEngine.
        self.macro_provider = macro_provider
        self.market_risk_provider = market_risk_provider

        # Task 009 (registry v5.93): closed 1H/4H/1D regime tracking (core.market_cycle). With
        # regime_observation False and no enabled gate (the defaults) nothing is fetched, no
        # metric or status key appears, and every decision is byte-identical. Observation only
        # records the regime; the BUY gate (regime_gate.enabled, default OFF, switched on only
        # after evidence measured on the runtime rule and an owner signature) can only turn a
        # BUY into a skip or shrink its proposed size - never create, enlarge or touch a SELL.
        # Review 17: regime bars come from a dedicated regime_feed, never market_feed, so a
        # regime fetch failure can never count toward (or latch) the 1m feed's degradation.
        if regime_gate is not None and not isinstance(regime_gate, RegimeGateConfig):
            raise ValueError("regime_gate must be a RegimeGateConfig")
        if not isinstance(regime_observation, bool):
            raise ValueError("regime_observation must be a bool")
        self.regime_gate = regime_gate if regime_gate is not None else RegimeGateConfig()
        if (regime_observation or self.regime_gate.enabled) and (
            regime_feed is None or regime_feed is market_feed
        ):
            raise ValueError("regime tracking needs its own regime_feed, separate from market_feed")
        self.regime_feed = regime_feed
        self._deferred_regime_observations: list[tuple[str, dict[str, Any], datetime]] | None = None
        self.market_cycle = (
            MarketCycleTracker(self._fetch_regime_bars, self.regime_gate)
            if regime_observation or self.regime_gate.enabled
            else None
        )

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

        # Phase-2 D1: monotonic time the worker last finished a cycle. This,
        # not thread liveness, is what "the loop is progressing" means.
        self.last_loop_progress_monotonic: float | None = None

        # Latest candle-age measurement per symbol (registry v4.71).
        # Not fetch liveness: see CANDLE_AGE_MEASURED above. Each entry
        # records the worker cycle it was taken in, so a symbol that was
        # not measured in a cycle is never reported with an older age.
        self.last_candle_age: dict[str, dict[str, Any]] = {}
        self._telemetry_cycle_sequence = 0
        # The cycle number of the worker running on the current thread.
        # Per-thread, so a measurement is tagged with the cycle of the
        # worker that took it even if a second worker ever overlaps.
        self._telemetry_cycle = threading.local()

        self.last_signals: dict[str, dict[str, Any]] = {}

        # Display-only copy of the macro / market_risk evidence
        # WorldAnalysisEngine already attached to this cycle's market_data
        # (registry v4.79), stored beside last_signals under the same lock.
        # DecisionAdapter.normalize drops market_state, so without this the
        # dashboard could show only the vote, never the 10Y move, curve or
        # volatility regime behind it. Nothing in the decision, risk or
        # execution path reads this attribute.
        self.last_agent_evidence: dict[str, dict[str, Any]] = {}
        self.last_executions: dict[str, dict[str, Any]] = {}

        # Last successfully processed closed candle per symbol.
        #
        # Example:
        # {
        #     "BTCUSDT": "open:1785160800000"
        # }
        self.last_processed_candles: dict[str, str] = {}
        # Observation only (registry v5.72): the last closed candles per
        # symbol, as immutable (open_time_ms, open, high, low, close) tuples
        # for the read-only price chart. Never read by the decision path.
        self.recent_candles: dict[str, tuple[tuple[int, float, float, float, float], ...]] = {}

        # Last time a market-data fetch actually delivered candles for
        # each symbol, independent of whether those candles were new.
        # A call that returns no bars does not count, so a symbol whose
        # provider only ever returns [] stays absent here and is
        # reported stale. Used only for staleness reporting - never
        # gates decisions.
        self.last_symbol_fetch_success_at: dict[str, datetime] = {}

        # Execution idempotency state.
        #
        # pending:
        #   Execution has been claimed but has not returned yet.
        #
        # completed:
        #   Execution returned a terminal result and must not
        #   be submitted again.
        self.pending_execution_fingerprints: set[str] = set()

        self.completed_execution_fingerprints: dict[
            str,
            dict[str, Any],
        ] = {}

        self.metrics: dict[str, int | float] = {
            "cycles": 0,
            "symbols_scanned": 0,
            "symbols_skipped": 0,
            "closed_candles_processed": 0,
            "duplicate_candles_skipped": 0,
            "open_candles_excluded": 0,
            "market_data_contract_violations": 0,
            "decisions_received": 0,
            "decisions_normalized": 0,
            "decisions_rejected": 0,
            "hold_decisions": 0,
            "sell_without_position_skipped": 0,
            "buy_stale_data_skipped": 0,
            "duplicate_decisions_skipped": 0,
            "duplicate_executions_skipped": 0,
            "execution_requests": 0,
            "executions_completed": 0,
            "executions_rejected": 0,
            "execution_failures": 0,
            "errors": 0,
            "latency": 0.0,
            "backfill_gap_exceeded": 0,
        }

        self.errors: list[dict[str, Any]] = []

        # Task 013 (registry v5.97): observation only - contract rejections per reason code and the
        # latest one, for the readiness check and the /system page. Never read by the decision path.
        self._contract_rejections: dict[str, int] = {}
        self._last_contract_rejection: dict[str, str] | None = None

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
            with self.lock:
                self._telemetry_cycle_sequence += 1

                cycle_sequence = (
                    self._telemetry_cycle_sequence
                )

            self._telemetry_cycle.sequence = cycle_sequence

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

                self.last_loop_progress_monotonic = time.monotonic()

            # After the duration is measured, so writing telemetry is
            # never inside the timed region.
            self._emit_cycle_telemetry(
                cycle_sequence
            )

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

        The processing clock is read exactly once here. Every symbol in
        the cycle is evaluated against that single explicit cutoff, and
        no component below MarketLoop reads a clock to decide candle
        closure.
        """

        processing_cutoff = self._processing_cutoff()

        runner = self.exit_guard_runner
        if runner is not None:
            try:
                runner(processing_cutoff)
            except Exception:
                logger.exception("exit guard run failed this cycle")

        # Review 17 F2: observe-only regime fetches wait until every symbol of the cycle
        # has been routed, so no symbol's execution waits on another symbol's regime I/O.
        if self.market_cycle is not None and not self.regime_gate.enabled:
            self._deferred_regime_observations = []

        try:
            for symbol in tuple(self.symbols):
                if not self.running:
                    break

                self.process_symbol(
                    symbol,
                    processing_cutoff=processing_cutoff,
                )
        finally:
            deferred = self._deferred_regime_observations or []
            self._deferred_regime_observations = None

        for symbol, decision, cutoff in deferred:
            if not self.running:
                break

            self._observe_regime(
                symbol,
                decision,
                cutoff,
            )

    @staticmethod
    def _processing_cutoff() -> datetime:
        """
        Return the single cycle cutoff.

        MarketLoop is the only clock authority on the market-data path.
        """

        return datetime.now(
            UTC
        )

    # =========================================================
    # SYMBOL PIPELINE
    # =========================================================

    def process_symbol(
        self,
        symbol: str,
        *,
        processing_cutoff: datetime | None = None,
    ) -> dict[str, Any] | None:
        """
        Execute the full intelligence pipeline for one symbol.

        Args:
            symbol:
                Market symbol to process.
            processing_cutoff:
                The explicit cycle cutoff supplied by run_cycle(). When
                a direct caller omits it, MarketLoop reads the clock
                here because it is the market-data clock authority.
                Components below MarketLoop never do.
        """

        symbol = str(
            symbol
        ).strip().upper()

        if processing_cutoff is None:
            processing_cutoff = self._processing_cutoff()

        try:
            # T-0015: the phases are _symbol_* helpers; each returns its
            # terminal result (None is a real 'skip' result here) or _CONTINUE.
            closed_candles, terminal = self._symbol_closed_candles(
                symbol,
                processing_cutoff,
            )

            if not isinstance(terminal, _Continue):
                return terminal

            candle_identity, terminal = self._symbol_new_candle_identity(
                symbol,
                closed_candles,
            )

            if not isinstance(terminal, _Continue):
                return terminal

            normalized_decision, market_data, terminal = self._symbol_decide(
                symbol,
                closed_candles,
            )

            if not isinstance(terminal, _Continue):
                return terminal

            # Mark the candle only after Brain output has been
            # normalized successfully. Failed cycles may retry.
            with self.lock:
                self.last_processed_candles[
                    symbol
                ] = candle_identity

                self.last_signals[
                    symbol
                ] = normalized_decision

                self.last_agent_evidence[
                    symbol
                ] = self._agent_evidence_snapshot(
                    market_data
                )

            self._increment_metric(
                "closed_candles_processed"
            )

            normalized_decision.setdefault(
                "metadata",
                {},
            )

            normalized_decision["metadata"].update(
                {
                    "candle_identity": candle_identity,
                    "closed_candle_only": True,
                    "market_loop_version": self.VERSION,
                }
            )

            self.publish(
                "ATLAS_DECISION",
                normalized_decision,
            )

            # Review 16 L1 / review 17 F2: the gate needs the regime before the BUY checks;
            # observation alone runs after routing (inside run_cycle, after every symbol of
            # the cycle), so its network I/O never sits before a routing in the same cycle.
            observe_late = (
                self.market_cycle is not None
                and not self.regime_gate.enabled
            )

            if self.market_cycle is not None and not observe_late:
                self._observe_regime(
                    symbol,
                    normalized_decision,
                    processing_cutoff,
                )

            terminal = self._symbol_execution_gate(
                symbol,
                normalized_decision,
                closed_candles,
                processing_cutoff,
            )

            if not isinstance(terminal, _Continue):
                if observe_late:
                    self._observe_regime_late(
                        symbol,
                        normalized_decision,
                        processing_cutoff,
                    )

                return terminal

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

            if observe_late:
                self._observe_regime_late(
                    symbol,
                    normalized_decision,
                    processing_cutoff,
                )

            return result

        except CandleContractError as exc:
            # Ambiguous or unordered market data. The symbol fails
            # closed for this cycle instead of guessing a winner.
            self._increment_metric(
                "symbols_skipped"
            )

            self._increment_metric(
                "market_data_contract_violations"
            )

            logger.error(
                "%s skipped: %s | %s",
                symbol,
                exc.reason,
                exc,
            )

            return {
                "status": "SKIPPED",
                "reason": exc.reason,
                "symbol": symbol,
                "detail": str(
                    exc
                ),
            }

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

    def _symbol_closed_candles(
        self,
        symbol: str,
        processing_cutoff: datetime,
    ) -> tuple[Any, Any]:
        """Load, normalize and keep only closed candles; at least 50 are required."""

        candles = self._load_candles(
            symbol
        )

        if not candles:
            self._increment_metric(
                "symbols_skipped"
            )
            return None, None

        # Recorded only once real bars are in hand, never merely
        # because the provider call did not raise. A provider that
        # keeps returning [] - a delisted symbol, a silently failing
        # API, empty-response rate limiting - must not refresh
        # freshness, or staleness reporting would render the absence
        # of data as positive evidence of data (NB-4).
        with self.lock:
            self.last_symbol_fetch_success_at[
                symbol
            ] = datetime.now(
                UTC
            )

        normalized_candles = self.processor.normalize(
            candles,
            processing_cutoff=processing_cutoff,
        )

        if not normalized_candles:
            self._increment_metric(
                "symbols_skipped"
            )
            return None, None

        closed_candles = self.processor.closed_candles(
            normalized_candles
        )

        # Measured before any skip below, so a duplicate or
        # insufficient-history cycle still records how old the
        # newest closed candle is. Never raises.
        self._record_candle_age(
            symbol,
            closed_candles,
            processing_cutoff,
        )

        open_candle_count = (
            len(normalized_candles)
            - len(closed_candles)
        )

        if open_candle_count > 0:
            self._increment_metric(
                "open_candles_excluded",
                open_candle_count,
            )

        if not closed_candles:
            logger.info(
                "%s skipped: no closed candles available",
                symbol,
            )

            self._increment_metric(
                "symbols_skipped"
            )

            return None, {
                "status": "SKIPPED",
                "reason": "NO_CLOSED_CANDLES",
                "symbol": symbol,
            }

        if len(closed_candles) < 50:
            logger.warning(
                "%s skipped: insufficient closed candles=%s",
                symbol,
                len(closed_candles),
            )

            self._increment_metric(
                "symbols_skipped"
            )

            return None, {
                "status": "SKIPPED",
                "reason": "INSUFFICIENT_CLOSED_CANDLES",
                "symbol": symbol,
                "candle_count": len(
                    closed_candles
                ),
            }

        return closed_candles, _CONTINUE

    def _symbol_new_candle_identity(
        self,
        symbol: str,
        closed_candles: Any,
    ) -> tuple[Any, Any]:
        """Remember the bars, identify the newest closed candle and skip one already processed."""

        self._remember_candles(symbol, closed_candles)
        candle_identity = (
            self.processor.latest_closed_identity(
                closed_candles
            )
        )

        if candle_identity is None:
            logger.warning(
                "%s skipped: closed candle identity unavailable",
                symbol,
            )

            self._increment_metric(
                "symbols_skipped"
            )

            return None, {
                "status": "SKIPPED",
                "reason": "CANDLE_IDENTITY_UNAVAILABLE",
                "symbol": symbol,
            }

        with self.lock:
            previous_identity = (
                self.last_processed_candles.get(
                    symbol
                )
            )

        self._check_backfill_gap(
            symbol,
            previous_identity=previous_identity,
            closed_candles=closed_candles,
        )

        if previous_identity == candle_identity:
            self._increment_metric(
                "duplicate_candles_skipped"
            )

            logger.debug(
                "%s duplicate closed candle skipped | %s",
                symbol,
                candle_identity,
            )

            return None, {
                "status": "SKIPPED",
                "reason": "DUPLICATE_CLOSED_CANDLE",
                "symbol": symbol,
                "candle_identity": candle_identity,
            }

        return candle_identity, _CONTINUE

    def _symbol_decide(
        self,
        symbol: str,
        closed_candles: Any,
    ) -> tuple[Any, Any, Any]:
        """Technical analysis, world market data and the Brain's decision, normalized."""

        analysis = self.technical.analyze(
            closed_candles
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

            return None, None, None

        price = self.processor.latest_closed_price(
            closed_candles
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

            return None, None, None

        score = self.calculate_score(
            analysis
        )

        market_data = self.world.build_market_data(
            symbol,
            price,
            analysis,
            score,
            sentiment_input=self._with_funding(self._sentiment_input(), symbol),
            macro_input=self._macro_input(),
            market_risk_input=self._market_risk_input(
                closed_candles
            ),
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

            return None, None, None

        self._increment_metric(
            "decisions_normalized"
        )

        # Task 012 (registry v5.96): the typed Brain -> MarketLoop contract. A decision that
        # breaks it is dropped fail-closed before any execution gate, like a failed
        # normalization, so the candle is retried next cycle. A valid decision passes unchanged.
        try:
            BrainDecisionPayload.from_decision(
                normalized_decision,
                expected_symbol=symbol,
                now=self._decision_contract_now(),
            )
        except ContractViolation as violation:
            self._increment_metric(
                "decisions_rejected"
            )
            self._increment_metric(
                "decision_contract_rejected"
            )

            with self.lock:
                self._contract_rejections[violation.code] = (
                    self._contract_rejections.get(violation.code, 0) + 1
                )
                self._last_contract_rejection = {
                    "reason": violation.code,
                    "at": datetime.now(UTC).isoformat(),
                }

            logger.warning(
                "%s decision rejected by the Brain decision contract: %s",
                symbol,
                violation,
            )

            self.publish(
                "DECISION_CONTRACT_REJECTED",
                {
                    "symbol": symbol,
                    "reason": violation.code,
                    "detail": str(violation),
                    "decision": self._safe_payload(
                        normalized_decision
                    ),
                    "timestamp": datetime.now(
                        UTC
                    ).isoformat(),
                },
            )

            return None, None, None

        return normalized_decision, market_data, _CONTINUE

    @staticmethod
    def _decision_contract_now() -> datetime:
        """The clock the decision contract's staleness rule reads (a seam for tests)."""

        return datetime.now(
            UTC
        )

    def _symbol_execution_gate(
        self,
        symbol: str,
        normalized_decision: dict[str, Any],
        closed_candles: Any,
        processing_cutoff: datetime,
    ) -> Any:
        """HOLD, invalid action, missing manager, SELL of a flat symbol and stale-data BUY end the cycle here."""

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

        guard = self.market_session_open
        if guard is not None:
            try:
                session_open = guard(processing_cutoff) is True
            except Exception:
                logger.exception("%s market session guard failed; treated as closed", symbol)
                session_open = False
            if not session_open:
                self._increment_metric(
                    "market_closed_skipped"
                )

                logger.info(
                    "%s %s not routed: the market is closed",
                    symbol,
                    action,
                )

                result = {
                    "status": "SKIPPED",
                    "reason": "MARKET_CLOSED",
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

        blocked_check = self.market_entry_blocked
        if action == "BUY" and blocked_check is not None:
            try:
                entry_blocked = blocked_check(processing_cutoff) is not False
            except Exception:
                logger.exception("%s pre-close check failed; no new risk", symbol)
                entry_blocked = True
            if entry_blocked:
                self._increment_metric(
                    "buy_pre_close_skipped"
                )

                logger.info(
                    "%s BUY not routed: no new risk before the weekly close",
                    symbol,
                )

                result = {
                    "status": "SKIPPED",
                    "reason": "PRE_CLOSE_NO_NEW_RISK",
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

        if action == "SELL" and self._sell_symbol_known_flat(symbol):
            # Registry v5.04: Atlas is LONG-only, so a SELL of a symbol the
            # durable book shows as not held has nothing to act on. It is
            # treated as HOLD instead of being routed into a rejection.
            self._increment_metric(
                "sell_without_position_skipped"
            )

            logger.info(
                "%s decision SELL with no held position | treated as HOLD, "
                "execution skipped",
                symbol,
            )

            result = {
                "status": "SKIPPED",
                "reason": "NO_POSITION_TO_SELL",
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

        if action == "BUY":
            age, age_status = self._candle_age(
                closed_candles[-1] if closed_candles else None,
                processing_cutoff,
            )

            if (
                age_status != self.CANDLE_AGE_MEASURED
                or age is None
                or age > self.BUY_MAX_CANDLE_AGE_SECONDS
            ):
                self._increment_metric(
                    "buy_stale_data_skipped"
                )

                logger.warning(
                    "%s BUY not routed: market data not fresh "
                    "(candle_age=%s status=%s limit=%ss)",
                    symbol,
                    age,
                    age_status,
                    self.BUY_MAX_CANDLE_AGE_SECONDS,
                )

                result = {
                    "status": "SKIPPED",
                    "reason": "STALE_MARKET_DATA",
                    "symbol": symbol,
                    "action": action,
                    "candle_age_seconds": age,
                    "candle_age_status": age_status,
                    "timestamp": datetime.now(
                        UTC
                    ).isoformat(),
                }

                with self.lock:
                    self.last_executions[
                        symbol
                    ] = result

                return result

        if action == "BUY" and self.regime_gate.enabled:
            vetoed = self._regime_gate_buy(
                symbol,
                normalized_decision,
            )

            if vetoed is not None:
                return vetoed

        return _CONTINUE

    # =========================================================
    # MARKET REGIME (Task 009, registry v5.93)
    # =========================================================

    def _fetch_regime_bars(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> Any:
        """Closed higher-timeframe bars from the dedicated regime feed (core.market_cycle filters them)."""

        candles_method = getattr(
            self.regime_feed,
            "candles",
            None,
        )

        if not callable(
            candles_method
        ):
            raise AttributeError(
                "regime_feed does not provide candles()"
            )

        return candles_method(
            symbol,
            interval=interval,
            limit=limit,
        )

    def _observe_regime_late(
        self,
        symbol: str,
        normalized_decision: dict[str, Any],
        processing_cutoff: datetime,
    ) -> None:
        """Observe-only: defer to the end of a running cycle, else observe now (direct callers)."""

        deferred = self._deferred_regime_observations

        if deferred is not None:
            deferred.append(
                (symbol, normalized_decision, processing_cutoff)
            )
            return

        self._observe_regime(
            symbol,
            normalized_decision,
            processing_cutoff,
        )

    def _observe_regime(
        self,
        symbol: str,
        normalized_decision: dict[str, Any],
        processing_cutoff: datetime,
    ) -> None:
        """Record this cycle's regime; never raises; observation alone never touches the decision."""

        try:
            snapshot = self.market_cycle.observe(
                symbol,
                int(processing_cutoff.timestamp() * 1000),
            )
        except Exception as exc:
            self._record_error(
                phase="market_regime",
                error=exc,
            )
            snapshot = {
                "regime": "UNKNOWN",
                "anchor_reason": f"OBSERVER_ERROR:{type(exc).__name__}",
            }

        if self.regime_gate.enabled:
            # Only the gate counts and annotates; observation alone leaves the decision and
            # the metrics untouched (its state lives in market_cycle and status()).
            self._increment_metric(
                "regime_observations"
            )

            metadata = normalized_decision.setdefault(
                "metadata",
                {},
            )

            if isinstance(metadata, dict):
                metadata["market_regime"] = snapshot.get(
                    "regime",
                    "UNKNOWN",
                )

    def _regime_gate_buy(
        self,
        symbol: str,
        normalized_decision: dict[str, Any],
    ) -> dict[str, Any] | None:
        """BUY permissibility under the symbol's regime; a refusal is a SKIPPED result."""

        snapshot = (
            self.market_cycle.snapshot(symbol)
            if self.market_cycle is not None
            else None
        ) or {"regime": "UNKNOWN"}

        regime = str(snapshot.get("regime", "UNKNOWN"))

        verdict = permission(
            self.regime_gate.archetype,
            regime,
        )

        if not verdict.allowed:
            self._increment_metric(
                "buy_regime_vetoed"
            )

            logger.info(
                "%s BUY not routed: regime %s refuses %s (%s)",
                symbol,
                regime,
                self.regime_gate.archetype,
                verdict.reason,
            )

            result = {
                "status": "SKIPPED",
                "reason": verdict.reason,
                "symbol": symbol,
                "action": "BUY",
                "market_regime": regime,
                "strategy_archetype": self.regime_gate.archetype,
                "timestamp": datetime.now(
                    UTC
                ).isoformat(),
            }

            with self.lock:
                self.last_executions[
                    symbol
                ] = result

            return result

        metadata = normalized_decision.setdefault(
            "metadata",
            {},
        )

        if isinstance(metadata, dict):
            metadata["regime_scale"] = format(
                verdict.scale,
                "f",
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
    # BACKFILL GAP DETECTION
    # =========================================================

    def _check_backfill_gap(
        self,
        symbol: str,
        *,
        previous_identity: str | None,
        closed_candles: list[dict[str, Any]],
    ) -> None:
        """
        Detect an outage longer than the just-fetched backfill window.

        Each cycle refetches the latest closed candles, which silently
        self-heals any outage shorter than that window - correct
        behavior, left unchanged here. But when the previous cycle's
        last-processed candle predates the oldest candle in this fetch
        by more than the fetched window itself spans, the candles
        between them were never retrieved and are permanently lost.
        This only detects and reports that condition; it never attempts
        to backfill it (CandleProcessor's fail-closed philosophy: detect
        and report, don't silently repair).
        """

        previous_open_time_ms = (
            self._identity_open_time_ms(
                previous_identity
            )
        )

        if previous_open_time_ms is None:
            return

        if not closed_candles:
            return

        oldest_open_time_ms = closed_candles[0].get(
            "open_time"
        )

        newest_open_time_ms = closed_candles[-1].get(
            "open_time"
        )

        if (
            oldest_open_time_ms is None
            or newest_open_time_ms is None
        ):
            return

        if oldest_open_time_ms <= previous_open_time_ms:
            # The previous last-processed candle still falls inside
            # (or at the edge of) this fetch's window - no gap.
            return

        window_span_ms = (
            newest_open_time_ms
            - oldest_open_time_ms
        )

        gap_ms = (
            oldest_open_time_ms
            - previous_open_time_ms
        )

        if gap_ms <= window_span_ms:
            return

        gap_start_iso = self._milliseconds_to_iso(
            previous_open_time_ms
        )

        gap_end_iso = self._milliseconds_to_iso(
            oldest_open_time_ms
        )

        logger.warning(
            "%s backfill gap exceeded fetch window: "
            "data loss between %s and %s",
            symbol,
            gap_start_iso,
            gap_end_iso,
        )

        self._increment_metric(
            "backfill_gap_exceeded"
        )

        self.publish(
            "MARKET_DATA_BACKFILL_GAP_EXCEEDED",
            {
                "symbol": symbol,
                "gap_start": gap_start_iso,
                "gap_end": gap_end_iso,
                "gap_minutes": round(
                    gap_ms / 60_000,
                    2,
                ),
            },
        )

    @staticmethod
    def _identity_open_time_ms(
        identity: str | None,
    ) -> int | None:
        """
        Parse the epoch-millisecond open time out of a candle identity.

        Only the "open:<ms>" identity form carries a usable timestamp.
        Any other form (or none) is not a comparable time and is
        treated as unavailable rather than guessed.
        """

        if (
            not isinstance(
                identity,
                str,
            )
            or not identity.startswith(
                "open:"
            )
        ):
            return None

        try:
            return int(
                identity.split(
                    ":",
                    1,
                )[1]
            )

        except (ValueError, IndexError):
            return None

    @staticmethod
    def _milliseconds_to_iso(
        value: int,
    ) -> str:
        return datetime.fromtimestamp(
            value / 1000,
            tz=UTC,
        ).isoformat()

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

        The method provides an idempotency boundary using:

            symbol + candle identity + action

        Only one caller may own a fingerprint at a time.
        """

        symbol = str(
            decision.get(
                "symbol",
                "UNKNOWN",
            )
        ).strip().upper()

        action = str(
            decision.get(
                "action",
                "UNKNOWN",
            )
        ).strip().upper()

        metadata = decision.get(
            "metadata"
        )

        if not isinstance(
            metadata,
            dict,
        ):
            metadata = {}

            decision["metadata"] = metadata

        candle_identity = str(
            metadata.get(
                "candle_identity",
                "NO_CANDLE",
            )
        ).strip()

        execution_fingerprint = (
            f"{symbol}|"
            f"{candle_identity}|"
            f"{action}"
        )

        # Use the deterministic fingerprint as request_id.
        #
        # ExecutionManager already preserves a supplied
        # request_id; therefore the same logical decision has
        # the same identity across downstream components.
        decision["request_id"] = (
            execution_fingerprint
        )

        metadata.update(
            {
                "execution_fingerprint": (
                    execution_fingerprint
                ),
                "idempotency_key": (
                    execution_fingerprint
                ),
            }
        )

        # Atomic claim.
        #
        # The shared MarketLoop lock prevents two threads from
        # passing the duplicate check simultaneously.
        with self.lock:
            if (
                execution_fingerprint
                in self.pending_execution_fingerprints
            ):
                self._increment_metric(
                    "duplicate_executions_skipped"
                )

                logger.warning(
                    "%s duplicate execution pending | %s",
                    symbol,
                    execution_fingerprint,
                )

                return {
                    "status": "SKIPPED",
                    "reason": "DUPLICATE_EXECUTION_PENDING",
                    "symbol": symbol,
                    "action": action,
                    "request_id": execution_fingerprint,
                    "execution_fingerprint": (
                        execution_fingerprint
                    ),
                    "timestamp": datetime.now(
                        UTC
                    ).isoformat(),
                }

            previous_result = (
                self.completed_execution_fingerprints.get(
                    execution_fingerprint
                )
            )

            if previous_result is not None:
                self._increment_metric(
                    "duplicate_decisions_skipped"
                )

                self._increment_metric(
                    "duplicate_executions_skipped"
                )

                logger.warning(
                    "%s duplicate completed execution skipped | %s",
                    symbol,
                    execution_fingerprint,
                )

                return {
                    "status": "SKIPPED",
                    "reason": "DUPLICATE_EXECUTION_COMPLETED",
                    "symbol": symbol,
                    "action": action,
                    "request_id": execution_fingerprint,
                    "execution_fingerprint": (
                        execution_fingerprint
                    ),
                    "previous_result": self._safe_payload(
                        previous_result
                    ),
                    "timestamp": datetime.now(
                        UTC
                    ).isoformat(),
                }

            self.pending_execution_fingerprints.add(
                execution_fingerprint
            )

        self._increment_metric(
            "execution_requests"
        )

        sizing_refusal = self._apply_position_sizing(
            action,
            decision,
            execution_fingerprint,
        )

        if sizing_refusal is not None:
            with self.lock:
                self.pending_execution_fingerprints.discard(
                    execution_fingerprint
                )

            self._increment_metric(
                "executions_rejected"
            )

            return sizing_refusal

        try:
            result = self.execution.execute(
                decision,
                market_state,
            )

        except Exception as exc:
            # Exceptions are retryable. Release the claim.
            with self.lock:
                self.pending_execution_fingerprints.discard(
                    execution_fingerprint
                )

            self._increment_metric(
                "execution_failures"
            )

            self._record_error(
                phase="execution",
                error=exc,
            )

            logger.exception(
                "%s execution routing failed",
                symbol,
            )

            return {
                "status": "FAILED",
                "reason": "EXECUTION_EXCEPTION",
                "error": str(
                    exc
                ),
                "symbol": symbol,
                "action": action,
                "request_id": execution_fingerprint,
                "execution_fingerprint": (
                    execution_fingerprint
                ),
                "timestamp": datetime.now(
                    UTC
                ).isoformat(),
            }

        result_dict = self._normalize_execution_result(
            result
        )

        result_dict.setdefault(
            "request_id",
            execution_fingerprint,
        )

        result_dict.setdefault(
            "execution_fingerprint",
            execution_fingerprint,
        )

        status = str(
            result_dict.get(
                "status",
                "UNKNOWN",
            )
        ).upper()

        success_statuses = {
            "PAPER_EXECUTED",
            "EXECUTED",
            "FILLED",
            "COMPLETED",
            "SUCCESS",
        }

        retryable_failure_statuses = {
            "FAILED",
            "ERROR",
        }

        if status in success_statuses:
            self._increment_metric(
                "executions_completed"
            )

        elif status == "REJECTED":
            self._increment_metric(
                "executions_rejected"
            )

        elif status in retryable_failure_statuses:
            self._increment_metric(
                "execution_failures"
            )

        # Complete or release the atomic claim.
        with self.lock:
            self.pending_execution_fingerprints.discard(
                execution_fingerprint
            )

            if status not in retryable_failure_statuses:
                self.completed_execution_fingerprints[
                    execution_fingerprint
                ] = dict(
                    result_dict
                )

        logger.info(
            "%s execution %s | action=%s request_id=%s",
            symbol,
            status,
            action,
            execution_fingerprint,
        )

        return result_dict

    # =========================================================
    # POSITION SIZING (Block 5C)
    # =========================================================

    def _sizing_risk_bucket(
        self,
        risk_bucket: str,
        decision: Any,
    ) -> str:
        """Bucket whose limits size this BUY (registry v5.22).

        Asks the canonical RiskEngine (RiskEngine.sizing_bucket) so the
        proposal matches what evaluate() will approve: an experiment-only
        admission is sized as EXPERIMENT_SIZING_BUCKET. Non-executable or
        unsupported levels pass through unchanged (the sizer refuses them).
        Any failure sizes as HIGH - the strictest executable bucket.
        """

        if risk_bucket not in ("LOW", "MEDIUM", "HIGH"):
            return risk_bucket

        engine = getattr(self.execution, "risk_engine", None)
        sizing_bucket = getattr(engine, "sizing_bucket", None)

        if not callable(sizing_bucket):
            return risk_bucket

        try:
            confidence = Decimal(str(decision.get("confidence"))) / Decimal("100")
            return sizing_bucket(risk_bucket, confidence).value
        except Exception:
            return "HIGH"

    def _apply_position_sizing(
        self,
        action: str,
        decision: dict[str, Any],
        request_id: str,
    ) -> dict[str, Any] | None:
        """Propose a BUY quote allocation before ``ExecutionManager.execute()``.

        Sizing happens after decision normalization and before risk
        admission: ``PositionSizingService`` proposes, ``RiskEngine`` (inside
        ``risk_check``) approves or rejects, and only ``risk_check`` may ever
        write ``approved_quote_allocation``. This method never does - it can
        only write the non-authoritative ``decision["proposed_quote_allocation"]``
        exact-Decimal transport (Block 5C B1) that ``ExecutionRequest`` carries
        losslessly through to ``_requested_quote_allocation``. ``decision["amount"]``
        is never written by this method: it stays the pre-5C compatibility
        mirror, untouched.

        Returns ``None`` to let ``decision`` proceed into ``execute()``
        unchanged - because sizing does not apply to this request, because
        this exact request identity already completed and must be answered
        from ``ExecutionManager``'s own durable duplicate cache instead,
        because durable state cannot be read safely, or because a proposal
        was written onto ``decision["proposed_quote_allocation"]``. No sizer
        configured, and every SELL or reduce-only request, take this path
        unchanged, which is what preserves Package 5B's fail-closed
        ``UNSIZED_REQUEST_REJECTED`` behaviour exactly.

        It returns a terminal rejection only for the one case that must
        never reach ``execute()``: this exact request identity already holds
        a reservation for a different amount than this evaluation just
        proposed. Letting that through would have ``risk_check`` attempt a
        second, conflicting reservation under the same id, which
        ``CapitalReservationLedger`` refuses as a collision - turning stale
        replay input into a halted runtime awaiting operator recovery, a far
        worse outcome than refusing the replay cleanly here.
        """
        sizer = self.position_sizing_service

        if action != "BUY" or sizer is None:
            return None

        manager = self.execution

        # A request this exact identity already completed - durably, via
        # ExecutionManager's own idempotency cache - must be answered from
        # that cache, not re-priced. Durable state (cash, exposure) has
        # moved past whatever earned the original approval, so recomputing a
        # proposal here would price an identical replay differently and
        # misreport a legitimate duplicate as SIZING_REPLAY_CONFLICT.
        # Returning None here, before any proposal is computed, hands the
        # request straight to execute() -> _claim_request(), which answers
        # it from completed_request_results without sizing, a new
        # reservation, a conflict, or a halt.
        if request_id in getattr(manager, "completed_request_results", {}):
            return None

        foundation = getattr(manager, "portfolio_foundation", None)
        ledger = getattr(manager, "reservation_ledger", None)

        if (
            foundation is None
            or ledger is None
            or not foundation.ready
            or not ledger.ready
        ):
            return None

        symbol = str(decision.get("symbol", "")).strip().upper()

        try:
            snapshot = foundation.snapshot()
            position = snapshot["positions"].get(symbol)

            symbol_exposure = (
                Decimal(str(position["base_quantity"]))
                * Decimal(str(position["mark_price"]))
                if position is not None
                else Decimal("0")
            )

            free_capital = snapshot["spendable_cash"] - ledger.active_reserved_capital(   # Task 025
                exclude=request_id
            )

            inputs = SizingInputs(
                request_id=request_id,
                symbol=symbol,
                risk_bucket=self._sizing_risk_bucket(
                    normalize_risk(
                        decision.get(
                            "risk",
                            decision.get("risk_level"),
                        )
                    ),
                    decision,
                ),
                durable_free_quote_capital=free_capital,
                symbol_exposure=symbol_exposure,
                committed_quote=snapshot["gross_exposure"],
            )

            proposal = sizer.propose(inputs)

        except Exception as exc:
            self._record_error(
                phase="position_sizing",
                error=exc,
            )

            logger.exception(
                "%s position sizing failed request_id=%s",
                symbol,
                request_id,
            )

            return None

        metadata = decision.get("metadata")

        if not isinstance(metadata, dict):
            metadata = {}
            decision["metadata"] = metadata

        metadata["sizing"] = dict(proposal.provenance)

        if proposal.status is not SizingStatus.PROPOSED:
            logger.info(
                "%s sizing refused request_id=%s reason=%s",
                symbol,
                request_id,
                proposal.reason_code,
            )

            return None

        proposed_allocation = proposal.proposed_quote_allocation

        if self.regime_gate.enabled:
            # Task 009: a marginal regime only ever shrinks the proposal (scale in (0, 1]);
            # the gate already refused every BUY whose regime scale is 0.
            try:
                scale = Decimal(str(metadata.get("regime_scale")))
            except Exception:
                scale = Decimal("0")

            if not scale.is_finite() or scale <= 0 or scale > 1:
                logger.warning(
                    "%s BUY sizing refused: invalid regime scale %r",
                    symbol,
                    metadata.get("regime_scale"),
                )

                request = manager.build_request(decision)

                return manager.reject(
                    "REGIME_SCALE_INVALID",
                    request,
                    details={"regime_scale": str(metadata.get("regime_scale"))},
                )

            if scale < 1:
                proposed_allocation = proposed_allocation * scale
                metadata["regime_scaled_allocation"] = format(proposed_allocation, "f")

        # A prior admission for this exact request identity already reserved
        # a specific amount. If today's inputs price the same request
        # differently, that is stale or conflicting replay input, and it
        # must be refused here - before ``execute()`` - rather than letting
        # ``risk_check`` discover it as a reservation collision.
        existing_reservation = ledger.get(request_id)

        if (
            existing_reservation is not None
            and existing_reservation.amount != proposed_allocation
        ):
            logger.warning(
                "%s sizing replay conflict request_id=%s reserved=%s proposed=%s",
                symbol,
                request_id,
                format(existing_reservation.amount, "f"),
                format(proposed_allocation, "f"),
            )

            request = manager.build_request(decision)

            return manager.reject(
                "SIZING_REPLAY_CONFLICT",
                request,
                details={
                    "reserved_amount": format(existing_reservation.amount, "f"),
                    "proposed_amount": format(
                        proposed_allocation, "f"
                    ),
                },
            )

        # The exact Decimal proposal, transported on its own dedicated field
        # (Block 5C B1) so it reaches ``risk_check`` without crossing the
        # lossy ``amount`` float mirror. ``amount`` itself is deliberately
        # left untouched: it stays compatibility-only and non-authoritative.
        decision["proposed_quote_allocation"] = proposed_allocation

        return None

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
    # SENTIMENT INPUT (registry v4.66)
    # =========================================================

    def _with_funding(self, sentiment: dict[str, Any] | None, symbol: str) -> dict[str, Any] | None:
        """Add this coin's funding-rate reading (design C) when a provider is attached. Never raises."""
        provider = getattr(self, "funding_provider", None)
        if provider is None or not isinstance(sentiment, dict):
            return sentiment
        try:
            reading = provider.rate(symbol)
        except Exception:
            logger.debug("funding rate unavailable for %s", symbol, exc_info=True)
            return sentiment
        return {**sentiment, "funding": dict(reading) if isinstance(reading, dict) else None}

    def _sentiment_input(self) -> dict[str, Any] | None:
        """
        Plain-value Fear & Greed input for WorldAnalysisEngine.

        The provider object never crosses into L4: this returns a dict of
        the raw index value and its band. The provider caches, so calling
        this every cycle does not contact the network every cycle.

        Never raises. Any provider failure, an unavailable reading, or a
        value the band classifier rejects becomes
        UNAVAILABLE_PROVIDER_ERROR with no value.
        """

        provider = self.sentiment_provider

        if provider is None:
            return None

        try:
            reading = provider.get_reading()
            available = getattr(reading, "available", None)

            if available is False:
                return self._sentiment_unavailable(
                    getattr(reading, "reason", None)
                )

            # Only the exact bool True counts; anything else is not a
            # reading this loop can trust.
            if available is not True:
                return self._sentiment_unavailable(
                    "MALFORMED_READING"
                )

            value = reading.value
            band = classify_fear_greed_band(
                value
            )
        except Exception:
            logger.exception(
                "Sentiment provider failed; sentiment unavailable this cycle"
            )
            return self._sentiment_unavailable(
                "PROVIDER_EXCEPTION"
            )

        return {
            "provider_status": MarketDataEvidenceStatus.AVAILABLE.value,
            "value": value,
            "band": band,
            "reason": "OK",
        }

    @staticmethod
    def _sentiment_unavailable(reason: Any) -> dict[str, Any]:
        return {
            "provider_status": (
                MarketDataEvidenceStatus.UNAVAILABLE_PROVIDER_ERROR.value
            ),
            "value": None,
            "band": None,
            "reason": reason if isinstance(reason, str) else "UNSPECIFIED",
        }

    # =========================================================
    # MACRO INPUT (registry v4.79)
    # =========================================================

    def _macro_input(self) -> dict[str, Any] | None:
        """
        Plain-value Treasury yield input for WorldAnalysisEngine.

        Mirrors _sentiment_input(): the provider object never crosses into
        L4, the provider caches so the network is not contacted every
        cycle, and this never raises. Any provider failure, an unavailable
        reading, or a value the move classifier rejects becomes
        UNAVAILABLE_PROVIDER_ERROR with no values.
        """

        provider = self.macro_provider

        if provider is None:
            return None

        try:
            reading = provider.get_reading()
            available = getattr(reading, "available", None)

            if available is False:
                return self._macro_unavailable(
                    getattr(reading, "reason", None)
                )

            # Only the exact bool True counts; anything else is not a
            # reading this loop can trust.
            if available is not True:
                return self._macro_unavailable(
                    "MALFORMED_READING"
                )

            change_bp = reading.ten_year_change_bp
            spread_bp = reading.curve_spread_bp
            move = classify_ten_year_move(
                change_bp
            )

            if type(spread_bp) is not int:
                return self._macro_unavailable(
                    "MALFORMED_READING"
                )

            observed_date = reading.observed_date.isoformat()
        except Exception:
            logger.exception(
                "Macro provider failed; macro unavailable this cycle"
            )
            return self._macro_unavailable(
                "PROVIDER_EXCEPTION"
            )

        return {
            "provider_status": MarketDataEvidenceStatus.AVAILABLE.value,
            "ten_year_change_bp": change_bp,
            "curve_spread_bp": spread_bp,
            "move": move,
            "observed_date": observed_date,
            "reason": "OK",
        }

    @staticmethod
    def _macro_unavailable(reason: Any) -> dict[str, Any]:
        return {
            "provider_status": (
                MarketDataEvidenceStatus.UNAVAILABLE_PROVIDER_ERROR.value
            ),
            "ten_year_change_bp": None,
            "curve_spread_bp": None,
            "move": None,
            "observed_date": None,
            "reason": reason if isinstance(reason, str) else "UNSPECIFIED",
        }

    # =========================================================
    # MARKET RISK INPUT (registry v4.79)
    # =========================================================

    def _market_risk_input(
        self,
        closed_candles: Any,
    ) -> dict[str, Any] | None:
        """
        Plain-value realized-volatility regime input for
        WorldAnalysisEngine, computed from this cycle's already-fetched
        closed candles. No data source is contacted.

        A fusion-input vote only: nothing here reads or feeds RiskEngine,
        risk_check, capital reservation, or execution. Never raises. An
        unavailable assessment (for example too little candle history
        right after a listing) becomes UNAVAILABLE_PROVIDER_ERROR with no
        values.
        """

        provider = self.market_risk_provider

        if provider is None:
            return None

        try:
            reading = provider.assess(
                closed_candles
            )
            available = getattr(reading, "available", None)

            if available is False:
                return self._market_risk_unavailable(
                    getattr(reading, "reason", None)
                )

            if available is not True:
                return self._market_risk_unavailable(
                    "MALFORMED_READING"
                )

            regime = reading.regime
            realized_volatility = reading.realized_volatility
            p20 = reading.p20
            p80 = reading.p80
            reference_windows = reading.reference_windows
        except Exception:
            logger.exception(
                "Market risk provider failed; market risk unavailable this cycle"
            )
            return self._market_risk_unavailable(
                "PROVIDER_EXCEPTION"
            )

        return {
            "provider_status": MarketDataEvidenceStatus.AVAILABLE.value,
            "regime": regime,
            "realized_volatility": realized_volatility,
            "p20": p20,
            "p80": p80,
            "reference_windows": reference_windows,
            "reason": "OK",
        }

    @staticmethod
    def _market_risk_unavailable(reason: Any) -> dict[str, Any]:
        return {
            "provider_status": (
                MarketDataEvidenceStatus.UNAVAILABLE_PROVIDER_ERROR.value
            ),
            "regime": None,
            "realized_volatility": None,
            "p20": None,
            "p80": None,
            "reference_windows": None,
            "reason": reason if isinstance(reason, str) else "UNSPECIFIED",
        }

    RECENT_CANDLE_LIMIT = 240

    def _remember_candles(self, symbol: str, closed_candles: Any) -> None:
        """Keep a small immutable copy for the chart; never raises, never blocks a decision."""
        try:
            rows = []
            for c in list(closed_candles)[-self.RECENT_CANDLE_LIMIT:]:
                rows.append((int(c["open_time"]), float(c["open"]), float(c["high"]),
                             float(c["low"]), float(c["close"])))
            self.recent_candles[symbol] = tuple(rows)
        except Exception:
            logger.debug("recent candle snapshot skipped for %s", symbol, exc_info=True)

    def _telemetry_decision(self, symbol: str) -> dict[str, Any] | None:
        decision = self.last_signals.get(symbol)
        if not isinstance(decision, dict):
            return None
        meta = decision.get("metadata") if isinstance(decision.get("metadata"), dict) else {}
        agents = meta.get("agents") if isinstance(meta.get("agents"), dict) else {}
        votes = {name: str(v.get("action")) for name, v in agents.items() if isinstance(v, dict) and v.get("action") is not None}
        conf = decision.get("confidence")
        finite = isinstance(conf, (int, float)) and not isinstance(conf, bool) and math.isfinite(conf)  # audit A-4
        # Phase-2 F1: the decision's canonical request_id (MarketLoop's
        # symbol|candle|action fingerprint, set when it reached execution) so
        # attribution joins on identity, not time; None when it never did.
        request_id = decision.get("request_id")
        return {"action": str(decision.get("action")), "confidence": conf if finite else None,
                "votes": votes, "request_id": request_id if isinstance(request_id, str) and request_id else None}

    def mark_prices(self, max_age_s: float = 300.0, now_ms: int | None = None) -> dict[str, Decimal]:
        """Last closed-candle close per symbol, only when fresh (audit F-3 mark-to-market).

        A symbol with no candle or a stale one is left out; the caller treats
        a missing price as unknown, never as zero.
        """
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        out: dict[str, Decimal] = {}
        for symbol, rows in dict(self.recent_candles).items():
            if not rows:
                continue
            open_time, close = rows[-1][0], rows[-1][4]
            if now - open_time <= max_age_s * 1000 and close > 0:
                out[symbol] = Decimal(str(close))
        return out

    def candles(self, symbol: str) -> tuple[tuple[int, float, float, float, float], ...]:
        """Read-only view of the last closed candles for one symbol (empty if none)."""
        return self.recent_candles.get(str(symbol).upper(), ())

    @staticmethod
    def _agent_evidence_snapshot(
        market_data: Any,
    ) -> dict[str, Any]:
        """
        Shallow copies of market_data's macro_evidence and
        market_risk_evidence for last_agent_evidence. An absent or
        non-dict entry (no provider configured) is recorded as None, never
        filled in.
        """

        if not isinstance(market_data, dict):
            market_data = {}

        snapshot: dict[str, Any] = {}

        for label, key in (
            ("macro", "macro_evidence"),
            ("market_risk", "market_risk_evidence"),
        ):
            evidence = market_data.get(key)
            snapshot[label] = (
                dict(evidence)
                if isinstance(evidence, dict)
                else None
            )

        return snapshot

    # =========================================================
    # EVENT BUS
    # =========================================================

    def publish(
        self,
        event_name: str,
        payload: Any,
    ) -> bool:
        """Publish a sanitized event using current or legacy contracts."""

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

        sanitized_payload = sanitize_sensitive_data(
            payload
        )

        event_payload = {
            "event": event_name,
            "payload": sanitized_payload,
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
                    sanitized_payload,
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

    def _sell_symbol_known_flat(
        self,
        symbol: str,
    ) -> bool:
        """
        True only when the durable book positively shows ``symbol`` not held.

        Any doubt - no manager, no foundation, a foundation not ready, an
        unreadable or malformed snapshot - returns False, so the SELL is
        routed to ExecutionManager, which refuses it fail-closed itself.
        """

        foundation = getattr(
            self.execution,
            "portfolio_foundation",
            None,
        )

        if foundation is None or getattr(foundation, "ready", False) is not True:
            return False

        try:
            positions = foundation.snapshot()["positions"]
        except Exception:
            logger.exception(
                "%s position lookup failed; SELL routed to execution",
                symbol,
            )
            return False

        if not isinstance(positions, dict):
            return False

        # Compare on normalized keys: a position stored under a differently
        # cased key must still count as held, so an exit is never skipped.
        wanted = str(symbol).strip().upper()
        return all(str(key).strip().upper() != wanted for key in positions)

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

        healthy reflects recent state (no error within the health
        recovery window), not lifetime-cumulative state: a historical
        transient error does not permanently latch healthy=False once
        the loop has run cleanly since. metrics["errors"] itself stays
        a lifetime-cumulative counter for other consumers and is
        reported unchanged below.

        market_data_stale (fetch liveness) is reported only - it never
        affects healthy and is not itself a trading gate. New risk is gated
        separately on the newest closed candle's age in process_symbol
        (BUY_MAX_CANDLE_AGE_SECONDS, registry v5.14).
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
                and not self._has_recent_error()
            )

            staleness = self._staleness_snapshot()

            market_data_stale = any(
                entry["stale"]
                for entry in staleness.values()
            )

            progress_at = self.last_loop_progress_monotonic

            return {
                "healthy": healthy,
                "running": self.running,
                "thread_alive": thread_alive,
                # Phase-2 D1: None until the first cycle completes.
                "loop_progress_age_seconds": (
                    None
                    if progress_at is None
                    else round(time.monotonic() - progress_at, 3)
                ),
                "loop_interval_seconds": self.interval,
                "version": self.VERSION,
                "errors": self.metrics[
                    "errors"
                ],
                "market_data_stale": (
                    market_data_stale
                ),
            }

    def _has_recent_error(self) -> bool:
        """
        Return True when the most recent recorded error is within the
        health recovery window.

        self.errors is append-only in chronological order (_record_error
        always appends), so the last entry is always the most recent -
        checking it alone is sufficient.
        """

        if not self.errors:
            return False

        last_error_time = self.errors[-1].get(
            "time"
        )

        if not isinstance(
            last_error_time,
            str,
        ):
            # A malformed diagnostic record is not evidence of recovery.
            return True

        try:
            parsed = datetime.fromisoformat(
                last_error_time
            )

        except ValueError:
            return True

        threshold = datetime.now(
            UTC
        ) - timedelta(
            seconds=(
                self.HEALTH_ERROR_RECOVERY_SECONDS
            )
        )

        return parsed >= threshold

    # =========================================================
    # CANDLE AGE AND CYCLE TELEMETRY (REGISTRY v4.71)
    # =========================================================

    @classmethod
    def _candle_age(
        cls,
        candle: dict[str, Any] | None,
        processing_cutoff: datetime | int,
    ) -> tuple[float | None, str]:
        """
        Return (candle_age_seconds, status) for one closed candle.

        Fails closed: every status other than CANDLE_AGE_MEASURED
        carries None, never a substitute value. In particular
        CandleProcessor falls back to open_time when a provider omits
        close_time, and a genuine closed kline always closes after it
        opens, so close_time <= open_time is treated as not
        provider-supplied rather than aged. A close_time after the
        cutoff is flagged, never clamped to zero.
        """

        if candle is None:
            return None, cls.CANDLE_AGE_NO_CLOSED_CANDLE

        close_time = candle.get(
            "close_time"
        )
        open_time = candle.get(
            "open_time"
        )

        if close_time is None:
            return None, cls.CANDLE_AGE_CLOSE_TIME_MISSING

        if not cls._is_epoch_milliseconds(
            close_time
        ) or not cls._is_epoch_milliseconds(
            open_time
        ):
            return None, cls.CANDLE_AGE_CLOSE_TIME_MALFORMED

        if close_time <= open_time:
            return (
                None,
                cls.CANDLE_AGE_CLOSE_TIME_NOT_PROVIDER_SUPPLIED,
            )

        if isinstance(
            processing_cutoff,
            datetime,
        ):
            if processing_cutoff.utcoffset() is None:
                return None, cls.CANDLE_AGE_CUTOFF_MALFORMED

            # Same integer floor arithmetic as the temporal authority
            # that decided closure, so age and closure agree exactly.
            cutoff_ms = (
                processing_cutoff - _EPOCH
            ) // timedelta(
                milliseconds=1
            )

        elif cls._is_epoch_milliseconds(
            processing_cutoff
        ):
            cutoff_ms = processing_cutoff

        else:
            return None, cls.CANDLE_AGE_CUTOFF_MALFORMED

        age_ms = cutoff_ms - close_time

        if age_ms < 0:
            return None, cls.CANDLE_AGE_CLOSE_TIME_AFTER_CUTOFF

        return age_ms / 1000, cls.CANDLE_AGE_MEASURED

    @staticmethod
    def _is_epoch_milliseconds(
        value: Any,
    ) -> bool:
        return isinstance(
            value,
            int,
        ) and not isinstance(
            value,
            bool,
        )

    def _record_candle_age(
        self,
        symbol: str,
        closed_candles: list[dict[str, Any]],
        processing_cutoff: datetime | int,
    ) -> None:
        """
        Store the newest closed candle's age for this symbol.

        Never raises: an unexpected error is recorded as
        CANDLE_AGE_COMPUTATION_ERROR, so this measurement can never
        reach _record_error() and so can never change health(),
        errors, metrics, or the pipeline's control flow.
        """

        try:
            candle = self.processor.latest_closed_candle(
                closed_candles
            )

            age, status = self._candle_age(
                candle,
                processing_cutoff,
            )

            close_time = (
                self._milliseconds_to_iso(
                    candle["close_time"]
                )
                if status == self.CANDLE_AGE_MEASURED
                else None
            )

        except Exception:
            logger.debug(
                "%s candle age computation failed",
                symbol,
                exc_info=True,
            )

            age = None
            status = self.CANDLE_AGE_COMPUTATION_ERROR
            close_time = None

        try:
            cutoff_text = (
                processing_cutoff.isoformat()
                if isinstance(
                    processing_cutoff,
                    datetime,
                )
                else None
            )

            with self.lock:
                self.last_candle_age[
                    symbol
                ] = {
                    "candle_age_seconds": age,
                    "candle_age_status": status,
                    "candle_close_time": close_time,
                    "processing_cutoff": cutoff_text,
                    # 0 outside a worker: never matches a worker cycle.
                    "cycle_sequence": getattr(
                        self._telemetry_cycle,
                        "sequence",
                        0,
                    ),
                }

        except Exception:
            logger.debug(
                "%s candle age could not be stored",
                symbol,
                exc_info=True,
            )

    def _emit_cycle_telemetry(
        self,
        cycle_sequence: int,
    ) -> None:
        """
        Emit one JSON-lines telemetry record per symbol for a cycle.

        Called by worker() after the cycle duration is measured. A
        symbol whose latest measurement belongs to an earlier cycle is
        reported NOT_MEASURED_THIS_CYCLE with no age, never with the
        older value. Never raises: a telemetry failure must not stop
        the worker thread.
        """

        try:
            if not telemetry_logger.isEnabledFor(
                logging.INFO
            ):
                return

            with self.lock:
                cycle_duration = self.last_cycle_duration
                cycle_finished_at = self.last_cycle
                cycle_count = self.metrics["cycles"]
                symbols = tuple(
                    self.symbols
                )
                measurements = {
                    symbol: dict(
                        self.last_candle_age[symbol]
                    )
                    for symbol in symbols
                    if symbol in self.last_candle_age
                }

            for symbol in symbols:
                measurement = measurements.get(
                    symbol
                )

                if (
                    measurement is None
                    or measurement.get(
                        "cycle_sequence"
                    )
                    != cycle_sequence
                ):
                    measurement = {
                        "candle_age_seconds": None,
                        "candle_age_status": (
                            self.CANDLE_AGE_NOT_MEASURED_THIS_CYCLE
                        ),
                        "candle_close_time": None,
                        "processing_cutoff": None,
                    }

                record = {
                    "schema_version": TELEMETRY_SCHEMA_VERSION,
                    "event": "market_loop_cycle",
                    "timestamp": cycle_finished_at,
                    "cycle": cycle_count,
                    "symbol": symbol,
                    "cycle_duration_seconds": cycle_duration,
                    "candle_age_seconds": measurement[
                        "candle_age_seconds"
                    ],
                    "candle_age_status": measurement[
                        "candle_age_status"
                    ],
                    "candle_close_time": measurement[
                        "candle_close_time"
                    ],
                    "processing_cutoff": measurement[
                        "processing_cutoff"
                    ],
                    # Agent attribution (owner MEGA 1 §11): the decision and
                    # each agent's vote, observation only; None when absent.
                    "decision": self._telemetry_decision(symbol),
                }

                telemetry_logger.info(
                    "%s",
                    json.dumps(
                        record,
                        sort_keys=True,
                        allow_nan=False,
                    ),
                )

        except Exception:
            logger.debug(
                "Market cycle telemetry emission failed",
                exc_info=True,
            )

    # =========================================================
    # STALENESS
    # =========================================================

    def _staleness_snapshot(
        self,
    ) -> dict[str, dict[str, Any]]:
        """
        Return per-symbol market-data staleness state.

        Reporting only: this must never gate or block trading/decisions.
        A symbol that has never had a successful fetch is reported stale
        with no measured age, rather than assumed fresh. A fetch counts
        as successful only when it delivered candles, so a symbol whose
        provider returns no bars indefinitely is reported stale by the
        same path as one that was never fetched at all.
        """

        now = datetime.now(
            UTC
        )

        snapshot: dict[str, dict[str, Any]] = {}

        for symbol in self.symbols:
            last_success = self.last_symbol_fetch_success_at.get(
                symbol
            )

            if last_success is None:
                snapshot[symbol] = {
                    "seconds_since_last_success": None,
                    "stale": True,
                }
                continue

            seconds_since = (
                now - last_success
            ).total_seconds()

            snapshot[symbol] = {
                "seconds_since_last_success": (
                    seconds_since
                ),
                "stale": (
                    seconds_since
                    > self.STALENESS_THRESHOLD_SECONDS
                ),
            }

        return snapshot

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

            payload = {
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
                "last_agent_evidence": dict(
                    self.last_agent_evidence
                ),
                "last_executions": dict(
                    self.last_executions
                ),
                "last_processed_candles": dict(
                    self.last_processed_candles
                ),
                "market_data_staleness": (
                    self._staleness_snapshot()
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

        # Task 009: present only when regime tracking is on, so the default status is unchanged.
        if self.market_cycle is not None:
            payload["market_regime"] = self.market_cycle.status()

        # Task 013: present only after a contract rejection, so the default status is unchanged.
        with self.lock:
            if self._contract_rejections:
                payload["decision_contract"] = {
                    "rejections_by_reason": dict(self._contract_rejections),
                    "last_rejection": dict(self._last_contract_rejection or {}),
                }

        return payload

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
