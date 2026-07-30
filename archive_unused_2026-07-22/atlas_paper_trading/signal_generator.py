"""Atlas AI - Signal Generator"""
from typing import List, Dict, Optional, Callable
from datetime import datetime
from collections import deque

from strategy_base import StrategyBase, Signal, SignalType, SignalStrength, StrategyConfig
from indicators import TechnicalIndicators

class RSIStrategy(StrategyBase):
    def __init__(self, config=None, rsi_period=14, oversold=30, overbought=70):
        if config is None: config = StrategyConfig(name="RSI", timeframe="5m")
        super().__init__(config)
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought

    def on_init(self):
        print(f"   [{self.name}] RSI({self.rsi_period}) | Oversold:{self.oversold} | Overbought:{self.overbought}")

    def on_candle(self, symbol, candle):
        closes = self.get_closes(symbol, self.rsi_period + 5)
        if len(closes) < self.rsi_period + 1: return None
        rsi_vals = TechnicalIndicators.rsi(closes, self.rsi_period)
        if not rsi_vals: return None
        curr = rsi_vals[-1]
        prev = rsi_vals[-2] if len(rsi_vals) > 1 else curr
        signal = None
        conf = 0.5
        strength = SignalStrength.MODERATE
        if prev < self.oversold and curr >= self.oversold:
            signal = SignalType.BUY
            conf = min(0.95, 0.6 + (self.oversold - prev) / 100)
            strength = SignalStrength.STRONG if curr < 25 else SignalStrength.MODERATE
        elif prev > self.overbought and curr <= self.overbought:
            signal = SignalType.SELL
            conf = min(0.95, 0.6 + (prev - self.overbought) / 100)
            strength = SignalStrength.STRONG if curr > 75 else SignalStrength.MODERATE
        elif curr < 20:
            signal = SignalType.BUY
            conf = 0.9
            strength = SignalStrength.VERY_STRONG
        elif curr > 80:
            signal = SignalType.SELL
            conf = 0.9
            strength = SignalStrength.VERY_STRONG
        if signal and conf >= self.min_confidence:
            return Signal(symbol=symbol, signal_type=signal, strength=strength, price=candle['close'], timestamp=datetime.now(), strategy_name=self.name, confidence=conf, metadata={'rsi': curr})
        return None

class MACDStrategy(StrategyBase):
    def __init__(self, config=None, fast=12, slow=26, signal=9):
        if config is None: config = StrategyConfig(name="MACD", timeframe="5m")
        super().__init__(config)
        self.fast = fast
        self.slow = slow
        self.signal_period = signal

    def on_init(self):
        print(f"   [{self.name}] MACD({self.fast},{self.slow},{self.signal_period})")

    def on_candle(self, symbol, candle):
        closes = self.get_closes(symbol, self.slow + self.signal_period + 5)
        if len(closes) < self.slow + self.signal_period: return None
        macd_l, sig_l, hist = TechnicalIndicators.macd(closes, self.fast, self.slow, self.signal_period)
        if not macd_l or not sig_l or len(macd_l) < 2: return None
        cross = TechnicalIndicators.crossover(macd_l[-5:], sig_l[-5:])
        under = TechnicalIndicators.crossunder(macd_l[-5:], sig_l[-5:])
        signal = None
        conf = 0.5
        strength = SignalStrength.MODERATE
        if cross:
            signal = SignalType.BUY
            conf = 0.75
            if hist and hist[-1] > 0:
                strength = SignalStrength.STRONG
                conf = 0.85
        elif under:
            signal = SignalType.SELL
            conf = 0.75
            if hist and hist[-1] < 0:
                strength = SignalStrength.STRONG
                conf = 0.85
        if signal and conf >= self.min_confidence:
            return Signal(symbol=symbol, signal_type=signal, strength=strength, price=candle['close'], timestamp=datetime.now(), strategy_name=self.name, confidence=conf, metadata={'macd': macd_l[-1], 'signal': sig_l[-1]})
        return None

class EMAStrategy(StrategyBase):
    def __init__(self, config=None, fast=9, slow=21):
        if config is None: config = StrategyConfig(name="EMA_Cross", timeframe="5m")
        super().__init__(config)
        self.fast = fast
        self.slow = slow

    def on_init(self):
        print(f"   [{self.name}] EMA Crossover({self.fast},{self.slow})")

    def on_candle(self, symbol, candle):
        closes = self.get_closes(symbol, self.slow + 5)
        if len(closes) < self.slow: return None
        ema_f = TechnicalIndicators.ema(closes, self.fast)
        ema_s = TechnicalIndicators.ema(closes, self.slow)
        if len(ema_f) < 2 or len(ema_s) < 2: return None
        diff = len(ema_f) - len(ema_s)
        ef = ema_f[diff:] if diff > 0 else ema_f
        es = ema_s[-diff:] if diff < 0 else ema_s
        if len(ef) < 2 or len(es) < 2: return None
        if TechnicalIndicators.crossover(ef, es):
            conf = 0.85 if ef[-1] > es[-1] * 1.01 else 0.7
            strength = SignalStrength.STRONG if ef[-1] > es[-1] * 1.01 else SignalStrength.MODERATE
            return Signal(symbol=symbol, signal_type=SignalType.BUY, strength=strength, price=candle['close'], timestamp=datetime.now(), strategy_name=self.name, confidence=conf, metadata={'ema_fast': ef[-1], 'ema_slow': es[-1]})
        elif TechnicalIndicators.crossunder(ef, es):
            conf = 0.85 if ef[-1] < es[-1] * 0.99 else 0.7
            strength = SignalStrength.STRONG if ef[-1] < es[-1] * 0.99 else SignalStrength.MODERATE
            return Signal(symbol=symbol, signal_type=SignalType.SELL, strength=strength, price=candle['close'], timestamp=datetime.now(), strategy_name=self.name, confidence=conf, metadata={'ema_fast': ef[-1], 'ema_slow': es[-1]})
        return None

