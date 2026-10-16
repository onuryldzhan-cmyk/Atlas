"""Strategic Scout & external research intelligence (Task 011, registry v5.95).

Offline and research-only: external findings arrive as plain records and leave
as EXPLORATORY reports. Nothing here fetches, executes, trades, or writes the
hypothesis registry, runtime state, rules or parameters; nothing here can
accept a candidate (the best outcome is PENDING_OWNER_REVIEW).
"""

from research.scout.acceptance_gate import (
    DEFAULT_ALLOWED_LICENSES,
    GATE_STEPS,
    REQUIRED_STEP_COUNT,
    CandidateKind,
    GatePolicy,
    GateStatus,
    GateStep,
    GateStepResult,
    GateVerdict,
    ScoutCandidate,
    SecurityProfile,
    evaluate_candidate,
)
from research.scout.provenance import EXPLORATORY, ScoutInputError, SourceRecord, SourceType
from research.scout.strategic_scout import (
    MODE_SPECS,
    ModeSpec,
    ScoutFinding,
    ScoutLedger,
    ScoutLedgerError,
    ScoutMode,
    ScoutReport,
    ScoutRequest,
    StrategicScout,
)
from research.scout.trader_reputation import (
    REQUIRED_DIMENSION_COUNT,
    ClaimType,
    ExecutionLogEvidence,
    ReputationDimension,
    ReputationPolicy,
    ReputationRating,
    TraderAssessment,
    TraderClaim,
    assess_claim,
)

__all__ = [
    "CandidateKind",
    "ClaimType",
    "DEFAULT_ALLOWED_LICENSES",
    "EXPLORATORY",
    "ExecutionLogEvidence",
    "GATE_STEPS",
    "GatePolicy",
    "GateStatus",
    "GateStep",
    "GateStepResult",
    "GateVerdict",
    "MODE_SPECS",
    "ModeSpec",
    "REQUIRED_DIMENSION_COUNT",
    "REQUIRED_STEP_COUNT",
    "ReputationDimension",
    "ReputationPolicy",
    "ReputationRating",
    "ScoutCandidate",
    "ScoutFinding",
    "ScoutInputError",
    "ScoutLedger",
    "ScoutLedgerError",
    "ScoutMode",
    "ScoutReport",
    "ScoutRequest",
    "SecurityProfile",
    "SourceRecord",
    "SourceType",
    "StrategicScout",
    "TraderAssessment",
    "TraderClaim",
    "assess_claim",
    "evaluate_candidate",
]
