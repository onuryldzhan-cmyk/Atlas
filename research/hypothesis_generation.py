"""Hypothesis generation and screening pipeline (Task 005, research only).

GRANT-TASK-005-HYPOTHESIS-GENERATION-SCREENING-RESEARCH-ONLY (registry v5.88).
Its output is research evidence for the owner, never trading authority; this
module imports nothing outside ``research/`` (ADR-0009) and no runtime module
imports it.

**Generate.** A ``Template`` sweeps a grid of existing replay knobs
(``KNOBS``: e.g. ``regime_filter``, ``atr_stop`` as an ATR multiple -- a
volatility-normalized stop --, ``risk_per_trade``, ``trend_ema_hours``,
``cost_gate``) on top of fixed base arguments. Each grid point is one
candidate: "this variant beats the reference". Its study specification seals
the exact arguments of the variant and of the reference plus their digest
(``study_spec``), so a registered run executes exactly what was registered
(closes residual R5-2 for generated studies).

**Deduplicate.** A candidate's idea fingerprint covers what it trades and
how (universe, timeframe, EXP-001 floor, the reference's and the variant's
sealed arguments), not its name, window or evaluation settings
(``idea_fingerprint``). A candidate whose fingerprint matches a hypothesis
already in the registry is EXISTING ("zaten hafizada") and is not registered
again; two identical ideas in one template are DUPLICATE.

**Screen.** Fresh candidates are screened on historical data that ends
before the registration (``research.screening``; owner decision 2026-10-09).
The data stages run once per universe; the trade-count stage runs per
candidate through an injected quick exploratory replay. A candidate whose
screening crashes is FAILED and the others continue: nothing is marked, so
the next generation run can produce it again.

**Register.** Survivors are registered, one hypothesis per survivor and
sealed period, as ONE family in the given registry (the canonical registry is
chosen by the caller, tools/hypothesis_pipeline.py). Registration happens
under an exclusive write lock on a registry re-read from disk
(``research.registry_lock``), so a concurrent writer's records are never
lost; deduplication is re-checked and the sealed windows are re-checked
against the real clock there. Every sealed window lies wholly after the
registration, lasts exactly the sealed days and starts on a whole minute. The
family's plan (``lineage``: the template and exactly which idea x period
pairs it registers) and size ``m`` are sealed into every member. All
pre-registrations are built and validated before the first write; a failure
while writing stops and is reported, and re-running the same plan resumes the
same family. A different plan for an existing family is refused.

**Multiple testing.** The family is adjudicated by the registry's existing
Benjamini-Hochberg path (``HypothesisRegistry.adjudicate_family``) over every
member, with ``q`` = the template's alpha. With ``correction="BONFERRONI"``
each member is also pre-registered at ``alpha / m`` (family-wise error), which
``adjudicate_family`` enforces as a further gate. The method, ``m`` and the
screening counts are sealed into every member (``feature_spec["generation"]``).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from research.hypothesis_registry import (
    CheckName,
    CheckPlan,
    HypothesisRegistry,
    PreRegistration,
    RegistryError,
)
from research.screening import ScreeningSpec, StageResult, passed, screen_data, screen_trades
from research.splitting import SplitSpec

STUDY_SPEC_KEY = "strategy_compare"
GENERATION_KEY = "generation"
MINUTE_MS = 60_000

#: The replay knobs a template may sweep, with their type ("bool", "int" or "decimal") and lower bound.
#: Exactly the knobs the owner's design decision names (registry v5.88: regime_filter, atr_stop,
#: risk_per_trade, trend_ema_hours, cost_gate) plus the two fill knobs the reference needs.
KNOBS: Mapping[str, tuple[str, Any]] = {
    "slippage_bps": ("int", 0),
    "next_open_fill": ("bool", None),
    "trend_ema_hours": ("int", 0),
    "atr_stop": ("decimal", Decimal("0")),
    "risk_per_trade": ("decimal", Decimal("0")),
    "cost_gate": ("decimal", Decimal("0")),
    "regime_filter": ("bool", None),
}
#: tools.backtest_replay.replay's own defaults (pinned by a test). A knob set to its default is
#: dropped when arguments are normalized, so writing a default out does not make a new idea.
KNOB_DEFAULTS: Mapping[str, Any] = {
    "slippage_bps": 0, "next_open_fill": False, "trend_ema_hours": 0, "atr_stop": "0", "risk_per_trade": "0",
    "cost_gate": "0", "regime_filter": False,
}
#: The fill knobs: every generated variant fills exactly like its reference (Task 005 review N-1).
FILL_KNOBS = ("slippage_bps", "next_open_fill")
CORRECTIONS = ("BH", "BONFERRONI")


class GenerationError(ValueError):
    """The template or the generation request is malformed; nothing was registered."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def normalize_args(args: Mapping[str, Any]) -> dict[str, Any]:
    """Validated, JSON-canonical replay arguments: bools, ints and decimals as normalized strings."""
    if not isinstance(args, Mapping):
        raise GenerationError(f"arguments must be a mapping, got {args!r:.80}")
    out: dict[str, Any] = {}
    for key, value in args.items():
        if key not in KNOBS:
            raise GenerationError(f"unknown replay argument {key!r}; allowed: {sorted(KNOBS)}")
        kind, low = KNOBS[key]
        if kind == "bool":
            if not isinstance(value, bool):
                raise GenerationError(f"{key} must be a bool, got {value!r}")
            out[key] = value
        elif kind == "int":
            if not isinstance(value, int) or isinstance(value, bool) or value < low:
                raise GenerationError(f"{key} must be an integer >= {low}, got {value!r}")
            out[key] = value
        else:
            if isinstance(value, bool):
                raise GenerationError(f"{key} must be a number, got {value!r}")
            try:
                number = Decimal(str(value))
            except InvalidOperation as exc:
                raise GenerationError(f"{key} must be a number, got {value!r}") from exc
            if not number.is_finite() or number < low:
                raise GenerationError(f"{key} must be a finite number >= {low}, got {value!r}")
            out[key] = "0" if number == 0 else format(number.normalize(), "f")  # "-0" is the default
    if Decimal(str(out.get("risk_per_trade", "0"))) > 0 and Decimal(str(out.get("atr_stop", "0"))) <= 0:
        raise GenerationError("risk_per_trade needs atr_stop > 0 (the replay sizes risk against the ATR stop)")
    if Decimal(str(out.get("risk_per_trade", "0"))) > Decimal("0.05"):
        raise GenerationError("risk_per_trade above 0.05 is outside the research envelope")
    return {k: v for k, v in sorted(out.items()) if v != KNOB_DEFAULTS[k]}


