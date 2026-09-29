"""
============================================================
ATLAS AI INTELLIGENCE BRAIN v10.2
============================================================

Institutional Intelligence Orchestrator


Responsibilities
----------------

- Coordinate the complete intelligence pipeline
- Connect world, agent, reasoning, memory, confidence and risk modules
- Build the final canonical Decision object
- Preserve final decision confidence
- Store intermediate intelligence results in metadata
- Maintain lifecycle statistics and diagnostics
- Provide controlled error recovery


Architecture
------------

Market Data
    |
    v
World Model
    |
    v
Agent Fusion
    |
    v
Reasoning Engine
    |
    v
Memory Core
    |
    v
Confidence Engine
    |
    v
Risk Engine
    |
    v
Decision Builder
    |
    v
Canonical Decision


Important Contract
------------------

The final Decision confidence is owned by DecisionBuilder.

Intermediate ConfidenceEngine results must never overwrite the final
decision confidence. They are stored only as diagnostic metadata.

============================================================
"""

from __future__ import annotations

import json
import logging

from datetime import UTC, datetime
from decimal import Decimal
from math import isfinite
from typing import Any

from .atlas_memory_core import AtlasMemoryCore
from .atlas_reasoning_engine import AtlasReasoningEngine
from .atlas_world_model import AtlasWorldModel

from .intelligence.agent_fusion import AgentFusion
from .intelligence.confidence.confidence_engine import ConfidenceEngine
from .intelligence.decision_builder import DecisionBuilder
from .intelligence.memory_adapter import MemoryAdapter
from .intelligence.reasoning_adapter import ReasoningAdapter
from .intelligence.risk_engine import AdvisoryRiskScorer, regime_risk_result

from core.decision_intelligence import (
    Action,
    CanonicalDecision,
    Evidence,
    FusionPolicy,
    SignalFusion,
)

# Research evidence recording only (ADR-0008). ClaimSource is a persistence
# value type and shares nothing with core.decision_intelligence.Evidence,
# which remains the Phase-5 fusion path's own contract. It is imported from
# contracts, never from the store: this layer may describe a source but must
# not reach the infrastructure that persists it.
from data_layer.contracts import ClaimSource

import logging as _logging

# Diagnostics go to the log, not stdout (registry v5.50: 20 coins x every cycle flooded the console).
_log = _logging.getLogger(__name__)


logger = logging.getLogger(
    "AtlasAI.IntelligenceBrain"
)


