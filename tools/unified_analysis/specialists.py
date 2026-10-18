"""Specialist analysis layer: one agent per responsibility, each with declared inputs, outputs and failure behaviour.

Contract of every specialist:
  input     a MarketSnapshot (already validated; a specialist never fetches)
  output    a SpecialistReport whose findings carry their kind, stance, strength, cited SourceRef ids, numeric claims
            (recomputed later by verification) and an independence group
  failure   no usable input -> ABSTAIN with the reason (never a default view); an exception -> FAILED (the pipeline
            catches it); a FAILED or ABSTAIN specialist is a MISSING source in fusion (NB-5), never agreement

Strengths are uncalibrated ordinal weights chosen by the agent author (Task 017 UNKNOWN): they rank evidence, they
are not probabilities. Contrarian context (funding, sentiment, macro) is deliberately weak (<= 0.3).

News and on-chain analysis are declared capabilities without a reliable provider in Atlas today
(UNAVAILABLE_CAPABILITIES); they are reported as gaps, not simulated.

ModelNarrativeAnalyst (optional, the TradingAgents analyst idea) reads the deterministic findings and may add
interpretations; it may not state an observed fact, every numeric claim it makes is recomputed, and a finding
without a cited deterministic finding is dropped.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Protocol

from core.market_cycle import RESTRICTIVE_REGIMES, anchored_regime

from tools.unified_analysis.contracts import AgentStatus, Claim, Finding, FindingKind, SpecialistReport, Stance
from tools.unified_analysis.market_intelligence import PRIMARY_TIMEFRAME, TIMEFRAMES, MarketSnapshot

UNAVAILABLE_CAPABILITIES = ("news: NO_PROVIDER (no reliable crypto news source in Atlas)",
                            "on_chain: NO_PROVIDER (no on-chain data source in Atlas)")
TF_WEIGHT = {"1h": 1.0, "4h": 1.5, "1d": 2.0}
MODEL_STRENGTH_CAP = 0.3


class Specialist(Protocol):
    name: str
    responsibility: str
    inputs: tuple[str, ...]

    def analyze(self, snapshot: MarketSnapshot) -> SpecialistReport: ...


def _overall(agent: str, findings: list[Finding], *, primary_only: tuple[str, ...] | None = None) -> SpecialistReport:
    """The agent's own view: the strength-weighted net of its directional findings."""
    used = [f for f in findings if primary_only is None or f.finding_id in primary_only]
    net = sum(f.strength if f.stance is Stance.BULLISH else -f.strength if f.stance is Stance.BEARISH else 0.0
              for f in used)
    total = sum(f.strength for f in used if f.stance is not Stance.NONE)
    if total <= 0:
        return SpecialistReport(agent, AgentStatus.OK, Stance.NONE, 0.0, tuple(findings))
    strength = min(1.0, abs(net) / total * max(f.strength for f in used))
    if abs(net) / total < 0.2:
        stance = Stance.NEUTRAL
    else:
        stance = Stance.BULLISH if net > 0 else Stance.BEARISH
    return SpecialistReport(agent, AgentStatus.OK, stance, round(strength, 4), tuple(findings))


def _abstain(agent: str, reason: str) -> SpecialistReport:
    return SpecialistReport(agent, AgentStatus.ABSTAIN, reason=reason)


