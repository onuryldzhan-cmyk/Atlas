# -*- coding: utf-8 -*-
"""
ATLAS MACRO ENGINE
Makroekonomik analiz motoru - FED, enflasyon, GDP, DXY, faiz oranlari
"""
import json
import time
import random
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class MacroSignal:
    """Makroekonomik sinyal"""
    indicator: str
    value: float
    previous_value: float
    trend: str  # improving, worsening, stable
    impact: str  # positive, negative, neutral
    confidence: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class MacroOutlook:
    """Makroekonomik gorunum"""
    regime: str  # expansion, contraction, recovery, peak
    risk_level: str  # low, medium, high
    direction: str  # bullish, bearish, neutral
    summary: str
    signals: List[MacroSignal]
    score: float  # -1.0 to +1.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class AtlasMacroEngine:
    """
    Atlas AI Makroekonomik Analiz Motoru
    
    Takip ettigi gostergeler:
    - FED Faiz Orani (Federal Funds Rate)
    - Enflasyon (CPI, PCE)
    - ISM PMI (Uretim sektoru)
    - Istihdam (Non-Farm Payrolls, Issizlik)
    - DXY (Dolar Endeksi)
    - Getiri Egrisi (Yield Curve)
    - VIX (Korku endeksi)
    """
    
    # Makro gosterge tanimlari
    INDICATORS = {
        "fed_rate": {
            "name": "FED Faiz Orani",
            "unit": "%",
            "bullish_threshold": 2.0,   # < 2% = dovish/bullish
            "bearish_threshold": 5.0,   # > 5% = hawkish/bearish
            "weight": 0.25,
        },
        "cpi_yoy": {
            "name": "CPI (Yillik)",
            "unit": "%",
            "bullish_threshold": 2.0,
            "bearish_threshold": 4.0,
            "weight": 0.20,
        },
        "ism_pmi": {
            "name": "ISM PMI",
            "unit": "index",
            "bullish_threshold": 52.0,
            "bearish_threshold": 48.0,
            "weight": 0.15,
        },
        "unemployment": {
            "name": "Issizlik Orani",
            "unit": "%",
            "bullish_threshold": 5.0,   # > 5% = FED dovish olabilir
            "bearish_threshold": 3.5,   # < 3.5% = FED hawkish
            "weight": 0.15,
        },
        "dxy": {
            "name": "DXY (Dolar Endeksi)",
            "unit": "index",
            "bullish_threshold": 100.0,  # < 100 = zayif dolar = kripto icin iyi
            "bearish_threshold": 105.0,  # > 105 = guclu dolar = kripto icin kotu
            "weight": 0.15,
        },
        "vix": {
            "name": "VIX (Korku Endeksi)",
            "unit": "index",
            "bullish_threshold": 20.0,   # < 20 = sakin piyasa
            "bearish_threshold": 30.0,   # > 30 = yuksek volatilite
            "weight": 0.10,
        },
    }
    
    # Makro rejimleri
    REGIMES = {
        "expansion": {"description": "Buyume - Riskli varliklar icin iyi", "crypto_bias": 0.3},
        "contraction": {"description": "Daralma - Guvenli limanlara donus", "crypto_bias": -0.5},
        "recovery": {"description": "Iyilesme - Erken donem frsatlari", "crypto_bias": 0.2},
        "peak": {"description": "Zirve - Dikkatli ol, donus yaklasiyor", "crypto_bias": -0.2},
    }
    
    def __init__(self):
        self.indicators: Dict[str, Dict] = {}
        self.history: List[MacroOutlook] = []
        self.current_outlook: Optional[MacroOutlook] = None
        
    def update_indicator(self, name: str, value: float, previous_value: Optional[float] = None):
        """Makro gosterge guncelle"""
        if name not in self.INDICATORS:
            return False
            
        if previous_value is None:
            previous_value = self.indicators.get(name, {}).get("value", value)
            
        self.indicators[name] = {
            "value": value,
            "previous_value": previous_value,
            "timestamp": datetime.now().isoformat(),
        }
        return True
    
    def _analyze_indicator(self, name: str) -> MacroSignal:
        """Tek bir gostergeyi analiz et"""
        config = self.INDICATORS[name]
        data = self.indicators.get(name, {})
        
        if not data:
            return MacroSignal(name, 0, 0, "stable", "neutral", 0.0)
            
        value = data["value"]
        prev = data["previous_value"]
        
        # Trend belirle
        if value > prev * 1.02:
            trend = "improving" if name in ["ism_pmi"] else "worsening"
        elif value < prev * 0.98:
            trend = "worsening" if name in ["ism_pmi"] else "improving"
        else:
            trend = "stable"
            
        # Etki belirle (kripto perspektifinden)
        bullish_thresh = config["bullish_threshold"]
        bearish_thresh = config["bearish_threshold"]
        
        # Ters gostergeler (issizlik, VIX - yuksek = kotu)
        inverse_indicators = ["unemployment", "vix"]
        
        if name in inverse_indicators:
            if value > bearish_thresh:
                impact = "negative"
            elif value < bullish_thresh:
                impact = "positive"
            else:
                impact = "neutral"
        else:
            if value < bullish_thresh:
                impact = "positive"
            elif value > bearish_thresh:
                impact = "negative"
            else:
                impact = "neutral"
                
        # Guven skoru
        distance_to_neutral = abs(value - (bullish_thresh + bearish_thresh) / 2)
        range_size = bearish_thresh - bullish_thresh
        confidence = min(1.0, distance_to_neutral / (range_size / 2)) if range_size > 0 else 0.5
        
        return MacroSignal(
            indicator=config["name"],
            value=value,
            previous_value=prev,
            trend=trend,
            impact=impact,
            confidence=confidence,
        )
    
    def analyze(self) -> MacroOutlook:
        """Tum makro gostergeleri analiz et ve gorunum olustur"""
        if not self.indicators:
            return MacroOutlook("unknown", "high", "neutral", "Veri yok", [], 0.0)
            
        signals = []
        weighted_score = 0.0
        total_weight = 0.0
        
        for name in self.INDICATORS:
            signal = self._analyze_indicator(name)
            signals.append(signal)
            
            weight = self.INDICATORS[name]["weight"]
            total_weight += weight
            
            # Skor: positive = +1, negative = -1, neutral = 0
            score_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
            weighted_score += score_map[signal.impact] * weight * signal.confidence
        
        # Normalize
        if total_weight > 0:
            weighted_score /= total_weight
            
        # Rejim belirle
        if weighted_score > 0.3:
            regime = "expansion"
            direction = "bullish"
        elif weighted_score > 0.1:
            regime = "recovery"
            direction = "bullish"
        elif weighted_score < -0.3:
            regime = "contraction"
            direction = "bearish"
        elif weighted_score < -0.1:
            regime = "peak"
            direction = "bearish"
        else:
            regime = "recovery"  # Tarafsiz = recovery varsay
            direction = "neutral"
            
        # Risk seviyesi
        vix_signal = next((s for s in signals if s.indicator == "VIX (Korku Endeksi)"), None)
        if vix_signal and vix_signal.value > 25:
            risk_level = "high"
        elif abs(weighted_score) > 0.5:
            risk_level = "high"
        elif abs(weighted_score) > 0.2:
            risk_level = "medium"
        else:
            risk_level = "low"
            
        # Ozet metni olustur
        positive_signals = [s for s in signals if s.impact == "positive"]
        negative_signals = [s for s in signals if s.impact == "negative"]
        
        summary = f"Makro skor: {weighted_score:+.2f}. "
        if positive_signals:
            summary += f"Pozitif: {len(positive_signals)} gosterge. "
        if negative_signals:
            summary += f"Negatif: {len(negative_signals)} gosterge. "
        summary += f"Rejim: {self.REGIMES[regime]['description']}"
        
        outlook = MacroOutlook(
            regime=regime,
            risk_level=risk_level,
            direction=direction,
            summary=summary,
            signals=signals,
            score=weighted_score,
        )
        
        self.current_outlook = outlook
        self.history.append(outlook)
        return outlook
    
    def get_crypto_bias(self) -> float:
        """Kripto varliklara yonelik egilim (-1.0 = cok kotu, +1.0 = cok iyi)"""
        if not self.current_outlook:
            return 0.0
        return self.REGIMES[self.current_outlook.regime]["crypto_bias"] + (self.current_outlook.score * 0.3)
    
    def get_recommendation(self, symbol: str = "BTC") -> Dict:
        """Makro perspektiften oneri ver"""
        if not self.current_outlook:
            return {"action": "HOLD", "confidence": 0.0, "reasoning": "Veri yok"}
            
        bias = self.get_crypto_bias()
        outlook = self.current_outlook
        
        if bias > 0.3:
            action = "BUY"
            confidence = min(1.0, abs(bias))
        elif bias < -0.3:
            action = "SELL"
            confidence = min(1.0, abs(bias))
        else:
            action = "HOLD"
            confidence = 0.5
            
        reasoning = f"Makro skor: {outlook.score:+.2f}. {outlook.summary}"
        
        return {
            "action": action,
            "confidence": confidence,
            "reasoning": reasoning,
            "risk_level": outlook.risk_level,
            "regime": outlook.regime,
        }
    
    def generate_report(self) -> str:
        """Makro raporu olustur"""
        if not self.current_outlook:
            return "Heniz analiz yapilmadi."
            
        outlook = self.current_outlook
        
        report = f"""
==============================================================
           ATLAS MACRO ENGINE - MAKRO RAPORU                  
==============================================================
  Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  Makro Rejim: {outlook.regime.upper()}
  Yon: {outlook.direction.upper()}
  Risk Seviyesi: {outlook.risk_level.upper()}
  Kripto Egilimi: {self.get_crypto_bias():+.2f}
  
  MAKRO SKORU: {outlook.score:+.2f} (-1.0 kotu ... +1.0 iyi)
  
  GOSTERGE ANALIZI:
"""
        for signal in outlook.signals:
            trend_icon = "+" if signal.trend == "improving" else "-" if signal.trend == "worsening" else "="
            impact_icon = "+" if signal.impact == "positive" else "-" if signal.impact == "negative" else "o"
            report += f"    {trend_icon}{impact_icon} {signal.indicator:25s}: {signal.value:8.2f} ({signal.trend:10s}) | Guven: {signal.confidence:.0%}\n"
            
        report += f"""
  KRIPTO ONERISI:
    Eylem: {self.get_recommendation()['action']}
    Guven: {self.get_recommendation()['confidence']:.0%}
    
  {outlook.summary}
==============================================================
"""
        return report
    
    def simulate_scenario(self, scenario_name: str) -> MacroOutlook:
        """Test senaryosu calistir"""
        scenarios = {
            "bullish_macro": {
                "fed_rate": 1.5, "cpi_yoy": 1.8, "ism_pmi": 55.0,
                "unemployment": 5.5, "dxy": 98.0, "vix": 15.0,
            },
            "bearish_macro": {
                "fed_rate": 5.5, "cpi_yoy": 5.0, "ism_pmi": 45.0,
                "unemployment": 3.0, "dxy": 108.0, "vix": 28.0,
            },
            "neutral_macro": {
                "fed_rate": 3.0, "cpi_yoy": 2.5, "ism_pmi": 50.0,
                "unemployment": 4.0, "dxy": 102.0, "vix": 20.0,
            },
            "stagflation": {
                "fed_rate": 6.0, "cpi_yoy": 6.0, "ism_pmi": 47.0,
                "unemployment": 6.0, "dxy": 105.0, "vix": 25.0,
            },
        }
        
        if scenario_name not in scenarios:
            return self.analyze()
            
        # Gostergeleri ayarla
        for name, value in scenarios[scenario_name].items():
            self.update_indicator(name, value)
            
        return self.analyze()


