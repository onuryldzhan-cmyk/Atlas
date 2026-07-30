# -*- coding: utf-8 -*-
"""
ATLAS EXPLAINABILITY ENGINE
Karar aciklama motoru - Neden al/sat yapildigini raporlar
"""
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field


@dataclass
class Explanation:
    """Karar aciklamasi"""
    decision_id: str
    symbol: str
    action: str
    confidence: float
    summary: str
    factors: List[Dict]
    reasoning_chain: List[str]
    risk_assessment: str
    alternatives: List[str]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class AtlasExplainability:
    """
    Atlas AI Karar Aciklama Motoru
    
    Her kararin NEDEN verildigini aciklar:
    - Hangi faktorler etkili oldu?
    - Her faktorun agirligi neydi?
    - Alternatifler neden reddedildi?
    - Risk degerlendirmesi nedir?
    """
    
    # Karar sablonlari
    DECISION_TEMPLATES = {
        "BUY": {
            "positive": "{symbol} icin guclu alim sinyali. {factors}",
            "cautious": "{symbol} icin dikkatli alim. {factors}",
        },
        "SELL": {
            "positive": "{symbol} icin guclu satis sinyali. {factors}",
            "cautious": "{symbol} icin dikkatli satis. {factors}",
        },
        "HOLD": {
            "neutral": "{symbol} icin bekleme karari. {factors}",
            "uncertain": "{symbol} icin belirsizlik nedeniyle pas. {factors}",
        },
        "REDUCE": {
            "default": "{symbol} pozisyonu kucultuluyor. {factors}",
        },
        "INCREASE": {
            "default": "{symbol} pozisyonu artiriliyor. {factors}",
        },
    }
    
    # Emoji haritasi
    EMOJI_MAP = {
        "BUY": "+",
        "SELL": "-",
        "HOLD": "o",
        "REDUCE": "v",
        "INCREASE": "^",
        "positive": "+",
        "negative": "-",
        "neutral": "o",
        "high": "!!",
        "medium": "!",
        "low": "",
    }
    
    def __init__(self):
        self.explanation_history: List[Explanation] = []
        
    def explain(self, decision: Dict, context: Dict = None) -> Explanation:
        """
        Bir karari acikla
        
        decision: {
            "symbol": "BTC",
            "action": "BUY",
            "confidence": 0.75,
            "factors": [...],
            "agents": [...],
            ...
        }
        """
        if context is None:
            context = {}
            
        symbol = decision.get("symbol", "UNKNOWN")
        action = decision.get("action", "HOLD")
        confidence = decision.get("confidence", 0.0)
        factors = decision.get("factors", [])
        agents = decision.get("agents", [])
        risk_level = decision.get("risk_level", "medium")
        
        # Karar ID olustur
        decision_id = f"{symbol}_{action}_{int(time.time())}"
        
        # Ozet olustur
        summary = self._generate_summary(symbol, action, confidence, factors, risk_level)
        
        # Faktorleri detaylandir
        detailed_factors = self._explain_factors(factors, confidence)
        
        # Muhakeme zinciri
        reasoning_chain = self._build_reasoning_chain(action, factors, agents, confidence)
        
        # Risk degerlendirmesi
        risk_assessment = self._assess_risk(risk_level, factors, confidence)
        
        # Alternatifler
        alternatives = self._generate_alternatives(action, symbol, factors)
        
        explanation = Explanation(
            decision_id=decision_id,
            symbol=symbol,
            action=action,
            confidence=confidence,
            summary=summary,
            factors=detailed_factors,
            reasoning_chain=reasoning_chain,
            risk_assessment=risk_assessment,
            alternatives=alternatives,
        )
        
        self.explanation_history.append(explanation)
        return explanation
    
    def _generate_summary(self, symbol: str, action: str, confidence: float, 
                          factors: List[Dict], risk_level: str) -> str:
        """Karar ozeti olustur"""
        # Faktor ozeti
        if factors:
            top_factor = max(factors, key=lambda x: x.get("weight", 0))
            factor_summary = f"En onemli faktor: {top_factor.get('name', 'Bilinmiyor')} ({top_factor.get('weight', 0):.0%} agirlik)"
        else:
            factor_summary = "Faktor bilgisi mevcut degil."
            
        # Sablon sec
        if action in ["BUY", "INCREASE"]:
            template_key = "positive" if confidence > 0.7 else "cautious"
        elif action in ["SELL", "REDUCE"]:
            template_key = "positive" if confidence > 0.7 else "cautious"
        else:
            template_key = "neutral" if confidence > 0.5 else "uncertain"
            
        template = self.DECISION_TEMPLATES.get(action, {}).get(template_key, "{symbol} karari: {factors}")
        
        return template.format(symbol=symbol, factors=factor_summary)
    
    def _explain_factors(self, factors: List[Dict], confidence: float) -> List[Dict]:
        """Her faktoru acikla"""
        explained = []
        
        for factor in factors:
            name = factor.get("name", "Bilinmiyor")
            weight = factor.get("weight", 0.0)
            value = factor.get("value", 0.0)
            impact = factor.get("impact", "neutral")
            
            # Faktor aciklamasi
            if impact == "positive":
                direction = "karari destekliyor"
            elif impact == "negative":
                direction = "karara karsi"
            else:
                direction = "notr etki"
                
            explained.append({
                "name": name,
                "weight": weight,
                "value": value,
                "impact": impact,
                "explanation": f"{name}: {value} degeri ile {direction} ({weight:.0%} agirlik)",
                "contribution": weight * (1.0 if impact == "positive" else -1.0 if impact == "negative" else 0.0),
            })
            
        # Sirala (en etkiliden en az etkiliye)
        explained.sort(key=lambda x: abs(x["contribution"]), reverse=True)
        return explained
    
    def _build_reasoning_chain(self, action: str, factors: List[Dict], 
                                agents: List[str], confidence: float) -> List[str]:
        """Muhakeme zinciri olustur"""
        chain = []
        
        # 1. Durum tespiti
        chain.append(f"1. DURUM ANALIZI: {len(factors)} faktor degerlendirildi.")
        
        # 2. Faktor agirliklari
        positive = [f for f in factors if f.get("impact") == "positive"]
        negative = [f for f in factors if f.get("impact") == "negative"]
        chain.append(f"2. FAKTOR DAGILIMI: {len(positive)} pozitif, {len(negative)} negatif, {len(factors) - len(positive) - len(negative)} notr.")
        
        # 3. Ajan konsensusu
        if agents:
            chain.append(f"3. AJAN KONSENSUSU: {len(agents)} ajan degerlendirdi. Guven: {confidence:.0%}")
        
        # 4. Karar mantigi
        if action in ["BUY", "INCREASE"]:
            chain.append(f"4. KARAR MANTIGI: Pozitif faktorler agir basiyor. Alim onerildi.")
        elif action in ["SELL", "REDUCE"]:
            chain.append(f"4. KARAR MANTIGI: Negatif faktorler agir basiyor. Satis onerildi.")
        else:
            chain.append(f"4. KARAR MANTIGI: Belirsizlik yuksek. Bekleme tercih edildi.")
            
        # 5. Guven degerlendirmesi
        if confidence >= 0.8:
            chain.append(f"5. GUVEN: Yuksek ({confidence:.0%}). Karar guclu.")
        elif confidence >= 0.6:
            chain.append(f"5. GUVEN: Orta ({confidence:.0%}). Dikkatli olunmali.")
        else:
            chain.append(f"5. GUVEN: Dusuk ({confidence:.0%}). Ek onay gerekli.")
            
        return chain
    
    def _assess_risk(self, risk_level: str, factors: List[Dict], confidence: float) -> str:
        """Risk degerlendirmesi yap"""
        risk_icon = self.EMOJI_MAP.get(risk_level, "")
        
        # Risk faktorleri
        risk_factors = [f for f in factors if f.get("impact") == "negative"]
        
        assessment = f"{risk_icon} Risk Seviyesi: {risk_level.upper()}\n\n"
        
        if risk_level == "high":
            assessment += "YUKSEK RISK UYARISI:\n"
            assessment += "- Pozisyon boyutu kucuk tutulmali\n"
            assessment += "- Stop loss mutlaka kullanilmali\n"
            assessment += "- Piyasa takibi siklastirilmali\n"
        elif risk_level == "medium":
            assessment += "ORTA RISK:\n"
            assessment += "- Normal risk yonetimi uygulanabilir\n"
            assessment += "- Stop loss onerilir\n"
        else:
            assessment += "DUSUK RISK:\n"
            assessment += "- Standart pozisyon yonetimi\n"
            
        if risk_factors:
            assessment += f"\nRisk faktorleri ({len(risk_factors)} adet):\n"
            for rf in risk_factors[:3]:
                assessment += f"  - {rf.get('name', 'Bilinmiyor')}: {rf.get('value', 0)}\n"
                
        assessment += f"\nGuven faktori: {confidence:.0%} - "
        if confidence < 0.6:
            assessment += "Dusuk guven riski artirir."
        else:
            assessment += "Guven seviyesi kabul edilebilir."
            
        return assessment
    
    def _generate_alternatives(self, action: str, symbol: str, factors: List[Dict]) -> List[str]:
        """Alternatif kararlari listele"""
        alternatives = []
        
        if action == "BUY":
            alternatives = [
                f"Bekle ve {symbol} dususunu gerceklesmesini bekle (daha iyi giris)",
                f"Kucuk pozisyon ile basla, sonra ekle (DCA stratejisi)",
                f"Benzer varliklara bak (diversifikasyon)",
            ]
        elif action == "SELL":
            alternatives = [
                f"Pozisyonu kismen kapat, tamamen degil (kademeli cikis)",
                f"Stop loss kullan, otomatik cikis planla",
                f"Kisa vadeli hedge pozisyonu ac",
            ]
        elif action == "HOLD":
            alternatives = [
                f"Kucuk test pozisyonu ac (piyasayi hisset)",
                f"Diger zaman dilimlerinde analiz yap (4h, 1d)",
                f"Makro haberleri bekle (FED, enflasyon)",
            ]
        else:
            alternatives = [
                "Mevcut pozisyonu koru",
                "Risk yonetimini gozden gecir",
                "Piyasa kosullarini izlemeye devam et",
            ]
            
        return alternatives
    
    def generate_report(self, explanation: Explanation) -> str:
        """Aciklama raporu olustur"""
        emoji = self.EMOJI_MAP.get(explanation.action, "o")
        
        report = f"""
==============================================================
        ATLAS EXPLAINABILITY - KARAR ACIKLAMA RAPORU          
==============================================================
  Karar ID: {explanation.decision_id}
  Sembol: {explanation.symbol}
  Eylem: {emoji} {explanation.action}
  Guven: {explanation.confidence:.0%}
  
  OZET:
  {explanation.summary}
  
  MUHAKEME ZINCIRI:
"""
        for step in explanation.reasoning_chain:
            report += f"  {step}\n"
            
        report += f"""
  ETKILI FAKTORLER:
"""
        for i, factor in enumerate(explanation.factors[:5], 1):
            impact_icon = self.EMOJI_MAP.get(factor['impact'], 'o')
            report += f"  {i}. {impact_icon} {factor['explanation']}\n"
            report += f"     Katki: {factor['contribution']:+.3f}\n"
            
        report += f"""
  RISK DEGERLENDIRMESI:
{explanation.risk_assessment}
  
  ALTERNATIFLER:
"""
        for i, alt in enumerate(explanation.alternatives, 1):
            report += f"  {i}. {alt}\n"
            
        report += f"""
==============================================================
"""
        return report
    
    def get_decision_history(self, symbol: Optional[str] = None) -> List[Explanation]:
        """Karar gecmisini al"""
        if symbol:
            return [e for e in self.explanation_history if e.symbol == symbol]
        return self.explanation_history
    
    def compare_decisions(self, decision_ids: List[str]) -> str:
        """Iki karari karsilastir"""
        decisions = [e for e in self.explanation_history if e.decision_id in decision_ids]
        
        if len(decisions) < 2:
            return "Karsilastirma icin en az 2 karar gerekli."
            
        report = """
==============================================================
           KARAR KARSILASTIRMA RAPORU                        
==============================================================
"""
        for d in decisions:
            emoji = self.EMOJI_MAP.get(d.action, "o")
            report += f"\n  {emoji} {d.symbol} | {d.action} | Guven: {d.confidence:.0%}\n"
            report += f"  {d.summary}\n"
            
        return report


