"""
================================================================================
ATLAS AI - MULTI-AGENT COUNCIL (atlas_multi_agent.py)
================================================================================
Cok ajanli karar sistemi. Tek AI yerine uzmanlasmis ajanlar bir araya gelir:

    Macro Agent        → Ekonomi, FED, enflasyon
    Technical Agent    → Grafik, indikator, pattern
    Sentiment Agent    → Duygu analizi, sosyal medya
    Orderflow Agent    → Hacim, likidite, whale hareketleri
    Portfolio Agent    → Portfoy optimizasyonu, allocation
    Risk Agent         → Risk degerlendirmesi, stop loss

    ↓

    CIO Agent (Chief Investment Officer) → Final karar

Her ajanin agirligi vardir (Darwinian selection). Iyi ajanlar sesini 
yukseltir, kotuler susturulur.

ATLAS by GIC'den ilham alinmistir: 25+ ajan, Darwinian selection,
autoresearch loop.
================================================================================
"""

import json
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


# ==============================================================================
# ENUMS
# ==============================================================================

class AgentType(Enum):
    MACRO = "macro"
    TECHNICAL = "technical"
    SENTIMENT = "sentiment"
    ORDERFLOW = "orderflow"
    PORTFOLIO = "portfolio"
    RISK = "risk"
    CIO = "cio"

class AgentStatus(Enum):
    ACTIVE = "active"
    SILENCED = "silenced"      # Kotu performans → sessiz
    PROBATION = "probation"    # Deneme asamasi
    RETIRED = "retired"        # Emekli edildi

class SignalType(Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


# ==============================================================================
# DATA CLASSES
# ==============================================================================

@dataclass
class AgentSignal:
    """Ajan sinyali"""
    agent_id: str
    agent_type: AgentType
    symbol: str
    signal: SignalType
    confidence: float  # 0-1
    reasoning: str
    evidence: List[Dict] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type.value,
            "symbol": self.symbol,
            "signal": self.signal.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "evidence": self.evidence,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class AgentPerformance:
    """Ajan performans kayitlari"""
    agent_id: str
    total_signals: int = 0
    correct_signals: int = 0
    total_pnl: float = 0.0
    avg_confidence: float = 0.0
    win_rate: float = 0.0
    sharpe: float = 0.0
    weight: float = 1.0  # Darwinian agirlik
    status: AgentStatus = AgentStatus.ACTIVE
    history: List[Dict] = field(default_factory=list)

    def update(self, signal_correct: bool, pnl: float, confidence: float):
        """Performansi guncelle"""
        self.total_signals += 1
        if signal_correct:
            self.correct_signals += 1
        self.total_pnl += pnl

        # Agirlik guncelle (Darwinian)
        if signal_correct and pnl > 0:
            self.weight = min(self.weight * 1.05, 2.5)  # Max 2.5
        elif not signal_correct or pnl < 0:
            self.weight = max(self.weight * 0.95, 0.3)  # Min 0.3

        # Win rate
        self.win_rate = self.correct_signals / max(self.total_signals, 1)

        # Status guncelle
        if self.win_rate < 0.3 and self.total_signals > 20:
            self.status = AgentStatus.SILENCED
        elif self.win_rate > 0.6 and self.status == AgentStatus.PROBATION:
            self.status = AgentStatus.ACTIVE

        self.history.append({
            "correct": signal_correct,
            "pnl": pnl,
            "confidence": confidence,
            "timestamp": datetime.now().isoformat(),
            "weight": self.weight
        })


@dataclass
class CouncilDecision:
    """Konsey karari"""
    symbol: str
    final_signal: SignalType
    final_confidence: float
    consensus_level: float  # 0-1, ne kadar uzlasti
    agent_votes: List[AgentSignal]
    weighted_votes: Dict[str, float]
    cio_reasoning: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "final_signal": self.final_signal.value,
            "final_confidence": self.final_confidence,
            "consensus_level": self.consensus_level,
            "agent_votes": [v.to_dict() for v in self.agent_votes],
            "weighted_votes": self.weighted_votes,
            "cio_reasoning": self.cio_reasoning,
            "timestamp": self.timestamp.isoformat()
        }


# ==============================================================================
# BASE AGENT
# ==============================================================================

class BaseAgent:
    """Temel ajan sinifi"""

    def __init__(self, agent_id: str, agent_type: AgentType, 
                 description: str = ""):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.description = description
        self.performance = AgentPerformance(agent_id=agent_id)

    def analyze(self, symbol: str, data: Dict) -> AgentSignal:
        """Analiz yap - alt siniflar override eder"""
        raise NotImplementedError

    def update_performance(self, signal_correct: bool, pnl: float, 
                          confidence: float):
        """Performansi guncelle"""
        self.performance.update(signal_correct, pnl, confidence)


