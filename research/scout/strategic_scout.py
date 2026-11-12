"""Strategic Scout: six research modes over external candidates (Task 011).

Owner decision 2026-10-11 (registry v5.95): the scout is **offline**. It makes
no network call, starts no subprocess and executes no external code. Findings
are gathered by a person or by the ``atlas-dashboard-scout`` agent (which can
only return text) and handed in as plain records; the scout structures,
gates and red-teams them. A URL in a record is stored, never fetched.

Modes (each with a fixed purpose and research questions, so the output
structure is deterministic):

* SEARCH -- a specific tool, library or algorithm for a stated need.
* HUNT -- proactive mining of repositories, papers and documentation; other
  source types are out of mode.
* COMPETITOR -- comparison against an existing Atlas component named in the
  request context (``atlas_component``).
* COST -- cheaper or open-source alternatives, against the current monthly
  cost in the request context (``current_monthly_cost_usd``). A candidate of
  unknown cost is flagged.
* RED_TEAM -- adversarial failure-mode analysis. Every failure mode found is
  blocking.
* EMERGENCY -- root-cause research for an incident (``incident_ref``). It has
  no fast path: the same gate applies, and the scout has no remediation
  authority.

A mode can add blocking flags but never remove a gate failure, so no mode is
more permissive than the gate.

**Memory firewall.** Every report, finding and assessment is tagged
``EXPLORATORY`` with ``evidence_eligible: false`` and authority ``NONE``. The
scout reads the hypothesis registry (gate step 6) and never writes to it, to
runtime state, or to any rule or parameter. The only thing it can persist is
its own append-only ``ScoutLedger`` at a path the caller names explicitly.

This module imports nothing outside ``research/`` and the standard library
(ADR-0009); its only I/O is ``ScoutLedger``.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from research.hypothesis_registry import HypothesisRegistry
from research.registry_lock import registry_write_lock
from research.scout.acceptance_gate import (
    GatePolicy,
    GateStatus,
    GateStep,
    GateVerdict,
    ScoutCandidate,
    evaluate_candidate,
    pending_problem,
)
from research.scout.provenance import (
    AUTHORITY_NONE,
    EXPLORATORY,
    ScoutInputError,
    SourceType,
    canonical_json,
    clean_text,
    finite_amount,
    parse_utc,
    record_digest,
    sha256_hex,
    text_set,
)
from research.scout.trader_reputation import (
    NEXT_STEP,
    ClaimType,
    DimensionVerdict,
    ReputationPolicy,
    ReputationRating,
    TraderAssessment,
    TraderClaim,
    assess_claim,
)

REPORT_SCHEMA_VERSION = "1"


class ScoutMode(str, Enum):
    SEARCH = "SEARCH"
    HUNT = "HUNT"
    COMPETITOR = "COMPETITOR"
    COST = "COST"
    RED_TEAM = "RED_TEAM"
    EMERGENCY = "EMERGENCY"


@dataclass(frozen=True)
class ModeSpec:
    mode: ScoutMode
    purpose: str
    research_questions: tuple[str, ...]
    required_context: tuple[str, ...] = ()
    allowed_source_types: frozenset[SourceType] | None = None


MODE_SPECS: Mapping[ScoutMode, ModeSpec] = MappingProxyType({
    ScoutMode.SEARCH: ModeSpec(
        mode=ScoutMode.SEARCH,
        purpose="Find a specific tool, library or quantitative algorithm for a verified Atlas need.",
        research_questions=(
            "Which verified Atlas problem does this need come from?",
            "Which candidates address it without duplicating an existing component?",
            "What sealed Atlas hypothesis would show the candidate adds measurable value?",
        ),
    ),
    ScoutMode.HUNT: ModeSpec(
        mode=ScoutMode.HUNT,
        purpose="Proactively mine repositories, academic papers and documentation.",
        research_questions=(
            "Which primary sources (repositories, papers, documentation) bear on an open Atlas problem?",
            "Is each source maintained, licensed and reviewable?",
            "Which ideas are worth a pre-registered hypothesis (Task 005)?",
        ),
        allowed_source_types=frozenset({
            SourceType.REPOSITORY, SourceType.PAPER, SourceType.DOCUMENTATION, SourceType.PACKAGE_INDEX,
        }),
    ),
    ScoutMode.COMPETITOR: ModeSpec(
        mode=ScoutMode.COMPETITOR,
        purpose="Compare open-source trading-system architectures against an existing Atlas component.",
        research_questions=(
            "How does each system solve what the named Atlas component solves?",
            "Where would adopting it duplicate the Atlas component?",
            "Which differences are worth a pre-registered comparison?",
        ),
        required_context=("atlas_component",),
    ),
    ScoutMode.COST: ModeSpec(
        mode=ScoutMode.COST,
        purpose="Evaluate low-cost and open-source alternatives against the current monthly cost.",
        research_questions=(
            "What does each alternative cost per month, and is that cost verified?",
            "Does the cheaper option still pass every acceptance step?",
            "What does switching cost in migration and reversibility?",
        ),
        required_context=("current_monthly_cost_usd",),
    ),
    ScoutMode.RED_TEAM: ModeSpec(
        mode=ScoutMode.RED_TEAM,
        purpose="Adversarial vulnerability and failure-mode analysis of proposed candidates.",
        research_questions=(
            "How could this candidate leak data, execute code or reach the network?",
            "Which of its claims are unverified, and what if they are false?",
            "What breaks, and what state is left behind, if it must be removed?",
        ),
    ),
    ScoutMode.EMERGENCY: ModeSpec(
        mode=ScoutMode.EMERGENCY,
        purpose="Root-cause research during a critical fault. Research only: no fast path, no remediation authority.",
        research_questions=(
            "What is the root cause of the referenced incident?",
            "Which known external issues or fixes match its symptoms?",
            "Which fix must then go through the normal Atlas workflow and this gate?",
        ),
        required_context=("incident_ref",),
    ),
})


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _validate_context(mode: ScoutMode, context: Mapping[str, Any]) -> dict[str, Any]:
    spec = MODE_SPECS[mode]
    unknown = sorted(str(key) for key in context if key not in spec.required_context)
    if unknown:
        raise ScoutInputError(f"{mode.value} context has unknown key(s) {unknown}")
    clean: dict[str, Any] = {}
    for key in spec.required_context:
        value = context.get(key)
        if key == "current_monthly_cost_usd":
            clean[key] = finite_amount(value, key)
        else:
            clean[key] = clean_text(value, key, single_line=True)
    return clean


@dataclass(frozen=True)
class ScoutRequest:
    mode: ScoutMode
    query: str
    as_of: datetime
    candidates: tuple[Any, ...] = ()
    trader_claims: tuple[Any, ...] = ()
    context: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        try:
            mode = ScoutMode(self.mode)
        except ValueError as exc:
            raise ScoutInputError(f"mode must be one of {[m.value for m in ScoutMode]}") from exc
        query = clean_text(self.query, "query")
        for name in ("candidates", "trader_claims"):
            value = getattr(self, name)
            if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
                raise ScoutInputError(f"{name} must be a list of records")
        if not isinstance(self.context, Mapping):
            raise ScoutInputError("context must be a mapping")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "as_of", parse_utc(self.as_of, "as_of"))
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "trader_claims", tuple(self.trader_claims))
        object.__setattr__(self, "context", MappingProxyType(_validate_context(mode, self.context)))


@dataclass(frozen=True)
class ScoutFinding:
    """One candidate's outcome. Always EXPLORATORY; never evidence."""

    candidate_id: str
    status: GateStatus
    candidate: ScoutCandidate | None
    gate: GateVerdict | None
    mode_flags: tuple[str, ...]
    input_errors: tuple[str, ...]
    epistemic_status: str = EXPLORATORY
    evidence_eligible: bool = False

    def __post_init__(self) -> None:
        # Firewall tags are invariants, and PENDING_OWNER_REVIEW is reachable only through a 7/7 gate verdict.
        if self.epistemic_status != EXPLORATORY or self.evidence_eligible is not False:
            raise ValueError("a scout finding is always EXPLORATORY and never evidence")
        if not isinstance(self.status, GateStatus):
            raise ValueError("status must be a GateStatus")
        if self.status is GateStatus.PENDING_OWNER_REVIEW:
            if (not isinstance(self.candidate, ScoutCandidate) or not isinstance(self.gate, GateVerdict)
                    or self.candidate.candidate_id != self.candidate_id or self.mode_flags or self.input_errors):
                raise ValueError("PENDING_OWNER_REVIEW requires a candidate with a passing gate verdict and no flags")
            problem = pending_problem(self.candidate.as_dict(), self.gate.as_dict())
            if problem is not None:
                raise ValueError(f"PENDING_OWNER_REVIEW refused: {problem}")
        object.__setattr__(self, "mode_flags", tuple(self.mode_flags))
        object.__setattr__(self, "input_errors", tuple(self.input_errors))

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status.value,
            "candidate": None if self.candidate is None else self.candidate.as_dict(),
            "gate": None if self.gate is None else self.gate.as_dict(),
            "mode_flags": list(self.mode_flags),
            "input_errors": list(self.input_errors),
            "epistemic_status": self.epistemic_status,
            "evidence_eligible": self.evidence_eligible,
        }


