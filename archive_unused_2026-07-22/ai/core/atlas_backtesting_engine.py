# -*- coding: utf-8 -*-
"""
ATLAS BACKTESTING ENGINE v2
Gelismis stratejiler, coklu sinyal, dinamik SL/TP, trailing stop
"""
import random
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class OHLCV:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Trade:
    id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    entry_time: int
    exit_time: int
    pnl: float
    pnl_pct: float
    fees: float
    strategy: str
    exit_reason: str


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    start_date: str
    end_date: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    profit_factor: float
    avg_trade_return: float
    avg_win: float
    avg_loss: float
    best_trade: float
    worst_trade: float
    trades: List[Trade]
    equity_curve: List[float]
    avg_holding_period: float


class AtlasBacktestingEngine:
    """
    Atlas AI Backtesting Motoru v2
    
    Yeni Stratejiler:
    1. RSI_Divergence - RSI uyumsuzlugu
    2. MACD_Histogram - MACD histogram stratejisi
    3. Bollinger_Squeeze - Bollinger daralmasi
    4. Volume_Breakout - Hacimli kirilim
    5. Multi_Timeframe - Coklu zaman dilimi
    6. Trend_Following - Trend takip
    7. Mean_Reversion - Ortalama donus
    8. Momentum - Momentum stratejisi
    9. Support_Resistance - Destek/direnc
    10. Combo_All - Tum gostergelerin birlesimi
    """
    
    COIN_UNIVERSE = {
        "BTC": {"category": "major", "volatility": 0.025, "base_price": 65000},
        "ETH": {"category": "major", "volatility": 0.030, "base_price": 3500},
        "BNB": {"category": "major", "volatility": 0.028, "base_price": 580},
        "SOL": {"category": "major", "volatility": 0.040, "base_price": 150},
        "XRP": {"category": "major", "volatility": 0.035, "base_price": 0.62},
        "ADA": {"category": "major", "volatility": 0.035, "base_price": 0.45},
        "DOGE": {"category": "major", "volatility": 0.045, "base_price": 0.12},
        "DOT": {"category": "major", "volatility": 0.032, "base_price": 7.2},
        "AVAX": {"category": "major", "volatility": 0.038, "base_price": 28},
        "LINK": {"category": "major", "volatility": 0.033, "base_price": 14},
        "UNI": {"category": "defi", "volatility": 0.040, "base_price": 8.5},
        "AAVE": {"category": "defi", "volatility": 0.042, "base_price": 95},
        "COMP": {"category": "defi", "volatility": 0.045, "base_price": 52},
        "MKR": {"category": "defi", "volatility": 0.038, "base_price": 1400},
        "LDO": {"category": "defi", "volatility": 0.050, "base_price": 1.8},
        "CRV": {"category": "defi", "volatility": 0.055, "base_price": 0.35},
        "SUSHI": {"category": "defi", "volatility": 0.052, "base_price": 0.85},
        "1INCH": {"category": "defi", "volatility": 0.048, "base_price": 0.38},
        "MATIC": {"category": "layer1", "volatility": 0.038, "base_price": 0.55},
        "ARB": {"category": "layer2", "volatility": 0.042, "base_price": 0.78},
        "OP": {"category": "layer2", "volatility": 0.045, "base_price": 1.4},
        "NEAR": {"category": "layer1", "volatility": 0.040, "base_price": 5.2},
        "FTM": {"category": "layer1", "volatility": 0.048, "base_price": 0.42},
        "ALGO": {"category": "layer1", "volatility": 0.042, "base_price": 0.15},
        "ATOM": {"category": "layer1", "volatility": 0.038, "base_price": 6.8},
        "ICP": {"category": "layer1", "volatility": 0.050, "base_price": 8.5},
        "SAND": {"category": "gaming", "volatility": 0.055, "base_price": 0.28},
        "MANA": {"category": "gaming", "volatility": 0.052, "base_price": 0.32},
        "AXS": {"category": "gaming", "volatility": 0.058, "base_price": 6.5},
        "GALA": {"category": "gaming", "volatility": 0.060, "base_price": 0.025},
        "ENJ": {"category": "gaming", "volatility": 0.050, "base_price": 0.22},
        "ILV": {"category": "gaming", "volatility": 0.065, "base_price": 42},
        "FIL": {"category": "infra", "volatility": 0.045, "base_price": 4.2},
        "GRT": {"category": "infra", "volatility": 0.048, "base_price": 0.18},
        "LPT": {"category": "infra", "volatility": 0.055, "base_price": 8.5},
        "HNT": {"category": "infra", "volatility": 0.050, "base_price": 3.8},
        "RNDR": {"category": "infra", "volatility": 0.055, "base_price": 6.2},
        "SHIB": {"category": "meme", "volatility": 0.065, "base_price": 0.000018},
        "PEPE": {"category": "meme", "volatility": 0.080, "base_price": 0.000009},
        "FLOKI": {"category": "meme", "volatility": 0.075, "base_price": 0.00015},
        "BONK": {"category": "meme", "volatility": 0.070, "base_price": 0.000025},
        "AGIX": {"category": "ai", "volatility": 0.060, "base_price": 0.55},
        "FET": {"category": "ai", "volatility": 0.058, "base_price": 1.2},
        "OCEAN": {"category": "ai", "volatility": 0.052, "base_price": 0.45},
        "CRO": {"category": "exchange", "volatility": 0.040, "base_price": 0.095},
        "FTT": {"category": "exchange", "volatility": 0.070, "base_price": 1.5},
        "KCS": {"category": "exchange", "volatility": 0.042, "base_price": 8.2},
        "HT": {"category": "exchange", "volatility": 0.045, "base_price": 0.55},
        "USDT": {"category": "stable", "volatility": 0.002, "base_price": 1.0},
        "USDC": {"category": "stable", "volatility": 0.002, "base_price": 1.0},
        "DAI": {"category": "stable", "volatility": 0.003, "base_price": 1.0},
    }
    
    @classmethod
    def add_coin(cls, symbol: str, category: str, volatility: float, base_price: float):
        cls.COIN_UNIVERSE[symbol] = {
            "category": category,
            "volatility": volatility,
            "base_price": base_price,
        }
        return True
    
    def __init__(self, initial_capital: float = 10000.0):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.data: Dict[str, List[OHLCV]] = {}
        self.results: Dict[str, BacktestResult] = {}
        self.active_coins: List[str] = []
        
    def generate_historical_data(self, symbol: str, days: int = 365) -> List[OHLCV]:
        if symbol not in self.COIN_UNIVERSE:
            return []
            
        coin_info = self.COIN_UNIVERSE[symbol]
        base_price = coin_info["base_price"]
        volatility = coin_info["volatility"]
        
        data = []
        price = base_price
        now = int(time.time())
        
        for i in range(days):
            timestamp = now - (days - i) * 86400
            daily_return = random.gauss(0.0005, volatility)
            open_price = price
            close_price = price * (1 + daily_return)
            intraday_vol = volatility * 0.5
            high_price = max(open_price, close_price) * (1 + abs(random.gauss(0, intraday_vol)))
            low_price = min(open_price, close_price) * (1 - abs(random.gauss(0, intraday_vol)))
            volume = random.uniform(1e6, 1e9) * (1 + abs(daily_return) * 10)
            
            candle = OHLCV(
                timestamp=timestamp,
                open=round(open_price, 8),
                high=round(high_price, 8),
                low=round(max(low_price, 0.000001), 8),
                close=round(close_price, 8),
                volume=round(volume, 2),
            )
            data.append(candle)
            price = close_price
        return data
    
    def load_data(self, symbols: List[str], days: int = 365):
        print(f"  [*] Veri yukleniyor: {len(symbols)} coin, {days} gun...")
        for symbol in symbols:
            self.data[symbol] = self.generate_historical_data(symbol, days)
        self.active_coins = symbols
        print(f"  [OK] Veri yuklendi: {len(symbols)} coin")
        
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> List[float]:
        if len(prices) < period + 1:
            return [50.0] * len(prices)
        rsi_values = [50.0] * period
        for i in range(period, len(prices)):
            gains = []
            losses = []
            for j in range(i - period + 1, i + 1):
                change = prices[j] - prices[j - 1]
                if change > 0:
                    gains.append(change)
                else:
                    losses.append(abs(change))
            avg_gain = sum(gains) / period if gains else 0.001
            avg_loss = sum(losses) / period if losses else 0.001
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            rsi_values.append(rsi)
        return rsi_values
    
    def _calculate_ema(self, prices: List[float], period: int = 20) -> List[float]:
        if len(prices) < period:
            return list(prices)
        multiplier = 2 / (period + 1)
        ema = [sum(prices[:period]) / period]
        for i in range(period, len(prices)):
            ema.append((prices[i] - ema[-1]) * multiplier + ema[-1])
        return [ema[0]] * (period - 1) + ema
    
    def _calculate_sma(self, prices: List[float], period: int = 20) -> List[float]:
        sma = []
        for i in range(len(prices)):
            if i < period - 1:
                sma.append(sum(prices[:i+1]) / (i+1))
            else:
                sma.append(sum(prices[i-period+1:i+1]) / period)
        return sma
    
    def _calculate_macd(self, prices: List[float]) -> Tuple[List[float], List[float], List[float]]:
        ema12 = self._calculate_ema(prices, 12)
        ema26 = self._calculate_ema(prices, 26)
        macd_line = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
        signal_line = self._calculate_ema(macd_line, 9)
        histogram = [m - s for m, s in zip(macd_line, signal_line)]
        return macd_line, signal_line, histogram
    
    def _calculate_bollinger(self, prices: List[float], period: int = 20, std_dev: float = 2.0):
        middle = []
        upper = []
        lower = []
        bandwidth = []
        for i in range(len(prices)):
            if i < period - 1:
                middle.append(prices[i])
                upper.append(prices[i] * 1.02)
                lower.append(prices[i] * 0.98)
                bandwidth.append(0.04)
            else:
                window = prices[i - period + 1:i + 1]
                sma = sum(window) / period
                std = (sum((p - sma) ** 2 for p in window) / period) ** 0.5
                middle.append(sma)
                upper.append(sma + std * std_dev)
                lower.append(sma - std * std_dev)
                bandwidth.append((upper[-1] - lower[-1]) / middle[-1] if middle[-1] > 0 else 0)
        return upper, middle, lower, bandwidth
    
    def _calculate_atr(self, candles: List[OHLCV], period: int = 14) -> List[float]:
        tr_values = []
        for i in range(len(candles)):
            if i == 0:
                tr = candles[i].high - candles[i].low
            else:
                tr1 = candles[i].high - candles[i].low
                tr2 = abs(candles[i].high - candles[i-1].close)
                tr3 = abs(candles[i].low - candles[i-1].close)
                tr = max(tr1, tr2, tr3)
            tr_values.append(tr)
        
        atr = []
        for i in range(len(tr_values)):
            if i < period:
                atr.append(sum(tr_values[:i+1]) / (i+1))
            else:
                atr.append((atr[-1] * (period - 1) + tr_values[i]) / period)
        return atr
    
    def _calculate_volume_sma(self, candles: List[OHLCV], period: int = 20) -> List[float]:
        volumes = [c.volume for c in candles]
        return self._calculate_sma(volumes, period)
    
    def _find_support_resistance(self, prices: List[float], lookback: int = 20) -> Tuple[List[float], List[float]]:
        supports = []
        resistances = []
        for i in range(len(prices)):
            if i < lookback:
                supports.append(prices[i] * 0.95)
                resistances.append(prices[i] * 1.05)
            else:
                window = prices[i-lookback:i+1]
                supports.append(min(window) * 1.02)
                resistances.append(max(window) * 0.98)
        return supports, resistances
    
    def _check_divergence(self, prices: List[float], indicator: List[float], lookback: int = 10) -> str:
        if len(prices) < lookback * 2 or len(indicator) < lookback * 2:
            return "none"
        
        price_now = prices[-1]
        price_before = prices[-lookback-1]
        ind_now = indicator[-1]
        ind_before = indicator[-lookback-1]
        
        # Bullish divergence: price lower low, indicator higher low
        if price_now < price_before and ind_now > ind_before:
            return "bullish"
        # Bearish divergence: price higher high, indicator lower high
        elif price_now > price_before and ind_now < ind_before:
            return "bearish"
        return "none"
    
    def run_strategy(self, symbol: str, strategy_type: str = "combo_all",
                     stop_loss_pct: float = 0.05,
                     take_profit_pct: float = 0.10,
                     trailing_stop: bool = True) -> BacktestResult:
        if symbol not in self.data or not self.data[symbol]:
            return None
            
        candles = self.data[symbol]
        prices = [c.close for c in candles]
        volumes = [c.volume for c in candles]
        
        # Gostergeler
        rsi = self._calculate_rsi(prices)
        ema9 = self._calculate_ema(prices, 9)
        ema20 = self._calculate_ema(prices, 20)
        ema50 = self._calculate_ema(prices, 50)
        sma20 = self._calculate_sma(prices, 20)
        macd_line, signal_line, histogram = self._calculate_macd(prices)
        bb_upper, bb_middle, bb_lower, bb_bandwidth = self._calculate_bollinger(prices)
        atr = self._calculate_atr(candles)
        vol_sma = self._calculate_volume_sma(candles)
        supports, resistances = self._find_support_resistance(prices)
        
        trades = []
        equity = [self.initial_capital]
        position = None
        entry_price = 0.0
        entry_time = 0
        highest_price = 0.0  # Trailing stop icin
        
        capital = self.initial_capital
        
        # Bollinger Squeeze icin son N barda gercek sikisma yasandi mi takibi
        squeeze_lookback = 10
        squeeze_threshold = 0.08  # Kripto volatilitesine daha uygun esik
        
        for i in range(50, len(candles) - 1):
            candle = candles[i]
            next_candle = candles[i + 1]
            
            # Dinamik SL/TP (ATR bazli)
            current_atr = atr[i] if i < len(atr) else atr[-1]
            atr_sl = (current_atr / candle.close) * 2.0  # 2x ATR
            atr_tp = (current_atr / candle.close) * 3.0  # 3x ATR
            
            sl = max(stop_loss_pct, atr_sl)
            tp = max(take_profit_pct, atr_tp)
            
            # Strateji sinyalleri
            buy_signal = False
            sell_signal = False
            
            # 1. RSI Divergence
            if strategy_type in ["rsi_divergence", "combo_all"]:
                div = self._check_divergence(prices[:i+1], rsi[:i+1])
                if div == "bullish" and position is None:
                    buy_signal = True
                elif div == "bearish" and position == "LONG":
                    sell_signal = True
            
            # 2. MACD Histogram
            if strategy_type in ["macd_histogram", "combo_all"]:
                if (histogram[i] > 0 and histogram[i-1] <= 0 and 
                    macd_line[i] > signal_line[i] and position is None):
                    buy_signal = True
                elif (histogram[i] < 0 and histogram[i-1] >= 0 and 
                      macd_line[i] < signal_line[i] and position == "LONG"):
                    sell_signal = True
            
            # 3. Bollinger Squeeze (DUZELTILDI)
            # Onceki mantik "bandwidth < esik VE bir onceki bar >= esik" seklindeydi;
            # bu, sikismaya girisin tam o barda yakalanmasini gerektiriyordu ve
            # yorumla celisecek sekilde breakout'u degil sikisma baslangicini ariyordu.
            # Bu yuzden 48 coin uzerinde hemen hic tetiklenmiyordu (0 trade).
            # Yeni mantik: son squeeze_lookback bar icinde gercek bir sikisma
            # yasanmis mi diye bakar, ardindan fiyat ust bandin uzerine kirildiginda
            # (gercek "squeeze sonrasi patlama") alim sinyali uretir.
            if strategy_type in ["bollinger_squeeze", "combo_all"]:
                recent_bw = bb_bandwidth[max(0, i - squeeze_lookback):i]
                was_squeezed = len(recent_bw) > 0 and min(recent_bw) < squeeze_threshold
                if (was_squeezed and candle.close > bb_upper[i] and 
                    candles[i-1].close <= bb_upper[i-1] and position is None):
                    buy_signal = True  # Sikisma sonrasi yukari kirilim
                elif (candle.close < bb_middle[i] and position == "LONG"):
                    sell_signal = True  # Orta banda geri donus -> cik
            
            # 4. Volume Breakout
            if strategy_type in ["volume_breakout", "combo_all"]:
                vol_spike = volumes[i] > vol_sma[i] * 1.5 if i < len(vol_sma) else False
                if (vol_spike and candle.close > ema20[i] and 
                    candle.close > candle.open * 1.02 and position is None):
                    buy_signal = True
                elif (vol_spike and candle.close < ema20[i] and position == "LONG"):
                    sell_signal = True
            
            # 5. Multi Timeframe (EMA stack)
            if strategy_type in ["multi_timeframe", "combo_all", "trend_following"]:
                if (ema9[i] > ema20[i] > ema50[i] and 
                    ema9[i-1] <= ema20[i-1] and position is None):
                    buy_signal = True
                elif (ema9[i] < ema20[i] < ema50[i] and 
                      ema9[i-1] >= ema20[i-1] and position == "LONG"):
                    sell_signal = True
            
            # 6. Mean Reversion
            if strategy_type in ["mean_reversion", "combo_all"]:
                if (candle.close < bb_lower[i] * 1.02 and rsi[i] < 30 and position is None):
                    buy_signal = True
                elif (candle.close > bb_upper[i] * 0.98 and rsi[i] > 70 and position == "LONG"):
                    sell_signal = True
            
            # 7. Momentum
            if strategy_type in ["momentum", "combo_all"]:
                price_change_5d = (prices[i] - prices[max(0, i-5)]) / prices[max(0, i-5)] if prices[max(0, i-5)] > 0 else 0
                if (price_change_5d > 0.05 and rsi[i] > 55 and rsi[i] < 75 and 
                    volumes[i] > vol_sma[i] and position is None):
                    buy_signal = True
                elif (price_change_5d < -0.03 and position == "LONG"):
                    sell_signal = True
            
            # 8. Support/Resistance
            if strategy_type in ["support_resistance", "combo_all"]:
                if (candle.close < supports[i] * 1.01 and rsi[i] < 40 and position is None):
                    buy_signal = True  # Destekten donus
                elif (candle.close > resistances[i] * 0.99 and position == "LONG"):
                    sell_signal = True  # Direncte satis
            
            # Islem yurut
            if buy_signal and capital > 100:
                position = "LONG"
                entry_price = next_candle.open
                entry_time = next_candle.timestamp
                highest_price = entry_price
            
            # Pozisyon yonetimi (SL/TP/Trailing)
            elif position == "LONG":
                current_pnl_pct = (candle.close - entry_price) / entry_price
                
                # Trailing stop guncelle
                if trailing_stop and candle.close > highest_price:
                    highest_price = candle.close
                
                # Stop Loss kontrolu
                stop_hit = candle.close < entry_price * (1 - sl)
                
                # Take Profit kontrolu
                tp_hit = candle.close > entry_price * (1 + tp)
                
                # Trailing Stop kontrolu
                trail_hit = False
                if trailing_stop and highest_price > entry_price * 1.02:
                    trail_distance = (highest_price - entry_price) * 0.3  # %30 geri cekilme
                    trail_hit = candle.close < highest_price - trail_distance
                
                # Sinyal cikisi
                signal_exit = sell_signal
                
                if stop_hit or tp_hit or trail_hit or signal_exit:
                    exit_price = next_candle.open
                    pnl = (exit_price - entry_price) / entry_price
                    pnl_value = capital * pnl * 0.95
                    fees = capital * 0.002
                    
                    # Cikis nedeni
                    if stop_hit:
                        reason = "stop_loss"
                    elif tp_hit:
                        reason = "take_profit"
                    elif trail_hit:
                        reason = "trailing_stop"
                    else:
                        reason = "signal"
                    
                    trade = Trade(
                        id=f"T{len(trades)}_{symbol}",
                        symbol=symbol,
                        side="BUY",
                        entry_price=entry_price,
                        exit_price=exit_price,
                        quantity=capital * 0.95 / entry_price,
                        entry_time=entry_time,
                        exit_time=next_candle.timestamp,
                        pnl=pnl_value - fees,
                        pnl_pct=pnl * 100,
                        fees=fees,
                        strategy=strategy_type,
                        exit_reason=reason,
                    )
                    
                    trades.append(trade)
                    capital += pnl_value - fees
                    equity.append(capital)
                    position = None
                    highest_price = 0.0
        
        # Acik pozisyonu kapat
        if position == "LONG":
            exit_price = candles[-1].close
            pnl = (exit_price - entry_price) / entry_price
            pnl_value = capital * pnl * 0.95
            fees = capital * 0.002
            
            trade = Trade(
                id=f"T{len(trades)}_{symbol}_CLOSE",
                symbol=symbol,
                side="BUY",
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=capital * 0.95 / entry_price,
                entry_time=entry_time,
                exit_time=candles[-1].timestamp,
                pnl=pnl_value - fees,
                pnl_pct=pnl * 100,
                fees=fees,
                strategy=strategy_type,
                exit_reason="timeout",
            )
            trades.append(trade)
            capital += pnl_value - fees
        
        # Metrikler
        total_return = (capital - self.initial_capital) / self.initial_capital
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl <= 0]
        
        win_rate = len(winning_trades) / len(trades) if trades else 0
        avg_win = sum(t.pnl_pct for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.pnl_pct for t in losing_trades) / len(losing_trades) if losing_trades else 0
        
        profit_factor = abs(sum(t.pnl for t in winning_trades) / sum(t.pnl for t in losing_trades)) if losing_trades and sum(t.pnl for t in losing_trades) != 0 else float('inf')
        
        # Max drawdown
        peak = self.initial_capital
        max_dd = 0
        for eq in equity:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
        
        # Sharpe
        returns = [(equity[i] - equity[i-1]) / equity[i-1] for i in range(1, len(equity))] if len(equity) > 1 else [0]
        avg_return = sum(returns) / len(returns) if returns else 0
        std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5 if returns else 1
        sharpe = (avg_return / std_return) * (252 ** 0.5) if std_return > 0 else 0
        
        # Ortalama tutma suresi
        avg_holding = 0
        if trades:
            holding_periods = []
            for t in trades:
                days_held = (t.exit_time - t.entry_time) / 86400
                holding_periods.append(days_held)
            avg_holding = sum(holding_periods) / len(holding_periods)
        
        result = BacktestResult(
            strategy_name=strategy_type,
            symbol=symbol,
            start_date=datetime.fromtimestamp(candles[0].timestamp).strftime('%Y-%m-%d'),
            end_date=datetime.fromtimestamp(candles[-1].timestamp).strftime('%Y-%m-%d'),
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=win_rate,
            total_return=total_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            profit_factor=profit_factor,
            avg_trade_return=sum(t.pnl_pct for t in trades) / len(trades) if trades else 0,
            avg_win=avg_win,
            avg_loss=avg_loss,
            best_trade=max((t.pnl_pct for t in trades), default=0),
            worst_trade=min((t.pnl_pct for t in trades), default=0),
            trades=trades,
            equity_curve=equity,
            avg_holding_period=avg_holding,
        )
        
        self.results[symbol] = result
        return result
    
    def run_multi_coin_backtest(self, symbols: List[str], strategy: str = "combo_all") -> Dict[str, BacktestResult]:
        results = {}
        print(f"\n  [*] Coklu coin backtesti baslatiliyor...")
        print(f"  [*] Strateji: {strategy}")
        print(f"  [*] Coin sayisi: {len(symbols)}")
        print()
        
        for i, symbol in enumerate(symbols, 1):
            print(f"  [{i:3d}/{len(symbols)}] {symbol:8s} test ediliyor...", end=" ")
            result = self.run_strategy(symbol, strategy)
            if result:
                emoji = "+" if result.total_return > 0 else "-"
                exit_breakdown = {}
                for t in result.trades:
                    exit_breakdown[t.exit_reason] = exit_breakdown.get(t.exit_reason, 0) + 1
                print(f"{emoji} Getiri: {result.total_return:+.1%} | WinRate: {result.win_rate:.1%} | Trades: {result.total_trades:2d} | Tutma: {result.avg_holding_period:.1f}g")
                results[symbol] = result
            else:
                print("VERI YOK")
        return results
    
    def get_best_performers(self, n: int = 10) -> List[Tuple[str, BacktestResult]]:
        return sorted(self.results.items(), key=lambda x: x[1].total_return, reverse=True)[:n]
    
    def get_worst_performers(self, n: int = 10) -> List[Tuple[str, BacktestResult]]:
        return sorted(self.results.items(), key=lambda x: x[1].total_return)[:n]
    
    def get_category_performance(self) -> Dict[str, Dict]:
        category_stats = {}
        for symbol, result in self.results.items():
            if symbol in self.COIN_UNIVERSE:
                cat = self.COIN_UNIVERSE[symbol]["category"]
                if cat not in category_stats:
                    category_stats[cat] = {"returns": [], "win_rates": [], "counts": [], "count": 0}
                category_stats[cat]["returns"].append(result.total_return)
                category_stats[cat]["win_rates"].append(result.win_rate)
                category_stats[cat]["counts"].append(result.total_trades)
                category_stats[cat]["count"] += 1
        
        for cat in category_stats:
            stats = category_stats[cat]
            stats["avg_return"] = sum(stats["returns"]) / len(stats["returns"])
            stats["avg_win_rate"] = sum(stats["win_rates"]) / len(stats["win_rates"])
            stats["avg_trades"] = sum(stats["counts"]) / len(stats["counts"])
        return category_stats
    
    def get_exit_analysis(self) -> Dict[str, int]:
        exits = {}
        for result in self.results.values():
            for trade in result.trades:
                exits[trade.exit_reason] = exits.get(trade.exit_reason, 0) + 1
        return exits
    
    def generate_report(self) -> str:
        if not self.results:
            return "Heniz backtest yapilmadi."
        
        best = self.get_best_performers(10)
        worst = self.get_worst_performers(5)
        categories = self.get_category_performance()
        exits = self.get_exit_analysis()
        
        total_return = sum(r.total_return for r in self.results.values()) / len(self.results)
        avg_win_rate = sum(r.win_rate for r in self.results.values()) / len(self.results)
        avg_sharpe = sum(r.sharpe_ratio for r in self.results.values()) / len(self.results)
        avg_drawdown = sum(r.max_drawdown for r in self.results.values()) / len(self.results)
        total_trades = sum(r.total_trades for r in self.results.values())
        avg_holding = sum(r.avg_holding_period for r in self.results.values()) / len(self.results)
        
        report = f"""
==============================================================
     ATLAS BACKTESTING ENGINE v2 - BACKTEST RAPORU            
==============================================================
  Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  Baslangic Sermayesi: ${self.initial_capital:,.2f}
  Test Edilen Coin: {len(self.results)}
  Toplam Islem: {total_trades}
  Ortalama Tutma Suresi: {avg_holding:.1f} gun
  
  GENEL PERFORMANS:
    Ortalama Getiri: {total_return:+.1%}
    Ortalama WinRate: {avg_win_rate:.1%}
    Ortalama Sharpe: {avg_sharpe:.2f}
    Ortalama Max DD: {avg_drawdown:.1%}
    
  EN IYI 10 COIN:
"""
        for i, (symbol, result) in enumerate(best, 1):
            report += f"    #{i:2d} {symbol:8s} | Getiri: {result.total_return:+.1%} | WinRate: {result.win_rate:.1%} | Trades: {result.total_trades:2d} | Sharpe: {result.sharpe_ratio:.2f} | Tutma: {result.avg_holding_period:.1f}g\n"
        
        report += f"\n  EN KOTU 5 COIN:\n"
        for i, (symbol, result) in enumerate(worst, 1):
            report += f"    #{i} {symbol:8s} | Getiri: {result.total_return:+.1%} | WinRate: {result.win_rate:.1%} | Trades: {result.total_trades:2d}\n"
        
        report += f"\n  KATEGORI PERFORMANSI:\n"
        for cat, stats in sorted(categories.items(), key=lambda x: x[1]["avg_return"], reverse=True):
            report += f"    {cat:12s}: Getiri: {stats['avg_return']:+.1%} | WinRate: {stats['avg_win_rate']:.1%} | Ort.Trade: {stats['avg_trades']:.1f} | Coin: {stats['count']}\n"
        
        report += f"\n  CIKIS NEDENLERI:\n"
        for reason, count in sorted(exits.items(), key=lambda x: x[1], reverse=True):
            report += f"    {reason:20s}: {count} islem\n"
        
        report += f"\n  AKTIF COIN LISTESI ({len(self.active_coins)} adet):\n"
        for i in range(0, len(self.active_coins), 10):
            row = self.active_coins[i:i+10]
            report += f"    {', '.join(row)}\n"
        
        report += f"""
  COIN EKLEME:
    AtlasBacktestingEngine.add_coin("YENI", "kategori", volatilite, fiyat)
==============================================================
"""
        return report


