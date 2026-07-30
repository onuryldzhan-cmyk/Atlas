import asyncio
from datetime import datetime
import random

from strategy_manager import StrategyManager

class MultiCoinScanner:
    def __init__(self, symbols, initial_balance=10000.0, max_positions=10, offline_mode=True):
        self.symbols = [s.upper() for s in symbols]
        self.initial_balance = initial_balance
        self.max_positions = max_positions
        self.offline_mode = offline_mode
        self.managers = {}
        self.scan_count = 0
        self.signals_found = 0
        self.trades_executed = 0
        self._offline_prices = {}
        print("🔍 Atlas AI Multi-Coin Scanner v2")
        print(f"   Coinler: {len(self.symbols)} | Mode: {'OFFLINE' if offline_mode else 'LIVE'}")

    def _generate_offline_data(self, symbol):
        if symbol not in self._offline_prices:
            base = {'BTCUSDT': 65000, 'ETHUSDT': 3500, 'SOLUSDT': 150, 'BNBUSDT': 600, 'ADAUSDT': 0.45,
                    'XRPUSDT': 0.60, 'DOTUSDT': 7.5, 'LINKUSDT': 15, 'MATICUSDT': 0.70, 'AVAXUSDT': 35,
                    'UNIUSDT': 10, 'LTCUSDT': 85, 'BCHUSDT': 450, 'ETCUSDT': 28, 'XLMUSDT': 0.12,
                    'TRXUSDT': 0.12, 'TONUSDT': 7, 'NEARUSDT': 6, 'APTUSDT': 9, 'FILUSDT': 5}
            p = base.get(symbol, 100)
            prices = [p * (1 + random.uniform(-0.03, 0.03)) for _ in range(50)]
            self._offline_prices[symbol] = prices
        else:
            p = self._offline_prices[symbol][-1] * (1 + random.uniform(-0.03, 0.03))
            self._offline_prices[symbol].append(p)
            if len(self._offline_prices[symbol]) > 100: self._offline_prices[symbol].pop(0)
        prices = self._offline_prices[symbol]
        return [{'open': c*0.998, 'high': c*1.005, 'low': c*0.995, 'close': c, 'volume': random.uniform(1000,10000), 'timestamp': datetime.now()} for c in prices]

    async def initialize(self):
        for symbol in self.symbols:
            m = StrategyManager(initial_balance=self.initial_balance/len(self.symbols), max_positions=self.max_positions)
            m.add_default_strategies()
            self.managers[symbol] = m
        print(f"🎯 {len(self.symbols)} coin hazir! Her biri: ${self.initial_balance/len(self.symbols):,.2f}")

    async def scan_all_coins(self):
        self.scan_count += 1
        print(f"\n{'='*70}")
        print(f"🔍 TARAMA #{self.scan_count} - {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*70}")
        for symbol in self.symbols:
            await self._scan_coin(symbol)
        self._print_summary()

    async def _scan_coin(self, symbol):
        try:
            candles = self._generate_offline_data(symbol)
            m = self.managers[symbol]
            price = candles[-1]['close']
            m.engine.update_price(symbol, price)
            signal = m.signal_gen.process_candle(symbol, candles[-1])
            if signal:
                self.signals_found += 1
                print(f"\n   🎯 {symbol}: {signal.signal_type.value} @ ${price:,.2f} | Conf: {signal.confidence:.2f}")
                m.on_signal(signal)
                self.trades_executed += 1
            else:
                m._check_exit(symbol, price)
                pos = m.engine.get_position(symbol)
                if pos:
                    pnl = ((price - pos.entry_price) / pos.entry_price) * 100
                    print(f"   {'🟢' if pnl>=0 else '🔴'} {symbol}: ${price:,.2f} | PnL: {pnl:+.2f}%")
                else:
                    print(f"   ⚪ {symbol}: ${price:,.2f}")
        except Exception as e:
            print(f"   ❌ {symbol}: {str(e)[:40]}")

    def _print_summary(self):
        equity = sum(m.engine.get_account_summary()['equity'] for m in self.managers.values())
        pnl = sum(m.engine.get_account_summary()['total_pnl'] for m in self.managers.values())
        positions = sum(len(m.engine.get_all_positions()) for m in self.managers.values())
        print(f"\n📊 PORTFOY | Equity: ${equity:,.2f} | PnL: ${pnl:,.2f} ({(pnl/self.initial_balance)*100:+.2f}%) | Poz: {positions}")

    async def run_once(self):
        await self.initialize()
        await self.scan_all_coins()
        self._print_final()

    def _print_final(self):
        print(f"\n{'='*70}\n📋 FINAL RAPOR\n{'='*70}")
        for symbol, m in self.managers.items():
            s = m.engine.get_account_summary()
            stats = m.engine.get_stats()
            print(f"{symbol}: Equity=${s['equity']:,.2f} PnL=${s['total_pnl']:,.2f} Trades={stats['total_trades']} WR={stats['win_rate']:.1f}%")
        total_equity = sum(m.engine.get_account_summary()['equity'] for m in self.managers.values())
        total_pnl = sum(m.engine.get_account_summary()['total_pnl'] for m in self.managers.values())
        print(f"\n💰 TOPLAM: Equity=${total_equity:,.2f} | PnL=${total_pnl:,.2f} ({(total_pnl/self.initial_balance)*100:+.2f}%)")

async def main():
    print("="*70 + "\nATLAS AI - 20 Coin Offline Scanner\n" + "="*70)
    scanner = MultiCoinScanner(
        symbols=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","ADAUSDT",
                 "XRPUSDT","DOTUSDT","LINKUSDT","MATICUSDT","AVAXUSDT",
                 "UNIUSDT","LTCUSDT","BCHUSDT","ETCUSDT","XLMUSDT",
                 "TRXUSDT","TONUSDT","NEARUSDT","APTUSDT","FILUSDT"],
        initial_balance=20000.0, max_positions=5, offline_mode=True
    )
    await scanner.run_once()
    print("\n" + "="*70 + "\n✅ Test tamamlandi!\n" + "="*70)

if __name__ == "__main__":
    asyncio.run(main())