@dataclass(frozen=True)
class TechnicalAnalyst:
    name: str = "technical"
    responsibility: str = "multi-timeframe trend structure and momentum from closed bars"
    inputs: tuple[str, ...] = ("bars:1h", "bars:4h", "bars:1d")

    def analyze(self, snapshot: MarketSnapshot) -> SpecialistReport:
        findings: list[Finding] = []
        trend_ids: list[str] = []
        group = f"price:{snapshot.symbol}"
        stances: dict[str, Stance] = {}
        for tf in TIMEFRAMES:
            view = snapshot.view(tf)
            if view is None or not view.usable:
                continue
            close, e20, e50, r = (view.metric(m) for m in ("close", "ema_20", "ema_50", "rsi_14"))
            if None in (close, e20, e50, r):
                continue
            src = (snapshot.source_id(f"bars:{tf}"),)
            if close > e20 > e50:
                stance, text = Stance.BULLISH, "above a rising EMA stack"
            elif close < e20 < e50:
                stance, text = Stance.BEARISH, "below a falling EMA stack"
            else:
                stance, text = Stance.NEUTRAL, "inside a mixed EMA stack"
            stances[tf] = stance
            fid = f"technical:{tf}:trend"
            trend_ids.append(fid)
            findings.append(Finding(fid, self.name, FindingKind.OBSERVED_FACT,
                                    f"{tf}: close {close:.6g} {text} (EMA20 {e20:.6g}, EMA50 {e50:.6g})",
                                    stance, min(1.0, 0.4 * TF_WEIGHT[tf]), src,
                                    (Claim("close", tf, close), Claim("ema_20", tf, e20), Claim("ema_50", tf, e50)),
                                    group))
            momentum = Stance.BULLISH if r >= 55 else Stance.BEARISH if r <= 45 else Stance.NEUTRAL
            findings.append(Finding(f"technical:{tf}:rsi", self.name, FindingKind.OBSERVED_FACT,
                                    f"{tf}: RSI(14) {r:.1f}", momentum, 0.3, src, (Claim("rsi_14", tf, r),), group))
            if r >= 70 or r <= 30:
                findings.append(Finding(
                    f"technical:{tf}:exhaustion", self.name, FindingKind.HYPOTHESIS,
                    f"{tf}: RSI {r:.1f} is stretched; the move may be exhausted",
                    Stance.BEARISH if r >= 70 else Stance.BULLISH, 0.25, src, (Claim("rsi_14", tf, r),), group))
        if not trend_ids:
            return _abstain(self.name, "NO_USABLE_TIMEFRAME")
        directional = {s for s in stances.values() if s in (Stance.BULLISH, Stance.BEARISH)}
        if len(stances) > 1:
            aligned = len(directional) == 1 and all(s in directional for s in stances.values())
            findings.append(Finding(
                "technical:alignment", self.name, FindingKind.INTERPRETATION,
                ("all timeframes agree: " if aligned else "timeframes disagree: ")
                + ", ".join(f"{tf} {s.value}" for tf, s in stances.items()),
                next(iter(directional)) if aligned else Stance.NEUTRAL, 0.8 if aligned else 0.5,
                tuple(snapshot.source_id(f"bars:{tf}") for tf in stances), (), group))
        return _overall(self.name, findings, primary_only=tuple(trend_ids))


