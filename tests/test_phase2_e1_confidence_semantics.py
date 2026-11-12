"""Phase-2 E1: confidence semantics are explicit.

Atlas's ``confidence`` is weighted agent consensus over the full expected roster
(NB-5), availability-penalised (NB-4). It is not P(win) and no calibration model
exists, so ``calibrated_p_win`` stays None (unknown) - never fabricated - and the
risk floors are unchanged by the naming. The arithmetic itself is pinned by
tests/test_block3_package4_confidence_semantics.py; this file pins the meaning.
"""

from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

import pytest

from ai.core.intelligence.agent_fusion import (
    CONFIDENCE_SEMANTICS,
    AgentFusion,
    AgentFusionResult,
)
from core.risk_engine import RiskPolicy

WEIGHTS = AgentFusion.WEIGHTS
ROOT = Path(__file__).resolve().parents[1]


def fuse(**scores) -> AgentFusionResult:
    engine = AgentFusion()
    return engine.fuse({n: {"action": engine.score_to_action(s), "score": s} for n, s in scores.items()})


def roster(score):
    return {name: score for name in WEIGHTS}


def test_semantics_label_says_consensus_not_probability():
    assert CONFIDENCE_SEMANTICS == "WEIGHTED_CONSENSUS_NOT_PROBABILITY"


def test_unanimous_weak_agents_are_full_consensus_not_a_certain_win():
    """Five barely-BUY votes give the same 1.0 as five strong ones: agreement, not P(win)."""
    weak, strong = fuse(**roster(0.6)), fuse(**roster(0.95))
    assert weak.action == strong.action == "BUY"
    assert weak.confidence == strong.confidence == pytest.approx(1.0)
    for r in (weak, strong):
        d = r.to_dict()
        assert d["consensus"] == d["confidence"] == 1.0
        assert d["calibrated_p_win"] is None and d["calibration_ref"] is None
        assert d["confidence_semantics"] == CONFIDENCE_SEMANTICS


def test_full_roster_coverage_is_one():
    assert fuse(**roster(0.9)).coverage == pytest.approx(1.0)


def test_partial_roster_reports_coverage_and_consensus_never_exceeds_it():
    three = fuse(technical=1.0, momentum=1.0, risk=1.0)
    expected = (WEIGHTS["technical"] + WEIGHTS["momentum"] + WEIGHTS["risk"]) / sum(WEIGHTS.values())
    assert three.coverage == pytest.approx(round(expected, 4))
    assert three.confidence <= three.coverage + 1e-9          # missing agents never count as agreement (NB-5)
    assert three.to_dict()["coverage"] == pytest.approx(three.coverage)


def test_missing_agents_below_the_floor_are_zero_consensus_with_known_coverage():
    two = fuse(technical=1.0, momentum=1.0)
    assert two.reason == "INSUFFICIENT_EVIDENCE" and two.confidence == 0.0
    assert 0 < two.coverage < 1
    assert two.to_dict()["calibrated_p_win"] is None


def test_weighted_votes_dissent_lowers_consensus():
    agree = fuse(**roster(0.9))
    split = fuse(technical=0.9, momentum=0.9, risk=0.9, macro=0.1, sentiment=0.1)
    assert split.confidence < agree.confidence
    assert split.coverage == agree.coverage == pytest.approx(1.0)  # same coverage, less agreement


def test_removing_an_agent_never_raises_consensus_nb4():
    full = fuse(technical=0.9, momentum=0.9, risk=0.9, macro=0.1, sentiment=0.9)
    without_dissent = fuse(technical=0.9, momentum=0.9, risk=0.9, sentiment=0.9)
    assert without_dissent.confidence <= full.confidence or without_dissent.coverage < full.coverage
    assert without_dissent.confidence <= without_dissent.coverage + 1e-9


def test_legacy_constructor_without_coverage_is_unknown_not_fabricated():
    legacy = AgentFusionResult(action="HOLD", confidence=0.0, scores={})
    assert legacy.coverage is None and legacy.to_dict()["coverage"] is None


def test_decision_metadata_carries_the_semantics():
    from ai.core.intelligence.decision_builder import DecisionBuilder

    meta = DecisionBuilder._confidence_semantics(fuse(**roster(0.9)))
    assert meta == {"meaning": CONFIDENCE_SEMANTICS, "consensus": 1.0, "coverage": 1.0,
                    "calibrated_p_win": None, "calibration_ref": None}


def test_risk_floor_is_unchanged_and_documented_as_a_consensus_floor():
    """E1 renames nothing that gates trading: the floors are the same numbers."""
    import core.risk_engine as risk_engine

    assert RiskPolicy.__dataclass_fields__["global_minimum_confidence"].default == D("0.60")
    assert "consensus" in (risk_engine.RiskPolicy.__doc__ or "").lower()
    assert "not a probability" in (risk_engine.RiskPolicy.__doc__ or "").lower()


def test_operator_ui_labels_confidence_as_consensus_not_probability():
    dashboard = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
    home = (ROOT / "templates" / "home.html").read_text(encoding="utf-8")
    assert "weighted agent consensus, not a win probability" in dashboard
    assert "olasılık değildir" in home
    for text in (dashboard, home):
        lowered = text.lower()
        assert "win probability" not in lowered.replace("not a win probability", "")
        assert "kazanma olasılığı" not in lowered
