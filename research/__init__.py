"""Atlas research subsystem: statistically rigorous strategy edge validation.

This package provides the infrastructure that makes look-ahead leakage,
multiple-testing inflation, and HARKing structurally difficult:

- ``lifecycle``: the monotone hypothesis state machine. It has no LIVE state.
- ``splitting``: purged and embargoed chronological train/calibration/test
  splits.
- ``multiple_testing``: Benjamini-Hochberg false discovery rate control.
- ``hypothesis_registry``: the tamper-evident, append-only pre-registration
  store that makes an honest multiple-testing family enumerable.

This package contains no strategy, no signal, no data acquisition, and no
connection to the Atlas runtime. It never writes Atlas runtime state, and it
carries no trading authority of any kind.

See ``docs/research/0001-hypothesis-registry-design.md``.
"""

from __future__ import annotations

from research.lifecycle import (
    FAMILY_ADJUDICATED_TRANSITION,
    TERMINAL_STATES,
    HypothesisState,
    IllegalTransitionError,
    LifecycleError,
    allowed_transitions,
    can_evaluate_test,
    can_transition,
    is_terminal,
    progress_rank,
    validate_transition,
)
from research.multiple_testing import (
    FDRDecision,
    MultipleTestingError,
    benjamini_hochberg,
)
from research.splitting import (
    DataSplit,
    Segment,
    SplitError,
    SplitSpec,
    make_purged_split,
)
from research.hypothesis_registry import (
    CHECK_ORDER,
    CHECK_SEGMENTS,
    CheckAdjudication,
    CheckName,
    CheckPlan,
    CheckPlanStatus,
    CheckResult,
    CheckVerdict,
    DuplicateCheckError,
    DuplicateHypothesisError,
    EvaluationNotPermittedError,
    EvaluationRecord,
    FamilyAdjudicationRequiredError,
    FamilyAlreadyAdjudicatedError,
    FamilyNotReadyError,
    HypothesisRecord,
    HypothesisRegistry,
    PreRegistration,
    RegistryError,
    SealVerificationError,
    ThresholdBindingError,
    UnknownHypothesisError,
    UnplannedCheckError,
)

__all__ = [
    "FAMILY_ADJUDICATED_TRANSITION",
    "TERMINAL_STATES",
    "HypothesisState",
    "IllegalTransitionError",
    "LifecycleError",
    "allowed_transitions",
    "can_evaluate_test",
    "can_transition",
    "is_terminal",
    "progress_rank",
    "validate_transition",
    "FDRDecision",
    "MultipleTestingError",
    "benjamini_hochberg",
    "DataSplit",
    "Segment",
    "SplitError",
    "SplitSpec",
    "make_purged_split",
    "CHECK_ORDER",
    "CHECK_SEGMENTS",
    "CheckAdjudication",
    "CheckName",
    "CheckPlan",
    "CheckPlanStatus",
    "CheckResult",
    "CheckVerdict",
    "DuplicateCheckError",
    "DuplicateHypothesisError",
    "EvaluationNotPermittedError",
    "EvaluationRecord",
    "FamilyAdjudicationRequiredError",
    "FamilyAlreadyAdjudicatedError",
    "FamilyNotReadyError",
    "HypothesisRecord",
    "HypothesisRegistry",
    "PreRegistration",
    "RegistryError",
    "SealVerificationError",
    "ThresholdBindingError",
    "UnknownHypothesisError",
    "UnplannedCheckError",
]