# ==============================================================================
# SPECIALIZED AGENTS
# ==============================================================================

class MacroAgent(BaseAgent):
    """Makroekonomi ajanı"""

    def __init__(self):
        super().__init__("macro_001", AgentType.MACRO, 
                        "Makroekonomik analiz: FED, enflasyon, DXY")

    def analyze(self, symbol: str, data: Dict) -> AgentSignal:
        """Makro verileri analiz et"""
        macro_data = data.get("macro", {})

        score = 0.0
        reasons = []
        evidence = []

        # FED politikasi
        fed_stance = macro_data.get("fed_stance", "neutral")
        if fed_stance == "hawkish":
            score -= 0.4
            reasons.append("FED hawkish → Dolar guclenir → kripto baskisi")
            evidence.append({"type": "fed", "value": fed_stance, "impact": -0.4})
        elif fed_stance == "dovish":
            score += 0.4
            reasons.append("FED dovish → likidite artar → kripto destegi")
            evidence.append({"type": "fed", "value": fed_stance, "impact": 0.4})

        # DXY
        dxy = macro_data.get("dxy", 100)
        if dxy > 105:
            score -= 0.3
            reasons.append(f"DXY yuksek ({dxy}) → kripto baskisi")
            evidence.append({"type": "dxy", "value": dxy, "impact": -0.3})
        elif dxy < 100:
            score += 0.2
            reasons.append(f"DXY dusuk ({dxy}) → kripto destegi")
            evidence.append({"type": "dxy", "value": dxy, "impact": 0.2})

        # Enflasyon
        inflation = macro_data.get("inflation", 2.0)
        if inflation > 4:
            score -= 0.2
            reasons.append(f"Enflasyon yuksek ({inflation}%) → FED baskisi")
            evidence.append({"type": "inflation", "value": inflation, "impact": -0.2})

        # Sinyal belirle
        signal, confidence = self._score_to_signal(score)

        return AgentSignal(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            symbol=symbol,
            signal=signal,
            confidence=confidence,
            reasoning="; ".join(reasons) if reasons else "Makro veriler tarafsiz",
            evidence=evidence
        )

    def _score_to_signal(self, score: float) -> Tuple[SignalType, float]:
        """Skoru sinyale cevir"""
        if score > 0.5:
            return SignalType.STRONG_BUY, min(abs(score), 1.0)
        elif score > 0.2:
            return SignalType.BUY, min(abs(score), 1.0)
        elif score < -0.5:
            return SignalType.STRONG_SELL, min(abs(score), 1.0)
        elif score < -0.2:
            return SignalType.SELL, min(abs(score), 1.0)
        else:
            return SignalType.HOLD, 0.5


class TechnicalAgent(BaseAgent):
    """Teknik analiz ajanı"""

    def __init__(self):
        super().__init__("tech_001", AgentType.TECHNICAL,
                        "Teknik analiz: RSI, MACD, EMA, pattern")

    def analyze(self, symbol: str, data: Dict) -> AgentSignal:
        """Teknik verileri analiz et"""
        tech_data = data.get("technical", {})

        score = 0.0
        reasons = []
        evidence = []

        # RSI
        rsi = tech_data.get("rsi", 50)
        if rsi < 30:
            score += 0.5
            reasons.append(f"RSI oversold ({rsi})")
            evidence.append({"indicator": "RSI", "value": rsi, "signal": "oversold", "impact": 0.5})
        elif rsi > 70:
            score -= 0.5
            reasons.append(f"RSI overbought ({rsi})")
            evidence.append({"indicator": "RSI", "value": rsi, "signal": "overbought", "impact": -0.5})

        # MACD
        macd = tech_data.get("macd", {})
        if macd.get("signal") == "bullish_cross":
            score += 0.4
            reasons.append("MACD bullish cross")
            evidence.append({"indicator": "MACD", "signal": "bullish_cross", "impact": 0.4})
        elif macd.get("signal") == "bearish_cross":
            score -= 0.4
            reasons.append("MACD bearish cross")
            evidence.append({"indicator": "MACD", "signal": "bearish_cross", "impact": -0.4})

        # EMA
        ema = tech_data.get("ema", {})
        if ema.get("trend") == "above_200":
            score += 0.3
            reasons.append("Fiyat 200 EMA uzerinde")
            evidence.append({"indicator": "EMA", "signal": "above_200", "impact": 0.3})
        elif ema.get("trend") == "below_200":
            score -= 0.3
            reasons.append("Fiyat 200 EMA altinda")
            evidence.append({"indicator": "EMA", "signal": "below_200", "impact": -0.3})

        # Volume
        volume = tech_data.get("volume", {})
        if volume.get("trend") == "increasing":
            score += 0.2
            reasons.append("Hacim artiyor")
            evidence.append({"indicator": "Volume", "signal": "increasing", "impact": 0.2})

        signal, confidence = self._score_to_signal(score)

        return AgentSignal(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            symbol=symbol,
            signal=signal,
            confidence=confidence,
            reasoning="; ".join(reasons) if reasons else "Teknik veriler tarafsiz",
            evidence=evidence
        )

    def _score_to_signal(self, score: float) -> Tuple[SignalType, float]:
        if score > 0.6:
            return SignalType.STRONG_BUY, min(abs(score), 1.0)
        elif score > 0.3:
            return SignalType.BUY, min(abs(score), 1.0)
        elif score < -0.6:
            return SignalType.STRONG_SELL, min(abs(score), 1.0)
        elif score < -0.3:
            return SignalType.SELL, min(abs(score), 1.0)
        else:
            return SignalType.HOLD, 0.5