@dataclass(frozen=True)
class ScoutReport:
    mode: ScoutMode
    query: str
    as_of: datetime
    purpose: str
    research_questions: tuple[str, ...]
    context: Mapping[str, Any]
    findings: tuple[ScoutFinding, ...]
    trader_assessments: tuple[TraderAssessment, ...]
    trader_claim_errors: tuple[Mapping[str, Any], ...]
    mode_analysis: Mapping[str, Any]
    epistemic_status: str = EXPLORATORY
    evidence_eligible: bool = False
    authority: str = AUTHORITY_NONE
    production_effect: str = AUTHORITY_NONE
    live_effect: str = AUTHORITY_NONE
    registry_writes: str = AUTHORITY_NONE

    def __post_init__(self) -> None:
        if (self.epistemic_status, self.evidence_eligible) != (EXPLORATORY, False) or any(
            value != AUTHORITY_NONE
            for value in (self.authority, self.production_effect, self.live_effect, self.registry_writes)
        ):
            raise ValueError("a scout report is always EXPLORATORY and carries no authority")
        if not all(isinstance(f, ScoutFinding) for f in self.findings):
            raise ValueError("findings must be ScoutFinding records")
        if not all(isinstance(a, TraderAssessment) for a in self.trader_assessments):
            raise ValueError("trader_assessments must be TraderAssessment records")
        for finding in self.findings:
            if finding.status is GateStatus.PENDING_OWNER_REVIEW:
                problem = _timing_problem(self.as_of, finding.gate.as_dict())
                if problem is not None:
                    raise ValueError(f"PENDING_OWNER_REVIEW refused: {problem}")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "mode": self.mode.value,
            "query": self.query,
            "as_of": self.as_of.isoformat(),
            "purpose": self.purpose,
            "research_questions": list(self.research_questions),
            "context": dict(self.context),
            "findings": [finding.as_dict() for finding in self.findings],
            "trader_assessments": [assessment.as_dict() for assessment in self.trader_assessments],
            "trader_claim_errors": [dict(error) for error in self.trader_claim_errors],
            "mode_analysis": _thaw(self.mode_analysis),
            "epistemic_status": self.epistemic_status,
            "evidence_eligible": self.evidence_eligible,
            "authority": self.authority,
            "production_effect": self.production_effect,
            "live_effect": self.live_effect,
            "registry_writes": self.registry_writes,
        }

    @property
    def report_id(self) -> str:
        return sha256_hex(self._body())

    def to_dict(self) -> dict[str, Any]:
        body = self._body()
        body["report_id"] = sha256_hex(body)
        return body


