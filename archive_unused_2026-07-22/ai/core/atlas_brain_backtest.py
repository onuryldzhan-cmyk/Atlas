"""ATLAS BRAIN BACKTEST v1.0 - Atlas Brain Kararlarini Tarihsel Test Et"""
from datetime import datetime
from typing import Dict, List, Optional
import json
import os
import sys

# Mevcut modulleri import et
try:
    from atlas_backtest_engine import AtlasBacktestEngine, BacktestTrade, TradeDirection, BacktestResult
    from atlas_brain import AtlasBrain
    MODULES_AVAILABLE = True
except ImportError as e:
    print(f"[BRAIN_BACKTEST] UYARI: Modul import hatasi: {e}")
    MODULES_AVAILABLE = False


class AtlasBrainBacktest:
    """Atlas Brain kararlarini backtest ile test eder"""
    
    def __init__(self, initial_capital: float = 10000.0):
        self.initial_capital = initial_capital
        self.backtest = AtlasBacktestEngine(initial_capital=initial_capital)
        self.brain = None
        if MODULES_AVAILABLE:
            try:
                self.brain = AtlasBrain()
                print("[BRAIN_BACKTEST] Atlas Brain yuklendi")
            except Exception as e:
                print(f"[BRAIN_BACKTEST] Brain yuklenemedi: {e}")
                self.brain = None
        print(f"[BRAIN_BACKTEST] Sermaye: ${initial_capital:,.2f}")
    
    def prepare_market_data(self, candle: Dict, idx: int, data: List[Dict]) -> Dict:
        """Brain icin piyasa verisi hazirla"""
        closes = [d["close"] for d in data[:idx+1]]
        
        # RSI (basit)
        rsi = 50
        if len(closes) >= 15:
            gains = []
            losses = []
            for i in range(len(closes)-14, len(closes)):
                change = closes[i] - closes[i-1]
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))
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
        
        # MACD (basit)
        macd = 0
        if len(closes) >= 26:
            ema12 = sum(closes[-12:]) / 12
            ema26 = sum(closes[-26:]) / 26
            macd = ema12 - ema26
        
        return {
            "rsi": round(rsi, 2),
            "macd": round(macd, 2),
            "trend": trend,
            "technical_score": min(max((100 - rsi) / 100, 0), 1) if rsi < 50 else min(max(rsi / 100, 0), 1),
            "macro_score": 0.5,
            "sentiment_score": 0.5,
            "risk_score": 0.5,
            "fed_policy": "neutral",
            "inflation": 3.0,
            "fear_greed": 50,
            "social_volume": 50000
        }
    
    def run_brain_backtest(self, symbol: str, data: List[Dict],
                           tp_pct: float = 8.0,
                           sl_pct: float = 4.0,
                           max_position_pct: float = 10.0) -> BacktestResult:
        """Atlas Brain kararlarini backtest et"""
        brain_status = "AKTIF" if self.brain else "PASIF (simulasyon)"
        print(f"\n{"="*70}")
        print(f"ATLAS BRAIN BACKTEST: {symbol}")
        print(f"{"="*70}")
        print(f"Brain modulu: {brain_status}")
        
        self.backtest.capital = self.initial_capital
        self.backtest.trades = []
        self.backtest.equity_curve = [self.initial_capital]
        
        open_trade = None
        cooldown = 0
        
        for i in range(len(data)):
            candle = data[i]
            current_price = candle["close"]
            
            if cooldown > 0:
                cooldown -= 1
            
            # Brain karari al
            brain_signal = "hold"
            confidence = 0.0
            
            if self.brain and i >= 30:
                try:
                    market_data = self.prepare_market_data(candle, i, data)
                    decision = self.brain.analyze_and_decide(symbol, market_data)
                    brain_signal = decision.get("action", "hold")
                    confidence = decision.get("confidence", 0.0)
                except Exception as e:
                    print(f"[BRAIN_BACKTEST] Brain hatasi (idx {i}): {e}")
                    brain_signal = "hold"
            
            # Acik trade kontrolu
            if open_trade:
                if open_trade.direction == TradeDirection.LONG:
                    pnl_pct = ((current_price - open_trade.entry_price) / open_trade.entry_price) * 100
                else:
                    pnl_pct = ((open_trade.entry_price - current_price) / open_trade.entry_price) * 100
                
                hit_tp = pnl_pct >= tp_pct
                hit_sl = pnl_pct <= -sl_pct
                
                signal_close = False
                if open_trade.direction == TradeDirection.LONG and brain_signal in ["sell", "reduce", "avoid"]:
                    signal_close = True
                elif open_trade.direction == TradeDirection.SHORT and brain_signal in ["buy"]:
                    signal_close = True
                
                end_of_test = i == len(data) - 1
                
                if hit_tp or hit_sl or signal_close or end_of_test:
                    reason = "tp" if hit_tp else "sl" if hit_sl else "signal" if signal_close else "end"
                    
                    if open_trade.direction == TradeDirection.LONG:
                        exit_price = current_price * (1 - self.backtest.slippage_pct / 100)
                    else:
                        exit_price = current_price * (1 + self.backtest.slippage_pct / 100)
                    
                    open_trade.close(exit_price, candle["timestamp"], reason)
                    
                    commission = open_trade.position_size * (self.backtest.commission_pct / 100) * 2
                    self.backtest.capital += open_trade.pnl_usd - commission
                    self.backtest.capital = max(self.backtest.capital, 0)
                    
                    self.backtest.trades.append(open_trade)
                    open_trade = None
                    cooldown = 5
            
            # Yeni trade ac
            elif brain_signal in ["buy", "reduce"] and not open_trade and cooldown == 0 and i >= 30:
                if confidence < 0.3:
                    continue
                
                position_size = (self.backtest.capital * max_position_pct / 100)
                if position_size < 10:
                    continue
                
                direction = TradeDirection.LONG if brain_signal == "buy" else TradeDirection.SHORT
                
                if direction == TradeDirection.LONG:
                    entry = current_price * (1 + self.backtest.slippage_pct / 100)
                else:
                    entry = current_price * (1 - self.backtest.slippage_pct / 100)
                
                open_trade = BacktestTrade(
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry,
                    entry_time=candle["timestamp"],
                    position_size=position_size
                )
                cooldown = 1
            
            self.backtest.equity_curve.append(self.backtest.capital)
        
        # Sonuclari hesapla
        result = self.backtest._calculate_metrics(symbol, "AtlasBrain", data)
        return result
    
    def compare_strategies(self, symbol: str, data: List[Dict]):
        """Brain vs geleneksel stratejiler karsilastirmasi"""
        print(f"\n{"="*70}")
        print(f"STRATEJI KARSILASTIRMASI: {symbol}")
        print(f"{"="*70}")
        
        results = []
        
        # 1. Atlas Brain
        print("\n[1/4] Atlas Brain...")
        brain_bt = AtlasBrainBacktest(initial_capital=10000)
        result_brain = brain_bt.run_brain_backtest(symbol, data)
        result_brain.print_summary()
        results.append(result_brain)
        
        # 2. RSI
        print("\n[2/4] RSI Stratejisi...")
        rsi_bt = AtlasBacktestEngine(initial_capital=10000)
        result_rsi = rsi_bt.run_backtest(symbol, data, "rsi", tp_pct=8, sl_pct=4)
        results.append(result_rsi)
        
        # 3. MACD
        print("\n[3/4] MACD Stratejisi...")
        macd_bt = AtlasBacktestEngine(initial_capital=10000)
        result_macd = macd_bt.run_backtest(symbol, data, "macd", tp_pct=8, sl_pct=4)
        results.append(result_macd)
        
        # 4. EMA Cross
        print("\n[4/4] EMA Cross...")
        ema_bt = AtlasBacktestEngine(initial_capital=10000)
        result_ema = ema_bt.run_backtest(symbol, data, "ema_cross", tp_pct=8, sl_pct=4)
        results.append(result_ema)
        
        # Ozet tablo
        print(f"\n{"="*70}")
        print("KARSILASTIRMA TABLOSU")
        print(f"{"="*70}")
        print(f"{"Strateji":<15} {"Getiri %":<12} {"Win Rate":<12} {"Max DD":<12} {"Trades":<10}")
        print("-" * 70)
        for r in results:
            print(f"{r.strategy_name:<15} {r.total_return_pct:>+8.2f}    {r.win_rate:>6.1f}%    {r.max_drawdown_pct:>6.2f}%    {r.total_trades:>6}")
        print(f"{"="*70}")
        
        # En iyi strateji
        best = max(results, key=lambda x: x.total_return_pct)
        print(f"\nEN IYI STRATEJI: {best.strategy_name} (%{best.total_return_pct:.2f})")
        
        return results


# ==================== TEST ====================
if __name__ == "__main__":
    print("=" * 70)
    print("ATLAS BRAIN BACKTEST v1.0 - TEST")
    print("=" * 70)
    
    # Demo veri uret
    from atlas_backtest_engine import AtlasBacktestEngine
    bt = AtlasBacktestEngine(initial_capital=10000)
    data = bt.generate_demo_data("BTCUSDT", days=180, start_price=40000,
                                  trend=0.0003, volatility=0.012)
    
    # Karsilastirma yap
    comparator = AtlasBrainBacktest(initial_capital=10000)
    results = comparator.compare_strategies("BTCUSDT", data)
    
    print("\n" + "=" * 70)
    print("BRAIN BACKTEST TAMAMLANDI!")
    print("=" * 70)