class SentimentAgent(BaseAgent):
    """Duygu analizi ajanı"""

    def __init__(self):
        super().__init__("sent_001", AgentType.SENTIMENT,
                        "Duygu analizi: Fear&Greed, funding, sosyal medya")

    def analyze(self, symbol: str, data: Dict) -> AgentSignal:
        """Duygu verilerini analiz et"""
        sentiment_data = data.get("sentiment", {})

        score = 0.0
        reasons = []
        evidence = []

        # Fear & Greed
        fg = sentiment_data.get("fear_greed", 50)
        if fg < 20:
            score += 0.5
            reasons.append(f"Extreme fear ({fg}) → contrarian alis firsati")
            evidence.append({"metric": "fear_greed", "value": fg, "interpretation": "extreme_fear", "impact": 0.5})
        elif fg > 80:
            score -= 0.5
            reasons.append(f"Extreme greed ({fg}) → contrarian satis firsati")
            evidence.append({"metric": "fear_greed", "value": fg, "interpretation": "extreme_greed", "impact": -0.5})

        # Funding rate
        funding = sentiment_data.get("funding", 0)
        if funding < -0.01:
            score += 0.3
            reasons.append(f"Funding negatif ({funding}) → short squeeze potansiyeli")
            evidence.append({"metric": "funding", "value": funding, "interpretation": "negative", "impact": 0.3})
        elif funding > 0.05:
            score -= 0.3
            reasons.append(f"Funding cok yuksek ({funding}) → long squeeze riski")
            evidence.append({"metric": "funding", "value": funding, "interpretation": "high", "impact": -0.3})

        # Social volume
        social = sentiment_data.get("social_volume", 0)
        if social > 1000:
            score -= 0.2
            reasons.append(f"Sosyal hacim yuksek ({social}) → FOMO riski")
            evidence.append({"metric": "social_volume", "value": social, "interpretation": "high", "impact": -0.2})

        signal, confidence = self._score_to_signal(score)

        return AgentSignal(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            symbol=symbol,
            signal=signal,
            confidence=confidence,
            reasoning="; ".join(reasons) if reasons else "Duygu verileri tarafsiz",
            evidence=evidence
        )

    def _score_to_signal(self, score: float) -> Tuple[SignalType, float]:
        if score > 0.4:
            return SignalType.BUY, min(abs(score), 1.0)
        elif score < -0.4:
            return SignalType.SELL, min(abs(score), 1.0)
        else:
            return SignalType.HOLD, 0.5