def _finding_order_key(finding: ScoutFinding) -> str:
    try:
        return sha256_hex(finding.as_dict())
    except (TypeError, ValueError, RecursionError):
        return repr(finding.input_errors)


def _input_error(exc: Exception) -> str:
    return "RECORD_NESTED_TOO_DEEPLY" if isinstance(exc, RecursionError) else str(exc)


def _timing_problem(as_of: datetime, gate: Mapping[str, Any]) -> str | None:
    """No lookahead: step-6 evidence must predate the report's as_of."""
    evidence = gate["steps"][5].get("evidence") or {}
    for key in ("preregistered_at", "adjudicated_at"):
        try:
            if parse_utc(evidence.get(key), key) > as_of:
                return f"step 6 evidence {key} is after as_of"
        except ScoutInputError:
            return f"step 6 evidence {key} is not a timestamp"
    return None


def _red_team_failure_modes(candidate: ScoutCandidate, gate: GateVerdict) -> list[str]:
    security = candidate.security
    modes: list[str] = []
    if candidate.claimed_benchmarks:
        # External claims stay unverified whatever step 6 found; the red team always surfaces them.
        modes.append("UNVERIFIED_BENCHMARK_CLAIMS")
    if candidate.maintainer_count is None or candidate.maintainer_count <= 1:
        modes.append("SINGLE_POINT_OF_MAINTENANCE")
    flags = (security.network_access, security.subprocess_execution,
             security.dynamic_code_execution, security.install_time_hooks)
    if any(flag is None for flag in flags) or security.known_vulnerabilities is None:
        modes.append("SECURITY_NOT_FULLY_ASSESSED")
    if any(flag is True for flag in flags):
        modes.append("EXECUTES_CODE_OR_REACHES_NETWORK")
    if security.known_vulnerabilities:
        modes.append("KNOWN_VULNERABILITIES")
    if candidate.requires_state_migration is not False:
        modes.append("STATE_MIGRATION_RISK")
    if candidate.removal_plan is None:
        modes.append("NO_REMOVAL_PATH")
    if candidate.source.source_type in (SourceType.SOCIAL, SourceType.ARTICLE):
        modes.append("SECONDARY_OR_SOCIAL_SOURCE")
    if not gate.result_for(GateStep.LICENSE_COMPLIANCE).passed:
        modes.append("LICENSE_RISK")
    if candidate.kind.value == "PROMPT_SKILL":
        modes.append("PROMPT_INJECTION_SURFACE")
    return modes


