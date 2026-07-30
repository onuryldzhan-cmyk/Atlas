# -*- coding: utf-8 -*-
"""
ATLAS DIGITAL TWIN
Dijital ikiz simulasyonu - Piyasa simulasyonu, senaryo testi
"""
import random
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class SimulatedAsset:
    """Simule edilmis varlik"""
    symbol: str
    base_price: float
    volatility: float
    trend: float
    current_price: float
    volume: float
    market_cap: float
    correlation_map: Dict[str, float]  # Diger varliklarla korelasyon
    price_history: List[float] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.price_history:
            self.price_history = [self.base_price]


@dataclass
class MarketScenario:
    """Piyasa senaryosu"""
    id: str
    name: str
    description: str
    duration_days: int
    events: List[Dict]
    impact_matrix: Dict[str, float]  # Varliklara etki
    probability: float


@dataclass
class SimulationResult:
    """Simulasyon sonucu"""
    scenario_id: str
    start_date: str
    end_date: str
    final_prices: Dict[str, float]
    returns: Dict[str, float]
    max_drawdowns: Dict[str, float]
    volatilities: Dict[str, float]
    correlations: Dict[str, Dict[str, float]]
    events_triggered: List[str]


class AtlasDigitalTwin:
    """
    Atlas AI Dijital Ikiz Simulasyon Motoru
    
    Simulasyon yetenekleri:
    1. Piyasa Simulasyonu - Monte Carlo fiyat modeli
    2. Senaryo Testi - Makro olaylarin etkisini simule et
    3. Stres Testi - Asiri kosullar altinda test
    4. Strateji Simulasyonu - Stratejileri simule ortamda test et
    5. What-If Analizi - Hipotetik senaryolar
    """
    
    # Varlik tanimlari
    ASSETS = {
        "BTC": {"base": 65000, "vol": 0.025, "trend": 0.0002, "cap": 1.3e12},
        "ETH": {"base": 3500, "vol": 0.030, "trend": 0.0003, "cap": 4.2e11},
        "SOL": {"base": 150, "vol": 0.040, "trend": 0.0005, "cap": 6.8e10},
        "ADA": {"base": 0.45, "vol": 0.035, "trend": 0.0001, "cap": 1.6e10},
        "DOT": {"base": 7.2, "vol": 0.032, "trend": 0.0002, "cap": 9.5e9},
        "DXY": {"base": 104, "vol": 0.008, "trend": -0.0001, "cap": 0},
        "GOLD": {"base": 2300, "vol": 0.012, "trend": 0.0001, "cap": 0},
        "VIX": {"base": 18, "vol": 0.050, "trend": 0.0, "cap": 0},
    }
    
    # Makro senaryolar
    SCENARIOS = {
        "bull_run": {
            "name": "Bull Run 2026",
            "description": "FED dovish, ETF onaylari, kurumsal benimseme",
            "duration": 180,
            "events": [
                {"day": 10, "event": "FED faiz indirimi", "impact": 0.05},
                {"day": 30, "event": "Spot ETF onayi", "impact": 0.15},
                {"day": 60, "event": "Buyuk yatirimci girisi", "impact": 0.10},
                {"day": 120, "event": "Ulke duzenlemesi", "impact": 0.08},
            ],
            "crypto_bias": 0.003,
            "vol_multiplier": 1.2,
        },
        "bear_market": {
            "name": "Bear Market 2026",
            "description": "FED hawkish, duzenleme baskisi, likidite krizi",
            "duration": 120,
            "events": [
                {"day": 5, "event": "FED faiz artirimi", "impact": -0.08},
                {"day": 20, "event": "Borsa kazasi", "impact": -0.12},
                {"day": 45, "event": "Duzenleme haberi", "impact": -0.05},
                {"day": 80, "event": "Buyuk satis", "impact": -0.10},
            ],
            "crypto_bias": -0.004,
            "vol_multiplier": 1.8,
        },
        "sideways": {
            "name": "Yatay Piyasa",
            "description": "Belirsizlik, dusuk volatilite, aralikli hareket",
            "duration": 90,
            "events": [
                {"day": 15, "event": "Kararsiz FED", "impact": 0.02},
                {"day": 40, "event": "Teknik direnc", "impact": -0.03},
                {"day": 65, "event": "Hacim dususu", "impact": -0.01},
            ],
            "crypto_bias": 0.0,
            "vol_multiplier": 0.7,
        },
        "black_swan": {
            "name": "Kara Kugu Olayi",
            "description": "Beklenmedik sistemik kriz",
            "duration": 30,
            "events": [
                {"day": 3, "event": "Sistemik kriz", "impact": -0.25},
                {"day": 7, "event": "Panik satisi", "impact": -0.20},
                {"day": 14, "event": "Mudahale", "impact": 0.10},
            ],
            "crypto_bias": -0.008,
            "vol_multiplier": 3.0,
        },
        "recovery": {
            "name": "Iyilesme Donemi",
            "description": "Dipten donus, yavas toparlanma",
            "duration": 150,
            "events": [
                {"day": 20, "event": "Dip bulundu", "impact": 0.05},
                {"day": 50, "event": "Ilk sinyaller", "impact": 0.03},
                {"day": 90, "event": "Guclu alim", "impact": 0.08},
                {"day": 130, "event": "Trend donusu", "impact": 0.12},
            ],
            "crypto_bias": 0.002,
            "vol_multiplier": 1.0,
        },
    }
    
    def __init__(self):
        self.assets: Dict[str, SimulatedAsset] = {}
        self.scenarios: List[MarketScenario] = []
        self.simulation_results: List[SimulationResult] = []
        self.initialize_assets()
        
    def initialize_assets(self):
        """Varliklari baslat"""
        # Korelasyon matrisi
        correlations = {
            "BTC": {"ETH": 0.85, "SOL": 0.75, "ADA": 0.70, "DOT": 0.65, "DXY": -0.60, "GOLD": 0.20, "VIX": -0.40},
            "ETH": {"BTC": 0.85, "SOL": 0.80, "ADA": 0.75, "DOT": 0.70, "DXY": -0.55, "GOLD": 0.15, "VIX": -0.35},
            "SOL": {"BTC": 0.75, "ETH": 0.80, "ADA": 0.65, "DOT": 0.60, "DXY": -0.50, "GOLD": 0.10, "VIX": -0.30},
            "ADA": {"BTC": 0.70, "ETH": 0.75, "SOL": 0.65, "DOT": 0.55, "DXY": -0.45, "GOLD": 0.10, "VIX": -0.25},
            "DOT": {"BTC": 0.65, "ETH": 0.70, "SOL": 0.60, "ADA": 0.55, "DXY": -0.40, "GOLD": 0.05, "VIX": -0.20},
            "DXY": {"BTC": -0.60, "ETH": -0.55, "SOL": -0.50, "ADA": -0.45, "DOT": -0.40, "GOLD": -0.30, "VIX": 0.50},
            "GOLD": {"BTC": 0.20, "ETH": 0.15, "SOL": 0.10, "ADA": 0.10, "DOT": 0.05, "DXY": -0.30, "VIX": 0.30},
            "VIX": {"BTC": -0.40, "ETH": -0.35, "SOL": -0.30, "ADA": -0.25, "DOT": -0.20, "DXY": 0.50, "GOLD": 0.30},
        }
        
        for symbol, data in self.ASSETS.items():
            self.assets[symbol] = SimulatedAsset(
                symbol=symbol,
                base_price=data["base"],
                volatility=data["vol"],
                trend=data["trend"],
                current_price=data["base"],
                volume=random.uniform(1e6, 1e9),
                market_cap=data["cap"],
                correlation_map=correlations.get(symbol, {}),
            )
    
    def _geometric_brownian_motion(self, price: float, drift: float, 
                                    volatility: float, dt: float = 1/365) -> float:
        """Geometrik Brown hareketi ile fiyat simulasyonu"""
        random_shock = random.gauss(0, 1)
        price_change = price * (drift * dt + volatility * random_shock * (dt ** 0.5))
        return max(0.01, price + price_change)
    
    def _apply_correlation(self, symbol: str, price_change: float) -> float:
        """Korelasyon etkisini uygula"""
        asset = self.assets[symbol]
        correlated_change = price_change
        
        for other_symbol, corr in asset.correlation_map.items():
            if other_symbol in self.assets:
                other_asset = self.assets[other_symbol]
                if len(other_asset.price_history) >= 2:
                    other_change = (other_asset.price_history[-1] - other_asset.price_history[-2]) / other_asset.price_history[-2]
                    correlated_change += other_change * corr * 0.3  # Korelasyon etkisi %30
                    
        return correlated_change
    
    def simulate_day(self, scenario: Dict = None) -> Dict[str, float]:
        """Bir gun simule et"""
        daily_returns = {}
        
        for symbol, asset in self.assets.items():
            # Temel drift
            drift = asset.trend
            
            # Senaryo etkisi
            if scenario:
                if symbol in ["BTC", "ETH", "SOL", "ADA", "DOT"]:
                    drift += scenario.get("crypto_bias", 0)
                vol_mult = scenario.get("vol_multiplier", 1.0)
            else:
                vol_mult = 1.0
                
            # Yeni fiyat hesapla
            new_price = self._geometric_brownian_motion(
                asset.current_price,
                drift,
                asset.volatility * vol_mult
            )
            
            # Korelasyon etkisi
            price_change = (new_price - asset.current_price) / asset.current_price
            adjusted_change = self._apply_correlation(symbol, price_change)
            final_price = asset.current_price * (1 + adjusted_change)
            
            asset.current_price = final_price
            asset.price_history.append(final_price)
            daily_returns[symbol] = adjusted_change
            
        return daily_returns
    
    def run_scenario(self, scenario_name: str, initial_capital: float = 10000.0) -> SimulationResult:
        """Senaryo calistir"""
        if scenario_name not in self.SCENARIOS:
            return None
            
        scenario = self.SCENARIOS[scenario_name]
        duration = scenario["duration"]
        
        # Baslangic degerlerini kaydet
        start_prices = {s: a.current_price for s, a in self.assets.items()}
        start_date = datetime.now()
        
        # Olaylari siraya koy
        events = sorted(scenario["events"], key=lambda x: x["day"])
        triggered_events = []
        
        # Simulasyonu calistir
        for day in range(duration):
            # Olay kontrolu
            for event in events:
                if event["day"] == day:
                    # Olay etkisini uygula
                    for symbol in ["BTC", "ETH", "SOL", "ADA", "DOT"]:
                        self.assets[symbol].trend += event["impact"] / 10
                    triggered_events.append(event["event"])
                    
            self.simulate_day(scenario)
            
        # Sonuclari hesapla
        end_prices = {s: a.current_price for s, a in self.assets.items()}
        returns = {s: (end_prices[s] / start_prices[s] - 1) for s in start_prices}
        
        # Max drawdown hesapla
        max_drawdowns = {}
        for symbol, asset in self.assets.items():
            peak = max(asset.price_history)
            trough = min(asset.price_history)
            max_drawdowns[symbol] = (trough - peak) / peak if peak > 0 else 0
            
        # Volatilite hesapla
        volatilities = {}
        for symbol, asset in self.assets.items():
            if len(asset.price_history) > 1:
                returns_list = [(asset.price_history[i] - asset.price_history[i-1]) / asset.price_history[i-1] 
                               for i in range(1, len(asset.price_history))]
                volatilities[symbol] = (sum(r**2 for r in returns_list) / len(returns_list)) ** 0.5 * (365 ** 0.5)
            else:
                volatilities[symbol] = 0
                
        # Korelasyonlari guncelle
        correlations = {}
        for symbol, asset in self.assets.items():
            correlations[symbol] = dict(asset.correlation_map)
            
        result = SimulationResult(
            scenario_id=scenario_name,
            start_date=start_date.isoformat(),
            end_date=(start_date + timedelta(days=duration)).isoformat(),
            final_prices=end_prices,
            returns=returns,
            max_drawdowns=max_drawdowns,
            volatilities=volatilities,
            correlations=correlations,
            events_triggered=triggered_events,
        )
        
        self.simulation_results.append(result)
        return result
    
    def stress_test(self, asset: str, shock: float = -0.30) -> Dict:
        """Stres testi uygula"""
        if asset not in self.assets:
            return {}
            
        original_price = self.assets[asset].current_price
        self.assets[asset].current_price *= (1 + shock)
        
        # Korelasyon etkisi
        affected_assets = {}
        for symbol, corr in self.assets[asset].correlation_map.items():
            if symbol in self.assets and symbol != asset:
                impact = shock * corr * 0.5
                old_price = self.assets[symbol].current_price
                self.assets[symbol].current_price *= (1 + impact)
                affected_assets[symbol] = {
                    "old_price": old_price,
                    "new_price": self.assets[symbol].current_price,
                    "change": impact,
                }
                
        return {
            "shocked_asset": asset,
            "shock_magnitude": shock,
            "original_price": original_price,
            "new_price": self.assets[asset].current_price,
            "affected_assets": affected_assets,
            "portfolio_impact": shock + sum(a["change"] for a in affected_assets.values()) / len(affected_assets) if affected_assets else shock,
        }
    
    def what_if(self, changes: Dict[str, Any]) -> Dict:
        """What-If analizi"""
        # Mevcut durumu kaydet
        original_state = {s: a.current_price for s, a in self.assets.items()}
        
        # Degisiklikleri uygula
        for change_type, params in changes.items():
            if change_type == "fed_rate_change":
                rate_change = params.get("change", 0)
                for symbol in ["BTC", "ETH", "SOL", "ADA", "DOT"]:
                    self.assets[symbol].trend += rate_change * 0.01
                self.assets["DXY"].trend -= rate_change * 0.005
                    
            elif change_type == "etf_approval":
                approval = params.get("approved", False)
                if approval:
                    for symbol in ["BTC", "ETH"]:
                        self.assets[symbol].trend += 0.002
                        self.assets[symbol].volatility *= 0.8
                        
            elif change_type == "regulation":
                severity = params.get("severity", "medium")
                impact = {"low": -0.001, "medium": -0.003, "high": -0.005}.get(severity, -0.001)
                for symbol in ["BTC", "ETH", "SOL", "ADA", "DOT"]:
                    self.assets[symbol].trend += impact
                    
        # 30 gun simule et
        for _ in range(30):
            self.simulate_day()
            
        # Sonuclari karsilastir
        new_state = {s: a.current_price for s, a in self.assets.items()}
        
        # Durumu geri yukle
        for symbol, price in original_state.items():
            self.assets[symbol].current_price = price
            
        return {
            "changes": changes,
            "projected_returns": {s: (new_state[s] / original_state[s] - 1) for s in original_state},
            "most_affected": max(new_state.keys(), key=lambda s: abs(new_state[s] / original_state[s] - 1)),
        }
    
    def reset(self):
        """Simulasyonu sifirla"""
        self.assets.clear()
        self.simulation_results.clear()
        self.initialize_assets()
    
    def generate_report(self, result: SimulationResult = None) -> str:
        """Simulasyon raporu olustur"""
        if result is None and self.simulation_results:
            result = self.simulation_results[-1]
            
        if result is None:
            return "Heniz simulasyon yapilmadi."
            
        scenario = self.SCENARIOS.get(result.scenario_id, {})
        
        report = f"""
==============================================================
       ATLAS DIGITAL TWIN - SIMULASYON RAPORU               
==============================================================
  Senaryo: {scenario.get('name', result.scenario_id)}
  Sure: {(datetime.fromisoformat(result.end_date) - datetime.fromisoformat(result.start_date)).days} gun
  Tarih: {result.start_date[:10]} - {result.end_date[:10]}
  
  TETIKLENEN OLAYLAR:
"""
        for event in result.events_triggered:
            report += f"    - {event}\n"
            
        report += f"\n  KRIPTO VARLIK SONUCLARI:\n"
        report += f"  {'Sembol':<8} {'Baslangic':>12} {'Bitis':>12} {'Getiri':>10} {'Max DD':>10} {'Vol':>8}\n"
        report += f"  {'-'*8} {'-'*12} {'-'*12} {'-'*10} {'-'*10} {'-'*8}\n"
        
        for symbol in ["BTC", "ETH", "SOL", "ADA", "DOT"]:
            if symbol in result.final_prices:
                # Baslangic fiyatini bul (simulasyon sonucundan hesapla)
                start_price = result.final_prices[symbol] / (1 + result.returns[symbol])
                report += f"  {symbol:<8} ${start_price:>10,.2f} ${result.final_prices[symbol]:>10,.2f} {result.returns[symbol]:>9.1%} {result.max_drawdowns[symbol]:>9.1%} {result.volatilities[symbol]:>7.1%}\n"
                
        report += f"\n  MAKRO GOSTERGELER:\n"
        for symbol in ["DXY", "GOLD", "VIX"]:
            if symbol in result.final_prices:
                start_price = result.final_prices[symbol] / (1 + result.returns[symbol])
                report += f"  {symbol:<8} ${start_price:>10,.2f} ${result.final_prices[symbol]:>10,.2f} {result.returns[symbol]:>9.1%}\n"
                
        report += f"""
  PORTFOY ANALIZI (Esit Agirlikli):
    Ortalama Getiri: {sum(result.returns[s] for s in ['BTC', 'ETH', 'SOL', 'ADA', 'DOT'] if s in result.returns) / 5:.1%}
    En Iyi: {max(((s, result.returns[s]) for s in result.returns), key=lambda x: x[1])[0]} ({max(result.returns.values()):.1%})
    En Kotu: {min(((s, result.returns[s]) for s in result.returns), key=lambda x: x[1])[0]} ({min(result.returns.values()):.1%})
    
  RISK METRIKLERI:
    Ortalama Volatilite: {sum(result.volatilities[s] for s in result.volatilities) / len(result.volatilities):.1%}
    Ortalama Max DD: {sum(result.max_drawdowns[s] for s in result.max_drawdowns) / len(result.max_drawdowns):.1%}
==============================================================
"""
        return report