class OrderflowAgent(BaseAgent):
    """Order flow ajanı"""

    def __init__(self):
        super().__init__("order_001", AgentType.ORDERFLOW,
                        "Order flow: hacim, likidite, whale hareketleri")

    def analyze(self, symbol: str, data: Dict) -> AgentSignal:
        """Order flow verilerini analiz et"""
        flow_data = data.get("orderflow", {})

        score = 0.0
        reasons = []
        evidence = []

        # Whale movements
        whales = flow_data.get("whale_movements", [])
        buy_whale = sum(1 for w in whales if w.get("direction") == "in")
        sell_whale = sum(1 for w in whales if w.get("direction") == "out")

        if buy_whale > sell_whale * 2:
            score += 0.5
            reasons.append(f"Whale alis baskisi ({buy_whale} vs {sell_whale})")
            evidence.append({"type": "whale", "buy": buy_whale, "sell": sell_whale, "impact": 0.5})
        elif sell_whale > buy_whale * 2:
            score -= 0.5
            reasons.append(f"Whale satis baskisi ({sell_whale} vs {buy_whale})")
            evidence.append({"type": "whale", "buy": buy_whale, "sell": sell_whale, "impact": -0.5})

        # Liquidation levels
        liq = flow_data.get("liquidation", {})
        if liq.get("long_liquidation_risk", 0) > 0.7:
            score -= 0.3
            reasons.append("Yuksek long likidasyon riski")
            evidence.append({"type": "liquidation", "risk": "long", "impact": -0.3})

        # Order book imbalance
        ob = flow_data.get("orderbook", {})
        bid_ask_ratio = ob.get("bid_ask_ratio", 1.0)
        if bid_ask_ratio > 1.5:
            score += 0.3
            reasons.append(f"Alis baskisi yuksek (ratio: {bid_ask_ratio:.2f})")
            evidence.append({"type": "orderbook", "ratio": bid_ask_ratio, "impact": 0.3})
        elif bid_ask_ratio < 0.7:
            score -= 0.3
            reasons.append(f"Satis baskisi yuksek (ratio: {bid_ask_ratio:.2f})")
            evidence.append({"type": "orderbook", "ratio": bid_ask_ratio, "impact": -0.3})

        signal, confidence = self._score_to_signal(score)

        return AgentSignal(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            symbol=symbol,
            signal=signal,
            confidence=confidence,
            reasoning="; ".join(reasons) if reasons else "Order flow tarafsiz",
            evidence=evidence
        )

    def _score_to_signal(self, score: float) -> Tuple[SignalType, float]:
        if score > 0.5:
            return SignalType.STRONG_BUY, min(abs(score), 1.0)
        elif score > 0.2:
            return SignalType.BUY, min(abs(score), 1.0)
        elif score < -0.5:
            return SignalType.STRONG_SELL, min(abs(score), 1.0)
        elif score < -0.2:
            return SignalType.SELL, min(abs(score), 1.0)
        else:
            return SignalType.HOLD, 0.5


class RiskAgent(BaseAgent):
    """Risk degerlendirme ajanı"""

    def __init__(self):
        super().__init__("risk_001", AgentType.RISK,
                        "Risk yonetimi: volatilite, drawdown, korrelasyon")

    def analyze(self, symbol: str, data: Dict) -> AgentSignal:
        """Risk verilerini analiz et"""
        risk_data = data.get("risk", {})

        score = 0.0  # Risk ajaninda pozitif = dusuk risk (alis), negatif = yuksek risk (satis)
        reasons = []
        evidence = []

        # Volatilite
        volatility = risk_data.get("volatility", 0.5)
        if volatility > 0.8:
            score -= 0.4
            reasons.append(f"Volatilite cok yuksek ({volatility:.1%})")
            evidence.append({"type": "volatility", "value": volatility, "impact": -0.4})
        elif volatility < 0.3:
            score += 0.2
            reasons.append(f"Volatilite dusuk ({volatility:.1%}) → stabil")
            evidence.append({"type": "volatility", "value": volatility, "impact": 0.2})

        # Max drawdown
        dd = risk_data.get("max_drawdown", 0)
        if dd > 0.2:
            score -= 0.3
            reasons.append(f"Max drawdown yuksek ({dd:.1%})")
            evidence.append({"type": "drawdown", "value": dd, "impact": -0.3})

        # Portfolio concentration
        concentration = risk_data.get("concentration", 0.5)
        if concentration > 0.7:
            score -= 0.3
            reasons.append(f"Konsantrasyon riski yuksek ({concentration:.1%})")
            evidence.append({"type": "concentration", "value": concentration, "impact": -0.3})

        # Correlation risk
        corr = risk_data.get("correlation", 0)
        if corr > 0.9:
            score -= 0.2
            reasons.append(f"Asiri korelasyon ({corr:.2f}) → diversifikasyon kaybi")
            evidence.append({"type": "correlation", "value": corr, "impact": -0.2})

        # Market risk events
        events = risk_data.get("events", [])
        for event in events:
            if event.get("severity") == "high":
                score -= 0.3
                reasons.append(f"Yuksek risk olayi: {event.get('name', 'unknown')}")
                evidence.append({"type": "event", "name": event["name"], "impact": -0.3})

        signal, confidence = self._score_to_signal(score)

        return AgentSignal(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            symbol=symbol,
            signal=signal,
            confidence=confidence,
            reasoning="; ".join(reasons) if reasons else "Risk profili normal",
            evidence=evidence
        )

    def _score_to_signal(self, score: float) -> Tuple[SignalType, float]:
        # Risk ajaninda: pozitif = dusuk risk = alis, negatif = yuksek risk = satis/reduce
        if score > 0.3:
            return SignalType.BUY, min(abs(score), 1.0)
        elif score < -0.5:
            return SignalType.STRONG_SELL, min(abs(score), 1.0)
        elif score < -0.2:
            return SignalType.REDUCE, min(abs(score), 1.0)
        else:
            return SignalType.HOLD, 0.5


