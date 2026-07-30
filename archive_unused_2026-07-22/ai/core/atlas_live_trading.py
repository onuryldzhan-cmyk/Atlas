"""ATLAS LIVE TRADING ENGINE v1.1 - Duzeltilmis Paper Trading"""
from datetime import datetime
from typing import Dict, List, Optional
import json
import os
import time

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from atlas_brain import AtlasBrain
    from atlas_memory_core import AtlasMemoryCore, TradeOutcome
    MODULES_AVAILABLE = True
except ImportError as e:
    print(f"[LIVE] Modul import hatasi: {e}")
    MODULES_AVAILABLE = False


class AtlasLiveTrading:
    def __init__(self, 
                 symbols: List[str] = None,
                 initial_balance: float = 10000.0,
                 timeframe: str = "1h",
                 paper_mode: bool = True):
        
        self.symbols = symbols or ["BTCUSDT", "ETHUSDT"]
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.timeframe = timeframe
        self.paper_mode = paper_mode
        
        self.positions: Dict[str, Dict] = {}
        self.trade_history: List[Dict] = []
        
        self.brain = None
        self.memory = None
        
        self.running = False
        self.cycle_count = 0
        
        self._initialize_modules()
        print(f"[LIVE] Atlas Live Trading v1.1 | Sermaye: ${initial_balance:,.2f}")
    
    def _initialize_modules(self):
        if not MODULES_AVAILABLE:
            return
        
        try:
            self.brain = AtlasBrain()
            self.memory = AtlasMemoryCore()
            print("[LIVE] Moduller yuklendi")
        except Exception as e:
            print(f"[LIVE] Hata: {e}")
    
    def fetch_binance_data(self, symbol: str, limit: int = 50) -> List[Dict]:
        if HAS_REQUESTS:
            try:
                url = "https://api.binance.com/api/v3/klines"
                params = {"symbol": symbol, "interval": self.timeframe, "limit": limit}
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    return [{
                        "timestamp": datetime.fromtimestamp(d[0]/1000).isoformat(),
                        "open": float(d[1]), "high": float(d[2]),
                        "low": float(d[3]), "close": float(d[4]),
                        "volume": float(d[5])
                    } for d in data]
            except Exception as e:
                print(f"[LIVE] API hatasi: {e}")
        
        return self._generate_demo_candles(symbol, limit)
    
    def _generate_demo_candles(self, symbol: str, limit: int = 50) -> List[Dict]:
        import random
        candles = []
        price = 45000 if "BTC" in symbol else 3000 if "ETH" in symbol else 150
        timestamp = datetime.now()
        timestamp = datetime.fromtimestamp(timestamp.timestamp() - limit * 3600)
        
        for i in range(limit):
            change = random.gauss(0.0002, 0.015)
            price *= (1 + change)
            candles.append({
                "timestamp": timestamp.isoformat(),
                "open": round(price * (1 + random.gauss(0, 0.003)), 2),
                "high": round(price * (1 + abs(random.gauss(0, 0.01))), 2),
                "low": round(price * (1 - abs(random.gauss(0, 0.01))), 2),
                "close": round(price, 2),
                "volume": round(random.uniform(1000, 10000), 2)
            })
            timestamp = datetime.fromtimestamp(timestamp.timestamp() + 3600)
        return candles
    
    def _calculate_indicators(self, candles: List[Dict]) -> Dict:
        """Gercek RSI ve trend hesapla"""
        closes = [c["close"] for c in candles]
        
        # RSI
        rsi = 50
        if len(closes) >= 15:
            gains, losses = [], []
            for i in range(len(closes)-14, len(closes)):
                change = closes[i] - closes[i-1]
                gains.append(max(change, 0))
                losses.append(abs(min(change, 0)))
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14
            if avg_loss > 0:
                rsi = 100 - (100 / (1 + avg_gain / avg_loss))
        
        # Trend
        trend = "sideways"
        if len(closes) >= 20:
            if closes[-1] > closes[-20] * 1.05:
                trend = "bullish"
            elif closes[-1] < closes[-20] * 0.95:
                trend = "bearish"
        
        # MACD
        macd = 0
        if len(closes) >= 26:
            ema12 = sum(closes[-12:]) / 12
            ema26 = sum(closes[-26:]) / 26
            macd = ema12 - ema26
        
        # Technical score (0-1)
        if rsi < 30:
            tech_score = 0.8  # Asiri satim = al
        elif rsi > 70:
            tech_score = 0.2  # Asiri alim = sat
        else:
            tech_score = 0.5
        
        if trend == "bullish":
            tech_score = min(tech_score + 0.2, 1.0)
        elif trend == "bearish":
            tech_score = max(tech_score - 0.2, 0.0)
        
        return {
            "rsi": round(rsi, 2),
            "macd": round(macd, 2),
            "trend": trend,
            "technical_score": round(tech_score, 2),
            "macro_score": 0.6,  # Hafif dovish
            "sentiment_score": 0.4,  # Hafif fear
            "risk_score": 0.4,  # Dusuk risk
            "fed_policy": "dovish",
            "inflation": 2.5,
            "fear_greed": 35,
            "social_volume": 75000
        }
    
    def open_position(self, symbol: str, direction: str, price: float, 
                      size_pct: float = 10.0, confidence: float = 0.5):
        if symbol in self.positions:
            return False
        
        position_size = (self.balance * size_pct / 100)
        if position_size < 10 or self.balance < position_size:
            print(f"[LIVE] Yetersiz bakiye: ${self.balance:.2f}")
            return False
        
        self.positions[symbol] = {
            "symbol": symbol,
            "direction": direction,
            "entry_price": price,
            "size": position_size,
            "confidence": confidence,
            "open_time": datetime.now().isoformat(),
            "pnl_pct": 0.0,
            "pnl_usd": 0.0
        }
        
        self.balance -= position_size
        
        print(f"\n{'='*60}")
        print(f"POZISYON ACILDI: {symbol}")
        print(f"Yon: {direction.upper()} | Giris: ${price:,.2f}")
        print(f"Buyukluk: ${position_size:,.2f} | Guven: {confidence:.2f}")
        print(f"Kalan Bakiye: ${self.balance:,.2f}")
        print(f"{'='*60}")
        
        if self.memory:
            self.memory.record_trade(symbol, price, position_size, "AtlasBrain_Live")
        
        return True
    
    def close_position(self, symbol: str, price: float, reason: str = ""):
        if symbol not in self.positions:
            return False
        
        pos = self.positions[symbol]
        
        if pos["direction"] == "long":
            pnl_pct = ((price - pos["entry_price"]) / pos["entry_price"]) * 100
        else:
            pnl_pct = ((pos["entry_price"] - price) / pos["entry_price"]) * 100
        
        pnl_usd = (pnl_pct / 100) * pos["size"]
        self.balance += pos["size"] + pnl_usd
        
        trade_record = {
            "symbol": symbol, "direction": pos["direction"],
            "entry": pos["entry_price"], "exit": price,
            "pnl_pct": pnl_pct, "pnl_usd": pnl_usd,
            "reason": reason, "time": datetime.now().isoformat()
        }
        self.trade_history.append(trade_record)
        
        if self.memory:
            outcome = TradeOutcome.WIN if pnl_pct > 0 else TradeOutcome.LOSS if pnl_pct < 0 else TradeOutcome.NEUTRAL
            self.memory.update_trade_outcome(symbol, price, pnl_pct, outcome)
        
        print(f"\n{'='*60}")
        print(f"POZISYON KAPANDI: {symbol}")
        print(f"Cikis: ${price:,.2f} | PnL: ${pnl_usd:+.2f} (%{pnl_pct:+.2f})")
        print(f"Neden: {reason} | Yeni Bakiye: ${self.balance:,.2f}")
        print(f"{'='*60}")
        
        del self.positions[symbol]
        return True
    
    def update_positions(self, current_prices: Dict[str, float]):
        for symbol, pos in list(self.positions.items()):
            if symbol not in current_prices:
                continue
            
            current_price = current_prices[symbol]
            
            if pos["direction"] == "long":
                pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
            else:
                pnl_pct = ((pos["entry_price"] - current_price) / pos["entry_price"]) * 100
            
            self.positions[symbol]["pnl_pct"] = pnl_pct
            self.positions[symbol]["pnl_usd"] = (pnl_pct / 100) * pos["size"]
            
            # TP/SL
            if pnl_pct >= 8.0:
                self.close_position(symbol, current_price, "take_profit")
            elif pnl_pct <= -4.0:
                self.close_position(symbol, current_price, "stop_loss")
    
    def run_cycle(self):
        self.cycle_count += 1
        print(f"\n{'='*70}")
        print(f"DONGU #{self.cycle_count} | {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*70}")
        
        current_prices = {}
        
        for symbol in self.symbols:
            print(f"\n[ANALIZ] {symbol}...")
            candles = self.fetch_binance_data(symbol, limit=50)
            if not candles:
                continue
            
            current_price = candles[-1]["close"]
            current_prices[symbol] = current_price
            
            # Gercek indikatorler
            market_data = self._calculate_indicators(candles)
            
            print(f"  Fiyat: ${current_price:,.2f} | RSI: {market_data['rsi']} | Trend: {market_data['trend']}")
            
            # Brain karari
            decision = None
            if self.brain:
                try:
                    decision = self.brain.analyze_and_decide(symbol, market_data)
                except Exception as e:
                    print(f"  Brain hatasi: {e}")
            
            if decision:
                action = decision.get("action", "hold")
                confidence = decision.get("confidence", 0.0)
                position_size = decision.get("position_size_pct", 5.0)
                
                print(f"  Brain Karar: {action.upper()} (guven: {confidence:.2f})")
                
                # DUSUK GUVEN ESIGI - daha agresif
                if action == "buy" and symbol not in self.positions and confidence >= 0.15:
                    self.open_position(symbol, "long", current_price, position_size, confidence)
                elif action == "sell" and symbol not in self.positions and confidence >= 0.15:
                    self.open_position(symbol, "short", current_price, position_size, confidence)
                elif action in ["reduce", "avoid", "sell"] and symbol in self.positions:
                    self.close_position(symbol, current_price, "signal")
                else:
                    print(f"  -> BEKLE (guven dusuk veya pozisyon var)")
            else:
                print(f"  -> Brain pasif, BEKLE")
        
        self.update_positions(current_prices)
        self.print_status()
    
    def print_status(self):
        print(f"\n{'='*70}")
        print("PORTFOY DURUMU")
        print(f"{'='*70}")
        print(f"Bakiye: ${self.balance:,.2f}")
        print(f"Toplam Trade: {len(self.trade_history)}")
        
        if self.positions:
            print(f"\nAcik Pozisyonlar:")
            for symbol, pos in self.positions.items():
                print(f"  {symbol}: {pos['direction'].upper()} @ ${pos['entry_price']:,.2f} | PnL: %{pos['pnl_pct']:+.2f}")
        else:
            print("\nAcik Pozisyon: Yok")
        
        if self.trade_history:
            print(f"\nSon Trades:")
            for t in self.trade_history[-3:]:
                print(f"  {t['symbol']}: {t['pnl_usd']:+.2f} (%{t['pnl_pct']:+.2f}) [{t['reason']}]")
        
        print(f"{'='*70}")
    
    def run(self, cycles: int = 5, interval_seconds: int = 3):
        self.running = True
        print(f"\n[LIVE] Trading basliyor... {cycles} dongu")
        
        for i in range(cycles):
            if not self.running:
                break
            
            self.run_cycle()
            
            if i < cycles - 1:
                print(f"\n[BEKLE] {interval_seconds} saniye...")
                time.sleep(interval_seconds)
        
        self.stop()
    
    def stop(self):
        self.running = False
        print(f"\n{'='*70}")
        print("TRADING TAMAMLANDI")
        print(f"{'='*70}")
        
        for symbol in list(self.positions.keys()):
            candles = self.fetch_binance_data(symbol, limit=1)
            if candles:
                self.close_position(symbol, candles[-1]["close"], "session_end")
        
        total_pnl = sum(t["pnl_usd"] for t in self.trade_history)
        total_return = (total_pnl / self.initial_balance) * 100
        
        print(f"\nFINAL RAPOR:")
        print(f"Baslangic: ${self.initial_balance:,.2f}")
        print(f"Bitis: ${self.balance:,.2f}")
        print(f"Toplam PnL: ${total_pnl:+.2f} (%{total_return:+.2f})")
        print(f"Toplam Trade: {len(self.trade_history)}")
        
        if self.trade_history:
            wins = len([t for t in self.trade_history if t["pnl_usd"] > 0])
            print(f"Win Rate: %{(wins/len(self.trade_history)*100):.1f}")
        
        print(f"{'='*70}")
        
        # Kaydet
        data = {
            "timestamp": datetime.now().isoformat(),
            "initial_balance": self.initial_balance,
            "final_balance": self.balance,
            "trades": self.trade_history
        }
        with open("live_trading_results.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("[LIVE] Sonuclar kaydedildi: live_trading_results.json")


# ==================== TEST ====================
if __name__ == "__main__":
    print("=" * 70)
    print("ATLAS LIVE TRADING ENGINE v1.1 - TEST")
    print("=" * 70)
    
    trader = AtlasLiveTrading(
        symbols=["BTCUSDT", "ETHUSDT"],
        initial_balance=10000.0,
        timeframe="1h",
        paper_mode=True
    )
    
    print("\n[TEST] 5 donguluk paper trading...")
    trader.run(cycles=5, interval_seconds=3)
    
    print("\n" + "=" * 70)
    print("LIVE TRADING v1.1 TEST TAMAMLANDI!")
    print("=" * 70)