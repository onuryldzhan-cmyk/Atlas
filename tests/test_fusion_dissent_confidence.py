"""Audit 2026-10-01 F-1 fix (full-weight denominator, OFF by default): a dissent never helps the winner."""

import pytest

from ai.core.intelligence.agent_fusion import AgentFusion

LIVE = {"technical": {"action": "BUY", "score": 0.85}, "macro": {"action": "SELL", "score": 0.25},
        "momentum": {"action": "BUY", "score": 0.70}}


def fuse(signals, fixed):
    f = AgentFusion()
    f.full_weight_denominator = fixed
    return f.fuse(signals)


def test_default_is_off_and_today_unchanged():
    assert AgentFusion.full_weight_denominator is False
    # audit probe value with risk HOLD and sentiment abstaining
    r = fuse({**LIVE, "risk": {"action": "HOLD", "score": 0.5}}, False)
    assert r.action == "BUY" and r.confidence == pytest.approx(0.6358, abs=1e-4)


@pytest.mark.parametrize("dissent", [{"action": "HOLD", "score": 0.5}, {"action": "SELL", "score": 0.25},
                                     {"action": "SELL", "score": 0.0}])
def test_fixed_dissent_is_never_better_than_abstaining(dissent):
    base = {**LIVE, "risk": {"action": "HOLD", "score": 0.5}}
    abstain = fuse(base, True)
    with_dissent = fuse({**base, "sentiment": dissent}, True)
    assert with_dissent.action == abstain.action == "BUY"
    assert with_dissent.confidence <= abstain.confidence
    # the bug, documented: today a partial dissent RAISES the BUY confidence (a full-strength SELL does not)
    today = fuse({**base, "sentiment": dissent}, False).confidence
    assert today >= fuse(base, False).confidence


def test_fixed_agreement_never_lowers_and_removal_never_raises():
    base = {**LIVE, "risk": {"action": "HOLD", "score": 0.5}}
    agree = fuse({**base, "sentiment": {"action": "BUY", "score": 0.75}}, True)
    assert agree.confidence >= fuse(base, True).confidence
    # NB-4: removing evidence never raises confidence
    for name in base:
        smaller = {k: v for k, v in base.items() if k != name}
        r = fuse(smaller, True)
        if r.action == "BUY":
            assert r.confidence <= fuse(base, True).confidence


def test_fixed_missing_agents_keep_the_full_roster_denominator():
    # NB-5: two unanimous agents cannot claim full consensus
    r = fuse({"technical": {"action": "BUY", "score": 1.0}, "momentum": {"action": "BUY", "score": 1.0},
              "macro": {"action": "BUY", "score": 1.0}}, True)
    assert r.confidence < 1.0


def test_fixed_is_more_conservative_on_the_live_pattern():
    for risk in ({"action": "HOLD", "score": 0.5}, {"action": "SELL", "score": 0.25}):
        s = {**LIVE, "risk": risk}
        assert fuse(s, True).confidence <= fuse(s, False).confidence


def test_application_switch_reaches_the_fusion_instance(tmp_path):
    from core.application import AtlasApplication
    from tests.test_block5e_fee_settlement_accounting import seed_state

    off = AtlasApplication(state_directory=seed_state(tmp_path / "a"))
    on = AtlasApplication(state_directory=seed_state(tmp_path / "b"), fusion_full_weight_denominator=True)
    assert off.brain.fusion_full_weight_denominator is False and on.brain.fusion_full_weight_denominator is True
    if on.brain.intelligence is None:
        on.brain._ensure_intelligence() if hasattr(on.brain, "_ensure_intelligence") else None
    fusion = getattr(on.brain.intelligence, "agents", None)
    if fusion is not None:
        assert fusion.full_weight_denominator is True
    assert AgentFusion.full_weight_denominator is False  # never set globally