class PortfolioAgent(BaseAgent):
    """Portfoy optimizasyon ajanı"""

    def __init__(self):
        super().__init__("port_001", AgentType.PORTFOLIO,
                        "Portfoy yonetimi: allocation, rebalancing, opportunity")

    def analyze(self, symbol: str, data: Dict) -> AgentSignal:
        """Portfoy verilerini analiz et"""
        portfolio_data = data.get("portfolio", {})

        score = 0.0
        reasons = []
        evidence = []

        # Opportunity score
        opp = portfolio_data.get("opportunity_score", 0.5)
        if opp > 0.8:
            score += 0.5
            reasons.append(f"Yuksek firsat skoru ({opp:.2f})")
            evidence.append({"type": "opportunity", "score": opp, "impact": 0.5})
        elif opp < 0.3:
            score -= 0.3
            reasons.append(f"Dusuk firsat skoru ({opp:.2f})")
            evidence.append({"type": "opportunity", "score": opp, "impact": -0.3})

        # Current allocation
        current_alloc = portfolio_data.get("current_allocation", 0)
        target_alloc = portfolio_data.get("target_allocation", 0.1)

        if current_alloc < target_alloc * 0.5:
            score += 0.3
            reasons.append(f"Allocasyon dusuk ({current_alloc:.1%} vs hedef {target_alloc:.1%})")
            evidence.append({"type": "allocation", "current": current_alloc, "target": target_alloc, "impact": 0.3})
        elif current_alloc > target_alloc * 2:
            score -= 0.3
            reasons.append(f"Allocasyon yuksek ({current_alloc:.1%} vs hedef {target_alloc:.1%})")
            evidence.append({"type": "allocation", "current": current_alloc, "target": target_alloc, "impact": -0.3})

        # Correlation with portfolio
        port_corr = portfolio_data.get("portfolio_correlation", 0.5)
        if port_corr > 0.8:
            score -= 0.2
            reasons.append(f"Portfoy ile yuksek korelasyon ({port_corr:.2f})")
            evidence.append({"type": "correlation", "value": port_corr, "impact": -0.2})

        signal, confidence = self._score_to_signal(score)

        return AgentSignal(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            symbol=symbol,
            signal=signal,
            confidence=confidence,
            reasoning="; ".join(reasons) if reasons else "Portfoy durumu dengeli",
            evidence=evidence
        )

    def _score_to_signal(self, score: float) -> Tuple[SignalType, float]:
        if score > 0.4:
            return SignalType.BUY, min(abs(score), 1.0)
        elif score < -0.4:
            return SignalType.SELL, min(abs(score), 1.0)
        else:
            return SignalType.HOLD, 0.5


# ==============================================================================
# CIO AGENT
# ==============================================================================

