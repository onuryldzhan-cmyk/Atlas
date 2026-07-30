"""
Atlas AI - Decision Engine v2.0
Karar verme, filtreleme ve risk kontrol motoru.
MODIFY kararları artık APPROVE olarak işleniyor (pozisyon boyutu ayarlı onay).
"""

import json
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import os


class DecisionType(Enum):
    APPROVE = "approve"
    REJECT = "reject"
    HOLD = "hold"
    MODIFY = "modify"


@dataclass
class Signal:
    symbol: str
    action: str
    confidence: float
    strategy: str
    timeframe: str = "5m"
    metadata: Dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Decision:
    signal: Signal
    decision: DecisionType
    reason: str
    modified_signal: Optional[Signal] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            'symbol': self.signal.symbol,
            'action': self.signal.action,
            'confidence': self.signal.confidence,
            'decision': self.decision.value,
            'reason': self.reason,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class Position:
    symbol: str
    action: str
    size: float
    entry_price: float
    confidence: float
    strategy: str
    open_time: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'action': self.action,
            'size': self.size,
            'entry_price': self.entry_price,
            'confidence': self.confidence,
            'strategy': self.strategy,
            'open_time': self.open_time.isoformat()
        }


class DecisionEngine:
    """
    Atlas AI Karar Motoru v2.0
    - Sinyalleri değerlendirir
    - Risk kuralları uygular
    - Pozisyon limitlerini kontrol eder
    - MODIFY kararları APPROVE olarak sayılır (pozisyon boyutu ayarlı onay)
    - Günlük istatistikleri tutar
    """

    def __init__(self, config_path: str = "config/settings.py"):
        self.active = False
        self.positions: Dict[str, Position] = {}
        self.decisions: List[Decision] = []
        self.cooldowns: Dict[str, datetime] = {}

        # İstatistikler
        self.total_evaluated = 0
        self.approved = 0
        self.rejected = 0
        self.held = 0
        self.modified = 0

        # Günlük istatistikler
        self.daily_stats = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'approved': 0,
            'rejected': 0
        }

        # Varsayılan kurallar
        self.rules = {
            'min_confidence': 0.6,
            'max_positions': 10,
            'risk_per_trade': 0.01,
            'max_daily_trades': 20,
            'cooldown_minutes': 15,
            'volatility_threshold': 0.8,
            'portfolio_concentration_limit': 0.3
        }

        self._load_config(config_path)
        self._load_history()

    def _load_config(self, config_path: str):
        try:
            if os.path.exists(config_path):
                import importlib.util
                spec = importlib.util.spec_from_file_location("settings", config_path)
                settings = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(settings)

                if hasattr(settings, 'RISK_PROFILES'):
                    profile = settings.RISK_PROFILES.get('medium', {})
                    self.rules['risk_per_trade'] = profile.get('max_risk_per_trade', 0.01)

                if hasattr(settings, 'MAX_POSITIONS'):
                    self.rules['max_positions'] = settings.MAX_POSITIONS

                if hasattr(settings, 'MAX_DAILY_LOSS'):
                    self.rules['max_daily_loss'] = settings.MAX_DAILY_LOSS

        except Exception as e:
            print(f"⚠️  Config yükleme hatası: {e}")

    def _load_history(self):
        history_file = "logs/decision_history.json"
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    data = json.load(f)
                    self.total_evaluated = data.get('total_evaluated', 0)
                    self.approved = data.get('approved', 0)
                    self.rejected = data.get('rejected', 0)
            except:
                pass

    def _save_history(self):
        try:
            os.makedirs("logs", exist_ok=True)
            history = {
                'total_evaluated': self.total_evaluated,
                'approved': self.approved,
                'rejected': self.rejected,
                'held': self.held,
                'modified': self.modified,
                'last_update': datetime.now().isoformat(),
                'recent_decisions': [d.to_dict() for d in self.decisions[-20:]]
            }
            with open("logs/decision_history.json", 'w') as f:
                json.dump(history, f, indent=2, default=str)
        except Exception as e:
            print(f"❌ Failed to save history: {e}")

    def _check_cooldown(self, symbol: str) -> bool:
        if symbol in self.cooldowns:
            elapsed = datetime.now() - self.cooldowns[symbol]
            if elapsed < timedelta(minutes=self.rules['cooldown_minutes']):
                return False
        return True

    def _check_portfolio_concentration(self, symbol: str) -> bool:
        if not self.positions:
            return True
        same_symbol = sum(1 for p in self.positions.values() if p.symbol == symbol)
        concentration = same_symbol / len(self.positions) if self.positions else 0
        return concentration < self.rules['portfolio_concentration_limit']

    def _check_daily_limit(self) -> bool:
        today = datetime.now().strftime('%Y-%m-%d')
        if self.daily_stats['date'] != today:
            self.daily_stats = {'date': today, 'approved': 0, 'rejected': 0}
        return self.daily_stats['approved'] < self.rules['max_daily_trades']

    def _adjust_position_size(self, signal: Signal) -> Signal:
        confidence = signal.confidence / 100.0

        if confidence >= 0.9:
            size_multiplier = 1.0
            risk_profile = 'high'
        elif confidence >= 0.75:
            size_multiplier = 0.8
            risk_profile = 'medium'
        elif confidence >= 0.6:
            size_multiplier = 0.5
            risk_profile = 'low'
        else:
            size_multiplier = 0.2
            risk_profile = 'minimal'

        max_size = 100 * self.rules['risk_per_trade'] * size_multiplier

        modified = Signal(
            symbol=signal.symbol,
            action=signal.action,
            confidence=signal.confidence,
            strategy=signal.strategy,
            timeframe=signal.timeframe,
            metadata={
                **signal.metadata,
                'size': max_size,
                'size_pct_of_balance': max_size,
                'risk_profile': risk_profile,
                'confidence_multiplier': round(size_multiplier, 2)
            },
            timestamp=signal.timestamp
        )
        return modified

    def evaluate(self, signal: Signal) -> Decision:
        """
        Bir sinyali değerlendir ve karar ver.
        MODIFY kararları da APPROVE olarak sayılır (pozisyon boyutu ayarlı onay).
        """
        self.total_evaluated += 1

        # 1. Minimum güven kontrolü
        confidence = signal.confidence / 100.0
        if confidence < self.rules['min_confidence']:
            self.rejected += 1
            self.daily_stats['rejected'] += 1
            return Decision(
                signal=signal,
                decision=DecisionType.REJECT,
                reason="insufficient_confidence"
            )

        # 2. Cooldown kontrolü
        if not self._check_cooldown(signal.symbol):
            self.held += 1
            return Decision(
                signal=signal,
                decision=DecisionType.HOLD,
                reason="cooldown_active"
            )

        # 3. Maksimum pozisyon kontrolü
        if len(self.positions) >= self.rules['max_positions']:
            self.held += 1
            return Decision(
                signal=signal,
                decision=DecisionType.HOLD,
                reason="max_positions_reached"
            )

        # 4. Günlük limit kontrolü
        if not self._check_daily_limit():
            self.held += 1
            return Decision(
                signal=signal,
                decision=DecisionType.HOLD,
                reason="daily_limit_reached"
            )

        # 5. Volatilite kontrolü
        if signal.metadata.get('volatility', 0) > self.rules['volatility_threshold']:
            self.rejected += 1
            self.daily_stats['rejected'] += 1
            return Decision(
                signal=signal,
                decision=DecisionType.REJECT,
                reason="high_volatility"
            )

        # 6. Pozisyon büyüklüğü ayarı
        modified_signal = self._adjust_position_size(signal)

        # Eğer pozisyon boyutu değiştiyse MODIFY kararı ver ama APPROVE olarak say
        if modified_signal.metadata != signal.metadata:
            self.modified += 1
            self.approved += 1  # MODIFY da APPROVE sayılır
            self.daily_stats['approved'] += 1
            self.cooldowns[signal.symbol] = datetime.now()
            return Decision(
                signal=signal,
                decision=DecisionType.MODIFY,
                reason="position_size_adjusted",
                modified_signal=modified_signal
            )

        # 7. Direkt onayla
        self.approved += 1
        self.daily_stats['approved'] += 1
        self.cooldowns[signal.symbol] = datetime.now()

        return Decision(
            signal=signal,
            decision=DecisionType.APPROVE,
            reason="all_checks_passed"
        )

    def evaluate_batch(self, signals: List[Signal]) -> List[Decision]:
        decisions = []
        for signal in signals:
            decision = self.evaluate(signal)
            decisions.append(decision)
            self.decisions.append(decision)

            emoji = {
                DecisionType.APPROVE: "✅",
                DecisionType.REJECT: "❌",
                DecisionType.HOLD: "⏸️",
                DecisionType.MODIFY: "🔧"
            }
            print(f"\n   Signal: {signal.symbol} {signal.action} (conf: {signal.confidence}%)")
            print(f"   Decision: {decision.decision.value.upper()}")
            print(f"   Reason: {decision.reason}")
            if decision.modified_signal:
                print(f"   Modified: {decision.modified_signal.metadata}")

        return decisions

    def get_stats(self) -> Dict:
        total = self.approved + self.rejected + self.held
        approval_rate = self.approved / total if total > 0 else 0.0

        return {
            'active': self.active,
            'total_evaluated': self.total_evaluated,
            'approved': self.approved,
            'rejected': self.rejected,
            'held': self.held,
            'modified': self.modified,
            'approval_rate': round(approval_rate, 2),
            'open_positions': len(self.positions),
            'cooldowns_active': len(self.cooldowns),
            'daily_stats': self.daily_stats,
            'rules': self.rules
        }

    def get_recent_decisions(self, n: int = 10) -> List[Dict]:
        return [d.to_dict() for d in self.decisions[-n:]]

    def open_position(self, decision: Decision, entry_price: float):
        signal = decision.modified_signal or decision.signal
        position = Position(
            symbol=signal.symbol,
            action=signal.action,
            size=signal.metadata.get('size', 100),
            entry_price=entry_price,
            confidence=signal.confidence,
            strategy=signal.strategy
        )
        self.positions[signal.symbol] = position

    def close_position(self, symbol: str) -> Optional[Position]:
        return self.positions.pop(symbol, None)

    def start(self):
        self.active = True
        print("🔧 Decision Engine v2.0 aktif!")

    def stop(self):
        self.active = False
        self._save_history()
        print("🔒 Decision Engine durduruldu. Geçmiş kaydedildi.")


