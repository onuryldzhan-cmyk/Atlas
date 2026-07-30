"""
ATLAS AI - CANLI TEST v3.0
FAZ 1 + FAZ 2 Entegre Sistem

Moduller:
- FAZ 1: Memory, Reasoning, World Model, Multi-Agent, CIO, Explainability
- FAZ 2: Alpha Factory, Strategy Evolution, Research Engine

Her dongude:
1. Piyasa verisi al
2. Research Engine analiz yapar
3. CIO rejim belirler
4. Multi-Agent karar verir
5. Alpha Factory yeni strateji onerir
6. Strategy Evolution en iyisini secer
7. Pozisyon ac/kapat
8. Rapor uret
"""

import sys
import os
import time
import json
import random
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

# Logging ayarlari
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AtlasOrchestrator")

# =============================================================================
# FAZ 1 MODULLERI
# =============================================================================
from atlas_memory_core import AtlasMemoryCore
from atlas_reasoning_engine import AtlasReasoningEngine
from atlas_world_model import AtlasWorldModel
from atlas_multi_agent import AtlasMultiAgentSystem

# CIO ve Explainability (mevcut dosyalardan)
try:
    from atlas_cio import AtlasCIO
    from atlas_explainability import AtlasExplainability
except ImportError:
    # Basit versiyonlar
    class AtlasCIO:
        def __init__(self, memory_core):
            self.memory = memory_core
            self.market_regime = "SIDEWAYS"
            self.risk_profile = "moderate"
            print("[CIO] Atlas CIO baslatildi!")

        def analyze_market_regime(self, market_data):
            returns = [d.get("return_24h", 0) for d in market_data.values()]
            avg_ret = sum(returns) / len(returns) if returns else 0
            vol = max(returns) - min(returns) if returns else 0

            if avg_ret > 0.03 and vol < 0.1:
                self.market_regime = "BULLISH"
                self.risk_profile = "aggressive"
            elif avg_ret < -0.03 and vol > 0.05:
                self.market_regime = "BEARISH"
                self.risk_profile = "defensive"
            elif vol > 0.08:
                self.market_regime = "VOLATILE"
                self.risk_profile = "conservative"
            else:
                self.market_regime = "SIDEWAYS"
                self.risk_profile = "moderate"

            return {
                "regime": self.market_regime,
                "risk_profile": self.risk_profile,
                "avg_return": avg_ret,
                "volatility": vol
            }

        def get_trade_settings(self):
            settings = {
                "SIDEWAYS": {"max_positions": 5, "max_size": 0.15, "min_conf": 0.2},
                "BULLISH": {"max_positions": 10, "max_size": 0.20, "min_conf": 0.15},
                "BEARISH": {"max_positions": 3, "max_size": 0.10, "min_conf": 0.3},
                "VOLATILE": {"max_positions": 2, "max_size": 0.08, "min_conf": 0.4}
            }
            return settings.get(self.market_regime, settings["SIDEWAYS"])

        def approve_asset(self, asset, sector="other"):
            return True

    class AtlasExplainability:
        def __init__(self):
            print("[EXPLAINABILITY] Atlas Explainability baslatildi!")

        def explain_decision(self, decision, agents_results, cio_settings):
            return f"Karar: {decision} | Rejim: {cio_settings.get('regime', 'N/A')} | Risk: {cio_settings.get('risk_profile', 'N/A')}"


# =============================================================================
# FAZ 2 MODULLERI
# =============================================================================
from atlas_alpha_factory import AtlasAlphaFactory, StrategyDNA
from atlas_strategy_evolution import AtlasStrategyEvolution, StrategyOrganism
from atlas_research_engine import AtlasResearchEngine, ResearchReport


