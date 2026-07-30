# -*- coding: utf-8 -*-
"""
ATLAS CIO (Chief Investment Officer)
Tum ajanlari yoneten, portfoy kararlarini veren bas yatirim sorumlusu.
"""
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field


@dataclass
class AgentRecommendation:
    """Bir ajanin onerisi"""
    agent_name: str
    symbol: str
    action: str  # BUY, SELL, HOLD, REDUCE, INCREASE
    confidence: float  # 0.0 - 1.0
    reasoning: str
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    time_horizon: str = "medium"  # short, medium, long
    risk_level: str = "medium"  # low, medium, high
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PortfolioDecision:
    """CIO'nun nihai portfoy karari"""
    symbol: str
    final_action: str
    confidence: float
    position_size_pct: float  # Portfoyun yuzde kaci
    stop_loss: Optional[float]
    take_profit: Optional[float]
    reasoning: str
    contributing_agents: List[str]
    risk_score: float
    expected_return: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class AtlasCIO:
    """
    Atlas AI Chief Investment Officer
    - Tum ajanlarin onerilerini toplar
    - Agirlikli oylama yapar
    - Risk yonetimi ile birlestirir
    - Nihai portfoy kararini verir
    """
    
    # Ajan agirliklari (guvenilirlik skorlarina gore dinamik)
    DEFAULT_AGENT_WEIGHTS = {
        "technical_analyst": 0.20,
        "macro_engine": 0.20,
        "sentiment_analyst": 0.15,
        "risk_manager": 0.20,
        "pattern_recognizer": 0.15,
        "liquidity_analyst": 0.10,
    }
    
    # Risk seviyesine gore maksimum pozisyon boyutu
    RISK_POSITION_LIMITS = {
        "low": 0.15,      # Portfoyun max %15'i
        "medium": 0.10,   # Portfoyun max %10'u
        "high": 0.05,     # Portfoyun max %5'i
    }
    
    # Minimum guven esigi
    MIN_CONFIDENCE_THRESHOLD = 0.60
    
    def __init__(self, total_capital: float = 10000.0):
        self.total_capital = total_capital
        self.agent_weights = self.DEFAULT_AGENT_WEIGHTS.copy()
        self.agent_performance: Dict[str, List[float]] = {k: [] for k in self.agent_weights}
        self.decision_history: List[PortfolioDecision] = []
        self.current_positions: Dict[str, Dict] = {}
        self.market_regime: str = "neutral"  # bullish, bearish, neutral, volatile
        
    def update_market_regime(self, regime: str):
        """Piyasa rejimini guncelle ve agirliklari ayarla"""
        self.market_regime = regime
        
        # Rejime gore agirliklari dinamik ayarla
        if regime == "bullish":
            self.agent_weights = {
                "technical_analyst": 0.25,
                "macro_engine": 0.15,
                "sentiment_analyst": 0.20,
                "risk_manager": 0.15,
                "pattern_recognizer": 0.15,
                "liquidity_analyst": 0.10,
            }
        elif regime == "bearish":
            self.agent_weights = {
                "technical_analyst": 0.15,
                "macro_engine": 0.25,
                "sentiment_analyst": 0.10,
                "risk_manager": 0.25,
                "pattern_recognizer": 0.10,
                "liquidity_analyst": 0.15,
            }
        elif regime == "volatile":
            self.agent_weights = {
                "technical_analyst": 0.20,
                "macro_engine": 0.15,
                "sentiment_analyst": 0.15,
                "risk_manager": 0.25,
                "pattern_recognizer": 0.10,
                "liquidity_analyst": 0.15,
            }
        else:  # neutral
            self.agent_weights = self.DEFAULT_AGENT_WEIGHTS.copy()
            
    def collect_recommendations(self, recommendations: List[AgentRecommendation]) -> Dict:
        """Tum ajan onerilerini topla ve analiz et"""
        if not recommendations:
            return {"error": "No recommendations provided"}
            
        # Sembol bazinda grupla
        symbol_recs: Dict[str, List[AgentRecommendation]] = {}
        for rec in recommendations:
            if rec.symbol not in symbol_recs:
                symbol_recs[rec.symbol] = []
            symbol_recs[rec.symbol].append(rec)
            
        return symbol_recs
    
    def _calculate_weighted_score(self, recommendations: List[AgentRecommendation]) -> Dict:
        """Agirlikli oylama skoru hesapla"""
        action_scores = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0, "REDUCE": 0.0, "INCREASE": 0.0}
        total_weight = 0.0
        confidences = []
        reasoning_parts = []
        contributing = []
        
        for rec in recommendations:
            weight = self.agent_weights.get(rec.agent_name, 0.1)
            weighted_confidence = rec.confidence * weight
            
            action_scores[rec.action] += weighted_confidence
            total_weight += weight
            confidences.append(rec.confidence)
            contributing.append(rec.agent_name)
            reasoning_parts.append(f"[{rec.agent_name}] {rec.action} (conf: {rec.confidence:.2f}): {rec.reasoning[:50]}...")
            
        # Normalize
        if total_weight > 0:
            for action in action_scores:
                action_scores[action] /= total_weight
                
        # En yuksek skorlu aksiyon
        best_action = max(action_scores, key=action_scores.get)
        best_score = action_scores[best_action]
        
        # Ortalama guven
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        
        return {
            "action_scores": action_scores,
            "best_action": best_action,
            "best_score": best_score,
            "avg_confidence": avg_confidence,
            "reasoning": "\n".join(reasoning_parts),
            "contributing_agents": contributing,
        }
    
    def _calculate_position_size(self, action: str, confidence: float, 
                                  risk_level: str, current_price: float) -> Dict:
        """Pozisyon boyutunu hesapla"""
        limit = self.RISK_POSITION_LIMITS.get(risk_level, 0.10)
        
        # Guvene gore ayarla
        if confidence >= 0.85:
            size_multiplier = 1.0
        elif confidence >= 0.75:
            size_multiplier = 0.8
        elif confidence >= 0.65:
            size_multiplier = 0.6
        else:
            size_multiplier = 0.4
            
        position_size_pct = limit * size_multiplier
        
        # SELL/REDUCE durumunda pozisyonu kapat
        if action in ["SELL", "REDUCE"]:
            position_size_pct = -position_size_pct
            
        # Dolar degeri
        position_value = self.total_capital * abs(position_size_pct)
        
        # Stop loss ve take profit hesapla
        if action in ["BUY", "INCREASE"]:
            stop_loss = current_price * 0.95  # %5 stop loss
            take_profit = current_price * 1.10  # %10 take profit
        elif action in ["SELL", "REDUCE"]:
            stop_loss = current_price * 1.05
            take_profit = current_price * 0.90
        else:
            stop_loss = None
            take_profit = None
            
        return {
            "position_size_pct": position_size_pct,
            "position_value": position_value,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }
    
    def make_decision(self, symbol: str, recommendations: List[AgentRecommendation],
                      current_price: float) -> PortfolioDecision:
        """Nihai portfoy kararini ver"""
        
        # Agirlikli skor hesapla
        analysis = self._calculate_weighted_score(recommendations)
        
        best_action = analysis["best_action"]
        confidence = analysis["avg_confidence"]
        
        # Guven esigi kontrolu
        if confidence < self.MIN_CONFIDENCE_THRESHOLD:
            best_action = "HOLD"
            confidence = 1.0 - confidence  # Dusuk guven = bekle
            
        # Risk seviyesini belirle (en yuksek risk)
        risk_levels = [rec.risk_level for rec in recommendations]
        risk_counts = {"low": 0, "medium": 0, "high": 0}
        for rl in risk_levels:
            risk_counts[rl] = risk_counts.get(rl, 0) + 1
        overall_risk = max(risk_counts, key=risk_counts.get)
        
        # Pozisyon boyutu
        sizing = self._calculate_position_size(best_action, confidence, overall_risk, current_price)
        
        # Beklenen getiri (basit tahmin)
        if best_action in ["BUY", "INCREASE"]:
            expected_return = (sizing["take_profit"] - current_price) / current_price * 100
        elif best_action in ["SELL", "REDUCE"]:
            expected_return = (current_price - sizing["take_profit"]) / current_price * 100
        else:
            expected_return = 0.0
            
        # Risk skoru (0-1)
        risk_score = 0.5
        if overall_risk == "high":
            risk_score = 0.8
        elif overall_risk == "low":
            risk_score = 0.2
            
        decision = PortfolioDecision(
            symbol=symbol,
            final_action=best_action,
            confidence=confidence,
            position_size_pct=sizing["position_size_pct"],
            stop_loss=sizing["stop_loss"],
            take_profit=sizing["take_profit"],
            reasoning=analysis["reasoning"],
            contributing_agents=analysis["contributing_agents"],
            risk_score=risk_score,
            expected_return=expected_return,
        )
        
        self.decision_history.append(decision)
        return decision
    
    def evaluate_agents(self, symbol: str, actual_return: float):
        """Ajan performansini degerlendir ve agirliklari guncelle"""
        # Son karari bul
        recent_decisions = [d for d in self.decision_history if d.symbol == symbol]
        if not recent_decisions:
            return
            
        last_decision = recent_decisions[-1]
        
        # Her ajanin performansini kaydet
        for agent_name in last_decision.contributing_agents:
            if agent_name not in self.agent_performance:
                self.agent_performance[agent_name] = []
            self.agent_performance[agent_name].append(actual_return)
            
        # Agirliklari guncelle (son 10 performans ortalamasi)
        self._update_weights()
        
    def _update_weights(self):
        """Ajan agirliklarini performansa gore guncelle"""
        new_weights = {}
        total_score = 0
        
        for agent_name, performances in self.agent_performance.items():
            if len(performances) >= 3:
                # Son 10 performansin ortalamasi
                recent = performances[-10:]
                avg_performance = sum(recent) / len(recent)
                # Normalize (pozitif = iyi)
                score = max(0.05, min(0.40, 0.20 + avg_performance * 0.01))
                new_weights[agent_name] = score
                total_score += score
                
        if total_score > 0:
            # Normalize et
            for agent in new_weights:
                new_weights[agent] /= total_score
            self.agent_weights.update(new_weights)
    
    def get_portfolio_summary(self) -> Dict:
        """Portfoy ozetini al"""
        total_exposure = sum(abs(d.position_size_pct) for d in self.decision_history[-10:])
        
        return {
            "total_capital": self.total_capital,
            "market_regime": self.market_regime,
            "agent_weights": self.agent_weights,
            "active_decisions": len([d for d in self.decision_history if d.final_action != "HOLD"]),
            "total_exposure": total_exposure,
            "recent_decisions": [
                {
                    "symbol": d.symbol,
                    "action": d.final_action,
                    "confidence": d.confidence,
                    "size_pct": d.position_size_pct,
                }
                for d in self.decision_history[-5:]
            ],
        }
    
    def generate_report(self) -> str:
        """CIO raporu olustur"""
        summary = self.get_portfolio_summary()
        
        report = f"""
==============================================================
           ATLAS CIO - PORTFOY YONETIM RAPORU               
==============================================================
  Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  Piyasa Rejimi: {summary['market_regime'].upper()}
  Toplam Sermaye: ${summary['total_capital']:,.2f}
  
  AKTIF AJAN AGIRLIKLARI:
"""
        for agent, weight in summary['agent_weights'].items():
            report += f"    * {agent:25s}: {weight:.2%}\n"
            
        report += f"""
  SON KARARLAR:
"""
        for d in summary['recent_decisions']:
            emoji = "+" if d['action'] in ["BUY", "INCREASE"] else "-" if d['action'] in ["SELL", "REDUCE"] else "o"
            report += f"    {emoji} {d['symbol']:8s} | {d['action']:8s} | Guven: {d['confidence']:.1%} | Boyut: {d['size_pct']:+.1%}\n"
            
        report += f"""
  TOPLAM ACIK POZISYON: {summary['active_decisions']}
  TOPLAM MARUZIYET: {summary['total_exposure']:.1%}
==============================================================
"""
        return report


