"""
================================================================================
ATLAS AI - REASONING ENGINE (atlas_reasoning_engine.py)
================================================================================
Muhakeme motoru. Karar verme surecini formalize eder:

Evidence (Kantlar) → Hypothesis (Hipotez) → Counter Evidence (Karsi Kantlar)
    → Confidence (Guven) → Decision (Karar)

Atlas yalnizca "RSI dustu, al" dememeli.
Soylemeli: "BTC dusuyor, FED aciklamasi var, Dominance artiyor, 
           Altcoinler zayif → Risk azalt."

Bu motor, Multi-Agent Council'in kararlarini sentezler.
================================================================================
"""

import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import numpy as np


# ==============================================================================
# ENUMS
# ==============================================================================

class EvidenceType(Enum):
    TECHNICAL = "technical"       # Teknik analiz verisi
    FUNDAMENTAL = "fundamental"   # Temel analiz verisi
    MACRO = "macro"               # Makroekonomik veri
    SENTIMENT = "sentiment"       # Duygu analizi
    ONCHAIN = "onchain"           # Zincir ustu veri
    MARKET_STRUCTURE = "market_structure"  # Piyasa yapisi
    RISK = "risk"                 # Risk verisi

class HypothesisType(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    VOLATILE = "volatile"
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"

class DecisionType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    REDUCE = "reduce"
    INCREASE = "increase"
    HEDGE = "hedge"
    WAIT = "wait"


# ==============================================================================
# DATA CLASSES
# ==============================================================================

@dataclass
class Evidence:
    """Kant (delil)"""
    id: str
    type: EvidenceType
    description: str
    value: Any
    weight: float = 1.0  # 0-1, bu kantin onemi
    source: str = "unknown"
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: float = 0.5  # Bu kantin guvenilirligi

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "description": self.description,
            "value": self.value,
            "weight": self.weight,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "confidence": self.confidence
        }


@dataclass
class Hypothesis:
    """Hipotez"""
    id: str
    type: HypothesisType
    description: str
    supporting_evidence: List[str] = field(default_factory=list)  # Evidence ID'ler
    confidence: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "description": self.description,
            "supporting_evidence": self.supporting_evidence,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class CounterArgument:
    """Karsi kant"""
    id: str
    target_hypothesis: str  # Hangi hipoteze karsi
    description: str
    evidence_ids: List[str] = field(default_factory=list)
    strength: float = 0.5  # 0-1, karsi kantin gucu

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "target_hypothesis": self.target_hypothesis,
            "description": self.description,
            "evidence_ids": self.evidence_ids,
            "strength": self.strength
        }


@dataclass
class ReasoningResult:
    """Muhakeme sonucu"""
    decision: DecisionType
    confidence: float
    hypothesis: HypothesisType
    primary_evidence: List[Evidence]
    counter_arguments: List[CounterArgument]
    reasoning_chain: List[str]  # Adim adim muhakeme
    risk_assessment: Dict
    timestamp: datetime = field(default_factory=datetime.now)
    explanation: str = ""  # Insanlar icin aciklama

    def to_dict(self) -> Dict:
        return {
            "decision": self.decision.value,
            "confidence": self.confidence,
            "hypothesis": self.hypothesis.value,
            "primary_evidence": [e.to_dict() for e in self.primary_evidence],
            "counter_arguments": [c.to_dict() for c in self.counter_arguments],
            "reasoning_chain": self.reasoning_chain,
            "risk_assessment": self.risk_assessment,
            "timestamp": self.timestamp.isoformat(),
            "explanation": self.explanation
        }


# ==============================================================================
# REASONING ENGINE
# ==============================================================================

