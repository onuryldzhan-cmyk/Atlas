"""Contract tests for Benjamini-Hochberg false discovery rate control."""

from __future__ import annotations

import math

import pytest

from research.multiple_testing import (
    MultipleTestingError,
    benjamini_hochberg,
)

# The worked example from Benjamini & Hochberg (1995).
BH1995_P_VALUES = [
    0.001, 0.008, 0.039, 0.041, 0.042, 0.060, 0.074, 0.205, 0.212, 0.216,
]


def test_matches_the_published_worked_example():
    decision = benjamini_hochberg(BH1995_P_VALUES, q=0.05)
    assert decision.n_tests == 10
    assert decision.n_rejected == 2
    assert decision.rejected[:2] == (True, True)
    assert not any(decision.rejected[2:])
    assert decision.critical_p_value == pytest.approx(0.008)


def test_adjusted_p_values_match_the_step_up_formula():
    decision = benjamini_hochberg(BH1995_P_VALUES, q=0.05)
    expected = [0.01, 0.04, 0.084, 0.084, 0.084, 0.1, 0.10571429, 0.216, 0.216, 0.216]
    assert decision.adjusted_p_values == pytest.approx(expected, rel=1e-6)


def test_rejecting_on_adjusted_p_equals_the_step_up_procedure():
    """The two formulations are equivalent; the implementation relies on it."""
    q = 0.05
    p_values = [0.0001, 0.004, 0.01, 0.02, 0.03, 0.2, 0.5, 0.9]
    decision = benjamini_hochberg(p_values, q=q)

    ordered = sorted(p_values)
    m = len(ordered)
    step_up_k = 0
    for index, value in enumerate(ordered, start=1):
        if value <= (index / m) * q:
            step_up_k = index

    assert decision.n_rejected == step_up_k
    from_adjusted = sum(1 for a in decision.adjusted_p_values if a <= q)
    assert from_adjusted == step_up_k


def test_adjusted_p_values_are_monotone_in_sorted_p_order():
    p_values = [0.9, 0.001, 0.3, 0.02, 0.6, 0.05]
    decision = benjamini_hochberg(p_values, q=0.1)
    paired = sorted(zip(decision.p_values, decision.adjusted_p_values))
    adjusted = [a for _, a in paired]
    assert adjusted == sorted(adjusted)


def test_adjusted_p_values_never_exceed_one():
    decision = benjamini_hochberg([0.4, 0.8, 0.95, 0.99], q=0.05)
    assert all(0.0 <= a <= 1.0 for a in decision.adjusted_p_values)


def test_results_are_aligned_with_the_input_order():
    ordered = [0.001, 0.30, 0.008, 0.90]
    decision = benjamini_hochberg(ordered, q=0.05, labels=["a", "b", "c", "d"])
    assert decision.p_values == tuple(ordered)
    assert decision.is_rejected("a")
    assert decision.is_rejected("c")
    assert not decision.is_rejected("b")
    assert not decision.is_rejected("d")
    assert decision.rejected_labels == ("a", "c")


def test_bh_is_never_less_powerful_than_bonferroni():
    p_values = [0.001, 0.006, 0.011, 0.02, 0.3, 0.7]
    q = 0.05
    decision = benjamini_hochberg(p_values, q=q)
    bonferroni = sum(1 for p in p_values if p <= q / len(p_values))
    assert decision.n_rejected >= bonferroni


def test_no_discoveries_when_every_p_value_is_one():
    decision = benjamini_hochberg([1.0] * 6, q=0.05)
    assert decision.n_rejected == 0
    assert decision.critical_p_value is None
    assert decision.rejected_labels == ()


def test_all_discoveries_when_every_p_value_is_zero():
    decision = benjamini_hochberg([0.0] * 5, q=0.05)
    assert decision.n_rejected == 5
    assert all(decision.rejected)


def test_single_test_family_reduces_to_the_raw_p_value():
    assert benjamini_hochberg([0.04], q=0.05).n_rejected == 1
    assert benjamini_hochberg([0.06], q=0.05).n_rejected == 0


def test_ties_are_handled_consistently():
    decision = benjamini_hochberg([0.02, 0.02, 0.02, 0.9], q=0.05)
    adjusted = decision.adjusted_p_values
    assert adjusted[0] == adjusted[1] == adjusted[2]


def test_an_incomplete_family_overstates_discoveries():
    """Why the registry must enumerate every hypothesis tested.

    Two strong results survive on their own, and are wiped out once the
    fifty worthless hypotheses that were also tested are included.
    """
    survivors_only = benjamini_hochberg([0.001, 0.008], q=0.05)
    assert survivors_only.n_rejected == 2

    complete_family = benjamini_hochberg([0.001, 0.008] + [1.0] * 50, q=0.05)
    assert complete_family.n_rejected == 0


def test_larger_q_never_yields_fewer_discoveries():
    p_values = [0.001, 0.02, 0.04, 0.07, 0.3]
    counts = [
        benjamini_hochberg(p_values, q=q).n_rejected for q in (0.01, 0.05, 0.1, 0.2)
    ]
    assert counts == sorted(counts)


# --- validation ----------------------------------------------------------


@pytest.mark.parametrize("q", [0.0, 1.0, -0.1, 1.5])
def test_q_must_lie_strictly_inside_the_unit_interval(q):
    with pytest.raises(MultipleTestingError, match="q must"):
        benjamini_hochberg([0.01], q=q)


def test_empty_family_is_rejected():
    with pytest.raises(MultipleTestingError, match="at least one test"):
        benjamini_hochberg([], q=0.05)


@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_p_values_outside_the_unit_interval_are_rejected(bad):
    with pytest.raises(MultipleTestingError, match=r"\[0.0, 1.0\]"):
        benjamini_hochberg([0.01, bad], q=0.05)


def test_non_finite_p_values_are_rejected():
    with pytest.raises(MultipleTestingError, match="finite"):
        benjamini_hochberg([0.01, math.nan], q=0.05)


def test_label_count_must_match_p_value_count():
    with pytest.raises(MultipleTestingError, match="does not match"):
        benjamini_hochberg([0.01, 0.02], q=0.05, labels=["only-one"])


def test_labels_must_be_unique_within_a_family():
    with pytest.raises(MultipleTestingError, match="unique"):
        benjamini_hochberg([0.01, 0.02], q=0.05, labels=["dup", "dup"])


def test_querying_an_unknown_label_is_an_error():
    decision = benjamini_hochberg([0.01], q=0.05, labels=["known"])
    with pytest.raises(MultipleTestingError, match="not part of this family"):
        decision.is_rejected("unknown")
    with pytest.raises(MultipleTestingError, match="not part of this family"):
        decision.adjusted_p_value("unknown")


def test_decision_serialises_to_a_plain_dict():
    decision = benjamini_hochberg([0.01, 0.4], q=0.05, labels=["a", "b"])
    payload = decision.as_dict()
    assert payload["n_tests"] == 2
    assert payload["labels"] == ["a", "b"]
    assert payload["q"] == 0.05