# ==============================================================
# TEST
# ==============================================================

def test_backtesting_engine_v2():
    print("=" * 70)
    print("ATLAS BACKTESTING ENGINE v2 - GELISMIS STRATEJI TESTI")
    print("=" * 70)
    
    engine = AtlasBacktestingEngine(initial_capital=10000.0)
    
    # 1. Coin evreni
    print("\n[1] Coin Evreni")
    print("-" * 50)
    print(f"  Toplam coin: {len(engine.COIN_UNIVERSE)}")
    categories = {}
    for symbol, info in engine.COIN_UNIVERSE.items():
        cat = info["category"]
        categories[cat] = categories.get(cat, 0) + 1
    for cat, count in sorted(categories.items()):
        print(f"    {cat:12s}: {count} coin")
    
    # 2. Tum stratejileri test et
    strategies = [
        "rsi_divergence",
        "macd_histogram", 
        "bollinger_squeeze",
        "volume_breakout",
        "multi_timeframe",
        "mean_reversion",
        "momentum",
        "support_resistance",
        "combo_all"
    ]
    
    crypto_coins = [s for s, info in engine.COIN_UNIVERSE.items() if info["category"] != "stable"]
    print(f"\n[2] Tum Stratejilerin Karsilastirmasi")
    print("-" * 50)
    print(f"  Test edilecek: {len(crypto_coins)} coin x {len(strategies)} strateji")
    
    engine.load_data(crypto_coins, days=365)
    
    strategy_results = {}
    for strat in strategies:
        print(f"\n  [*] Strateji: {strat}")
        engine.results.clear()
        results = engine.run_multi_coin_backtest(crypto_coins, strategy=strat)
        
        if results:
            avg_return = sum(r.total_return for r in results.values()) / len(results)
            avg_winrate = sum(r.win_rate for r in results.values()) / len(results)
            total_trades = sum(r.total_trades for r in results.values())
            avg_trades = total_trades / len(results)
            
            strategy_results[strat] = {
                "avg_return": avg_return,
                "avg_winrate": avg_winrate,
                "total_trades": total_trades,
                "avg_trades": avg_trades,
            }
            print(f"      Ort.Getiri: {avg_return:+.1%} | Ort.WinRate: {avg_winrate:.1%} | Toplam Trade: {total_trades}")
    
    # 3. Strateji siralamasi
    print("\n[3] Strateji Siralamasi (Ortalama Getiri)")
    print("-" * 50)
    sorted_strats = sorted(strategy_results.items(), key=lambda x: x[1]["avg_return"], reverse=True)
    for i, (strat, data) in enumerate(sorted_strats, 1):
        print(f"  #{i} {strat:20s}: Getiri: {data['avg_return']:+.1%} | WinRate: {data['avg_winrate']:.1%} | Trade/Coin: {data['avg_trades']:.1f}")
    
    # 4. En iyi strateji ile detayli rapor
    print(f"\n[4] En Iyi Strateji Detayli Analiz: {sorted_strats[0][0]}")
    print("-" * 50)
    best_strat = sorted_strats[0][0]
    engine.results.clear()
    engine.run_multi_coin_backtest(crypto_coins, strategy=best_strat)
    
    best = engine.get_best_performers(10)
    print("\n  En Iyi 10 Coin:")
    for i, (symbol, result) in enumerate(best, 1):
        cat = engine.COIN_UNIVERSE[symbol]["category"]
        exit_reasons = {}
        for t in result.trades:
            exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1
        reasons_str = ", ".join([f"{k}:{v}" for k, v in exit_reasons.items()])
        print(f"    #{i:2d} {symbol:8s} [{cat:8s}] | Getiri: {result.total_return:+.1%} | WinRate: {result.win_rate:.1%} | Trades: {result.total_trades:2d} | Tutma: {result.avg_holding_period:.1f}g | Cikis: {reasons_str}")
    
    # 5. Kategori analizi
    print("\n[5] Kategori Bazli Analiz")
    print("-" * 50)
    cat_perf = engine.get_category_performance()
    for cat, stats in sorted(cat_perf.items(), key=lambda x: x[1]["avg_return"], reverse=True):
        print(f"  {cat:12s}: Getiri: {stats['avg_return']:+.1%} | WinRate: {stats['avg_win_rate']:.1%} | Ort.Trade: {stats['avg_trades']:.1f}")
    
    # 6. Cikis analizi
    print("\n[6] Cikis Nedenleri Analizi")
    print("-" * 50)
    exits = engine.get_exit_analysis()
    for reason, count in sorted(exits.items(), key=lambda x: x[1], reverse=True):
        pct = count / sum(exits.values()) * 100
        print(f"  {reason:20s}: {count:3d} islem ({pct:.1f}%)")
    
    # 7. Rapor
    print("\n" + "=" * 70)
    print(engine.generate_report())
    
    # 8. Strateji karsilastirma grafigi (metin)
    print("\n[7] Strateji Performans Karsilastirmasi")
    print("-" * 50)
    print(f"  {'Strateji':<22} {'Getiri':>10} {'WinRate':>10} {'Trades':>8}")
    print(f"  {'-'*22} {'-'*10} {'-'*10} {'-'*8}")
    for strat, data in sorted_strats:
        bar = "+" * int(abs(data['avg_return']) * 50)
        sign = "+" if data['avg_return'] > 0 else "-"
        print(f"  {strat:<22} {data['avg_return']:>+9.1%} {data['avg_winrate']:>9.1%} {data['total_trades']:>7d}")
    
    print("\n" + "=" * 70)
    print("[OK] GELISMIS BACKTESTING TEST TAMAMLANDI")
    print("=" * 70)


if __name__ == "__main__":
    test_backtesting_engine_v2()