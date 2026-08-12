"""
NBF-1 - AtlasBrain -> ConfidenceEngine `expected_agent_count` wiring.

NB-4/NB-5 (tests/test_nb4_nb5_confidence_availability_correction.py) proved
that ConfidenceEngine.calculate()/calculate_agent_agreement() use
`expected_agent_count` as the agreement denominator instead of the
surviving-agent count, when a caller supplies it. Those tests exercise
ConfidenceEngine directly - they do not, and by design should not, know
whether any real caller actually passes that argument.

The remaining regression-risk gap this file closes: AtlasBrain.
analyze_and_decide() must keep passing
`expected_agent_count=len(self.agents.WEIGHTS)` at its live
ConfidenceEngine.calculate() call site
(ai/core/atlas_brain.py, "INTERMEDIATE CONFIDENCE ANALYSIS" section). If
that keyword argument were ever deleted from the call site, every NB-4/
NB-5 helper-level test above would keep passing (they call ConfidenceEngine
themselves), while production would silently regress to the pre-fix
surviving-count denominator. This file constructs a real AtlasBrain, runs
its real analyze_and_decide() pipeline, and intercepts the real
ConfidenceEngine instance's calculate() to observe what AtlasBrain actually
passed - so removing the call-site keyword argument fails this file even
though it would not fail NB-4/NB-5.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from ai.core.atlas_brain import AtlasBrain
from ai.core.intelligence.agent_fusion import AgentFusion
from analysis.evidence_status import MarketDataEvidenceStatus


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    # AtlasBrain() bootstraps AtlasMemoryCore/AtlasReasoningEngine/
    # AtlasWorldModel, each of which may create a CWD-relative
    # "memory_data" directory (production behavior, left unchanged).
    # Redirecting the test CWD into pytest's isolated tmp_path keeps that
    # side effect out of the repository, matching the existing pattern in
    # tests/test_atlas_brain_phase5_shadow.py.
    monkeypatch.chdir(tmp_path)


def _market_data(*, include_macro: bool, include_sentiment: bool) -> dict:
    evidence_status = {
        "technical": MarketDataEvidenceStatus.AVAILABLE.value,
        "market_risk": MarketDataEvidenceStatus.AVAILABLE.value,
        "macro": (
            MarketDataEvidenceStatus.AVAILABLE.value
            if include_macro
            else MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value
        ),
        "sentiment": (
            MarketDataEvidenceStatus.AVAILABLE.value
            if include_sentiment
            else MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER.value
        ),
    }
    return {
        "price": 65_000.0,
        "technical_score": 0.8,
        "risk_score": 0.7,
        "macro_score": 0.75,
        "sentiment_score": 0.9,
        "evidence_status": evidence_status,
        # momentum has no evidence_status entry by contract - it is
        # derived internally from rsi/trend (NB-3).
        "rsi": 50,
        "trend": "SIDEWAYS",
        "timestamp": datetime.now(UTC).isoformat(),
    }


FULL_MARKET_DATA = _market_data(include_macro=True, include_sentiment=True)
REDUCED_MARKET_DATA = _market_data(include_macro=False, include_sentiment=False)


# =================================================================
# 1. Mandatory: live call-site wiring
# =================================================================


def test_atlas_brain_passes_configured_roster_size_to_live_confidence_call():
    brain = AtlasBrain()

    # `AgentFusion.WEIGHTS` is read from the brain's own live `agents`
    # instance, never a literal, so this assertion tracks the current
    # configured roster even if it is resized in the future.
    configured_roster_size = len(brain.agents.WEIGHTS)
    assert configured_roster_size == len(AgentFusion.WEIGHTS)

    with patch.object(
        brain.confidence,
        "calculate",
        wraps=brain.confidence.calculate,
    ) as confidence_spy:
        decision = brain.analyze_and_decide(
            "BTCUSDT",
            FULL_MARKET_DATA,
        )

    # 1. AtlasBrain reached the real confidence call site.
    confidence_spy.assert_called_once()

    # 2/3. The supplied expected_agent_count equals the *current*
    # configured roster size - not a number this test hardcodes. If the
    # `expected_agent_count=len(self.agents.WEIGHTS)` keyword argument
    # were removed from ai/core/atlas_brain.py, this call would either
    # omit the keyword (KeyError below) or fall back to its default of
    # None, and this assertion would fail either way.
    called_kwargs = confidence_spy.call_args.kwargs
    assert called_kwargs["expected_agent_count"] == configured_roster_size

    # 4. Existing behavior remains unchanged: the pipeline still produces
    # a normal, valid decision through the wrapped (not bypassed) real
    # ConfidenceEngine.calculate().
    assert decision.action.value in {"BUY", "SELL", "HOLD"}
    assert isinstance(decision.confidence, float)
    assert "intermediate_confidence" in decision.metadata


# =================================================================
# 2. Optional: availability-sensitive behavior reaches AtlasBrain
# =================================================================


def test_reduced_agent_availability_does_not_increase_live_confidence():
    full_brain = AtlasBrain()
    reduced_brain = AtlasBrain()

    with patch.object(
        full_brain.confidence,
        "calculate",
        wraps=full_brain.confidence.calculate,
    ) as full_spy:
        full_decision = full_brain.analyze_and_decide(
            "BTCUSDT",
            FULL_MARKET_DATA,
        )

    with patch.object(
        reduced_brain.confidence,
        "calculate",
        wraps=reduced_brain.confidence.calculate,
    ) as reduced_spy:
        reduced_decision = reduced_brain.analyze_and_decide(
            "BTCUSDT",
            REDUCED_MARKET_DATA,
        )

    full_agents_seen = full_spy.call_args.args[0]
    reduced_agents_seen = reduced_spy.call_args.args[0]

    # Sanity: the reduced fixture genuinely dropped macro/sentiment
    # participation at the live agents.evaluate() stage, it did not just
    # change scores.
    assert len(reduced_agents_seen) < len(full_agents_seen)

    # The wiring keeps the denominator pinned to the configured roster
    # size in both calls, regardless of how many agents survived.
    configured_roster_size = len(AgentFusion.WEIGHTS)
    assert (
        full_spy.call_args.kwargs["expected_agent_count"]
        == configured_roster_size
    )
    assert (
        reduced_spy.call_args.kwargs["expected_agent_count"]
        == configured_roster_size
    )

    # Losing evidence must never increase intermediate confidence - the
    # same monotonicity NB-4/NB-5 proved at the ConfidenceEngine level,
    # now observed through the real AtlasBrain call site.
    full_intermediate = full_decision.metadata["intermediate_confidence"]
    reduced_intermediate = reduced_decision.metadata["intermediate_confidence"]
    assert reduced_intermediate <= full_intermediate
