from data.binance_provider import BinanceProvider
from data.candle_manager import CandleManager

from analysis.technical_analyzer import TechnicalAnalyzer

from intelligence.market_intelligence import MarketIntelligence



provider = BinanceProvider()


candle = CandleManager(
    provider
)


technical = TechnicalAnalyzer()



brain = MarketIntelligence(

    candle,

    technical

)



result = brain.analyze(
    "BTCUSDT"
)



print("="*50)
print("ATLAS MARKET INTELLIGENCE TEST")
print("="*50)


print(result)


print()


print(
    brain.status()
)