@dataclass(frozen=True)
class RegimeAnalyst:
    name: str = "regime"
    responsibility: str = "market regime and volatility state per timeframe, bounded by higher-timeframe anchors"
    inputs: tuple[str, ...] = ("bars:1h", "bars:4h", "bars:1d")

    def analyze(self, snapshot: MarketSnapshot) -> SpecialistReport:
        view = snapshot.view(PRIMARY_TIMEFRAME)
        if view is None or not view.usable:
            return _abstain(self.name, "PRIMARY_TIMEFRAME_UNUSABLE")
        group = f"price:{snapshot.symbol}"
        findings: list[Finding] = []
        regimes: dict[str, str] = {}
        for tf in TIMEFRAMES:
            v = snapshot.view(tf)
            regime = v.regime.get("regime", "UNKNOWN") if v is not None and v.usable else "UNKNOWN"
            regimes[tf] = regime
            if v is None or not v.usable:
                continue
            claims = tuple(Claim(m, tf, float(v.regime[m])) for m in ("efficiency_ratio", "vol_percentile")
                           if isinstance(v.regime.get(m), (int, float)))
            findings.append(Finding(f"regime:{tf}", self.name, FindingKind.OBSERVED_FACT, f"{tf} regime {regime}",
                                    Stance.NONE, 0.5, (snapshot.source_id(f"bars:{tf}"),), claims, group))
        tactical = regimes[PRIMARY_TIMEFRAME]
        anchored, why = anchored_regime(tactical, {tf: regimes[tf] for tf in TIMEFRAMES if tf != PRIMARY_TIMEFRAME})
        if anchored == "TREND_DOWN" and any(regimes[tf] == "TREND_UP" for tf in TIMEFRAMES if tf != PRIMARY_TIMEFRAME):
            anchored, why = "TRANSITION", "TACTICAL_TREND_DOWN_AGAINST_TREND_UP_ANCHOR"  # the symmetric bound
        stance = {"TREND_UP": Stance.BULLISH, "TREND_DOWN": Stance.BEARISH, "SIDEWAYS": Stance.NEUTRAL}.get(
            anchored, Stance.NONE)
        findings.append(Finding("regime:anchored", self.name, FindingKind.INTERPRETATION,
                                f"anchored regime {anchored}" + (f" ({why})" if why else ""), stance,
                                0.6 if stance is not Stance.NONE else 0.0,
                                tuple(snapshot.source_id(f"bars:{tf}") for tf in TIMEFRAMES
                                      if snapshot.view(tf) is not None and snapshot.view(tf).usable), (), group))
        report = _overall(self.name, findings, primary_only=("regime:anchored",))
        return SpecialistReport(report.agent, report.status, report.stance, report.strength, report.findings,
                                reason=f"anchored={anchored}; restrictive={anchored in RESTRICTIVE_REGIMES}")


def anchored_of(report: SpecialistReport | None) -> str:
    """The anchored regime a RegimeAnalyst report states (UNKNOWN when it has none)."""
    if report is None or report.status is not AgentStatus.OK:
        return "UNKNOWN"
    for part in report.reason.split(";"):
        if part.strip().startswith("anchored="):
            return part.strip().split("=", 1)[1]
    return "UNKNOWN"


@dataclass(frozen=True)
class LiquidityStructureAnalyst:
    name: str = "liquidity"
    responsibility: str = "traded value, relative volume, volatility (ATR) and position in the recent range"
    inputs: tuple[str, ...] = ("bars:1h",)

    def analyze(self, snapshot: MarketSnapshot) -> SpecialistReport:
        view = snapshot.view(PRIMARY_TIMEFRAME)
        if view is None or not view.usable:
            return _abstain(self.name, "PRIMARY_TIMEFRAME_UNUSABLE")
        tf = PRIMARY_TIMEFRAME
        src = (snapshot.source_id(f"bars:{tf}"),)
        q24, q168, atr_pct, lo, hi, close = (view.metric(m) for m in (
            "quote_volume_24", "quote_volume_168", "atr_pct_14", "swing_low_24", "swing_high_24", "close"))
        if None in (q24, atr_pct, lo, hi, close):
            return _abstain(self.name, "INSUFFICIENT_BARS_FOR_LIQUIDITY")
        findings = [
            Finding("liquidity:quote_volume_24", self.name, FindingKind.OBSERVED_FACT,
                    f"24h traded value {q24:,.0f} quote units", Stance.NONE, 0.5, src,
                    (Claim("quote_volume_24", tf, q24),), f"volume:{snapshot.symbol}"),
            Finding("liquidity:atr", self.name, FindingKind.OBSERVED_FACT, f"1h ATR(14) is {atr_pct:.2%} of price",
                    Stance.NONE, 0.5, src, (Claim("atr_pct_14", tf, atr_pct),), f"price:{snapshot.symbol}"),
        ]
        rel = None
        if q168 is not None and q168 > 0:
            rel = q24 / (q168 / 7)
            findings.append(Finding("liquidity:relative_volume", self.name, FindingKind.OBSERVED_FACT,
                                    f"last 24h traded value is {rel:.2f}x the 7-day daily average", Stance.NONE, 0.4,
                                    src, (Claim("quote_volume_24", tf, q24), Claim("quote_volume_168", tf, q168)),
                                    f"volume:{snapshot.symbol}"))
        if hi > lo:
            position = (close - lo) / (hi - lo)
            stance = Stance.NONE
            if rel is not None and rel >= 1.2 and position >= 0.8:
                stance = Stance.BULLISH
            elif rel is not None and rel >= 1.2 and position <= 0.2:
                stance = Stance.BEARISH
            findings.append(Finding(
                "liquidity:range_position", self.name,
                FindingKind.HYPOTHESIS if stance is not Stance.NONE else FindingKind.OBSERVED_FACT,
                f"close sits at {position:.0%} of the 24-bar range [{lo:.6g}, {hi:.6g}]"
                + (" on rising volume: pressure toward the range edge" if stance is not Stance.NONE else ""),
                stance, 0.3 if stance is not Stance.NONE else 0.2, src,
                (Claim("close", tf, close), Claim("swing_low_24", tf, lo), Claim("swing_high_24", tf, hi)),
                f"volume:{snapshot.symbol}" if stance is not Stance.NONE else f"price:{snapshot.symbol}"))
        return _overall(self.name, findings)


