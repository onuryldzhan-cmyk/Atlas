"""Risk and decision layer: the final classification, in Atlas's priority order (safety and evidence before view).

  1. unusable data                     -> INSUFFICIENT_EVIDENCE
  2. failed verification               -> INSUFFICIENT_EVIDENCE (wrong number, look-ahead, contradiction, ...)
  3. fusion over the EXPECTED roster   core.decision_intelligence.SignalFusion: a missing or failed specialist counts
                                       fully against every direction (NB-5 denominator, NB-4 monotone)
  4. scenario / fusion agreement       they must point the same way, else INSUFFICIENT_EVIDENCE
  5. confidence                        fusion bound - review penalties, capped by the measured track record (or by
                                       UNCALIBRATED_CAP without one); below the threshold -> INSUFFICIENT_EVIDENCE
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
NEUTRAL_SCALE = D("0.50")
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


def decide(snapshot: MarketSnapshot, reports: tuple[SpecialistReport, ...], scenarios: tuple[Scenario, ...],
           primary: str, review: ReviewResult, verification: VerificationResult,
           calibration: Mapping[str, Mapping[str, Any]] | None = None, roster: str = "live"
           ) -> tuple[Classification, Decimal, dict[str, Any], RiskAssessment, tuple[str, ...]]:
    """``calibration`` is keyed "<roster>:<classification>" (experience.calibration)."""
    risk = assess_risk(snapshot, reports, review)
    basis: dict[str, Any] = {"calibrated_probability": False, "roster": roster}
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
        target = Classification.NEUTRAL_RANGE
        if chosen.support_score <= 0 or (fusion.action is Action.ABSTAIN
                                         and "INSUFFICIENT_VALID_EVIDENCE" in fusion.reason_codes):
            return Classification.INSUFFICIENT_EVIDENCE, D("0"), basis, risk, ("NO_CLEAR_EDGE",)
        # A range view's confidence is an availability bound only: it never rises when evidence is removed (NB-4).
        raw = (fusion.coverage * NEUTRAL_SCALE).quantize(D("0.000001"))
    else:
        target = Classification.BULLISH_SETUP if chosen.stance is Stance.BULLISH else Classification.BEARISH_SETUP
        expected = Action.BUY if chosen.stance is Stance.BULLISH else Action.SELL
        if fusion.action is Action.ABSTAIN:
            return Classification.INSUFFICIENT_EVIDENCE, D("0"), basis, risk, ("FUSION_BELOW_THRESHOLD",) + tuple(
                fusion.reason_codes)
        if fusion.action is not expected:
            return Classification.INSUFFICIENT_EVIDENCE, D("0"), basis, risk, ("FUSION_SCENARIO_DISAGREE",)
        raw = fusion.confidence
    majors = sum(1 for o in review.objections if o.severity is Severity.MAJOR)
    penalised = max(D("0"), raw - MAJOR_PENALTY * majors)
    track = (calibration or {}).get(f"{roster}:{target.value}") or {}
    if track.get("measured"):
        cap = D(str(track["wilson_lower"])).quantize(D("0.000001"))
        basis["calibration"] = {"status": "MEASURED", **{k: track[k] for k in ("n", "hit_rate", "wilson_lower") if k in track}}
    else:
        cap = UNCALIBRATED_CAP
        basis["calibration"] = {"status": "UNCALIBRATED", "n": track.get("n", 0), "cap": str(UNCALIBRATED_CAP)}
    confidence = min(penalised, cap)
    basis.update({"raw": str(raw), "major_objections": majors, "penalty": str(MAJOR_PENALTY * majors),
                  "cap": str(cap)})
    reasons: tuple[str, ...] = tuple(fusion.reason_codes)
    if not risk.approved:
        # the last gate, with no override path: agreement among agents cannot lift a risk rejection
        return Classification.RISK_REJECTED, D("0"), basis, risk, ("RISK_REJECTED",) + risk.rejections
    if target in (Classification.BULLISH_SETUP, Classification.BEARISH_SETUP) and confidence < DECISION_THRESHOLD:
        return Classification.INSUFFICIENT_EVIDENCE, confidence, basis, risk, ("REVIEW_OBJECTIONS_OUTWEIGH",) + reasons
    return target, confidence, basis, risk, reasons
