"""Block-3 MEDIUM-1: M-2 winner-selection precision authority.

Package 4 corrected the M-2 confidence *denominator* so that an absent
participant is charged its full configured weight instead of vanishing from
the normalization. That fixed the inversion it was aimed at, but the final
independent audit found a second, independent channel for the same defect,
in the *numerator*.

``fuse()`` selected the winning bucket with ``max()`` over ``scores`` - the
distribution rounded to three decimals for display - while the confidence
numerator used that bucket's unrounded mass. Two buckets whose true masses
differ only in the fourth decimal collapse onto one 3-decimal share, and
``max()`` then returns the first key in insertion order (BUY, SELL, HOLD).
So BUY could be declared the winner while SELL held strictly more mass.
Removing a participant broke the collision, the larger true mass became the
numerator, and reported confidence *rose* on evidence removal - the exact
thing M-2 exists to forbid. Independent grid search found 69 such inversions
across 6.7M removals, up to +0.0007, including cases where the removed
participant voted with factor 1.0 so the denominator was provably unchanged.

The correction makes one quantity serve both roles: the winner is chosen by
bucket mass quantized at ``MASS_PRECISION``, and that same quantized value is
the confidence numerator. ``scores`` keeps its 3-decimal rounding and stays
display-only. The invariant being frozen here is broader than the arithmetic:
decision authority must never depend on presentation rounding.

No weight, threshold, participation floor, or availability semantic is
changed by any of this.
"""

from __future__ import annotations

import itertools

import pytest

from ai.core.intelligence.agent_fusion import AgentFusion


WEIGHTS = AgentFusion.WEIGHTS
NAMES = tuple(WEIGHTS)


def action_for(score: float) -> str:
    if score >= 0.60:
        return "BUY"
    if score <= 0.40:
        return "SELL"
    return "HOLD"


def signals(assignment: dict[str, float]) -> dict:
    return {
        name: {"action": action_for(score), "score": score}
        for name, score in assignment.items()
    }


def true_masses(assignment: dict[str, float]) -> dict[str, float]:
    """Bucket masses re-derived here rather than read back from fuse()."""
    masses = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    for name, score in assignment.items():
        weight = WEIGHTS[name]
        action = action_for(score)
        if action == "BUY":
            masses["BUY"] += score * weight
        elif action == "SELL":
            masses["SELL"] += (1 - score) * weight
        else:
            masses["HOLD"] += 0.5 * weight
    return masses


@pytest.fixture
def fusion() -> AgentFusion:
    return AgentFusion()


# --------------------------------------------------------------------------
# the two deterministic counterexamples the audit reproduced
# --------------------------------------------------------------------------


#: Five participants whose BUY and SELL masses (0.41300000000000003 vs
#: 0.4138) both round to a 0.5 share. Scores are 3-decimal, i.e. exactly the
#: shape ``evaluate()`` produces.
AUDIT_CASE_DISPLAY_TIE = {
    "momentum": 0.207, "risk": 0.153, "sentiment": 0.994,
    "macro": 0.142, "technical": 0.784,
}

#: The removed participant votes BUY with score 1.0, so its vote factor is 1
#: and the denominator is mathematically unchanged by its removal. Any
#: confidence movement here is therefore attributable to the numerator alone,
#: which is what isolates this defect from the Package-4 denominator work.
AUDIT_CASE_UNCHANGED_DENOMINATOR = {
    "technical": 1.0, "macro": 0.0, "risk": 0.4,
    "momentum": 0.3985687505281087, "sentiment": 0.4,
}


@pytest.mark.parametrize(
    "assignment, victim",
    [
        (AUDIT_CASE_DISPLAY_TIE, "sentiment"),
        (AUDIT_CASE_UNCHANGED_DENOMINATOR, "technical"),
    ],
    ids=["display_tie", "unchanged_denominator"],
)
def test_audit_counterexamples_no_longer_invert(fusion, assignment, victim):
    """A: the reproduced inversions must not survive."""
    before = fusion.fuse(signals(assignment))
    reduced = {k: v for k, v in assignment.items() if k != victim}
    after = fusion.fuse(signals(reduced))

    assert after.confidence <= before.confidence


def test_display_tie_case_now_selects_the_bucket_holding_more_mass(fusion):
    """G: the specific mis-selection that caused the inversion is gone.

    SELL genuinely holds more mass than BUY here, yet both render as a 0.5
    share, so this is precisely the input on which the old display-rounded
    selection picked BUY.
    """
    masses = true_masses(AUDIT_CASE_DISPLAY_TIE)
    assert masses["SELL"] > masses["BUY"]

    result = fusion.fuse(signals(AUDIT_CASE_DISPLAY_TIE))

    assert result.scores["BUY"] == result.scores["SELL"]   # still a display tie
    assert result.action == "SELL"                          # authority is mass


# --------------------------------------------------------------------------
# the general properties, over a bounded but adversarial grid
# --------------------------------------------------------------------------


#: Boundary-heavy: the score_to_action thresholds, full conviction both ways,
#: and the neutral point. Ties between buckets are common in this region,
#: which is where the defect lived.
GRID = (0.0, 0.4, 0.401, 0.5, 0.599, 0.6, 1.0)