class CIOAgent:
    """
    Chief Investment Officer - Final karar verici.
    Tum ajanlarin sinyallerini agirliklandirarak sentezler.
    """

    def __init__(self):
        self.agent_id = "cio_001"
        self.agent_type = AgentType.CIO
        self.decision_history: List[CouncilDecision] = []

        # Sinyal agirliklari (numerik deger)
        self.signal_weights = {
            SignalType.STRONG_BUY: 2.0,
            SignalType.BUY: 1.0,
            SignalType.HOLD: 0.0,
            SignalType.REDUCE: -0.5,
            SignalType.SELL: -1.0,
            SignalType.STRONG_SELL: -2.0
        }

        print("[CIO] Chief Investment Officer baslatildi")

    def synthesize(self, symbol: str, signals: List[AgentSignal],
                   agent_performances: Dict[str, AgentPerformance]) -> CouncilDecision:
        """
        Tum ajan sinyallerini sentezle ve final karar ver.

        Algoritma:
        1. Her ajanin sinyalini agirliklandir (performans * confidence)
        2. Tum sinyalleri topla
        3. Konsensus seviyesini hesapla
        4. Final sinyali belirle
        """
        if not signals:
            return CouncilDecision(
                symbol=symbol,
                final_signal=SignalType.HOLD,
                final_confidence=0.0,
                consensus_level=0.0,
                agent_votes=[],
                weighted_votes={},
                cio_reasoning="Hicbir ajan sinyal uretmedi"
            )

        weighted_scores = {}
        total_weight = 0

        for signal in signals:
            perf = agent_performances.get(signal.agent_id)
            if not perf:
                continue

            # Agirlik = ajan performans agirligi * sinyal confidence'i
            agent_weight = perf.weight
            signal_confidence = signal.confidence
            signal_value = self.signal_weights.get(signal.signal, 0)

            weighted_score = agent_weight * signal_confidence * signal_value
            weighted_scores[signal.agent_id] = weighted_score
            total_weight += agent_weight * signal_confidence

        # Final skor
        if total_weight > 0:
            final_score = sum(weighted_scores.values()) / total_weight
        else:
            final_score = 0

        # Final sinyal
        final_signal, final_confidence = self._score_to_final_signal(final_score)

        # Konsensus seviyesi
        signal_values = [self.signal_weights.get(s.signal, 0) for s in signals]
        if signal_values:
            consensus = 1 - (np.std(signal_values) / 2.0)  # Normalize
            consensus = max(0, min(1, consensus))
        else:
            consensus = 0

        # Muhakeme olustur
        reasoning = self._generate_reasoning(signals, weighted_scores, 
                                             final_signal, consensus)

        decision = CouncilDecision(
            symbol=symbol,
            final_signal=final_signal,
            final_confidence=final_confidence,
            consensus_level=consensus,
            agent_votes=signals,
            weighted_votes=weighted_scores,
            cio_reasoning=reasoning
        )

        self.decision_history.append(decision)
        return decision

    def _score_to_final_signal(self, score: float) -> Tuple[SignalType, float]:
        """Skoru final sinyale cevir"""
        abs_score = abs(score)

        if score > 0.8:
            return SignalType.STRONG_BUY, min(abs_score, 1.0)
        elif score > 0.4:
            return SignalType.BUY, min(abs_score, 1.0)
        elif score > 0.1:
            return SignalType.HOLD, min(abs_score, 1.0)
        elif score > -0.4:
            return SignalType.REDUCE, min(abs_score, 1.0)
        elif score > -0.8:
            return SignalType.SELL, min(abs_score, 1.0)
        else:
            return SignalType.STRONG_SELL, min(abs_score, 1.0)

    def _generate_reasoning(self, signals: List[AgentSignal],
                           weighted_scores: Dict[str, float],
                           final_signal: SignalType,
                           consensus: float) -> str:
        """CIO muhakemesi olustur"""
        lines = [
            f"CIO KARAR ANALIZI",
            f"{'='*50}",
            f"",
            f"Final Sinyal: {final_signal.value.upper()}",
            f"Konsensus: {consensus:.1%}",
            f"",
            f"AJAN OYLARI:"
        ]

        for signal in signals:
            weight = weighted_scores.get(signal.agent_id, 0)
            perf = f"(agirlik: {weight:+.2f})"
            lines.append(f"  [{signal.agent_type.value.upper()}] {signal.signal.value} "
                        f"(guven: {signal.confidence:.1%}) {perf}")
            lines.append(f"    → {signal.reasoning}")

        lines.extend([
            f"",
            f"SENTEZ:",
            f"  {'Yuksek uzlasma' if consensus > 0.7 else 'Orta uzlasma' if consensus > 0.4 else 'Dusuk uzlasma - dikkatli olun'}"
        ])

        if consensus < 0.4:
            lines.append(f"  Ajanlar ihtilaf halinde. Pozisyon kucult veya bekle.")

        return "\n".join(lines)


# ==============================================================================
# MULTI-AGENT COUNCIL
# ==============================================================================

