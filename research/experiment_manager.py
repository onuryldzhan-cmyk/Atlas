"""Experiment Manager v1 -- research only (GRANT-EXPMGR-V1-RESEARCH-ONLY, v5.86).

Records pre-registered experiments, their runs and a verdict. Its output is
evidence for the owner, never trading authority: it imports nothing outside
``research/`` (ADR-0009), no runtime module imports it, and there is no
method here that reaches a risk gate, capital, an order path or the runtime
brain.

**Identity.** No new id scheme. An experiment *is* its sealed
``PreRegistration``: it is keyed by ``hypothesis_id``, pinned to the
pre-registration seal hash, and carries the hypothesis's sealed ``CheckPlan``.
One experiment per hypothesis; a changed experiment needs a new hypothesis.

**Storage.** None. The run / verdict log is an in-memory, append-only,
SHA-256 hash-chained (unkeyed) tuple; it is lost when the process ends and is
never durable evidence. The grant forbids a new storage schema without a
separate owner approval, so persistence is deliberately absent. Check results
live where they already live: in ``HypothesisRegistry``, written through its
own ``record_evaluation`` path.

**Reads are tamper-safe (review H1).** Every log payload is deep-frozen
(read-only mappings, tuples), so a returned entry cannot be mutated into
manager state. Every public read of research state (``log``, ``runs``,
``effective_runs``, ``verdicts``, ``latest_verdict``, ``experiment``)
re-verifies the hash chain first and halts on a mismatch.

**Evidence binding (review M2).** The registry's evaluations are hashed one
by one into an evidence snapshot, pinned at registration, at every status
change and in every verdict. An evaluation that is later altered, removed or
inserted before a pinned one is an integrity failure (halt). An evaluation
*appended* after completion through the registry's own write path is allowed,
but only as an explicit successor verdict bound to the new evidence hash and
flagged ``evidence_after_completion``.

**Verdicts** (v5.86 ``verdict_rules``):

* SUPPORTED requires a registered p-value procedure and a power analysis.
  Neither exists (both constants below are ``None``), so no code path here
  returns SUPPORTED; the ceiling is INSUFFICIENT_EVIDENCE.
* REJECTED requires rejection criteria sealed inside the pre-registration
  (``feature_spec["rejection_criteria"]``), all required checks recorded
  (the plan is the NB-5 denominator), a pre-registered failing check, and
  every recorded run -- superseded runs included (review M1) -- meeting the
  pre-registered minimum sample. Missing or corrupt data, a missing check or
  a small sample give INSUFFICIENT_EVIDENCE; superseding a small run with a
  larger one cannot hide the small one.
  Criteria cannot be supplied at evaluation time; adding them afterwards
  changes the seal and halts the manager.
* INSUFFICIENT_EVIDENCE otherwise.

**Fail safe.** Any integrity failure (seal drift, broken log chain, tampered
stored checks, altered evidence) or unexpected error halts the manager; every
later research read and every write raises ``ExperimentManagerHalted``. The
only exception is ``log``: after a halt it stays readable as frozen forensic
evidence and is no longer verified -- it is never trusted research state.
Malformed caller input is refused without halting and without writing.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from research.hypothesis_registry import (
    CheckName,
    CheckPlan,
    CheckPlanStatus,
    HypothesisRecord,
    HypothesisRegistry,
    RegistryError,
    UnknownHypothesisError,
)
from research.lifecycle import is_terminal

#: v5.86: no p-value procedure is registered in this build.
REGISTERED_P_VALUE_PROCEDURE: str | None = None
#: v5.86: no power analysis is registered in this build.
REGISTERED_POWER_ANALYSIS: str | None = None

#: The sealed ``PreRegistration.feature_spec`` key holding rejection criteria.
REJECTION_CRITERIA_KEY = "rejection_criteria"
_CRITERIA_FIELDS = frozenset({"minimum_sample_size", "failing_checks"})

_EVIDENCE_REF_PATTERN = re.compile(r"^[A-Za-z0-9._:/#@-]{1,200}$")
_METRIC_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_GENESIS = "0" * 64


class ExperimentError(Exception):
    """Base error for Experiment Manager contract violations."""


class IllegalExperimentTransitionError(ExperimentError):
    """The experiment lifecycle does not permit the requested step."""


class MalformedRunError(ExperimentError):
    """A run result is missing, malformed or references nothing valid."""


class ExperimentIntegrityError(ExperimentError):
    """Seal, log chain or stored evidence failed verification. Halts."""


class ExperimentManagerHalted(ExperimentError):
    """The manager stopped after an integrity failure or unexpected error."""


class ExperimentStatus(str, Enum):
    REGISTERED = "REGISTERED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


_TRANSITIONS: Mapping[ExperimentStatus, frozenset[ExperimentStatus]] = {
    ExperimentStatus.REGISTERED: frozenset(
        {ExperimentStatus.RUNNING, ExperimentStatus.ABORTED}
    ),
    ExperimentStatus.RUNNING: frozenset(
        {ExperimentStatus.COMPLETED, ExperimentStatus.ABORTED}
    ),
    ExperimentStatus.COMPLETED: frozenset(),
    ExperimentStatus.ABORTED: frozenset(),
}


class Verdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    REJECTED = "REJECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _freeze(value: Any) -> Any:
    """Deep read-only copy: mappings become read-only proxies, sequences tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Plain JSON-shaped copy of a frozen value (what is hashed and exported)."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class RunResult:
    """One research run's outcome, as plain data. Validated on construction."""

    sample_size: int
    evidence_refs: tuple[str, ...]
    metrics: Mapping[str, float] = field(default_factory=dict)
    supersedes: str | None = None

    def __post_init__(self) -> None:
        size = self.sample_size
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise MalformedRunError(f"sample_size must be a positive int, got {size!r}")
        refs = tuple(self.evidence_refs) if not isinstance(self.evidence_refs, str) else ()
        if not refs:
            raise MalformedRunError("a run must reference at least one evidence item")
        for ref in refs:
            if not isinstance(ref, str) or not _EVIDENCE_REF_PATTERN.match(ref):
                raise MalformedRunError(f"invalid evidence reference {ref!r}")
        if len(set(refs)) != len(refs):
            raise MalformedRunError("duplicate evidence reference")
        object.__setattr__(self, "evidence_refs", refs)
        metrics: dict[str, float] = {}
        for name, value in dict(self.metrics).items():
            if not isinstance(name, str) or not _METRIC_NAME_PATTERN.match(name):
                raise MalformedRunError(f"invalid metric name {name!r}")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise MalformedRunError(f"metric {name} must be numeric")
            if not math.isfinite(float(value)):
                raise MalformedRunError(f"metric {name} must be finite")
            metrics[name] = float(value)
        object.__setattr__(self, "metrics", MappingProxyType(metrics))
        if self.supersedes is not None and not (
            isinstance(self.supersedes, str) and _HASH_PATTERN.match(self.supersedes)
        ):
            raise MalformedRunError("supersedes must be a log entry hash")

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_size": self.sample_size,
            "evidence_refs": list(self.evidence_refs),
            "metrics": dict(self.metrics),
            "supersedes": self.supersedes,
        }


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One append-only, hash-chained log entry."""

    sequence: int
    kind: str
    hypothesis_id: str
    payload: Mapping[str, Any]
    recorded_at: str
    previous_hash: str
    entry_hash: str

    def __post_init__(self) -> None:
        # Review H1: the payload is deep-frozen, so no returned entry can be
        # used to mutate manager state.
        object.__setattr__(self, "payload", _freeze(self.payload))

    def hashed_body(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "hypothesis_id": self.hypothesis_id,
            "payload": _thaw(self.payload),
            "recorded_at": self.recorded_at,
            "previous_hash": self.previous_hash,
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.hashed_body(), "entry_hash": self.entry_hash}


@dataclass(frozen=True, slots=True)
class Experiment:
    """Read-only view of one experiment, derived from the log."""

    hypothesis_id: str
    family_id: str
    preregistration_hash: str
    check_plan: CheckPlan
    status: ExperimentStatus

    @property
    def required_check_count(self) -> int:
        return self.check_plan.required_check_count


@dataclass(frozen=True, slots=True)
class VerdictRecord:
    """A recorded verdict. Evidence for the owner; it carries no authority."""

    hypothesis_id: str
    verdict: Verdict
    reasons: tuple[str, ...]
    preregistration_hash: str
    supersedes: str | None
    entry_hash: str
    evidence_hash: str
    evidence_after_completion: bool


class ExperimentManager:
    """Research-only manager over an existing ``HypothesisRegistry``."""

    def __init__(self, *, registry: HypothesisRegistry) -> None:
        if not isinstance(registry, HypothesisRegistry):
            raise ExperimentError("registry must be a HypothesisRegistry")
        self._registry = registry
        self._log: list[LogEntry] = []
        self._halted = False

    # -- guards ----------------------------------------------------------

    @property
    def halted(self) -> bool:
        return self._halted

    def _guarded(self, operation, *args):
        if self._halted:
            raise ExperimentManagerHalted("experiment manager is halted")
        try:
            return operation(*args)
        except ExperimentIntegrityError:
            self._halted = True
            raise
        except (ExperimentError, UnknownHypothesisError):
            raise
        except Exception as exc:  # unexpected: stop rather than continue
            self._halted = True
            raise ExperimentManagerHalted(
                f"halted on unexpected {type(exc).__name__}: {exc}"
            ) from exc

    # -- log -------------------------------------------------------------

    @property
    def log(self) -> tuple[LogEntry, ...]:
        """The frozen log. Verified before it is returned (a mismatch halts).

        After a halt it stays readable as forensic evidence only: it is then
        returned unverified and is never trusted research state.
        """
        if self._halted:
            return tuple(self._log)
        return self._guarded(self._verified_log)

    def _verified_log(self) -> tuple[LogEntry, ...]:
        self._verify_log()
        return tuple(self._log)

    def verify_log(self) -> None:
        self._guarded(self._verify_log)

    def _verify_log(self) -> None:
        previous = _GENESIS
        for index, entry in enumerate(self._log):
            if entry.sequence != index or entry.previous_hash != previous:
                raise ExperimentIntegrityError(f"log chain broken at entry {index}")
            if _sha256(entry.hashed_body()) != entry.entry_hash:
                raise ExperimentIntegrityError(f"log entry {index} hash mismatch")
            previous = entry.entry_hash

    def _append(self, kind: str, hypothesis_id: str, payload: Mapping[str, Any]) -> LogEntry:
        previous = self._log[-1].entry_hash if self._log else _GENESIS
        body = {
            "sequence": len(self._log),
            "kind": kind,
            "hypothesis_id": hypothesis_id,
            "payload": json.loads(_canonical(payload)),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "previous_hash": previous,
        }
        entry = LogEntry(**body, entry_hash=_sha256(body))
        self._log.append(entry)
        return entry

    def _entries(self, hypothesis_id: str, kind: str) -> tuple[LogEntry, ...]:
        return tuple(
            e for e in self._log if e.hypothesis_id == hypothesis_id and e.kind == kind
        )

    # -- evidence binding (review M2) --------------------------------------

    @staticmethod
    def _evidence_snapshot(record: HypothesisRecord) -> tuple[str, ...]:
        """One hash per stored evaluation, in stored order."""
        return tuple(
            _sha256({"hypothesis_id": record.hypothesis_id, "evaluation": e.as_dict()})
            for e in record.evaluations
        )

    @staticmethod
    def _evidence_hash(snapshot: tuple[str, ...]) -> str:
        return _sha256({"evaluations": list(snapshot)})

    def _pinned_snapshots(self, hypothesis_id: str) -> tuple[tuple[str, ...], ...]:
        pins = []
        for entry in self._log:
            if entry.hypothesis_id != hypothesis_id:
                continue
            if entry.kind in ("EXPERIMENT_REGISTERED", "STATUS_CHANGED", "VERDICT_RECORDED"):
                pinned = entry.payload.get("evidence_snapshot")
                if not isinstance(pinned, tuple):
                    raise ExperimentIntegrityError(
                        f"{hypothesis_id}: log entry {entry.sequence} carries no evidence snapshot"
                    )
                pins.append(pinned)
        return tuple(pins)

    def _verify_evidence(self, hypothesis_id: str, record: HypothesisRecord) -> tuple[str, ...]:
        """Every pinned snapshot must still be an exact prefix of the stored evaluations.

        Altered, removed or inserted-before evaluations break the prefix and
        halt; evaluations appended after the last pin keep it and are allowed.
        """
        current = self._evidence_snapshot(record)
        for pinned in self._pinned_snapshots(hypothesis_id):
            if current[: len(pinned)] != pinned:
                raise ExperimentIntegrityError(
                    f"{hypothesis_id}: evaluation evidence was altered, removed or "
                    f"inserted after it was pinned"
                )
        return current

    # -- registry access -------------------------------------------------

    def _verified_record(self, hypothesis_id: str, pinned: str | None) -> HypothesisRecord:
        record = self._registry.get(hypothesis_id)
        try:
            record.verify_seal()
            record.verify_state_chain()
            record.verify_recorded_checks()
        except RegistryError as exc:
            raise ExperimentIntegrityError(str(exc)) from exc
        if pinned is not None and record.preregistration_hash != pinned:
            raise ExperimentIntegrityError(
                f"{hypothesis_id} pre-registration hash changed since the "
                f"experiment was registered"
            )
        return record

    # -- reads -----------------------------------------------------------

    def experiment(self, hypothesis_id: str) -> Experiment:
        return self._guarded(self._experiment, hypothesis_id)

    def _experiment(self, hypothesis_id: str) -> Experiment:
        self._verify_log()
        created = self._entries(hypothesis_id, "EXPERIMENT_REGISTERED")
        if not created:
            raise ExperimentError(f"no experiment registered for {hypothesis_id!r}")
        pinned = created[0].payload["preregistration_hash"]
        record = self._verified_record(hypothesis_id, pinned)
        self._verify_evidence(hypothesis_id, record)
        status = ExperimentStatus.REGISTERED
        for entry in self._entries(hypothesis_id, "STATUS_CHANGED"):
            status = ExperimentStatus(entry.payload["to"])
        return Experiment(
            hypothesis_id=hypothesis_id,
            family_id=record.family_id,
            preregistration_hash=pinned,
            check_plan=record.check_plan,
            status=status,
        )

    def runs(self, hypothesis_id: str) -> tuple[LogEntry, ...]:
        """Every recorded run, superseded ones included (provenance is kept)."""
        return self._guarded(self._verified_entries, hypothesis_id, "RUN_RECORDED")

    def _verified_entries(self, hypothesis_id: str, kind: str) -> tuple[LogEntry, ...]:
        self._verify_log()
        return self._entries(hypothesis_id, kind)

    def effective_runs(self, hypothesis_id: str) -> tuple[LogEntry, ...]:
        return self._guarded(self._verified_effective_runs, hypothesis_id)

    def _verified_effective_runs(self, hypothesis_id: str) -> tuple[LogEntry, ...]:
        self._verify_log()
        return self._effective_runs(hypothesis_id)

    def _effective_runs(self, hypothesis_id: str) -> tuple[LogEntry, ...]:
        runs = self._entries(hypothesis_id, "RUN_RECORDED")
        superseded = {r.payload["run"]["supersedes"] for r in runs}
        return tuple(r for r in runs if r.entry_hash not in superseded)

    def verdicts(self, hypothesis_id: str) -> tuple[VerdictRecord, ...]:
        return self._guarded(self._verified_verdicts, hypothesis_id)

    def _verified_verdicts(self, hypothesis_id: str) -> tuple[VerdictRecord, ...]:
        self._verify_log()
        return self._verdicts(hypothesis_id)

    def latest_verdict(self, hypothesis_id: str) -> VerdictRecord | None:
        found = self.verdicts(hypothesis_id)
        return found[-1] if found else None

    def _verdicts(self, hypothesis_id: str) -> tuple[VerdictRecord, ...]:
        return tuple(
            VerdictRecord(
                hypothesis_id=e.hypothesis_id,
                verdict=Verdict(e.payload["verdict"]),
                reasons=tuple(e.payload["reasons"]),
                preregistration_hash=e.payload["preregistration_hash"],
                supersedes=e.payload["supersedes"],
                entry_hash=e.entry_hash,
                evidence_hash=e.payload["evidence_hash"],
                evidence_after_completion=e.payload["evidence_after_completion"],
            )
            for e in self._entries(hypothesis_id, "VERDICT_RECORDED")
        )

    # -- writes ----------------------------------------------------------

    def register_experiment(self, hypothesis_id: str) -> Experiment:
        return self._guarded(self._register, hypothesis_id)

    def _register(self, hypothesis_id: str) -> Experiment:
        self._verify_log()
        if self._entries(hypothesis_id, "EXPERIMENT_REGISTERED"):
            raise ExperimentError(
                f"{hypothesis_id} already has an experiment; a changed experiment "
                f"needs a new pre-registered hypothesis"
            )
        record = self._verified_record(hypothesis_id, None)
        if is_terminal(record.state):
            raise ExperimentError(
                f"{hypothesis_id} is {record.state.value}; no experiment can open"
            )
        self._append(
            "EXPERIMENT_REGISTERED",
            hypothesis_id,
            {
                "preregistration_hash": record.preregistration_hash,
                "family_id": record.family_id,
                "check_plan": record.check_plan.as_dict(),
                "evidence_snapshot": list(self._evidence_snapshot(record)),
            },
        )
        return self._experiment(hypothesis_id)

    def _transition(self, hypothesis_id: str, target: ExperimentStatus, reason: str = "") -> Experiment:
        experiment = self._experiment(hypothesis_id)
        current = experiment.status
        if target not in _TRANSITIONS[current]:
            raise IllegalExperimentTransitionError(
                f"{hypothesis_id}: {current.value} -> {target.value} is not permitted"
            )
        record = self._verified_record(hypothesis_id, experiment.preregistration_hash)
        snapshot = self._verify_evidence(hypothesis_id, record)
        self._append(
            "STATUS_CHANGED",
            hypothesis_id,
            {
                "from": current.value,
                "to": target.value,
                "reason": reason,
                "evidence_snapshot": list(snapshot),
            },
        )
        return self._experiment(hypothesis_id)

    def start(self, hypothesis_id: str) -> Experiment:
        return self._guarded(self._transition, hypothesis_id, ExperimentStatus.RUNNING)

    def complete(self, hypothesis_id: str) -> Experiment:
        return self._guarded(self._transition, hypothesis_id, ExperimentStatus.COMPLETED)

    def abort(self, hypothesis_id: str, *, reason: str) -> Experiment:
        return self._guarded(self._abort, hypothesis_id, reason)

    def _abort(self, hypothesis_id: str, reason: str) -> Experiment:
        if not isinstance(reason, str) or not reason.strip():
            raise ExperimentError("an abort needs a reason")
        try:  # F-5: unserialisable text is refused input, not a halt
            reason.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ExperimentError("an abort reason must be valid UTF-8 text") from exc
        return self._transition(hypothesis_id, ExperimentStatus.ABORTED, reason.strip())

    def record_run(self, hypothesis_id: str, run: RunResult) -> LogEntry:
        return self._guarded(self._record_run, hypothesis_id, run)

    def _record_run(self, hypothesis_id: str, run: RunResult) -> LogEntry:
        if not isinstance(run, RunResult):
            raise MalformedRunError("run must be a RunResult")
        status = self._experiment(hypothesis_id).status
        if status is not ExperimentStatus.RUNNING:
            raise IllegalExperimentTransitionError(
                f"{hypothesis_id} is {status.value}; runs are recorded only while RUNNING"
            )
        run_hash = _sha256({"hypothesis_id": hypothesis_id, "run": run.as_dict()})
        existing = self._entries(hypothesis_id, "RUN_RECORDED")
        for entry in existing:
            if entry.payload["run_hash"] == run_hash:
                return entry  # idempotent: the same run is never recorded twice
        if run.supersedes is not None:
            targets = {e.entry_hash for e in existing}
            if run.supersedes not in targets:
                raise MalformedRunError("supersedes references no run of this experiment")
            if any(e.payload["run"]["supersedes"] == run.supersedes for e in existing):
                raise MalformedRunError("that run has already been superseded")
        return self._append(
            "RUN_RECORDED", hypothesis_id, {"run_hash": run_hash, "run": run.as_dict()}
        )

    # -- verdict ---------------------------------------------------------

    def evaluate(self, hypothesis_id: str) -> VerdictRecord:
        return self._guarded(self._evaluate, hypothesis_id)

    def _evaluate(self, hypothesis_id: str) -> VerdictRecord:
        experiment = self._experiment(hypothesis_id)
        if experiment.status not in (ExperimentStatus.COMPLETED, ExperimentStatus.ABORTED):
            raise IllegalExperimentTransitionError(
                f"{hypothesis_id} is {experiment.status.value}; a verdict needs "
                f"COMPLETED or ABORTED"
            )
        record = self._verified_record(hypothesis_id, experiment.preregistration_hash)
        snapshot = self._verify_evidence(hypothesis_id, record)
        evidence_hash = self._evidence_hash(snapshot)
        terminal = [
            e for e in self._entries(hypothesis_id, "STATUS_CHANGED")
            if e.payload["to"] in (ExperimentStatus.COMPLETED.value, ExperimentStatus.ABORTED.value)
        ]
        late = len(snapshot) > len(terminal[-1].payload["evidence_snapshot"])
        verdict, reasons = self._decide(experiment, record)

        previous = self._verdicts(hypothesis_id)
        last = previous[-1] if previous else None
        if (
            last is not None
            and last.verdict is verdict
            and last.reasons == reasons
            and last.evidence_hash == evidence_hash
        ):
            return last  # idempotent: nothing changed, nothing appended
        self._append(
            "VERDICT_RECORDED",
            hypothesis_id,
            {
                "verdict": verdict.value,
                "reasons": list(reasons),
                "preregistration_hash": experiment.preregistration_hash,
                "supersedes": last.entry_hash if last else None,
                "evidence_snapshot": list(snapshot),
                "evidence_hash": evidence_hash,
                "evidence_after_completion": late,
            },
        )
        return self._verdicts(hypothesis_id)[-1]

    def _decide(
        self, experiment: Experiment, record: HypothesisRecord
    ) -> tuple[Verdict, tuple[str, ...]]:
        insufficient = Verdict.INSUFFICIENT_EVIDENCE
        if experiment.status is ExperimentStatus.ABORTED:
            return insufficient, ("EXPERIMENT_ABORTED",)

        reasons: list[str] = []
        runs = self._effective_runs(experiment.hypothesis_id)
        if not runs:
            reasons.append("NO_RUN")

        adjudication = record.adjudicate_checks()
        if adjudication.status is CheckPlanStatus.INCOMPLETE:
            reasons.append("CHECKS_MISSING")

        criteria = self._rejection_criteria(record, reasons)
        if criteria is not None and runs:
            minimum, failing = criteria
            # Review M1: every recorded run counts, superseded ones included,
            # so replacing a small run with a larger one cannot hide it.
            recorded = self._entries(experiment.hypothesis_id, "RUN_RECORDED")
            if any(r.payload["run"]["sample_size"] < minimum for r in recorded):
                reasons.append("SAMPLE_TOO_SMALL")
            if adjudication.status is CheckPlanStatus.COMPLETE_FAIL:
                hits = [c for c in adjudication.failed_checks if c in failing]
                if not hits:
                    reasons.append("FAILURE_NOT_A_PREREGISTERED_REJECTION_CRITERION")
                elif not reasons:
                    return Verdict.REJECTED, tuple(
                        f"PREREGISTERED_REJECTION_CRITERIA_MET:{c.value}" for c in hits
                    )

        # SUPPORTED: the v5.86 preconditions do not exist in this build.
        if REGISTERED_P_VALUE_PROCEDURE is None:
            reasons.append("SUPPORTED_CEILING_NO_REGISTERED_P_VALUE_PROCEDURE")
        if REGISTERED_POWER_ANALYSIS is None:
            reasons.append("SUPPORTED_CEILING_NO_POWER_ANALYSIS")
        return insufficient, tuple(reasons)

    @staticmethod
    def _rejection_criteria(
        record: HypothesisRecord, reasons: list[str]
    ) -> tuple[int, frozenset[CheckName]] | None:
        """Parse the sealed criteria strictly; anything invalid cannot reject."""
        spec = record.preregistration.feature_spec
        if REJECTION_CRITERIA_KEY not in spec:
            reasons.append("NO_PREREGISTERED_REJECTION_CRITERIA")
            return None
        raw = spec[REJECTION_CRITERIA_KEY]
        try:
            if not isinstance(raw, Mapping) or set(raw) != _CRITERIA_FIELDS:
                raise ValueError("criteria fields")
            minimum = raw["minimum_sample_size"]
            if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
                raise ValueError("minimum_sample_size")
            names = raw["failing_checks"]
            if isinstance(names, str) or not names:
                raise ValueError("failing_checks")
            failing = frozenset(CheckName(n) for n in names)
            if len(failing) != len(names) or not all(
                record.check_plan.requires(c) for c in failing
            ):
                raise ValueError("failing_checks not in sealed plan")
        except (ValueError, TypeError):
            reasons.append("REJECTION_CRITERIA_INVALID")
            return None
        return minimum, failing
