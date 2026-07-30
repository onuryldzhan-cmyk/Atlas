from data.binance_provider import BinanceProvider
from data.candle_manager import CandleManager



print("="*50)
print("ATLAS MARKET DATA TEST")
print("="*50)



provider = BinanceProvider()


manager = CandleManager(
    provider
)



snapshot = manager.snapshot(
    "BTCUSDT"
)



print(snapshot)



print()


print(
    manager.status()
)