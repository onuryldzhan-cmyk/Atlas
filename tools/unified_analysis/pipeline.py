"""End-to-end orchestration of one analysis. Never raises on bad data or a failing agent; every branch is recorded.

Branches that save work:
  * unusable primary data   -> INSUFFICIENT_EVIDENCE at once: no specialist, no model call
  * no directional thesis   -> the model court does not sit (nothing to try)
  * inference budget        -> ``max_inference_calls`` bounds every model call of the run (narrative + court);
                               the gateway's own window, duplicate and runaway limits apply on top
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Callable, Mapping

from tools.unified_analysis.contracts import (
    AgentStatus,
    AnalysisReport,
    Check,
    CheckStatus,
    Classification,
    ReviewResult,
    RiskAssessment,
    SpecialistReport,
    VerificationResult,
)
from tools.unified_analysis.decision import decide
from tools.unified_analysis.experience import ExperienceLedger, analysis_id
from tools.unified_analysis.market_intelligence import PRIMARY_TIMEFRAME, MarketInputs, build_snapshot
from tools.unified_analysis.review import JUROR_LENSES, review
from tools.unified_analysis.scenarios import build_scenarios
from tools.unified_analysis.specialists import DEFAULT_SPECIALISTS, UNAVAILABLE_CAPABILITIES, model_narrative
from tools.unified_analysis.verification import verify_findings, verify_report

Ask = Callable[[str, str, dict[str, Any]], Any]
DEFAULT_HORIZON_HOURS = 24
DEFAULT_MAX_INFERENCE_CALLS = 5     # narrative 1 + prosecutor 1 + 3 jurors


def _run_specialist(specialist: Any, snapshot) -> SpecialistReport:
    try:
        report = specialist.analyze(snapshot)
        if not isinstance(report, SpecialistReport):
            return SpecialistReport(specialist.name, AgentStatus.FAILED, reason="MALFORMED_REPORT")
        return report
    except Exception as exc:  # one failing agent never stops the run; it becomes a missing source
        return SpecialistReport(getattr(specialist, "name", "unknown"), AgentStatus.FAILED,
                                reason=f"{type(exc).__name__}: {str(exc)[:160]}")


def run_analysis(inputs: MarketInputs, *, ask: Ask | None = None, specialists=DEFAULT_SPECIALISTS,
                 calibration: Mapping[str, Mapping[str, Any]] | None = None,
                 horizon_hours: int = DEFAULT_HORIZON_HOURS, max_inference_calls: int = DEFAULT_MAX_INFERENCE_CALLS,
                 jurors: int = len(JUROR_LENSES), ledger: ExperienceLedger | None = None,
                 clock: Callable[[], float] = time.perf_counter) -> AnalysisReport:
    if horizon_hours < 1:
        raise ValueError("horizon_hours must be >= 1")
    timings: dict[str, float] = {}
    started = clock()

    def lap(name: str, since: float) -> float:
        now = clock()
        timings[name] = round((now - since) * 1000, 3)
        return now

    snapshot = build_snapshot(inputs)
    t = lap("market_intelligence_ms", started)
    roster = "hist" if inputs.source == "market_archive" else "live"
    profile = f"{roster}-{'ai' if ask is not None else 'det'}"
    aid = analysis_id(inputs.symbol, inputs.cutoff_ms, profile)
    view = snapshot.view(PRIMARY_TIMEFRAME)
    reference_close = view.metric("close") if view is not None else None
    budget = max(0, int(max_inference_calls))
    calls, cost = 0, Decimal("0")

    if not snapshot.usable:
        verification = VerificationResult((Check("data:primary_timeframe", CheckStatus.FAIL,
                                                 f"1h unusable: {view.reason if view else 'absent'}"),))
        empty_review = ReviewResult((), (), "NOT_RUN", independence_note="data unusable: no review was needed")
        report = AnalysisReport(
            aid, inputs.symbol, snapshot.as_of, inputs.cutoff_ms, Classification.INSUFFICIENT_EVIDENCE, None,
            Decimal("0"), {"calibrated_probability": False}, horizon_hours, ("DATA_UNUSABLE",) + snapshot.problems,
            (), (), empty_review, verification, RiskAssessment(("DATA_UNUSABLE",), ()), snapshot.sources,
            reference_close, UNAVAILABLE_CAPABILITIES,
            {"inference_calls": 0, "cost_usd": "0", "timings": timings, "data_problems": list(snapshot.problems),
             "source": snapshot.source_name, "profile": profile})
        if ledger is not None:
            ledger.record_prediction(report)
        return report

    reports = tuple(_run_specialist(s, snapshot) for s in specialists)
    t = lap("specialists_ms", t)
    if ask is not None and budget >= 1:
        narrative = model_narrative(snapshot, reports, ask)
        calls += narrative.inference_calls
        cost += narrative.cost_usd
        reports = reports + (narrative,)
        t = lap("narrative_ms", t)
    accepted, intake = verify_findings(snapshot, reports)
    dropped = sum(1 for c in intake if c.status is CheckStatus.FAIL and not c.blocking and c.check_id.startswith(
        "finding:narrative"))
    scenarios, primary, contradictory = build_scenarios(snapshot, accepted)
    t = lap("verification_intake_and_scenarios_ms", t)
    calibrated = any(bool(v.get("measured")) for k, v in (calibration or {}).items() if k.startswith(f"{roster}:"))
    reviewed = review(snapshot, accepted, scenarios, primary, reports, calibrated=calibrated,
                      dropped_model_findings=dropped, ask=ask, jurors=jurors, max_calls=budget - calls)
    calls += reviewed.inference_calls
    cost += reviewed.cost_usd
    t = lap("review_ms", t)
    verification = verify_report(snapshot, accepted, scenarios, primary, contradictory, intake)
    t = lap("verification_ms", t)
    classification, confidence, basis, risk, reasons = decide(
        snapshot, reports, scenarios, primary, reviewed, verification, calibration, roster)
    lap("decision_ms", t)
    timings["total_ms"] = round((clock() - started) * 1000, 3)
    report = AnalysisReport(
        aid, inputs.symbol, snapshot.as_of, inputs.cutoff_ms, classification, primary, confidence, basis,
        horizon_hours, reasons, scenarios, reports, reviewed, verification, risk, snapshot.sources,
        reference_close, UNAVAILABLE_CAPABILITIES,
        {"inference_calls": calls, "inference_budget": budget, "cost_usd": str(cost), "timings": timings,
         "data_problems": list(snapshot.problems), "source": snapshot.source_name, "profile": profile,
         "accepted_findings": len(accepted)})
    if ledger is not None:
        ledger.record_prediction(report)
    return report