class BollingerStrategy(StrategyBase):
    def __init__(self, config=None, period=20, std_dev=2.0):
        if config is None: config = StrategyConfig(name="Bollinger", timeframe="5m")
        super().__init__(config)
        self.period = period
        self.std_dev = std_dev

    def on_init(self):
        print(f"   [{self.name}] Bollinger({self.period},{self.std_dev})")

    def on_candle(self, symbol, candle):
        closes = self.get_closes(symbol, self.period + 5)
        if len(closes) < self.period: return None
        upper, middle, lower = TechnicalIndicators.bollinger(closes, self.period, self.std_dev)
        if not upper or not lower: return None
        curr = candle['close']
        prev = closes[-2] if len(closes) > 1 else curr
        signal = None
        conf = 0.6
        strength = SignalStrength.MODERATE
        if prev <= lower[-1] and curr > lower[-1]:
            signal = SignalType.BUY
            conf = 0.8
            strength = SignalStrength.STRONG
        elif prev >= upper[-1] and curr < upper[-1]:
            signal = SignalType.SELL
            conf = 0.8
            strength = SignalStrength.STRONG
        elif curr < lower[-1]:
            signal = SignalType.BUY
            conf = 0.65
            strength = SignalStrength.WEAK
        elif curr > upper[-1]:
            signal = SignalType.SELL
            conf = 0.65
            strength = SignalStrength.WEAK
        if signal and conf >= self.min_confidence:
            return Signal(symbol=symbol, signal_type=signal, strength=strength, price=curr, timestamp=datetime.now(), strategy_name=self.name, confidence=conf, metadata={'upper': upper[-1], 'middle': middle[-1], 'lower': lower[-1]})
        return None

class SignalGenerator:
    def __init__(self):
        self.strategies = {}
        self.signals = deque(maxlen=1000)
        self.active_signals = {}
        self.min_total_confidence = 0.6
        self.min_strategies_agree = 2
        self.cooldown_minutes = 15
        self.last_signal_time = {}
        self.signal_callbacks = []

    def add_strategy(self, strategy):
        strategy.initialize()
        self.strategies[strategy.name] = strategy
        print(f"[SignalGen] Strateji eklendi: {strategy.name}")

    def process_candle(self, symbol, candle):
        symbol = symbol.upper()
        all_signals = []
        for strategy in self.strategies.values():
            signal = strategy.add_candle(symbol, candle)
            if signal:
                all_signals.append(signal)
        if not all_signals:
            return None
        combined = self._combine_signals(all_signals, symbol, candle['close'])
        if combined:
            self.signals.append(combined)
            self.active_signals[symbol] = combined
            for cb in self.signal_callbacks:
                cb(combined)
            return combined
        return None

    def _combine_signals(self, signals, symbol, price):
        last = self.last_signal_time.get(symbol)
        if last and (datetime.now() - last).total_seconds() / 60 < self.cooldown_minutes:
            return None
        buy_s = [s for s in signals if s.signal_type == SignalType.BUY]
        sell_s = [s for s in signals if s.signal_type == SignalType.SELL]
        if len(buy_s) >= self.min_strategies_agree and len(buy_s) > len(sell_s):
            return self._create_combined(buy_s, SignalType.BUY, symbol, price)
        elif len(sell_s) >= self.min_strategies_agree and len(sell_s) > len(buy_s):
            return self._create_combined(sell_s, SignalType.SELL, symbol, price)
        return None

    def _create_combined(self, signals, signal_type, symbol, price):
        avg_conf = sum(s.confidence for s in signals) / len(signals)
        if avg_conf < self.min_total_confidence:
            return None
        max_str = max(signals, key=lambda s: s.strength.value).strength
        names = [s.strategy_name for s in signals]
        self.last_signal_time[symbol] = datetime.now()
        print(f"\n🎯 SINYAL: {signal_type.value} {symbol} @ ${price:,.2f}")
        print(f"   Confidence: {avg_conf:.2f} | Strength: {max_str.name}")
        print(f"   Stratejiler: {', '.join(names)}")
        return Signal(symbol=symbol, signal_type=signal_type, strength=max_str, price=price, timestamp=datetime.now(), strategy_name=f"Combined({','.join(names)})", confidence=avg_conf, metadata={'strategies': names, 'count': len(signals)})

    def get_strategy_stats(self):
        return {name: s.get_stats() for name, s in self.strategies.items()}
