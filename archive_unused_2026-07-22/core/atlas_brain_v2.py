"""
Atlas AI Brain v2.2 - Risk Profili Entegrasyonu

Risk Profilleri:
- LOW:    Korunmak, az islem, kucuk pozisyon, uzun SL
- MEDIUM: Dengeli, orta islem, orta pozisyon, standart SL
- HIGH:   Agresif, cok islem, buyuk pozisyon, kisa SL

Her profile gore:
- Farkli strateji secimi
- Farkli pozisyon buyuklugu
- Farkli SL/TP oranlari
- Farkli islem limitleri
"""
import json
import os
import sys
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from ai.pattern_memory import PatternMemory
    PATTERN_MEMORY_AVAILABLE = True
except ImportError:
    PATTERN_MEMORY_AVAILABLE = False


class RiskProfile:
    """Risk profili yapilandirmasi"""

    PROFILES = {
        "LOW": {
            "name": "Dusuk Risk",
            "description": "Korunmak isteyenler icin",
            "position_size": 0.05,      # Bakiyenin %5'i
            "max_positions": 1,         # Ayni anda 1 pozisyon
            "max_daily_trades": 2,      # Gunde max 2 islem
            "max_daily_loss_pct": 0.02, # Gunde max %2 kayip
            "stop_loss_pct": 0.015,     # %1.5 SL
            "take_profit_pct": 0.03,    # %3 TP
            "min_confidence": 0.75,     # Min %75 guven
            "allowed_strategies": ["Mean Reversion", "Support Resistance"],
            "trailing_stop": True,
            "cooldown_candles": 10
        },
        "MEDIUM": {
            "name": "Orta Risk",
            "description": "Dengeli getiri icin",
            "position_size": 0.10,      # Bakiyenin %10'u
            "max_positions": 2,         # Ayni anda 2 pozisyon
            "max_daily_trades": 5,      # Gunde max 5 islem
            "max_daily_loss_pct": 0.05, # Gunde max %5 kayip
            "stop_loss_pct": 0.02,      # %2 SL
            "take_profit_pct": 0.05,    # %5 TP
            "min_confidence": 0.60,     # Min %60 guven
            "allowed_strategies": ["Mean Reversion", "Trend Following", "Momentum", "Breakout"],
            "trailing_stop": True,
            "cooldown_candles": 5
        },
        "HIGH": {
            "name": "Yuksek Risk",
            "description": "Agresif kazanc icin",
            "position_size": 0.20,      # Bakiyenin %20'si
            "max_positions": 3,         # Ayni anda 3 pozisyon
            "max_daily_trades": 10,     # Gunde max 10 islem
            "max_daily_loss_pct": 0.10, # Gunde max %10 kayip
            "stop_loss_pct": 0.025,     # %2.5 SL
            "take_profit_pct": 0.08,    # %8 TP
            "min_confidence": 0.50,     # Min %50 guven
            "allowed_strategies": ["Trend Following", "Momentum", "Breakout", "Scalping", "Bollinger Squeeze"],
            "trailing_stop": False,
            "cooldown_candles": 2
        }
    }

    def __init__(self, profile: str = "MEDIUM"):
        self.profile_name = profile.upper()
        self.config = self.PROFILES.get(self.profile_name, self.PROFILES["MEDIUM"])

    def get_config(self) -> Dict:
        return self.config

    def is_strategy_allowed(self, strategy_name: str) -> bool:
        """Bu strateji bu profile uygun mu?"""
        allowed = self.config["allowed_strategies"]
        return any(a.lower() in strategy_name.lower() for a in allowed)

    def meets_confidence(self, confidence: float) -> bool:
        """Guven seviyesi yeterli mi?"""
        return confidence >= self.config["min_confidence"]


