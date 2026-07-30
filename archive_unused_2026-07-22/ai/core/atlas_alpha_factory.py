# -*- coding: utf-8 -*-
"""
ATLAS ALPHA FACTORY
Strateji uretim fabrikasi - Yeni stratejiler otomatik olusturur
"""
import random
import json
import time
import hashlib
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class StrategyDNA:
    """Strateji DNA'si - parametre seti"""
    name: str
    indicators: List[Dict]  # [{"name": "RSI", "params": {"period": 14, "overbought": 70}}]
    entry_rules: List[str]  # ["RSI < 30", "MACD > Signal"]
    exit_rules: List[str]   # ["RSI > 70", "StopLoss < -5%"]
    position_sizing: Dict   # {"type": "fixed", "value": 0.1}
    risk_params: Dict       # {"stop_loss": 0.05, "take_profit": 0.10}
    timeframe: str = "1h"
    fitness: float = 0.0
    generation: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def get_hash(self) -> str:
        """Strateji DNA'sinin benzersiz hash'i"""
        content = f"{self.name}{json.dumps(self.indicators, sort_keys=True)}"
        return hashlib.md5(content.encode()).hexdigest()[:8]


@dataclass
class StrategyResult:
    """Strateji test sonucu"""
    strategy: StrategyDNA
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    profit_factor: float
    score: float = 0.0


