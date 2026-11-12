"""Adversarial review layer (Court Skill concepts: prosecutor, lens jurors who never see each other, "would flip if").

Two reviewers challenge the primary scenario:

* the deterministic prosecutor (always runs, no model): counter-evidence, evidence concentrated in one data stream,
  support resting on hypotheses only, a higher timeframe against the thesis, a restrictive regime, an invalidation
  level inside normal noise, missing specialists and capabilities, uncalibrated confidence;
* the model court (optional, through tools.ai_gateway): a prosecutor writes charges that must cite finding ids, then
  each juror reviews the case through one lens in its own call. The case file holds only the structured record,
  never an opinion (Court Skill: a case file that leans one way decides the trial).

What the court can and cannot do:
* a model charge counts as an objection only when it cites findings that exist; at most MAJOR (it lowers
  confidence, it never decides alone); an uncited charge becomes an unresolved question;
* juror votes are tallied and recorded. A majority is NOT verification and never changes the classification;
  a rejecting majority adds one MINOR objection, and each "would flip if" becomes an unresolved question;
* a failed prosecutor call ends the court (ABSTAINED); a failed juror is NO VOTE, never a vote written for it.

Independence: all jurors may run on one model. Different prompts are different perspectives, not statistically
independent samples, and the record says so.
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable

from core.market_cycle import RESTRICTIVE_REGIMES

from tools.unified_analysis.contracts import (
    AgentStatus,
    Finding,
    FindingKind,
    Objection,
    ReviewResult,
    Scenario,
    Severity,
    SpecialistReport,
    Stance,
)
from tools.unified_analysis.market_intelligence import PRIMARY_TIMEFRAME, MarketSnapshot
from tools.unified_analysis.specialists import UNAVAILABLE_CAPABILITIES, _numbers_backed, anchored_of

COUNTER_STRENGTH = 0.5
NOISE_ATR_MULTIPLE = 0.5
JUROR_LENSES = (
    ("Risk Manager", "You protect capital first. What loses money if this is wrong, how fast, and is the invalidation "
                     "level realistic given the volatility?"),
    ("Statistician", "You care about the burden of proof. Are the cited findings independent, or several readings of "
                     "one price series? Is anything here more than noise?"),
    ("Market-Structure Trader", "You read liquidity, positioning and higher timeframes. Does the structure support "
                                "the thesis, or is it fighting the bigger trend or crowded positioning?"),
)
INDEPENDENCE_NOTE = ("Model jurors share one model and differ only by prompt: perspectives, not statistically "
                     "independent samples. Their votes are recorded, never counted as verification.")

PROSECUTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "charges": {"type": "array", "items": {"type": "object", "properties": {
            "statement": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}},
            "severity": {"type": "string", "enum": ["MAJOR", "MINOR"]}},
            "required": ["statement", "cites", "severity"], "additionalProperties": False}},
        "unresolved_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["charges", "unresolved_questions"],
    "additionalProperties": False,
}
JUROR_SCHEMA = {
    "type": "object",
    "properties": {
        "vote": {"type": "string", "enum": ["UPHOLD", "REJECT", "NO_VIEW"]},
        "reason": {"type": "string"},
        "deciding_finding": {"type": "string"},
        "would_flip_if": {"type": "string"},
    },
    "required": ["vote", "reason", "deciding_finding", "would_flip_if"],
    "additionalProperties": False,
}
# COURT_RULES and the Statistician lens's first sentence are adapted from court-skill (MIT, 2abd32d): court.py
# lines 111-113 ("Use only what is in the record. Never invent facts, numbers, quotes or sources. Where the record is
# silent, say what is missing ...") and jurors.json ("The Retired Judge": "You care about the burden of proof.")
# (review 49 LOW-2; MIT License, Copyright (c) 2026 Alex Chen)
COURT_RULES = ("Use only what is in the case file. Never invent facts, numbers or sources; where the record is "
               "silent, say what is missing. The analysis is advisory research about a crypto asset, not a trade.")


def deterministic_review(snapshot: MarketSnapshot, accepted: tuple[Finding, ...], scenarios: tuple[Scenario, ...],
                         primary: str, reports: tuple[SpecialistReport, ...], calibrated: bool,
                         dropped_model_findings: int = 0) -> tuple[list[Objection], list[str]]:
    by_id = {f.finding_id: f for f in accepted}
    chosen = next(s for s in scenarios if s.name == primary)
    objections: list[Objection] = []
    questions: list[str] = []

    def add(category: str, severity: Severity, statement: str, targets: tuple[str, ...] = ()) -> None:
        objections.append(Objection(f"det:{category}:{len(objections) + 1}", "deterministic_prosecutor", severity,
                                    category, statement, targets))

    regime = anchored_of(next((r for r in reports if r.agent == "regime"), None))
    if regime in RESTRICTIVE_REGIMES:
        add("RESTRICTIVE_REGIME", Severity.BLOCKING,
            f"the anchored regime is {regime}: no directional conclusion is defensible in it", ("regime:anchored",))
    if chosen.stance in (Stance.BULLISH, Stance.BEARISH):
        counters = sorted((by_id[i] for i in chosen.opposing if by_id[i].strength >= COUNTER_STRENGTH),
                          key=lambda f: -f.strength)[:3]
        for f in counters:
            add("COUNTER_EVIDENCE", Severity.MAJOR, f"against the thesis: {f.statement}", (f.finding_id,))
        if len(chosen.independent_groups) <= 1:
            add("EVIDENCE_CONCENTRATION", Severity.MAJOR,
                f"all support comes from one data stream ({', '.join(chosen.independent_groups) or 'none'}); "
                "several readings of one series are not independent confirmation", chosen.supporting)
        if chosen.supporting and all(by_id[i].kind in (FindingKind.HYPOTHESIS, FindingKind.PREDICTION)
                                     for i in chosen.supporting):
            add("HYPOTHESIS_ONLY", Severity.MAJOR, "the support is hypotheses only, no observed fact",
                chosen.supporting)
        daily = by_id.get("technical:1d:trend")
        opposite = Stance.BEARISH if chosen.stance is Stance.BULLISH else Stance.BULLISH
        if daily is not None and daily.stance is opposite:
            add("TIMEFRAME_CONFLICT", Severity.MAJOR, f"the daily trend is against the thesis: {daily.statement}",
                (daily.finding_id,))
        view = snapshot.view(PRIMARY_TIMEFRAME)
        close = view.metric("close") if view is not None else None
        atr = view.metric("atr_14") if view is not None else None
        if close and atr:
            for cond in chosen.invalidation:
                if abs(close - cond.threshold) < NOISE_ATR_MULTIPLE * atr:
                    add("NOISE_INVALIDATION", Severity.MAJOR,
                        f"invalidation ({cond.description}) is within {NOISE_ATR_MULTIPLE} ATR of the close: "
                        "ordinary noise can trigger it")
    for r in reports:
        if r.status is not AgentStatus.OK:
            add("MISSING_SPECIALIST", Severity.MINOR, f"{r.agent} gave no view ({r.status.value}: {r.reason})")
    questions.extend(f"not analysed - {c}" for c in UNAVAILABLE_CAPABILITIES)
    if not calibrated:
        add("UNCALIBRATED", Severity.MINOR, "this classification has no measured track record in the experience "
                                            "ledger; confidence is capped, not calibrated")
    if dropped_model_findings:
        add("MODEL_FINDINGS_DROPPED", Severity.MINOR,
            f"{dropped_model_findings} model finding(s) failed verification and were excluded")
    return objections, questions


def _case_file(snapshot: MarketSnapshot, accepted: tuple[Finding, ...], chosen: Scenario,
               objections: list[Objection]) -> str:
    by_id = {f.finding_id: f for f in accepted}
    case = {
        "asset": snapshot.symbol, "analysis_time": snapshot.as_of.isoformat(),
        "thesis": {"scenario": chosen.name, "claim": chosen.thesis,
                   "invalidation": [c.description for c in chosen.invalidation]},
        "supporting_findings": [{"id": i, "kind": by_id[i].kind.value, "statement": by_id[i].statement}
                                for i in chosen.supporting],
        "opposing_findings": [{"id": i, "kind": by_id[i].kind.value, "statement": by_id[i].statement}
                              for i in chosen.opposing],
        "other_findings": [{"id": f.finding_id, "statement": f.statement} for f in accepted
                           if f.finding_id not in chosen.supporting and f.finding_id not in chosen.opposing
                           and not f.model_generated],   # the case file holds the record, not a model's opinion
        "objections_already_raised": [o.statement for o in objections],
        "not_analysed": list(UNAVAILABLE_CAPABILITIES),
    }
    return json.dumps(case, ensure_ascii=False, indent=1)


def _safe_ask(ask: Callable[[str, str, dict[str, Any]], Any], system: str, prompt: str, schema: dict[str, Any]) -> Any:
    """A model call that cannot raise into the pipeline (review F6): any exception is an ABSTAIN."""
    try:
        return ask(system, prompt, schema)
    except Exception as exc:
        return SimpleNamespace(status="ABSTAIN", data=None, reason=f"ASK_RAISED ({type(exc).__name__})",
                               cost_usd=Decimal("0"))


def _cost(result: Any) -> Decimal:
    value = getattr(result, "cost_usd", None)
    return value if isinstance(value, Decimal) and value.is_finite() and value >= 0 else Decimal("0")


def model_court(snapshot: MarketSnapshot, accepted: tuple[Finding, ...], scenarios: tuple[Scenario, ...], primary: str,
                objections: list[Objection], ask: Callable[[str, str, dict[str, Any]], Any], *,
                jurors: int = len(JUROR_LENSES), max_calls: int) -> ReviewResult:
    """Model court over the primary scenario. Returns only the court's part (merged by ``review``)."""
    jurors = max(0, min(jurors, len(JUROR_LENSES)))
    if max_calls < 2 or jurors < 1:
        return ReviewResult((), (), "NOT_RUN", independence_note="inference budget below prosecutor + one juror")
    jurors = min(jurors, max_calls - 1)
    chosen = next(s for s in scenarios if s.name == primary)
    known = {f.finding_id for f in accepted}
    case = _case_file(snapshot, accepted, chosen, objections)
    calls, cost = 1, Decimal("0")
    # the opening sentence is adapted from court-skill (MIT, github.com/alexyc9381/court-skill, skills/court/court.py
    # at 2abd32d, line 119; MIT License, Copyright (c) 2026 Alex Chen); see docs/architecture/UNIFIED_ANALYSIS.md
    # section 6 (review 48 L4)
    pros = _safe_ask(ask, f"You are the PROSECUTOR. Build the strongest honest case that the thesis is wrong. "
                          f"{COURT_RULES} Give at most 5 charges; each cites the finding ids it rests on.",
                     case, PROSECUTOR_SCHEMA)
    cost += _cost(pros)
    data = getattr(pros, "data", None)
    if getattr(pros, "status", None) != "OK" or not isinstance(data, dict) \
            or not isinstance(data.get("charges"), list) or not isinstance(data.get("unresolved_questions", []), list):
        return ReviewResult((), (f"model court abstained: {getattr(pros, 'reason', 'ABSTAIN')}",), "ABSTAINED",
                            independence_note=INDEPENDENCE_NOTE, inference_calls=calls, cost_usd=cost)
    out: list[Objection] = []
    questions: list[str] = []
    charges = []
    for i, charge in enumerate(data["charges"][:5]):
        try:
            statement = str(charge["statement"])[:400]
            if not isinstance(charge["cites"], list):
                continue
            cites = tuple(str(c) for c in charge["cites"] if str(c) in known)
            severity = Severity.MINOR if charge.get("severity") == "MINOR" else Severity.MAJOR
        except (KeyError, TypeError, AttributeError):
            continue
        charges.append(statement)
        # review 48 L1: a number in a charge must be one of the cited findings' recomputed claim values
        claims = tuple(c for f in accepted if f.finding_id in cites for c in f.claims)
        if cites and not _numbers_backed(statement, claims):
            questions.append(f"charge with an unverified number (not counted): {statement}")
        elif cites:
            out.append(Objection(f"court:charge:{i + 1}", "model_prosecutor", severity, "MODEL_CHARGE", statement,
                                 cites, model_generated=True))
        else:
            questions.append(f"uncited charge (not counted): {statement}")
    questions.extend(f"prosecutor asks: {str(q)[:300]}" for q in (data.get("unresolved_questions") or [])[:5])
    record = case + "\n\nProsecution charges:\n" + "\n".join(f"{n + 1}. {c}" for n, c in enumerate(charges))
    votes: list[dict[str, Any]] = []
    for name, lens in JUROR_LENSES[:jurors]:
        calls += 1
        res = _safe_ask(ask, f"You are a JUROR: {name}. {lens} You decide alone and never see other jurors. "
                             f"{COURT_RULES} UPHOLD means the thesis survives the charges; REJECT means it does not.",
                        record, JUROR_SCHEMA)
        cost += _cost(res)
        data = getattr(res, "data", None)
        if getattr(res, "status", None) != "OK" or not isinstance(data, dict) or data.get("vote") not in (
                "UPHOLD", "REJECT", "NO_VIEW"):
            votes.append({"juror": name, "vote": "NO VOTE", "reason": str(getattr(res, "reason", ""))[:200]})
            continue
        deciding = str(data.get("deciding_finding", ""))
        votes.append({"juror": name, "vote": data["vote"], "reason": str(data.get("reason", ""))[:300],
                      "deciding_finding": deciding if deciding in known else f"(not in record) {deciding}"[:120],
                      "would_flip_if": str(data.get("would_flip_if", ""))[:300]})
        if data.get("would_flip_if"):
            questions.append(f"{name} would flip if: {str(data['would_flip_if'])[:300]}")
    tally = {k: sum(1 for v in votes if v["vote"] == k) for k in ("UPHOLD", "REJECT", "NO_VIEW", "NO VOTE")}
    if tally["REJECT"] > tally["UPHOLD"]:
        out.append(Objection("court:majority", "model_jury", Severity.MINOR, "JURY_MAJORITY_REJECTS",
                             f"the jury rejected the thesis {tally['REJECT']} to {tally['UPHOLD']} "
                             "(recorded; a vote is not verification)", model_generated=True))
    status = "PARTIAL" if tally["NO VOTE"] else "COMPLETE"
    return ReviewResult(tuple(out), tuple(questions), status, tuple(votes), tally, INDEPENDENCE_NOTE, calls, cost)