# ==============================================================
# TEST
# ==============================================================

def test_macro_engine():
    """Makro motor testi"""
    print("=" * 60)
    print("ATLAS MACRO ENGINE - MAKROEKONOMIK ANALIZ TESTI")
    print("=" * 60)
    
    engine = AtlasMacroEngine()
    
    # Senaryo 1: Bullish makro
    print("\n[Senaryo 1] Bullish Makro - FED Dovish, Dusuk Enflasyon")
    print("-" * 50)
    outlook = engine.simulate_scenario("bullish_macro")
    print(f"Rejim: {outlook.regime.upper()}")
    print(f"Yon: {outlook.direction.upper()}")
    print(f"Risk: {outlook.risk_level.upper()}")
    print(f"Makro Skor: {outlook.score:+.2f}")
    print(f"Kripto Egilimi: {engine.get_crypto_bias():+.2f}")
    rec = engine.get_recommendation("BTC")
    print(f"Oneri: {rec['action']} (Guven: {rec['confidence']:.0%})")
    
    # Senaryo 2: Bearish makro
    print("\n[Senaryo 2] Bearish Makro - FED Hawkish, Yuksek Enflasyon")
    print("-" * 50)
    outlook2 = engine.simulate_scenario("bearish_macro")
    print(f"Rejim: {outlook2.regime.upper()}")
    print(f"Yon: {outlook2.direction.upper()}")
    print(f"Risk: {outlook2.risk_level.upper()}")
    print(f"Makro Skor: {outlook2.score:+.2f}")
    print(f"Kripto Egilimi: {engine.get_crypto_bias():+.2f}")
    rec2 = engine.get_recommendation("BTC")
    print(f"Oneri: {rec2['action']} (Guven: {rec2['confidence']:.0%})")
    
    # Senaryo 3: Stagflasyon
    print("\n[Senaryo 3] Stagflasyon - En Kotu Senaryo")
    print("-" * 50)
    outlook3 = engine.simulate_scenario("stagflation")
    print(f"Rejim: {outlook3.regime.upper()}")
    print(f"Yon: {outlook3.direction.upper()}")
    print(f"Risk: {outlook3.risk_level.upper()}")
    print(f"Makro Skor: {outlook3.score:+.2f}")
    print(f"Kripto Egilimi: {engine.get_crypto_bias():+.2f}")
    rec3 = engine.get_recommendation("BTC")
    print(f"Oneri: {rec3['action']} (Guven: {rec3['confidence']:.0%})")
    
    # Detayli rapor
    print("\n" + "=" * 60)
    print(engine.generate_report())
    
    print("\n" + "=" * 60)
    print("[OK] MAKRO MOTOR TEST TAMAMLANDI")
    print("=" * 60)


if __name__ == "__main__":
    test_macro_engine()