class AtlasAlphaFactory:
    """
    Atlas AI Alpha Factory
    
    Strateji uretim yontemleri:
    1. Rastgele uretim - Yeni stratejiler rastgele kombinasyonlarla
    2. Mutasyon - Mevcut stratejileri degistirerek
    3. Crossover - Iki stratejiyi birlestirerek
    4. Template-based - Sablonlardan tureterek
    """
    
    # Kullanilabilir gostergeler
    INDICATORS_POOL = [
        {"name": "RSI", "params": {"period": [7, 14, 21], "overbought": [65, 70, 75], "oversold": [25, 30, 35]}},
        {"name": "MACD", "params": {"fast": [8, 12], "slow": [21, 26], "signal": [9]}},
        {"name": "EMA", "params": {"period": [9, 20, 50, 200], "cross_type": ["golden", "death"]}},
        {"name": "Bollinger", "params": {"period": [20], "std_dev": [2.0, 2.5], "breakout": ["upper", "lower"]}},
        {"name": "ATR", "params": {"period": [14], "multiplier": [1.5, 2.0, 3.0]}},
        {"name": "Volume", "params": {"period": [20], "threshold": [1.5, 2.0]}},
        {"name": "Stochastic", "params": {"k_period": [14], "d_period": [3], "overbought": [80], "oversold": [20]}},
        {"name": "ADX", "params": {"period": [14], "threshold": [20, 25]}},
    ]
    
    # Giris kurali sablonlari
    ENTRY_TEMPLATES = [
        "{indicator} < {threshold}",
        "{indicator} > {threshold}",
        "{indicator1} crosses above {indicator2}",
        "{indicator1} crosses below {indicator2}",
        "{indicator} divergence bullish",
        "{indicator} divergence bearish",
        "{indicator} breakout {direction}",
        "volume > {threshold} AND {indicator} {condition}",
    ]
    
    # Cikis kurali sablonlari
    EXIT_TEMPLATES = [
        "{indicator} > {threshold}",
        "{indicator} < {threshold}",
        "profit > {take_profit}%",
        "loss < -{stop_loss}%",
        "time > {max_bars} bars",
        "{indicator} reversal",
    ]
    
    # Pozisyon boyutlandirma stratejileri
    SIZING_STRATEGIES = [
        {"type": "fixed", "value": [0.05, 0.10, 0.15]},
        {"type": "risk_based", "risk_per_trade": [0.01, 0.02, 0.03]},
        {"type": "kelly", "fraction": [0.25, 0.5]},
        {"type": "volatility", "atr_multiplier": [1.0, 1.5, 2.0]},
    ]
    
    def __init__(self):
        self.population: List[StrategyDNA] = []
        self.results: List[StrategyResult] = []
        self.generation = 0
        self.best_strategy: Optional[StrategyDNA] = None
        self.best_score = -float('inf')
        
    def _random_param(self, param_range: List) -> Any:
        """Parametre araligindan rastgele sec"""
        return random.choice(param_range)
    
    def _create_indicator(self) -> Dict:
        """Rastgele bir gosterge olustur"""
        base = random.choice(self.INDICATORS_POOL)
        indicator = {"name": base["name"], "params": {}}
        
        for param_name, param_range in base["params"].items():
            indicator["params"][param_name] = self._random_param(param_range)
            
        return indicator
    
    def _create_entry_rule(self, indicators: List[Dict]) -> str:
        """Rastgele giris kurali olustur"""
        template = random.choice(self.ENTRY_TEMPLATES)
        
        # Gosterge yer tutucularini doldur
        if "{indicator1}" in template and len(indicators) >= 2:
            template = template.replace("{indicator1}", indicators[0]["name"])
            template = template.replace("{indicator2}", indicators[1]["name"])
        elif "{indicator}" in template:
            template = template.replace("{indicator}", indicators[0]["name"] if indicators else "RSI")
            
        # Esik degerleri
        template = template.replace("{threshold}", str(random.choice([20, 30, 40, 50, 60, 70, 80])))
        template = template.replace("{condition}", random.choice([">", "<", "=="]))
        template = template.replace("{direction}", random.choice(["up", "down"]))
        
        return template
    
    def _create_exit_rule(self, indicators: List[Dict]) -> str:
        """Rastgele cikis kurali olustur"""
        template = random.choice(self.EXIT_TEMPLATES)
        
        if "{indicator}" in template:
            template = template.replace("{indicator}", indicators[0]["name"] if indicators else "RSI")
            
        template = template.replace("{threshold}", str(random.choice([20, 30, 40, 50, 60, 70, 80])))
        template = template.replace("{take_profit}", str(random.choice([5, 8, 10, 15, 20])))
        template = template.replace("{stop_loss}", str(random.choice([2, 3, 5, 8, 10])))
        template = template.replace("{max_bars}", str(random.choice([10, 20, 50, 100])))
        
        return template
    
    def _create_sizing(self) -> Dict:
        """Rastgele pozisyon boyutlandirma"""
        strategy = random.choice(self.SIZING_STRATEGIES)
        sizing = {"type": strategy["type"]}
        
        for param_name, param_range in strategy.items():
            if param_name != "type":
                sizing[param_name] = self._random_param(param_range)
                
        return sizing
    
    def generate_random(self, count: int = 1) -> List[StrategyDNA]:
        """Rastgele strateji uret"""
        strategies = []
        
        for i in range(count):
            # 2-4 gosterge sec
            num_indicators = random.randint(2, 4)
            indicators = [self._create_indicator() for _ in range(num_indicators)]
            
            # 1-3 giris kurali
            num_entries = random.randint(1, 3)
            entries = [self._create_entry_rule(indicators) for _ in range(num_entries)]
            
            # 1-3 cikis kurali
            num_exits = random.randint(1, 3)
            exits = [self._create_exit_rule(indicators) for _ in range(num_exits)]
            
            # Pozisyon boyutlandirma
            sizing = self._create_sizing()
            
            # Risk parametreleri
            risk = {
                "stop_loss": random.choice([0.02, 0.03, 0.05, 0.08]),
                "take_profit": random.choice([0.05, 0.08, 0.10, 0.15, 0.20]),
                "max_positions": random.randint(3, 10),
            }
            
            strategy = StrategyDNA(
                name=f"Alpha_{self.generation}_{i+1}",
                indicators=indicators,
                entry_rules=entries,
                exit_rules=exits,
                position_sizing=sizing,
                risk_params=risk,
                timeframe=random.choice(["15m", "1h", "4h", "1d"]),
                generation=self.generation,
            )
            
            strategies.append(strategy)
            
        self.population.extend(strategies)
        return strategies
    
    def mutate(self, strategy: StrategyDNA, mutation_rate: float = 0.3) -> StrategyDNA:
        """Mevcut stratejiyi mutasyona ugrat"""
        new_indicators = [dict(ind) for ind in strategy.indicators]
        new_entries = list(strategy.entry_rules)
        new_exits = list(strategy.exit_rules)
        new_sizing = dict(strategy.position_sizing)
        new_risk = dict(strategy.risk_params)
        
        # Gosterge mutasyonu
        if random.random() < mutation_rate:
            idx = random.randint(0, len(new_indicators) - 1)
            new_indicators[idx] = self._create_indicator()
            
        # Giris kurali mutasyonu
        if random.random() < mutation_rate and new_entries:
            idx = random.randint(0, len(new_entries) - 1)
            new_entries[idx] = self._create_entry_rule(new_indicators)
            
        # Cikis kurali mutasyonu
        if random.random() < mutation_rate and new_exits:
            idx = random.randint(0, len(new_exits) - 1)
            new_exits[idx] = self._create_exit_rule(new_indicators)
            
        # Risk parametre mutasyonu
        if random.random() < mutation_rate:
            new_risk["stop_loss"] = random.choice([0.02, 0.03, 0.05, 0.08])
            new_risk["take_profit"] = random.choice([0.05, 0.08, 0.10, 0.15, 0.20])
            
        mutated = StrategyDNA(
            name=f"{strategy.name}_MUT",
            indicators=new_indicators,
            entry_rules=new_entries,
            exit_rules=new_exits,
            position_sizing=new_sizing,
            risk_params=new_risk,
            timeframe=strategy.timeframe,
            generation=self.generation + 1,
        )
        
        return mutated
    
    def crossover(self, parent1: StrategyDNA, parent2: StrategyDNA) -> StrategyDNA:
        """Iki stratejiyi birlestir"""
        # Gostergeleri karistir
        indicators = []
        for i in range(max(len(parent1.indicators), len(parent2.indicators))):
            if i < len(parent1.indicators) and random.random() < 0.5:
                indicators.append(parent1.indicators[i])
            elif i < len(parent2.indicators):
                indicators.append(parent2.indicators[i])
                
        # Giris kurallarini karistir
        entries = []
        p1_entries = list(parent1.entry_rules)
        p2_entries = list(parent2.entry_rules)
        for i in range(max(len(p1_entries), len(p2_entries))):
            if i < len(p1_entries) and random.random() < 0.5:
                entries.append(p1_entries[i])
            elif i < len(p2_entries):
                entries.append(p2_entries[i])
                
        # Cikis kurallarini karistir
        exits = []
        p1_exits = list(parent1.exit_rules)
        p2_exits = list(parent2.exit_rules)
        for i in range(max(len(p1_exits), len(p2_exits))):
            if i < len(p1_exits) and random.random() < 0.5:
                exits.append(p1_exits[i])
            elif i < len(p2_exits):
                exits.append(p2_exits[i])
                
        # Risk parametrelerini karistir
        risk = parent1.risk_params if random.random() < 0.5 else parent2.risk_params
        
        child = StrategyDNA(
            name=f"Alpha_X_{parent1.name[:4]}_{parent2.name[:4]}",
            indicators=indicators,
            entry_rules=entries,
            exit_rules=exits,
            position_sizing=parent1.position_sizing if random.random() < 0.5 else parent2.position_sizing,
            risk_params=risk,
            timeframe=parent1.timeframe if random.random() < 0.5 else parent2.timeframe,
            generation=max(parent1.generation, parent2.generation) + 1,
        )
        
        return child
    
    def simulate_backtest(self, strategy: StrategyDNA) -> StrategyResult:
        """Stratejiyi simule et (gercek backtest yerine simulasyon)"""
        # Basit simulasyon - gercek backtest sonraki asamada
        random.seed(strategy.get_hash())
        
        # Strateji kalitesine gore performans
        num_indicators = len(strategy.indicators)
        num_rules = len(strategy.entry_rules) + len(strategy.exit_rules)
        
        # Daha fazla gosterge ve kural = daha iyi (ama cok fazla = asiri optimizasyon)
        complexity_score = min(1.0, (num_indicators + num_rules) / 8.0)
        
        # Rastgele performans (simulasyon)
        base_return = random.uniform(-0.2, 0.5) * complexity_score
        sharpe = random.uniform(0.5, 2.5) * complexity_score
        drawdown = random.uniform(0.05, 0.25)
        win_rate = random.uniform(0.45, 0.65)
        trades = random.randint(20, 200)
        profit_factor = random.uniform(0.8, 2.5)
        
        # Skor = Sharpe * WinRate / Drawdown
        score = (sharpe * win_rate) / (drawdown + 0.01)
        
        return StrategyResult(
            strategy=strategy,
            total_return=base_return,
            sharpe_ratio=sharpe,
            max_drawdown=drawdown,
            win_rate=win_rate,
            total_trades=trades,
            profit_factor=profit_factor,
            score=score,
        )
    
    def evolve_generation(self, population_size: int = 20, top_k: int = 5) -> List[StrategyResult]:
        """Bir nesil evrim gecir"""
        self.generation += 1
        
        # Yeni stratejiler uret
        new_strategies = self.generate_random(population_size)
        
        # Mevcut popülasyondan mutasyonlar
        if self.population:
            for _ in range(population_size // 2):
                parent = random.choice(self.population)
                mutated = self.mutate(parent)
                new_strategies.append(mutated)
                
        # Crossover
        if len(self.population) >= 2:
            for _ in range(population_size // 4):
                p1, p2 = random.sample(self.population, 2)
                child = self.crossover(p1, p2)
                new_strategies.append(child)
                
        # Test et
        results = [self.simulate_backtest(s) for s in new_strategies]
        
        # Sirala
        results.sort(key=lambda x: x.score, reverse=True)
        
        # En iyileri sakla
        self.results.extend(results)
        self.population = [r.strategy for r in results[:top_k]]
        
        # En iyi stratejiyi guncelle
        if results and results[0].score > self.best_score:
            self.best_score = results[0].score
            self.best_strategy = results[0].strategy
            
        return results
    
    def get_best_strategies(self, n: int = 5) -> List[StrategyResult]:
        """En iyi stratejileri al"""
        all_results = sorted(self.results, key=lambda x: x.score, reverse=True)
        return all_results[:n]
    
    def generate_report(self) -> str:
        """Fabrika raporu olustur"""
        best = self.get_best_strategies(3)
        
        report = f"""
==============================================================
           ATLAS ALPHA FACTORY - STRATEJI RAPORU              
==============================================================
  Nesil: {self.generation}
  Toplam Strateji: {len(self.population)}
  Test Edilen: {len(self.results)}
  
  EN IYI STRATEJI:
"""
        if self.best_strategy:
            report += f"""
    Isim: {self.best_strategy.name}
    Fitness: {self.best_score:.2f}
    Gostergeler: {len(self.best_strategy.indicators)}
    Giris Kurallari: {len(self.best_strategy.entry_rules)}
    Cikis Kurallari: {len(self.best_strategy.exit_rules)}
    Zaman Dilimi: {self.best_strategy.timeframe}
"""
            
        report += f"\n  TOP 3 STRATEJILER:\n"
        for i, result in enumerate(best, 1):
            report += f"""
    #{i} {result.strategy.name}
      Skor: {result.score:.2f} | Getiri: {result.total_return:+.1%} | Sharpe: {result.sharpe_ratio:.2f}
      DD: {result.max_drawdown:.1%} | WinRate: {result.win_rate:.1%} | Trades: {result.total_trades}
"""
            
        report += f"""
==============================================================
"""
        return report


# ==============================================================
# TEST
# ==============================================================

def test_alpha_factory():
    """Alpha Factory testi"""
    print("=" * 60)
    print("ATLAS ALPHA FACTORY - STRATEJI URETIM TESTI")
    print("=" * 60)
    
    factory = AtlasAlphaFactory()
    
    # 1. Rastgele strateji uret
    print("\n[1] Rastgele Strateji Uretimi")
    print("-" * 50)
    strategies = factory.generate_random(3)
    for s in strategies:
        print(f"  * {s.name}: {len(s.indicators)} gosterge, {len(s.entry_rules)} giris, {len(s.exit_rules)} cikis")
        print(f"    Gostergeler: {[i['name'] for i in s.indicators]}")
        print(f"    Giris: {s.entry_rules}")
        print(f"    Cikis: {s.exit_rules}")
        print(f"    Risk: SL {s.risk_params['stop_loss']:.0%}, TP {s.risk_params['take_profit']:.0%}")
        print()
    
    # 2. Mutasyon testi
    print("\n[2] Mutasyon Testi")
    print("-" * 50)
    original = strategies[0]
    mutated = factory.mutate(original, mutation_rate=0.5)
    print(f"  Orijinal: {original.name}")
    print(f"    Gostergeler: {[i['name'] for i in original.indicators]}")
    print(f"  Mutasyon: {mutated.name}")
    print(f"    Gostergeler: {[i['name'] for i in mutated.indicators]}")
    print(f"    Nesil: {mutated.generation}")
    
    # 3. Crossover testi
    print("\n[3] Crossover Testi")
    print("-" * 50)
    if len(strategies) >= 2:
        child = factory.crossover(strategies[0], strategies[1])
        print(f"  Ebeveyn 1: {strategies[0].name} ({len(strategies[0].indicators)} gosterge)")
        print(f"  Ebeveyn 2: {strategies[1].name} ({len(strategies[1].indicators)} gosterge)")
        print(f"  Cocuk: {child.name} ({len(child.indicators)} gosterge)")
        print(f"    Gostergeler: {[i['name'] for i in child.indicators]}")
        print(f"    Giris: {child.entry_rules}")
        print(f"    Nesil: {child.generation}")
    
    # 4. Evrim
    print("\n[4] Evrim Simulasyonu (3 Nesil)")
    print("-" * 50)
    for gen in range(1, 4):
        results = factory.evolve_generation(population_size=10, top_k=3)
        best = results[0]
        print(f"  Nesil {gen}: En iyi = {best.strategy.name} (Skor: {best.score:.2f}, Getiri: {best.total_return:+.1%})")
    
    # 5. Rapor
    print("\n" + "=" * 60)
    print(factory.generate_report())
    
    # 6. En iyi strateji detayi
    print("\n[5] En Iyi Strateji Detayi")
    print("-" * 50)
    if factory.best_strategy:
        best = factory.best_strategy
        print(f"  Isim: {best.name}")
        print(f"  Hash: {best.get_hash()}")
        print(f"  Nesil: {best.generation}")
        print(f"  Zaman Dilimi: {best.timeframe}")
        print(f"  Gostergeler:")
        for ind in best.indicators:
            print(f"    - {ind['name']}: {ind['params']}")
        print(f"  Giris Kurallari:")
        for rule in best.entry_rules:
            print(f"    - {rule}")
        print(f"  Cikis Kurallari:")
        for rule in best.exit_rules:
            print(f"    - {rule}")
        print(f"  Pozisyon Boyutlandirma: {best.position_sizing}")
        print(f"  Risk Parametreleri: {best.risk_params}")
    
    print("\n" + "=" * 60)
    print("[OK] ALPHA FACTORY TEST TAMAMLANDI")
    print("=" * 60)


if __name__ == "__main__":
    test_alpha_factory()