# ==============================================================
# TEST
# ==============================================================

def test_explainability():
    """Aciklama motoru testi"""
    print("=" * 60)
    print("ATLAS EXPLAINABILITY - KARAR ACIKLAMA TESTI")
    print("=" * 60)
    
    explainer = AtlasExplainability()
    
    # Senaryo 1: Guclu alim karari
    print("\n[Senaryo 1] BTC Guclu Alim - Aciklama")
    print("-" * 50)
    
    decision1 = {
        "symbol": "BTC",
        "action": "BUY",
        "confidence": 0.82,
        "risk_level": "medium",
        "factors": [
            {"name": "RSI Momentum", "weight": 0.25, "value": 65, "impact": "positive"},
            {"name": "MACD Crossover", "weight": 0.20, "value": 1, "impact": "positive"},
            {"name": "FED Dovish", "weight": 0.20, "value": 2.5, "impact": "positive"},
            {"name": "DXY Dusus", "weight": 0.15, "value": 98, "impact": "positive"},
            {"name": "Hacim Artisi", "weight": 0.10, "value": 1.5, "impact": "positive"},
            {"name": "Volatilite Yuksek", "weight": 0.10, "value": 25, "impact": "negative"},
        ],
        "agents": ["technical_analyst", "macro_engine", "sentiment_analyst"],
    }
    
    exp1 = explainer.explain(decision1)
    print(explainer.generate_report(exp1))
    
    # Senaryo 2: Zayif satis karari
    print("\n[Senaryo 2] ETH Satis - Aciklama")
    print("-" * 50)
    
    decision2 = {
        "symbol": "ETH",
        "action": "SELL",
        "confidence": 0.75,
        "risk_level": "high",
        "factors": [
            {"name": "RSI Asiri Alim", "weight": 0.25, "value": 78, "impact": "negative"},
            {"name": "Death Cross", "weight": 0.20, "value": 1, "impact": "negative"},
            {"name": "FED Hawkish", "weight": 0.20, "value": 5.5, "impact": "negative"},
            {"name": "DXY Yukselis", "weight": 0.15, "value": 105, "impact": "negative"},
            {"name": "Hacim Dususu", "weight": 0.10, "value": 0.7, "impact": "negative"},
            {"name": "Sosyal Medya Pozitif", "weight": 0.10, "value": 0.6, "impact": "positive"},
        ],
        "agents": ["technical_analyst", "macro_engine", "risk_manager"],
    }
    
    exp2 = explainer.explain(decision2)
    print(explainer.generate_report(exp2))
    
    # Senaryo 3: Belirsizlik - HOLD
    print("\n[Senaryo 3] SOL Bekleme - Aciklama")
    print("-" * 50)
    
    decision3 = {
        "symbol": "SOL",
        "action": "HOLD",
        "confidence": 0.45,
        "risk_level": "medium",
        "factors": [
            {"name": "Kariskik Sinyaller", "weight": 0.30, "value": 50, "impact": "neutral"},
            {"name": "Dusuk Hacim", "weight": 0.25, "value": 0.5, "impact": "negative"},
            {"name": "Makro Belirsiz", "weight": 0.25, "value": 3.0, "impact": "neutral"},
            {"name": "Direnç Seviyesi", "weight": 0.20, "value": 150, "impact": "negative"},
        ],
        "agents": ["technical_analyst"],
    }
    
    exp3 = explainer.explain(decision3)
    print(explainer.generate_report(exp3))
    
    # Karar gecmisi
    print("\n" + "=" * 60)
    print("KARAR GECMISI OZETI:")
    history = explainer.get_decision_history()
    for h in history:
        print(f"  {h.symbol:6s} | {h.action:6s} | Guven: {h.confidence:.0%} | {h.timestamp[:19]}")
    
    print("\n" + "=" * 60)
    print("[OK] ACIKLAMA MOTORU TEST TAMAMLANDI")
    print("=" * 60)


if __name__ == "__main__":
    test_explainability()