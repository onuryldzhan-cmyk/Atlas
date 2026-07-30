import random
from atlas_alpha_factory import AtlasAlphaFactory
from atlas_strategy_evolution import AtlasStrategyEvolution
from atlas_research_engine import AtlasResearchEngine

print('='*70)
print('ATLAS AI - FAZ 2 ANALIZ')
print('='*70)

alpha_factory = AtlasAlphaFactory('alpha_catalog.json')
strategy_evolution = AtlasStrategyEvolution('evolution_population.json')
research_engine = AtlasResearchEngine('research_knowledge.json')

if not strategy_evolution.population:
    print('[FAZ2] Baslangic populasyonu olusturuluyor...')
    strategy_evolution.create_initial_population(10)

market_data_dict = {}
for symbol, base_price, change in [
    ('BTCUSDT', 65000, 0.05), ('ETHUSDT', 3500, 0.08),
    ('SOLUSDT', 150, 0.12), ('BNBUSDT', 580, -0.03),
    ('ADAUSDT', 0.45, 0.02), ('XRPUSDT', 0.60, 0.01),
    ('DOTUSDT', 7.5, -0.02), ('DOGEUSDT', 0.12, 0.15),
    ('AVAXUSDT', 28, 0.08), ('LINKUSDT', 14, 0.03),
]:
    market_data_dict[symbol] = {
        'price': base_price * (1 + change),
        'return_24h': change,
        'volume_change': random.uniform(0.5, 3.0),
        'volatility': random.uniform(0.01, 0.10),
        'sector': 'crypto'
    }

report = research_engine.generate_research_report(market_data_dict)
print(report.to_text())

for org in strategy_evolution.population:
    if org.is_alive and org.total_trades < 20:
        for _ in range(random.randint(2, 5)):
            org.record_trade(random.uniform(-30, 80), random.uniform(0, 0.1))

best = strategy_evolution.get_best_organism()
if best:
    print(f'[FAZ2-EVOLUTION] En iyi: {best.name} (Fitness: {best.fitness:.3f})')

new_strategies = alpha_factory.generate_new_strategies(2)
for s in new_strategies:
    alpha_factory.add_to_catalog(s)
print(f'[FAZ2-ALPHA] {len(new_strategies)} yeni strateji')

print(alpha_factory.get_catalog_report())
print('='*70)
print('FAZ 2 ANALIZ TAMAMLANDI')
print('='*70)