@dataclass(frozen=True)
class DerivativesAnalyst:
    name: str = "derivatives"
    responsibility: str = "perpetual funding as positioning context (contrarian, weak)"
    inputs: tuple[str, ...] = ("funding",)

    def analyze(self, snapshot: MarketSnapshot) -> SpecialistReport:
        if snapshot.funding is None:
            return _abstain(self.name, "FUNDING_UNAVAILABLE")
        rate, band = snapshot.funding["rate"], snapshot.funding.get("band")
        stance = {"CROWDED_LONG": Stance.BEARISH, "CROWDED_SHORT": Stance.BULLISH}.get(band, Stance.NONE)
        text = {"CROWDED_LONG": "longs pay a crowded premium: a long squeeze is a risk",
                "CROWDED_SHORT": "shorts pay a crowded premium: a short squeeze is possible"}.get(band, "positioning neutral")
        return _overall(self.name, [Finding(
            "derivatives:funding", self.name, FindingKind.HYPOTHESIS if stance is not Stance.NONE else FindingKind.OBSERVED_FACT,
            f"funding {rate:.4%} per 8h ({band}): {text}", stance, 0.3 if stance is not Stance.NONE else 0.2,
            (snapshot.source_id("funding"),), (), f"funding:{snapshot.symbol}")])


@dataclass(frozen=True)
class SentimentAnalyst:
    name: str = "sentiment"
    responsibility: str = "market-wide crowd sentiment (Fear & Greed) as contrarian context"
    inputs: tuple[str, ...] = ("fear_greed",)

    def analyze(self, snapshot: MarketSnapshot) -> SpecialistReport:
        if snapshot.fear_greed is None:
            return _abstain(self.name, "FEAR_GREED_UNAVAILABLE_OR_STALE")
        value = snapshot.fear_greed["value"]
        stance = Stance.BULLISH if value <= 25 else Stance.BEARISH if value >= 75 else Stance.NONE
        return _overall(self.name, [Finding(
            "sentiment:fear_greed", self.name, FindingKind.HYPOTHESIS if stance is not Stance.NONE else FindingKind.OBSERVED_FACT,
            f"Fear & Greed {value} (market-wide, not specific to {snapshot.symbol})"
            + ("; extremes have tended to precede reversals (contrarian, unmeasured in Atlas)" if stance is not Stance.NONE else ""),
            stance, 0.25 if stance is not Stance.NONE else 0.2, ("market:fear_greed",), (), "sentiment:market")])


