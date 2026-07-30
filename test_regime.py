from intelligence.regime.market_regime_engine import MarketRegimeEngine


engine = MarketRegimeEngine()


result = engine.analyze(
    trend_strength=85,
    volatility=60,
    volume_change=35
)


print("="*50)
print("ATLAS MARKET REGIME ENGINE")
print("="*50)

print(result)