# =============================================================================
# ORKESTRATOR
# =============================================================================
class AtlasOrchestrator:
    """
    Atlas AI Ana Orkestratoru
    Tum modulleri koordine eder
    """

    COINS = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT",
        "XRPUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT",
        "MATICUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "ETCUSDT",
        "XLMUSDT", "ALGOUSDT", "VETUSDT", "FILUSDT", "TRXUSDT"
    ]

    SECTORS = {
        "BTCUSDT": "blue_chip", "ETHUSDT": "blue_chip",
        "SOLUSDT": "layer1", "BNBUSDT": "exchange",
        "ADAUSDT": "layer1", "XRPUSDT": "payment",
        "DOTUSDT": "infrastructure", "DOGEUSDT": "meme",
        "AVAXUSDT": "layer1", "LINKUSDT": "infrastructure",
        "MATICUSDT": "infrastructure", "LTCUSDT": "legacy",
        "UNIUSDT": "defi", "ATOMUSDT": "layer1",
        "ETCUSDT": "legacy", "XLMUSDT": "payment",
        "ALGOUSDT": "layer1", "VETUSDT": "payment",
        "FILUSDT": "infrastructure", "TRXUSDT": "other"
    }

    def __init__(self, paper_balance: float = 10000.0):
        self.paper_balance = paper_balance
        self.cash = paper_balance
        self.positions: Dict[str, Dict] = {}
        self.trade_history: List[Dict] = []
        self.reports: List[str] = []
        self.loop_count = 0

        # FAZ 1 Modulleri
        print("\n" + "=" * 70)
        print("ATLAS AI v3.0 - FAZ 1 + FAZ 2 ENTEGRE SISTEM")
        print("=" * 70)

        self.memory = AtlasMemoryCore()
        self.reasoning = AtlasReasoningEngine(self.memory)
        self.world_model = AtlasWorldModel()
        self.multi_agent = AtlasMultiAgentSystem(self.memory)

        # Ajanlari kaydet
        self.multi_agent.register_agent("TechnicalAnalyst", "technical", 1.0)
        self.multi_agent.register_agent("MacroAnalyst", "macro", 0.9)
        self.multi_agent.register_agent("RiskManager", "risk", 1.1)
        self.multi_agent.register_agent("SentimentAnalyzer", "sentiment", 0.8)
        self.multi_agent.register_agent("QuantStrategist", "quant", 1.0)
        logger.info("[ORCHESTRATOR] 5 ajan kaydedildi")

        self.cio = AtlasCIO(self.memory)
        logger.info("[ORCHESTRATOR] CIO modulu basariliyla yuklendi!")

        self.explainability = AtlasExplainability()
        logger.info("[ORCHESTRATOR] Explainability modulu basariliyla yuklendi!")

        # FAZ 2 Modulleri
        self.alpha_factory = AtlasAlphaFactory("alpha_catalog.json")
        self.strategy_evolution = AtlasStrategyEvolution("evolution_population.json")
        self.research_engine = AtlasResearchEngine("research_knowledge.json")

        # Eger populasyon bos ise baslangic olustur
        if not self.strategy_evolution.population:
            logger.info("[ORCHESTRATOR] Baslangic populasyonu olusturuluyor...")
            self.strategy_evolution.create_initial_population(10)

        logger.info("[ORCHESTRATOR] Faz 2 modulleri basariliyla yuklendi!")
        logger.info("[ORCHESTRATOR] Atlas Orchestrator baslatildi!")

        # Simulasyon verisi
        self.base_prices = {
            "BTCUSDT": 65000, "ETHUSDT": 3500, "SOLUSDT": 150,
            "BNBUSDT": 600, "ADAUSDT": 0.45, "XRPUSDT": 0.60,
            "DOTUSDT": 7.20, "DOGEUSDT": 0.12, "AVAXUSDT": 28,
            "LINKUSDT": 14, "MATICUSDT": 0.55, "LTCUSDT": 75,
            "UNIUSDT": 9.50, "ATOMUSDT": 6.80, "ETCUSDT": 26,
            "XLMUSDT": 0.11, "ALGOUSDT": 0.16, "VETUSDT": 0.03,
            "FILUSDT": 4.50, "TRXUSDT": 0.12
        }

    def simulate_market_data(self) -> Dict[str, Dict]:
        """Simule piyasa verisi uret"""
        data = {}
        for coin in self.COINS:
            base = self.base_prices.get(coin, 100)
            change = random.uniform(-0.08, 0.12)
            price = base * (1 + change)

            data[coin] = {
                "price": round(price, 8 if price < 1 else 2),
                "return_24h": round(change, 4),
                "return_7d": round(change * random.uniform(3, 7), 4),
                "volume_change": round(random.uniform(0.3, 4.0), 2),
                "volatility": round(random.uniform(0.01, 0.12), 4),
                "sector": self.SECTORS.get(coin, "other")
            }
        return data

    def run_research_phase(self, market_data: Dict[str, Dict]) -> ResearchReport:
        """Arastirma fazini calistir"""
        logger.info("[RESEARCH] Piyasa analizi baslatiliyor...")

        # Research Engine ile analiz
        report = self.research_engine.generate_research_report(market_data)

        logger.info(f"[RESEARCH] Rapor uretildi: {len(report.findings)} bulgu, {len(report.recommendations)} oneri")

        # Bulgulari memory'ye kaydet
        for finding in report.findings:
            self.memory.add_experience(
                event_type="research_finding",
                data=finding,
                outcome="info",
                tags=["research", finding.get("type", "general")]
            )

        return report

    def run_evolution_phase(self, market_data: Dict[str, Dict]):
        """Evrim fazini calistir"""
        logger.info("[EVOLUTION] Strateji evrimi calistiriliyor...")

        # Mevcut populasyonu degerlendir (simule trade'lerle)
        for org in self.strategy_evolution.population:
            if org.is_alive and org.total_trades < 20:
                # Simule trade kaydet
                for _ in range(random.randint(1, 3)):
                    profit = random.uniform(-30, 80)
                    dd = random.uniform(0, 0.1)
                    org.record_trade(profit, dd)

        # Her 5 dongude bir evrimlestir
        if self.loop_count % 5 == 0 and self.loop_count > 0:
            logger.info("[EVOLUTION] Nesil evrimlestiriliyor...")
            self.strategy_evolution.evolve_generation(12)

        # En iyi stratejiyi al
        best = self.strategy_evolution.get_best_organism()
        if best:
            logger.info(f"[EVOLUTION] En iyi strateji: {best.name} (Fitness: {best.fitness:.3f})")

        return best

    def run_alpha_phase(self) -> Optional[StrategyDNA]:
        """Alpha uretim fazini calistir"""
        # Her 3 dongude bir yeni strateji uret
        if self.loop_count % 3 == 0:
            logger.info("[ALPHA] Yeni stratejiler uretiliyor...")
            new_strategies = self.alpha_factory.generate_new_strategies(2)
            for s in new_strategies:
                self.alpha_factory.add_to_catalog(s)
            logger.info(f"[ALPHA] {len(new_strategies)} yeni strateji kataloga eklendi")
            return new_strategies[0] if new_strategies else None
        return None

    def run_trading_cycle(self):
        """Bir trading dongusu calistir"""
        self.loop_count += 1

        logger.info("\n" + "=" * 70)
        logger.info(f"[ORCHESTRATOR] DONGU #{self.loop_count} BASLIYOR")
        logger.info("=" * 70)

        # 1. Piyasa verisi al
        market_data = self.simulate_market_data()
        logger.info(f"[ORCHESTRATOR] {len(market_data)} coin icin veri alindi")

        # 2. FAZ 2: Research Phase
        research_report = self.run_research_phase(market_data)

        # 3. FAZ 2: Evolution Phase
        best_strategy = self.run_evolution_phase(market_data)

        # 4. FAZ 2: Alpha Phase
        new_alpha = self.run_alpha_phase()

        # 5. FAZ 1: CIO Analiz
        regime = self.cio.analyze_market_regime(market_data)
        logger.info(f"[CIO] Piyasa Rejimi: {regime['regime']} | Risk: {regime['risk_profile']}")

        settings = self.cio.get_trade_settings()
        logger.info(f"[ORCHESTRATOR] CIO ayarlari uygulandi: max_pos={settings['max_positions']}, max_size={settings['max_size']}")

        # 6. FAZ 1: Multi-Agent Karar
        decisions = []
        for coin in self.COINS[:10]:  # Ilk 10 coin
            if not self.cio.approve_asset(coin, self.SECTORS.get(coin, "other")):
                continue

            # Simule ajan kararlari
            agent_results = {
                "technical": {"signal": random.choice(["BUY", "SELL", "HOLD"]), "confidence": random.uniform(0.3, 0.9)},
                "macro": {"signal": random.choice(["BUY", "SELL", "HOLD"]), "confidence": random.uniform(0.3, 0.8)},
                "risk": {"signal": random.choice(["BUY", "HOLD"]), "confidence": random.uniform(0.5, 0.9)},
                "sentiment": {"signal": random.choice(["BUY", "SELL", "HOLD"]), "confidence": random.uniform(0.3, 0.7)},
                "quant": {"signal": random.choice(["BUY", "SELL", "HOLD"]), "confidence": random.uniform(0.4, 0.8)}
            }

            # Fused signal
            buy_votes = sum(1 for r in agent_results.values() if r["signal"] == "BUY")
            sell_votes = sum(1 for r in agent_results.values() if r["signal"] == "SELL")

            if buy_votes >= 3 and coin not in self.positions:
                conf = sum(r["confidence"] for r in agent_results.values() if r["signal"] == "BUY") / buy_votes
                if conf >= settings["min_conf"]:
                    decisions.append(("BUY", coin, conf))
            elif sell_votes >= 3 and coin in self.positions:
                conf = sum(r["confidence"] for r in agent_results.values() if r["signal"] == "SELL") / sell_votes
                decisions.append(("SELL", coin, conf))

        # 7. FAZ 2: Research onerilerini degerlendir
        for rec in research_report.recommendations:
            # Onerileri rapora ekle
            self.reports.append(f"[RESEARCH] {rec}")

        # 8. Pozisyon yonetimi
        executed = 0
        for action, coin, conf in decisions:
            if action == "BUY" and len(self.positions) < settings["max_positions"]:
                size = min(settings["max_size"], 0.15)
                amount = (self.paper_balance * size) / market_data[coin]["price"]
                cost = amount * market_data[coin]["price"]

                if cost <= self.cash:
                    self.positions[coin] = {
                        "amount": amount,
                        "entry_price": market_data[coin]["price"],
                        "entry_time": datetime.now().isoformat(),
                        "confidence": conf
                    }
                    self.cash -= cost
                    executed += 1
                    logger.info(f"[TRADE] {coin}: Pozisyon acildi: {amount:.4f} @ {market_data[coin]['price']}")

                    # Memory'ye kaydet
                    self.memory.add_experience(
                        event_type="trade_open",
                        data={"coin": coin, "amount": amount, "price": market_data[coin]["price"]},
                        outcome="success",
                        tags=["trade", coin]
                    )

            elif action == "SELL" and coin in self.positions:
                pos = self.positions[coin]
                current_price = market_data[coin]["price"]
                pnl = (current_price - pos["entry_price"]) * pos["amount"]

                self.cash += pos["amount"] * current_price
                del self.positions[coin]
                executed += 1
                logger.info(f"[TRADE] {coin}: Pozisyon kapandi. PnL: ${pnl:.2f}")

                # Memory'ye kaydet
                self.memory.add_experience(
                    event_type="trade_close",
                    data={"coin": coin, "pnl": pnl},
                    outcome="win" if pnl > 0 else "loss",
                    tags=["trade", coin, "win" if pnl > 0 else "loss"]
                )

        # 9. Portfoy degeri hesapla
        position_value = sum(
            pos["amount"] * market_data[coin]["price"]
            for coin, pos in self.positions.items()
        )
        total_value = self.cash + position_value

        # 10. Rapor uret
        report_lines = [
            f"\n[DURUM] Dongu: #{self.loop_count}",
            f"[DURUM] Portfoy: ${total_value:.2f} | Nakit: ${self.cash:.2f} | Pozisyon: {len(self.positions)}",
            f"[CIO] Rejim: {regime['regime']} | Risk: {regime['risk_profile']}",
            f"[RESEARCH] Bulgular: {len(research_report.findings)} | Oneriler: {len(research_report.recommendations)}",
        ]

        if best_strategy:
            report_lines.append(f"[EVOLUTION] En Iyi Strateji: {best_strategy.name} (Fitness: {best_strategy.fitness:.3f})")

        if new_alpha:
            report_lines.append(f"[ALPHA] Yeni Strateji: {new_alpha.name} ({len(new_alpha.genes)} gen)")

        report_lines.append(f"[TRADE] Uygulanan: {executed}")

        if self.positions:
            report_lines.append("\n[Aktif Pozisyonlar]:")
            for coin, pos in self.positions.items():
                current = market_data[coin]["price"]
                pnl_pct = (current - pos["entry_price"]) / pos["entry_price"] * 100
                report_lines.append(f"  {coin}: {pos['amount']:.4f} @ ${pos['entry_price']:.2f} (PnL: {pnl_pct:+.2f}%)")

        report_text = "\n".join(report_lines)
        logger.info(report_text)
        self.reports.append(report_text)

        # 11. Durum kaydet
        self._save_state()

        return report_text

    def _save_state(self):
        """Durumu kaydet"""
        state = {
            "loop_count": self.loop_count,
            "paper_balance": self.paper_balance,
            "cash": self.cash,
            "positions": self.positions,
            "reports_count": len(self.reports),
            "timestamp": datetime.now().isoformat()
        }
        with open("atlas_orchestrator_state_v3.json", "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        logger.info("[ORCHESTRATOR] Durum kaydedildi")

    def run(self, cycles: int = 5, sleep_seconds: int = 3):
        """Ana donguyu calistir"""
        print("\n" + "=" * 70)
        print("ATLAS AI v3.0 - CANLI TEST BASLIYOR")
        print("=" * 70)
        print(f"Dongu: {cycles} | Sleep: {sleep_seconds}s")
        print("Durdurmak icin: Ctrl+C")
        print("=" * 70)

        try:
            for i in range(cycles):
                self.run_trading_cycle()

                if i < cycles - 1:
                    logger.info(f"[SLEEP] Sonraki dongu: {sleep_seconds} saniye...")
                    time.sleep(sleep_seconds)

        except KeyboardInterrupt:
            print("\n\n[Kullanici tarafindan durduruldu]")

        # Final rapor
        self._print_final_report()

    def _print_final_report(self):
        """Final rapor"""
        print("\n" + "=" * 70)
        print("ATLAS AI v3.0 - FINAL RAPOR")
        print("=" * 70)
        print(f"Toplam Dongu: {self.loop_count}")
        print(f"Nakit: ${self.cash:.2f}")
        print(f"Pozisyonlar: {len(self.positions)}")

        if self.positions:
            print("\nAktif Pozisyonlar:")
            for coin, pos in self.positions.items():
                print(f"  {coin}: {pos['amount']:.4f} @ ${pos['entry_price']:.2f}")

        print(f"\nUretilen Raporlar: {len(self.reports)}")
        print(f"Memory Kayitlari: {len(self.memory.episodes)}")
        print(f"Alpha Katalog: {len(self.alpha_factory.catalog)} strateji")
        print(f"Evrim Populasyonu: {len(self.strategy_evolution.population)} organizma")
        print(f"Research Pattern'leri: {len(self.research_engine.patterns)}")
        print(f"Research Anomalileri: {len(self.research_engine.anomalies)}")

        # Research raporu goster
        if self.research_engine.reports:
            print("\n" + "=" * 70)
            print("SON ARASTIRMA RAPORU:")
            print("=" * 70)
            print(self.research_engine.reports[-1].to_text())

        # Evolution raporu goster
        print("\n" + "=" * 70)
        print("EVRIM RAPORU:")
        print("=" * 70)
        print(self.strategy_evolution.get_evolution_report())

        print("\n" + "=" * 70)
        print("ATLAS AI v3.0 - TEST TAMAMLANDI")
        print("=" * 70)


# =============================================================================
# CALISTIR
# =============================================================================
if __name__ == "__main__":
    orchestrator = AtlasOrchestrator(paper_balance=10000.0)
    orchestrator.run(cycles=5, sleep_seconds=2)
