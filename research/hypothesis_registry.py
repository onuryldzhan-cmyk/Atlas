"""Tamper-evident, append-only registry of pre-registered research hypotheses.

A hypothesis is registered *before* it is evaluated, with its test fully
specified: statistic, direction, alpha, minimum effect size, universe, date
window, and split parameters. Those fields are sealed by a SHA-256 hash over
their canonical JSON serialisation.

The seal exists because the registry is a JSON file on disk. Without it,
``direction`` could be flipped from ``greater`` to ``less`` after seeing a
negative result and nothing would record that it happened. With it, editing
any sealed field makes the stored hash disagree with the recomputed hash and
the registry refuses to load.

``economic_rationale`` is human-written and therefore format-uncontrolled. It
is hashed into the seal rather than being allowed to widen any identity
charset: ``hypothesis_id`` keeps its strict ``HYP-NNNN`` slug regardless of
what the rationale contains.

A hypothesis needing any sealed field changed is not an amended hypothesis —
it is a new one, with a new id, entering the multiple-testing family as an
additional test. Revision is never free; it always costs statistical power.

Nothing is ever edited or deleted. Only ``state`` advances (through the
lifecycle machine) and ``evaluations`` grows. The registry must be able to
enumerate every hypothesis ever tested, including the failures, because
Benjamini-Hochberg controls FDR only over a complete family.

**Validation checks.** A pre-registration also seals a ``check_plan``: which
of the five named validation checks this hypothesis must clear, and each
one's parameters. The plan is sealed for the same reason ``direction`` is —
a check set chosen after seeing results is HARKing at the level of the
validation protocol rather than the hypothesis. Checks are *adjudicated*
here; they are not computed here. A ``CheckResult`` arrives as plain data.

The five checks map onto three segments: BACKTEST scores TRAIN,
WALK_FORWARD scores CALIBRATION, and OUT_OF_SAMPLE, COST_ADJUSTED and
MONTE_CARLO all score the single TEST read. The latter three therefore ride
on *one* TEST evaluation: COST_ADJUSTED re-scores that read under a cost
model and MONTE_CARLO resamples it, neither of which is a second read.

**Runtime-state isolation.** ``registry_path`` is required and has no
default. A relative default would resolve against the process working
directory and write into Atlas's live runtime state when run from the
repository root. Research code never writes to ``memory_data/``, never
touches the paper-trading book, and never constructs AtlasApplication.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from research.lifecycle import (
    FAMILY_ADJUDICATED_TRANSITION,
    HypothesisState,
    IllegalTransitionError,
    can_evaluate_test,
    validate_transition,
)
from research.multiple_testing import FDRDecision, benjamini_hochberg
from research.splitting import SplitSpec

#: Version 2 added the sealed ``check_plan`` to every pre-registration and
#: ``checks`` to every evaluation. Version 3 (owner brief 2026-09-25, Part I)
#: added three more hardening properties: a registry file missing its
#: ``records`` key refuses to load rather than reading as empty; family
#: membership is sealed into a ``family_manifests`` list that every load
#: cross-checks against the actual records, so deleting a member hypothesis
#: can no longer shrink a multiple-testing family unnoticed; and every
#: record's ``state`` is sealed via a hash-chained ``state_chain``, so a
#: hand-edited ``state`` field no longer loads as a silently-promoted
#: hypothesis. Each version bump here is a clean break: no version-N payload
#: can produce a valid version-(N+1) seal, and there is deliberately no
#: backward loading path. ``_load`` refuses any version it does not
#: recognise rather than guessing (fail-closed). No registry file has ever
#: been checked into this repository (``registry_path`` has no default and
#: is never wired to a persisted path in ``core/`` or ``config/``), so this
#: bump carries no data-migration burden.
REGISTRY_FORMAT_VERSION = 3

_HYPOTHESIS_ID_PATTERN = re.compile(r"^HYP-[0-9]{4}$")
_FAMILY_ID_PATTERN = re.compile(r"^FAM-[A-Z0-9-]{1,32}$")
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{2,20}$")

DIRECTIONS: frozenset[str] = frozenset({"greater", "less", "two_sided"})
SEGMENTS: frozenset[str] = frozenset({"TRAIN", "CALIBRATION", "TEST"})


class CheckName(str, Enum):
    """The five named validation checks a hypothesis may be required to clear.

    This set is closed. A sixth check is a change to the validation protocol
    and belongs in a reviewed change to this enum, not in a free-text field.
    """

    BACKTEST = "BACKTEST"
    WALK_FORWARD = "WALK_FORWARD"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"
    COST_ADJUSTED = "COST_ADJUSTED"
    MONTE_CARLO = "MONTE_CARLO"


class CheckVerdict(str, Enum):
    """A check either passed or it did not.

    There is deliberately no third value. "INCONCLUSIVE" or "SKIPPED" would
    be a place for a failing check to hide, and the adjudicator already
    treats an absent required check as a failure (the NB-4 analogue), so a
    check that could not be computed simply is not recorded.
    """

    PASS = "PASS"
    FAIL = "FAIL"


class CheckPlanStatus(str, Enum):
    """Whether a hypothesis's sealed check plan has been fully answered.

    INCOMPLETE is distinct from COMPLETE_FAIL on purpose: "three of five
    checks are still outstanding" and "all five ran and one failed" are
    different operational situations. Both are non-promotable.
    """

    INCOMPLETE = "INCOMPLETE"
    COMPLETE_PASS = "COMPLETE_PASS"
    COMPLETE_FAIL = "COMPLETE_FAIL"


#: Canonical check order. A check plan is normalised into this order so that
#: two plans requiring the same checks seal identically regardless of the
#: order they were written in.
CHECK_ORDER: tuple[CheckName, ...] = (
    CheckName.BACKTEST,
    CheckName.WALK_FORWARD,
    CheckName.OUT_OF_SAMPLE,
    CheckName.COST_ADJUSTED,
    CheckName.MONTE_CARLO,
)

#: The data segment each check is scored against. OUT_OF_SAMPLE *is* the
#: single irreversible TEST read; COST_ADJUSTED re-scores that same read
#: under a cost model and MONTE_CARLO resamples it. None of the three is an
#: additional read, which is why all three attach to one TEST evaluation.
CHECK_SEGMENTS: Mapping[CheckName, str] = {
    CheckName.BACKTEST: "TRAIN",
    CheckName.WALK_FORWARD: "CALIBRATION",
    CheckName.OUT_OF_SAMPLE: "TEST",
    CheckName.COST_ADJUSTED: "TEST",
    CheckName.MONTE_CARLO: "TEST",
}

#: Parameters each check must pre-register, as ``name -> kind``. A required
#: check with unspecified parameters is a check whose threshold can be chosen
#: after the fact, so the plan is rejected rather than defaulted.
#:
#: BACKTEST reuses ``minimum_effect_size``, the threshold convention this
#: module already applies to the TEST segment, rather than inventing a second
#: one. OUT_OF_SAMPLE takes no parameters: its identity is the pre-registered
#: split's TEST segment, already sealed via ``split_spec``.
_CHECK_PARAMETER_SCHEMA: Mapping[CheckName, Mapping[str, str]] = {
    CheckName.BACKTEST: {"minimum_effect_size": "non_negative_float"},
    CheckName.WALK_FORWARD: {
        "window_count": "positive_int",
        "minimum_fraction_passing": "unit_fraction",
    },
    CheckName.OUT_OF_SAMPLE: {},
    CheckName.COST_ADJUSTED: {
        "cost_model_id": "identifier",
        "cost_bps": "non_negative_float",
    },
    CheckName.MONTE_CARLO: {
        "trial_count": "positive_int",
        "null_model_id": "identifier",
        "percentile_threshold": "percentile",
    },
}

#: Which sealed parameter is the number a check's verdict is decided against.
#:
#: Sealing a threshold stops it being *edited* after the fact; on its own it
#: does not stop the check being *computed* against a different number and a
#: PASS handed in regardless. Binding closes that: a result must declare the
#: threshold it used, and it must be the one the plan sealed.
#:
#: WALK_FORWARD binds ``minimum_fraction_passing`` for exactly the same
#: reason as the other three -- "6 of 10 windows cleared, threshold 0.3" is a
#: pass the plan never authorised if the plan sealed 0.6.
#:
#: OUT_OF_SAMPLE seals no threshold: its identity is the pre-registered
#: split's TEST segment, already sealed through ``split_spec`` and enforced
#: structurally by the single-use test read. A check with no sealed threshold
#: must carry no ``threshold_applied`` at all, so that a stored number can
#: never be mistaken for a binding that was never checked.
_CHECK_THRESHOLD_PARAMETER: Mapping[CheckName, str | None] = {
    CheckName.BACKTEST: "minimum_effect_size",
    CheckName.WALK_FORWARD: "minimum_fraction_passing",
    CheckName.OUT_OF_SAMPLE: None,
    CheckName.COST_ADJUSTED: "cost_bps",
    CheckName.MONTE_CARLO: "percentile_threshold",
}

#: States in which a hypothesis has not yet produced a test result.
PENDING_STATES: frozenset[HypothesisState] = frozenset(
    {
        HypothesisState.DRAFT,
        HypothesisState.REGISTERED,
        HypothesisState.CALIBRATED,
    }
)

#: Segments may be read only from these states. TRAIN and CALIBRATION have
#: unlimited access by design; TEST is readable only from CALIBRATED, exactly
#: once, and reading it advances the hypothesis to TESTED.
_SEGMENT_ALLOWED_STATES: Mapping[str, frozenset[HypothesisState]] = {
    "TRAIN": frozenset({HypothesisState.REGISTERED, HypothesisState.CALIBRATED}),
    "CALIBRATION": frozenset(
        {HypothesisState.REGISTERED, HypothesisState.CALIBRATED}
    ),
    "TEST": frozenset({HypothesisState.CALIBRATED}),
}


class RegistryError(Exception):
    """Base error for hypothesis registry contract violations."""


class DuplicateHypothesisError(RegistryError):
    """Raised when a hypothesis id is already registered."""


class UnknownHypothesisError(RegistryError):
    """Raised when a hypothesis id is not present in the registry."""


class SealVerificationError(RegistryError):
    """Raised when a stored pre-registration hash does not match its content."""


class EvaluationNotPermittedError(RegistryError):
    """Raised when a data segment may not be read in the current state."""


class UnplannedCheckError(RegistryError):
    """Raised when a check result is recorded outside the sealed check plan.

    Accepting one would let a check be introduced after results are visible,
    which is exactly what sealing the plan exists to prevent.
    """


class ThresholdBindingError(RegistryError):
    """Raised when a check was scored against a threshold the plan did not seal.

    Sealing a threshold makes it un-editable; binding makes it *load-bearing*.
    Without this, a plan could seal ``minimum_effect_size: 0.5`` while the
    engine scored the check against 0.0001 and handed in a PASS, and the
    sealed number would be decoration.
    """


class FamilyAdjudicationRequiredError(RegistryError):
    """Raised when TESTED -> CANDIDATE is attempted outside family adjudication.

    Promotion is the one transition a hypothesis cannot make on its own
    evidence: it depends on how many *other* hypotheses were tested. Allowing
    it through the general-purpose state mutator would route around the FDR,
    alpha, effect-size and check gates in a single call.
    """


class DuplicateCheckError(RegistryError):
    """Raised when a check result is recorded twice for one hypothesis.

    A check verdict is recorded once. Re-recording it would allow a FAIL to
    be re-rolled into a PASS, so a repeat is refused rather than treated as
    an idempotent overwrite -- the same convention this module already
    applies to the single-use TEST evaluation.
    """


class FamilyNotReadyError(RegistryError):
    """Raised when a family still has hypotheses awaiting a test result."""


class FamilyAlreadyAdjudicatedError(RegistryError):
    """Raised when a family has already been through FDR adjudication."""


class FamilyMembershipTamperedError(RegistryError):
    """Raised when a family's sealed manifest disagrees with its records.

    ``adjudicate_family`` treats ``self.family(family_id)`` as the complete
    set of tests, so anything that changes what that call returns without
    going through ``register`` -- most dangerously, deleting a losing
    hypothesis's record -- must be caught before it can shrink the family
    size BH corrects against.
    """


class StateChainError(RegistryError):
    """Raised when a hypothesis record's state hash chain is invalid.

    Covers a missing or empty chain, a recomputed fold hash that disagrees
    with the stored one, a discontinuity between consecutive links, a link
    that is not a legal lifecycle transition, and a final link whose
    ``to_state`` disagrees with the record's stored ``state``. That last
    case is the one this exists for: a hand-edited ``state`` field with no
    matching chain link must fail to load rather than load as promoted.
    """


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required(value: Any, field_name: str) -> None:
    if not str(value).strip():
        raise RegistryError(f"{field_name} is required")


def _parse_timestamp(value: str, field_name: str) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise RegistryError(
            f"{field_name} must be an ISO-8601 timestamp, got {value!r}"
        ) from exc


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _coerce_parameter(
    kind: str, check: "CheckName", name: str, value: Any
) -> Any:
    """Validate one check-plan parameter and return its canonical form.

    Coercion is not cosmetic. The plan is hashed into the seal via canonical
    JSON, where ``1`` and ``1.0`` serialise differently, so a parameter must
    land in one settled representation or an identical plan could seal two
    ways.
    """
    label = f"{check.value} check parameter {name}"

    if kind == "identifier":
        # Opaque and format-uncontrolled: preserved byte-exact, never
        # normalised, only required to be a non-empty string. Coercing with
        # str() would quietly seal 123 and "123" as the same plan, so a
        # non-string is refused instead.
        if not isinstance(value, str):
            raise RegistryError(f"{label} must be a string, got {value!r}")
        if not value.strip():
            raise RegistryError(f"{label} must not be empty")
        return value

    if kind == "positive_int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise RegistryError(f"{label} must be an int, got {value!r}")
        if value < 1:
            raise RegistryError(f"{label} must be >= 1, got {value}")
        return int(value)

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RegistryError(f"{label} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise RegistryError(f"{label} must be finite, got {value!r}")

    if kind == "non_negative_float":
        if number < 0.0:
            raise RegistryError(f"{label} must be >= 0, got {value}")
    elif kind == "unit_fraction":
        if not 0.0 < number <= 1.0:
            raise RegistryError(f"{label} must lie in (0.0, 1.0], got {value}")
    elif kind == "percentile":
        if not 0.0 < number < 100.0:
            raise RegistryError(
                f"{label} must lie in (0.0, 100.0), got {value}"
            )
    else:  # pragma: no cover - guards the schema table against a typo
        raise RegistryError(f"unknown parameter kind {kind!r} for {label}")
    return number


def _verify_threshold_binding(
    plan: "CheckPlan", check: "CheckResult", hypothesis_id: str
) -> None:
    """Raise unless a check was scored against the threshold its plan sealed.

    Applied on both the write path and the load path. Enforcing it in only
    one place would recreate the asymmetry that let an appended duplicate
    launder a verdict: an invariant that holds until the next restart is not
    an invariant.
    """
    sealed = plan.threshold_for(check.check_name)
    applied = check.threshold_applied

    if sealed is None:
        if applied is not None:
            raise ThresholdBindingError(
                f"{hypothesis_id}: the {check.check_name.value} check seals no "
                f"threshold, so its result must not declare one; got "
                f"threshold_applied={applied!r}"
            )
        return

    if applied is None:
        raise ThresholdBindingError(
            f"{hypothesis_id}: the {check.check_name.value} check must declare "
            f"the threshold it was scored against; its plan seals {sealed}"
        )
    if float(applied) != float(sealed):
        raise ThresholdBindingError(
            f"{hypothesis_id}: the {check.check_name.value} check was scored "
            f"against threshold {float(applied)}, but its sealed plan requires "
            f"{float(sealed)}; a verdict decided against a different number is "
            f"not the check that was pre-registered"
        )


@dataclass(frozen=True, slots=True)
class CheckPlan:
    """The sealed set of validation checks a hypothesis must clear.

    Sealed with the rest of the pre-registration, and for the same reason: a
    check plan chosen after results are visible is HARKing one level up. If
    MONTE_CARLO is added only once the cost-adjusted result disappoints, the
    plan records a protocol nobody committed to.

    The plan is also the denominator of every "how many checks passed"
    question (see ``required_check_count``). That is the NB-5 analogue: the
    count of checks that *should* exist, never the count that happen to be
    present.
    """

    required_checks: tuple[CheckName, ...]
    parameters: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        resolved: list[CheckName] = []
        for raw in self.required_checks:
            try:
                resolved.append(CheckName(raw))
            except ValueError as exc:
                raise RegistryError(
                    f"unknown check name {raw!r}; expected one of "
                    f"{[c.value for c in CHECK_ORDER]}"
                ) from exc

        if not resolved:
            raise RegistryError(
                "check_plan must require at least one check; an empty plan "
                "would make the check gate vacuously true"
            )
        if len(set(resolved)) != len(resolved):
            raise RegistryError(
                "check_plan must not require the same check twice"
            )

        required = frozenset(resolved)
        object.__setattr__(
            self,
            "required_checks",
            tuple(check for check in CHECK_ORDER if check in required),
        )

        supplied = dict(self.parameters)
        unrequired = sorted(set(supplied) - {c.value for c in required})
        if unrequired:
            raise RegistryError(
                f"check_plan carries parameters for checks it does not "
                f"require: {unrequired}"
            )

        normalised: dict[str, dict[str, Any]] = {}
        for check in self.required_checks:
            schema = _CHECK_PARAMETER_SCHEMA[check]
            given = dict(supplied.get(check.value, {}))
            missing = sorted(set(schema) - set(given))
            if missing:
                raise RegistryError(
                    f"{check.value} check_plan is missing parameters {missing}"
                )
            unknown = sorted(set(given) - set(schema))
            if unknown:
                raise RegistryError(
                    f"{check.value} check_plan carries unknown parameters "
                    f"{unknown}"
                )
            normalised[check.value] = {
                name: _coerce_parameter(kind, check, name, given[name])
                for name, kind in schema.items()
            }
        object.__setattr__(self, "parameters", normalised)

    @property
    def required_check_count(self) -> int:
        """The NB-5 denominator: how many checks the *plan* demands.

        Every pass ratio in the adjudication path divides by this, never by
        the number of recorded results. A plan requiring five checks with
        three recorded is three of five, never three of three.
        """
        return len(self.required_checks)

    def requires(self, check_name: "CheckName | str") -> bool:
        """Return True when ``check_name`` is part of this sealed plan."""
        try:
            resolved = CheckName(check_name)
        except ValueError:
            return False
        return resolved in self.required_checks

    def parameters_for(self, check_name: "CheckName | str") -> Mapping[str, Any]:
        """Return the sealed parameters for one required check."""
        resolved = CheckName(check_name)
        if resolved not in self.required_checks:
            raise RegistryError(
                f"{resolved.value} is not part of this check plan"
            )
        return dict(self.parameters[resolved.value])

    def threshold_for(self, check_name: "CheckName | str") -> float | None:
        """The sealed number this check's verdict must be decided against.

        ``None`` for a check that seals no comparison threshold. A compute
        engine reads its threshold from here rather than choosing one, and
        ``record_evaluation`` refuses any result scored against a different
        number -- which is what makes the sealed parameter binding rather
        than documentary.
        """
        resolved = CheckName(check_name)
        parameter = _CHECK_THRESHOLD_PARAMETER[resolved]
        if parameter is None:
            return None
        return float(self.parameters_for(resolved)[parameter])

    def as_dict(self) -> dict[str, Any]:
        return {
            "required_checks": [check.value for check in self.required_checks],
            "parameters": {
                name: dict(values) for name, values in self.parameters.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CheckPlan":
        try:
            return cls(
                required_checks=tuple(payload["required_checks"]),
                parameters=dict(payload.get("parameters", {})),
            )
        except KeyError as exc:
            raise RegistryError(f"check plan missing field {exc}") from exc


@dataclass(frozen=True, slots=True)
class PreRegistration:
    """The sealed, immutable specification of a hypothesis and its test."""

    hypothesis_id: str
    title: str
    description: str
    economic_rationale: str
    author: str
    universe: tuple[str, ...]
    timeframe: str
    data_start: str
    data_end: str
    entry_rule: str
    exit_rule: str
    test_statistic: str
    direction: str
    null_hypothesis: str
    alpha: float
    minimum_effect_size: float
    family_id: str
    split_spec: SplitSpec
    check_plan: CheckPlan
    feature_spec: Mapping[str, Any] = field(default_factory=dict)
    preregistered_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not _HYPOTHESIS_ID_PATTERN.match(str(self.hypothesis_id)):
            raise RegistryError(
                f"hypothesis_id must match HYP-NNNN, got {self.hypothesis_id!r}"
            )
        if not _FAMILY_ID_PATTERN.match(str(self.family_id)):
            raise RegistryError(
                f"family_id must match FAM-<A-Z0-9-> , got {self.family_id!r}"
            )

        for name in (
            "title",
            "description",
            "economic_rationale",
            "author",
            "timeframe",
            "entry_rule",
            "exit_rule",
            "test_statistic",
            "null_hypothesis",
        ):
            _required(getattr(self, name), name)

        universe = tuple(str(symbol) for symbol in self.universe)
        if not universe:
            raise RegistryError("universe must contain at least one symbol")
        for symbol in universe:
            if not _SYMBOL_PATTERN.match(symbol):
                raise RegistryError(f"invalid symbol in universe: {symbol!r}")
        if len(set(universe)) != len(universe):
            raise RegistryError("universe must not contain duplicate symbols")
        object.__setattr__(self, "universe", universe)

        if str(self.direction) not in DIRECTIONS:
            raise RegistryError(
                f"direction must be one of {sorted(DIRECTIONS)}, "
                f"got {self.direction!r}"
            )

        alpha = float(self.alpha)
        if not math.isfinite(alpha) or not 0.0 < alpha < 1.0:
            raise RegistryError(f"alpha must lie in (0.0, 1.0), got {self.alpha}")

        effect = float(self.minimum_effect_size)
        if not math.isfinite(effect) or effect < 0.0:
            raise RegistryError(
                f"minimum_effect_size must be >= 0, got {self.minimum_effect_size}"
            )

        start = _parse_timestamp(self.data_start, "data_start")
        end = _parse_timestamp(self.data_end, "data_end")
        if start >= end:
            raise RegistryError("data_start must be strictly before data_end")
        _parse_timestamp(self.preregistered_at, "preregistered_at")

        if not isinstance(self.split_spec, SplitSpec):
            raise RegistryError("split_spec must be a SplitSpec")

        if not isinstance(self.check_plan, CheckPlan):
            raise RegistryError("check_plan must be a CheckPlan")

        try:
            _canonical_json(dict(self.feature_spec))
        except (TypeError, ValueError) as exc:
            raise RegistryError("feature_spec must be JSON-serialisable") from exc

    def sealed_payload(self) -> dict[str, Any]:
        """The canonical dict that the pre-registration hash is computed over."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "title": self.title,
            "description": self.description,
            "economic_rationale": self.economic_rationale,
            "author": self.author,
            "universe": list(self.universe),
            "timeframe": self.timeframe,
            "data_start": self.data_start,
            "data_end": self.data_end,
            "entry_rule": self.entry_rule,
            "exit_rule": self.exit_rule,
            "test_statistic": self.test_statistic,
            "direction": self.direction,
            "null_hypothesis": self.null_hypothesis,
            "alpha": float(self.alpha),
            "minimum_effect_size": float(self.minimum_effect_size),
            "family_id": self.family_id,
            "split_spec": self.split_spec.as_dict(),
            "check_plan": self.check_plan.as_dict(),
            "feature_spec": dict(self.feature_spec),
            "preregistered_at": self.preregistered_at,
        }

    def seal_hash(self) -> str:
        """SHA-256 over the canonical serialisation of the sealed fields."""
        canonical = _canonical_json(self.sealed_payload())
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PreRegistration":
        try:
            return cls(
                hypothesis_id=payload["hypothesis_id"],
                title=payload["title"],
                description=payload["description"],
                economic_rationale=payload["economic_rationale"],
                author=payload["author"],
                universe=tuple(payload["universe"]),
                timeframe=payload["timeframe"],
                data_start=payload["data_start"],
                data_end=payload["data_end"],
                entry_rule=payload["entry_rule"],
                exit_rule=payload["exit_rule"],
                test_statistic=payload["test_statistic"],
                direction=payload["direction"],
                null_hypothesis=payload["null_hypothesis"],
                alpha=float(payload["alpha"]),
                minimum_effect_size=float(payload["minimum_effect_size"]),
                family_id=payload["family_id"],
                split_spec=SplitSpec.from_dict(payload["split_spec"]),
                # Required, with no default: a stored pre-registration that
                # carries no check plan is a version-1 payload or a hand-edit,
                # and either way loading must fail rather than substitute an
                # empty plan that would pass the check gate vacuously.
                check_plan=CheckPlan.from_dict(payload["check_plan"]),
                feature_spec=dict(payload.get("feature_spec", {})),
                preregistered_at=payload["preregistered_at"],
            )
        except KeyError as exc:
            raise RegistryError(f"pre-registration missing field {exc}") from exc


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One named validation check's outcome, as plain data.

    This module adjudicates check results; it does not compute them. The
    statistic, the p-value and the verdict are produced elsewhere and handed
    in. ``threshold_applied`` records the number the verdict was decided
    against, so a stored result can be re-read later without consulting the
    engine that produced it, and ``payload`` carries whatever per-check
    detail that engine wants to keep (per-window outcomes, trial summaries).
    """

    check_name: CheckName
    verdict: CheckVerdict
    statistic_value: float
    p_value: float | None = None
    effect_size: float | None = None
    threshold_applied: float | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    recorded_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "check_name", CheckName(self.check_name))
        except ValueError as exc:
            raise RegistryError(
                f"check_name must be one of {[c.value for c in CHECK_ORDER]}, "
                f"got {self.check_name!r}"
            ) from exc

        try:
            object.__setattr__(self, "verdict", CheckVerdict(self.verdict))
        except ValueError as exc:
            raise RegistryError(
                f"verdict must be one of "
                f"{[v.value for v in CheckVerdict]}, got {self.verdict!r}"
            ) from exc

        if not math.isfinite(float(self.statistic_value)):
            raise RegistryError("statistic_value must be finite")

        if self.p_value is not None:
            p_value = float(self.p_value)
            if not math.isfinite(p_value) or not 0.0 <= p_value <= 1.0:
                raise RegistryError(
                    f"p_value must lie in [0.0, 1.0], got {self.p_value}"
                )
        if self.effect_size is not None and not math.isfinite(
            float(self.effect_size)
        ):
            raise RegistryError("effect_size must be finite")
        if self.threshold_applied is not None and not math.isfinite(
            float(self.threshold_applied)
        ):
            raise RegistryError("threshold_applied must be finite")

        try:
            _canonical_json(dict(self.payload))
        except (TypeError, ValueError) as exc:
            raise RegistryError("payload must be JSON-serialisable") from exc

        _parse_timestamp(self.recorded_at, "recorded_at")

    @property
    def segment(self) -> str:
        """The data segment this check is scored against."""
        return CHECK_SEGMENTS[self.check_name]

    @property
    def passed(self) -> bool:
        return self.verdict is CheckVerdict.PASS

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_name": self.check_name.value,
            "verdict": self.verdict.value,
            "statistic_value": float(self.statistic_value),
            "p_value": None if self.p_value is None else float(self.p_value),
            "effect_size": (
                None if self.effect_size is None else float(self.effect_size)
            ),
            "threshold_applied": (
                None
                if self.threshold_applied is None
                else float(self.threshold_applied)
            ),
            "payload": dict(self.payload),
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CheckResult":
        try:
            return cls(
                check_name=payload["check_name"],
                verdict=payload["verdict"],
                statistic_value=float(payload["statistic_value"]),
                p_value=(
                    None if payload.get("p_value") is None
                    else float(payload["p_value"])
                ),
                effect_size=(
                    None if payload.get("effect_size") is None
                    else float(payload["effect_size"])
                ),
                threshold_applied=(
                    None if payload.get("threshold_applied") is None
                    else float(payload["threshold_applied"])
                ),
                payload=dict(payload.get("payload", {})),
                recorded_at=payload["recorded_at"],
            )
        except KeyError as exc:
            raise RegistryError(f"check result missing field {exc}") from exc
        except (TypeError, ValueError) as exc:
            # A malformed stored value must surface as the documented error
            # family, so a caller guarding the load with ``except
            # RegistryError`` cannot be bypassed by a bad payload type.
            raise RegistryError(f"malformed check result: {exc}") from exc


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    """One append-only evaluation result against a named data segment.

    ``checks`` carries the validation-check results scored against this same
    segment read. The three TEST-segment checks ride on one evaluation
    precisely so that recording them cannot become a second test read.
    """

    segment: str
    statistic_value: float
    p_value: float | None = None
    effect_size: float | None = None
    notes: str = ""
    recorded_at: str = field(default_factory=_now)
    checks: tuple[CheckResult, ...] = ()

    def __post_init__(self) -> None:
        if str(self.segment) not in SEGMENTS:
            raise RegistryError(
                f"segment must be one of {sorted(SEGMENTS)}, got {self.segment!r}"
            )
        if not math.isfinite(float(self.statistic_value)):
            raise RegistryError("statistic_value must be finite")

        if self.p_value is not None:
            p_value = float(self.p_value)
            if not math.isfinite(p_value) or not 0.0 <= p_value <= 1.0:
                raise RegistryError(
                    f"p_value must lie in [0.0, 1.0], got {self.p_value}"
                )
        if self.effect_size is not None and not math.isfinite(
            float(self.effect_size)
        ):
            raise RegistryError("effect_size must be finite")

        # A test evaluation is the single irreversible read of the test
        # segment, so it must carry everything adjudication needs.
        if str(self.segment) == "TEST":
            if self.p_value is None:
                raise RegistryError("a TEST evaluation must carry a p_value")
            if self.effect_size is None:
                raise RegistryError("a TEST evaluation must carry an effect_size")

        _parse_timestamp(self.recorded_at, "recorded_at")

        checks = tuple(self.checks)
        for check in checks:
            if not isinstance(check, CheckResult):
                raise RegistryError("checks must contain CheckResult objects")
            if check.segment != str(self.segment):
                raise RegistryError(
                    f"{check.check_name.value} is scored against the "
                    f"{check.segment} segment and cannot be attached to a "
                    f"{self.segment} evaluation"
                )
        names = [check.check_name for check in checks]
        if len(set(names)) != len(names):
            raise DuplicateCheckError(
                "one evaluation must not carry the same check twice"
            )
        object.__setattr__(self, "checks", checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "segment": self.segment,
            "statistic_value": float(self.statistic_value),
            "p_value": None if self.p_value is None else float(self.p_value),
            "effect_size": (
                None if self.effect_size is None else float(self.effect_size)
            ),
            "notes": self.notes,
            "recorded_at": self.recorded_at,
            "checks": [check.as_dict() for check in self.checks],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvaluationRecord":
        try:
            return cls(
                segment=payload["segment"],
                statistic_value=float(payload["statistic_value"]),
                p_value=(
                    None if payload.get("p_value") is None
                    else float(payload["p_value"])
                ),
                effect_size=(
                    None if payload.get("effect_size") is None
                    else float(payload["effect_size"])
                ),
                notes=payload.get("notes", ""),
                recorded_at=payload["recorded_at"],
                # Absent checks load as none recorded. Evaluations are not
                # covered by the seal, so this is deliberately the direction
                # that is safe to get wrong: a deleted check result becomes a
                # missing required check, which adjudicates as FAIL.
                checks=tuple(
                    CheckResult.from_dict(check)
                    for check in payload.get("checks", ())
                ),
            )
        except KeyError as exc:
            raise RegistryError(f"evaluation missing field {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise RegistryError(f"malformed evaluation: {exc}") from exc


@dataclass(frozen=True, slots=True)
class CheckAdjudication:
    """How one hypothesis's recorded checks score against its sealed plan.

    ``required_check_count`` comes from the plan and is the only denominator
    any caller should use. It is reported alongside the counts precisely so
    that no consumer has to reconstruct it from the results it can see.
    """

    required_check_count: int
    passed_check_count: int
    recorded_check_count: int
    missing_checks: tuple[CheckName, ...]
    failed_checks: tuple[CheckName, ...]
    status: CheckPlanStatus

    @property
    def all_required_checks_passed(self) -> bool:
        """True only when every check the plan requires recorded a PASS.

        Stated three independent ways -- the count matches the plan's count,
        nothing is missing, nothing failed -- so that no single arithmetic
        slip can turn an incomplete or failing plan into a promotion.
        """
        return (
            self.passed_check_count == self.required_check_count
            and not self.missing_checks
            and not self.failed_checks
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "required_check_count": self.required_check_count,
            "passed_check_count": self.passed_check_count,
            "recorded_check_count": self.recorded_check_count,
            "missing_checks": [check.value for check in self.missing_checks],
            "failed_checks": [check.value for check in self.failed_checks],
            "status": self.status.value,
            "all_required_checks_passed": self.all_required_checks_passed,
        }


@dataclass(frozen=True, slots=True)
class StateTransition:
    """One link in a hypothesis's state hash chain.

    ``from_state`` is ``None`` only for the genesis link, which records
    ``register()`` creating the hypothesis directly into REGISTERED -- the
    one state a hypothesis enters without a lifecycle transition. Every
    later link's ``from_state`` must equal the previous link's ``to_state``;
    that continuity, not just this dataclass's own field validation, is
    checked by ``HypothesisRecord.verify_state_chain``.
    """

    from_state: HypothesisState | None
    to_state: HypothesisState
    recorded_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.from_state is not None:
            object.__setattr__(self, "from_state", HypothesisState(self.from_state))
        object.__setattr__(self, "to_state", HypothesisState(self.to_state))
        _parse_timestamp(self.recorded_at, "recorded_at")

    def as_dict(self) -> dict[str, Any]:
        return {
            "from_state": None if self.from_state is None else self.from_state.value,
            "to_state": self.to_state.value,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StateTransition":
        try:
            return cls(
                from_state=payload["from_state"],
                to_state=payload["to_state"],
                recorded_at=payload["recorded_at"],
            )
        except KeyError as exc:
            raise RegistryError(f"state transition missing field {exc}") from exc
        except ValueError as exc:
            raise RegistryError(f"malformed state transition: {exc}") from exc


def _fold_state_chain(
    hypothesis_id: str, transitions: Sequence["StateTransition"]
) -> str:
    """Fold an ordered sequence of state transitions into one chained hash.

    Each step hashes the running hash together with the next transition's
    canonical content, so the result commits to the entire ordered history
    from GENESIS through the final link -- not to the final state in
    isolation. Splicing, reordering, or truncating any link changes every
    hash folded after it, including the one this function returns, which is
    what makes the chain a chain rather than one hash per link.
    """
    running = "GENESIS"
    for index, transition in enumerate(transitions):
        payload = {
            "hypothesis_id": hypothesis_id,
            "index": index,
            "previous_hash": running,
            **transition.as_dict(),
        }
        running = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return running


@dataclass(frozen=True, slots=True)
class FamilyManifest:
    """Sealed, append-only record of which hypothesis ids belong to a family.

    Established when a family's first hypothesis registers and extended by
    exactly one id, in registration order, each time another hypothesis
    joins it. ``HypothesisRegistry._load`` cross-checks every manifest
    against the hypothesis records actually present: without this, deleting
    a losing hypothesis's record from ``records`` would silently shrink what
    ``family()`` (and therefore ``adjudicate_family``) sees as the
    multiple-testing family, inflating the survivors' apparent significance
    -- exactly the selection bias Benjamini-Hochberg exists to control.
    """

    family_id: str
    member_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _FAMILY_ID_PATTERN.match(str(self.family_id)):
            raise RegistryError(
                f"family_id must match FAM-<A-Z0-9-> , got {self.family_id!r}"
            )
        member_ids = tuple(str(member_id) for member_id in self.member_ids)
        if not member_ids:
            raise RegistryError(
                f"family {self.family_id} manifest must record at least one member"
            )
        for member_id in member_ids:
            if not _HYPOTHESIS_ID_PATTERN.match(member_id):
                raise RegistryError(
                    f"family manifest member id must match HYP-NNNN, got "
                    f"{member_id!r}"
                )
        if len(set(member_ids)) != len(member_ids):
            raise RegistryError(
                f"family {self.family_id} manifest lists a member id more than once"
            )
        object.__setattr__(self, "member_ids", member_ids)

    def sealed_payload(self) -> dict[str, Any]:
        return {"family_id": self.family_id, "member_ids": list(self.member_ids)}

    def seal_hash(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.sealed_payload()).encode("utf-8")
        ).hexdigest()

    def extended(self, hypothesis_id: str) -> "FamilyManifest":
        """Return a new manifest with ``hypothesis_id`` appended.

        Registration order, never any other order: this is what lets the
        manifest's own seal detect a later reordering of ``member_ids``.
        """
        if hypothesis_id in self.member_ids:
            raise RegistryError(
                f"{hypothesis_id} is already a member of family {self.family_id}"
            )
        return FamilyManifest(
            family_id=self.family_id, member_ids=self.member_ids + (str(hypothesis_id),)
        )

    def as_dict(self) -> dict[str, Any]:
        return {**self.sealed_payload(), "manifest_hash": self.seal_hash()}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FamilyManifest":
        try:
            manifest = cls(
                family_id=payload["family_id"],
                member_ids=tuple(payload["member_ids"]),
            )
        except KeyError as exc:
            raise RegistryError(f"family manifest missing field {exc}") from exc

        stored_hash = str(payload.get("manifest_hash", ""))
        recomputed_hash = manifest.seal_hash()
        if stored_hash != recomputed_hash:
            raise SealVerificationError(
                f"family manifest seal mismatch for {manifest.family_id}: "
                f"stored {stored_hash}, recomputed {recomputed_hash}"
            )
        return manifest


@dataclass(frozen=True, slots=True)
class HypothesisRecord:
    """A sealed pre-registration plus its mutable lifecycle state."""

    preregistration: PreRegistration
    preregistration_hash: str
    state: HypothesisState
    evaluations: tuple[EvaluationRecord, ...] = ()
    state_chain: tuple[StateTransition, ...] = ()
    state_chain_hash: str = ""

    @classmethod
    def initial(
        cls, *, preregistration: PreRegistration, preregistration_hash: str
    ) -> "HypothesisRecord":
        """Build the record ``register()`` creates: REGISTERED, with a
        one-link state chain sealing that creation as its genesis event."""
        genesis = (
            StateTransition(from_state=None, to_state=HypothesisState.REGISTERED),
        )
        return cls(
            preregistration=preregistration,
            preregistration_hash=preregistration_hash,
            state=HypothesisState.REGISTERED,
            evaluations=(),
            state_chain=genesis,
            state_chain_hash=_fold_state_chain(
                preregistration.hypothesis_id, genesis
            ),
        )

    def transitioned_to(self, target_state: HypothesisState) -> "HypothesisRecord":
        """Return a copy advanced to ``target_state`` with the state chain
        extended and resealed to cover the new link.

        This method only records a transition; it does not gate one. Every
        caller (``advance``, ``record_evaluation``, ``adjudicate_family``)
        validates the transition against ``research.lifecycle`` first, the
        same as before this method existed -- this only adds the chain
        bookkeeping around that already-validated state change.
        """
        target_state = HypothesisState(target_state)
        chain = self.state_chain + (
            StateTransition(from_state=self.state, to_state=target_state),
        )
        return replace(
            self,
            state=target_state,
            state_chain=chain,
            state_chain_hash=_fold_state_chain(self.hypothesis_id, chain),
        )

    @property
    def hypothesis_id(self) -> str:
        return self.preregistration.hypothesis_id

    @property
    def family_id(self) -> str:
        return self.preregistration.family_id

    @property
    def test_evaluation(self) -> EvaluationRecord | None:
        """The single test-segment evaluation, if it has been consumed."""
        for evaluation in self.evaluations:
            if evaluation.segment == "TEST":
                return evaluation
        return None

    @property
    def check_plan(self) -> CheckPlan:
        return self.preregistration.check_plan

    def check_results(self) -> tuple[CheckResult, ...]:
        """Every recorded check result, across all evaluation segments.

        Checks are spread over three segments -- BACKTEST on TRAIN,
        WALK_FORWARD on CALIBRATION, the other three on the single TEST read
        -- so adjudication reads all evaluations, not only the test one.
        """
        return tuple(
            check
            for evaluation in self.evaluations
            for check in evaluation.checks
        )

    def adjudicate_checks(self) -> CheckAdjudication:
        """Score the recorded checks against the sealed plan.

        Two regression guards are load-bearing here.

        **NB-4 analogue.** A required check with no recorded result is a
        FAIL, never a skip. The loop below iterates the plan and looks each
        required check up among the results; a check that is not there
        cannot be silently passed over. Consequently removing a recorded
        result can only move a check from passed to missing, which is to say
        removing evidence can only make the verdict less permissive -- the
        exact property NB-4 exists to protect.

        **NB-5 analogue.** The denominator is the plan's required-check
        count, held in a named variable below, never ``len(recorded)``. Were
        it the latter, a hypothesis with two of five checks recorded and
        both passing would read as full consensus, which is the same false
        unanimity NB-5 describes for a short agent roster.
        """
        plan = self.check_plan

        # The NB-5 denominator. Taken from the sealed plan, so it cannot
        # shrink to match whatever results happen to have been recorded.
        required_check_count = plan.required_check_count

        recorded: dict[CheckName, CheckResult] = {}
        for check in self.check_results():
            existing = recorded.get(check.check_name)
            # Conservative fold. Two results for one check should be
            # unreachable -- the write path and the load path both refuse a
            # duplicate -- but if one ever exists, the failing verdict wins.
            # Last-wins would resolve in the permissive direction, and
            # "append a passing copy after a failing one" is precisely the
            # shape a post-hoc edit takes.
            if existing is None or (existing.passed and not check.passed):
                recorded[check.check_name] = check

        passed: list[CheckName] = []
        failed: list[CheckName] = []
        missing: list[CheckName] = []
        # Iterate the *plan*, not the results. This is what makes an absent
        # required check visible at all.
        for check_name in plan.required_checks:
            result = recorded.get(check_name)
            if result is None:
                missing.append(check_name)
            elif result.passed:
                passed.append(check_name)
            else:
                failed.append(check_name)

        if missing:
            status = CheckPlanStatus.INCOMPLETE
        elif failed:
            status = CheckPlanStatus.COMPLETE_FAIL
        else:
            status = CheckPlanStatus.COMPLETE_PASS

        return CheckAdjudication(
            required_check_count=required_check_count,
            passed_check_count=len(passed),
            recorded_check_count=len(recorded),
            missing_checks=tuple(missing),
            failed_checks=tuple(failed),
            status=status,
        )

    def verify_recorded_checks(self) -> None:
        """Re-apply the write path's check invariants to loaded evaluations.

        Evaluations are deliberately outside the seal, so a hand-edited file
        can carry checks ``record_evaluation`` would have refused: one that
        the sealed plan never required, or a second verdict for a check
        already answered. Appending a passing copy after a failing result is
        the cheapest way to re-roll a verdict, and it leaves the
        pre-registration hash untouched, so the seal cannot catch it.

        The load path therefore refuses exactly what the write path refuses.
        This does not make evaluations tamper-evident -- an in-place edit of
        a single verdict remains undetectable, and closing that needs a
        chained hash over the append-only log, recorded as future work.
        """
        plan = self.check_plan
        seen: set[CheckName] = set()
        for check in self.check_results():
            if not plan.requires(check.check_name):
                raise UnplannedCheckError(
                    f"{self.hypothesis_id} carries a stored "
                    f"{check.check_name.value} result that its sealed plan "
                    f"never required"
                )
            if check.check_name in seen:
                raise DuplicateCheckError(
                    f"{self.hypothesis_id} carries more than one stored "
                    f"{check.check_name.value} result; a check verdict is "
                    f"recorded once and is never re-rolled"
                )
            seen.add(check.check_name)
            _verify_threshold_binding(plan, check, self.hypothesis_id)

    def verify_seal(self) -> None:
        """Raise SealVerificationError if the sealed content has been edited."""
        recomputed = self.preregistration.seal_hash()
        if recomputed != self.preregistration_hash:
            raise SealVerificationError(
                f"pre-registration seal mismatch for {self.hypothesis_id}: "
                f"stored {self.preregistration_hash}, recomputed {recomputed}"
            )

    def verify_state_chain(self) -> None:
        """Raise StateChainError if the state chain is invalid or disagrees
        with the stored ``state``.

        Checked, in order: the chain is non-empty; the recomputed fold hash
        matches ``state_chain_hash``; the first link starts at genesis
        (``from_state is None``) and lands on REGISTERED, the only state a
        hypothesis enters without a transition; each later link continues
        from where the previous one ended; each link beyond genesis is a
        legal ``research.lifecycle`` transition; and the final link's
        ``to_state`` equals the record's stored ``state``. That last check is
        the one that catches a hand-edited ``state`` with no matching chain
        link -- the exact gap this hardening item exists to close.
        """
        chain = self.state_chain
        if not chain:
            raise StateChainError(f"{self.hypothesis_id} has an empty state chain")

        recomputed = _fold_state_chain(self.hypothesis_id, chain)
        if recomputed != self.state_chain_hash:
            raise StateChainError(
                f"{self.hypothesis_id}: state chain hash mismatch (stored "
                f"{self.state_chain_hash}, recomputed {recomputed})"
            )

        genesis = chain[0]
        if genesis.from_state is not None:
            raise StateChainError(
                f"{self.hypothesis_id}: state chain does not start at genesis "
                f"(first link has from_state={genesis.from_state.value})"
            )
        if genesis.to_state is not HypothesisState.REGISTERED:
            raise StateChainError(
                f"{self.hypothesis_id}: state chain genesis link must "
                f"transition to REGISTERED, got {genesis.to_state.value}"
            )

        for index in range(1, len(chain)):
            previous, current = chain[index - 1], chain[index]
            if current.from_state != previous.to_state:
                raise StateChainError(
                    f"{self.hypothesis_id}: state chain link {index} starts "
                    f"at {current.from_state}, but link {index - 1} ended at "
                    f"{previous.to_state.value}"
                )
            try:
                validate_transition(previous.to_state, current.to_state)
            except IllegalTransitionError as exc:
                raise StateChainError(
                    f"{self.hypothesis_id}: state chain link {index} is "
                    f"illegal: {exc}"
                ) from exc

        if chain[-1].to_state != self.state:
            raise StateChainError(
                f"{self.hypothesis_id}: stored state is {self.state.value}, "
                f"but the state chain's last link ends at "
                f"{chain[-1].to_state.value}"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "preregistration": self.preregistration.sealed_payload(),
            "preregistration_hash": self.preregistration_hash,
            "state": self.state.value,
            "evaluations": [e.as_dict() for e in self.evaluations],
            "state_chain": [t.as_dict() for t in self.state_chain],
            "state_chain_hash": self.state_chain_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HypothesisRecord":
        try:
            record = cls(
                preregistration=PreRegistration.from_dict(
                    payload["preregistration"]
                ),
                preregistration_hash=str(payload["preregistration_hash"]),
                state=HypothesisState(payload["state"]),
                evaluations=tuple(
                    EvaluationRecord.from_dict(e)
                    for e in payload.get("evaluations", ())
                ),
                # Required, with no default: a stored record with no state
                # chain is a pre-version-3 payload or a hand-edit, and either
                # way loading must fail rather than substitute an empty chain
                # that would trivially "match" any state.
                state_chain=tuple(
                    StateTransition.from_dict(t) for t in payload["state_chain"]
                ),
                state_chain_hash=str(payload["state_chain_hash"]),
            )
        except KeyError as exc:
            raise RegistryError(f"hypothesis record missing field {exc}") from exc
        record.verify_seal()
        record.verify_recorded_checks()
        record.verify_state_chain()
        return record


class HypothesisRegistry:
    """JSON-backed, append-only registry of pre-registered hypotheses.

    ``registry_path`` is required. There is no default and no fallback to the
    process working directory.
    """

    def __init__(self, *, registry_path: Path | str) -> None:
        if not str(registry_path).strip():
            raise RegistryError("registry_path is required")
        self.registry_path = Path(registry_path)
        self._records: dict[str, HypothesisRecord] = {}
        self._family_manifests: dict[str, FamilyManifest] = {}
        self._load()

    # -- persistence -----------------------------------------------------

    def _load(self) -> None:
        if not self.registry_path.exists():
            return
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryError(
                f"cannot read hypothesis registry at {self.registry_path}: {exc}"
            ) from exc

        # A truncated or otherwise corrupted file can still be valid JSON --
        # for example the top-level object with everything after "version"
        # cut off. Without this, such a file loads as a silently empty
        # registry rather than failing closed.
        if not isinstance(payload, dict):
            raise RegistryError(
                f"hypothesis registry at {self.registry_path} is not a JSON "
                f"object; the file may be truncated or corrupted"
            )

        version = payload.get("version")
        if version != REGISTRY_FORMAT_VERSION:
            raise RegistryError(
                f"unsupported registry format version {version!r}; "
                f"expected {REGISTRY_FORMAT_VERSION}"
            )

        if "records" not in payload:
            raise RegistryError(
                f"hypothesis registry at {self.registry_path} has no "
                f"'records' key; the file may be truncated, refusing to "
                f"load it as an empty registry"
            )
        records_payload = payload["records"]
        if not isinstance(records_payload, list):
            raise RegistryError(
                f"hypothesis registry at {self.registry_path} has a "
                f"non-list 'records' field; the file may be corrupted"
            )

        if "family_manifests" not in payload:
            raise RegistryError(
                f"hypothesis registry at {self.registry_path} has no "
                f"'family_manifests' key; the file may be truncated, "
                f"refusing to load it as a registry with no family history"
            )
        manifests_payload = payload["family_manifests"]
        if not isinstance(manifests_payload, list):
            raise RegistryError(
                f"hypothesis registry at {self.registry_path} has a "
                f"non-list 'family_manifests' field; the file may be "
                f"corrupted"
            )

        for entry in records_payload:
            # from_dict verifies the seal, checks and state chain, so a
            # hand-edited file fails here.
            record = HypothesisRecord.from_dict(entry)
            self._records[record.hypothesis_id] = record

        for entry in manifests_payload:
            # from_dict verifies the manifest's own seal.
            manifest = FamilyManifest.from_dict(entry)
            if manifest.family_id in self._family_manifests:
                raise FamilyMembershipTamperedError(
                    f"family {manifest.family_id} has more than one stored "
                    f"manifest"
                )
            self._family_manifests[manifest.family_id] = manifest

        # Cross-check: what the manifests claim must equal what the records
        # actually contain, in both directions. This is what stops a deleted
        # (or added, or moved) record from silently changing a family's
        # membership without the deletion itself being detectable.
        actual_members: dict[str, set[str]] = {}
        for record in self._records.values():
            actual_members.setdefault(record.family_id, set()).add(
                record.hypothesis_id
            )

        for family_id, member_ids in actual_members.items():
            manifest = self._family_manifests.get(family_id)
            if manifest is None:
                raise FamilyMembershipTamperedError(
                    f"family {family_id} has {len(member_ids)} recorded "
                    f"hypothesis(es) but no sealed family manifest; the "
                    f"registry may be truncated or hand-edited"
                )
            if set(manifest.member_ids) != member_ids:
                raise FamilyMembershipTamperedError(
                    f"family {family_id} manifest does not match its "
                    f"recorded hypotheses (manifest="
                    f"{sorted(manifest.member_ids)}, actual="
                    f"{sorted(member_ids)}); a member may have been added or "
                    f"deleted outside register()"
                )

        for family_id in self._family_manifests:
            if family_id not in actual_members:
                raise FamilyMembershipTamperedError(
                    f"family {family_id} has a sealed manifest but no "
                    f"recorded hypotheses; the registry may be corrupted"
                )

    def _save(self) -> None:
        payload = {
            "version": REGISTRY_FORMAT_VERSION,
            "records": [
                self._records[key].as_dict() for key in sorted(self._records)
            ],
            "family_manifests": [
                self._family_manifests[key].as_dict()
                for key in sorted(self._family_manifests)
            ],
        }
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.registry_path.parent,
            prefix=self.registry_path.name,
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, self.registry_path)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise

    # -- reads -----------------------------------------------------------

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, hypothesis_id: object) -> bool:
        return str(hypothesis_id) in self._records

    def get(self, hypothesis_id: str) -> HypothesisRecord:
        """Return one record, raising UnknownHypothesisError if absent."""
        try:
            return self._records[str(hypothesis_id)]
        except KeyError as exc:
            raise UnknownHypothesisError(
                f"no hypothesis registered as {hypothesis_id!r}"
            ) from exc

    def all_records(self) -> tuple[HypothesisRecord, ...]:
        """Every record, ordered by hypothesis id."""
        return tuple(self._records[key] for key in sorted(self._records))

    def family(self, family_id: str) -> tuple[HypothesisRecord, ...]:
        """Every record in one multiple-testing family, ordered by id.

        This includes failures and abandoned hypotheses. BH controls FDR only
        over a complete family, so this must never be filtered to survivors.
        """
        return tuple(
            record
            for record in self.all_records()
            if record.family_id == str(family_id)
        )

    def family_manifest(self, family_id: str) -> FamilyManifest | None:
        """The sealed membership manifest for one family, or ``None`` if the
        family has never had a hypothesis registered into it."""
        return self._family_manifests.get(str(family_id))

    # -- writes ----------------------------------------------------------

    def register(self, preregistration: PreRegistration) -> HypothesisRecord:
        """Seal a pre-registration and store it in the REGISTERED state."""
        hypothesis_id = preregistration.hypothesis_id
        if hypothesis_id in self._records:
            raise DuplicateHypothesisError(
                f"{hypothesis_id} is already registered; a changed hypothesis "
                f"needs a new id, not an amendment"
            )
        record = HypothesisRecord.initial(
            preregistration=preregistration,
            preregistration_hash=preregistration.seal_hash(),
        )
        family_id = preregistration.family_id
        existing_manifest = self._family_manifests.get(family_id)
        manifest = (
            FamilyManifest(family_id=family_id, member_ids=(hypothesis_id,))
            if existing_manifest is None
            else existing_manifest.extended(hypothesis_id)
        )

        self._records[hypothesis_id] = record
        self._family_manifests[family_id] = manifest
        self._save()
        return record

    def advance(
        self, hypothesis_id: str, target_state: HypothesisState
    ) -> HypothesisRecord:
        """Move a hypothesis to ``target_state`` if the transition is legal.

        Promotion is excluded. ``lifecycle`` declares
        ``FAMILY_ADJUDICATED_TRANSITION`` as the one transition that cannot be
        made on a hypothesis's own evidence, and this is where that
        declaration is enforced: ``TESTED -> CANDIDATE`` is legal for the
        state machine but reachable only through ``adjudicate_family``, which
        applies the FDR, alpha, effect-size and check gates together. Without
        this refusal the entire conjunctive gate is one call away from being
        routed around, and the gate would only be as strong as the discipline
        of whoever calls this method.

        No mechanism beyond the refusal is needed: ``adjudicate_family``
        validates and writes its own transitions directly and never calls
        this method, so nothing legitimate passes through here.
        """
        record = self.get(hypothesis_id)
        target_state = HypothesisState(target_state)

        if (record.state, target_state) == FAMILY_ADJUDICATED_TRANSITION:
            raise FamilyAdjudicationRequiredError(
                f"{record.hypothesis_id} cannot be advanced from "
                f"{record.state.value} to {target_state.value} directly; "
                f"promotion depends on how many other hypotheses were tested "
                f"in family {record.family_id}, so it is made only by "
                f"adjudicate_family"
            )

        validate_transition(record.state, target_state)
        updated = record.transitioned_to(target_state)
        self._records[record.hypothesis_id] = updated
        self._save()
        return updated

    def record_evaluation(
        self, hypothesis_id: str, evaluation: EvaluationRecord
    ) -> HypothesisRecord:
        """Append an evaluation, enforcing per-segment access rules.

        A TEST evaluation is permitted only from CALIBRATED and advances the
        hypothesis to TESTED, which monotonicity then makes irreversible.
        """
        record = self.get(hypothesis_id)
        segment = evaluation.segment
        permitted = _SEGMENT_ALLOWED_STATES[segment]

        if record.state not in permitted:
            raise EvaluationNotPermittedError(
                f"{record.hypothesis_id} is in state {record.state.value}; "
                f"{segment} evaluations are permitted only from "
                f"{sorted(s.value for s in permitted)}"
            )

        if segment == "TEST":
            if not can_evaluate_test(record.state):
                raise EvaluationNotPermittedError(
                    f"{record.hypothesis_id} may not read the test segment from "
                    f"state {record.state.value}"
                )
            if record.test_evaluation is not None:
                raise EvaluationNotPermittedError(
                    f"{record.hypothesis_id} has already consumed its single "
                    f"test evaluation"
                )

        # Checks are admitted only against the sealed plan, and only once.
        # Both refusals are the anti-HARKing property at write time: a check
        # cannot be introduced after results are visible, and a recorded
        # verdict cannot be re-rolled.
        plan = record.check_plan
        already_recorded = {check.check_name for check in record.check_results()}
        for check in evaluation.checks:
            if not plan.requires(check.check_name):
                raise UnplannedCheckError(
                    f"{record.hypothesis_id} did not pre-register the "
                    f"{check.check_name.value} check; its sealed plan requires "
                    f"{[c.value for c in plan.required_checks]}"
                )
            if check.check_name in already_recorded:
                raise DuplicateCheckError(
                    f"{record.hypothesis_id} has already recorded a "
                    f"{check.check_name.value} result; a check verdict is "
                    f"recorded once and is never re-rolled"
                )
            _verify_threshold_binding(plan, check, record.hypothesis_id)

        updated = replace(record, evaluations=record.evaluations + (evaluation,))
        if segment == "TEST":
            validate_transition(updated.state, HypothesisState.TESTED)
            updated = updated.transitioned_to(HypothesisState.TESTED)

        self._records[record.hypothesis_id] = updated
        self._save()
        return updated

    # -- family adjudication ---------------------------------------------

    def adjudicate_family(self, family_id: str, *, q: float) -> FDRDecision:
        """Run Benjamini-Hochberg over a family and promote or reject it.

        ``TESTED -> CANDIDATE`` is the one transition a hypothesis cannot make
        on its own evidence: whether a result survives correction depends on
        how many *other* hypotheses were tested. The family is therefore
        adjudicated once, atomically, and only when every member has reached a
        terminal-or-tested state.

        A hypothesis is promoted only if it clears all four gates: the
        family-level FDR decision, its own pre-registered ``alpha``, its
        pre-registered ``minimum_effect_size``, and every check its sealed
        plan requires. The four are combined with a hard AND. There is no
        weighted score, because a weighted score lets a strong p-value buy
        its way past a failed cost-adjusted check, and those two quantities
        are not exchangeable.

        **Ordering matters and is not negotiable.** Benjamini-Hochberg runs
        first, over the p-values of every tested hypothesis in the family,
        and check verdicts are not consulted while it runs. Its family size
        ``m`` is therefore the true number of tests. Gating on checks before
        the correction would shrink ``m`` by the hypotheses that failed
        their checks, inflating everyone else's chance of surviving FDR --
        the exact selection bias the correction exists to remove. Checks are
        applied strictly afterwards, as a further conjunct on a decision BH
        has already made.
        """
        members = self.family(family_id)
        if not members:
            raise UnknownHypothesisError(
                f"no hypotheses registered in family {family_id!r}"
            )

        tested: list[HypothesisRecord] = []
        for record in members:
            if record.state in PENDING_STATES:
                raise FamilyNotReadyError(
                    f"{record.hypothesis_id} is still {record.state.value}; "
                    f"adjudicating now would understate the family size and "
                    f"void FDR control"
                )
            if record.state is HypothesisState.TESTED:
                tested.append(record)
                continue
            if (
                record.state is HypothesisState.REJECTED
                and record.test_evaluation is None
            ):
                # Rejected before ever reading the test segment: it produced no
                # p-value, so it is not one of the m tests.
                continue
            raise FamilyAlreadyAdjudicatedError(
                f"{record.hypothesis_id} is in state {record.state.value}; "
                f"family {family_id} has already been adjudicated"
            )

        if not tested:
            raise FamilyNotReadyError(
                f"family {family_id} has no tested hypotheses to adjudicate"
            )

        labels = [record.hypothesis_id for record in tested]
        p_values = []
        for record in tested:
            test_evaluation = record.test_evaluation
            if test_evaluation is None or test_evaluation.p_value is None:
                raise FamilyNotReadyError(
                    f"{record.hypothesis_id} is TESTED but carries no test p-value"
                )
            p_values.append(float(test_evaluation.p_value))

        # The correction runs here, over every tested member of the family,
        # with no check verdict consulted above this line.
        decision = benjamini_hochberg(p_values, q=q, labels=labels)

        # Only now do checks enter, as a fourth conjunct on an already-made
        # per-hypothesis FDR decision.
        for record in tested:
            test_evaluation = record.test_evaluation
            assert test_evaluation is not None  # guaranteed by the loop above
            passes_fdr = decision.is_rejected(record.hypothesis_id)
            passes_alpha = (
                float(test_evaluation.p_value) <= record.preregistration.alpha
            )
            passes_effect = float(test_evaluation.effect_size or 0.0) >= (
                record.preregistration.minimum_effect_size
            )
            # Missing required checks adjudicate as failures, so a hypothesis
            # whose plan is incomplete is rejected rather than held open.
            passes_checks = record.adjudicate_checks().all_required_checks_passed
            target = (
                HypothesisState.CANDIDATE
                if (
                    passes_fdr
                    and passes_alpha
                    and passes_effect
                    and passes_checks
                )
                else HypothesisState.REJECTED
            )
            validate_transition(record.state, target)
            self._records[record.hypothesis_id] = record.transitioned_to(target)

        self._save()
        return decision


__all__ = [
    "REGISTRY_FORMAT_VERSION",
    "DIRECTIONS",
    "SEGMENTS",
    "PENDING_STATES",
    "CHECK_ORDER",
    "CHECK_SEGMENTS",
    "CheckName",
    "CheckVerdict",
    "CheckPlanStatus",
    "CheckPlan",
    "CheckResult",
    "CheckAdjudication",
    "RegistryError",
    "DuplicateHypothesisError",
    "UnknownHypothesisError",
    "SealVerificationError",
    "EvaluationNotPermittedError",
    "UnplannedCheckError",
    "DuplicateCheckError",
    "ThresholdBindingError",
    "FamilyAdjudicationRequiredError",
    "FamilyNotReadyError",
    "FamilyAlreadyAdjudicatedError",
    "FamilyMembershipTamperedError",
    "StateChainError",
    "PreRegistration",
    "EvaluationRecord",
    "StateTransition",
    "FamilyManifest",
    "HypothesisRecord",
    "HypothesisRegistry",
]
