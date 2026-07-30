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

import logging

from datetime import UTC, datetime
from typing import Any

from .atlas_memory_core import AtlasMemoryCore
from .atlas_reasoning_engine import AtlasReasoningEngine
from .atlas_world_model import AtlasWorldModel

from .intelligence.agent_fusion import AgentFusion
from .intelligence.confidence.confidence_engine import ConfidenceEngine
from .intelligence.decision_builder import DecisionBuilder
from .intelligence.memory_adapter import MemoryAdapter
from .intelligence.reasoning_adapter import ReasoningAdapter
from .intelligence.risk_engine import RiskEngine


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
        self.risk: RiskEngine | None = None
        self.builder: DecisionBuilder | None = None

        self.initialize_modules()

        self.status = self.STATUS_ACTIVE

        print(
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

            self.risk = RiskEngine()

            self.builder = DecisionBuilder()

            print(
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

            print(
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

        self.cycles += 1
        self.last_symbol = normalized_symbol
        self.last_analysis_at = datetime.now(
            UTC
        ).isoformat()

        try:
            self._validate_pipeline()

            print()
            print(
                "=" * 60
            )
            print(
                f"ATLAS INTELLIGENCE "
                f"v{self.VERSION} : "
                f"{normalized_symbol}"
            )
            print(
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
            # INTERMEDIATE CONFIDENCE ANALYSIS
            # =================================================

            confidence_result = self.confidence.calculate(
                agent_results,
                reasoning_result,
                {
                    "level": "MEDIUM",
                },
            )

            intermediate_confidence = (
                self._extract_confidence_percentage(
                    confidence_result
                )
            )

            print(
                f"[CONFIDENCE] "
                f"{intermediate_confidence}%"
            )

            # =================================================
            # RISK ANALYSIS
            # =================================================

            risk_result = self.risk.calculate(
                confidence=confidence_result.value
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

            print(
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

            print(
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

            print(
                f"[WORLD ERROR] {exc}"
            )

            return {}

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