class AtlasBrain:
    """
    Central Atlas intelligence orchestration layer.

    AtlasBrain coordinates intelligence modules but does not directly
    implement technical indicators, confidence mathematics, risk rules,
    or execution logic.
    """

    VERSION = "10.2"

    NAME = "AtlasIntelligenceBrain"

    STATUS_INITIALIZING = "INITIALIZING"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_ERROR = "ERROR"
    STATUS_STOPPED = "STOPPED"

    # Default change-trigger threshold for research evidence recording
    # (ADR-0008, OQ-4). Overridable per run via config.
    DEFAULT_EVIDENCE_CONVICTION_DELTA = 0.15

    def __init__(
        self,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.config = dict(
            config or {}
        )

        self.status = self.STATUS_INITIALIZING

        self.session_id = datetime.now(
            UTC
        ).strftime(
            "atlas_%Y%m%d_%H%M%S"
        )

        self.started_at = datetime.now(
            UTC
        ).isoformat()

        self.last_analysis_at: str | None = None
        self.last_symbol: str | None = None
        self.last_decision: Any | None = None
        self.last_error: dict[str, Any] | None = None

        self.cycles = 0
        self.successful_cycles = 0
        self.failed_cycles = 0
        self.errors = 0

        self.memory_core: AtlasMemoryCore | None = None
        self.reasoning_engine: AtlasReasoningEngine | None = None
        self.world: AtlasWorldModel | None = None
        self.agents: AgentFusion | None = None
        self.reasoning: ReasoningAdapter | None = None
        self.memory: MemoryAdapter | None = None
        self.confidence: ConfidenceEngine | None = None
        self.risk: AdvisoryRiskScorer | None = None
        self.builder: DecisionBuilder | None = None

        # =====================================================
        # RESEARCH EVIDENCE RECORDING (ADR-0008)
        # =====================================================
        #
        # Observational only. The store is absent by default (a bare
        # AtlasBrain() records nothing) and every interaction with it is
        # fail-open: it can never alter agent_results, fusion_result, or
        # the returned Decision. See _record_evidence_claims().
        self.evidence_store: Any | None = self.config.get(
            "evidence_store"
        )

        # Change-triggered writes (OQ-4). Per-agent and per-symbol state
        # from the previous cycle, used to decide whether this cycle says
        # anything new. At the 10s market interval, recording every cycle
        # would be roughly 79M rows a year of mostly identical readings;
        # a claim is meant to be an assertion, not telemetry.
        self._evidence_last_agent: dict[
            tuple[str, str], tuple[str, float]
        ] = {}
        self._evidence_last_fused: dict[str, str] = {}

        # Minimum absolute conviction move that counts as a new claim when
        # the agent's direction is unchanged. 0.15 on the 0..1 conviction
        # scale: large enough that ordinary tick-to-tick noise is silent,
        # small enough that a genuine regime move is captured well before
        # the direction actually flips.
        self.evidence_conviction_delta = float(
            self.config.get(
                "evidence_conviction_delta",
                self.DEFAULT_EVIDENCE_CONVICTION_DELTA,
            )
        )

        self.initialize_modules()

        self.status = self.STATUS_ACTIVE

        _log.debug(
            f"[ATLAS BRAIN] Intelligence Brain "
            f"v{self.VERSION} active"
        )

        logger.info(
            "Atlas Intelligence Brain v%s initialized",
            self.VERSION,
        )

    # =========================================================
    # MODULE INITIALIZATION
    # =========================================================

    def initialize_modules(self) -> None:
        """
        Initialize all intelligence pipeline modules.
        """

        try:
            data_dir = str(
                self.config.get(
                    "data_dir",
                    "memory_data",
                )
            )

            self.memory_core = AtlasMemoryCore(
                data_dir=data_dir
            )

            self.reasoning_engine = AtlasReasoningEngine(
                data_dir=data_dir
            )

            self.world = AtlasWorldModel(
                data_dir=data_dir
            )

            self.agents = AgentFusion()

            self.reasoning = ReasoningAdapter(
                self.reasoning_engine
            )

            self.memory = MemoryAdapter(
                self.memory_core
            )

            self.confidence = ConfidenceEngine()

            self.risk = AdvisoryRiskScorer()

            self.builder = DecisionBuilder()

            _log.debug(
                "[ATLAS BRAIN] All intelligence modules loaded"
            )

            logger.info(
                "All intelligence modules loaded"
            )

        except Exception as exc:
            self.status = self.STATUS_ERROR
            self.errors += 1

            self.last_error = self._build_error_record(
                phase="initialization",
                error=exc,
            )

            logger.exception(
                "Atlas intelligence initialization failed"
            )

            _log.debug(
                f"[ATLAS INIT ERROR] {exc}"
            )

            raise

    # =========================================================
    # MAIN PIPELINE
    # =========================================================

    def analyze_and_decide(
        self,
        symbol: str,
        market_data: Any,
    ) -> Any:
        """
        Run one complete intelligence cycle.

        Returns:
            Canonical Decision object produced by DecisionBuilder.

        Important:
            DecisionBuilder owns the final execution confidence.
            ConfidenceEngine output is diagnostic and must not overwrite it.
        """

        normalized_symbol = str(
            symbol
        ).strip().upper()

        cycle_started_at = datetime.now(
            UTC
        )

        self.cycles += 1
        self.last_symbol = normalized_symbol
        self.last_analysis_at = cycle_started_at.isoformat()

        try:
            self._validate_pipeline()

            print()
            _log.debug(
                "=" * 60
            )
            _log.debug(
                f"ATLAS INTELLIGENCE "
                f"v{self.VERSION} : "
                f"{normalized_symbol}"
            )
            _log.debug(
                "=" * 60
            )

            # =================================================
            # WORLD ANALYSIS
            # =================================================

            world_result = self.world_analysis(
                normalized_symbol
            )

            # =================================================
            # AGENT ANALYSIS
            # =================================================

            agent_results = self.agents.evaluate(
                normalized_symbol,
                market_data,
            )

            # =================================================
            # REASONING ANALYSIS
            # =================================================

            reasoning_result = self.reasoning.analyze(
                normalized_symbol,
                market_data,
            )

            # =================================================
            # MEMORY ANALYSIS
            # =================================================

            memory_result = self.memory.analyze()

            # =================================================
            # AGENT FUSION
            # =================================================

            fusion_result = self.agents.fuse(
                agent_results
            )

            # =================================================
            # PHASE-5 SHADOW PROPOSAL (PROPOSAL_ONLY, non-execution)
            # =================================================

            try:
                phase5_shadow_proposal = (
                    self._build_phase5_shadow_proposal(
                        normalized_symbol,
                        agent_results,
                        market_data,
                    )
                )
            except Exception:
                logger.exception(
                    "Phase-5 shadow proposal call site failed; "
                    "continuing without shadow proposal"
                )

                phase5_shadow_proposal = None

            # =================================================
            # RESEARCH EVIDENCE RECORDING (ADR-0008, observational)
            # =================================================
            #
            # Deliberately fail-open, and deliberately placed after every
            # value it reads is already final. It assigns to nothing the
            # pipeline below consumes: agent_results and fusion_result are
            # passed in and never mutated, no name here is rebound, and the
            # block produces no value. A failure therefore costs a log line
            # and a health() counter, never a decision.
            try:
                self._record_evidence_claims(
                    normalized_symbol,
                    agent_results,
                    fusion_result,
                    market_data,
                )
            except Exception:
                logger.exception(
                    "Research evidence recording failed; continuing "
                    "without recording this cycle"
                )

            # =================================================
            # INTERMEDIATE CONFIDENCE ANALYSIS
            # =================================================

            confidence_result = self.confidence.calculate(
                agent_results,
                reasoning_result,
                {
                    "level": "MEDIUM",
                },
                expected_agent_count=len(
                    self.agents.WEIGHTS
                ),
            )

            intermediate_confidence = (
                self._extract_confidence_percentage(
                    confidence_result
                )
            )

            _log.debug(
                f"[CONFIDENCE] "
                f"{intermediate_confidence}%"
            )

            # =================================================
            # RISK ANALYSIS
            # =================================================

            # Advisory score kept for audit only (metadata["advisory_risk"]).
            advisory_risk_result = self.risk.calculate(
                confidence=confidence_result.value
            )

            # Registry v5.22: the bucket-selecting risk_level comes from
            # the measured volatility regime (fail-closed to HIGH).
            risk_result = regime_risk_result(
                market_data,
                normalized_symbol,
            )

            # =================================================
            # FINAL DECISION
            # =================================================

            decision = self.builder.create(
                normalized_symbol,
                fusion_result,
                risk_result,
                reasoning_result,
                memory_result,
                agent_results,
                getattr(
                    self.agents,
                    "last_unavailable_agents",
                    None,
                ),
            )

            # =================================================
            # DIAGNOSTIC METADATA
            # =================================================
            #
            # Never overwrite:
            #
            #     decision.confidence
            #
            # DecisionBuilder owns the final execution confidence.
            # ConfidenceEngine results belong in metadata only.
            # =================================================

            confidence_explanation = (
                self._safe_confidence_explanation(
                    confidence_result
                )
            )

            decision.metadata.update(
                {
                    "brain_version": self.VERSION,
                    "brain_session_id": self.session_id,
                    "advisory_risk": advisory_risk_result.to_dict(),
                    "analysis_timestamp": datetime.now(
                        UTC
                    ).isoformat(),
                    "world_analysis": world_result,
                    "intermediate_confidence": (
                        intermediate_confidence
                    ),
                    "confidence_explanation": (
                        confidence_explanation
                    ),
                    "final_confidence": (
                        float(
                            decision.confidence
                        )
                    ),
                }
            )

            if phase5_shadow_proposal is not None:
                try:
                    decision.metadata[
                        "phase5_proposal"
                    ] = phase5_shadow_proposal.audit_record()
                except Exception:
                    logger.exception(
                        "Phase-5 shadow proposal metadata "
                        "attachment failed; ignoring proposal"
                    )

            self.successful_cycles += 1
            self.last_decision = decision
            self.last_error = None

            logger.info(
                "%s intelligence completed "
                "action=%s final_confidence=%.2f "
                "intermediate_confidence=%.2f",
                normalized_symbol,
                self._decision_action_value(
                    decision
                ),
                float(
                    decision.confidence
                ),
                intermediate_confidence,
            )

            return decision

        except Exception as exc:
            self.errors += 1
            self.failed_cycles += 1

            self.last_error = self._build_error_record(
                phase=f"analysis:{normalized_symbol}",
                error=exc,
            )

            logger.exception(
                "%s intelligence cycle failed",
                normalized_symbol,
            )

            _log.debug(
                f"[ATLAS ERROR] {exc}"
            )

            return {
                "symbol": normalized_symbol,
                "action": "HOLD",
                "confidence": 0.0,
                "reasoning": "Atlas intelligence pipeline error",
                "risk_level": "CRITICAL",
                "strategy": "Atlas_Error_Fallback",
                "created_at": datetime.now(
                    UTC
                ).isoformat(),
                "metadata": {
                    "brain_version": self.VERSION,
                    "error": str(
                        exc
                    ),
                    "error_type": type(
                        exc
                    ).__name__,
                    "fallback": True,
                },
            }

    # =========================================================
    # WORLD MODEL
    # =========================================================

    def world_analysis(
        self,
        symbol: str,
    ) -> Any:
        """
        Retrieve the world-model impact chain for one asset.
        """

        if self.world is None:
            return {}

        try:
            asset = str(
                symbol
            ).upper().replace(
                "USDT",
                "",
            )

            result = self.world.get_impact_chain(
                asset,
                depth=2,
            )

            try:
                related_count = len(
                    result
                )
            except TypeError:
                related_count = 0

            _log.debug(
                f"[WORLD] "
                f"{related_count} related assets"
            )

            return result

        except Exception as exc:
            self.errors += 1

            logger.exception(
                "%s world analysis failed",
                symbol,
            )

            _log.debug(
                f"[WORLD ERROR] {exc}"
            )

            return {}

    # =========================================================
    # PHASE-5 SHADOW PROPOSAL (PROPOSAL_ONLY, non-execution)
    # =========================================================

    def _build_phase5_shadow_proposal(
        self,
        symbol: str,
        agent_results: Any,
        market_data: Any,
        *,
        now: datetime | None = None,
    ) -> CanonicalDecision | None:
        """
        Build a shadow-only Phase-5 CanonicalDecision from agent evidence.

        This is advisory only: it never influences action, confidence,
        price, risk, sizing, routing, or execution eligibility. Any
        failure here is swallowed and returns None so the live decision
        path is never affected.

        Weighting semantics (intentional, NOT baseline parity):
        This uses SignalFusion's equal-weight, one-source-one-vote signed
        fusion (core/decision_intelligence.py) - every agent gets weight
        1, regardless of AgentFusion.WEIGHTS' configured importance
        (technical=.40, momentum=.20, risk=.20, macro=.10, sentiment=.10).
        It deliberately does NOT reproduce AgentFusion.fuse()'s weighted
        bucket-share conviction. The resulting action/confidence are an
        independent Phase-5 research/shadow metric and must not be read
        as a reproduction of production conviction - the two can and do
        diverge materially on identical agent input.

        HOLD evidence contributes zero to SignalFusion's signed numerator
        (BUY is positive conviction, SELL is negative) but still
        contributes its full source weight to the denominator, so each
        HOLD dilutes net conviction rather than being excluded outright -
        a third behavior, distinct from both AgentFusion's own HOLD
        handling (0.5 * weight into a dedicated HOLD bucket) and from
        simply dropping HOLD evidence. Because of this dilution, a
        symbol with several HOLD agents and only one directional agent
        can legitimately fall below FusionPolicy.decision_threshold and
        resolve to ABSTAIN here while AgentFusion's bucket-share vote
        still resolves to BUY or SELL on the same input. This is an
        action-level divergence, not merely a confidence-magnitude
        difference, and is expected behavior for this independent
        research metric - it must not be read as a bug or as evidence
        Phase 5 and baseline disagree about market direction.

        Freshness semantics (intentional, INGESTION-TIME only):
        Evidence.observed_at is parsed from market_data["timestamp"] -
        the market-data ingestion/build time - not exchange/source event
        time. If that timestamp is missing, malformed, or timezone-naive,
        no provenance is fabricated: this method returns None rather
        than substituting cycle-start or wall-clock time as fake
        evidence age. `now` is an independently evaluated fusion time
        (defaults to the real current time; overridable for deterministic
        tests), never derived from the evidence itself, so the staleness
        check is a genuine comparison between two independently obtained
        timestamps rather than a literal `now == observed_at` tautology.
        Source/event-time (exchange candle) freshness is NOT verified by
        this check and remains UNVERIFIED pending future propagation of
        candle timestamps into market_data.

        In practice, on the normal synchronous live path, market_data
        ["timestamp"] is stamped by build_market_data() only milliseconds
        before this method runs, so evidence age is normally near zero
        and the 5-minute freshness gate will almost never reject evidence
        for genuine upstream market-data staleness in that path - it
        mainly guards other callers or future asynchronous/queued paths
        where ingestion and fusion can drift apart. Passing evidence
        through this gate is proof the ingestion timestamp itself is
        recent; it is not proof the underlying exchange/source data was
        fresh at the exchange.

        Replay/backtest callers must not assume this gate enforces a
        correct historical event-time contract; it does not yet, and two
        distinct failure modes are both possible depending on how the
        caller constructs market_data:
        - if replay/backtest reuses build_market_data() unmodified, the
          ingestion timestamp is stamped at replay wall-clock time, so
          arbitrarily old historical evidence will appear fresh here;
        - if replay/backtest instead injects genuine historical
          timestamps while `now` defaults to current wall-clock time,
          that evidence will read as STALE (age > max_age) and the
          proposal will legitimately degrade to ABSTAIN regardless of
          how directionally strong the historical evidence actually was.
        Neither failure mode is fixed by this method; correct replay
        semantics require propagating a matching historical `now`
        alongside historical evidence, which is separate, not-yet-scoped
        roadmap work.

        Per-agent isolation:
        Each agent result is validated and converted independently via
        _build_phase5_agent_evidence(). One malformed agent (unsupported
        action, non-numeric/boolean/out-of-range score, etc.) is
        excluded and recorded - it never discards valid evidence from
        other agents, and it never aborts the whole proposal. Rejections
        are surfaced in the resulting CanonicalDecision's market_context
        under "phase5_agent_input_rejections" (a compact JSON list of
        {"agent", "reason"} records) so malformed input remains visible
        in the audit trail rather than silently vanishing.
        """

        try:
            observed_at = self._parse_ingestion_timestamp(
                market_data
            )

            if observed_at is None:
                return None

            evaluation_now = (
                now
                if now is not None
                else datetime.now(
                    UTC
                )
            )

            evidence: list[Evidence] = []
            rejections: list[tuple[str, str]] = []

            for name, data in dict(
                agent_results or {}
            ).items():
                item, reason = self._build_phase5_agent_evidence(
                    name,
                    data,
                    symbol,
                    observed_at,
                )

                if item is not None:
                    evidence.append(
                        item
                    )
                elif reason is not None:
                    rejections.append(
                        (
                            name,
                            reason,
                        )
                    )

            if not evidence:
                return None

            policy = FusionPolicy(
                weights={
                    item.source: Decimal("1")
                    for item in evidence
                }
            )

            fusion = SignalFusion(
                policy
            ).fuse(
                symbol,
                evidence,
                now=evaluation_now,
            )

            market_context: dict[str, str] = {}

            if rejections:
                market_context[
                    "phase5_agent_input_rejections"
                ] = json.dumps(
                    [
                        {
                            "agent": agent_name,
                            "reason": reason_code,
                        }
                        for agent_name, reason_code in sorted(
                            rejections
                        )
                    ],
                    sort_keys=True,
                    separators=(
                        ",",
                        ":",
                    ),
                )

            return CanonicalDecision.from_fusion(
                symbol,
                fusion,
                timestamp=evaluation_now,
                market_context=market_context,
            )

        except Exception:
            logger.exception(
                "Phase-5 shadow proposal construction failed; "
                "continuing without shadow proposal"
            )

            return None

    def _build_phase5_agent_evidence(
        self,
        name: str,
        data: Any,
        symbol: str,
        observed_at: datetime,
    ) -> tuple[Evidence | None, str | None]:
        """
        Validate and convert one agent result into Evidence.

        Isolates one agent's failure from the rest of the batch: a
        single malformed agent must never discard valid evidence
        already constructed for other agents. Returns:
        - (Evidence, None) on success;
        - (None, None) when the agent simply supplied no signal
          (absent/None action or score - not malformed, not recorded
          as a rejection);
        - (None, reason_code) when the supplied signal is malformed
          and must be recorded in the Phase-5 audit trail. Reason
          codes: "malformed_agent_result", "unsupported_action",
          "invalid_score_type", "score_out_of_range".

        This is a distinct, earlier taxonomy from SignalFusion's own
        per-evidence rejection reasons (WRONG_SYMBOL, STALE, etc.),
        which apply only to evidence that already passed this stage.
        """

        if not isinstance(
            data,
            dict,
        ):
            return None, "malformed_agent_result"

        action = data.get(
            "action"
        )
        score = data.get(
            "score"
        )

        if action is None or score is None:
            return None, None

        try:
            normalized_action = Action(
                str(
                    action
                ).strip().upper()
            )
        except ValueError:
            return None, "unsupported_action"

        if isinstance(
            score,
            bool,
        ) or not isinstance(
            score,
            (
                int,
                float,
                str,
            ),
        ):
            return None, "invalid_score_type"

        try:
            score_value = float(
                score
            )
        except (
            TypeError,
            ValueError,
        ):
            return None, "invalid_score_type"

        if (
            not isfinite(
                score_value
            )
            or not (
                0.0 <= score_value <= 1.0
            )
        ):
            return None, "score_out_of_range"

        conviction = self._agent_score_to_conviction(
            normalized_action.value,
            score_value,
        )

        try:
            evidence = Evidence(
                evidence_id=f"agent:{name}:{symbol}:{observed_at.isoformat()}",
                source=f"agent:{name}",
                source_version="1",
                symbol=symbol,
                action=normalized_action,
                score=Decimal(
                    str(
                        conviction
                    )
                ),
                observed_at=observed_at,
            )
        except Exception:
            return None, "malformed_agent_result"

        return evidence, None

    @staticmethod
    def _parse_ingestion_timestamp(
        market_data: Any,
    ) -> datetime | None:
        """
        Parse a trustworthy, timezone-aware ingestion timestamp.

        Returns None (never a fabricated substitute) when the timestamp
        is missing, malformed, or timezone-naive - a naive value cannot
        be trusted as verified UTC provenance.
        """

        if not isinstance(
            market_data,
            dict,
        ):
            return None

        raw_timestamp = market_data.get(
            "timestamp"
        )

        if (
            not isinstance(
                raw_timestamp,
                str,
            )
            or not raw_timestamp
        ):
            return None

        try:
            parsed = datetime.fromisoformat(
                raw_timestamp
            )
        except ValueError:
            return None

        if (
            parsed.tzinfo is None
            or parsed.utcoffset() is None
        ):
            return None

        return parsed.astimezone(
            UTC
        )

    @staticmethod
    def _agent_score_to_conviction(
        action: str,
        score: Any,
    ) -> float:
        """
        Convert a raw agent score into directional Evidence conviction.

        Mirrors AgentFusion.fuse()'s own convention (agent_fusion.py):
        SELL strength is (1 - score); BUY strength is score. HOLD has no
        directional weight in SignalFusion (signed value is 0), so its
        raw score is preserved unchanged.
        """

        score_value = float(
            score
        )

        normalized_action = str(
            action
        ).strip().upper()

        if normalized_action == "SELL":
            return 1 - score_value

        return score_value

    # =========================================================
    # RESEARCH EVIDENCE RECORDING (ADR-0008)
    # =========================================================

    def _record_evidence_claims(
        self,
        symbol: str,
        agent_results: Any,
        fusion_result: Any,
        market_data: Any,
    ) -> None:
        """
        Record this cycle's agent claims when the cycle says something new.

        Observational and strictly read-only with respect to the decision
        pipeline: this method receives ``agent_results`` and
        ``fusion_result`` and never mutates them, returns nothing, and
        raises nothing that the caller does not already absorb.

        Change-triggered per OQ-4. An agent is recorded when its direction
        flips, when its conviction moves by at least
        ``evidence_conviction_delta``, when the fused action changes, or on
        the first observation of that agent/symbol pair. Otherwise the
        cycle is silent - at a 10s interval, recording unchanged readings
        would bury genuine assertions in telemetry.

        Provenance rule: a claim is only recorded when the market data
        carries a trustworthy ingestion timestamp. This mirrors
        _parse_ingestion_timestamp()'s existing contract - a fabricated
        substitute is worse than no record, because the entire point of
        this store is that a claim can be traced back to what was actually
        examined and when.
        """

        store = self.evidence_store

        if store is None or not isinstance(
            agent_results,
            dict,
        ):
            return

        observed_at = self._parse_ingestion_timestamp(
            market_data
        )

        if observed_at is None:
            logger.debug(
                "Evidence recording skipped for %s: market data carries "
                "no trustworthy ingestion timestamp",
                symbol,
            )
            return

        fused_action = self._normalized_action(
            getattr(
                fusion_result,
                "action",
                None,
            )
        )

        previous_fused = self._evidence_last_fused.get(
            symbol
        )

        fused_changed = (
            fused_action is not None
            and previous_fused is not None
            and fused_action != previous_fused
        )

        current = self._current_agent_signals(
            agent_results
        )

        triggered = []

        for name in sorted(
            current
        ):
            action, conviction = current[name]

            previous = self._evidence_last_agent.get(
                (
                    symbol,
                    name,
                )
            )

            if previous is None:
                trigger = "INITIAL_OBSERVATION"
            elif previous[0] != action:
                trigger = "ACTION_FLIP"
            elif (
                abs(
                    conviction - previous[1]
                )
                >= self.evidence_conviction_delta
            ):
                trigger = "CONVICTION_DELTA"
            elif fused_changed:
                trigger = "FUSED_ACTION_CHANGE"
            else:
                continue

            triggered.append(
                (
                    name,
                    action,
                    conviction,
                    trigger,
                )
            )

        recorded: dict[str, tuple[str, str]] = {}

        for name, action, conviction, trigger in triggered:
            claim_id = self._record_one_agent_claim(
                store,
                symbol,
                name,
                action,
                conviction,
                trigger,
                observed_at,
                fused_action,
            )

            if claim_id is not None:
                recorded[name] = (
                    claim_id,
                    action,
                )

        self._link_contradicting_claims(
            store,
            recorded,
        )

        # State advances even when a write failed, so a persistently
        # broken store cannot turn every subsequent cycle into a retry
        # storm. The failure is already counted in health().
        for name, (action, conviction) in current.items():
            self._evidence_last_agent[
                (
                    symbol,
                    name,
                )
            ] = (
                action,
                conviction,
            )

        if fused_action is not None:
            self._evidence_last_fused[symbol] = fused_action

    @staticmethod
    def _normalized_action(
        action: Any,
    ) -> str | None:
        """
        Normalize an action label, or None when it is absent/unusable.
        """

        if action is None:
            return None

        text = str(
            action
        ).strip().upper()

        return text or None

    def _current_agent_signals(
        self,
        agent_results: dict[Any, Any],
    ) -> dict[str, tuple[str, float]]:
        """
        Extract this cycle's usable (action, conviction) per agent.

        Tolerant by design: an agent this cannot interpret is skipped, not
        defaulted and not raised on. Malformed-agent accounting already
        belongs to the Phase-5 path (_build_phase5_agent_evidence), which
        this deliberately does not touch or duplicate authority over.
        """

        signals: dict[str, tuple[str, float]] = {}

        for raw_name, data in agent_results.items():
            if not isinstance(
                data,
                dict,
            ):
                continue

            action = self._normalized_action(
                data.get(
                    "action"
                )
            )

            score = data.get(
                "score"
            )

            if action is None or score is None:
                continue

            if isinstance(
                score,
                bool,
            ) or not isinstance(
                score,
                (
                    int,
                    float,
                    str,
                ),
            ):
                continue

            try:
                score_value = float(
                    score
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            if not isfinite(
                score_value
            ) or not (
                0.0 <= score_value <= 1.0
            ):
                continue

            conviction = self._agent_score_to_conviction(
                action,
                score_value,
            )

            if not isfinite(
                conviction
            ) or not (
                0.0 <= conviction <= 1.0
            ):
                continue

            signals[str(raw_name)] = (
                action,
                round(
                    conviction,
                    6,
                ),
            )

        return signals

    def _record_one_agent_claim(
        self,
        store: Any,
        symbol: str,
        name: str,
        action: str,
        conviction: float,
        trigger: str,
        observed_at: datetime,
        fused_action: str | None,
    ) -> str | None:
        """
        Write one agent's claim. Returns its claim_id, or None on failure.

        Every failure is absorbed here and registered on the store's own
        diagnostics, so one unwritable claim cannot abort the rest of the
        cycle's recording - and certainly cannot reach the decision path.
        """

        try:
            source = ClaimSource(
                source_kind="MARKET_DATA",
                source_uri=f"market_data://{symbol}",
                source_version="1",
                retrieved_at=observed_at,
            )

            reason_codes = [
                trigger,
            ]

            if fused_action is not None:
                reason_codes.append(
                    f"FUSED_{fused_action}"
                )

            return store.record_claim(
                claim_text=(
                    f"{name} reads {action} on {symbol} "
                    f"at conviction {conviction:.4f}"
                ),
                claim_kind="DIRECTIONAL",
                subject_scope="SYMBOL",
                subject_symbol=symbol,
                # Reuses the established agent-source naming from the
                # Phase-5 path so one agent has one identity everywhere.
                agent_id=f"agent:{name}",
                agent_version="1",
                confidence=Decimal(
                    str(
                        conviction
                    )
                ),
                asserted_at=observed_at,
                sources=[
                    source,
                ],
                payload={
                    "action": action,
                    "conviction": conviction,
                },
                run_id=self.session_id,
                reason_codes=reason_codes,
            )

        except Exception as exc:
            self._register_evidence_failure(
                store,
                exc,
            )

            logger.warning(
                "Evidence claim not recorded for %s/%s: %s",
                symbol,
                name,
                exc,
            )

            return None

    def _link_contradicting_claims(
        self,
        store: Any,
        recorded: dict[str, tuple[str, str]],
    ) -> None:
        """
        Link every directionally opposed pair recorded this cycle.

        A BUY and a SELL asserted about the same symbol in the same cycle
        genuinely argue against each other, so the counter-evidence graph
        is populated from real disagreement rather than waiting for an
        LLM research layer that does not exist yet.
        """

        names = sorted(
            recorded
        )

        for index, first in enumerate(
            names
        ):
            first_id, first_action = recorded[first]

            for second in names[index + 1:]:
                second_id, second_action = recorded[second]

                if {
                    first_action,
                    second_action,
                } != {
                    "BUY",
                    "SELL",
                }:
                    continue

                try:
                    store.link(
                        from_claim_id=first_id,
                        to_claim_id=second_id,
                        relation_kind="CONTRADICTS",
                        created_by="atlas_brain",
                    )
                except Exception as exc:
                    self._register_evidence_failure(
                        store,
                        exc,
                    )

                    logger.warning(
                        "Contradiction edge not recorded: %s",
                        exc,
                    )

    @staticmethod
    def _register_evidence_failure(
        store: Any,
        error: BaseException,
    ) -> None:
        """
        Record a swallowed failure on the store, never raising itself.

        Fail-open must not also mean fail-silent: this is what keeps a
        broken store visible in health() after the exception is absorbed.
        """

        try:
            store.record_write_failure(
                error
            )
        except Exception:
            logger.debug(
                "Evidence store could not register a write failure",
                exc_info=True,
            )

    # =========================================================
    # PIPELINE VALIDATION
    # =========================================================

    def _validate_pipeline(self) -> None:
        """
        Ensure all required intelligence modules are available.
        """

        required_modules = {
            "world": self.world,
            "agents": self.agents,
            "reasoning": self.reasoning,
            "memory": self.memory,
            "confidence": self.confidence,
            "risk": self.risk,
            "builder": self.builder,
        }

        missing_modules = [
            name
            for name, module in required_modules.items()
            if module is None
        ]

        if missing_modules:
            raise RuntimeError(
                "Missing intelligence modules: "
                + ", ".join(
                    missing_modules
                )
            )

    # =========================================================
    # CONFIDENCE HELPERS
    # =========================================================

    @staticmethod
    def _extract_confidence_percentage(
        confidence_result: Any,
    ) -> float:
        """
        Extract ConfidenceEngine output on the 0-100 scale.
        """

        percentage_method = getattr(
            confidence_result,
            "percentage",
            None,
        )

        if callable(
            percentage_method
        ):
            try:
                return round(
                    max(
                        0.0,
                        min(
                            float(
                                percentage_method()
                            ),
                            100.0,
                        ),
                    ),
                    2,
                )

            except (
                TypeError,
                ValueError,
            ):
                pass

        value = getattr(
            confidence_result,
            "value",
            0.0,
        )

        try:
            normalized = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return 0.0

        if 0.0 <= normalized <= 1.0:
            normalized *= 100.0

        return round(
            max(
                0.0,
                min(
                    normalized,
                    100.0,
                ),
            ),
            2,
        )

    def _safe_confidence_explanation(
        self,
        confidence_result: Any,
    ) -> Any:
        """
        Retrieve ConfidenceEngine diagnostics without changing Decision.
        """

        if self.confidence is None:
            return None

        explain_method = getattr(
            self.confidence,
            "explain",
            None,
        )

        if not callable(
            explain_method
        ):
            return None

        try:
            return explain_method(
                confidence_result
            )

        except Exception as exc:
            logger.warning(
                "Confidence explanation failed: %s",
                exc,
            )

            return {
                "error": str(
                    exc
                ),
                "available": False,
            }

    # =========================================================
    # ERROR HELPERS
    # =========================================================

    @staticmethod
    def _build_error_record(
        *,
        phase: str,
        error: Exception,
    ) -> dict[str, Any]:
        """
        Create a structured diagnostic error record.
        """

        return {
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
    # DECISION HELPERS
    # =========================================================

    @staticmethod
    def _decision_action_value(
        decision: Any,
    ) -> str:
        """
        Safely retrieve a decision action string.
        """

        action = getattr(
            decision,
            "action",
            "UNKNOWN",
        )

        return str(
            getattr(
                action,
                "value",
                action,
            )
        )

    # =========================================================
    # HEALTH
    # =========================================================

    def health(self) -> dict[str, Any]:
        """
        Return concise intelligence health information.
        """

        modules_ready = all(
            module is not None
            for module in (
                self.world,
                self.agents,
                self.reasoning,
                self.memory,
                self.confidence,
                self.risk,
                self.builder,
            )
        )

        healthy = bool(
            self.status == self.STATUS_ACTIVE
            and modules_ready
        )

        return {
            "healthy": healthy,
            "status": self.status,
            "version": self.VERSION,
            "cycles": self.cycles,
            "successful_cycles": self.successful_cycles,
            "failed_cycles": self.failed_cycles,
            "errors": self.errors,
        }

    # =========================================================
    # STATUS
    # =========================================================

    def get_system_status(self) -> dict[str, Any]:
        """
        Return complete intelligence diagnostics.
        """

        return {
            "name": self.NAME,
            "version": self.VERSION,
            "status": self.status,
            "session": self.session_id,
            "started_at": self.started_at,
            "last_analysis_at": self.last_analysis_at,
            "last_symbol": self.last_symbol,
            "cycles": self.cycles,
            "successful_cycles": self.successful_cycles,
            "failed_cycles": self.failed_cycles,
            "errors": self.errors,
            "modules": {
                "world": self.world is not None,
                "agents": self.agents is not None,
                "reasoning": self.reasoning is not None,
                "memory": self.memory is not None,
                "confidence": self.confidence is not None,
                "risk": self.risk is not None,
                "decision": self.builder is not None,
            },
            "last_decision": (
                self.last_decision.to_dict()
                if (
                    self.last_decision is not None
                    and callable(
                        getattr(
                            self.last_decision,
                            "to_dict",
                            None,
                        )
                    )
                )
                else self.last_decision
            ),
            "last_error": self.last_error,
            "time": datetime.now(
                UTC
            ).isoformat(),
        }

    # =========================================================
    # REPRESENTATION
    # =========================================================

    def __repr__(self) -> str:
        return (
            f"<{self.NAME} "
            f"version={self.VERSION} "
            f"status={self.status} "
            f"cycles={self.cycles}>"
        )