def replay_kwargs(args: Mapping[str, Any]) -> dict[str, Any]:
    """Sealed arguments -> replay keyword arguments (decimal strings become Decimal)."""
    normalized = normalize_args(args)
    return {k: Decimal(v) if KNOBS[k][0] == "decimal" else v for k, v in normalized.items()}


def study_spec(variant_args: Mapping[str, Mapping[str, Any]], *, reference: str, days: int, windows: int,
               embargo: int, step: int, exp001: bool) -> dict[str, Any]:
    """The sealed study specification of a run with explicit variant arguments.

    tools/strategy_compare.study_parameters returns exactly this for a run with sealed
    arguments, so a registered run binds only when it runs exactly these arguments.
    """
    if reference not in variant_args:
        raise GenerationError(f"the reference {reference!r} must be one of the variants")
    sealed = {str(name): normalize_args(args) for name, args in sorted(variant_args.items())}
    return {"variants": sorted(sealed), "reference": reference, "days": days, "windows": windows,
            "embargo": embargo, "step": step, "exp001": exp001,
            "variant_args": sealed, "variant_args_sha256": _sha256(sealed)}


def sealed_variant_args(spec: Mapping[str, Any]) -> dict[str, dict[str, Any]] | None:
    """The sealed arguments of a study specification, digest-checked; None for a names-only study."""
    if not isinstance(spec, Mapping) or "variant_args" not in spec:
        return None
    sealed = spec["variant_args"]
    if not isinstance(sealed, Mapping) or _sha256(sealed) != spec.get("variant_args_sha256"):
        raise GenerationError("the sealed variant arguments do not match their sealed digest")
    if sorted(sealed) != list(spec.get("variants", [])):
        raise GenerationError("the sealed variant arguments do not name exactly the sealed variants")
    return {str(name): normalize_args(args) for name, args in sealed.items()}