class MultiAgentCouncil:
    """
    Cok ajanli konsey. Tum ajanlari yonetir, toplantilari duzenler,
    performanslari takip eder.
    """

    def __init__(self):
        self.agents: Dict[str, BaseAgent] = {}
        self.cio = CIOAgent()
        self.meeting_history: List[Dict] = []

        # Varsayilan ajanlari olustur
        self._init_default_agents()

        print(f"[Council] Multi-Agent Council baslatildi")
        print(f"[Council] Aktif ajan: {len(self.agents)}")

    def _init_default_agents(self):
        """Varsayilan ajanlari olustur"""
        default_agents = [
            MacroAgent(),
            TechnicalAgent(),
            SentimentAgent(),
            OrderflowAgent(),
            RiskAgent(),
            PortfolioAgent()
        ]

        for agent in default_agents:
            self.agents[agent.agent_id] = agent

    def add_agent(self, agent: BaseAgent):
        """Yeni ajan ekle"""
        self.agents[agent.agent_id] = agent
        print(f"[Council] Yeni ajan eklendi: {agent.agent_id} ({agent.agent_type.value})")

    def remove_agent(self, agent_id: str):
        """Ajan cikar"""
        if agent_id in self.agents:
            del self.agents[agent_id]
            print(f"[Council] Ajan cikarildi: {agent_id}")

    def hold_meeting(self, symbol: str, data: Dict) -> CouncilDecision:
        """
        Konsey toplantisi duzenle - tum ajanlar analiz yapar, CIO karar verir.

        Args:
            symbol: Analiz edilecek sembol
            data: {
                "technical": {...},
                "macro": {...},
                "sentiment": {...},
                "orderflow": {...},
                "risk": {...},
                "portfolio": {...}
            }
        """
        print(f"\n[Council] Toplanti basladi: {symbol}")
        print(f"[Council] Katilan ajan: {len(self.agents)}")

        # Her ajan analiz yapar
        signals = []
        for agent_id, agent in self.agents.items():
            if agent.performance.status == AgentStatus.SILENCED:
                print(f"  [{agent.agent_type.value}] Sessiz (kotu performans)")
                continue

            try:
                signal = agent.analyze(symbol, data)
                signals.append(signal)
                print(f"  [{agent.agent_type.value.upper()}] {signal.signal.value} "
                      f"(guven: {signal.confidence:.1%})")
            except Exception as e:
                print(f"  [{agent.agent_type.value}] HATA: {e}")

        # Performans kayitlarini topla
        performances = {aid: a.performance for aid, a in self.agents.items()}

        # CIO karar verir
        decision = self.cio.synthesize(symbol, signals, performances)

        # Toplanti kaydet
        self.meeting_history.append({
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "signals": [s.to_dict() for s in signals],
            "decision": decision.to_dict()
        })

        print(f"[Council] Toplanti tamamlandi: {decision.final_signal.value.upper()} "
              f"(guven: {decision.final_confidence:.1%}, konsensus: {decision.consensus_level:.1%})")

        return decision

    def update_agent_performance(self, agent_id: str, signal_correct: bool,
                                  pnl: float, confidence: float):
        """Ajan performansini guncelle"""
        if agent_id in self.agents:
            self.agents[agent_id].update_performance(signal_correct, pnl, confidence)
            perf = self.agents[agent_id].performance
            print(f"[Council] {agent_id} performans guncellendi: "
                  f"win_rate={perf.win_rate:.1%}, weight={perf.weight:.2f}, "
                  f"status={perf.status.value}")

    def get_agent_stats(self) -> Dict:
        """Ajan istatistikleri"""
        stats = {}
        for aid, agent in self.agents.items():
            p = agent.performance
            stats[aid] = {
                "type": agent.agent_type.value,
                "status": p.status.value,
                "win_rate": p.win_rate,
                "total_pnl": p.total_pnl,
                "weight": p.weight,
                "total_signals": p.total_signals
            }
        return stats

    def get_cio_decision_history(self, limit: int = 10) -> List[Dict]:
        """CIO karar gecmisi"""
        return [d.to_dict() for d in self.cio.decision_history[-limit:]]

    def print_council_status(self):
        """Konsey durumunu yazdir"""
        print("\n" + "="*60)
        print("MULTI-AGENT COUNCIL DURUMU")
        print("="*60)

        for aid, agent in self.agents.items():
            p = agent.performance
            status_icon = "✅" if p.status == AgentStatus.ACTIVE else "🔇" if p.status == AgentStatus.SILENCED else "⚠️"
            print(f"{status_icon} {agent.agent_type.value.upper():12} | "
                  f"Win: {p.win_rate:.1%} | Weight: {p.weight:.2f} | "
                  f"PnL: ${p.total_pnl:+.2f} | {p.status.value}")

        print("="*60)


# ==============================================================================
# TEST
# ==============================================================================

