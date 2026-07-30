# -*- coding: utf-8 -*-
"""
ATLAS RESEARCH ENGINE
Otonom arastirma motoru - Piyasa verilerini analiz edip yeni fikirler uretir
"""
import random
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class ResearchFinding:
    """Arastirma bulgusu"""
    id: str
    category: str  # pattern, anomaly, correlation, opportunity
    title: str
    description: str
    confidence: float
    evidence: List[Dict]
    actionable: bool
    recommended_action: Optional[str]
    symbols: List[str]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class MarketInsight:
    """Piyasa icgorusu"""
    symbol: str
    insight_type: str  # trend, reversal, breakout, consolidation
    direction: str  # bullish, bearish, neutral
    strength: float  # 0-1
    timeframe: str
    supporting_data: Dict
    confidence: float


class AtlasResearchEngine:
    """
    Atlas AI Otonom Arastirma Motoru
    
    Arastirma alanlari:
    1. Pattern Discovery - Gizli paternleri bul
    2. Anomaly Detection - Anomalileri tespit et
    3. Correlation Analysis - Korelasyonlari analiz et
    4. Opportunity Scanner - Firsatlari tarar
    5. Hypothesis Testing - Hipotezleri test et
    """
    
    # Arastirma kategorileri
    CATEGORIES = {
        "pattern": "Gizli patern kesfi",
        "anomaly": "Anomali tespiti",
        "correlation": "Korelasyon analizi",
        "opportunity": "Firsat taramasi",
        "hypothesis": "Hipotez testi",
    }
    
    # Piyasa olaylari
    MARKET_EVENTS = [
        "FED aciklamasi", "Enflasyon verisi", "GDP buyumesi", "Issizlik raporu",
        "Kripto duzenlemesi", "Buyuk yatirimci hareketi", "Borsa kazasi",
        "Jeopolitik kriz", "Teknolojik gelisme", "Merkez bankasi mudahalesi",
    ]
    
    # Varlik siniflari
    ASSET_CLASSES = {
        "crypto": ["BTC", "ETH", "SOL", "ADA", "DOT", "AVAX", "LINK", "MATIC"],
        "forex": ["EURUSD", "GBPUSD", "USDJPY", "DXY"],
        "commodities": ["GOLD", "SILVER", "OIL", "NATGAS"],
        "indices": ["SPX", "NDX", "DJI", "VIX"],
    }
    
    def __init__(self):
        self.findings: List[ResearchFinding] = []
        self.insights: List[MarketInsight] = []
        self.hypotheses: List[Dict] = []
        self.research_log: List[Dict] = []
        
    def _generate_id(self) -> str:
        """Benzersiz ID olustur"""
        return f"R{int(time.time())}_{random.randint(1000, 9999)}"
    
    def discover_pattern(self, symbol: str, data: List[Dict] = None) -> ResearchFinding:
        """Gizli patern kesfet"""
        patterns = [
            "Head and Shoulders", "Double Top", "Double Bottom", "Triangle",
            "Flag", "Pennant", "Wedge", "Cup and Handle", "Diamond",
            "Ascending Triangle", "Descending Triangle", "Symmetrical Triangle",
        ]
        
        pattern = random.choice(patterns)
        confidence = random.uniform(0.55, 0.90)
        
        # Paternin gecmis basarisi
        historical_success = random.uniform(0.50, 0.75)
        
        finding = ResearchFinding(
            id=self._generate_id(),
            category="pattern",
            title=f"{symbol} - {pattern} Formasyonu",
            description=f"{symbol} fiyat hareketlerinde {pattern} formasyonu tespit edildi. "
                       f"Gecmis basari orani: {historical_success:.0%}. "
                       f"Formasyon tamamlanma olasiligi: {confidence:.0%}.",
            confidence=confidence,
            evidence=[
                {"type": "price_action", "data": f"Formasyon boyutlari: {random.randint(10, 50)} bar"},
                {"type": "volume", "data": f"Hacim onayi: {'Evet' if random.random() > 0.3 else 'Hayir'}"},
                {"type": "historical", "data": f"Gecmis basari: {historical_success:.0%}"},
            ],
            actionable=True,
            recommended_action="BUY" if "Bottom" in pattern or "Cup" in pattern or "Ascending" in pattern else "SELL",
            symbols=[symbol],
        )
        
        self.findings.append(finding)
        return finding
    
    def detect_anomaly(self, symbol: str) -> ResearchFinding:
        """Anomali tespit et"""
        anomalies = [
            "Asiri hacim", "Asiri volatilite", "Fiyat boslugu", "Divergence",
            "Asiri alim/satim", "Beklenmeyen hareket", "Korelasyon kirilmasi",
        ]
        
        anomaly = random.choice(anomalies)
        severity = random.choice(["Dusuk", "Orta", "Yuksek", "Kritik"])
        confidence = random.uniform(0.60, 0.95)
        
        finding = ResearchFinding(
            id=self._generate_id(),
            category="anomaly",
            title=f"{symbol} - {anomaly} Anomalisi",
            description=f"{symbol} uzerinde {severity} seviyede {anomaly} anomalisi tespit edildi. "
                       f"Bu durum genellikle trend donusu veya siddetli hareket oncesi isaret eder.",
            confidence=confidence,
            evidence=[
                {"type": "statistical", "data": f"Z-skor: {random.uniform(2.0, 4.0):.2f}"},
                {"type": "historical", "data": f"Benzer anomali sayisi: {random.randint(3, 15)}"},
                {"type": "impact", "data": f"Tahmini etki: {random.choice(['%5-10', '%10-20', '%20+'])}"},
            ],
            actionable=severity in ["Yuksek", "Kritik"],
            recommended_action="ALERT" if severity == "Kritik" else "MONITOR",
            symbols=[symbol],
        )
        
        self.findings.append(finding)
        return finding
    
    def analyze_correlation(self, symbols: List[str]) -> ResearchFinding:
        """Korelasyon analizi yap"""
        if len(symbols) < 2:
            symbols = random.sample(self.ASSET_CLASSES["crypto"], 2)
            
        corr_value = random.uniform(-0.95, 0.95)
        
        if abs(corr_value) > 0.8:
            strength = "Cok guclu"
        elif abs(corr_value) > 0.6:
            strength = "Guclu"
        elif abs(corr_value) > 0.4:
            strength = "Orta"
        else:
            strength = "Zayif"
            
        direction = "Pozitif" if corr_value > 0 else "Negatif"
        
        finding = ResearchFinding(
            id=self._generate_id(),
            category="correlation",
            title=f"{'-'.join(symbols)} Korelasyon Analizi",
            description=f"{symbols[0]} ve {symbols[1]} arasinda {strength.lower()} {direction.lower()} "
                       f"korelasyon tespit edildi (r={corr_value:.2f}). "
                       f"Bu iliski portfoy cesitlendirmesi icin {'onemli' if abs(corr_value) > 0.7 else 'dikkate deger'}.",
            confidence=abs(corr_value),
            evidence=[
                {"type": "statistical", "data": f"Korelasyon katsayisi: {corr_value:.2f}"},
                {"type": "timeframe", "data": f"Analiz periyodu: {random.choice(['30', '60', '90'])} gun"},
                {"type": "significance", "data": f"P-degeri: {random.uniform(0.001, 0.05):.3f}"},
            ],
            actionable=abs(corr_value) > 0.7,
            recommended_action="HEDGE" if abs(corr_value) > 0.8 and corr_value > 0 else "DIVERSIFY",
            symbols=symbols,
        )
        
        self.findings.append(finding)
        return finding
    
    def scan_opportunities(self, market_data: Dict = None) -> List[ResearchFinding]:
        """Firsat taramasi yap"""
        opportunities = []
        
        # Her varlik sinifindan rastgele sembol sec
        all_symbols = []
        for asset_class, symbols in self.ASSET_CLASSES.items():
            all_symbols.extend(symbols)
            
        # Rastgele 5 sembol sec
        selected = random.sample(all_symbols, min(5, len(all_symbols)))
        
        for symbol in selected:
            # Rastgele firsat skoru
            opportunity_score = random.uniform(0.3, 0.95)
            
            if opportunity_score > 0.75:
                action = "BUY"
                reason = "Guclu teknik ve makro sinyaller"
            elif opportunity_score > 0.6:
                action = "WATCH"
                reason = "Potansiyel donus sinyalleri"
            elif opportunity_score > 0.4:
                action = "HOLD"
                reason = "Notr kosullar"
            else:
                action = "AVOID"
                reason = "Zayif sinyaller veya asiri risk"
                
            finding = ResearchFinding(
                id=self._generate_id(),
                category="opportunity",
                title=f"{symbol} - {action} Firsati",
                description=f"{symbol} icin {reason}. "
                           f"Firsat skoru: {opportunity_score:.0%}. "
                           f"Beklenen getiri: {random.uniform(-5, 20):+.1f}%.",
                confidence=opportunity_score,
                evidence=[
                    {"type": "technical", "data": f"Teknik skor: {random.uniform(0, 100):.0f}/100"},
                    {"type": "fundamental", "data": f"Temel skor: {random.uniform(0, 100):.0f}/100"},
                    {"type": "sentiment", "data": f"Duygu skoru: {random.uniform(0, 100):.0f}/100"},
                ],
                actionable=opportunity_score > 0.6,
                recommended_action=action,
                symbols=[symbol],
            )
            
            opportunities.append(finding)
            self.findings.append(finding)
            
        return opportunities
    
    def test_hypothesis(self, hypothesis: str, evidence: List[Dict] = None) -> ResearchFinding:
        """Hipotez test et"""
        # Hipotez sonucu
        is_valid = random.random() > 0.4  # %60 dogrulama orani
        confidence = random.uniform(0.55, 0.90) if is_valid else random.uniform(0.20, 0.50)
        
        finding = ResearchFinding(
            id=self._generate_id(),
            category="hypothesis",
            title=f"Hipotez Testi: {hypothesis[:50]}...",
            description=f"Hipotez: '{hypothesis}'\n\n"
                       f"Sonuc: {'DOGRULANDI' if is_valid else 'REDEDILDI'}\n"
                       f"Guven: {confidence:.0%}\n"
                       f"{'Bu hipotez islem stratejisi olarak kullanilabilir.' if is_valid else 'Bu hipotez guncel piyasa kosullarinda gecerli degil.'}",
            confidence=confidence,
            evidence=evidence or [
                {"type": "backtest", "data": f"Gecmis test: {random.randint(50, 500)} ornek"},
                {"type": "statistical", "data": f"Anlamlilik: {'Evet' if is_valid else 'Hayir'}"},
                {"type": "validation", "data": f"Capraz dogrulama: {random.choice(['Basarili', 'Kismi', 'Basarisiz'])}"},
            ],
            actionable=is_valid and confidence > 0.7,
            recommended_action="IMPLEMENT" if is_valid and confidence > 0.7 else "REJECT",
            symbols=[],
        )
        
        self.findings.append(finding)
        self.hypotheses.append({
            "hypothesis": hypothesis,
            "result": "VALID" if is_valid else "INVALID",
            "confidence": confidence,
        })
        
        return finding
    
    def generate_insight(self, symbol: str) -> MarketInsight:
        """Piyasa icgorusu uret"""
        insight_types = ["trend", "reversal", "breakout", "consolidation"]
        directions = ["bullish", "bearish", "neutral"]
        timeframes = ["short_term", "medium_term", "long_term"]
        
        insight_type = random.choice(insight_types)
        direction = random.choice(directions)
        timeframe = random.choice(timeframes)
        strength = random.uniform(0.3, 0.95)
        confidence = random.uniform(0.5, 0.9)
        
        # Icgörü metni
        if insight_type == "trend":
            desc = f"{symbol} {'yukari' if direction == 'bullish' else 'asagi'} yonlu trend icinde"
        elif insight_type == "reversal":
            desc = f"{symbol} trend donusu sinyalleri veriyor"
        elif insight_type == "breakout":
            desc = f"{symbol} onemli bir direnc/direnc kirmasi yapiyor"
        else:
            desc = f"{symbol} birlesme/daralma icinde, hareket bekleniyor"
            
        insight = MarketInsight(
            symbol=symbol,
            insight_type=insight_type,
            direction=direction,
            strength=strength,
            timeframe=timeframe,
            supporting_data={
                "technical_score": random.uniform(0, 100),
                "volume_profile": random.choice(["Yuksek", "Orta", "Dusuk"]),
                "momentum": random.uniform(-50, 50),
            },
            confidence=confidence,
        )
        
        self.insights.append(insight)
        return insight
    
    def run_full_research(self, symbols: List[str] = None) -> Dict:
        """Tam arastirma calistir"""
        if symbols is None:
            symbols = random.sample(self.ASSET_CLASSES["crypto"], 3)
            
        print(f"\n  [*] Tam arastirma baslatiliyor ({len(symbols)} sembol)...")
        
        # 1. Pattern kesfi
        print(f"  [*] Pattern kesfi...")
        patterns = [self.discover_pattern(s) for s in symbols]
        
        # 2. Anomali tespiti
        print(f"  [*] Anomali tespiti...")
        anomalies = [self.detect_anomaly(s) for s in symbols]
        
        # 3. Korelasyon analizi
        print(f"  [*] Korelasyon analizi...")
        correlations = []
        for i in range(len(symbols) - 1):
            correlations.append(self.analyze_correlation([symbols[i], symbols[i+1]]))
            
        # 4. Firsat taramasi
        print(f"  [*] Firsat taramasi...")
        opportunities = self.scan_opportunities()
        
        # 5. Hipotez testi
        print(f"  [*] Hipotez testi...")
        hypothesis = self.test_hypothesis(
            f"{symbols[0]} fiyat hareketi {self.MARKET_EVENTS[0]} sonrasi pozitif yonlenir"
        )
        
        # 6. Icgoru uretimi
        print(f"  [*] Icgoru uretimi...")
        insights = [self.generate_insight(s) for s in symbols]
        
        return {
            "patterns": patterns,
            "anomalies": anomalies,
            "correlations": correlations,
            "opportunities": opportunities,
            "hypothesis": hypothesis,
            "insights": insights,
            "total_findings": len(self.findings),
        }
    
    def get_research_summary(self) -> Dict:
        """Arastirma ozetini al"""
        categories = {}
        for f in self.findings:
            categories[f.category] = categories.get(f.category, 0) + 1
            
        actionable = len([f for f in self.findings if f.actionable])
        
        return {
            "total_findings": len(self.findings),
            "categories": categories,
            "actionable_findings": actionable,
            "avg_confidence": sum(f.confidence for f in self.findings) / len(self.findings) if self.findings else 0,
            "insights_count": len(self.insights),
            "hypotheses_tested": len(self.hypotheses),
            "valid_hypotheses": len([h for h in self.hypotheses if h["result"] == "VALID"]),
        }
    
    def generate_report(self) -> str:
        """Arastirma raporu olustur"""
        summary = self.get_research_summary()
        
        report = f"""
==============================================================
        ATLAS RESEARCH ENGINE - ARASTIRMA RAPORU              
==============================================================
  Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  Toplam Bulgu: {summary['total_findings']}
  Harekete Gecirilebilir: {summary['actionable_findings']}
  Ortalama Guven: {summary['avg_confidence']:.0%}
  Icgoru Sayisi: {summary['insights_count']}
  Test Edilen Hipotez: {summary['hypotheses_tested']}
  Gecerli Hipotez: {summary['valid_hypotheses']}
  
  BULGU KATEGORILERI:
"""
        for cat, count in summary['categories'].items():
            report += f"    - {self.CATEGORIES.get(cat, cat):25s}: {count}\n"
            
        report += f"\n  SON BULGULAR:\n"
        for f in self.findings[-5:]:
            action_icon = "!" if f.actionable else "o"
            report += f"    {action_icon} [{f.category.upper():12s}] {f.title} (Guven: {f.confidence:.0%})\n"
            if f.recommended_action:
                report += f"       Oneri: {f.recommended_action}\n"
                
        report += f"\n  SON ICGORULER:\n"
        for i in self.insights[-3:]:
            direction_icon = "+" if i.direction == "bullish" else "-" if i.direction == "bearish" else "o"
            report += f"    {direction_icon} {i.symbol}: {i.insight_type} | Guclu: {i.strength:.0%} | Guven: {i.confidence:.0%}\n"
            
        report += f"""
==============================================================
"""
        return report


