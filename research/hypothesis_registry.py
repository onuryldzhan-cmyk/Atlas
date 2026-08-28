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
from pathlib import Path
from typing import Any, Mapping, Sequence

from research.lifecycle import (
    HypothesisState,
    can_evaluate_test,
    validate_transition,
)
from research.multiple_testing import FDRDecision, benjamini_hochberg
from research.splitting import SplitSpec

REGISTRY_FORMAT_VERSION = 1

_HYPOTHESIS_ID_PATTERN = re.compile(r"^HYP-[0-9]{4}$")
_FAMILY_ID_PATTERN = re.compile(r"^FAM-[A-Z0-9-]{1,32}$")
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{2,20}$")

DIRECTIONS: frozenset[str] = frozenset({"greater", "less", "two_sided"})
SEGMENTS: frozenset[str] = frozenset({"TRAIN", "CALIBRATION", "TEST"})

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


class FamilyNotReadyError(RegistryError):
    """Raised when a family still has hypotheses awaiting a test result."""


class FamilyAlreadyAdjudicatedError(RegistryError):
    """Raised when a family has already been through FDR adjudication."""


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
                feature_spec=dict(payload.get("feature_spec", {})),
                preregistered_at=payload["preregistered_at"],
            )
        except KeyError as exc:
            raise RegistryError(f"pre-registration missing field {exc}") from exc


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    """One append-only evaluation result against a named data segment."""

    segment: str
    statistic_value: float
    p_value: float | None = None
    effect_size: float | None = None
    notes: str = ""
    recorded_at: str = field(default_factory=_now)

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
            )
        except KeyError as exc:
            raise RegistryError(f"evaluation missing field {exc}") from exc


@dataclass(frozen=True, slots=True)
class HypothesisRecord:
    """A sealed pre-registration plus its mutable lifecycle state."""

    preregistration: PreRegistration
    preregistration_hash: str
    state: HypothesisState
    evaluations: tuple[EvaluationRecord, ...] = ()

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

    def verify_seal(self) -> None:
        """Raise SealVerificationError if the sealed content has been edited."""
        recomputed = self.preregistration.seal_hash()
        if recomputed != self.preregistration_hash:
            raise SealVerificationError(
                f"pre-registration seal mismatch for {self.hypothesis_id}: "
                f"stored {self.preregistration_hash}, recomputed {recomputed}"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "preregistration": self.preregistration.sealed_payload(),
            "preregistration_hash": self.preregistration_hash,
            "state": self.state.value,
            "evaluations": [e.as_dict() for e in self.evaluations],
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
            )
        except KeyError as exc:
            raise RegistryError(f"hypothesis record missing field {exc}") from exc
        record.verify_seal()
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

        version = payload.get("version")
        if version != REGISTRY_FORMAT_VERSION:
            raise RegistryError(
                f"unsupported registry format version {version!r}; "
                f"expected {REGISTRY_FORMAT_VERSION}"
            )

        for entry in payload.get("records", ()):
            # from_dict verifies the seal, so a hand-edited file fails here.
            record = HypothesisRecord.from_dict(entry)
            self._records[record.hypothesis_id] = record

    def _save(self) -> None:
        payload = {
            "version": REGISTRY_FORMAT_VERSION,
            "records": [
                self._records[key].as_dict() for key in sorted(self._records)
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

    # -- writes ----------------------------------------------------------

    def register(self, preregistration: PreRegistration) -> HypothesisRecord:
        """Seal a pre-registration and store it in the REGISTERED state."""
        hypothesis_id = preregistration.hypothesis_id
        if hypothesis_id in self._records:
            raise DuplicateHypothesisError(
                f"{hypothesis_id} is already registered; a changed hypothesis "
                f"needs a new id, not an amendment"
            )
        record = HypothesisRecord(
            preregistration=preregistration,
            preregistration_hash=preregistration.seal_hash(),
            state=HypothesisState.REGISTERED,
            evaluations=(),
        )
        self._records[hypothesis_id] = record
        self._save()
        return record

    def advance(
        self, hypothesis_id: str, target_state: HypothesisState
    ) -> HypothesisRecord:
        """Move a hypothesis to ``target_state`` if the transition is legal."""
        record = self.get(hypothesis_id)
        target_state = HypothesisState(target_state)
        validate_transition(record.state, target_state)
        updated = replace(record, state=target_state)
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

        updated = replace(record, evaluations=record.evaluations + (evaluation,))
        if segment == "TEST":
            validate_transition(updated.state, HypothesisState.TESTED)
            updated = replace(updated, state=HypothesisState.TESTED)

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

        A hypothesis is promoted only if it clears all three gates: the
        family-level FDR decision, its own pre-registered ``alpha``, and its
        pre-registered ``minimum_effect_size``.
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

        decision = benjamini_hochberg(p_values, q=q, labels=labels)

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
            target = (
                HypothesisState.CANDIDATE
                if (passes_fdr and passes_alpha and passes_effect)
                else HypothesisState.REJECTED
            )
            validate_transition(record.state, target)
            self._records[record.hypothesis_id] = replace(record, state=target)

        self._save()
        return decision


__all__ = [
    "REGISTRY_FORMAT_VERSION",
    "DIRECTIONS",
    "SEGMENTS",
    "PENDING_STATES",
    "RegistryError",
    "DuplicateHypothesisError",
    "UnknownHypothesisError",
    "SealVerificationError",
    "EvaluationNotPermittedError",
    "FamilyNotReadyError",
    "FamilyAlreadyAdjudicatedError",
    "PreRegistration",
    "EvaluationRecord",
    "HypothesisRecord",
    "HypothesisRegistry",
]
