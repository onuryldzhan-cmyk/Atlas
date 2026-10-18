"""Scenario construction (the TradingAgents bull/bear researcher idea, deterministic).

Each scenario lists the findings for and against it and is scored by INDEPENDENT evidence: within one independence
group only the strongest finding counts, so five indicators of one price series cannot outvote one independent
source. Every scenario carries concrete invalidation conditions taken from the 1h bars.
"""

from __future__ import annotations

from typing import Iterable

from tools.unified_analysis.contracts import Finding, InvalidationCondition, Scenario, Stance
from tools.unified_analysis.market_intelligence import PRIMARY_TIMEFRAME, MarketSnapshot

MIN_MARGIN = 0.3          # bull - bear independent score needed before one side is primary (uncalibrated)
CONTRADICTION_LEVEL = 0.6  # both sides at least this strong = contradictory evidence


def _score(findings: Iterable[Finding]) -> tuple[float, tuple[str, ...]]:
    best: dict[str, float] = {}
    for f in findings:
        group = f.independence_group or f.finding_id
        best[group] = max(best.get(group, 0.0), f.strength)
    return round(sum(best.values()), 4), tuple(sorted(best))


def build_scenarios(snapshot: MarketSnapshot, findings: tuple[Finding, ...]) -> tuple[tuple[Scenario, ...], str, bool]:
    """(scenarios, primary scenario name, contradictory). Only findings that survived verification are passed in.

    Model findings are recorded but never scored (review F1): a model citing findings of four different groups
    would otherwise add four "independent" groups out of its own reading of the same data."""
    findings = tuple(f for f in findings if not f.model_generated)
    bull = [f for f in findings if f.stance is Stance.BULLISH]
    bear = [f for f in findings if f.stance is Stance.BEARISH]
    neutral = [f for f in findings if f.stance is Stance.NEUTRAL]
    view = snapshot.view(PRIMARY_TIMEFRAME)
    lo = view.metric("swing_low_24") if view is not None else None
    hi = view.metric("swing_high_24") if view is not None else None
    tf = PRIMARY_TIMEFRAME
    below = (InvalidationCondition(f"a {tf} close below the 24-bar low {lo:.6g}", "close", tf, "<", lo),) if lo else ()
    above = (InvalidationCondition(f"a {tf} close above the 24-bar high {hi:.6g}", "close", tf, ">", hi),) if hi else ()
    out = []
    for name, stance, sup, opp, inv, thesis in (
            ("BULL", Stance.BULLISH, bull, bear, below, "price continues higher over the horizon"),
            ("BEAR", Stance.BEARISH, bear, bull, above, "price continues lower over the horizon"),
            ("NEUTRAL", Stance.NEUTRAL, neutral, bull + bear, below + above, "price stays inside the recent range")):
        score, groups = _score(sup)
        out.append(Scenario(name, stance, thesis, tuple(f.finding_id for f in sup), tuple(f.finding_id for f in opp),
                            score, groups, inv))
    bull_s, bear_s = out[0].support_score, out[1].support_score
    contradictory = bull_s >= CONTRADICTION_LEVEL and bear_s >= CONTRADICTION_LEVEL
    if abs(bull_s - bear_s) < MIN_MARGIN:
        primary = "NEUTRAL"
    else:
        primary = "BULL" if bull_s > bear_s else "BEAR"
    return tuple(out), primary, contradictory