def _states():
    for size in (3, 4):
        for subset in itertools.combinations(NAMES, size):
            for combo in itertools.product(GRID, repeat=size):
                yield dict(zip(subset, combo))


def test_removing_any_participant_never_increases_confidence(fusion):
    """B/C/D: the frozen M-2 invariant, over every state in the grid.

    Supportive and dissenting removals are not split into separate tests
    because the invariant is deliberately unconditional: no removal of any
    participant, whatever it voted, may raise confidence.
    """
    violations = []

    for assignment in _states():
        before = fusion.fuse(signals(assignment))
        for victim in assignment:
            reduced = {k: v for k, v in assignment.items() if k != victim}
            after = fusion.fuse(signals(reduced))
            if after.confidence > before.confidence:
                violations.append(
                    (assignment, victim, before.confidence, after.confidence)
                )

    assert violations == []


def test_authoritative_winner_always_holds_maximal_true_mass(fusion):
    """G: selection authority is mass, never the rounded distribution."""
    for assignment in _states():
        result = fusion.fuse(signals(assignment))
        if result.reason != "FUSED_EVIDENCE":
            continue
        masses = true_masses(assignment)
        assert masses[result.action] == pytest.approx(max(masses.values()))


def test_confidence_stays_within_the_unit_interval(fusion):
    """I: no input may produce a confidence outside [0, 1]."""
    for assignment in _states():
        assert 0.0 <= fusion.fuse(signals(assignment)).confidence <= 1.0


def test_displayed_distribution_remains_the_three_decimal_bucket_share(fusion):
    """F: `scores` is unchanged - it is still the 3dp share of the surviving
    mass, and it is still what a caller reads for presentation."""
    for assignment in _states():
        result = fusion.fuse(signals(assignment))
        if result.reason != "FUSED_EVIDENCE":
            continue
        masses = true_masses(assignment)
        total = sum(masses.values())
        for bucket in ("BUY", "SELL", "HOLD"):
            assert result.scores[bucket] == round(masses[bucket] / total, 3)


def test_selection_is_deterministic_across_repeated_calls(fusion):
    """H: an exact tie must resolve the same way every time."""
    for assignment in itertools.islice(_states(), 0, None, 37):
        first = fusion.fuse(signals(assignment))
        second = fusion.fuse(signals(assignment))
        assert (first.action, first.confidence, first.scores) == (
            second.action, second.confidence, second.scores
        )


def test_a_genuine_tie_yields_the_same_confidence_either_way(fusion):
    """H: when two buckets hold exactly equal mass, the insertion-order
    tie-break cannot change the reported confidence, because the numerator is
    the same quantity whichever of them is named the winner.

    This is what makes the remaining tie-break safe to leave deterministic
    rather than needing a policy of its own: under the old scheme a "tie" was
    a rounding collision between unequal masses, so the choice mattered; now
    a tie is genuine equality, so it cannot.
    """
    # technical BUY@1.0 -> 0.40; momentum and risk SELL@0.0 -> 0.20 + 0.20.
    assignment = {"technical": 1.0, "momentum": 0.0, "risk": 0.0}
    masses = true_masses(assignment)
    assert masses["BUY"] == masses["SELL"]

    result = fusion.fuse(signals(assignment))

    available = sum(WEIGHTS[name] for name in assignment)
    denominator = sum(masses.values()) + (sum(WEIGHTS.values()) - available)
    expected = round(masses["BUY"] / denominator, 4)

    assert result.action == "BUY"                      # deterministic
    assert result.confidence == expected
    assert result.confidence == round(masses["SELL"] / denominator, 4)


# --------------------------------------------------------------------------
# the surrounding contract this change must not move
# --------------------------------------------------------------------------


def test_participation_floor_is_unchanged(fusion):
    """J: the minimum-evidence floor is untouched by the selection change."""
    assert AgentFusion.MIN_PARTICIPATING_AGENTS == 3
    assert AgentFusion.MIN_WEIGHT_COVERAGE == 0.50

    result = fusion.fuse(signals({"technical": 0.9, "momentum": 0.9}))

    assert result.action == "HOLD"
    assert result.confidence == 0.0
    assert result.reason == "INSUFFICIENT_EVIDENCE"


def test_third_provider_interlock_remains_gated(fusion):
    """L: technical+momentum is the only combination reachable today, and it
    must still fail closed. Nothing in this change lifts that interlock."""
    for scores in ({"technical": 1.0, "momentum": 1.0},
                   {"technical": 0.0, "momentum": 0.0}):
        result = fusion.fuse(signals(scores))
        assert result.reason == "INSUFFICIENT_EVIDENCE"
        assert result.confidence == 0.0


def test_full_roster_unanimity_still_reports_the_coverage_ladder(fusion):
    """E: the availability ladder Package 4 established is preserved."""
    full = {name: 1.0 for name in NAMES}
    assert fusion.fuse(signals(full)).confidence == pytest.approx(1.0)

    three = {"technical": 1.0, "momentum": 1.0, "risk": 1.0}
    assert fusion.fuse(signals(three)).confidence == pytest.approx(0.80)