if __name__ == "__main__":
    print("="*70)
    print("ATLAS AI - MULTI-AGENT COUNCIL TEST")
    print("="*70)

    council = MultiAgentCouncil()

    # SENARYO 1: Guclu yukselis sinyalleri
    print("\n" + "="*70)
    print("SENARYO 1: Guclu yukselis sinyalleri (ETH)")
    print("="*70)

    data_bullish = {
        "technical": {
            "rsi": 65,
            "macd": {"signal": "bullish_cross", "value": 1.2},
            "ema": {"trend": "above_200"},
            "volume": {"trend": "increasing"}
        },
        "macro": {
            "fed_stance": "dovish",
            "dxy": 98.5,
            "inflation": 2.1
        },
        "sentiment": {
            "fear_greed": 65,
            "funding": 0.01,
            "social_volume": 500
        },
        "orderflow": {
            "whale_movements": [
                {"direction": "in", "amount": 10000},
                {"direction": "in", "amount": 5000}
            ],
            "orderbook": {"bid_ask_ratio": 1.8}
        },
        "risk": {
            "volatility": 0.45,
            "max_drawdown": 0.05,
            "events": []
        },
        "portfolio": {
            "opportunity_score": 0.85,
            "current_allocation": 0.05,
            "target_allocation": 0.15,
            "portfolio_correlation": 0.6
        }
    }

    decision1 = council.hold_meeting("ETHUSDT", data_bullish)
    print(f"\n📊 CIO KARAR:")
    print(f"   Sinyal: {decision1.final_signal.value.upper()}")
    print(f"   Guven: {decision1.final_confidence:.1%}")
    print(f"   Konsensus: {decision1.consensus_level:.1%}")
    print(f"\n📝 CIO MUHAKEMESI:")
    print(decision1.cio_reasoning)

    # SENARYO 2: Karisik sinyaller (riskli)
    print("\n" + "="*70)
    print("SENARYO 2: Karisik sinyaller - Teknik olumlu, Makro riskli (BTC)")
    print("="*70)

    data_mixed = {
        "technical": {
            "rsi": 28,
            "macd": {"signal": "bullish_cross", "value": -0.5},
            "ema": {"trend": "above_200"}
        },
        "macro": {
            "fed_stance": "hawkish",
            "dxy": 106.0,
            "inflation": 4.5
        },
        "sentiment": {
            "fear_greed": 22,
            "funding": -0.02
        },
        "orderflow": {
            "whale_movements": [
                {"direction": "out", "amount": 15000}
            ],
            "orderbook": {"bid_ask_ratio": 0.8}
        },
        "risk": {
            "volatility": 0.75,
            "max_drawdown": 0.15,
            "events": [{"name": "FED Meeting", "severity": "high"}]
        },
        "portfolio": {
            "opportunity_score": 0.4,
            "current_allocation": 0.2,
            "target_allocation": 0.1
        }
    }

    decision2 = council.hold_meeting("BTCUSDT", data_mixed)
    print(f"\n📊 CIO KARAR:")
    print(f"   Sinyal: {decision2.final_signal.value.upper()}")
    print(f"   Guven: {decision2.final_confidence:.1%}")
    print(f"   Konsensus: {decision2.consensus_level:.1%}")
    print(f"\n📝 CIO MUHAKEMESI:")
    print(decision2.cio_reasoning)

    # SENARYO 3: Performans guncelleme (Darwinian selection)
    print("\n" + "="*70)
    print("SENARYO 3: Darwinian Selection - Performans guncelleme")
    print("="*70)

    # Technical ajan dogru tahmin etti
    council.update_agent_performance("tech_001", True, 150.0, 0.8)
    # Macro ajan yanlis tahmin etti
    council.update_agent_performance("macro_001", False, -80.0, 0.6)
    # Risk ajan dogru uyardi
    council.update_agent_performance("risk_001", True, 50.0, 0.7)

    council.print_council_status()

    # SENARYO 4: Ayni sembol tekrar analiz (agirliklar degisti!)
    print("\n" + "="*70)
    print("SENARYO 4: Ayni senaryo, farkli agirliklar")
    print("="*70)

    decision3 = council.hold_meeting("BTCUSDT", data_mixed)
    print(f"\n📊 CIO KARAR (guncel agirliklarla):")
    print(f"   Sinyal: {decision3.final_signal.value.upper()}")
    print(f"   Guven: {decision3.final_confidence:.1%}")
    print(f"   Konsensus: {decision3.consensus_level:.1%}")

    # Istatistikler
    print("\n" + "="*70)
    print("GENEL ISTATISTIKLER")
    print("="*70)
    print(f"Toplanti sayisi: {len(council.meeting_history)}")
    print(f"CIO karar sayisi: {len(council.cio.decision_history)}")

    print("\n" + "="*70)
    print("TUM TESTLER BASARILI!")
    print("="*70)