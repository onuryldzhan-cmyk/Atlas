"""Evidence and verification layer: Atlas checks the claims itself instead of trusting any agent's report.

Intake (``verify_findings``), before scenarios are built:
  * every cited source must exist in the snapshot's provenance;
  * an OBSERVED_FACT must cite a source, and a model may never state one;
  * every numeric claim is recomputed from the bars with the trusted indicators (market_intelligence.METRICS).
    A deterministic specialist whose number does not reproduce is an integrity failure (blocking: the run ends
    INSUFFICIENT_EVIDENCE). A model finding with a wrong or unverifiable number is dropped and recorded.

Report (``verify_report``), after review:
  * the primary timeframe is usable; no source is observed after the cutoff (look-ahead) and no bar closes at or
    after it;
  * the scenarios reference only accepted findings;
  * contradictory evidence (both sides strong) fails: conflicting evidence never becomes a direction;
  * a directional primary scenario has an invalidation condition and is not already invalidated at the cutoff.
"""

from __future__ import annotations

from datetime import timedelta

from tools.unified_analysis.contracts import (
    AgentStatus,
    Check,
    CheckStatus,
    Finding,
    FindingKind,
    Scenario,
    SpecialistReport,
    Stance,
    VerificationResult,
)
from tools.unified_analysis.market_intelligence import FUTURE_TOLERANCE, PRIMARY_TIMEFRAME, MarketSnapshot

DETERMINISTIC_REL_TOL = 1e-9
MODEL_REL_TOL = 0.005  # a model rounds what it quotes; 0.5 % of the true value


def _matches(claimed: float, actual: float, rel_tol: float) -> bool:
    return abs(claimed - actual) <= max(1e-12, rel_tol * abs(actual))


def verify_findings(snapshot: MarketSnapshot, reports: tuple[SpecialistReport, ...]) -> tuple[tuple[Finding, ...], list[Check]]:
    known_sources = {s.source_id for s in snapshot.sources}
    accepted: list[Finding] = []
    checks: list[Check] = []
    for report in reports:
        if report.status is AgentStatus.FAILED:
            checks.append(Check(f"agent:{report.agent}", CheckStatus.FAIL, f"specialist failed: {report.reason}",
                                blocking=False))
        if report.status is not AgentStatus.OK:
            continue
        for f in report.findings:
            problems: list[str] = []
            unknown = [e for e in f.evidence if e not in known_sources]
            if unknown:
                problems.append(f"cites unknown sources {unknown}")
            if f.kind is FindingKind.OBSERVED_FACT and not f.evidence:
                problems.append("an observed fact without a source")
            if f.model_generated and f.kind is FindingKind.OBSERVED_FACT:
                problems.append("a model may not state an observed fact")
            for c in f.claims:
                view = snapshot.view(c.timeframe or PRIMARY_TIMEFRAME)
                actual = view.metric(c.metric) if view is not None else None
                if actual is None:
                    problems.append(f"{c.metric}@{c.timeframe} cannot be recomputed")
                elif not _matches(c.value, actual, MODEL_REL_TOL if f.model_generated else DETERMINISTIC_REL_TOL):
                    problems.append(f"{c.metric}@{c.timeframe} claimed {c.value:.6g}, recomputed {actual:.6g}")
            if problems:
                checks.append(Check(f"finding:{f.finding_id}", CheckStatus.FAIL, "; ".join(problems),
                                    blocking=not f.model_generated))
            else:
                accepted.append(f)
                if f.claims:
                    checks.append(Check(f"finding:{f.finding_id}", CheckStatus.PASS,
                                        f"{len(f.claims)} claim(s) recomputed"))
    return tuple(accepted), checks


def verify_report(snapshot: MarketSnapshot, accepted: tuple[Finding, ...], scenarios: tuple[Scenario, ...],
                  primary: str, contradictory: bool, intake: list[Check]) -> VerificationResult:
    checks = list(intake)
    view = snapshot.view(PRIMARY_TIMEFRAME)
    checks.append(Check("data:primary_timeframe", CheckStatus.PASS if snapshot.usable else CheckStatus.FAIL,
                        "1h bars usable" if snapshot.usable else f"1h unusable: {view.reason if view else 'absent'}"))
    late = [s.source_id for s in snapshot.sources if s.observed_at > snapshot.as_of + FUTURE_TOLERANCE]
    late += [f"bars:{tf}" for tf, v in snapshot.views.items() if v.usable and v.last_close_ms >= snapshot.cutoff_ms]
    checks.append(Check("data:no_lookahead", CheckStatus.FAIL if late else CheckStatus.PASS,
                        f"observed after the cutoff: {late}" if late else "every source precedes the cutoff"))
    if view is not None and view.usable:
        age = timedelta(milliseconds=snapshot.cutoff_ms - view.last_close_ms)
        checks.append(Check("data:freshness", CheckStatus.PASS, f"newest 1h bar closed {age} before the cutoff"))
    ids = {f.finding_id for f in accepted}
    stray = sorted({i for s in scenarios for i in (*s.supporting, *s.opposing) if i not in ids})
    checks.append(Check("consistency:scenario_references", CheckStatus.FAIL if stray else CheckStatus.PASS,
                        f"scenarios cite unaccepted findings {stray}" if stray else "scenarios cite accepted findings only"))
    checks.append(Check("consistency:contradiction", CheckStatus.FAIL if contradictory else CheckStatus.PASS,
                        "bull and bear evidence are both strong: conflicting evidence" if contradictory
                        else "no strong two-sided conflict"))
    chosen = next((s for s in scenarios if s.name == primary), None)
    if chosen is not None and chosen.stance in (Stance.BULLISH, Stance.BEARISH):
        close = view.metric("close") if view is not None else None
        if not chosen.invalidation:
            checks.append(Check("invalidation:defined", CheckStatus.FAIL, "a directional scenario without invalidation"))
        elif close is None:
            checks.append(Check("invalidation:defined", CheckStatus.FAIL, "no close to test invalidation against"))
        else:
            hit = [c.description for c in chosen.invalidation if c.hit(close)]
            checks.append(Check("invalidation:defined", CheckStatus.FAIL if hit else CheckStatus.PASS,
                                f"already invalidated at the cutoff: {hit}" if hit
                                else f"{len(chosen.invalidation)} condition(s), none hit at close {close:.6g}"))
    return VerificationResult(tuple(checks))
