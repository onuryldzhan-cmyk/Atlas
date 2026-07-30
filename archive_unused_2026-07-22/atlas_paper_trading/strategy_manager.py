"""Atlas AI - Strategy Manager"""
from datetime import datetime
from typing import Dict, List

from signal_generator import SignalGenerator, RSIStrategy, MACDStrategy, EMAStrategy, BollingerStrategy
from strategy_base import Signal, SignalType, StrategyConfig
from paper_trading_engine import PaperTradingEngine, OrderSide
from position_tracker import PositionTracker
from performance_report import PerformanceReport
from risk_guardian import RiskGuardian, KillSwitchReason

class StrategyManager:
    def __init__(self, initial_balance=10000.0, risk_per_trade=0.02, max_positions=5):
        self.initial_balance = initial_balance
        self.risk_per_trade = risk_per_trade
        self.max_positions = max_positions
        self.engine = PaperTradingEngine(initial_balance=initial_balance)
        self.tracker = PositionTracker(self.engine)
        self.report = PerformanceReport(self.engine)
        self.guardian = RiskGuardian(self.engine, self.tracker)
        self.signal_gen = SignalGenerator()
        self.position_size_pct = 0.10
        self.stop_loss_pct = 0.03
        self.take_profit_pct = 0.06
        self.trade_callbacks = []
        print(f"🧠 Atlas AI Strategy Manager baslatildi")
        print(f"   Bakiye: ${initial_balance:,.2f}")
        print(f"   Risk/Trade: {risk_per_trade*100}%")
        print(f"   Max Pozisyon: {max_positions}")

    def add_default_strategies(self):
        self.signal_gen.add_strategy(RSIStrategy(StrategyConfig(name="RSI", timeframe="5m", min_confidence=0.65)))
        self.signal_gen.add_strategy(MACDStrategy(StrategyConfig(name="MACD", timeframe="5m", min_confidence=0.7)))
        self.signal_gen.add_strategy(EMAStrategy(StrategyConfig(name="EMA_Cross", timeframe="5m", min_confidence=0.7)))
        self.signal_gen.add_strategy(BollingerStrategy(StrategyConfig(name="Bollinger", timeframe="5m", min_confidence=0.65)))
        print("\n✅ 4 strateji yuklendi: RSI, MACD, EMA_Cross, Bollinger")

    def on_signal(self, signal: Signal):
        symbol = signal.symbol
        if not self.guardian.is_trading_allowed():
            print(f"⛔ Sinyal engellendi: Kill Switch aktif")
            return
        if not self.guardian.is_symbol_allowed(symbol):
            print(f"⛔ Sinyal engellendi: Circuit Breaker aktif ({symbol})")
            return
        current_pos = self.engine.get_position(symbol)
        if signal.signal_type == SignalType.BUY:
            if current_pos and current_pos.side.value == "LONG":
                print(f"⏭️ BUY atlandi: Zaten LONG ({symbol})")
                return
            if len(self.engine.get_all_positions()) >= self.max_positions:
                print(f"⏭️ BUY atlandi: Max pozisyon")
                return
            equity = self.engine.get_account_summary()['equity']
            qty = (equity * self.position_size_pct) / signal.price
            order = self.engine.place_market_order(symbol, OrderSide.BUY, qty)
            if order.status.value == "FILLED":
                pos = self.engine.get_position(symbol)
                if pos:
                    pos.stop_loss = signal.price * (1 - self.stop_loss_pct)
                    pos.take_profit = signal.price * (1 + self.take_profit_pct)
                    print(f"   🛡️ SL: ${pos.stop_loss:,.2f} | TP: ${pos.take_profit:,.2f}")
                print(f"✅ BUY: {symbol} {qty:.6f} @ ${signal.price:,.2f}")
                for cb in self.trade_callbacks:
                    cb({'type': 'BUY', 'symbol': symbol, 'quantity': qty, 'price': signal.price})
        elif signal.signal_type == SignalType.SELL:
            if current_pos and current_pos.side.value == "LONG":
                order = self.engine.place_market_order(symbol, OrderSide.SELL, current_pos.quantity)
                if order.status.value == "FILLED":
                    pnl = current_pos.realized_pnl
                    self.guardian.record_trade_result(pnl > 0, pnl)
                    self.tracker.record_trade_pnl({'symbol': symbol, 'realized_pnl': pnl, 'commission': order.commission})
                    print(f"✅ SELL: {symbol} kapandi | PnL: ${pnl:,.2f}")
                    for cb in self.trade_callbacks:
                        cb({'type': 'SELL', 'symbol': symbol, 'pnl': pnl})
            else:
                print(f"⏭️ SELL atlandi: Acik LONG yok ({symbol})")

    def run_simulation(self, prices: Dict[str, List[float]], volumes: Dict[str, List[float]] = None):
        print("\n" + "=" * 70)
        print("🚀 SIMULASYON BASLATILIYOR")
        print("=" * 70)
        for symbol, price_list in prices.items():
            vol_list = volumes.get(symbol, [1000] * len(price_list)) if volumes else [1000] * len(price_list)
            print(f"\n📊 {symbol} - {len(price_list)} mum isleniyor...")
            for i, (price, vol) in enumerate(zip(price_list, vol_list)):
                self.engine.update_price(symbol, price)
                candle = {
                    'open': price * 0.998,
                    'high': price * 1.002,
                    'low': price * 0.997,
                    'close': price,
                    'volume': vol,
                    'timestamp': datetime.now()
                }
                signal = self.signal_gen.process_candle(symbol, candle)
                if signal:
                    self.on_signal(signal)
                self.guardian.check_all_risks()
                self._check_exit(symbol, price)
        print("\n📋 Kalan pozisyonlar kapatiliyor...")
        for symbol in list(self.engine.positions.keys()):
            pos = self.engine.get_position(symbol)
            if pos:
                self.engine.place_market_order(symbol, OrderSide.SELL, pos.quantity)
        self._print_final()

    def _check_exit(self, symbol: str, price: float):
        pos = self.engine.get_position(symbol)
        if not pos:
            return
        if pos.stop_loss and pos.side.value == "LONG" and price <= pos.stop_loss:
            print(f"\n🛑 STOP LOSS: {symbol} @ ${price:,.2f}")
            self.engine.place_market_order(symbol, OrderSide.SELL, pos.quantity)
            self.guardian.record_trade_result(False, pos.realized_pnl)
        elif pos.take_profit and pos.side.value == "LONG" and price >= pos.take_profit:
            print(f"\n🎯 TAKE PROFIT: {symbol} @ ${price:,.2f}")
            self.engine.place_market_order(symbol, OrderSide.SELL, pos.quantity)
            self.guardian.record_trade_result(True, pos.realized_pnl)

    def _print_final(self):
        print("\n" + "=" * 70)
        print("📊 SIMULASYON SONUC RAPORU")
        print("=" * 70)
        s = self.engine.get_account_summary()
        print(f"\n💰 HESAP")
        print(f"   Baslangic: ${self.initial_balance:,.2f}")
        print(f"   Bitis: ${s['equity']:,.2f}")
        print(f"   Getiri: {s['return_pct']:+.2f}%")
        print(f"   PnL: ${s['total_pnl']:,.2f}")
        print(f"   Komisyon: ${s['total_commission']:,.4f}")
        stats = self.engine.get_stats()
        print(f"\n📈 ISLEMLER")
        print(f"   Toplam: {stats['total_trades']}")
        print(f"   Kazanan: {stats['winning_trades']}")
        print(f"   Kaybeden: {stats['losing_trades']}")
        print(f"   Win Rate: {stats['win_rate']:.1f}%")
        print(f"   Profit Factor: {stats['profit_factor']:.2f}")
        print(f"   Max DD: {stats['max_drawdown']*100:.2f}%")
        print("\n🧠 STRATEJILER")
        for name, stat in self.signal_gen.get_strategy_stats().items():
            print(f"   {name}: {stat['signals_generated']} sinyal")
        print("\n" + "=" * 70)