def idea_fingerprint(universe: Sequence[str], timeframe: str, spec: Mapping[str, Any]) -> str:
    """Identity of an idea: what it trades and how, not what it is called or how it is evaluated.

    For a study with sealed arguments: the universe, the timeframe, the EXP-001 floor, the
    reference's arguments and the set of variant arguments -- not the variant names (which
    carry the template name), the window, ``days``, ``windows``, ``embargo`` or ``step``.
    Re-evaluating the same idea under another name or other evaluation settings is the same
    idea, so it is EXISTING, not a new family member (Task 005 review F-2). A names-only
    study (no sealed arguments) can only be compared by its specification as a whole.
    """
    sealed = spec.get("variant_args") if isinstance(spec, Mapping) else None
    if isinstance(sealed, Mapping):
        reference = spec.get("reference")
        idea = {"universe": sorted(universe), "timeframe": str(timeframe), "exp001": spec.get("exp001"),
                "reference_args": sealed.get(reference),
                "variants": sorted(_canonical(args) for name, args in sealed.items() if name != reference)}
    else:
        idea = {"universe": sorted(universe), "timeframe": str(timeframe), "study": spec}
    return _sha256(idea)


def record_fingerprint(record) -> str | None:
    spec = record.preregistration.feature_spec.get(STUDY_SPEC_KEY)
    if not isinstance(spec, Mapping):
        return None
    return idea_fingerprint(record.preregistration.universe, record.preregistration.timeframe, dict(spec))


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_.=-]+", "-", value.lower()).strip("-")