# ==============================================================
# TEST
# ==============================================================

def test_cio():
    """CIO testi"""
    print("=" * 60)
    print("ATLAS CIO - CHIEF INVESTMENT OFFICER TEST")
    print("=" * 60)
    
    cio = AtlasCIO(total_capital=10000.0)
    
    # Senaryo 1: Bullish piyasa, BTC guclu sinyal
    print("\n[Senaryo 1] Bullish Piyasa - BTC Guclu Alim Sinyali")
    print("-" * 50)
    cio.update_market_regime("bullish")
    
    recs_btc = [
        AgentRecommendation("technical_analyst", "BTC", "BUY", 0.85, "RSI 65, MACD bullish crossover", 72000, 68000, "medium", "medium"),
        AgentRecommendation("macro_engine", "BTC", "BUY", 0.80, "FED dovish, DXY dusuyor", 72000, 68000, "medium", "low"),
        AgentRecommendation("sentiment_analyst", "BTC", "BUY", 0.75, "Sosyal medya pozitif", 72000, 68000, "short", "medium"),
        AgentRecommendation("risk_manager", "BTC", "HOLD", 0.60, "Volatilite yuksek, dikkatli ol", 72000, 68000, "medium", "high"),
        AgentRecommendation("pattern_recognizer", "BTC", "BUY", 0.70, "Cup and handle formasyonu", 72000, 68000, "medium", "medium"),
    ]
    
    decision = cio.make_decision("BTC", recs_btc, 70000.0)
    print(f"[+] KARAR: {decision.final_action}")
    print(f"   Guven: {decision.confidence:.1%}")
    print(f"   Pozisyon Boyutu: {decision.position_size_pct:+.1%}")
    print(f"   Stop Loss: ${decision.stop_loss:,.2f}" if decision.stop_loss else "   Stop Loss: Yok")
    print(f"   Take Profit: ${decision.take_profit:,.2f}" if decision.take_profit else "   Take Profit: Yok")
    print(f"   Beklenen Getiri: {decision.expected_return:+.1f}%")
    print(f"   Risk Skoru: {decision.risk_score:.2f}")
    
    # Senaryo 2: Bearish piyasa, ETH zayif
    print("\n[Senaryo 2] Bearish Piyasa - ETH Satis Sinyali")
    print("-" * 50)
    cio.update_market_regime("bearish")
    
    recs_eth = [
        AgentRecommendation("technical_analyst", "ETH", "SELL", 0.80, "RSI 75 asiri alim, death cross", 3800, 4200, "short", "high"),
        AgentRecommendation("macro_engine", "ETH", "SELL", 0.85, "FED hawkish, enflasyon artiyor", 3800, 4200, "medium", "high"),
        AgentRecommendation("sentiment_analyst", "ETH", "HOLD", 0.55, "Karisik sinyaller", 3800, 4200, "medium", "medium"),
        AgentRecommendation("risk_manager", "ETH", "SELL", 0.90, "Yuksek korelasyon riski, stop onerilir", 3800, 4200, "short", "high"),
        AgentRecommendation("pattern_recognizer", "ETH", "SELL", 0.75, "Head and shoulders formasyonu", 3800, 4200, "medium", "high"),
    ]
    
    decision2 = cio.make_decision("ETH", recs_eth, 4000.0)
    print(f"[-] KARAR: {decision2.final_action}")
    print(f"   Guven: {decision2.confidence:.1%}")
    print(f"   Pozisyon Boyutu: {decision2.position_size_pct:+.1%}")
    print(f"   Stop Loss: ${decision2.stop_loss:,.2f}" if decision2.stop_loss else "   Stop Loss: Yok")
    print(f"   Take Profit: ${decision2.take_profit:,.2f}" if decision2.take_profit else "   Take Profit: Yok")
    print(f"   Beklenen Getiri: {decision2.expected_return:+.1f}%")
    print(f"   Risk Skoru: {decision2.risk_score:.2f}")
    
    # Senaryo 3: Dusuk guven - HOLD
    print("\n[Senaryo 3] Dusuk Guven - SOL Kararsiz")
    print("-" * 50)
    
    recs_sol = [
        AgentRecommendation("technical_analyst", "SOL", "BUY", 0.50, "Karisik sinyaller", 150, 140, "medium", "medium"),
        AgentRecommendation("macro_engine", "SOL", "HOLD", 0.45, "Belirsizlik yuksek", 150, 140, "medium", "medium"),
        AgentRecommendation("sentiment_analyst", "SOL", "SELL", 0.40, "Negatif sosyal medya", 150, 140, "short", "medium"),
    ]
    
    decision3 = cio.make_decision("SOL", recs_sol, 145.0)
    print(f"[o] KARAR: {decision3.final_action}")
    print(f"   Guven: {decision3.confidence:.1%}")
    print(f"   Pozisyon Boyutu: {decision3.position_size_pct:+.1%}")
    print(f"   (Dusuk guven nedeniyle bekleme modu)")
    
    # Rapor
    print("\n" + "=" * 60)
    print(cio.generate_report())
    
    # Portfoy ozeti
    summary = cio.get_portfolio_summary()
    print(f"\n[*] PORTFOY OZETI:")
    print(f"   Toplam Sermaye: ${summary['total_capital']:,.2f}")
    print(f"   Piyasa Rejimi: {summary['market_regime']}")
    print(f"   Aktif Kararlar: {summary['active_decisions']}")
    print(f"   Toplam Maruziyet: {summary['total_exposure']:.1%}")
    
    print("\n" + "=" * 60)
    print("[OK] CIO TEST TAMAMLANDI")
    print("=" * 60)


if __name__ == "__main__":
    test_cio()