@dataclass(frozen=True)
class MacroAnalyst:
    name: str = "macro"
    responsibility: str = "rates context from US treasury yields (risk appetite), weak"
    inputs: tuple[str, ...] = ("treasury",)

    def analyze(self, snapshot: MarketSnapshot) -> SpecialistReport:
        if snapshot.treasury is None:
            return _abstain(self.name, "TREASURY_UNAVAILABLE_OR_STALE")
        change = snapshot.treasury["ten_year_change_bp"]
        stance = Stance.BEARISH if change >= 25 else Stance.BULLISH if change <= -25 else Stance.NONE
        return _overall(self.name, [Finding(
            "macro:ten_year", self.name, FindingKind.HYPOTHESIS if stance is not Stance.NONE else FindingKind.OBSERVED_FACT,
            f"US 10y yield moved {change:+d} bp over the lookback; 10y-2y {snapshot.treasury['curve_spread_bp']:+d} bp",
            stance, 0.2, ("macro:treasury",), (), "macro:rates")])


DEFAULT_SPECIALISTS: tuple[Specialist, ...] = (TechnicalAnalyst(), RegimeAnalyst(), LiquidityStructureAnalyst(),
                                               DerivativesAnalyst(), SentimentAnalyst(), MacroAnalyst())
# The expected roster (NB-5 denominator) and each source's weight in fusion. Uncalibrated (Task 017 UNKNOWN).
ROSTER_WEIGHTS = {"technical": Decimal("1"), "regime": Decimal("1"), "liquidity": Decimal("0.5"),
                  "derivatives": Decimal("0.5"), "sentiment": Decimal("0.5"), "macro": Decimal("0.5")}
# Atlas holds no point-in-time history of funding, sentiment or macro, so a replay from the market archive cannot
# have them (taking today's value would be look-ahead). Its roster is declared up front as the price-derived
# specialists only; the report records which roster was used and calibration never mixes the two.
HISTORICAL_ROSTER_WEIGHTS = {k: ROSTER_WEIGHTS[k] for k in ("technical", "regime", "liquidity")}
ROSTERS = {"live": ROSTER_WEIGHTS, "hist": HISTORICAL_ROSTER_WEIGHTS}


# =============================================================================
# Optional model narrative (the TradingAgents analyst report, constrained)
# =============================================================================

NARRATIVE_AGENT = "narrative"
NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {"findings": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "statement": {"type": "string"},
            "kind": {"type": "string", "enum": ["INTERPRETATION", "HYPOTHESIS"]},
            "stance": {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL", "NONE"]},
            "strength": {"type": "number"},
            "cites": {"type": "array", "items": {"type": "string"}},
            "claims": {"type": "array", "items": {"type": "object", "properties": {
                "metric": {"type": "string"}, "timeframe": {"type": "string"}, "value": {"type": "number"}},
                "required": ["metric", "timeframe", "value"], "additionalProperties": False}},
        },
        "required": ["statement", "kind", "stance", "strength", "cites", "claims"],
        "additionalProperties": False}}},
    "required": ["findings"],
    "additionalProperties": False,
}
NARRATIVE_SYSTEM = (
    "You are a crypto market analyst inside Atlas, an analysis platform (not a trading bot). You receive verified "
    "findings computed from Binance data. Add at most 4 interpretations or hypotheses that the findings support. "
    "Rules: cite the finding ids you rely on; never state a new fact; every number you write must be a claim with "
    "metric, timeframe and value taken from the findings (metrics: close, rsi_14, ema_20, ema_50, return_20, "
    "atr_pct_14, swing_low_24, swing_high_24, quote_volume_24); strength 0..1; say NONE when you have no view.")


NARRATIVE_KINDS = ("INTERPRETATION", "HYPOTHESIS")
_NUMBER = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:[.,]\d+)*(?:\.\d+)?")


