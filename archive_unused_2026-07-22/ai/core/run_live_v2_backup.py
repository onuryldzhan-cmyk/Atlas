"""
ATLAS AI - Canli Test Scripti
Orchestrator'u dogrudan kullanir, rapor uretir
"""

import sys
import time
from datetime import datetime

# Orchestrator'u import et
from atlas_orchestrator import AtlasOrchestrator, MarketData
import random


def create_demo_market_data() -> list:
    """Demo piyasa verisi olustur"""
    symbols = [
        ("BTCUSDT", 65000, 0.05), ("ETHUSDT", 3500, 0.08),
        ("SOLUSDT", 150, 0.12), ("BNBUSDT", 580, -0.03),
        ("ADAUSDT", 0.45, 0.02), ("XRPUSDT", 0.60, 0.01),
        ("DOTUSDT", 7.5, -0.02), ("DOGEUSDT", 0.12, 0.15),
        ("AVAXUSDT", 28, 0.08), ("LINKUSDT", 14, 0.03),
        ("MATICUSDT", 0.70, -0.01), ("LTCUSDT", 75, 0.02),
        ("UNIUSDT", 9, 0.05), ("ATOMUSDT", 6.5, -0.03),
        ("ETCUSDT", 25, 0.04), ("XLMUSDT", 0.10, 0.01),
        ("ALGOUSDT", 0.15, 0.06), ("VETUSDT", 0.03, 0.02),
        ("FILUSDT", 4.5, -0.01), ("TRXUSDT", 0.12, 0.01),
    ]

    data = []
    for symbol, base_price, change in symbols:
        rsi = random.uniform(20, 80)
        macd = random.uniform(-0.5, 0.5)
        ema_20 = base_price * (1 + random.uniform(-0.02, 0.02))
        ema_50 = base_price * (1 + random.uniform(-0.05, 0.05))
        bb_upper = base_price * 1.05
        bb_lower = base_price * 0.95
        atr = base_price * 0.02

        data.append(MarketData(
            symbol=symbol,
            price=base_price * (1 + change),
            volume_24h=random.uniform(1e6, 1e9),
            change_24h=change * 100,
            rsi=rsi,
            macd=macd,
            ema_20=ema_20,
            ema_50=ema_50,
            bb_upper=bb_upper,
            bb_lower=bb_lower,
            atr=atr,
            timestamp=datetime.now()
        ))

    return data


def main():
    print("=" * 70)
    print("ATLAS AI - CANLI TEST (CIO + Explainability Entegreli)")
    print("=" * 70)
    print("Durdurmak icin: Ctrl+C")
    print("=" * 70)

    # Orchestrator'u baslat
    orch = AtlasOrchestrator(config={
        'min_confidence': 0.2,
        'max_position_size': 0.15,
        'max_positions': 5
    })

    cycle = 0
    interval = 60  # saniye

    try:
        while True:
            cycle += 1
            print(f"\n{'='*70}")
            print(f"DONGU #{cycle} - {datetime.now().strftime('%H:%M:%S')}")
            print(f"{'='*70}")

            # Piyasa verisi olustur
            market_data = create_demo_market_data()

            # Dongu calistir
            result = orch.run_cycle(market_data)

            # Ozet yazdir
            print(f"\n[OZET]")
            print(f"  Kararlar: {len(result['decisions'])}")
            print(f"  Uygulanan: {len(result['executed'])}")
            print(f"  Portfoy: ${result['status']['portfolio_value']:.2f}")
            print(f"  Nakit: ${result['status']['cash']:.2f}")
            print(f"  Pozisyon: {result['status']['active_positions']}")

            if 'cio' in result['status']:
                cio = result['status']['cio']
                print(f"  [CIO] Rejim: {cio['regime'].upper()} | Risk: {cio['risk_profile']}")

            # Rapor kontrolu
            import os
            report_dir = "reports"
            if os.path.exists(report_dir):
                reports = [f for f in os.listdir(report_dir) if f.endswith('.txt')]
                print(f"  Raporlar: {len(reports)} adet")
                if reports:
                    latest = sorted(reports)[-1]
                    print(f"  Son rapor: {latest}")

            print(f"\n[SLEEP] Sonraki dongu: {interval} saniye...")
            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n{'='*70}")
        print("Kullanici tarafindan durduruldu")
        print(f"{'='*70}")

    finally:
        # Final durum
        status = orch.get_status()
        print(f"\n[FINAL DURUM]")
        print(f"  Toplam Dongu: {status['cycle_count']}")
        print(f"  Portfoy: ${status['portfolio_value']:.2f}")
        print(f"  Nakit: ${status['cash']:.2f}")
        print(f"  Pozisyonlar: {status['active_positions']}")

        if status['positions']:
            print(f"\n  Aktif Pozisyonlar:")
            for sym, pos in status['positions'].items():
                print(f"    {sym}: {pos['qty']:.4f} @ ${pos['entry']:.2f}")

        # Raporlari listele
        if os.path.exists(report_dir):
            reports = [f for f in os.listdir(report_dir) if f.endswith('.txt')]
            print(f"\n  Uretilen Raporlar: {len(reports)}")
            for r in sorted(reports)[-5:]:  # Son 5 rapor
                print(f"    - {r}")

        print(f"\n{'='*70}")
        print("ATLAS AI - TEST TAMAMLANDI")
        print(f"{'='*70}")


if __name__ == "__main__":
    main()

# =============================================================================
# FAZ 2 ENTEGRASYONU (Alpha Factory + Strategy Evolution + Research Engine)
# =============================================================================
from atlas_alpha_factory import AtlasAlphaFactory
from atlas_strategy_evolution import AtlasStrategyEvolution
from atlas_research_engine import AtlasResearchEngine

# Faz 2 modullerini baslat
alpha_factory = AtlasAlphaFactory("alpha_catalog.json")
strategy_evolution = AtlasStrategyEvolution("evolution_population.json")
research_engine = AtlasResearchEngine("research_knowledge.json")

if not strategy_evolution.population:
    print("[FAZ2] Baslangic populasyonu olusturuluyor...")
    strategy_evolution.create_initial_population(10)

print("[FAZ2] Faz 2 modulleri hazir!")

# Her dongu sonrasi Faz 2 analizi
def run_faz2_analysis(market_data_dict):
    """Faz 2 analizlerini calistir"""
    # Research
    report = research_engine.generate_research_report(market_data_dict)
    print(f"[FAZ2-RESEARCH] {len(report.findings)} bulgu, {len(report.recommendations)} oneri")
    
    # Evolution
    for org in strategy_evolution.population:
        if org.is_alive and org.total_trades < 20:
            for _ in range(random.randint(1, 2)):
                org.record_trade(random.uniform(-20, 50), random.uniform(0, 0.08))
    
    best = strategy_evolution.get_best_organism()
    if best:
        print(f"[FAZ2-EVOLUTION] En iyi: {best.name} (Fitness: {best.fitness:.3f})")
    
    # Alpha
    if random.random() < 0.3:
        new_strategies = alpha_factory.generate_new_strategies(1)
        for s in new_strategies:
            alpha_factory.add_to_catalog(s)
        print(f"[FAZ2-ALPHA] {len(new_strategies)} yeni strateji")
    
    return report

print("[FAZ2] Entegrasyon tamamlandi!")
