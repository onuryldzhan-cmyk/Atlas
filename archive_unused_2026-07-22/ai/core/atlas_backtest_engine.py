"""ATLAS BACKTEST ENGINE v1.1 - Duzeltilmis Strateji Test Motoru"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum
import json
import os
import random


class TradeDirection(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class BacktestTrade:
    symbol: str
    direction: TradeDirection
    entry_price: float
    exit_price: Optional[float] = None
    entry_time: str = ""
    exit_time: Optional[str] = None
    position_size: float = 1.0
    pnl_pct: float = 0.0
    pnl_usd: float = 0.0
    exit_reason: str = ""
    
    def close(self, exit_price: float, exit_time: str, reason: str = ""):
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.exit_reason = reason
        
        if self.direction == TradeDirection.LONG:
            self.pnl_pct = ((exit_price - self.entry_price) / self.entry_price) * 100
        else:
            self.pnl_pct = ((self.entry_price - exit_price) / self.entry_price) * 100
        
        self.pnl_usd = (self.pnl_pct / 100) * self.position_size


@dataclass
class BacktestResult:
    symbol: str
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_trade_return: float = 0.0
    avg_winning_trade: float = 0.0
    avg_losing_trade: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    
    def print_summary(self):
        print("\n" + "=" * 60)
        print(f"BACKTEST SONUCLARI: {self.symbol} | {self.strategy_name}")
        print("=" * 60)
        print(f"Periyot: {self.start_date} -> {self.end_date}")
        print(f"Baslangic Sermayesi: ${self.initial_capital:,.2f}")
        print(f"Bitis Sermayesi: ${self.final_capital:,.2f}")
        print(f"Toplam Getiri: %{self.total_return_pct:.2f}")
        print(f"\nTRADE ISTATISTIKLERI:")
        print(f"  Toplam Trade: {self.total_trades}")
        print(f"  Kazanan: {self.winning_trades}")
        print(f"  Kaybeden: {self.losing_trades}")
        print(f"  Win Rate: %{self.win_rate:.1f}")
        print(f"  Ort. Trade Getiri: %{self.avg_trade_return:.2f}")
        print(f"  Ort. Kazanan: %{self.avg_winning_trade:.2f}")
        print(f"  Ort. Kaybeden: %{self.avg_losing_trade:.2f}")
        print(f"  En Iyi Trade: %{self.best_trade:.2f}")
        print(f"  En Kotu Trade: %{self.worst_trade:.2f}")
        print(f"\nRISK METRIKLERI:")
        print(f"  Max Drawdown: %{self.max_drawdown_pct:.2f}")
        print(f"  Sharpe Ratio: {self.sharpe_ratio:.2f}")
        print(f"  Profit Factor: {self.profit_factor:.2f}")
        print("=" * 60)


class AtlasBacktestEngine:
    """Atlas AI Backtest Motoru v1.1"""
    
    def __init__(self, initial_capital: float = 10000.0, 
                 commission_pct: float = 0.1,
                 slippage_pct: float = 0.05):
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.capital = initial_capital
        self.trades: List[BacktestTrade] = []
        self.equity_curve: List[float] = []
        self.data_dir = "backtest_data"
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        print(f"[BACKTEST] Atlas Backtest Engine v1.1 | Sermaye: ${initial_capital:,.2f}")
    
    def _calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """RSI hesapla"""
        if len(closes) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        for i in range(len(closes) - period, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def _calculate_ema(self, values: List[float], period: int) -> float:
        """EMA hesapla"""
        if len(values) < period:
            return sum(values) / len(values)
        
        multiplier = 2 / (period + 1)
        ema = sum(values[:period]) / period
        for val in values[period:]:
            ema = (val - ema) * multiplier + ema
        return ema
    
    def strategy_rsi(self, data: List[Dict], current_idx: int) -> Optional[str]:
        """RSI stratejisi - daha az sinyal"""
        if current_idx < 20:
            return None
        
        closes = [d["close"] for d in data[:current_idx+1]]
        rsi = self._calculate_rsi(closes, 14)
        
        # Onceki RSI
        prev_rsi = self._calculate_rsi(closes[:-1], 14) if len(closes) > 15 else rsi
        
        # Sadece kesin sinyaller - onceki durumdan farkli olmali
        if prev_rsi >= 35 and rsi < 30:
            return "buy"
        elif prev_rsi <= 65 and rsi > 70:
            return "sell"
        return None
    
    def strategy_macd(self, data: List[Dict], current_idx: int) -> Optional[str]:
        """MACD stratejisi"""
        if current_idx < 35:
            return None
        
        closes = [d["close"] for d in data[:current_idx+1]]
        
        ema12 = self._calculate_ema(closes, 12)
        ema26 = self._calculate_ema(closes, 26)
        macd = ema12 - ema26
        
        # Signal line (EMA9 of MACD history)
        macd_history = []
        for i in range(26, len(closes)):
            e12 = self._calculate_ema(closes[:i+1], 12)
            e26 = self._calculate_ema(closes[:i+1], 26)
            macd_history.append(e12 - e26)
        
        if len(macd_history) < 10:
            return None
        
        signal = self._calculate_ema(macd_history, 9)
        prev_macd = macd_history[-2] if len(macd_history) > 1 else macd
        prev_signal = self._calculate_ema(macd_history[:-1], 9) if len(macd_history) > 9 else signal
        
        # Yukari kesisim
        if prev_macd <= prev_signal and macd > signal:
            return "buy"
        # Asagi kesisim
        elif prev_macd >= prev_signal and macd < signal:
            return "sell"
        return None
    
    def strategy_ema_cross(self, data: List[Dict], current_idx: int) -> Optional[str]:
        """EMA kesisim stratejisi"""
        if current_idx < 25:
            return None
        
        closes = [d["close"] for d in data[:current_idx+1]]
        
        ema9 = self._calculate_ema(closes, 9)
        ema21 = self._calculate_ema(closes, 21)
        
        prev_closes = closes[:-1]
        prev_ema9 = self._calculate_ema(prev_closes, 9) if len(prev_closes) >= 9 else ema9
        prev_ema21 = self._calculate_ema(prev_closes, 21) if len(prev_closes) >= 21 else ema21
        
        if prev_ema9 <= prev_ema21 and ema9 > ema21:
            return "buy"
        elif prev_ema9 >= prev_ema21 and ema9 < ema21:
            return "sell"
        return None
    
    def run_backtest(self, symbol: str, data: List[Dict], 
                     strategy_name: str = "rsi",
                     tp_pct: float = 5.0,
                     sl_pct: float = 3.0,
                     max_position_pct: float = 10.0,
                     cooldown_bars: int = 5) -> BacktestResult:
        """
        Ana backtest fonksiyonu
        cooldown_bars: Sonraki sinyali engelle (overtrading'i onle)
        """
        print(f"\n[BACKTEST] {symbol} | {strategy_name.upper()} | {len(data)} candle")
        
        self.capital = self.initial_capital
        self.trades = []
        self.equity_curve = [self.initial_capital]
        
        open_trade: Optional[BacktestTrade] = None
        cooldown = 0  # Sinyal bekleme suresi
        
        for i in range(len(data)):
            candle = data[i]
            current_price = candle["close"]
            
            # Cooldown azalt
            if cooldown > 0:
                cooldown -= 1
            
            # Strateji sinyali al
            signal = None
            if cooldown == 0 and not open_trade:
                if strategy_name == "rsi":
                    signal = self.strategy_rsi(data, i)
                elif strategy_name == "macd":
                    signal = self.strategy_macd(data, i)
                elif strategy_name == "ema_cross":
                    signal = self.strategy_ema_cross(data, i)
            
            # Acik trade varsa kontrol et
            if open_trade:
                pnl_pct = 0
                if open_trade.direction == TradeDirection.LONG:
                    pnl_pct = ((current_price - open_trade.entry_price) / open_trade.entry_price) * 100
                else:
                    pnl_pct = ((open_trade.entry_price - current_price) / open_trade.entry_price) * 100
                
                # TP/SL kontrolu
                hit_tp = pnl_pct >= tp_pct
                hit_sl = pnl_pct <= -sl_pct
                
                # Sinyal ters yondeyse kapat
                signal_close = False
                if open_trade.direction == TradeDirection.LONG and signal == "sell":
                    signal_close = True
                elif open_trade.direction == TradeDirection.SHORT and signal == "buy":
                    signal_close = True
                
                # Son mumda kapat
                end_of_test = i == len(data) - 1
                
                if hit_tp or hit_sl or signal_close or end_of_test:
                    reason = "tp" if hit_tp else "sl" if hit_sl else "signal" if signal_close else "end"
                    
                    # Slippage uygula
                    if open_trade.direction == TradeDirection.LONG:
                        exit_price = current_price * (1 - self.slippage_pct / 100)
                    else:
                        exit_price = current_price * (1 + self.slippage_pct / 100)
                    
                    open_trade.close(exit_price, candle["timestamp"], reason)
                    
                    # Komisyon hesapla (giris + cikis)
                    trade_value = open_trade.position_size
                    commission = trade_value * (self.commission_pct / 100) * 2  # Giris + cikis
                    
                    self.capital += open_trade.pnl_usd - commission
                    self.capital = max(self.capital, 0)  # Negatif olmasin
                    
                    self.trades.append(open_trade)
                    open_trade = None
                    cooldown = cooldown_bars  # Yeni sinyel icin bekle
            
            # Yeni trade ac
            elif signal and not open_trade and cooldown == 0:
                # Pozisyon boyutu: mevcut sermayenin %'si
                position_size = (self.capital * max_position_pct / 100)
                
                if position_size < 10:  # Minimum pozisyon
                    continue
                
                if signal == "buy":
                    direction = TradeDirection.LONG
                else:
                    direction = TradeDirection.SHORT
                
                # Slippage uygula
                if direction == TradeDirection.LONG:
                    entry = current_price * (1 + self.slippage_pct / 100)
                else:
                    entry = current_price * (1 - self.slippage_pct / 100)
                
                open_trade = BacktestTrade(
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry,
                    entry_time=candle["timestamp"],
                    position_size=position_size
                )
                
                cooldown = 1  # Bir sonraki bari bekle
            
            self.equity_curve.append(self.capital)
        
        return self._calculate_metrics(symbol, strategy_name, data)
    
    def _calculate_metrics(self, symbol: str, strategy_name: str, 
                          data: List[Dict]) -> BacktestResult:
        """Performans metriklerini hesapla"""
        
        winning = [t for t in self.trades if t.pnl_pct > 0]
        losing = [t for t in self.trades if t.pnl_pct <= 0]
        
        total_return = ((self.capital - self.initial_capital) / self.initial_capital) * 100
        
        # Max drawdown
        max_dd = 0
        peak = self.equity_curve[0]
        for equity in self.equity_curve:
            if equity > peak:
                peak = equity
            dd = ((peak - equity) / peak) * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        
        # Sharpe ratio
        returns = []
        for i in range(1, len(self.equity_curve)):
            if self.equity_curve[i-1] > 0:
                ret = (self.equity_curve[i] - self.equity_curve[i-1]) / self.equity_curve[i-1]
                returns.append(ret)
        
        if len(returns) > 1:
            avg_return = sum(returns) / len(returns)
            variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
            std_dev = variance ** 0.5
            sharpe = (avg_return / std_dev) * (252 ** 0.5) if std_dev > 0 else 0
        else:
            sharpe = 0
        
        # Profit factor
        gross_profit = sum(t.pnl_usd for t in winning)
        gross_loss = abs(sum(t.pnl_usd for t in losing))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        return BacktestResult(
            symbol=symbol,
            strategy_name=strategy_name,
            start_date=str(data[0]["timestamp"]) if data else "",
            end_date=str(data[-1]["timestamp"]) if data else "",
            initial_capital=self.initial_capital,
            final_capital=self.capital,
            total_trades=len(self.trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=(len(winning) / len(self.trades) * 100) if self.trades else 0,
            total_return_pct=total_return,
            max_drawdown_pct=max_dd,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            avg_trade_return=sum(t.pnl_pct for t in self.trades) / len(self.trades) if self.trades else 0,
            avg_winning_trade=sum(t.pnl_pct for t in winning) / len(winning) if winning else 0,
            avg_losing_trade=sum(t.pnl_pct for t in losing) / len(losing) if losing else 0,
            best_trade=max((t.pnl_pct for t in self.trades), default=0),
            worst_trade=min((t.pnl_pct for t in self.trades), default=0)
        )
    
    def generate_demo_data(self, symbol: str = "BTCUSDT", 
                          days: int = 365, 
                          start_price: float = 30000,
                          trend: float = 0.0005,
                          volatility: float = 0.015) -> List[Dict]:
        """Daha gercekci demo veri uret"""
        data = []
        price = start_price
        timestamp = datetime(2024, 1, 1)
        
        for i in range(days * 24):
            # Trendli fiyat hareketi
            change = random.gauss(trend, volatility)
            price = price * (1 + change)
            
            # OHLCV
            open_p = price * (1 + random.gauss(0, 0.003))
            high_p = max(open_p, price) * (1 + abs(random.gauss(0, 0.008)))
            low_p = min(open_p, price) * (1 - abs(random.gauss(0, 0.008)))
            close_p = price
            volume = random.uniform(5000, 20000)
            
            data.append({
                "timestamp": timestamp.isoformat(),
                "open": round(open_p, 2),
                "high": round(high_p, 2),
                "low": round(low_p, 2),
                "close": round(close_p, 2),
                "volume": round(volume, 2)
            })
            
            timestamp = datetime.fromtimestamp(timestamp.timestamp() + 3600)
        
        print(f"[BACKTEST] Demo veri: {symbol} | {len(data)} candle | {days} gun | Trend: {trend}")
        return data
    
    def save_results(self, result: BacktestResult, filepath: str = None):
        """Sonuclari kaydet"""
        if filepath is None:
            filepath = os.path.join(self.data_dir, f"backtest_{result.symbol}_{result.strategy_name}.json")
        
        data = {
            "symbol": result.symbol,
            "strategy": result.strategy_name,
            "metrics": {
                "total_return_pct": result.total_return_pct,
                "win_rate": result.win_rate,
                "max_drawdown_pct": result.max_drawdown_pct,
                "sharpe_ratio": result.sharpe_ratio,
                "profit_factor": result.profit_factor,
                "total_trades": result.total_trades
            }
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[BACKTEST] Kaydedildi: {filepath}")


# ==================== TEST ====================
if __name__ == "__main__":
    print("=" * 70)
    print("ATLAS BACKTEST ENGINE v1.1 - TEST")
    print("=" * 70)
    
    # Daha gercekci veri - yukari trendli
    engine = AtlasBacktestEngine(initial_capital=10000)
    data = engine.generate_demo_data("BTCUSDT", days=180, start_price=40000, 
                                      trend=0.0003, volatility=0.012)
    
    # Test 1: RSI
    print("\n[TEST 1] RSI Stratejisi...")
    result_rsi = engine.run_backtest("BTCUSDT", data, "rsi", tp_pct=8, sl_pct=4)
    result_rsi.print_summary()
    engine.save_results(result_rsi)
    
    # Test 2: MACD
    print("\n[TEST 2] MACD Stratejisi...")
    engine2 = AtlasBacktestEngine(initial_capital=10000)
    result_macd = engine2.run_backtest("BTCUSDT", data, "macd", tp_pct=8, sl_pct=4)
    result_macd.print_summary()
    engine2.save_results(result_macd)
    
    # Test 3: EMA Cross
    print("\n[TEST 3] EMA Cross Stratejisi...")
    engine3 = AtlasBacktestEngine(initial_capital=10000)
    result_ema = engine3.run_backtest("BTCUSDT", data, "ema_cross", tp_pct=8, sl_pct=4)
    result_ema.print_summary()
    engine3.save_results(result_ema)
    
    # Karsilastirma
    print("\n" + "=" * 70)
    print("STRATEJI KARSILASTIRMASI")
    print("=" * 70)
    print(f"{'Strateji':<15} {'Getiri %':<12} {'Win Rate':<12} {'Max DD':<12} {'Trades':<10}")
    print("-" * 70)
    for r in [result_rsi, result_macd, result_ema]:
        print(f"{r.strategy_name:<15} {r.total_return_pct:>+8.2f}    {r.win_rate:>6.1f}%    {r.max_drawdown_pct:>6.2f}%    {r.total_trades:>6}")
    print("=" * 70)
    
    print("\n" + "=" * 70)
    print("BACKTEST ENGINE v1.1 TEST TAMAMLANDI!")
    print("=" * 70)