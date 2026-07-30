"""Atlas AI - Strategy Base"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

class SignalType(Enum): BUY = "BUY"; SELL = "SELL"; HOLD = "HOLD"; CLOSE = "CLOSE"
class SignalStrength(Enum): WEAK = 1; MODERATE = 2; STRONG = 3; VERY_STRONG = 4

@dataclass
class Signal:
    symbol: str; signal_type: SignalType; strength: SignalStrength
    price: float; timestamp: datetime; strategy_name: str
    confidence: float; metadata: Dict[str, Any] = None
    def to_dict(self): return {'symbol': self.symbol, 'type': self.signal_type.value, 'strength': self.strength.value, 'price': self.price, 'timestamp': self.timestamp.isoformat(), 'strategy': self.strategy_name, 'confidence': self.confidence, 'metadata': self.metadata or {}}

@dataclass
class StrategyConfig:
    name: str; timeframe: str = "5m"; symbols: List[str] = None
    risk_per_trade: float = 0.02; max_positions: int = 5
    min_confidence: float = 0.6; enabled: bool = True

class StrategyBase(ABC):
    def __init__(self, config: StrategyConfig):
        self.config = config; self.name = config.name; self.timeframe = config.timeframe
        self.symbols = config.symbols or ["BTCUSDT"]; self.risk_per_trade = config.risk_per_trade
        self.max_positions = config.max_positions; self.min_confidence = config.min_confidence
        self.enabled = config.enabled
        self.candles: Dict[str, List[dict]] = {}; self.indicators: Dict[str, dict] = {}
        self.signals_history: List[Signal] = []
        self.stats = {'signals_generated': 0, 'signals_executed': 0, 'winning_signals': 0, 'losing_signals': 0, 'total_pnl': 0.0}
        self._initialized = False

    def initialize(self):
        if not self._initialized: self.on_init(); self._initialized = True; print(f"[Strategy] {self.name} baslatildi")

    @abstractmethod
    def on_init(self): pass

    @abstractmethod
    def on_candle(self, symbol: str, candle: dict) -> Optional[Signal]: pass

    def add_candle(self, symbol: str, candle: dict):
        symbol = symbol.upper()
        if symbol not in self.candles: self.candles[symbol] = []
        self.candles[symbol].append(candle)
        if len(self.candles[symbol]) > 500: self.candles[symbol].pop(0)
        if self.enabled and len(self.candles[symbol]) >= 20:
            signal = self.on_candle(symbol, candle)
            if signal: self.signals_history.append(signal); self.stats['signals_generated'] += 1; return signal
        return None

    def get_closes(self, symbol: str, limit: int = 100):
        candles = self.candles.get(symbol.upper(), [])[-limit:]
        return [c['close'] for c in candles]

    def record_result(self, signal: Signal, pnl: float):
        self.stats['total_pnl'] += pnl
        if pnl > 0: self.stats['winning_signals'] += 1
        else: self.stats['losing_signals'] += 1

    def get_stats(self):
        total = self.stats['winning_signals'] + self.stats['losing_signals']
        return {**self.stats, 'win_rate': (self.stats['winning_signals'] / max(total, 1)) * 100, 'avg_pnl': self.stats['total_pnl'] / max(total, 1), 'name': self.name, 'enabled': self.enabled}