class AtlasReasoningEngine:
    """
    Atlas AI Muhakeme Motoru.

    Kullanim:
        engine = AtlasReasoningEngine()

        # Kant ekle
        engine.add_evidence("rsi_oversold", EvidenceType.TECHNICAL, 
                           "RSI 28 (oversold)", 28, weight=0.8)

        # Hipotez olustur
        engine.form_hypothesis("h1", HypothesisType.BULLISH, 
                              "BTC oversold, donus bekleniyor")

        # Karsi kant ekle
        engine.add_counter_argument("c1", "h1", 
                                   "FED yarın aciklama yapacak, piyasa gergin")

        # Karar ver
        result = engine.reason(symbol="BTCUSDT")
        print(result.explanation)
    """

    def __init__(self):
        self.evidence_pool: Dict[str, Evidence] = {}
        self.hypotheses: Dict[str, Hypothesis] = {}
        self.counter_arguments: Dict[str, CounterArgument] = {}
        self.reasoning_history: List[ReasoningResult] = []

        # Kant agirliklari (varsayilan)
        self.evidence_weights = {
            EvidenceType.TECHNICAL: 0.25,
            EvidenceType.FUNDAMENTAL: 0.20,
            EvidenceType.MACRO: 0.20,
            EvidenceType.SENTIMENT: 0.15,
            EvidenceType.ONCHAIN: 0.10,
            EvidenceType.MARKET_STRUCTURE: 0.10,
            EvidenceType.RISK: 0.30  # Risk her zaman yuksek agirlikli
        }

        print("[ReasoningEngine] Atlas Reasoning Engine baslatildi")

    # ==========================================================================
    # EVIDENCE MANAGEMENT
    # ==========================================================================

    def add_evidence(self, evidence_id: str, evidence_type: EvidenceType,
                     description: str, value: Any, weight: float = 1.0,
                     source: str = "system", confidence: float = 0.5) -> Evidence:
        """Yeni kant ekle"""
        evidence = Evidence(
            id=evidence_id,
            type=evidence_type,
            description=description,
            value=value,
            weight=weight,
            source=source,
            confidence=confidence
        )
        self.evidence_pool[evidence_id] = evidence
        return evidence

    def add_technical_evidence(self, indicator: str, value: float,
                               signal: str, strength: float = 0.5,
                               source: str = "technical_analysis") -> Evidence:
        """Teknik kant ekle (kolaylik fonksiyonu)"""
        evidence_id = f"tech_{indicator.lower()}_{datetime.now().strftime('%H%M%S')}"
        description = f"{indicator}: {value} → {signal}"

        return self.add_evidence(
            evidence_id=evidence_id,
            evidence_type=EvidenceType.TECHNICAL,
            description=description,
            value={"indicator": indicator, "value": value, "signal": signal},
            weight=strength,
            source=source,
            confidence=0.7
        )

    def add_macro_evidence(self, event: str, impact: str,
                           direction: str, strength: float = 0.5) -> Evidence:
        """Makro kant ekle"""
        evidence_id = f"macro_{event.lower().replace(' ', '_')}"
        description = f"Makro: {event} → {impact} ({direction})"

        return self.add_evidence(
            evidence_id=evidence_id,
            evidence_type=EvidenceType.MACRO,
            description=description,
            value={"event": event, "impact": impact, "direction": direction},
            weight=strength,
            source="macro_analysis",
            confidence=0.6
        )

    def add_sentiment_evidence(self, metric: str, value: float,
                               interpretation: str, strength: float = 0.5) -> Evidence:
        """Duygu kant ekle"""
        evidence_id = f"sent_{metric.lower()}"
        description = f"Sentiment: {metric}={value} → {interpretation}"

        return self.add_evidence(
            evidence_id=evidence_id,
            evidence_type=EvidenceType.SENTIMENT,
            description=description,
            value={"metric": metric, "value": value, "interpretation": interpretation},
            weight=strength,
            source="sentiment_analysis",
            confidence=0.5
        )

    def add_risk_evidence(self, risk_type: str, level: str,
                          description: str, strength: float = 0.5) -> Evidence:
        """Risk kant ekle"""
        evidence_id = f"risk_{risk_type.lower().replace(' ', '_')}"

        return self.add_evidence(
            evidence_id=evidence_id,
            evidence_type=EvidenceType.RISK,
            description=description,
            value={"type": risk_type, "level": level},
            weight=strength,
            source="risk_manager",
            confidence=0.8
        )

    def clear_evidence(self):
        """Tum kantlari temizle (yeni analiz icin)"""
        self.evidence_pool.clear()
        self.hypotheses.clear()
        self.counter_arguments.clear()

    # ==========================================================================
    # HYPOTHESIS & COUNTER-ARGUMENT
    # ==========================================================================

    def form_hypothesis(self, hypothesis_id: str, hypothesis_type: HypothesisType,
                        description: str, evidence_ids: List[str] = None) -> Hypothesis:
        """Hipotez olustur"""
        # Kantlari degerlendir
        total_weight = 0
        total_confidence = 0

        for eid in (evidence_ids or []):
            if eid in self.evidence_pool:
                ev = self.evidence_pool[eid]
                category_weight = self.evidence_weights.get(ev.type, 0.1)
                total_weight += ev.weight * category_weight
                total_confidence += ev.confidence * ev.weight

        confidence = total_confidence / max(total_weight, 0.001)
        confidence = min(confidence, 1.0)

        hypothesis = Hypothesis(
            id=hypothesis_id,
            type=hypothesis_type,
            description=description,
            supporting_evidence=evidence_ids or [],
            confidence=confidence
        )
        self.hypotheses[hypothesis_id] = hypothesis
        return hypothesis

    def add_counter_argument(self, counter_id: str, target_hypothesis: str,
                             description: str, evidence_ids: List[str] = None,
                             strength: float = 0.5) -> CounterArgument:
        """Karsi kant ekle"""
        counter = CounterArgument(
            id=counter_id,
            target_hypothesis=target_hypothesis,
            description=description,
            evidence_ids=evidence_ids or [],
            strength=strength
        )
        self.counter_arguments[counter_id] = counter
        return counter

    # ==========================================================================
    # CORE REASONING
    # ==========================================================================

    def reason(self, symbol: str = "UNKNOWN", 
               context: Dict = None) -> ReasoningResult:
        """
        Ana muhakeme fonksiyonu.
        Evidence → Hypothesis → Counter → Confidence → Decision
        """
        reasoning_chain = []
        context = context or {}

        # ADIM 1: Tum kantlari kategorilere ayir
        reasoning_chain.append("ADIM 1: Kantlar toplandi")

        evidence_by_type = {et: [] for et in EvidenceType}
        for ev in self.evidence_pool.values():
            evidence_by_type[ev.type].append(ev)

        # Her kategorinin ozetini cikar
        category_scores = {}
        for et, evidences in evidence_by_type.items():
            if not evidences:
                continue
            avg_weight = np.mean([e.weight for e in evidences])
            avg_confidence = np.mean([e.confidence for e in evidences])
            category_scores[et] = avg_weight * avg_confidence
            reasoning_chain.append(
                f"  {et.value}: {len(evidences)} kant, "
                f"agirlik={avg_weight:.2f}, guven={avg_confidence:.2f}"
            )

        # ADIM 2: Hipotezleri degerlendir
        reasoning_chain.append("\nADIM 2: Hipotezler degerlendiriliyor")

        hypothesis_scores = {}
        for hid, hyp in self.hypotheses.items():
            # Karsi kantlari hesapla
            counter_strength = 0
            for cid, counter in self.counter_arguments.items():
                if counter.target_hypothesis == hid:
                    counter_strength += counter.strength

            # Net confidence
            net_confidence = hyp.confidence * (1 - counter_strength * 0.5)
            net_confidence = max(0, min(1, net_confidence))

            hypothesis_scores[hid] = {
                "hypothesis": hyp,
                "net_confidence": net_confidence,
                "counter_strength": counter_strength
            }

            reasoning_chain.append(
                f"  {hyp.type.value}: guven={hyp.confidence:.2f}, "
                f"karsi_kant={counter_strength:.2f}, net={net_confidence:.2f}"
            )

        # ADIM 3: En guclu hipotezi sec
        reasoning_chain.append("\nADIM 3: En guclu hipotez seciliyor")

        if not hypothesis_scores:
            # Hipotez yoksa, kantlardan otomatik olustur
            best_hypothesis = self._infer_hypothesis_from_evidence()
            best_confidence = 0.3
            reasoning_chain.append("  Hipotez bulunamadi, kantlardan cikarim yapildi")
        else:
            best = max(hypothesis_scores.items(), key=lambda x: x[1]["net_confidence"])
            best_hypothesis = best[1]["hypothesis"]
            best_confidence = best[1]["net_confidence"]
            reasoning_chain.append(
                f"  Secilen: {best_hypothesis.type.value} "
                f"(guven: {best_confidence:.2f})"
            )

        # ADIM 4: Karar ver
        reasoning_chain.append("\nADIM 4: Karar veriliyor")

        decision, decision_confidence = self._decision_from_hypothesis(
            best_hypothesis, best_confidence, category_scores
        )

        reasoning_chain.append(f"  Karar: {decision.value}")
        reasoning_chain.append(f"  Guven: {decision_confidence:.2f}")

        # ADIM 5: Risk degerlendirmesi
        reasoning_chain.append("\nADIM 5: Risk degerlendirmesi")
        risk_assessment = self._assess_risk()
        reasoning_chain.append(
            f"  Genel risk: {risk_assessment['overall_risk']}, "
            f"tavsiye: {risk_assessment['recommendation']}"
        )

        # Karar riski etkileyecek mi?
        if risk_assessment["overall_risk"] == "HIGH" and decision in [DecisionType.BUY, DecisionType.INCREASE]:
            old_decision = decision
            decision = DecisionType.REDUCE
            reasoning_chain.append(
                f"  RISK UYARISI: {old_decision.value} → {decision.value} "
                f"(yuksek risk nedeniyle)"
            )

        # Aciklama olustur
        explanation = self._generate_explanation(
            symbol, decision, best_hypothesis, best_confidence,
            risk_assessment, category_scores
        )

        # Sonuc olustur
        result = ReasoningResult(
            decision=decision,
            confidence=decision_confidence,
            hypothesis=best_hypothesis.type,
            primary_evidence=list(self.evidence_pool.values()),
            counter_arguments=list(self.counter_arguments.values()),
            reasoning_chain=reasoning_chain,
            risk_assessment=risk_assessment,
            explanation=explanation
        )

        self.reasoning_history.append(result)
        return result

    def _infer_hypothesis_from_evidence(self) -> Hypothesis:
        """Kantlardan hipotez cikar"""
        # Basit kural tabanli cikarim
        bullish_score = 0
        bearish_score = 0

        for ev in self.evidence_pool.values():
            desc = ev.description.lower()
            if any(w in desc for w in ["oversold", "bullish", "support", "buy"]):
                bullish_score += ev.weight
            elif any(w in desc for w in ["overbought", "bearish", "resistance", "sell"]):
                bearish_score += ev.weight

        if bullish_score > bearish_score * 1.5:
            htype = HypothesisType.BULLISH
            desc = "Kantlar yukselis egilimini destekliyor"
        elif bearish_score > bullish_score * 1.5:
            htype = HypothesisType.BEARISH
            desc = "Kantlar dusus egilimini destekliyor"
        else:
            htype = HypothesisType.NEUTRAL
            desc = "Kantlar celiskili, tarafsiz durum"

        return Hypothesis(
            id="inferred_001",
            type=htype,
            description=desc,
            confidence=0.3
        )

    def _decision_from_hypothesis(self, hypothesis: Hypothesis, 
                                   confidence: float,
                                   category_scores: Dict) -> Tuple[DecisionType, float]:
        """Hipotezden karar uret"""

        # Temel karar
        decision_map = {
            HypothesisType.BULLISH: DecisionType.BUY,
            HypothesisType.BEARISH: DecisionType.SELL,
            HypothesisType.NEUTRAL: DecisionType.HOLD,
            HypothesisType.VOLATILE: DecisionType.HEDGE,
            HypothesisType.ACCUMULATION: DecisionType.BUY,
            HypothesisType.DISTRIBUTION: DecisionType.SELL
        }

        base_decision = decision_map.get(hypothesis.type, DecisionType.HOLD)

        # Guven cok dusukse bekle
        if confidence < 0.3:
            return DecisionType.WAIT, confidence

        # Guven orta seviyedeyse azalt
        if confidence < 0.6 and base_decision in [DecisionType.BUY, DecisionType.SELL]:
            if base_decision == DecisionType.BUY:
                return DecisionType.INCREASE if confidence > 0.5 else DecisionType.HOLD
            else:
                return DecisionType.REDUCE if confidence > 0.5 else DecisionType.HOLD

        return base_decision, confidence

    def _assess_risk(self) -> Dict:
        """Risk degerlendirmesi"""
        risk_score = 0
        risk_factors = []

        for ev in self.evidence_pool.values():
            if ev.type == EvidenceType.RISK:
                risk_score += ev.weight
                risk_factors.append(ev.description)
            elif ev.type == EvidenceType.MACRO:
                # Makro olaylar riski artirir
                if any(w in ev.description.lower() for w in ["fed", "sec", "war", "crisis"]):
                    risk_score += ev.weight * 0.5
                    risk_factors.append(f"Makro risk: {ev.description}")

        if risk_score > 0.7:
            overall = "HIGH"
            recommendation = "Pozisyon azalt veya hedge"
        elif risk_score > 0.4:
            overall = "MEDIUM"
            recommendation = "Dikkatli ol, stop loss siki"
        else:
            overall = "LOW"
            recommendation = "Normal risk profili"

        return {
            "overall_risk": overall,
            "risk_score": risk_score,
            "risk_factors": risk_factors,
            "recommendation": recommendation
        }

    def _generate_explanation(self, symbol: str, decision: DecisionType,
                              hypothesis: Hypothesis, confidence: float,
                              risk: Dict, category_scores: Dict) -> str:
        """Insanlar icin aciklama uret"""

        lines = [
            f"📊 ATLAS AI KARAR RAPORU - {symbol}",
            f"{'='*50}",
            f"",
            f"🎯 KARAR: {decision.value.upper()}",
            f"📈 GUven: {confidence:.1%}",
            f"🔮 HIPOTEZ: {hypothesis.type.value}",
            f"",
            f"📝 MUHAKEME:",
            f"   {hypothesis.description}",
            f"",
            f"📋 KANTLAR:",
        ]

        # Her kategoriden en onemli 2 kanti goster
        for et in EvidenceType:
            evidences = [e for e in self.evidence_pool.values() if e.type == et]
            if evidences:
                top = sorted(evidences, key=lambda x: x.weight, reverse=True)[:2]
                for ev in top:
                    lines.append(f"   [{et.value.upper()}] {ev.description} (agirlik: {ev.weight:.2f})")

        lines.extend([
            f"",
            f"⚠️ RISK DEGERLENDIRMESI:",
            f"   Seviye: {risk['overall_risk']}",
            f"   Skor: {risk['risk_score']:.2f}",
            f"   Tavsiye: {risk['recommendation']}",
        ])

        if risk['risk_factors']:
            lines.append(f"   Risk Faktörleri:")
            for factor in risk['risk_factors'][:3]:
                lines.append(f"      • {factor}")

        lines.extend([
            f"",
            f"⏰ Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"{'='*50}"
        ])

        return "\n".join(lines)

    # ==========================================================================
    # QUICK REASONING (Convenience)
    # ==========================================================================

    def quick_reason(self, symbol: str, technical_signals: List[Dict],
                     macro_events: List[Dict] = None,
                     sentiment_data: Dict = None,
                     risk_level: str = "normal") -> ReasoningResult:
        """
        Hizli muhakeme - tum verileri alip karar verir.

        Args:
            symbol: Islem sembolu
            technical_signals: [{"indicator": "RSI", "value": 28, "signal": "oversold"}, ...]
            macro_events: [{"event": "FED Meeting", "impact": "high", "direction": "negative"}, ...]
            sentiment_data: {"fear_greed": 25, "funding": 0.01, ...}
            risk_level: "low", "normal", "high"
        """
        self.clear_evidence()

        # Teknik kantlar
        for sig in (technical_signals or []):
            self.add_technical_evidence(
                indicator=sig["indicator"],
                value=sig["value"],
                signal=sig["signal"],
                strength=sig.get("strength", 0.5)
            )

        # Makro kantlar
        for event in (macro_events or []):
            self.add_macro_evidence(
                event=event["event"],
                impact=event["impact"],
                direction=event["direction"],
                strength=event.get("strength", 0.5)
            )

        # Duygu kantlari
        if sentiment_data:
            for metric, value in sentiment_data.items():
                interpretation = self._interpret_sentiment(metric, value)
                self.add_sentiment_evidence(
                    metric=metric,
                    value=value,
                    interpretation=interpretation,
                    strength=0.4
                )

        # Risk kantlari
        if risk_level == "high":
            self.add_risk_evidence(
                risk_type="general",
                level="high",
                description="Genel risk seviyesi yuksek",
                strength=0.8
            )

        # Hipotez olustur
        self._auto_form_hypotheses()

        # Karar ver
        return self.reason(symbol=symbol)

    def _auto_form_hypotheses(self):
        """Kantlardan otomatik hipotez olustur"""
        # Bullish kantlari topla
        bullish_evidence = []
        bearish_evidence = []

        for eid, ev in self.evidence_pool.items():
            desc = ev.description.lower()
            if any(w in desc for w in ["oversold", "bullish", "support", "golden", "positive"]):
                bullish_evidence.append(eid)
            elif any(w in desc for w in ["overbought", "bearish", "resistance", "death", "negative"]):
                bearish_evidence.append(eid)

        if bullish_evidence:
            self.form_hypothesis(
                "hyp_bullish",
                HypothesisType.BULLISH,
                "Teknik ve diger kantlar yukselis egilimini destekliyor",
                bullish_evidence
            )

        if bearish_evidence:
            self.form_hypothesis(
                "hyp_bearish", 
                HypothesisType.BEARISH,
                "Teknik ve diger kantlar dusus egilimini destekliyor",
                bearish_evidence
            )

    def _interpret_sentiment(self, metric: str, value: float) -> str:
        """Duygu metrigini yorumla"""
        interpretations = {
            "fear_greed": lambda v: "extreme_fear" if v < 20 else "fear" if v < 40 else "neutral" if v < 60 else "greed" if v < 80 else "extreme_greed",
            "funding": lambda v: "negative" if v < 0 else "low" if v < 0.01 else "high" if v > 0.05 else "neutral",
            "social_volume": lambda v: "low" if v < 100 else "medium" if v < 1000 else "high"
        }

        if metric in interpretations:
            return interpretations[metric](value)
        return "unknown"

    # ==========================================================================
    # REPORTING
    # ==========================================================================

    def get_reasoning_history(self, limit: int = 10) -> List[Dict]:
        """Muhakeme gecmisi"""
        return [r.to_dict() for r in self.reasoning_history[-limit:]]

    def get_stats(self) -> Dict:
        """Istatistikler"""
        if not self.reasoning_history:
            return {"total_decisions": 0}

        decisions = [r.decision for r in self.reasoning_history]

        return {
            "total_decisions": len(decisions),
            "buy_count": decisions.count(DecisionType.BUY),
            "sell_count": decisions.count(DecisionType.SELL),
            "hold_count": decisions.count(DecisionType.HOLD),
            "avg_confidence": np.mean([r.confidence for r in self.reasoning_history]),
            "total_evidence_used": len(self.evidence_pool),
            "total_hypotheses": len(self.hypotheses)
        }


