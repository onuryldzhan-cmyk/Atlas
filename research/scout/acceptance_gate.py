"""The 7-step acceptance gate for external tools and strategies (Task 011).

Every external candidate (repository, library, strategy or prompt skill) is
scored on seven fixed steps:

1. REAL_PROBLEM_ALIGNMENT -- it addresses a problem on the owner-curated
   register of verified Atlas problems.
2. SOURCE_RELIABILITY -- recent maintenance, enough maintainers, and a source
   that is not social media.
3. LICENSE_COMPLIANCE -- an SPDX licence on the allow-list.
4. SECURITY_RISK -- no network access, subprocess, dynamic code execution or
   install-time hooks, and no known vulnerabilities.
5. ARCHITECTURAL_FIT -- no overlap with an existing component and no more new
   dependencies than the policy allows.
6. MEASURABLE_VALUE -- a sealed Atlas hypothesis (Task 005), bound to this
   candidate at pre-registration, that passed its pre-registered checks and
   family adjudication (Task 006).
7. REVERSIBILITY -- a removal plan and no state migration.

Fail-closed rules (CLAUDE.md NB-4 / NB-5 analogues):

* A field that was not assessed (``None``) fails its step. Removing evidence
  can therefore only turn a pass into a fail, never the reverse.
* All seven steps are always evaluated and every failed criterion is
  reported and logged. The denominator is the fixed ``REQUIRED_STEP_COUNT``,
  never the number of steps that happened to have data.

**There is no ACCEPTED outcome.** The best a candidate can reach is
``PENDING_OWNER_REVIEW``: capability is never authority, and adoption still
goes through the owner and the normal Atlas workflow. As in
``research.lifecycle``, the way to keep the gate from granting authority is for
the state not to exist.

**External benchmark claims are never evidence.** ``claimed_benchmarks`` is
recorded for the reviewer and red team only; step 6 never reads it. Step 6
passes only on a ``HypothesisRegistry`` record that Atlas sealed and
adjudicated itself, re-verified here, in state CANDIDATE or later (reachable
only through family adjudication) with every pre-registered check passed. The
registry is only read.

The hypothesis must be **bound** to the candidate: its sealed ``feature_spec``
carries ``scout_candidate_id`` and ``scout_source_url`` equal to the
candidate's id and source URL. Because ``feature_spec`` is inside the seal,
the binding is fixed when the hypothesis is pre-registered; any other passing
hypothesis cannot be borrowed by quoting its id.

Step 6 re-opens the registry **from its file** (an in-memory record that is
not on disk does not count) and pins the file's SHA-256, refusing a file that
changed while it was read. It refuses evidence dated after ``as_of`` (no
lookahead): the pre-registration time and the CANDIDATE transition must both
be no later than it.

Seals are tamper-evidence, not authentication: anyone who can write a registry
file through its API can build a self-consistent record. Step 6 therefore
records the provenance it relied on (resolved registry path and file digest,
seal and state-chain hashes, title, family, pre-registration and adjudication
times) so the owner can check it at review. A PENDING_OWNER_REVIEW finding is
refused at construction unless that provenance is present and every
policy-independent condition of the seven steps holds (``pending_problem``).

This module performs no I/O and imports nothing outside ``research/`` and the
standard library (ADR-0009).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from pathlib import Path
from typing import Any, Iterable, Mapping

from research.hypothesis_registry import (
    CheckPlanStatus,
    HypothesisRecord,
    HypothesisRegistry,
    RegistryError,
)
from research.lifecycle import HypothesisState, is_terminal, progress_rank
from research.scout.provenance import (
    ScoutInputError,
    SourceRecord,
    SourceType,
    identifier,
    optional_amount,
    optional_bool,
    optional_count,
    optional_text_tuple,
    optional_utc,
    parse_utc,
    reject_unknown_keys,
    require_mapping,
    text,
    text_set,
)

logger = logging.getLogger(__name__)


class CandidateKind(str, Enum):
    REPOSITORY = "REPOSITORY"
    LIBRARY = "LIBRARY"
    STRATEGY = "STRATEGY"
    PROMPT_SKILL = "PROMPT_SKILL"


class GateStep(str, Enum):
    REAL_PROBLEM_ALIGNMENT = "REAL_PROBLEM_ALIGNMENT"
    SOURCE_RELIABILITY = "SOURCE_RELIABILITY"
    LICENSE_COMPLIANCE = "LICENSE_COMPLIANCE"
    SECURITY_RISK = "SECURITY_RISK"
    ARCHITECTURAL_FIT = "ARCHITECTURAL_FIT"
    MEASURABLE_VALUE = "MEASURABLE_VALUE"
    REVERSIBILITY = "REVERSIBILITY"


#: The fixed evaluation order and the NB-5 denominator.
GATE_STEPS: tuple[GateStep, ...] = tuple(GateStep)
REQUIRED_STEP_COUNT = len(GATE_STEPS)


class GateStatus(str, Enum):
    """Deliberately has no ACCEPTED value: the gate never adopts anything."""

    REJECTED = "REJECTED"
    PENDING_OWNER_REVIEW = "PENDING_OWNER_REVIEW"


#: Permissive licences whose terms do not constrain how Atlas is distributed.
#: Copyleft (GPL, AGPL, LGPL, MPL), NOASSERTION and unknown licences fail.
DEFAULT_ALLOWED_LICENSES: frozenset[str] = frozenset({
    "0BSD", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC-BY-4.0", "CC0-1.0",
    "ISC", "MIT", "PSF-2.0", "Unlicense", "Zlib",
})

#: The sealed feature_spec keys that bind a hypothesis to one scout candidate.
BINDING_CANDIDATE_KEY = "scout_candidate_id"
BINDING_SOURCE_URL_KEY = "scout_source_url"

#: The earliest hypothesis state that proves family adjudication happened
#: (TESTED -> CANDIDATE is the one family-adjudicated transition).
_ADJUDICATED_FLOOR = progress_rank(HypothesisState.CANDIDATE)


@dataclass(frozen=True)
class GatePolicy:
    allowed_licenses: frozenset[str] = DEFAULT_ALLOWED_LICENSES
    max_inactivity_days: int = 365
    min_maintainers: int = 1
    max_new_dependencies: int = 1

    def __post_init__(self) -> None:
        try:
            licenses = text_set(self.allowed_licenses, "allowed_licenses")
        except ScoutInputError as exc:
            raise ValueError(str(exc)) from exc
        object.__setattr__(self, "allowed_licenses", licenses)
        for name in ("max_inactivity_days", "min_maintainers", "max_new_dependencies"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.min_maintainers < 1:
            raise ValueError("min_maintainers must be at least 1")


@dataclass(frozen=True)
class SecurityProfile:
    """``None`` is *not assessed* and fails the step."""

    network_access: bool | None
    subprocess_execution: bool | None
    dynamic_code_execution: bool | None
    install_time_hooks: bool | None
    known_vulnerabilities: int | None

    _FIELDS = frozenset({
        "network_access", "subprocess_execution", "dynamic_code_execution",
        "install_time_hooks", "known_vulnerabilities",
    })

    @classmethod
    def from_dict(cls, payload: Any) -> "SecurityProfile":
        payload = require_mapping({} if payload is None else payload, "security")
        reject_unknown_keys(payload, cls._FIELDS, "security")
        return cls(
            network_access=optional_bool(payload, "network_access"),
            subprocess_execution=optional_bool(payload, "subprocess_execution"),
            dynamic_code_execution=optional_bool(payload, "dynamic_code_execution"),
            install_time_hooks=optional_bool(payload, "install_time_hooks"),
            known_vulnerabilities=optional_count(payload, "known_vulnerabilities"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in sorted(self._FIELDS)}


@dataclass(frozen=True)
class ScoutCandidate:
    """One external candidate, parsed strictly from untrusted input."""

    candidate_id: str
    kind: CandidateKind
    name: str
    source: SourceRecord
    problem_ref: str | None
    license_spdx: str | None
    last_activity_at: datetime | None
    maintainer_count: int | None
    security: SecurityProfile
    overlapping_components: tuple[str, ...] | None
    new_dependency_count: int | None
    sealed_hypothesis_id: str | None
    removal_plan: str | None
    requires_state_migration: bool | None
    monthly_cost_usd: float | None = None
    claimed_benchmarks: tuple[str, ...] = field(default=())

    _FIELDS = frozenset({
        "candidate_id", "kind", "name", "source", "problem_ref", "license_spdx",
        "last_activity_at", "maintainer_count", "security", "overlapping_components",
        "new_dependency_count", "sealed_hypothesis_id", "removal_plan",
        "requires_state_migration", "monthly_cost_usd", "claimed_benchmarks",
    })

    @classmethod
    def from_dict(cls, payload: Any) -> "ScoutCandidate":
        payload = require_mapping(payload, "candidate")
        reject_unknown_keys(payload, cls._FIELDS, "candidate")
        try:
            kind = CandidateKind(payload.get("kind"))
        except ValueError as exc:
            raise ScoutInputError(f"kind must be one of {[k.value for k in CandidateKind]}") from exc
        return cls(
            candidate_id=identifier(payload, "candidate_id"),
            kind=kind,
            name=text(payload, "name"),
            source=SourceRecord.from_dict(payload.get("source")),
            problem_ref=text(payload, "problem_ref", required=False, single_line=True),
            license_spdx=text(payload, "license_spdx", required=False, single_line=True),
            last_activity_at=optional_utc(payload, "last_activity_at"),
            maintainer_count=optional_count(payload, "maintainer_count"),
            security=SecurityProfile.from_dict(payload.get("security")),
            overlapping_components=optional_text_tuple(payload, "overlapping_components", single_line=True),
            new_dependency_count=optional_count(payload, "new_dependency_count"),
            sealed_hypothesis_id=text(payload, "sealed_hypothesis_id", required=False, single_line=True),
            removal_plan=text(payload, "removal_plan", required=False),
            requires_state_migration=optional_bool(payload, "requires_state_migration"),
            monthly_cost_usd=optional_amount(payload, "monthly_cost_usd"),
            claimed_benchmarks=optional_text_tuple(payload, "claimed_benchmarks") or (),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "kind": self.kind.value,
            "name": self.name,
            "source": self.source.as_dict(),
            "problem_ref": self.problem_ref,
            "license_spdx": self.license_spdx,
            "last_activity_at": None if self.last_activity_at is None else self.last_activity_at.isoformat(),
            "maintainer_count": self.maintainer_count,
            "security": self.security.as_dict(),
            "overlapping_components": None if self.overlapping_components is None else list(self.overlapping_components),
            "new_dependency_count": self.new_dependency_count,
            "sealed_hypothesis_id": self.sealed_hypothesis_id,
            "removal_plan": self.removal_plan,
            "requires_state_migration": self.requires_state_migration,
            "monthly_cost_usd": self.monthly_cost_usd,
            "claimed_benchmarks": list(self.claimed_benchmarks),
            "claimed_benchmarks_status": "UNVERIFIED_NOT_EVIDENCE",
        }


@dataclass(frozen=True)
class GateStepResult:
    step: GateStep
    passed: bool
    reasons: tuple[str, ...]
    evidence: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not isinstance(self.step, GateStep) or self.passed is not (not self.reasons):
            raise ValueError("a gate step passes exactly when it has no failure reasons")
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))

    def as_dict(self) -> dict[str, Any]:
        return {"step": self.step.value, "passed": self.passed, "reasons": list(self.reasons),
                "evidence": dict(self.evidence)}


@dataclass(frozen=True)
class GateVerdict:
    candidate_id: str
    steps: tuple[GateStepResult, ...]
    status: GateStatus
    required_step_count: int = REQUIRED_STEP_COUNT

    def __post_init__(self) -> None:
        # A verdict cannot be assembled out of step: all seven steps, in order, and a status that
        # follows from them. PENDING_OWNER_REVIEW is reachable only with every step passed.
        if self.required_step_count != REQUIRED_STEP_COUNT:
            raise ValueError("the gate denominator is fixed at 7")
        if tuple(getattr(r, "step", None) for r in self.steps) != GATE_STEPS:
            raise ValueError("a verdict must hold all seven steps in order")
        expected = (GateStatus.PENDING_OWNER_REVIEW if all(r.passed for r in self.steps)
                    else GateStatus.REJECTED)
        if self.status is not expected:
            raise ValueError("verdict status does not follow from its steps")

    @property
    def passed_step_count(self) -> int:
        return sum(1 for result in self.steps if result.passed)

    @property
    def failed_steps(self) -> tuple[GateStepResult, ...]:
        return tuple(result for result in self.steps if not result.passed)

    def result_for(self, step: GateStep) -> GateStepResult:
        return next(result for result in self.steps if result.step is step)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status.value,
            "passed_step_count": self.passed_step_count,
            "required_step_count": self.required_step_count,
            "score": f"{self.passed_step_count}/{self.required_step_count}",
            "steps": [result.as_dict() for result in self.steps],
        }


def _problem_alignment(candidate: ScoutCandidate, verified_problems: frozenset[str]) -> list[str]:
    if not verified_problems:
        return ["NO_VERIFIED_PROBLEM_REGISTER"]
    if candidate.problem_ref is None:
        return ["PROBLEM_REF_MISSING"]
    if candidate.problem_ref not in verified_problems:
        return [f"PROBLEM_NOT_VERIFIED:{candidate.problem_ref}"]
    return []


def _source_reliability(candidate: ScoutCandidate, policy: GatePolicy, as_of: datetime) -> list[str]:
    reasons: list[str] = []
    if candidate.source.source_type is SourceType.SOCIAL:
        reasons.append("SOCIAL_SOURCE")
    if candidate.source.retrieved_at > as_of:
        reasons.append("SOURCE_RETRIEVED_AFTER_AS_OF")
    if candidate.last_activity_at is None:
        reasons.append("MAINTENANCE_HISTORY_UNKNOWN")
    elif candidate.last_activity_at > as_of:
        reasons.append("LAST_ACTIVITY_IN_THE_FUTURE")
    elif as_of - candidate.last_activity_at > timedelta(days=policy.max_inactivity_days):
        reasons.append(f"INACTIVE_MORE_THAN_{policy.max_inactivity_days}_DAYS")
    if candidate.maintainer_count is None:
        reasons.append("MAINTAINER_COUNT_UNKNOWN")
    elif candidate.maintainer_count < policy.min_maintainers:
        reasons.append(f"FEWER_THAN_{policy.min_maintainers}_MAINTAINERS")
    return reasons


def _license_compliance(candidate: ScoutCandidate, policy: GatePolicy) -> list[str]:
    if candidate.license_spdx is None:
        return ["LICENSE_UNKNOWN"]
    if candidate.license_spdx not in policy.allowed_licenses:
        return [f"LICENSE_NOT_ALLOWED:{candidate.license_spdx}"]
    return []


def _security_risk(candidate: ScoutCandidate) -> list[str]:
    security = candidate.security
    reasons: list[str] = []
    for name, label in (
        ("network_access", "NETWORK_ACCESS"),
        ("subprocess_execution", "SUBPROCESS_EXECUTION"),
        ("dynamic_code_execution", "DYNAMIC_CODE_EXECUTION"),
        ("install_time_hooks", "INSTALL_TIME_HOOKS"),
    ):
        value = getattr(security, name)
        if value is None:
            reasons.append(f"{label}_NOT_ASSESSED")
        elif value:
            reasons.append(label)
    if security.known_vulnerabilities is None:
        reasons.append("VULNERABILITIES_NOT_ASSESSED")
    elif security.known_vulnerabilities > 0:
        reasons.append(f"KNOWN_VULNERABILITIES:{security.known_vulnerabilities}")
    return reasons


def _architectural_fit(candidate: ScoutCandidate, policy: GatePolicy) -> list[str]:
    reasons: list[str] = []
    if candidate.overlapping_components is None:
        reasons.append("OVERLAP_NOT_ASSESSED")
    elif candidate.overlapping_components:
        reasons.append("DUPLICATES:" + ",".join(sorted(candidate.overlapping_components)))
    if candidate.new_dependency_count is None:
        reasons.append("DEPENDENCIES_NOT_ASSESSED")
    elif candidate.new_dependency_count > policy.max_new_dependencies:
        reasons.append(f"NEW_DEPENDENCIES:{candidate.new_dependency_count}>{policy.max_new_dependencies}")
    return reasons


def _file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _log_safe(text: str) -> str:
    """Escape control and non-ASCII characters so external text can never start a log line."""
    return str(text).encode("unicode_escape").decode("ascii")


def _measurable_value(
    candidate: ScoutCandidate, registry: HypothesisRegistry | None, as_of: datetime
) -> tuple[list[str], dict[str, Any]]:
    """Only Atlas's own sealed, bound and adjudicated evidence counts (Tasks 005/006).

    Exact type checks, not isinstance: a look-alike or subclass registry that
    answers ``get`` with a fabricated record must not pass. The record is read
    from a fresh, read-only load of the registry file, never from the object's
    memory. Returns the failure reasons and the provenance the step relied on.
    """
    hypothesis_id = candidate.sealed_hypothesis_id
    evidence: dict[str, Any] = {"hypothesis_id": hypothesis_id,
                                "authenticity": "TAMPER_EVIDENT_NOT_AUTHENTICATED"}
    if hypothesis_id is None:
        return ["NO_SEALED_HYPOTHESIS"], evidence
    if type(registry) is not HypothesisRegistry:
        return ["NO_CANONICAL_REGISTRY"], evidence
    try:
        path = Path(registry.registry_path).resolve()
    except (OSError, ValueError, RuntimeError):  # review 25 L-1: an unusable path fails step 6, not the run
        return ["REGISTRY_FILE_UNREADABLE"], evidence
    evidence["registry_path"] = str(path)
    before = _file_digest(path)
    if before is None:
        return ["REGISTRY_FILE_UNREADABLE"], evidence
    try:
        on_disk = HypothesisRegistry(registry_path=path)
    except Exception as exc:  # noqa: BLE001 - reviews 22 L-2 / 24 F-1: fail closed, never a crash
        # Any failure to load the file (malformed JSON, an overflowing number, an invalid split, ...)
        # refuses step 6 for this candidate and names the exception type; it can never pass.
        return [f"REGISTRY_FILE_INVALID:{type(exc).__name__}"], evidence
    if _file_digest(path) != before:
        return ["REGISTRY_CHANGED_DURING_READ"], evidence
    evidence["registry_file_sha256"] = before
    if hypothesis_id not in on_disk:
        return [f"HYPOTHESIS_NOT_REGISTERED:{hypothesis_id}"], evidence
    record = on_disk.get(hypothesis_id)
    if type(record) is not HypothesisRecord:
        return [f"HYPOTHESIS_RECORD_INVALID:{hypothesis_id}"], evidence
    try:
        record.verify_seal()
        record.verify_state_chain()
        record.verify_recorded_checks()
    except RegistryError as exc:
        return [f"HYPOTHESIS_INTEGRITY_FAILED:{hypothesis_id}:{type(exc).__name__}"], evidence
    preregistration = record.preregistration
    checks_status = record.adjudicate_checks().status
    adjudicated_at = next((t.recorded_at for t in record.state_chain
                           if t.to_state is HypothesisState.CANDIDATE), None)
    evidence.update({
        "title": preregistration.title,
        "family_id": preregistration.family_id,
        "preregistration_hash": record.preregistration_hash,
        "state_chain_hash": record.state_chain_hash,
        "state": record.state.value,
        "checks_status": checks_status.value,
        "preregistered_at": preregistration.preregistered_at,
        "adjudicated_at": adjudicated_at,
    })
    reasons: list[str] = []
    binding = dict(preregistration.feature_spec)
    if (binding.get(BINDING_CANDIDATE_KEY) != candidate.candidate_id
            or binding.get(BINDING_SOURCE_URL_KEY) != candidate.source.url):
        reasons.append(f"HYPOTHESIS_NOT_BOUND_TO_CANDIDATE:{hypothesis_id}")
    if is_terminal(record.state) or progress_rank(record.state) < _ADJUDICATED_FLOOR:
        reasons.append(f"HYPOTHESIS_NOT_ADJUDICATED_PASS:{record.state.value}")
    if checks_status is not CheckPlanStatus.COMPLETE_PASS:
        reasons.append("HYPOTHESIS_CHECKS_NOT_COMPLETE_PASS")
    never_adjudicated = any(r.startswith("HYPOTHESIS_NOT_ADJUDICATED_PASS") for r in reasons)
    for label, stamp in (("PREREGISTERED", preregistration.preregistered_at), ("ADJUDICATED", adjudicated_at)):
        if stamp is None:
            # A hypothesis that never reached CANDIDATE has no adjudication time; it already fails.
            if not (label == "ADJUDICATED" and never_adjudicated):
                reasons.append(f"HYPOTHESIS_{label}_TIME_MISSING")
            continue
        try:
            if parse_utc(stamp, label) > as_of:
                reasons.append(f"HYPOTHESIS_{label}_AFTER_AS_OF")
        except ScoutInputError:
            reasons.append(f"HYPOTHESIS_{label}_TIME_INVALID")
    return reasons, evidence


#: Step-6 provenance a PENDING_OWNER_REVIEW finding must carry.
REQUIRED_VALUE_EVIDENCE = frozenset({
    "hypothesis_id", "authenticity", "registry_path", "registry_file_sha256", "title", "family_id",
    "preregistration_hash", "state_chain_hash", "state", "checks_status", "preregistered_at", "adjudicated_at",
})
_ADJUDICATED_STATES = frozenset(
    state.value for state in HypothesisState
    if not is_terminal(state) and progress_rank(state) >= _ADJUDICATED_FLOOR
)


def pending_problem(candidate: Any, gate: Any) -> str | None:
    """The policy-independent conditions of a PENDING_OWNER_REVIEW finding, on serialised records.

    Used when a finding is built and when a ledger is read, so a hand-built
    7/7 verdict around a candidate that could never pass is refused. ``None``
    means no problem was found.
    """
    if not isinstance(candidate, Mapping) or not isinstance(gate, Mapping):
        return "a pending finding needs a candidate and a gate verdict"
    steps = gate.get("steps")
    if not isinstance(steps, list) or len(steps) != REQUIRED_STEP_COUNT or not all(
        isinstance(step, Mapping) for step in steps
    ):
        return "the gate verdict does not hold seven steps"
    if [step.get("step") for step in steps] != [step.value for step in GATE_STEPS] or not all(
        step.get("passed") is True and not step.get("reasons") for step in steps
    ):
        return "the gate verdict is not a passing 7/7 in order"
    if gate.get("status") != GateStatus.PENDING_OWNER_REVIEW.value \
            or gate.get("passed_step_count") != REQUIRED_STEP_COUNT \
            or gate.get("required_step_count") != REQUIRED_STEP_COUNT \
            or gate.get("candidate_id") != candidate.get("candidate_id"):
        return "the gate verdict does not match the candidate"
    security = candidate.get("security")
    source = candidate.get("source")
    if not isinstance(security, Mapping) or not isinstance(source, Mapping):
        return "the candidate lacks security or source data"
    checks = (
        candidate.get("problem_ref") is not None,
        candidate.get("license_spdx") is not None,
        candidate.get("last_activity_at") is not None,
        isinstance(candidate.get("maintainer_count"), int) and candidate["maintainer_count"] >= 1,
        source.get("source_type") != SourceType.SOCIAL.value,
        all(security.get(flag) is False for flag in (
            "network_access", "subprocess_execution", "dynamic_code_execution", "install_time_hooks")),
        security.get("known_vulnerabilities") == 0 and type(security.get("known_vulnerabilities")) is int,
        candidate.get("overlapping_components") == [],
        isinstance(candidate.get("new_dependency_count"), int),
        candidate.get("removal_plan") is not None,
        candidate.get("requires_state_migration") is False,
    )
    if not all(checks):
        return "the candidate fails a policy-independent gate condition"
    evidence = steps[GATE_STEPS.index(GateStep.MEASURABLE_VALUE)].get("evidence")
    if not isinstance(evidence, Mapping) or not REQUIRED_VALUE_EVIDENCE <= set(evidence) \
            or any(evidence.get(key) in (None, "") for key in REQUIRED_VALUE_EVIDENCE):
        return "step 6 provenance is missing"
    if evidence.get("hypothesis_id") != candidate.get("sealed_hypothesis_id") \
            or evidence.get("state") not in _ADJUDICATED_STATES \
            or evidence.get("checks_status") != CheckPlanStatus.COMPLETE_PASS.value:
        return "step 6 provenance does not support the verdict"
    return None


def _reversibility(candidate: ScoutCandidate) -> list[str]:
    reasons: list[str] = []
    if candidate.removal_plan is None:
        reasons.append("REMOVAL_PLAN_MISSING")
    if candidate.requires_state_migration is None:
        reasons.append("STATE_MIGRATION_NOT_ASSESSED")
    elif candidate.requires_state_migration:
        reasons.append("REQUIRES_STATE_MIGRATION")
    return reasons


def evaluate_candidate(
    candidate: ScoutCandidate,
    *,
    as_of: datetime,
    verified_problems: Iterable[str],
    policy: GatePolicy | None = None,
    registry: HypothesisRegistry | None = None,
) -> GateVerdict:
    """Score ``candidate`` on all seven steps; never short-circuits, never accepts."""
    if not isinstance(candidate, ScoutCandidate):
        raise ScoutInputError("candidate must be a ScoutCandidate")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ScoutInputError("as_of must be a timezone-aware datetime")
    policy = policy or GatePolicy()
    if not isinstance(policy, GatePolicy):
        raise ScoutInputError("policy must be a GatePolicy")
    problems = text_set(verified_problems, "verified_problems")
    value_reasons, value_evidence = _measurable_value(candidate, registry, as_of)
    findings: Mapping[GateStep, list[str]] = {
        GateStep.REAL_PROBLEM_ALIGNMENT: _problem_alignment(candidate, problems),
        GateStep.SOURCE_RELIABILITY: _source_reliability(candidate, policy, as_of),
        GateStep.LICENSE_COMPLIANCE: _license_compliance(candidate, policy),
        GateStep.SECURITY_RISK: _security_risk(candidate),
        GateStep.ARCHITECTURAL_FIT: _architectural_fit(candidate, policy),
        GateStep.MEASURABLE_VALUE: value_reasons,
        GateStep.REVERSIBILITY: _reversibility(candidate),
    }
    # Iterate the fixed step list, not the findings: a step can never be skipped.
    steps = tuple(
        GateStepResult(step=step, passed=not findings[step], reasons=tuple(findings[step]),
                       evidence=value_evidence if step is GateStep.MEASURABLE_VALUE else {})
        for step in GATE_STEPS
    )
    all_passed = len(steps) == REQUIRED_STEP_COUNT and all(result.passed for result in steps)
    verdict = GateVerdict(
        candidate_id=candidate.candidate_id,
        steps=steps,
        status=GateStatus.PENDING_OWNER_REVIEW if all_passed else GateStatus.REJECTED,
    )
    if verdict.status is GateStatus.REJECTED:
        logger.warning(
            "scout gate REJECTED %s (%d/%d): %s",
            candidate.candidate_id,
            verdict.passed_step_count,
            REQUIRED_STEP_COUNT,
            # Control and non-ASCII characters external text could carry are escaped (no forged
            # log lines); plain reason text stays readable.
            "; ".join(f"{r.step.value}=" + ",".join(_log_safe(reason) for reason in r.reasons)
                      for r in verdict.failed_steps),
        )
    return verdict