class StrategySelector:
    """Risk profiline gore strateji secimi"""

    STRATEGIES = {
        "Mean Reversion": {
            "indicators": ["rsi", "bollinger"],
            "signal_fn": lambda p, c: p["rsi"] < 35 and c < p["bb_lower"] * 1.01,
            "direction": 1,
            "description": "RSI asiri satim + BB alt bandi"
        },
        "Trend Following": {
            "indicators": ["ema20", "ema50", "adx"],
            "signal_fn": lambda p, c: p["ema20"] > p["ema50"] and p["adx"] > 25,
            "direction": 1,
            "description": "EMA20>EMA50 + Guclu trend"
        },
        "Momentum": {
            "indicators": ["rsi", "macd"],
            "signal_fn": lambda p, c: p["rsi"] > 50 and p["macd"] > 0,
            "direction": 1,
            "description": "RSI momentum + MACD pozitif"
        },
        "Breakout": {
            "indicators": ["high_20", "volume"],
            "signal_fn": lambda p, c: c > p["high_20"] and p["volume"] > p["avg_volume"] * 1.5,
            "direction": 1,
            "description": "20 mumluk zirve kirilimi + Hacim"
        },
        "Scalping": {
            "indicators": ["ema5", "ema10"],
            "signal_fn": lambda p, c: p["ema5"] > p["ema10"] * 1.001,
            "direction": 1,
            "description": "EMA5>EMA10 hizli kesisim"
        }
    }

    def __init__(self, risk_profile: RiskProfile):
        self.risk = risk_profile
        self.available_strategies = []
        self._load_strategies()

    def _load_strategies(self):
        """Profile uygun stratejileri yukle"""
        for name, config in self.STRATEGIES.items():
            if self.risk.is_strategy_allowed(name):
                self.available_strategies.append((name, config))
        print(f"[STRATEGY] {self.risk.profile_name} profili icin {len(self.available_strategies)} strateji yuklendi")

    def select_strategy(self, market_data: Dict) -> Optional[Dict]:
        """Piyasa durumuna gore en uygun stratejiyi sec"""
        prices = market_data.get("prices", [])
        if len(prices) < 50:
            return None

        current = prices[-1]

        # Gostergeleri hesapla
        params = self._calculate_indicators(prices, market_data.get("volumes", []))

        # Stratejileri test et
        for name, config in self.available_strategies:
            if config["signal_fn"](params, current):
                return {
                    "name": name,
                    "direction": config["direction"],
                    "description": config["description"],
                    "confidence": 0.7,  # Basit guven
                    "params": params
                }

        return None

    def _calculate_indicators(self, prices: List[float], volumes: List[float]) -> Dict:
        """Teknik gostergeleri hesapla"""
        # RSI
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [c for c in changes[-14:] if c > 0]
        losses = [abs(c) for c in changes[-14:] if c < 0]
        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        rsi = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))

        # Bollinger
        sma20 = sum(prices[-20:]) / 20
        std = (sum((p - sma20)**2 for p in prices[-20:]) / 20) ** 0.5

        # EMA
        ema20 = self._ema(prices, 20)
        ema50 = self._ema(prices, 50)
        ema5 = self._ema(prices, 5)
        ema10 = self._ema(prices, 10)

        # High/Low
        high_20 = max(prices[-20:])

        # Volume
        avg_volume = sum(volumes[-20:]) / 20 if volumes else 0

        return {
            "rsi": rsi,
            "bb_lower": sma20 - 2 * std,
            "bb_upper": sma20 + 2 * std,
            "ema5": ema5,
            "ema10": ema10,
            "ema20": ema20,
            "ema50": ema50,
            "high_20": high_20,
            "volume": volumes[-1] if volumes else 0,
            "avg_volume": avg_volume,
            "adx": 30  # Basit varsayim
        }

    def _ema(self, prices: List[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0
        alpha = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for p in prices[period:]:
            ema = alpha * p + (1 - alpha) * ema
        return ema


class AtlasBrainV2:
    """Atlas AI Brain v2.2 - Risk Profilli"""

    def __init__(self, risk_profile: str = "MEDIUM"):
        self.version = "2.2.0"
        self.start_time = datetime.now()

        # Risk profili
        self.risk = RiskProfile(risk_profile)
        self.strategy_selector = StrategySelector(self.risk)

        # Moduller
        self.pattern_memory = PatternMemory() if PATTERN_MEMORY_AVAILABLE else None

        # Durum
        self.state = {
            "status": "ACTIVE",
            "mode": "SIMULATION",
            "risk_profile": risk_profile,
            "total_trades_today": 0,
            "daily_loss": 0,
            "positions": [],
            "trades": []
        }

        print(f"[BRAIN v{self.version}] Risk Profili: {self.risk.config['name']}")
        print(f"[BRAIN] Pozisyon: {self.risk.config['position_size']*100:.0f}% | Max: {self.risk.config['max_positions']} | Gunluk: {self.risk.config['max_daily_trades']}")

    def process(self, market_data: Dict) -> Dict:
        """Piyasa verisini isle ve karar al"""
        print(f"\n[BRAIN] {market_data['symbol']} @ {market_data['current_price']:.2f}")
        print(f"[PROFILE] {self.risk.config['name']} | Gunluk: {self.state['total_trades_today']}/{self.risk.config['max_daily_trades']}")

        # 1. Strateji sec
        strategy = self.strategy_selector.select_strategy(market_data)

        if not strategy:
            print("[SIGNAL] BEKLE - Uygun strateji bulunamadi")
            return {"direction": 0, "reason": "Uygun strateji yok"}

        print(f"[STRATEGY] {strategy['name']} | {strategy['description']}")

        # 2. Guven kontrolu
        if not self.risk.meets_confidence(strategy['confidence']):
            print(f"[RISK] Guven yetersiz: {strategy['confidence']:.0%} < {self.risk.config['min_confidence']:.0%}")
            return {"direction": 0, "reason": "Dusuk guven"}

        # 3. Gunluk limit kontrolu
        if self.state['total_trades_today'] >= self.risk.config['max_daily_trades']:
            print(f"[RISK] Gunluk limit doldu")
            return {"direction": 0, "reason": "Gunluk limit"}

        # 4. Pozisyon limiti
        if len(self.state['positions']) >= self.risk.config['max_positions']:
            print(f"[RISK] Max pozisyon: {len(self.state['positions'])}/{self.risk.config['max_positions']}")
            return {"direction": 0, "reason": "Max pozisyon"}

        # 5. Signal olustur
        signal = self._create_signal(strategy, market_data['current_price'])

        # 6. Pattern Memory dogrula
        if self.pattern_memory:
            should_trade, conf, reason = self.pattern_memory.should_take_signal(signal, {})
            if not should_trade:
                print(f"[PATTERN] RED: {reason}")
                return {"direction": 0, "reason": f"Pattern: {reason}"}
            print(f"[PATTERN] ONAY: {reason}")

        return signal

    def _create_signal(self, strategy: Dict, current_price: float) -> Dict:
        """Sinyal olustur"""
        cfg = self.risk.config

        sl = current_price * (1 - cfg['stop_loss_pct']) if strategy['direction'] == 1 else current_price * (1 + cfg['stop_loss_pct'])
        tp = current_price * (1 + cfg['take_profit_pct']) if strategy['direction'] == 1 else current_price * (1 - cfg['take_profit_pct'])

        return {
            "direction": strategy['direction'],
            "strategy": strategy['name'],
            "reason": strategy['description'],
            "entry_price": current_price,
            "stop_loss": sl,
            "take_profit": tp,
            "position_size": cfg['position_size'],
            "confidence": strategy['confidence'],
            "trailing_stop": cfg['trailing_stop']
        }

    def execute(self, signal: Dict) -> Dict:
        """Sinyali calistir"""
        if signal.get("direction", 0) == 0:
            return {"status": "NO_TRADE"}

        self.state['total_trades_today'] += 1

        trade = {
            "timestamp": datetime.now().isoformat(),
            "side": "LONG" if signal['direction'] == 1 else "SHORT",
            "strategy": signal.get('strategy', 'Unknown'),
            "entry": signal['entry_price'],
            "sl": signal['stop_loss'],
            "tp": signal['take_profit'],
            "size": signal['position_size'],
            "confidence": signal.get('confidence', 0)
        }

        self.state['trades'].append(trade)
        self.state['positions'].append(trade)

        print(f"[EXECUTE] === {trade['side']} | {trade['strategy']} ===")
        print(f"[EXECUTE] Entry: {trade['entry']:.2f} | SL: {trade['sl']:.2f} | TP: {trade['tp']:.2f}")
        print(f"[EXECUTE] Size: {trade['size']*100:.0f}% | Guven: {trade['confidence']:.0%}")

        return {"status": "EXECUTED", "trade": trade}

    def print_dashboard(self):
        print("\n" + "="*60)
        print(f"ATLAS AI BRAIN v{self.version} - DASHBOARD")
        print("="*60)
        print(f"Profil: {self.risk.config['name']} ({self.state['risk_profile']})")
        print(f"Calisma: {int((datetime.now()-self.start_time).total_seconds())} sn")
        print(f"Gunluk: {self.state['total_trades_today']}/{self.risk.config['max_daily_trades']} islem")
        print(f"Aktif: {len(self.state['positions'])} pozisyon")
        print(f"Toplam: {len(self.state['trades'])} islem")
        if self.state['trades']:
            t = self.state['trades'][-1]
            print(f"Son: {t['side']} {t['strategy']} @ {t['entry']:.2f}")
        print("="*60)


def demo_all_profiles():
    """Tum risk profillerini demo et"""
    print("="*60)
    print("ATLAS AI BRAIN v2.2 - RISK PROFILI DEMO")
    print("="*60)

    # Veri hazirla
    random.seed(42)
    prices = [65000]
    for _ in range(200):
        prices.append(prices[-1] * (1 + random.gauss(0, 0.008)))

    market_data = {
        "symbol": "BTCUSDT",
        "prices": prices,
        "volumes": [random.gauss(1000, 200) for _ in range(200)],
        "current_price": prices[-1]
    }

    # Her profili test et
    for profile in ["LOW", "MEDIUM", "HIGH"]:
        print(f"\n{'='*60}")
        print(f"[PROFILE TEST] {profile}")
        print(f"{'='*60}")

        brain = AtlasBrainV2(profile)

        for i in range(3):
            window = {
                "symbol": market_data["symbol"],
                "prices": market_data["prices"][i*20:i*20+100],
                "volumes": market_data["volumes"][i*20:i*20+100],
                "current_price": market_data["prices"][i*20+99]
            }

            signal = brain.process(window)
            brain.execute(signal)
            time.sleep(0.2)

        brain.print_dashboard()

    print("\n[DEMO] Tum profiller tamamlandi!")
    print("\n[OZET]")
    print("  LOW:    Az islem, yuksek guven, kucuk pozisyon")
    print("  MEDIUM: Dengeli, orta guven, orta pozisyon")
    print("  HIGH:   Cok islem, dusuk guven, buyuk pozisyon")


if __name__ == "__main__":
    demo_all_profiles()

