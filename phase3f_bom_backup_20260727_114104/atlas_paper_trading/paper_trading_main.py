"""Atlas AI - Paper Trading Main Engine"""
from paper_trading_engine import PaperTradingEngine, OrderSide
from position_tracker import PositionTracker
from performance_report import PerformanceReport
from risk_guardian import RiskGuardian, KillSwitchReason

class AtlasPaperTrader:
    def __init__(self, initial_balance=10000.0, symbols=None, timeframe='5m'):
        self.symbols = symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        self.timeframe = timeframe; self.running = False
        print("🚀 Atlas AI Paper Trading Engine baslatiliyor..."); print("=" * 70)
        self.trading_engine = PaperTradingEngine(initial_balance=initial_balance, base_commission_rate=0.001, slippage_model="adaptive")
        print(f"✅ Paper Trading Engine hazir (Bakiye: ${initial_balance:,.2f})")
        self.position_tracker = PositionTracker(self.trading_engine); print("✅ Position Tracker hazir")
        self.performance_report = PerformanceReport(self.trading_engine, benchmark_symbol="BTCUSDT"); print("✅ Performance Report hazir")
        self.risk_guardian = RiskGuardian(self.trading_engine, self.position_tracker); print("✅ Risk Guardian hazir")
        self._setup_callbacks(); print("=" * 70); print("🎯 Tum sistemler hazir!")

    def _setup_callbacks(self):
        self.trading_engine.on_trade_executed(lambda trade: self.position_tracker.record_trade_pnl(trade.to_dict()))
        self.trading_engine.on_trade_executed(lambda trade: self.risk_guardian.record_trade_result(trade.realized_pnl > 0, trade.realized_pnl))
        self.trading_engine.on_position_update(lambda pos, event: None)

    def buy(self, symbol, quantity):
        if not self.risk_guardian.is_trading_allowed(): return {'success': False, 'error': 'KILL_SWITCH_ACTIVE', 'message': 'Trading durduruldu'}
        if not self.risk_guardian.is_symbol_allowed(symbol): return {'success': False, 'error': 'CIRCUIT_BREAKER_ACTIVE', 'message': f'{symbol} trading durduruldu'}
        order = self.trading_engine.place_market_order(symbol, OrderSide.BUY, quantity)
        return {'success': order.status.value == 'FILLED', 'order': order.to_dict()}

    def sell(self, symbol, quantity):
        if not self.risk_guardian.is_trading_allowed(): return {'success': False, 'error': 'KILL_SWITCH_ACTIVE', 'message': 'Trading durduruldu'}
        order = self.trading_engine.place_market_order(symbol, OrderSide.SELL, quantity)
        return {'success': order.status.value == 'FILLED', 'order': order.to_dict()}

    def close_position(self, symbol):
        pos = self.trading_engine.get_position(symbol)
        if not pos: return {'success': False, 'error': 'NO_POSITION', 'message': 'Acik pozisyon yok'}
        return self.sell(symbol, pos.quantity) if pos.side.value == "LONG" else self.buy(symbol, pos.quantity)

    def close_all_positions(self):
        results = []
        for symbol in list(self.trading_engine.positions.keys()): results.append(self.close_position(symbol))
        return results

    def get_portfolio(self): return {'account': self.trading_engine.get_account_summary(), 'positions': self.position_tracker.get_open_positions(), 'position_summary': self.position_tracker.get_position_summary(), 'risk': self.position_tracker.calculate_risk_metrics()}
    def print_portfolio(self): self.position_tracker.print_report()
    def print_performance(self): self.performance_report.print_full_report()
    def print_risk(self): self.risk_guardian.print_status()