def _ranking(findings: Sequence[ScoutFinding]) -> list[str]:
    def key(finding: ScoutFinding) -> tuple[int, int, str]:
        passed = 0 if finding.gate is None else finding.gate.passed_step_count
        return (0 if finding.status is GateStatus.PENDING_OWNER_REVIEW else 1, -passed, finding.candidate_id)
    return [finding.candidate_id for finding in sorted(findings, key=key)]


class StrategicScout:
    """Offline research engine. Reads; never writes registry, runtime or rules."""

    def __init__(
        self,
        *,
        verified_problems: Iterable[str],
        gate_policy: GatePolicy | None = None,
        reputation_policy: ReputationPolicy | None = None,
        registry: HypothesisRegistry | None = None,
    ) -> None:
        self._verified_problems = text_set(verified_problems, "verified_problems")
        self._gate_policy = gate_policy or GatePolicy()
        self._reputation_policy = reputation_policy or ReputationPolicy()
        self._registry = registry

    def run(self, request: ScoutRequest) -> ScoutReport:
        if not isinstance(request, ScoutRequest):
            raise ScoutInputError("request must be a ScoutRequest")
        spec = MODE_SPECS[request.mode]
        findings = self._findings(request, spec)
        claims: list[tuple[TraderClaim, Any]] = []
        claim_errors: list[dict[str, Any]] = []
        for payload in request.trader_claims:
            try:
                claims.append((TraderClaim.from_dict(payload), payload))
            except (ScoutInputError, RecursionError) as exc:  # review 22 L-2: refused per record
                claim_errors.append({"record_sha256": record_digest(payload), "error": _input_error(exc)})
        claim_counts: dict[str, int] = {}
        for claim, _ in claims:
            claim_counts[claim.claim_id] = claim_counts.get(claim.claim_id, 0) + 1
        assessments: list[TraderAssessment] = []
        for claim, payload in claims:
            if claim_counts[claim.claim_id] > 1:
                # Like candidates: every copy is refused, so one record cannot shadow another.
                claim_errors.append({"record_sha256": record_digest(payload),
                                     "error": f"DUPLICATE_CLAIM_ID:{claim.claim_id}"})
                continue
            assessments.append(assess_claim(claim, as_of=request.as_of, policy=self._reputation_policy))
        assessments.sort(key=lambda a: (a.trader_id, a.claim_id))
        claim_errors.sort(key=lambda e: (e["record_sha256"], e["error"]))
        return ScoutReport(
            mode=request.mode,
            query=request.query,
            as_of=request.as_of,
            purpose=spec.purpose,
            research_questions=spec.research_questions,
            context=request.context,
            findings=findings,
            trader_assessments=tuple(assessments),
            trader_claim_errors=tuple(MappingProxyType(error) for error in claim_errors),
            mode_analysis=_freeze(self._mode_analysis(request, findings)),
        )

    def _findings(self, request: ScoutRequest, spec: ModeSpec) -> tuple[ScoutFinding, ...]:
        # Keyed by content digest, not input position, so the report does not depend on input order.
        parsed: list[tuple[str, str, ScoutCandidate | None, str | None]] = []
        for payload in request.candidates:
            digest = record_digest(payload)
            try:
                candidate = ScoutCandidate.from_dict(payload)
            except (ScoutInputError, RecursionError) as exc:  # review 22 L-2: refused per record
                parsed.append((digest, f"<malformed:{digest[:16]}>", None, _input_error(exc)))
            else:
                parsed.append((digest, candidate.candidate_id, candidate, None))
        id_counts: dict[str, int] = {}
        for _, candidate_id, candidate, _ in parsed:
            if candidate is not None:
                id_counts[candidate_id] = id_counts.get(candidate_id, 0) + 1

        findings: list[tuple[str, str, ScoutFinding]] = []
        for digest, candidate_id, candidate, error in parsed:
            if candidate is None:
                finding = ScoutFinding(candidate_id, GateStatus.REJECTED, None, None, (), (f"MALFORMED_CANDIDATE: {error}",))
            elif id_counts[candidate_id] > 1:
                # Every copy is refused: a later record must not shadow, or be shadowed by, another.
                finding = ScoutFinding(candidate_id, GateStatus.REJECTED, candidate, None, (), ("DUPLICATE_CANDIDATE_ID",))
            else:
                gate = evaluate_candidate(
                    candidate,
                    as_of=request.as_of,
                    verified_problems=self._verified_problems,
                    policy=self._gate_policy,
                    registry=self._registry,
                )
                flags = self._mode_flags(request, spec, candidate, gate)
                blocked = gate.status is GateStatus.REJECTED or bool(flags)
                finding = ScoutFinding(
                    candidate_id,
                    GateStatus.REJECTED if blocked else GateStatus.PENDING_OWNER_REVIEW,
                    candidate,
                    gate,
                    tuple(flags),
                    (),
                )
            findings.append((candidate_id, digest, finding))
        # Reviews 23 L-4 / 24 F-2: unserialisable records share a fallback digest, so the finding's own
        # serialised content breaks the tie; findings that still tie serialise identically.
        findings.sort(key=lambda item: (item[0], item[1], _finding_order_key(item[2])))
        return tuple(finding for _, _, finding in findings)

    @staticmethod
    def _mode_flags(request: ScoutRequest, spec: ModeSpec, candidate: ScoutCandidate, gate: GateVerdict) -> list[str]:
        flags: list[str] = []
        if spec.allowed_source_types is not None and candidate.source.source_type not in spec.allowed_source_types:
            flags.append(f"SOURCE_TYPE_OUT_OF_MODE:{candidate.source.source_type.value}")
        if request.mode is ScoutMode.COST and candidate.monthly_cost_usd is None:
            flags.append("COST_UNKNOWN")
        if request.mode is ScoutMode.RED_TEAM:
            flags.extend(f"RED_TEAM:{mode}" for mode in _red_team_failure_modes(candidate, gate))
        return flags

    @staticmethod
    def _mode_analysis(request: ScoutRequest, findings: Sequence[ScoutFinding]) -> dict[str, Any]:
        evaluated = [f for f in findings if f.candidate is not None and f.gate is not None]
        analysis: dict[str, Any] = {
            "ranking": _ranking(findings),
            "pending_owner_review": sorted(
                f.candidate_id for f in findings if f.status is GateStatus.PENDING_OWNER_REVIEW
            ),
        }
        mode = request.mode
        if mode is ScoutMode.HUNT:
            counts: dict[str, int] = {}
            for finding in evaluated:
                source_type = finding.candidate.source.source_type.value
                counts[source_type] = counts.get(source_type, 0) + 1
            analysis["by_source_type"] = dict(sorted(counts.items()))
        elif mode is ScoutMode.COMPETITOR:
            component = request.context["atlas_component"]
            analysis["atlas_component"] = component
            analysis["comparison"] = [
                {
                    "candidate_id": f.candidate_id,
                    "overlaps_atlas_component": (
                        None if f.candidate.overlapping_components is None
                        else component in f.candidate.overlapping_components
                    ),
                    "score": f"{f.gate.passed_step_count}/{f.gate.required_step_count}",
                    "failed_steps": [r.step.value for r in f.gate.failed_steps],
                }
                for f in evaluated
            ]
        elif mode is ScoutMode.COST:
            current = request.context["current_monthly_cost_usd"]
            analysis["current_monthly_cost_usd"] = current
            analysis["cost_comparison"] = [
                {
                    "candidate_id": f.candidate_id,
                    "monthly_cost_usd": f.candidate.monthly_cost_usd,
                    "delta_usd": None if f.candidate.monthly_cost_usd is None
                    else round(f.candidate.monthly_cost_usd - current, 6),
                    "cheaper": None if f.candidate.monthly_cost_usd is None
                    else f.candidate.monthly_cost_usd < current,
                }
                for f in evaluated
            ]
        elif mode is ScoutMode.RED_TEAM:
            analysis["failure_modes"] = {
                f.candidate_id: [flag.split(":", 1)[1] for flag in f.mode_flags if flag.startswith("RED_TEAM:")]
                for f in evaluated
            }
        elif mode is ScoutMode.EMERGENCY:
            analysis["incident_ref"] = request.context["incident_ref"]
            analysis["remediation_authority"] = AUTHORITY_NONE
            analysis["fast_path"] = False
            analysis["note"] = (
                "Findings feed root-cause analysis only. Any fix goes through the normal Atlas "
                "workflow and this same gate; an emergency relaxes nothing."
            )
        return analysis