def test_decision_engine():
    print("🎯 Atlas AI Decision Engine v2.0 - Test Mode")
    print("=" * 50)

    engine = DecisionEngine()

    print("\n📋 Initial Stats:")
    for k, v in engine.get_stats().items():
        print(f"   {k}: {v}")

    test_signals = [
        Signal(symbol="BTCUSDT", action="BUY", confidence=85, strategy="trend_following", metadata={'volatility': 0.5}),
        Signal(symbol="ETHUSDT", action="SELL", confidence=45, strategy="mean_reversion", metadata={'volatility': 0.3}),
        Signal(symbol="SOLUSDT", action="BUY", confidence=92, strategy="momentum", metadata={'volatility': 0.9}),
        Signal(symbol="ADAUSDT", action="BUY", confidence=78, strategy="breakout", metadata={'volatility': 0.4}),
    ]

    print(f"\n🔧 Initializing engine...")
    engine.start()

    print(f"\n📡 Evaluating {len(test_signals)} test signals...")
    print("-" * 50)

    decisions = engine.evaluate_batch(test_signals)

    print("\n" + "=" * 50)
    print("\n📋 Final Stats:")
    for k, v in engine.get_stats().items():
        print(f"   {k}: {v}")

    print("\n📜 Recent Decisions:")
    for d in engine.get_recent_decisions():
        print(f"   {d['symbol']} -> {d['decision'].upper()} | {d['reason']}")

    print("\n🔒 Shutting down...")
    engine.stop()

    print("\n✅ Decision Engine v2.0 test completed!")
    return engine


if __name__ == "__main__":
    test_decision_engine()