def _numbers_backed(statement: str, claims: tuple[Claim, ...]) -> bool:
    """Every number written in the statement must be one of its claims' values (as a value or as a percentage,
    within the model tolerance). Indicator periods in names (RSI(14), EMA20, 24h, 1d) are not free numbers."""
    from tools.unified_analysis.verification import MODEL_REL_TOL

    text = re.sub(r"(?i)\b(rsi|ema|atr|sma)\s*\(?\s*\d+\s*\)?|\b\d+\s*(h|d|m|w|bar|bars)\b", " ", statement)
    for raw in _NUMBER.findall(text):
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            return False
        if not any(abs(value - v) <= max(1e-9, MODEL_REL_TOL * abs(v)) or abs(value - 100 * v) <= max(1e-9, MODEL_REL_TOL * abs(100 * v))
                   for v in (c.value for c in claims)):
            return False
    return True


def model_narrative(snapshot: MarketSnapshot, reports: tuple[SpecialistReport, ...],
                    ask: Callable[[str, str, dict[str, Any]], Any]) -> SpecialistReport:
    """One model call. Abstains on any model failure; malformed items are dropped, never repaired."""
    findings = [f for r in reports if r.status is AgentStatus.OK for f in r.findings]
    if not findings:
        return _abstain(NARRATIVE_AGENT, "NO_FINDINGS_TO_INTERPRET")
    payload = [{"id": f.finding_id, "kind": f.kind.value, "statement": f.statement, "stance": f.stance.value,
                "claims": [{"metric": c.metric, "timeframe": c.timeframe, "value": c.value} for c in f.claims]}
               for f in findings]
    prompt = f"Symbol {snapshot.symbol}, analysis time {snapshot.as_of.isoformat()}.\nFindings:\n" + json.dumps(payload)
    from tools.unified_analysis.review import _cost, _safe_ask

    result = _safe_ask(ask, NARRATIVE_SYSTEM, prompt, NARRATIVE_SCHEMA)
    cost = _cost(result)
    data = getattr(result, "data", None)
    if getattr(result, "status", None) != "OK" or not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        return SpecialistReport(NARRATIVE_AGENT, AgentStatus.ABSTAIN, reason=f"MODEL_{getattr(result, 'reason', 'ABSTAIN')}",
                                inference_calls=1, cost_usd=cost)
    known = {f.finding_id: f for f in findings}
    out: list[Finding] = []
    dropped = 0
    for i, item in enumerate(data["findings"][:4]):
        try:
            if not isinstance(item["cites"], list) or not isinstance(item["claims"], list) \
                    or item["kind"] not in NARRATIVE_KINDS:
                dropped += 1
                continue
            cites = tuple(str(c) for c in item["cites"] if str(c) in known)
            if not cites:
                dropped += 1
                continue
            claims = tuple(Claim(str(c["metric"]), str(c["timeframe"]), float(c["value"])) for c in item["claims"])
            statement = str(item["statement"])[:400]
            if not _numbers_backed(statement, claims):
                dropped += 1   # a number in free text that no recomputed claim backs (review F1)
                continue
            out.append(Finding(f"narrative:{i}", NARRATIVE_AGENT, FindingKind(item["kind"]), statement,
                               Stance(item["stance"]), min(MODEL_STRENGTH_CAP, max(0.0, float(item["strength"]))),
                               tuple(sorted({e for c in cites for e in known[c].evidence})), claims,
                               known[cites[0]].independence_group, model_generated=True))
        except (KeyError, TypeError, ValueError, AttributeError):
            dropped += 1
    if not out:
        return SpecialistReport(NARRATIVE_AGENT, AgentStatus.ABSTAIN, reason=f"MODEL_NO_USABLE_FINDING (dropped {dropped})",
                                inference_calls=1, cost_usd=cost)
    report = _overall(NARRATIVE_AGENT, out)
    return SpecialistReport(NARRATIVE_AGENT, AgentStatus.OK, report.stance, report.strength, report.findings,
                            reason=f"dropped {dropped}", inference_calls=1, cost_usd=cost)