# ==============================================================
# TEST
# ==============================================================

def test_digital_twin():
    """Dijital ikiz testi"""
    print("=" * 60)
    print("ATLAS DIGITAL TWIN - PIYASA SIMULASYON TESTI")
    print("=" * 60)
    
    twin = AtlasDigitalTwin()
    
    # 1. Baslangic durumu
    print("\n[1] Baslangic Durumu")
    print("-" * 50)
    for symbol, asset in twin.assets.items():
        print(f"  {symbol:<6} ${asset.current_price:>10,.2f} | Vol: {asset.volatility:.1%} | Trend: {asset.trend:.3f}")
    
    # 2. Bull Run senaryosu
    print("\n[2] Bull Run Senaryosu (180 gun)")
    print("-" * 50)
    twin.reset()
    result_bull = twin.run_scenario("bull_run")
    print(f"  Tetiklenen olaylar: {len(result_bull.events_triggered)}")
    for symbol in ["BTC", "ETH", "SOL"]:
        print(f"  {symbol}: {result_bull.returns[symbol]:+.1%}")
    
    # 3. Bear Market senaryosu
    print("\n[3] Bear Market Senaryosu (120 gun)")
    print("-" * 50)
    twin.reset()
    result_bear = twin.run_scenario("bear_market")
    print(f"  Tetiklenen olaylar: {len(result_bear.events_triggered)}")
    for symbol in ["BTC", "ETH", "SOL"]:
        print(f"  {symbol}: {result_bear.returns[symbol]:+.1%}")
    
    # 4. Stres testi
    print("\n[4] Stres Testi (BTC -30% sok)")
    print("-" * 50)
    twin.reset()
    stress = twin.stress_test("BTC", -0.30)
    print(f"  Sok: {stress['shock_magnitude']:.0%}")
    print(f"  BTC: ${stress['original_price']:,.2f} -> ${stress['new_price']:,.2f}")
    print(f"  Etkilenen varliklar:")
    for symbol, data in stress['affected_assets'].items():
        print(f"    {symbol}: {data['change']:+.1%}")
    print(f"  Portfoy etkisi: {stress['portfolio_impact']:+.1%}")
    
    # 5. What-If analizi
    print("\n[5] What-If Analizi")
    print("-" * 50)
    twin.reset()
    whatif = twin.what_if({
        "fed_rate_change": {"change": -0.50},
        "etf_approval": {"approved": True},
    })
    print(f"  Senaryo: FED -50bp + ETF Onayi")
    print(f"  Projeksiyon (30 gun):")
    for symbol in ["BTC", "ETH", "SOL", "DXY"]:
        if symbol in whatif['projected_returns']:
            print(f"    {symbol}: {whatif['projected_returns'][symbol]:+.1%}")
    print(f"  En cok etkilenen: {whatif['most_affected']}")
    
    # 6. Raporlar
    print("\n[6] Bull Run Raporu")
    print("-" * 50)
    print(twin.generate_report(result_bull))
    
    print("\n[7] Bear Market Raporu")
    print("-" * 50)
    print(twin.generate_report(result_bear))
    
    print("\n" + "=" * 60)
    print("[OK] DIJITAL IKIZ TEST TAMAMLANDI")
    print("=" * 60)


if __name__ == "__main__":
    test_digital_twin()