class ScoutLedgerError(Exception):
    """The ledger is malformed or its hash chain is broken: halt, never continue."""


_GENESIS = "0" * 64
_ENTRY_KEYS = frozenset({"seq", "prev_sha256", "report", "entry_sha256"})
_REPORT_TAGS = {"epistemic_status": EXPLORATORY, "evidence_eligible": False, "authority": AUTHORITY_NONE,
                "production_effect": AUTHORITY_NONE, "live_effect": AUTHORITY_NONE,
                "registry_writes": AUTHORITY_NONE}
#: Runtime-state roots (core/application.py names them; research/ may not import it, ADR-0009).
_RUNTIME_ROOT_ENV = ("ATLAS_STATE_DIRECTORY", "ATLAS_EVIDENCE_DIRECTORY",
                     "ATLAS_MARKET_ARCHIVE_DIRECTORY", "ATLAS_LOG_DIRECTORY")
#: core/application.py's installation-anchored defaults for the same roots.
_INSTALLATION_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_RUNTIME_ROOTS = (
    _INSTALLATION_ROOT / "memory_data",
    _INSTALLATION_ROOT / "data" / "market_archive",
    _INSTALLATION_ROOT / "evidence_store",
)


def _report_problem(report: Any) -> str | None:
    """The one validation applied on both write and read; ``None`` when the report is acceptable."""
    if not isinstance(report, dict):
        return "the report is not an object"
    for key, expected in _REPORT_TAGS.items():
        if report.get(key) != expected or type(report.get(key)) is not type(expected):
            return f"report tag {key} is not {expected!r}"
    body = {key: value for key, value in report.items() if key != "report_id"}
    if report.get("report_id") != sha256_hex(body):
        return "report_id does not match the report"
    findings = report.get("findings")
    assessments = report.get("trader_assessments")
    if not isinstance(findings, list) or not isinstance(assessments, list):
        return "findings or trader_assessments missing"
    for finding in findings:
        if not isinstance(finding, dict) or finding.get("epistemic_status") != EXPLORATORY \
                or finding.get("evidence_eligible") is not False:
            return "a finding is not EXPLORATORY"
        if finding.get("status") == GateStatus.PENDING_OWNER_REVIEW.value:
            if finding.get("mode_flags") or finding.get("input_errors"):
                return "a PENDING_OWNER_REVIEW finding carries flags or errors"
            candidate = finding.get("candidate")
            if not isinstance(candidate, dict) or candidate.get("candidate_id") != finding.get("candidate_id"):
                return "a PENDING_OWNER_REVIEW finding lacks its candidate"
            problem = pending_problem(candidate, finding.get("gate"))
            if problem is None:
                try:
                    problem = _timing_problem(parse_utc(report.get("as_of"), "as_of"), finding["gate"])
                except ScoutInputError:
                    problem = "the report as_of is not a timestamp"
            if problem is not None:
                return f"PENDING_OWNER_REVIEW refused: {problem}"
        elif finding.get("status") != GateStatus.REJECTED.value:
            return "a finding has an unknown status"
    for assessment in assessments:
        if not isinstance(assessment, dict) or assessment.get("epistemic_status") != EXPLORATORY \
                or assessment.get("signal_authority") != AUTHORITY_NONE or assessment.get("next_step") != NEXT_STEP:
            return "a trader assessment carries authority"
        rating = assessment.get("rating")
        if rating not in {r.value for r in ReputationRating}:
            return "a trader assessment has an unknown rating"
        if rating == ReputationRating.RESEARCH_CANDIDATE.value:
            dimensions = assessment.get("dimensions")
            source = assessment.get("source")
            if (
                assessment.get("claim_type") != ClaimType.LIVE_TRACK_RECORD.value
                or not isinstance(source, dict) or source.get("source_type") == SourceType.SOCIAL.value
                or not isinstance(dimensions, list) or len(dimensions) != 4
                or not all(isinstance(d, dict) and d.get("verdict") == DimensionVerdict.PASS.value for d in dimensions)
            ):
                return "a RESEARCH_CANDIDATE assessment does not follow from its claim"
    return None