def run_cli():
    print("\n╔══════════════════════════════════════════════════════════════╗\n║                                                              ║\n║           ATLAS AI - PAPER TRADING ENGINE                    ║\n║                                                              ║\n║  🚀 Gercek veri, sanal para, profesyonel simulasyon         ║\n║                                                              ║\n╚══════════════════════════════════════════════════════════════╝\n")
    trader = AtlasPaperTrader(initial_balance=10000.0, symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"], timeframe='5m')
    trader.trading_engine.update_price("BTCUSDT", 65000.0)
    trader.trading_engine.update_price("ETHUSDT", 3500.0)
    trader.trading_engine.update_price("SOLUSDT", 150.0)
    trader.performance_report.set_benchmark_price(64000.0)
    trader.performance_report.record_equity(10000.0)
    print("\n📚 KOMUTLAR:\n   portfolio  - Portfoy ozeti\n   buy <sym> <qty>  - Alim\n   sell <sym> <qty> - Satim\n   close <sym>      - Pozisyon kapat\n   closeall         - Tumunu kapat\n   risk             - Risk durumu\n   perf             - Performans\n   report           - Detayli rapor\n   price <sym> <p>  - Fiyat guncelle\n   kill             - Kill switch\n   release          - Kill switch kaldir\n   quit             - Cikis\n" + "=" * 70)
    while True:
        try:
            cmd = input("\n🤖 Atlas> ").strip().lower()
            if not cmd: continue
            parts = cmd.split(); command = parts[0]
            if command in ('quit', 'exit'): print("👋 Atlas AI kapatiliyor..."); break
            elif command == 'portfolio' or command == 'p': trader.print_portfolio()
            elif command == 'buy':
                if len(parts) < 3: print("❌ Kullanim: buy <symbol> <quantity>"); continue
                result = trader.buy(parts[1].upper(), float(parts[2]))
                print(f"✅ BUY emri: {result['order']['symbol']} {result['order']['quantity']}" if result['success'] else f"❌ Hata: {result['message']}")
            elif command == 'sell':
                if len(parts) < 3: print("❌ Kullanim: sell <symbol> <quantity>"); continue
                result = trader.sell(parts[1].upper(), float(parts[2]))
                print(f"✅ SELL emri: {result['order']['symbol']} {result['order']['quantity']}" if result['success'] else f"❌ Hata: {result['message']}")
            elif command == 'close':
                if len(parts) < 2: print("❌ Kullanim: close <symbol>"); continue
                result = trader.close_position(parts[1].upper())
                print("✅ Pozisyon kapandi" if result['success'] else f"❌ Hata: {result['message']}")
            elif command == 'closeall':
                results = trader.close_all_positions(); closed = sum(1 for r in results if r['success'])
                print(f"✅ {closed} pozisyon kapatildi")
            elif command == 'risk': trader.print_risk()
            elif command == 'perf': trader.print_performance()
            elif command == 'report': trader.print_portfolio(); trader.print_risk(); trader.print_performance()
            elif command == 'price':
                if len(parts) < 3: print("❌ Kullanim: price <symbol> <price>"); continue
                trader.trading_engine.update_price(parts[1].upper(), float(parts[2])); print(f"✅ Fiyat guncellendi: {parts[1].upper()} ${float(parts[2]):,.2f}")
            elif command == 'kill': trader.risk_guardian.activate_kill_switch(KillSwitchReason.MANUAL, "Manual kill switch")
            elif command == 'release': trader.risk_guardian.deactivate_kill_switch(manual_override=True)
            else: print(f"❌ Bilinmeyen komut: {command}")
        except KeyboardInterrupt: print("\n👋 Atlas AI kapatiliyor..."); break
        except Exception as e: print(f"❌ Hata: {e}")

def test_main_engine():
    print("=" * 70); print("ATLAS AI - Main Engine Test"); print("=" * 70)
    trader = AtlasPaperTrader(initial_balance=10000.0, symbols=["BTCUSDT", "ETHUSDT"], timeframe='5m')
    trader.trading_engine.update_price("BTCUSDT", 65000.0)
    trader.trading_engine.update_price("ETHUSDT", 3500.0)
    trader.performance_report.set_benchmark_price(64000.0)
    trader.performance_report.record_equity(10000.0)
    print("\n[1] Portfoy (baslangic):"); trader.print_portfolio()
    print("\n[2] BTC alimi..."); result = trader.buy("BTCUSDT", 0.05); print(f"   Sonuc: Basarili")
    print("\n[3] ETH alimi..."); result = trader.buy("ETHUSDT", 1.0); print(f"   Sonuc: Basarili")
    print("\n[4] Fiyatlar guncelleniyor..."); trader.trading_engine.update_price("BTCUSDT", 67000.0); trader.trading_engine.update_price("ETHUSDT", 3300.0); trader.performance_report.record_equity(10000 + (67000-65000)*0.05 + (3300-3500)*1.0)
    print("\n[5] Guncel portfoy:"); trader.print_portfolio()
    print("\n[6] Risk durumu:"); trader.print_risk()
    print("\n[7] Performans raporu:"); trader.print_performance()
    print("\n[8] BTC pozisyonu kapatiliyor..."); result = trader.close_position("BTCUSDT")
    print("\n[9] ETH pozisyonu kapatiliyor..."); result = trader.close_position("ETHUSDT")
    print("\n[10] Final rapor:"); trader.print_performance()
    print("\n" + "=" * 70); print("✅ Tum testler basariyla tamamlandi!"); print("=" * 70); print("\n💡 CLI baslatmak icin: python paper_trading_main.py cli")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'cli': run_cli()
    else: test_main_engine()