@dataclass(frozen=True, slots=True)
class Template:
    """A family of candidate hypotheses: base arguments x grid, tested against a reference."""

    name: str
    family_id: str
    author: str
    universe: tuple[str, ...]
    reference: str
    reference_args: Mapping[str, Any]
    base_args: Mapping[str, Any]
    grid: Mapping[str, Sequence[Any]]
    periods: tuple[str, ...]
    economic_rationale: str
    days: int = 30
    windows: int = 3
    embargo: int = 240
    step: int = 15
    exp001: bool = True
    timeframe: str = "1m"
    alpha: float = 0.05
    minimum_effect_size: float = 0.0
    correction: str = "BH"
    split_spec: SplitSpec = field(default_factory=lambda: SplitSpec(
        train_fraction=0.6, calibration_fraction=0.2, test_fraction=0.2, label_horizon_bars=10, embargo_pct=0.01))
    check_plan: CheckPlan = field(default_factory=lambda: CheckPlan(required_checks=(CheckName.OUT_OF_SAMPLE,)))

    def __post_init__(self) -> None:
        if not _slug(self.name) or _slug(self.name) != self.name:
            raise GenerationError(f"template name must be a lower-case slug, got {self.name!r}")
        object.__setattr__(self, "universe", tuple(self.universe))
        if not self.universe or len(set(self.universe)) != len(self.universe) or \
                not all(isinstance(s, str) and re.fullmatch(r"[A-Z0-9]{2,20}", s) for s in self.universe):
            raise GenerationError(f"the universe must be distinct exchange symbols, got {list(self.universe)!r}")
        object.__setattr__(self, "periods", tuple(self.periods))
        for name in ("days", "windows", "embargo", "step"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < (0 if name == "embargo" else 1):
                raise GenerationError(f"{name} must be a positive integer, got {value!r}")
        if not isinstance(self.exp001, bool):
            raise GenerationError(f"exp001 must be true or false, got {self.exp001!r}")
        if self.correction not in CORRECTIONS:
            raise GenerationError(f"correction must be one of {CORRECTIONS}, got {self.correction!r}")
        if not self.periods:
            raise GenerationError("a template needs at least one sealed period")
        if not isinstance(self.grid, Mapping) or not self.grid:
            raise GenerationError("a template needs a non-empty grid")
        for knob, values in self.grid.items():
            if knob not in KNOBS:
                raise GenerationError(f"grid knob {knob!r} is not a replay argument; allowed: {sorted(KNOBS)}")
            if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or not values:
                raise GenerationError(f"grid values for {knob!r} must be a non-empty list")
            if knob in self.base_args:
                raise GenerationError(f"{knob!r} is both a base argument and a grid knob")
        base, reference = normalize_args(self.base_args), normalize_args(self.reference_args)
        if any(knob in self.grid for knob in FILL_KNOBS) or \
                any(base.get(knob) != reference.get(knob) for knob in FILL_KNOBS):
            raise GenerationError("every variant must fill exactly like the reference (slippage_bps, "
                                  "next_open_fill): cheaper fills would beat the reference by construction")


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    args: Mapping[str, Any]
    spec: Mapping[str, Any]
    fingerprint: str


def _display(knob: str, value: Any) -> str:
    shown = normalize_args({knob: value}).get(knob, KNOB_DEFAULTS[knob])
    return str(shown).lower() if isinstance(shown, bool) else str(shown)


def generate(template: Template) -> list[Candidate]:
    """Every grid point, in a deterministic order."""
    knobs = sorted(template.grid)
    out = []
    for values in itertools.product(*(template.grid[k] for k in knobs)):
        args = normalize_args({**template.base_args, **dict(zip(knobs, values))})
        label = ",".join(f"{k}={_display(k, v)}" for k, v in zip(knobs, values))
        name = f"gen:{template.name}:{label}"
        if name == template.reference:
            raise GenerationError("a generated variant may not take the reference's name")
        spec = study_spec({template.reference: template.reference_args, name: args}, reference=template.reference,
                          days=template.days, windows=template.windows, embargo=template.embargo,
                          step=template.step, exp001=template.exp001)
        out.append(Candidate(name=name, args=args, spec=spec,
                             fingerprint=idea_fingerprint(template.universe, template.timeframe, spec)))
    return out


def _sealed_windows(template: Template, now: datetime) -> list[tuple[str, str]]:
    """Each period's [start, end): timezone-aware, whole-minute, wholly after ``now``, exactly ``days`` long, disjoint."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise GenerationError("now must be timezone-aware")
    windows: list[tuple[datetime, datetime]] = []
    for text in template.periods:
        try:
            start = datetime.fromisoformat(str(text))
        except ValueError as exc:
            raise GenerationError(f"unreadable period start {text!r}") from exc
        if start.tzinfo is None or start.utcoffset() is None:
            raise GenerationError(f"period start {text!r} must be timezone-aware")
        if int(start.timestamp() * 1000) % MINUTE_MS:
            raise GenerationError(f"period start {text!r} must be on a whole minute")
        if start <= now:
            raise GenerationError(f"period start {text!r} is not after the registration: the sealed window "
                                  f"must lie wholly after it")
        windows.append((start, start + timedelta(days=template.days)))
    windows.sort()
    for (_, end), (start, _) in zip(windows, windows[1:]):
        if start < end:
            raise GenerationError("sealed periods overlap; the regime bar needs non-overlapping periods")
    return [(s.isoformat(), e.isoformat()) for s, e in windows]


def _next_ids(registry: HypothesisRegistry, count: int) -> list[str]:
    used = [int(r.hypothesis_id[4:]) for r in registry.all_records()]
    first = max(used, default=0) + 1
    if first + count - 1 > 9999:
        raise GenerationError("the registry has no free HYP-NNNN ids left for this family")
    return [f"HYP-{n:04d}" for n in range(first, first + count)]


# -- the pipeline ------------------------------------------------------------

REGISTERED, EXISTING, DUPLICATE, SCREENED_OUT, FAILED, NOT_REGISTERED, REGISTRATION_FAILED = (
    "REGISTERED", "EXISTING", "DUPLICATE", "SCREENED_OUT", "FAILED", "NOT_REGISTERED", "REGISTRATION_FAILED")


@dataclass
class CandidateOutcome:
    name: str
    args: Mapping[str, Any]
    fingerprint: str
    status: str = ""
    reason: str = ""
    stages: list[StageResult] = field(default_factory=list)
    hypothesis_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "args": dict(self.args), "fingerprint": self.fingerprint, "status": self.status,
                "reason": self.reason, "stages": [s.as_dict() for s in self.stages],
                "hypothesis_ids": list(self.hypothesis_ids)}


QuickTrades = Callable[[Candidate, Mapping[str, Sequence[Any]]], int]
_CANDIDATE_CRASHES = (ArithmeticError, LookupError, TypeError, ValueError, OSError, RuntimeError, AttributeError)


def _template_digest(template: Template, windows: Sequence[tuple[str, str]]) -> str:
    """The template as sealed: everything that fixes which hypotheses it can produce."""
    return _sha256({"template": template.name, "family_id": template.family_id, "universe": list(template.universe),
                    "reference_args": normalize_args(template.reference_args),
                    "base_args": normalize_args(template.base_args),
                    "grid": {k: [str(v) for v in values] for k, values in sorted(template.grid.items())},
                    "settings": [template.days, template.windows, template.embargo, template.step, template.exp001,
                                 template.timeframe, template.alpha, template.minimum_effect_size, template.correction],
                    "windows": [list(w) for w in windows]})


def _family_plan(registry: HypothesisRegistry, family_id: str) -> tuple[str, list[list[Any]], Mapping[str, Any]] | None:
    """(template digest, sealed plan, first member's generation block) of an existing generated family."""
    members = registry.family(family_id)
    if not members:
        return None
    blocks = [m.preregistration.feature_spec.get(GENERATION_KEY) or {} for m in members]
    digests = {b.get("template_digest") for b in blocks}
    plans = {_canonical(b.get("plan")) for b in blocks}
    if None in digests or len(digests) != 1 or len(plans) != 1:
        raise GenerationError(f"family {family_id} already exists and was not registered by one generation plan")
    return digests.pop(), json.loads(plans.pop()), blocks[0]


def family_completeness(registry: HypothesisRegistry, family_id: str) -> tuple[int, int | None]:
    """(registered members, sealed family size) of a generated family; size None if not generated.

    A generated family that was only partly registered must be resumed (same template) before it
    is adjudicated: adjudicating it early would correct over fewer tests than were planned.
    """
    members = registry.family(family_id)
    sizes = {((m.preregistration.feature_spec.get(GENERATION_KEY) or {}).get("multiple_testing") or {}).get("family_size")
             for m in members} - {None}
    if len(sizes) > 1:
        raise GenerationError(f"family {family_id} carries more than one sealed family size: {sorted(sizes)}")
    return len(members), (sizes.pop() if sizes else None)


def _known_ideas(registry: HypothesisRegistry, exclude_family: str) -> dict[str, list[str]]:
    known: dict[str, list[str]] = {}
    for record in registry.all_records():
        if record.family_id == exclude_family:
            continue  # the template's own family: handled as a resume, never as "already known"
        fp = record_fingerprint(record)
        if fp is not None:
            known.setdefault(fp, []).append(record.hypothesis_id)
    return known


def run_pipeline(template: Template, registry_path: str | Path, *, historical: Mapping[str, Sequence[Any]],
                 screening: ScreeningSpec, quick_trades: QuickTrades | None, now: datetime,
                 dry_run: bool = False, clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """Generate -> deduplicate -> screen -> register one family. Returns a report; never evidence.

    The registry is read twice: once, read-only, to skip ideas already known before the slow
    screening; and again from disk under an exclusive write lock (research.registry_lock), where
    deduplication, the family check, the sealed windows (against the real clock), id allocation
    and every write happen, so nothing written meanwhile by another writer is lost (Task 005
    review F-1, F-4). A dry run writes nothing and takes no lock. Raises GenerationError only for
    a malformed request; nothing is written then. Candidate crashes are reported per candidate.
    A registry write failure stops registration and is reported. If the template's family already
    exists, the run RESUMES it from the plan sealed in its members, without screening again (so a
    changed market or a transient crash cannot change the plan); a family that was not registered
    by this template's plan is refused (F-5).
    """
    from contextlib import nullcontext

    from research.registry_lock import registry_write_lock

    clock = clock or (lambda: datetime.now(timezone.utc))
    windows = _sealed_windows(template, now)  # fail fast, before any download-sized work
    template_digest = _template_digest(template, windows)
    if screening.cutoff_ms > int(now.timestamp() * 1000):
        raise GenerationError("the screening cutoff must not be after the registration time")
    candidates = generate(template)
    outcomes = [CandidateOutcome(c.name, c.args, c.fingerprint) for c in candidates]
    snapshot = HypothesisRegistry(registry_path=registry_path)
    stored = _family_plan(snapshot, template.family_id)
    if stored is not None:  # resume: the plan is the one sealed in the family, not a new screening
        if stored[0] != template_digest:
            raise GenerationError(f"family {template.family_id} already exists with another plan; a generated "
                                  f"family is registered once (or resumed with exactly the same template)")
        planned = {fp for fp, _ in stored[1]}
        for outcome in outcomes:
            if outcome.fingerprint not in planned:
                outcome.status = SCREENED_OUT
                outcome.reason = "not in the family's sealed plan (screened out or failed when it was planned)"
        _deduplicate([o for o in outcomes if not o.status], _known_ideas(snapshot, template.family_id))
    else:
        _deduplicate(outcomes, _known_ideas(snapshot, template.family_id))
        fresh = [(c, o) for c, o in zip(candidates, outcomes) if not o.status]
        data_stages = screen_data(historical, template.universe, screening) if fresh else []
        for candidate, outcome in fresh:
            outcome.stages = list(data_stages)
            if not all(s.passed for s in data_stages):
                outcome.status = SCREENED_OUT
                outcome.reason = next(s.reason for s in data_stages if not s.passed)
                continue
            try:  # a crash in one candidate never stops the others, and marks nothing
                trades = None if quick_trades is None else quick_trades(candidate, historical)
            except _CANDIDATE_CRASHES as exc:
                outcome.status, outcome.reason = FAILED, f"{type(exc).__name__}: {exc}"
                continue
            outcome.stages.append(screen_trades(trades, screening))
            if not passed(outcome.stages):
                outcome.status, outcome.reason = SCREENED_OUT, outcome.stages[-1].reason

    if not any(not o.status for o in outcomes):
        return _report(template, outcomes, windows, screening, dry_run, family_size=0)
    failure = None
    with nullcontext() if dry_run else registry_write_lock(registry_path):
        registry = HypothesisRegistry(registry_path=registry_path)  # the latest file, inside the lock
        _deduplicate([o for o in outcomes if not o.status], _known_ideas(registry, template.family_id))
        survivors = [(c, o) for c, o in zip(candidates, outcomes) if not o.status]
        registered_at = clock()
        windows = _sealed_windows(template, max(now, registered_at))  # wholly after the real registration time
        if not survivors:
            return _report(template, outcomes, windows, screening, dry_run, family_size=0)
        plan = sorted([c.fingerprint, i] for c, _ in survivors for i in range(len(windows)))
        current = _family_plan(registry, template.family_id)
        if current is not None and (current[0] != template_digest or current[1] != plan):
            raise GenerationError(f"family {template.family_id} already exists with another plan; a generated "
                                  f"family is registered once (or resumed with exactly the same template)")
        done: dict[tuple[str, int], str] = {}
        for record in registry.family(template.family_id):
            gen = record.preregistration.feature_spec.get(GENERATION_KEY) or {}
            done[(gen.get("idea_fingerprint"), gen.get("period_index"))] = record.hypothesis_id
        m = len(plan)
        alpha = template.alpha / m if template.correction == "BONFERRONI" else template.alpha
        ids = iter(_next_ids(registry, m - len(done)))
        if current is not None:  # a resumed member carries exactly the family's original generation block
            generation = {k: v for k, v in current[2].items() if k not in ("idea_fingerprint", "period_index")}
        else:
            generation = {"template": template.name, "template_digest": template_digest, "plan": plan,
                          "lineage": _sha256([template_digest, plan]), "candidates_generated": len(outcomes),
                          "candidates_screened_out": sum(o.status == SCREENED_OUT for o in outcomes),
                          "candidates_failed": sum(o.status == FAILED for o in outcomes),
                          "screening_digest": _report(template, outcomes, [], screening, dry_run,
                                                      family_size=0)["screening_digest"],
                          "multiple_testing": {"method": template.correction, "family_size": m,
                                               "q": template.alpha, "alpha_per_hypothesis": alpha}}
        planned: list[tuple[CandidateOutcome, PreRegistration]] = []
        for candidate, outcome in survivors:  # build and validate everything before the first write
            for index, (start, end) in enumerate(windows):
                if (candidate.fingerprint, index) in done:
                    outcome.hypothesis_ids.append(done[(candidate.fingerprint, index)])
                    continue
                try:
                    planned.append((outcome, _preregistration(template, candidate, next(ids), index, len(windows),
                                                              start, end, alpha, registered_at.isoformat(),
                                                              generation)))
                except RegistryError as exc:
                    raise GenerationError(f"{candidate.name}: invalid pre-registration: {exc}") from exc
        if dry_run:
            for outcome, prereg in planned:
                outcome.hypothesis_ids.append(prereg.hypothesis_id)
            for _, outcome in survivors:
                outcome.status, outcome.reason = NOT_REGISTERED, "dry run: nothing registered"
            return _report(template, outcomes, windows, screening, dry_run, family_size=m)
        for outcome, prereg in planned:
            if failure is None:
                try:
                    registry.register(prereg)
                    outcome.hypothesis_ids.append(prereg.hypothesis_id)
                    continue
                except (RegistryError, OSError) as exc:
                    failure = f"registration stopped at {prereg.hypothesis_id}: {type(exc).__name__}: {exc}"
            outcome.status, outcome.reason = REGISTRATION_FAILED, failure
        for _, outcome in survivors:
            if not outcome.status:
                outcome.status = REGISTERED
                if any(key in done for key in ((outcome.fingerprint, i) for i in range(len(windows)))):
                    outcome.reason = "resumed: part of this family was registered by an earlier run"
    registered = sum(len(o.hypothesis_ids) for o in outcomes if o.status == REGISTERED)
    return _report(template, outcomes, windows, screening, dry_run, family_size=registered, failure=failure)


def _deduplicate(outcomes: Sequence[CandidateOutcome], known: Mapping[str, list[str]]) -> None:
    seen: set[str] = set()
    for outcome in outcomes:
        if outcome.fingerprint in known:
            outcome.status, outcome.hypothesis_ids = EXISTING, list(known[outcome.fingerprint])
            outcome.reason = "zaten hafizada: already in the canonical registry"
        elif outcome.fingerprint in seen:
            outcome.status, outcome.reason = DUPLICATE, "the same idea appears twice in the template"
        seen.add(outcome.fingerprint)


def _preregistration(template: Template, candidate: Candidate, hypothesis_id: str, index: int, periods: int,
                     start: str, end: str, alpha: float, preregistered_at: str,
                     generation: Mapping[str, Any]) -> PreRegistration:
    return PreRegistration(
        hypothesis_id=hypothesis_id, title=f"{candidate.name} beats {template.reference}",
        description=f"Generated by template {template.name}: the variant with sealed arguments "
                    f"{_canonical(candidate.args)} versus the reference, period {index + 1} of {periods}.",
        economic_rationale=template.economic_rationale, author=template.author,
        universe=template.universe, timeframe=template.timeframe, data_start=start, data_end=end,
        entry_rule="tools.backtest_replay.replay with the sealed variant arguments",
        exit_rule="tools.backtest_replay.replay with the sealed variant arguments",
        test_statistic="net P/L minus the reference's net P/L, per window",
        direction="greater", null_hypothesis="the variant does not beat the reference",
        alpha=alpha, minimum_effect_size=template.minimum_effect_size, family_id=template.family_id,
        split_spec=template.split_spec, check_plan=template.check_plan, preregistered_at=preregistered_at,
        feature_spec={STUDY_SPEC_KEY: dict(candidate.spec),
                      GENERATION_KEY: {**generation, "idea_fingerprint": candidate.fingerprint, "period_index": index}})


def _report(template: Template, outcomes: list[CandidateOutcome], windows: list[tuple[str, str]],
            screening: ScreeningSpec, dry_run: bool, *, family_size: int, failure: str | None = None) -> dict[str, Any]:
    screened = [{"name": o.name, "fingerprint": o.fingerprint, "stages": [s.as_dict() for s in o.stages]}
                for o in outcomes]
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.status or "PENDING"] = counts.get(o.status or "PENDING", 0) + 1
    return {"template": template.name, "family_id": template.family_id, "dry_run": dry_run,
            "evidence_eligible": False, "sealed_windows": [list(w) for w in windows],
            "screening_span_ms": [screening.start_ms, screening.end_ms], "screening_digest": _sha256(screened),
            "counts": counts, "family_size": family_size,
            "multiple_testing": {"method": template.correction, "q": template.alpha,
                                 "adjudication": "HypothesisRegistry.adjudicate_family(family_id, q) over every member, "
                                                 "only after family_completeness(registry, family_id) shows the family "
                                                 "complete; an incomplete family is resumed first"},
            "registration_failure": failure, "candidates": [o.as_dict() for o in outcomes]}