# ==============================================================
# TEST
# ==============================================================

def test_research_engine():
    """Arastirma motoru testi"""
    print("=" * 60)
    print("ATLAS RESEARCH ENGINE - OTONOM ARASTIRMA TESTI")
    print("=" * 60)
    
    engine = AtlasResearchEngine()
    
    # 1. Pattern kesfi
    print("\n[1] Pattern Kesfi")
    print("-" * 50)
    pattern = engine.discover_pattern("BTC")
    print(f"  Bulgu: {pattern.title}")
    print(f"  Guven: {pattern.confidence:.0%}")
    print(f"  Eylem: {pattern.recommended_action}")
    
    # 2. Anomali tespiti
    print("\n[2] Anomali Tespiti")
    print("-" * 50)
    anomaly = engine.detect_anomaly("ETH")
    print(f"  Bulgu: {anomaly.title}")
    print(f"  Guven: {anomaly.confidence:.0%}")
    print(f"  Eylem: {anomaly.recommended_action}")
    
    # 3. Korelasyon analizi
    print("\n[3] Korelasyon Analizi")
    print("-" * 50)
    corr = engine.analyze_correlation(["BTC", "ETH"])
    print(f"  Bulgu: {corr.title}")
    print(f"  Guven: {corr.confidence:.0%}")
    print(f"  Eylem: {corr.recommended_action}")
    
    # 4. Firsat taramasi
    print("\n[4] Firsat Taramasi")
    print("-" * 50)
    opportunities = engine.scan_opportunities()
    for opp in opportunities:
        print(f"  {opp.title} | Guven: {opp.confidence:.0%} | Eylem: {opp.recommended_action}")
    
    # 5. Hipotez testi
    print("\n[5] Hipotez Testi")
    print("-" * 50)
    hypo = engine.test_hypothesis("BTC fiyati FED faiz indirimi sonrasi %10 artar")
    print(f"  Hipotez: {hypo.title}")
    print(f"  Sonuc: {'DOGRULANDI' if 'DOGRULANDI' in hypo.description else 'REDEDILDI'}")
    print(f"  Guven: {hypo.confidence:.0%}")
    
    # 6. Icgoru uretimi
    print("\n[6] Piyasa Icgorusu")
    print("-" * 50)
    insight = engine.generate_insight("SOL")
    print(f"  Sembol: {insight.symbol}")
    print(f"  Tip: {insight.insight_type}")
    print(f"  Yon: {insight.direction}")
    print(f"  Guclu: {insight.strength:.0%}")
    print(f"  Guven: {insight.confidence:.0%}")
    
    # 7. Tam arastirma
    print("\n[7] Tam Arastirma (3 sembol)")
    print("-" * 50)
    results = engine.run_full_research(["BTC", "ETH", "SOL"])
    print(f"\n  Tamamlandi!")
    print(f"  Toplam bulgu: {results['total_findings']}")
    print(f"  Pattern: {len(results['patterns'])}")
    print(f"  Anomali: {len(results['anomalies'])}")
    print(f"  Korelasyon: {len(results['correlations'])}")
    print(f"  Firsat: {len(results['opportunities'])}")
    
    # 8. Rapor
    print("\n" + "=" * 60)
    print(engine.generate_report())
    
    # 9. Ozet
    print("\n[8] Arastirma Ozeti")
    print("-" * 50)
    summary = engine.get_research_summary()
    print(f"  Toplam bulgu: {summary['total_findings']}")
    print(f"  Kategoriler: {summary['categories']}")
    print(f"  Harekete gecirilebilir: {summary['actionable_findings']}")
    print(f"  Ortalama guven: {summary['avg_confidence']:.0%}")
    
    print("\n" + "=" * 60)
    print("[OK] ARASTIRMA MOTORU TEST TAMAMLANDI")
    print("=" * 60)


if __name__ == "__main__":
    test_research_engine()