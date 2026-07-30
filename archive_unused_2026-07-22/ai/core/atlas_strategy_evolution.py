# -*- coding: utf-8 -*-
"""
ATLAS STRATEGY EVOLUTION
Strateji evrimi - Basarili stratejileri mutasyon ve caprazlama ile gelistirir
"""
import random
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class StrategyGenome:
    """Strateji genomu - evrim icin temel birim"""
    id: str
    dna: Dict  # Strateji parametreleri
    fitness: float = 0.0
    generation: int = 0
    wins: int = 0
    losses: int = 0
    total_return: float = 0.0
    sharpe: float = 0.0
    max_dd: float = 0.0
    trades: int = 0
    parent_ids: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def win_rate(self) -> float:
        """Kazanma orani"""
        total = self.wins + self.losses
        return self.wins / total if total > 0 else 0.0
    
    def to_dict(self) -> Dict:
        """Sozluge cevir"""
        return {
            "id": self.id,
            "fitness": self.fitness,
            "generation": self.generation,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate(),
            "total_return": self.total_return,
            "sharpe": self.sharpe,
            "max_dd": self.max_dd,
            "trades": self.trades,
            "parent_ids": self.parent_ids,
        }


class AtlasStrategyEvolution:
    """
    Atlas AI Strateji Evrim Motoru
    
    Darwinian Selection prensibi:
    1. Populasyon olustur
    2. Her bireyi degerlendir (fitness)
    3. En iyileri sec (selection)
    4. Caprazla (crossover)
    5. Mutasyona ugrat (mutation)
    6. Yeni nesil olustur
    7. Tekrarla
    """
    
    def __init__(self, population_size: int = 50, mutation_rate: float = 0.15,
                 crossover_rate: float = 0.7, elitism: int = 3):
        self.population_size = population_size
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate
        self.elitism = elitism  # En iyi kac birey direkt aktarilsin
        
        self.population: List[StrategyGenome] = []
        self.generation = 0
        self.best_genome: Optional[StrategyGenome] = None
        self.history: List[Dict] = []
        
        # Parametre araliklari
        self.param_ranges = {
            "rsi_period": [7, 14, 21],
            "rsi_overbought": [65, 70, 75, 80],
            "rsi_oversold": [20, 25, 30, 35],
            "ema_fast": [8, 12, 20],
            "ema_slow": [50, 100, 200],
            "macd_fast": [8, 12],
            "macd_slow": [21, 26],
            "macd_signal": [9],
            "bb_period": [20],
            "bb_std": [2.0, 2.5, 3.0],
            "atr_period": [14],
            "atr_multiplier": [1.5, 2.0, 2.5, 3.0],
            "stop_loss": [0.02, 0.03, 0.05, 0.08, 0.10],
            "take_profit": [0.05, 0.08, 0.10, 0.15, 0.20, 0.25],
            "position_size": [0.05, 0.10, 0.15, 0.20],
            "max_positions": [3, 5, 7, 10],
        }
        
    def _random_genome(self) -> StrategyGenome:
        """Rastgele genom olustur"""
        dna = {}
        for param, values in self.param_ranges.items():
            dna[param] = random.choice(values)
            
        # Strateji tipi
        dna["strategy_type"] = random.choice(["momentum", "mean_reversion", "trend_following", "breakout"])
        
        # Giris kosullari
        dna["entry_conditions"] = random.sample([
            "rsi_oversold", "rsi_overbought", "macd_bullish", "macd_bearish",
            "ema_golden_cross", "ema_death_cross", "bb_lower_touch", "bb_upper_touch",
            "volume_spike", "atr_breakout"
        ], k=random.randint(2, 4))
        
        # Cikis kosullari
        dna["exit_conditions"] = random.sample([
            "rsi_reverse", "macd_reverse", "ema_cross_reverse", "bb_middle",
            "trailing_stop", "time_exit", "profit_target", "stop_loss_hit"
        ], k=random.randint(2, 3))
        
        return StrategyGenome(
            id=f"GEN_{self.generation}_{random.randint(1000, 9999)}",
            dna=dna,
            generation=self.generation,
        )
    
    def _mutate(self, genome: StrategyGenome) -> StrategyGenome:
        """Genomu mutasyona ugrat"""
        new_dna = dict(genome.dna)
        
        # Rastgele parametreleri degistir
        for param, values in self.param_ranges.items():
            if random.random() < self.mutation_rate:
                new_dna[param] = random.choice(values)
                
        # Strateji tipi mutasyonu
        if random.random() < self.mutation_rate:
            new_dna["strategy_type"] = random.choice(["momentum", "mean_reversion", "trend_following", "breakout"])
            
        # Kosul mutasyonu
        if random.random() < self.mutation_rate:
            all_conditions = [
                "rsi_oversold", "rsi_overbought", "macd_bullish", "macd_bearish",
                "ema_golden_cross", "ema_death_cross", "bb_lower_touch", "bb_upper_touch",
                "volume_spike", "atr_breakout", "rsi_reverse", "macd_reverse",
                "ema_cross_reverse", "bb_middle", "trailing_stop", "time_exit",
                "profit_target", "stop_loss_hit"
            ]
            if random.random() < 0.5 and "entry_conditions" in new_dna:
                new_dna["entry_conditions"] = random.sample(all_conditions[:10], k=random.randint(2, 4))
            elif "exit_conditions" in new_dna:
                new_dna["exit_conditions"] = random.sample(all_conditions[10:], k=random.randint(2, 3))
                
        return StrategyGenome(
            id=f"GEN_{self.generation}_{random.randint(1000, 9999)}",
            dna=new_dna,
            generation=self.generation,
            parent_ids=[genome.id],
        )
    
    def _crossover(self, parent1: StrategyGenome, parent2: StrategyGenome) -> Tuple[StrategyGenome, StrategyGenome]:
        """Iki genomu caprazla"""
        child1_dna = {}
        child2_dna = {}
        
        for param in self.param_ranges.keys():
            if random.random() < 0.5:
                child1_dna[param] = parent1.dna.get(param, random.choice(self.param_ranges[param]))
                child2_dna[param] = parent2.dna.get(param, random.choice(self.param_ranges[param]))
            else:
                child1_dna[param] = parent2.dna.get(param, random.choice(self.param_ranges[param]))
                child2_dna[param] = parent1.dna.get(param, random.choice(self.param_ranges[param]))
                
        # Strateji tipi
        child1_dna["strategy_type"] = parent1.dna.get("strategy_type", "momentum")
        child2_dna["strategy_type"] = parent2.dna.get("strategy_type", "momentum")
        
        # Kosullar - karistir
        p1_entry = parent1.dna.get("entry_conditions", [])
        p2_entry = parent2.dna.get("entry_conditions", [])
        p1_exit = parent1.dna.get("exit_conditions", [])
        p2_exit = parent2.dna.get("exit_conditions", [])
        
        child1_dna["entry_conditions"] = list(set(p1_entry[:len(p1_entry)//2] + p2_entry[len(p2_entry)//2:]))
        child2_dna["entry_conditions"] = list(set(p2_entry[:len(p2_entry)//2] + p1_entry[len(p1_entry)//2:]))
        child1_dna["exit_conditions"] = list(set(p1_exit[:len(p1_exit)//2] + p2_exit[len(p2_exit)//2:]))
        child2_dna["exit_conditions"] = list(set(p2_exit[:len(p2_exit)//2] + p1_exit[len(p1_exit)//2:]))
        
        child1 = StrategyGenome(
            id=f"GEN_{self.generation}_{random.randint(1000, 9999)}",
            dna=child1_dna,
            generation=self.generation,
            parent_ids=[parent1.id, parent2.id],
        )
        child2 = StrategyGenome(
            id=f"GEN_{self.generation}_{random.randint(1000, 9999)}",
            dna=child2_dna,
            generation=self.generation,
            parent_ids=[parent1.id, parent2.id],
        )
        
        return child1, child2
    
    def _evaluate_fitness(self, genome: StrategyGenome) -> float:
        """Genom fitness'ini hesapla (simulasyon)"""
        random.seed(hash(genome.id) % 10000)
        
        # Strateji tipine gore temel performans
        strategy_bonus = {
            "momentum": 0.05,
            "mean_reversion": 0.03,
            "trend_following": 0.04,
            "breakout": 0.02,
        }.get(genome.dna.get("strategy_type", "momentum"), 0.0)
        
        # Parametre kalitesi
        sl = genome.dna.get("stop_loss", 0.05)
        tp = genome.dna.get("take_profit", 0.10)
        risk_reward = tp / sl if sl > 0 else 2.0
        
        # Rastgele performans (simulasyon)
        base_return = random.uniform(-0.15, 0.35) + strategy_bonus
        sharpe = random.uniform(0.5, 2.0) + strategy_bonus * 5
        drawdown = random.uniform(0.05, 0.20)
        win_rate = random.uniform(0.45, 0.60)
        trades = random.randint(30, 200)
        
        wins = int(trades * win_rate)
        losses = trades - wins
        
        # Fitness skoru: Sharpe * WinRate / Drawdown * RiskReward
        fitness = (sharpe * win_rate) / (drawdown + 0.01) * min(risk_reward, 3.0)
        
        genome.fitness = fitness
        genome.total_return = base_return
        genome.sharpe = sharpe
        genome.max_dd = drawdown
        genome.wins = wins
        genome.losses = losses
        genome.trades = trades
        
        return fitness
    
    def initialize_population(self):
        """Baslangic populasyonu olustur"""
        self.population = [self._random_genome() for _ in range(self.population_size)]
        self.generation = 0
        
    def evolve(self, generations: int = 10) -> List[StrategyGenome]:
        """Belirli sayida nesil evrim gecir"""
        if not self.population:
            self.initialize_population()
            
        for gen in range(generations):
            self.generation = gen
            
            # 1. Degerlendir
            for genome in self.population:
                self._evaluate_fitness(genome)
                
            # 2. Sirala
            self.population.sort(key=lambda x: x.fitness, reverse=True)
            
            # 3. En iyiyi kaydet
            current_best = self.population[0]
            if not self.best_genome or current_best.fitness > self.best_genome.fitness:
                self.best_genome = current_best
                
            # 4. Gecmise kaydet
            self.history.append({
                "generation": gen,
                "best_fitness": current_best.fitness,
                "avg_fitness": sum(g.fitness for g in self.population) / len(self.population),
                "best_return": current_best.total_return,
                "best_sharpe": current_best.sharpe,
                "best_winrate": current_best.win_rate(),
            })
            
            # 5. Yeni populasyon olustur
            new_population = []
            
            # Elitizm - en iyileri direkt aktar
            new_population.extend(self.population[:self.elitism])
            
            # Geri kalanini caprazla ve mutasyona ugrat
            while len(new_population) < self.population_size:
                # Turnuva secimi
                tournament_size = 3
                parent1 = max(random.sample(self.population, tournament_size), key=lambda x: x.fitness)
                parent2 = max(random.sample(self.population, tournament_size), key=lambda x: x.fitness)
                
                # Crossover
                if random.random() < self.crossover_rate:
                    child1, child2 = self._crossover(parent1, parent2)
                    new_population.extend([child1, child2])
                else:
                    # Mutasyon
                    child = self._mutate(parent1)
                    new_population.append(child)
                    
            # Populasyonu guncelle
            self.population = new_population[:self.population_size]
            
        # Son degerlendirme
        for genome in self.population:
            self._evaluate_fitness(genome)
        self.population.sort(key=lambda x: x.fitness, reverse=True)
        
        return self.population
    
    def get_evolution_stats(self) -> Dict:
        """Evrim istatistiklerini al"""
        if not self.history:
            return {}
            
        return {
            "generations": len(self.history),
            "best_fitness_ever": max(h["best_fitness"] for h in self.history),
            "avg_fitness_first": self.history[0]["avg_fitness"] if self.history else 0,
            "avg_fitness_last": self.history[-1]["avg_fitness"] if self.history else 0,
            "improvement": (self.history[-1]["avg_fitness"] - self.history[0]["avg_fitness"]) / abs(self.history[0]["avg_fitness"]) * 100 if self.history and self.history[0]["avg_fitness"] != 0 else 0,
        }
    
    def generate_report(self) -> str:
        """Evrim raporu olustur"""
        stats = self.get_evolution_stats()
        
        report = f"""
==============================================================
        ATLAS STRATEGY EVOLUTION - EVRIM RAPORU               
==============================================================
  Toplam Nesil: {stats.get('generations', 0)}
  Populasyon Boyutu: {self.population_size}
  Mutasyon Orani: {self.mutation_rate:.0%}
  Caprazlama Orani: {self.crossover_rate:.0%}
  Elitizm: {self.elitism}
  
  EVRIM ISTATISTIKLERI:
    En Iyi Fitness: {stats.get('best_fitness_ever', 0):.2f}
    Ilk Ortalama: {stats.get('avg_fitness_first', 0):.2f}
    Son Ortalama: {stats.get('avg_fitness_last', 0):.2f}
    Gelisim: {stats.get('improvement', 0):+.1f}%
  
  EN IYI GENOM:
"""
        if self.best_genome:
            bg = self.best_genome
            report += f"""
    ID: {bg.id}
    Nesil: {bg.generation}
    Fitness: {bg.fitness:.2f}
    Strateji: {bg.dna.get('strategy_type', 'Bilinmiyor')}
    Getiri: {bg.total_return:+.1%}
    Sharpe: {bg.sharpe:.2f}
    Max DD: {bg.max_dd:.1%}
    WinRate: {bg.win_rate():.1%}
    Trades: {bg.trades}
    Kazanma: {bg.wins} | Kayip: {bg.losses}
    
    PARAMETRELER:
"""
            for param, value in bg.dna.items():
                if param not in ["entry_conditions", "exit_conditions"]:
                    report += f"      {param:20s}: {value}\n"
            report += f"""
    GIRIS KOSULLARI:
"""
            for cond in bg.dna.get("entry_conditions", []):
                report += f"      - {cond}\n"
            report += f"""
    CIKIS KOSULLARI:
"""
            for cond in bg.dna.get("exit_conditions", []):
                report += f"      - {cond}\n"
                
        report += f"""
  NESIL GRAFIK:
"""
        for h in self.history:
            bar = "+" * int(h["best_fitness"] / 2)
            report += f"    Nesil {h['generation']:2d}: {bar} {h['best_fitness']:.1f} (avg: {h['avg_fitness']:.1f})\n"
            
        report += f"""
==============================================================
"""
        return report


# ==============================================================
# TEST
# ==============================================================

def test_strategy_evolution():
    """Strateji evrimi testi"""
    print("=" * 60)
    print("ATLAS STRATEGY EVOLUTION - DARWINIAN SELECTION TESTI")
    print("=" * 60)
    
    # 1. Basit evrim
    print("\n[1] 10 Nesil Evrim (Populasyon: 20)")
    print("-" * 50)
    
    evo = AtlasStrategyEvolution(population_size=20, mutation_rate=0.15, elitism=2)
    evo.initialize_population()
    
    print(f"  Baslangic populasyonu: {len(evo.population)} birey")
    print(f"  Mutasyon orani: {evo.mutation_rate}")
    print(f"  Elitizm: {evo.elitism}")
    
    # Evrim gecir
    final_pop = evo.evolve(generations=10)
    
    print(f"\n  Evrim tamamlandi!")
    print(f"  Final populasyon: {len(final_pop)} birey")
    print(f"  En iyi fitness: {evo.best_genome.fitness:.2f}" if evo.best_genome else "  En iyi: Yok")
    
    # 2. Istatistikler
    print("\n[2] Evrim Istatistikleri")
    print("-" * 50)
    stats = evo.get_evolution_stats()
    print(f"  Nesil sayisi: {stats['generations']}")
    print(f"  En iyi fitness: {stats['best_fitness_ever']:.2f}")
    print(f"  Ilk ortalama: {stats['avg_fitness_first']:.2f}")
    print(f"  Son ortalama: {stats['avg_fitness_last']:.2f}")
    print(f"  Gelisim: {stats['improvement']:+.1f}%")
    
    # 3. En iyi strateji
    print("\n[3] En Iyi Strateji")
    print("-" * 50)
    if evo.best_genome:
        best = evo.best_genome
        print(f"  ID: {best.id}")
        print(f"  Tip: {best.dna.get('strategy_type')}")
        print(f"  Fitness: {best.fitness:.2f}")
        print(f"  Getiri: {best.total_return:+.1%}")
        print(f"  Sharpe: {best.sharpe:.2f}")
        print(f"  Max DD: {best.max_dd:.1%}")
        print(f"  WinRate: {best.win_rate():.1%}")
        print(f"  Trades: {best.trades}")
        print(f"  RSI Period: {best.dna.get('rsi_period')}")
        print(f"  Stop Loss: {best.dna.get('stop_loss')}")
        print(f"  Take Profit: {best.dna.get('take_profit')}")
    
    # 4. Rapor
    print("\n" + "=" * 60)
    print(evo.generate_report())
    
    # 5. Top 5 strateji
    print("\n[4] Top 5 Strateji")
    print("-" * 50)
    top5 = sorted(evo.population, key=lambda x: x.fitness, reverse=True)[:5]
    for i, g in enumerate(top5, 1):
        print(f"  #{i} {g.id} | Fitness: {g.fitness:.2f} | {g.dna.get('strategy_type')} | Getiri: {g.total_return:+.1%}")
    
    print("\n" + "=" * 60)
    print("[OK] STRATEJI EVRIMI TEST TAMAMLANDI")
    print("=" * 60)


if __name__ == "__main__":
    test_strategy_evolution()