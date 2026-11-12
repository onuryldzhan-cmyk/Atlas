"""Risk and decision layer: the final classification, in Atlas's priority order (safety and evidence before view).

  1. unusable data                     -> INSUFFICIENT_EVIDENCE
  2. failed verification               -> INSUFFICIENT_EVIDENCE (wrong number, look-ahead, contradiction, ...)
  3. fusion over the EXPECTED roster   core.decision_intelligence.SignalFusion: a missing or failed specialist counts
                                       fully against every direction (NB-5 denominator, NB-4 monotone)
  4. scenario / fusion agreement       they must point the same way, else INSUFFICIENT_EVIDENCE
  5. confidence                        fusion bound - review penalties (counter-evidence exempt: fusion counts it),
                                       capped by the candidate class's track record (the hit rate shrunk toward
                                       UNCALIBRATED_CAP, never above it; MEASURED is a diagnostic only);
                                       below the threshold -> INSUFFICIENT_EVIDENCE. A NEUTRAL_RANGE needs the
                                       monotone neutral bound >= the threshold and reports no confidence
  6. risk gate (last, no override)     restrictive regime, thin liquidity, extreme volatility or a BLOCKING
                                       objection -> RISK_REJECTED, however many agents agree

Every step only lowers confidence or makes the result less directional. Confidence is an evidence-agreement bound,
not a probability (calibrated_probability is False until the experience ledger measures it). The thresholds are
uncalibrated defaults (Task 017 UNKNOWN), and none of them is a trading parameter.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from core.decision_intelligence import Action, Evidence, FusionPolicy, SignalFusion
from core.market_cycle import RESTRICTIVE_REGIMES

from tools.unified_analysis.contracts import (
    AgentStatus,
    Classification,
    ReviewResult,
    RiskAssessment,
    Scenario,
    Severity,
    SpecialistReport,
    Stance,
    VerificationResult,
)
from tools.unified_analysis.market_intelligence import PRIMARY_TIMEFRAME, MarketSnapshot
from tools.unified_analysis.specialists import ROSTERS, anchored_of

D = Decimal
DECISION_THRESHOLD = D("0.20")
MINIMUM_SOURCES = 2
MAJOR_PENALTY = D("0.10")
UNCALIBRATED_CAP = D("0.50")
CAP_PRIOR_N = D("10")             # pseudo-samples at UNCALIBRATED_CAP in the shrunk cap (uncalibrated)
PENALTY_EXEMPT = frozenset({"COUNTER_EVIDENCE"})
MIN_QUOTE_VOLUME_24 = 5_000_000.0   # quote units (USDT) traded in 24h; below it the book is too thin to read
MAX_ATR_PCT = 0.03                   # 1h ATR above 3 % of price: volatility swamps any thesis
SOURCE_VERSION = "task017-unified-analysis-v1"


def _evidence(snapshot: MarketSnapshot, report: SpecialistReport) -> Evidence:
    action = {Stance.BULLISH: Action.BUY, Stance.BEARISH: Action.SELL}.get(report.stance, Action.HOLD)
    return Evidence(evidence_id=f"{snapshot.symbol}:{snapshot.cutoff_ms}:{report.agent}", source=report.agent,
                    source_version=SOURCE_VERSION, symbol=snapshot.symbol, action=action,
                    score=D(str(report.strength)) if action is not Action.HOLD else D("0"),
                    observed_at=snapshot.as_of)


def fuse(snapshot: MarketSnapshot, reports: tuple[SpecialistReport, ...], roster: str = "live"):
    weights = ROSTERS[roster]
    policy = FusionPolicy(weights=weights, minimum_sources=MINIMUM_SOURCES, decision_threshold=DECISION_THRESHOLD)
    evidence = [_evidence(snapshot, r) for r in reports if r.status is AgentStatus.OK and r.agent in weights]
    return SignalFusion(policy).fuse(snapshot.symbol, evidence, now=snapshot.as_of)


def assess_risk(snapshot: MarketSnapshot, reports: tuple[SpecialistReport, ...], review: ReviewResult) -> RiskAssessment:
    rejections: list[str] = []
    warnings: list[str] = []
    regime = anchored_of(next((r for r in reports if r.agent == "regime"), None))
    if regime in RESTRICTIVE_REGIMES:
        rejections.append(f"REGIME_{regime}")
    view = snapshot.view(PRIMARY_TIMEFRAME)
    volume = view.metric("quote_volume_24") if view is not None else None
    atr_pct = view.metric("atr_pct_14") if view is not None else None
    if volume is None:
        rejections.append("LIQUIDITY_UNKNOWN")
    elif volume < MIN_QUOTE_VOLUME_24:
        rejections.append(f"THIN_LIQUIDITY ({volume:,.0f} < {MIN_QUOTE_VOLUME_24:,.0f})")
    if atr_pct is None:
        rejections.append("VOLATILITY_UNKNOWN")
    elif atr_pct > MAX_ATR_PCT:
        rejections.append(f"EXTREME_VOLATILITY (1h ATR {atr_pct:.2%} > {MAX_ATR_PCT:.0%})")
    for o in review.objections:
        if o.severity is Severity.BLOCKING:
            rejections.append(f"BLOCKING_OBJECTION ({o.category})")
        elif o.category == "NOISE_INVALIDATION":
            warnings.append("invalidation inside normal noise")
    if snapshot.funding is None:
        warnings.append("no funding context (spot-only or unavailable)")
    return RiskAssessment(tuple(dict.fromkeys(rejections)), tuple(dict.fromkeys(warnings)))


def _penalised_majors(review: ReviewResult, reports: tuple[SpecialistReport, ...], thesis: Stance) -> int:
    """MAJOR objections that lower confidence (review N5).

    A COUNTER_EVIDENCE finding from a specialist whose own view opposes the thesis is already inside the fusion
    bound, so it is not penalised again (doing so would let removing that specialist lift confidence). A counter
    finding from inside a specialist that fusion counted FOR the thesis is penalised, at most once per specialist:
    removing that specialist costs fusion at least weight/total >= 0.125 > the 0.10 penalty, so NB-4 holds."""
    stance = {r.agent: r.stance for r in reports if r.status is AgentStatus.OK}
    opposite = Stance.BEARISH if thesis is Stance.BULLISH else Stance.BULLISH if thesis is Stance.BEARISH else None
    majors, counter_agents = 0, set()
    for o in review.objections:
        if o.severity is not Severity.MAJOR:
            continue
        if o.category in PENALTY_EXEMPT:
            agent = o.targets[0].split(":", 1)[0] if o.targets else ""
            if opposite is not None and stance.get(agent) is not opposite:
                counter_agents.add(agent)
            continue
        majors += 1
    return majors + len(counter_agents)


def neutral_bound(reports: tuple[SpecialistReport, ...], roster: str = "live") -> Decimal:
    """Worst-case agreement on "no directional edge", over the expected roster (the NB-4/NB-5 rule of SignalFusion
    applied to the range view): a NEUTRAL source counts +strength, a directional one -strength, a source with no
    view 0, a missing or failed one -1 (fully against). Removing any source never raises it."""
    weights = ROSTERS[roster]
    total = sum(weights.values(), D("0"))
    present = {r.agent: r for r in reports if r.status is AgentStatus.OK and r.agent in weights}
    net = D("0")
    for agent, weight in weights.items():
        r = present.get(agent)
        if r is None:
            net -= weight
        elif r.stance is Stance.NEUTRAL:
            net += D(str(r.strength)) * weight
        elif r.stance in (Stance.BULLISH, Stance.BEARISH):
            net -= D(str(r.strength)) * weight
    return (net / total).quantize(D("0.000001"))


def calibration_cap(track: Mapping[str, Any]) -> tuple[Decimal, dict[str, Any]]:
    """The confidence cap from the candidate class's settled record (review F4: a poor record must lower it).

    The forward hit rate, with every hindsight sample counted as a miss (review 51 F-51-1), shrunk toward
    UNCALIBRATED_CAP with a prior of CAP_PRIOR_N pseudo-samples, never above
    UNCALIBRATED_CAP: no record = 0.50, a losing record lowers it smoothly, one early miss cannot freeze the class at
    zero, one more hit never lowers it and one more miss never raises it ((h + 1 + 5) / (n + 11) >= (h + 5) / (n + 10)
    whenever h <= n).

    Review 48 H1: a MEASURED record (walk-forward) no longer lifts the cap above UNCALIBRATED_CAP. The walk-forward
    split moves with every new sample, so a lift tied to it could fall when a hit arrives. MEASURED is reported in the
    basis as a diagnostic; a monotone lift above 0.50 is an owner decision, not made here."""
    n, hits = int(track.get("n") or 0), int(track.get("hits") or 0)
    f_n, f_hits = int(track.get("forward_n") or 0), int(track.get("forward_hits") or 0)
    # review 50 F-50-1 / review 51 F-51-1: a hindsight sample (recorded after its window began, or a track without
    # forward counts) can only count as a miss; its hits are ignored, so winners chosen after the fact can neither
    # hold the cap up nor cancel the honest misses. One more hit (forward) never lowers it, one more miss of either
    # kind never raises it.
    hindsight_misses = max(0, (n - f_n) - (hits - f_hits))
    shrunk = (D(f_hits) + UNCALIBRATED_CAP * CAP_PRIOR_N) / (D(f_n + hindsight_misses) + CAP_PRIOR_N)
    base = min(UNCALIBRATED_CAP, shrunk).quantize(D("0.000001"))
    return base, {"status": "MEASURED_DIAGNOSTIC_ONLY" if track.get("measured") else "UNCALIBRATED", "n": n,
                  "hits": hits, "forward_n": f_n, "forward_hits": f_hits, "hindsight_misses": hindsight_misses,
                  "cap": str(base)}


def decide(snapshot: MarketSnapshot, reports: tuple[SpecialistReport, ...], scenarios: tuple[Scenario, ...],
           primary: str, review: ReviewResult, verification: VerificationResult,
           calibration: Mapping[str, Mapping[str, Any]] | None = None, roster: str = "live"
           ) -> tuple[Classification, Decimal, dict[str, Any], RiskAssessment, tuple[str, ...]]:
    """``calibration`` is keyed "<roster>:<candidate class>" (experience.calibration).

    The reported confidence is non-zero only for a directional result. Every other result reports 0 and keeps the
    value it would have had in ``basis["candidate_confidence"]``, so no path from a directional result to a
    non-directional one (or between non-directional ones) can raise the reported figure (review F2, NB-4)."""
    risk = assess_risk(snapshot, reports, review)
    basis: dict[str, Any] = {"calibrated_probability": False, "roster": roster, "candidate": None}
    if not snapshot.usable:
        return Classification.INSUFFICIENT_EVIDENCE, D("0"), basis, risk, ("DATA_UNUSABLE",)
    if not verification.passed:
        failed = tuple(c.check_id for c in verification.failures if c.blocking)
        return Classification.INSUFFICIENT_EVIDENCE, D("0"), basis, risk, ("VERIFICATION_FAILED",) + failed

    fusion = fuse(snapshot, reports, roster)
    basis.update({"fusion_action": fusion.action.value, "fusion_confidence": str(fusion.confidence),
                  "coverage": str(fusion.coverage), "missing_sources": list(fusion.missing_sources),
                  "expected_sources": list(fusion.expected_sources), "fusion_reasons": list(fusion.reason_codes)})
    chosen = next(s for s in scenarios if s.name == primary)
    if chosen.stance is Stance.NEUTRAL:
        bound = neutral_bound(reports, roster)
        basis["neutral_bound"] = str(bound)
        if fusion.action is not Action.ABSTAIN or chosen.support_score <= 0 or bound < DECISION_THRESHOLD:
            return Classification.INSUFFICIENT_EVIDENCE, D("0"), basis, risk, ("NO_CLEAR_EDGE",)
        target, raw = Classification.NEUTRAL_RANGE, bound
    else:
        target = Classification.BULLISH_SETUP if chosen.stance is Stance.BULLISH else Classification.BEARISH_SETUP
        expected = Action.BUY if chosen.stance is Stance.BULLISH else Action.SELL
        if fusion.action is Action.ABSTAIN:
            return Classification.INSUFFICIENT_EVIDENCE, D("0"), basis, risk, ("FUSION_BELOW_THRESHOLD",) + tuple(
                fusion.reason_codes)
        if fusion.action is not expected:
            return Classification.INSUFFICIENT_EVIDENCE, D("0"), basis, risk, ("FUSION_SCENARIO_DISAGREE",)
        raw = fusion.confidence
    majors = _penalised_majors(review, reports, chosen.stance)
    penalised = max(D("0"), raw - MAJOR_PENALTY * majors)
    cap, basis["calibration"] = calibration_cap((calibration or {}).get(f"{roster}:{target.value}") or {})
    candidate_confidence = min(penalised, cap)
    basis.update({"candidate": target.value, "candidate_confidence": str(candidate_confidence), "raw": str(raw),
                  "major_objections": majors, "penalty": str(MAJOR_PENALTY * majors), "cap": str(cap)})
    reasons: tuple[str, ...] = tuple(fusion.reason_codes)
    if not risk.approved:
        # the last gate, with no override path: agreement among agents cannot lift a risk rejection
        return Classification.RISK_REJECTED, D("0"), basis, risk, ("RISK_REJECTED",) + risk.rejections
    if target is Classification.NEUTRAL_RANGE:
        return target, D("0"), basis, risk, reasons + ("RANGE_VIEW_CARRIES_NO_CONFIDENCE",)
    if candidate_confidence < DECISION_THRESHOLD:
        return Classification.INSUFFICIENT_EVIDENCE, D("0"), basis, risk, ("REVIEW_OBJECTIONS_OUTWEIGH",) + reasons
    return target, candidate_confidence, basis, risk, reasons