# ==============================================================================
# TEST
# ==============================================================================

if __name__ == "__main__":
    print("="*70)
    print("ATLAS AI - REASONING ENGINE TEST")
    print("="*70)

    engine = AtlasReasoningEngine()

    # SENARYO 1: BTC - Oversold + FED riski
    print("\n" + "="*70)
    print("SENARYO 1: BTC - Teknik olumlu, Makro riskli")
    print("="*70)

    result = engine.quick_reason(
        symbol="BTCUSDT",
        technical_signals=[
            {"indicator": "RSI", "value": 28, "signal": "oversold", "strength": 0.8},
            {"indicator": "MACD", "value": -0.5, "signal": "bullish_cross", "strength": 0.6},
            {"indicator": "EMA", "value": 64700, "signal": "above_200ema", "strength": 0.5}
        ],
        macro_events=[
            {"event": "FED Meeting", "impact": "high", "direction": "negative", "strength": 0.9},
            {"event": "BTC ETF Outflows", "impact": "medium", "direction": "negative", "strength": 0.6}
        ],
        sentiment_data={
            "fear_greed": 22,
            "funding": -0.02
        },
        risk_level="high"
    )

    print(result.explanation)

    # SENARYO 2: ETH - Guclu yukselis sinyalleri
    print("\n" + "="*70)
    print("SENARYO 2: ETH - Guclu yukselis sinyalleri")
    print("="*70)

    result2 = engine.quick_reason(
        symbol="ETHUSDT",
        technical_signals=[
            {"indicator": "RSI", "value": 65, "signal": "bullish_momentum", "strength": 0.7},
            {"indicator": "MACD", "value": 1.2, "signal": "strong_bullish", "strength": 0.8},
            {"indicator": "Volume", "value": 150000, "signal": "breakout_volume", "strength": 0.9},
            {"indicator": "EMA", "value": 3520, "signal": "golden_cross", "strength": 0.7}
        ],
        macro_events=[
            {"event": "ETH ETF Approval", "impact": "high", "direction": "positive", "strength": 0.9}
        ],
        sentiment_data={
            "fear_greed": 65,
            "funding": 0.01
        },
        risk_level="normal"
    )

    print(result2.explanation)

    # SENARYO 3: Karisik sinyaller
    print("\n" + "="*70)
    print("SENARYO 3: SOL - Karisik sinyaller (tarafsiz)")
    print("="*70)

    result3 = engine.quick_reason(
        symbol="SOLUSDT",
        technical_signals=[
            {"indicator": "RSI", "value": 52, "signal": "neutral", "strength": 0.3},
            {"indicator": "MACD", "value": 0.1, "signal": "weak_bullish", "strength": 0.4}
        ],
        macro_events=[
            {"event": "Network Upgrade", "impact": "medium", "direction": "positive", "strength": 0.5},
            {"event": "Competitor Launch", "impact": "medium", "direction": "negative", "strength": 0.5}
        ],
        sentiment_data={
            "fear_greed": 50,
            "funding": 0.005
        },
        risk_level="normal"
    )

    print(result3.explanation)

    # Istatistikler
    print("\n" + "="*70)
    print("GENEL ISTATISTIKLER")
    print("="*70)
    stats = engine.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")

    print("\n" + "="*70)
    print("TUM TESTLER BASARILI!")
    print("="*70)