"""Lifecycle state machine for research hypotheses.

The machine encodes three properties that the rest of the research track
depends on:

- **Monotonicity.** Every legal transition strictly increases a progress
  rank. Nothing returns to an earlier state.
- **Single-use test segment.** A hypothesis's test data may be read only
  from CALIBRATED, and reading it advances the hypothesis to TESTED.
  Because transitions are monotone, CALIBRATED is unreachable again, so
  "test, adjust, re-test" is structurally impossible rather than merely
  discouraged.
- **No live authority.** There is deliberately no LIVE, PRODUCTION, or
  DEPLOYED state — not even a guarded one. The terminal promotion state is
  VALIDATED, which confers no trading authority of any kind. Per the project
  contract, live/real-money authority is denied by default, and the way a
  state machine is kept from granting it is for the state not to exist.

DRAFT and WITHDRAWN describe the composition phase, before a hypothesis is
sealed into the registry. This step does not persist that phase; the states
are defined here so the contract is complete.

This module holds no data and performs no I/O.
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping


class LifecycleError(Exception):
    """Base error for lifecycle contract violations."""


class IllegalTransitionError(LifecycleError):
    """Raised when a transition is not permitted by the state machine."""


class HypothesisState(str, Enum):
    """The states a research hypothesis may occupy."""

    DRAFT = "DRAFT"
    REGISTERED = "REGISTERED"
    CALIBRATED = "CALIBRATED"
    TESTED = "TESTED"
    CANDIDATE = "CANDIDATE"
    PAPER_VALIDATING = "PAPER_VALIDATING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"
    WITHDRAWN = "WITHDRAWN"


TERMINAL_STATES: frozenset[HypothesisState] = frozenset(
    {
        HypothesisState.REJECTED,
        HypothesisState.RETIRED,
        HypothesisState.WITHDRAWN,
    }
)

#: Terminal states share one rank so that every legal transition, including
#: the exits, strictly increases progress. This is asserted by the tests.
_TERMINAL_RANK = 99

_PROGRESS_RANK: Mapping[HypothesisState, int] = {
    HypothesisState.DRAFT: 0,
    HypothesisState.REGISTERED: 1,
    HypothesisState.CALIBRATED: 2,
    HypothesisState.TESTED: 3,
    HypothesisState.CANDIDATE: 4,
    HypothesisState.PAPER_VALIDATING: 5,
    HypothesisState.VALIDATED: 6,
    HypothesisState.REJECTED: _TERMINAL_RANK,
    HypothesisState.RETIRED: _TERMINAL_RANK,
    HypothesisState.WITHDRAWN: _TERMINAL_RANK,
}

_TRANSITIONS: Mapping[HypothesisState, frozenset[HypothesisState]] = {
    HypothesisState.DRAFT: frozenset(
        {HypothesisState.REGISTERED, HypothesisState.WITHDRAWN}
    ),
    HypothesisState.REGISTERED: frozenset(
        {HypothesisState.CALIBRATED, HypothesisState.REJECTED}
    ),
    HypothesisState.CALIBRATED: frozenset(
        {HypothesisState.TESTED, HypothesisState.REJECTED}
    ),
    HypothesisState.TESTED: frozenset(
        {HypothesisState.CANDIDATE, HypothesisState.REJECTED}
    ),
    HypothesisState.CANDIDATE: frozenset(
        {HypothesisState.PAPER_VALIDATING, HypothesisState.RETIRED}
    ),
    HypothesisState.PAPER_VALIDATING: frozenset(
        {HypothesisState.VALIDATED, HypothesisState.RETIRED}
    ),
    HypothesisState.VALIDATED: frozenset({HypothesisState.RETIRED}),
    HypothesisState.REJECTED: frozenset(),
    HypothesisState.RETIRED: frozenset(),
    HypothesisState.WITHDRAWN: frozenset(),
}

#: The only state from which the single-use test segment may be read.
_TEST_READABLE_FROM: HypothesisState = HypothesisState.CALIBRATED

#: The only transition that cannot be made on a hypothesis's own evidence.
#: Promotion depends on how many *other* hypotheses were tested in the same
#: family, so it requires a family-level FDR decision (see multiple_testing).
FAMILY_ADJUDICATED_TRANSITION: tuple[HypothesisState, HypothesisState] = (
    HypothesisState.TESTED,
    HypothesisState.CANDIDATE,
)


def is_terminal(state: HypothesisState) -> bool:
    """Return True when no further transition is possible."""
    return state in TERMINAL_STATES


def allowed_transitions(state: HypothesisState) -> frozenset[HypothesisState]:
    """Return the states reachable in one step from ``state``."""
    return _TRANSITIONS[HypothesisState(state)]


def progress_rank(state: HypothesisState) -> int:
    """Return the monotone progress rank of ``state``."""
    return _PROGRESS_RANK[HypothesisState(state)]


def can_transition(source: HypothesisState, target: HypothesisState) -> bool:
    """Return True when ``source -> target`` is a legal transition."""
    return HypothesisState(target) in allowed_transitions(source)


def validate_transition(source: HypothesisState, target: HypothesisState) -> None:
    """Raise IllegalTransitionError unless ``source -> target`` is legal."""
    source = HypothesisState(source)
    target = HypothesisState(target)
    if can_transition(source, target):
        return
    if is_terminal(source):
        raise IllegalTransitionError(
            f"{source.value} is terminal; no transition to {target.value} is possible"
        )
    permitted = ", ".join(sorted(s.value for s in allowed_transitions(source)))
    raise IllegalTransitionError(
        f"illegal transition {source.value} -> {target.value}; "
        f"permitted from {source.value}: {permitted or 'none'}"
    )


def can_evaluate_test(state: HypothesisState) -> bool:
    """Return True when the single-use test segment may be read.

    True only from CALIBRATED. Evaluating the test segment advances the
    hypothesis to TESTED, and monotonicity makes CALIBRATED unreachable
    thereafter, which is what makes the test segment single-use.
    """
    return HypothesisState(state) is _TEST_READABLE_FROM