def review(snapshot: MarketSnapshot, accepted: tuple[Finding, ...], scenarios: tuple[Scenario, ...], primary: str,
           reports: tuple[SpecialistReport, ...], *, calibrated: bool, dropped_model_findings: int = 0,
           ask: Callable[[str, str, dict[str, Any]], Any] | None = None, jurors: int = len(JUROR_LENSES),
           max_calls: int = 0) -> ReviewResult:
    objections, questions = deterministic_review(snapshot, accepted, scenarios, primary, reports, calibrated,
                                                 dropped_model_findings)
    chosen = next(s for s in scenarios if s.name == primary)
    if ask is None:
        court = ReviewResult((), (), "NOT_RUN", independence_note="no model configured (deterministic review only)")
    elif chosen.stance not in (Stance.BULLISH, Stance.BEARISH):
        court = ReviewResult((), (), "NOT_RUN", independence_note="no directional thesis to try")
    else:
        court = model_court(snapshot, accepted, scenarios, primary, objections, ask, jurors=jurors, max_calls=max_calls)
    return ReviewResult(tuple(objections) + court.objections, tuple(questions) + court.unresolved_questions,
                        court.court_status, court.votes, court.tally, court.independence_note or INDEPENDENCE_NOTE,
                        court.inference_calls, court.cost_usd)
