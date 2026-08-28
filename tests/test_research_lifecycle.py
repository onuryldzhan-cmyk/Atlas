"""Contract tests for the research hypothesis lifecycle state machine."""

from __future__ import annotations

import pytest

from research.lifecycle import (
    TERMINAL_STATES,
    HypothesisState,
    IllegalTransitionError,
    allowed_transitions,
    can_evaluate_test,
    can_transition,
    is_terminal,
    progress_rank,
    validate_transition,
)


def test_every_state_has_a_transition_set_and_a_rank():
    for state in HypothesisState:
        assert isinstance(allowed_transitions(state), frozenset)
        assert isinstance(progress_rank(state), int)


def test_every_legal_transition_strictly_increases_progress_rank():
    """Monotonicity is what makes the test segment single-use."""
    for source in HypothesisState:
        for target in allowed_transitions(source):
            assert progress_rank(target) > progress_rank(source), (
                f"{source.value} -> {target.value} does not advance progress"
            )


def test_terminal_states_have_no_outgoing_transitions():
    for state in TERMINAL_STATES:
        assert is_terminal(state)
        assert allowed_transitions(state) == frozenset()


def test_non_terminal_states_are_not_dead_ends():
    for state in HypothesisState:
        if state not in TERMINAL_STATES:
            assert allowed_transitions(state), f"{state.value} is a dead end"


def test_no_live_trading_state_exists():
    """Live authority is denied by default: the state must not exist at all."""
    forbidden = {"LIVE", "PRODUCTION", "DEPLOYED", "REAL", "TRADING"}
    names = {state.name for state in HypothesisState}
    assert names.isdisjoint(forbidden)
    assert HypothesisState.VALIDATED in HypothesisState


def test_every_state_is_reachable_from_draft():
    reached = {HypothesisState.DRAFT}
    frontier = [HypothesisState.DRAFT]
    while frontier:
        current = frontier.pop()
        for target in allowed_transitions(current):
            if target not in reached:
                reached.add(target)
                frontier.append(target)
    assert reached == set(HypothesisState)


def test_a_tested_hypothesis_can_never_return_to_calibrated():
    """Without this, "test, adjust, re-test" would be available."""
    assert not can_transition(HypothesisState.TESTED, HypothesisState.CALIBRATED)
    with pytest.raises(IllegalTransitionError):
        validate_transition(HypothesisState.TESTED, HypothesisState.CALIBRATED)


def test_a_rejected_hypothesis_cannot_be_revived():
    with pytest.raises(IllegalTransitionError, match="terminal"):
        validate_transition(HypothesisState.REJECTED, HypothesisState.CANDIDATE)


def test_test_segment_is_readable_only_from_calibrated():
    for state in HypothesisState:
        assert can_evaluate_test(state) is (state is HypothesisState.CALIBRATED)


def test_promotion_requires_passing_through_tested():
    assert not can_transition(
        HypothesisState.CALIBRATED, HypothesisState.CANDIDATE
    )
    assert can_transition(HypothesisState.TESTED, HypothesisState.CANDIDATE)


def test_validate_transition_accepts_legal_moves():
    validate_transition(HypothesisState.DRAFT, HypothesisState.REGISTERED)
    validate_transition(HypothesisState.REGISTERED, HypothesisState.CALIBRATED)
    validate_transition(HypothesisState.CALIBRATED, HypothesisState.TESTED)
    validate_transition(HypothesisState.TESTED, HypothesisState.CANDIDATE)
    validate_transition(
        HypothesisState.CANDIDATE, HypothesisState.PAPER_VALIDATING
    )
    validate_transition(
        HypothesisState.PAPER_VALIDATING, HypothesisState.VALIDATED
    )
    validate_transition(HypothesisState.VALIDATED, HypothesisState.RETIRED)


def test_transition_error_names_the_permitted_targets():
    with pytest.raises(IllegalTransitionError) as excinfo:
        validate_transition(HypothesisState.REGISTERED, HypothesisState.VALIDATED)
    message = str(excinfo.value)
    assert "CALIBRATED" in message
    assert "REJECTED" in message
