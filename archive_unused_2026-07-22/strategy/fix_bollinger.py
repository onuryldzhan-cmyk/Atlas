import os

code = '''\"\"\"Atlas AI - Bollinger Squeeze Stratejisi v5 (Duzeltilmis)\"\"\"

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class SqueezeSignal:
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    squeeze_bars: int
    reason: str


class BollingerSqueezeStrategy:
    def __init__(self,
                 bb_period: int = 20,
                 bb_std: float = 2.0,
                 squeeze_threshold: float = 0.05,
                 min_squeeze_bars: int = 5,
                 max_squeeze_bars: int = 30,
                 atr_period: int = 14,
                 atr_sl_mult: float = 2.0,
                 atr_tp_mult: float = 3.0,
                 lookback: int = 3):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.squeeze_threshold = squeeze_threshold
        self.min_squeeze_bars = min_squeeze_bars
        self.max_squeeze_bars = max_squeeze_bars
        self.atr_period = atr_period
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp_mult = atr_tp_mult
        self.lookback = lookback
        self.name = "bollinger_squeeze"
        self.description = "Bollinger Squeeze Breakout Strategy"

    def calculate_bollinger(self, closes: np.ndarray):
        n = len(closes)
        if n < self.bb_period:
            return None, None, None, None
        series = pd.Series(closes)
        sma = series.rolling(window=self.bb_period, min_periods=self.bb_period).mean().values
        std = series.rolling(window=self.bb_period, min_periods=self.bb_period).std().values
        upper = sma + self.bb_std * std
        lower = sma - self.bb_std * std
        bandwidth = np.full(n, np.nan)
        valid = ~np.isnan(sma) & (sma != 0)
        bandwidth[valid] = (upper[valid] - lower[valid]) / sma[valid]
        return upper, sma, lower, bandwidth

    def calculate_atr(self, highs, lows, closes):
        n = len(closes)
        if n < 2:
            return np.zeros(n)
        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - closes[:-1])
        tr3 = np.abs(lows[1:] - closes[:-1])
        tr = np.maximum(np.maximum(tr1, tr2), tr3)
        atr = pd.Series(tr).rolling(window=self.atr_period, min_periods=1).mean().values
        atr = np.concatenate([[tr[0] if len(tr) > 0 else 0], atr])
        atr = pd.Series(atr).ffill().bfill().values
        return atr

    def find_squeeze_periods(self, bandwidth):
        periods = []
        in_squeeze = False
        start = 0
        for i in range(len(bandwidth)):
            if np.isnan(bandwidth[i]):
                if in_squeeze:
                    duration = i - start
                    if duration >= self.min_squeeze_bars:
                        periods.append((start, i - 1))
                    in_squeeze = False
                continue
            is_squeeze = bandwidth[i] < self.squeeze_threshold
            if is_squeeze and not in_squeeze:
                start = i
                in_squeeze = True
            elif not is_squeeze and in_squeeze:
                duration = i - start
                if duration >= self.min_squeeze_bars:
                    periods.append((start, i - 1))
                in_squeeze = False
        if in_squeeze:
            duration = len(bandwidth) - start
            if duration >= self.min_squeeze_bars:
                periods.append((start, len(bandwidth) - 1))
        return periods

    def generate_signal(self, df, current_idx=None):
        if len(df) < self.bb_period + 30:
            return None
        if current_idx is None:
            current_idx = len(df) - 1
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        result = self.calculate_bollinger(closes)
        if result[0] is None:
            return None
        upper, sma, lower, bandwidth = result
        atr = self.calculate_atr(highs, lows, closes)
        squeeze_periods = self.find_squeeze_periods(bandwidth)
        if not squeeze_periods:
            return None
        for sq_start, sq_end in reversed(squeeze_periods):
            duration = sq_end - sq_start + 1
            if duration > self.max_squeeze_bars:
                continue
            if sq_end < current_idx - self.lookback:
                continue
            if sq_end >= current_idx:
                continue
            breakout_bar = sq_end + 1
            if breakout_bar >= len(closes):
                continue
            if breakout_bar < current_idx - 2:
                continue
            sq_upper = upper[sq_end]
            sq_lower = lower[sq_end]
            if np.isnan(sq_upper) or np.isnan(sq_lower):
                continue
            breakout_high = highs[breakout_bar]
            breakout_low = lows[breakout_bar]
            breakout_close = closes[breakout_bar]
            direction = None
            if breakout_high > sq_upper * 1.001 and breakout_close > sq_upper * 0.999:
                direction = 'LONG'
            elif breakout_low < sq_lower * 0.999 and breakout_close < sq_lower * 1.001:
                direction = 'SHORT'
            if direction is None:
                continue
            entry_price = breakout_close
            current_atr = atr[breakout_bar] if breakout_bar < len(atr) else atr[-1]
            if current_atr <= 0 or np.isnan(current_atr):
                current_atr = entry_price * 0.02
            if direction == 'LONG':
                stop_loss = entry_price - current_atr * self.atr_sl_mult
                take_profit = entry_price + current_atr * self.atr_tp_mult
            else:
                stop_loss = entry_price + current_atr * self.atr_sl_mult
                take_profit = entry_price - current_atr * self.atr_tp_mult
            duration_factor = min(duration / 15.0, 1.0)
            sq_bandwidth = bandwidth[sq_start:sq_end+1]
            min_bw = np.nanmin(sq_bandwidth) if len(sq_bandwidth) > 0 else self.squeeze_threshold
            depth = max(0, (self.squeeze_threshold - min_bw) / self.squeeze_threshold)
            confidence = 0.50 + (duration_factor * 0.25) + (depth * 0.25)
            confidence = min(confidence, 0.95)
            return SqueezeSignal(
                direction=direction,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=confidence,
                squeeze_bars=duration,
                reason=f"Squeeze {duration}bars -> {direction} breakout"
            )
        return None

    def backtest(self, df, initial_balance=1000.0):
        if len(df) < self.bb_period + 30:
            return {'total_return': 0.0, 'win_rate': 0.0, 'total_trades': 0, 'avg_hold': 0.0, 'trades': []}
        trades = []
        position = None
        cooldown = 0
        for i in range(self.bb_period + 10, len(df)):
            if cooldown > 0:
                cooldown -= 1
                continue
            current_df = df.iloc[:i+1]
            if position is None:
                signal = self.generate_signal(current_df, current_idx=i)
                if signal:
                    position = {
                        'direction': signal.direction,
                        'entry': signal.entry_price,
                        'stop_loss': signal.stop_loss,
                        'take_profit': signal.take_profit,
                        'entry_bar': i,
                        'confidence': signal.confidence,
                        'highest': signal.entry_price,
                        'lowest': signal.entry_price
                    }
            else:
                current_close = df['close'].iloc[i]
                current_high = df['high'].iloc[i]
                current_low = df['low'].iloc[i]
                if position['direction'] == 'LONG':
                    position['highest'] = max(position['highest'], current_high)
                else:
                    position['lowest'] = min(position['lowest'], current_low)
                exit_price = None
                exit_reason = None
                if position['direction'] == 'LONG':
                    if current_low <= position['stop_loss']:
                        exit_price = position['stop_loss']
                        exit_reason = 'stop_loss'
                    elif current_high >= position['take_profit']:
                        exit_price = position['take_profit']
                        exit_reason = 'take_profit'
                else:
                    if current_high >= position['stop_loss']:
                        exit_price = position['stop_loss']
                        exit_reason = 'stop_loss'
                    elif current_low <= position['take_profit']:
                        exit_price = position['take_profit']
                        exit_reason = 'take_profit'
                if exit_price is None and i - position['entry_bar'] > 5:
                    if position['direction'] == 'LONG':
                        trail = position['highest'] * 0.98
                        if current_low <= trail and trail > position['stop_loss']:
                            exit_price = trail
                            exit_reason = 'trailing_stop'
                    else:
                        trail = position['lowest'] * 1.02
                        if current_high >= trail and trail < position['stop_loss']:
                            exit_price = trail
                            exit_reason = 'trailing_stop'
                if i - position['entry_bar'] > 20 and exit_price is None:
                    exit_price = current_close
                    exit_reason = 'timeout'
                if exit_price:
                    if position['direction'] == 'LONG':
                        pnl = (exit_price - position['entry']) / position['entry']
                    else:
                        pnl = (position['entry'] - exit_price) / position['entry']
                    trades.append({
                        'direction': position['direction'],
                        'entry': position['entry'],
                        'exit': exit_price,
                        'pnl': pnl,
                        'hold_bars': i - position['entry_bar'],
                        'reason': exit_reason,
                        'confidence': position['confidence']
                    })
                    position = None
                    cooldown = 3
        if position:
            final_price = df['close'].iloc[-1]
            if position['direction'] == 'LONG':
                pnl = (final_price - position['entry']) / position['entry']
            else:
                pnl = (position['entry'] - final_price) / position['entry']
            trades.append({
                'direction': position['direction'],
                'entry': position['entry'],
                'exit': final_price,
                'pnl': pnl,
                'hold_bars': len(df) - position['entry_bar'],
                'reason': 'end_of_data',
                'confidence': position['confidence']
            })
        if not trades:
            return {'total_return': 0.0, 'win_rate': 0.0, 'total_trades': 0, 'avg_hold': 0.0, 'trades': []}
        total_return = sum(t['pnl'] for t in trades)
        wins = sum(1 for t in trades if t['pnl'] > 0)
        win_rate = (wins / len(trades)) * 100
        avg_hold = sum(t['hold_bars'] for t in trades) / len(trades)
        return {
            'total_return': total_return * 100,
            'win_rate': win_rate,
            'total_trades': len(trades),
            'avg_hold': avg_hold,
            'trades': trades
        }
'''

filepath = os.path.join('strategy', 'bollinger_squeeze.py')
with open(filepath, 'w', encoding='utf-8') as f:
    f.write(code)

print(f'Dosya olusturuldu: {filepath}')
print(f'Boyut: {len(code)} karakter')