def _refuse_constant(name: str) -> Any:
    raise ValueError(f"non-finite number {name}")


def _ledger_line(entry: Mapping[str, Any]) -> str:
    """ASCII-only, so no character inside external text can split the line (U+2028, U+2029, U+0085)."""
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


class ScoutLedger:
    """Append-only, hash-chained JSONL record of scout reports (the research sandbox).

    The path is required and has no default (like ``HypothesisRegistry``). It
    must end in ``.jsonl`` -- so it can never be the canonical ``hypotheses.json``
    -- and must not lie under ``memory_data/`` or a runtime root named by
    ``ATLAS_STATE_DIRECTORY`` / ``ATLAS_EVIDENCE_DIRECTORY`` /
    ``ATLAS_MARKET_ARCHIVE_DIRECTORY`` / ``ATLAS_LOG_DIRECTORY``; a symlinked or
    hard-linked file is refused. Appends take the research sidecar lock and
    verify the whole chain first; a report is validated identically before it is
    written and when it is read back.

    The chain detects an edited, reordered or removed interior line and a partial
    last line. It cannot by itself detect lost *trailing* entries or a complete
    rewrite with recomputed hashes: a caller who keeps the hash ``append``
    returns can pass it as ``anchor`` to ``entries`` to detect both.
    """

    def __init__(self, path: str | Path) -> None:
        if path is None or (isinstance(path, str) and not path.strip()):
            raise ScoutLedgerError("a ledger path is required")
        given = Path(path)
        if given.is_symlink():
            raise ScoutLedgerError("the scout ledger must not be a symlink")
        resolved = given.resolve()
        if resolved.suffix != ".jsonl":
            raise ScoutLedgerError("the scout ledger must be a .jsonl file")
        if "memory_data" in resolved.parts:
            raise ScoutLedgerError("the scout ledger must not live under runtime state (memory_data/)")
        for root in _DEFAULT_RUNTIME_ROOTS:
            if resolved.is_relative_to(root):
                raise ScoutLedgerError(f"the scout ledger must not live under the runtime root {root.name}")
        for variable in _RUNTIME_ROOT_ENV:
            root = os.environ.get(variable, "").strip()
            if root and resolved.is_relative_to(Path(root).expanduser().resolve()):
                raise ScoutLedgerError(f"the scout ledger must not live under runtime root {variable}")
        if resolved.exists() and resolved.stat().st_nlink > 1:
            raise ScoutLedgerError("the scout ledger must not be hard-linked")
        self.path = resolved

    def entries(self, *, anchor: str | None = None) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            if anchor is not None:
                raise ScoutLedgerError("the anchored entry is missing: the ledger is gone")
            return ()
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ScoutLedgerError(f"cannot read scout ledger {self.path}: {exc}") from exc
        if raw and not raw.endswith("\n"):
            raise ScoutLedgerError(f"scout ledger {self.path} ends in a partial line")
        entries: list[dict[str, Any]] = []
        previous = _GENESIS
        # Split on "\n" only: str.splitlines() would also split on characters JSON leaves unescaped.
        for number, line in enumerate(raw.split("\n")[:-1] if raw else []):
            try:
                entry = json.loads(line, parse_constant=_refuse_constant)
                if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
                    raise ScoutLedgerError(f"line {number + 1} has an unexpected shape")
                if entry["seq"] != number or entry["prev_sha256"] != previous:
                    raise ScoutLedgerError(f"line {number + 1} breaks the sequence or hash chain")
                body = {key: entry[key] for key in ("seq", "prev_sha256", "report")}
                if sha256_hex(body) != entry["entry_sha256"]:
                    raise ScoutLedgerError(f"line {number + 1} does not match its hash")
                problem = _report_problem(entry["report"])
            except ScoutLedgerError:
                raise
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, RecursionError) as exc:
                # Malformed content of any kind halts the read with the ledger's own error.
                raise ScoutLedgerError(f"line {number + 1} is malformed: {type(exc).__name__}") from exc
            if problem is not None:
                raise ScoutLedgerError(f"line {number + 1}: {problem}")
            entries.append(entry)
            previous = entry["entry_sha256"]
        if anchor is not None and anchor not in {entry["entry_sha256"] for entry in entries}:
            raise ScoutLedgerError("the anchored entry is missing: the ledger was truncated or rewritten")
        return tuple(entries)

    def append(self, report: ScoutReport) -> str:
        if not isinstance(report, ScoutReport):
            raise ScoutLedgerError("only a ScoutReport can be recorded")
        try:
            payload = report.to_dict()
            problem = _report_problem(payload)
        except (ValueError, TypeError, UnicodeError, KeyError, IndexError, RecursionError) as exc:
            raise ScoutLedgerError(f"refusing to record: the report cannot be serialised ({type(exc).__name__})") from exc
        if problem is not None:
            raise ScoutLedgerError(f"refusing to record: {problem}")
        with registry_write_lock(self.path):
            existing = self.entries()
            body = {
                "seq": len(existing),
                "prev_sha256": existing[-1]["entry_sha256"] if existing else _GENESIS,
                "report": payload,
            }
            entry = dict(body, entry_sha256=sha256_hex(body))
            line = _ledger_line(entry)
            if "\n" in line or json.loads(line) != entry:
                raise ScoutLedgerError("refusing to record: the entry does not round-trip")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Re-checked at write time, inside the lock: never follow a symlink or write a hard-linked file.
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(self.path, flags, 0o644)
            except OSError as exc:
                raise ScoutLedgerError(f"cannot open scout ledger {self.path} safely: {exc}") from exc
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ScoutLedgerError("the scout ledger must be a regular, unlinked file")
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return entry["entry_sha256"]