if __name__ == "__main__":
    import random
    random.seed(42)
    print("=" * 70)
    print("ATLAS AI - Strategy Manager Test")
    print("=" * 70)
    
    manager = StrategyManager(initial_balance=10000.0, risk_per_trade=0.02, max_positions=3)
    manager.add_default_strategies()
    
    # ============================================================
    # EL ILE YAZILMIS TEST VERISI - Kesin BUY ve SELL sinyali
    # ============================================================
    
    prices = []
    
    # Phase 1: Sabit yuksek (RSI hesaplanmasi icin) - 20 mum
    for i in range(20):
        prices.append(70000)
    
    # Phase 2: KESIN DUSUS - Her mum oncekinden dusuk (RSI < 30 yapmak icin)
    p = 70000
    for i in range(25):
        p = p * 0.98  # %2 dusus
        prices.append(p)
    
    # Phase 3: DIP - Fiyat yatay kalsin (RSI 20'lerde kalsin) - 5 mum
    for i in range(5):
        prices.append(p)
    
    # Phase 4: KESIN YUKSELIS - Her mum oncekinden yuksek (RSI 30'u yukari kirsin)
    for i in range(25):
        p = p * 1.03  # %3 yukselis
        prices.append(p)
    
    # Phase 5: KESIN DUSUS - SELL sinyali icin
    for i in range(15):
        p = p * 0.97  # %3 dusus
        prices.append(p)
    
    volumes = [random.uniform(1000, 5000) for _ in prices]
    
    print(f"\n📊 Test verisi: {len(prices)} mum")
    print(f"   Baslangic: ${prices[0]:,.2f}")
    print(f"   Dip: ${min(prices):,.2f}")
    print(f"   Zirve: ${max(prices):,.2f}")
    print(f"   Bitis: ${prices[-1]:,.2f}")
    
    manager.run_simulation(prices={'BTCUSDT': prices}, volumes={'BTCUSDT': volumes})
    print("\n" + "=" * 70)
    print("✅ Test tamamlandi!")
    print("=" * 70)
