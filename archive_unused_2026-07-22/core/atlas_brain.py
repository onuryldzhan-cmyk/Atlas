"""
Atlas AI Brain v2 - Ana Kontrol Motoru
Tum modulleri birlestiren, karar alan ve yoneten merkezi beyin

Entegre Moduller:
- Pattern Memory (Asama 4) - Ogrenmis patternler
- Market Regime (Asama 5) - Piyasa durumu tespiti
- Risk Manager - Risk yonetimi
- Signal Fusion - Sinyal birlestirme
- Execution Engine - Islem yonetimi
- GitHub Integration - Versiyon kontrolu
- Background Service - Dosya analizi
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Modul importlari
try:
    from ai.pattern_memory import PatternMemory
    PATTERN_MEMORY_AVAILABLE = True
except ImportError:
    PATTERN_MEMORY_AVAILABLE = False
    print("[WARNING] Pattern Memory modulu bulunamadi")

try:
    from github.github_integration import AtlasGitHubManager
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False

class MarketRegimeDetector:
    """Asama 5: Piyasa durumunu tespit et"""

    def __init__(self):
        self.current_regime = "UNKNOWN"
        self.regime_history = []

    def detect(self, prices: List[float], volumes: List[float]) -> Dict:
        """Piyasa rejimini tespit et"""
        if len(prices) < 50:
            return {"regime": "UNKNOWN", "confidence": 0}

        # Trend hesapla
        sma20 = sum(prices[-20:]) / 20
        sma50 = sum(prices[-50:]) / 50

        # Volatilite
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        volatility = sum(r**2 for r in returns[-20:]) / 20

        # Hacim trendi
        avg_volume = sum(volumes[-20:]) / 20 if volumes else 0
        recent_volume = sum(volumes[-5:]) / 5 if volumes else 0
        volume_spike = recent_volume > avg_volume * 1.5 if avg_volume > 0 else False

        # Rejim belirle
        if volatility > 0.0004:  # Yuksek volatilite
            regime = "VOLATILE"
            confidence = min(1.0, volatility / 0.001)
        elif abs(sma20 - sma50) / sma50 > 0.02:  # Guclu trend
            regime = "TRENDING_UP" if sma20 > sma50 else "TRENDING_DOWN"
            confidence = min(1.0, abs(sma20 - sma50) / sma50 / 0.05)
        else:
            regime = "RANGING"
            confidence = 0.7

        self.current_regime = regime
        self.regime_history.append({
            "timestamp": datetime.now().isoformat(),
            "regime": regime,
            "confidence": confidence,
            "volatility": volatility,
            "sma20": sma20,
            "sma50": sma50
        })

        return {
            "regime": regime,
            "confidence": confidence,
            "volatility": volatility,
            "volume_spike": volume_spike,
            "recommendation": self._get_recommendation(regime)
        }

    def _get_recommendation(self, regime: str) -> str:
        """Rejime gore oneri"""
        recommendations = {
            "TRENDING_UP": "Trend takip stratejileri kullan (Breakout, Momentum)",
            "TRENDING_DOWN": "Short pozisyonlar veya bekle",
            "RANGING": "Mean reversion stratejileri kullan (RSI, BB)",
            "VOLATILE": "Pozisyon kucult veya bekle, yuksek volatilite",
            "UNKNOWN": "Yeterli veri yok, bekle"
        }
        return recommendations.get(regime, "Bekle")


class AtlasBrainV2:
    """Atlas AI Brain v2 - Ana kontrol motoru"""

    def __init__(self):
        self.version = "2.0.0"
        self.start_time = datetime.now()

        # Modulleri baslat
        self.pattern_memory = PatternMemory() if PATTERN_MEMORY_AVAILABLE else None
        self.regime_detector = MarketRegimeDetector()
        self.github = AtlasGitHubManager() if GITHUB_AVAILABLE else None

        # Durum
        self.state = {
            "status": "INITIALIZING",
            "mode": "SIMULATION",  # SIMULATION, PAPER, LIVE
            "active_strategy": None,
            "last_signal": None,
            "total_trades_today": 0,
            "daily_pnl": 0
        }

        print(f"[BRAIN v2] Atlas AI Brain v{self.version} baslatildi")
        print(f"[BRAIN v2] Moduller: PatternMemory={PATTERN_MEMORY_AVAILABLE}, GitHub={GITHUB_AVAILABLE}")

    def process_market_data(self, data: Dict) -> Dict:
        """
        Piyasa verisini isle ve karar al

        data: {
            "symbol": "BTCUSDT",
            "prices": [...],
            "highs": [...],
            "lows": [...],
            "volumes": [...],
            "current_price": 65000,
            "timestamp": "..."
        }
        """
        print(f"\n[BRAIN] {data['symbol']} isleniyor...")

        # 1. Piyasa rejimini tespit et
        regime = self.regime_detector.detect(data["prices"], data.get("volumes", []))
        print(f"[REGIME] {regime['regime']} (Guven: {regime['confidence']:.0%})")
        print(f"[REGIME] Oneri: {regime['recommendation']}")

        # 2. Sinyal uret (basit ornek)
        signal = self._generate_signal(data, regime)

        # 3. Pattern Memory ile dogrula
        if self.pattern_memory and signal["direction"] != 0:
            should_trade, confidence, reason = self.pattern_memory.should_take_signal(
                signal, {"trend": regime["regime"]}
            )
            signal["pattern_confidence"] = confidence
            signal["pattern_reason"] = reason

            if not should_trade:
                print(f"[PATTERN] Sinyal REDDEDILDI: {reason}")
                signal["direction"] = 0
            else:
                print(f"[PATTERN] Sinyal ONAYLANDI: {reason} (Guven: {confidence:.0%})")

        # 4. Risk kontrolu
        signal = self._apply_risk_management(signal)

        self.state["last_signal"] = signal
        return signal

    def _generate_signal(self, data: Dict, regime: Dict) -> Dict:
        """Basit sinyal uretici"""
        prices = data["prices"]
        if len(prices) < 20:
            return {"direction": 0, "reason": "Yetersiz veri"}

        # RSI benzeri basit osilatör
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c < 0]

        avg_gain = sum(gains[-14:]) / 14 if gains else 0
        avg_loss = sum(losses[-14:]) / 14 if losses else 0

        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        # Bollinger pozisyonu
        sma20 = sum(prices[-20:]) / 20
        std = (sum((p - sma20)**2 for p in prices[-20:]) / 20) ** 0.5
        bb_lower = sma20 - 2 * std
        bb_upper = sma20 + 2 * std

        current = prices[-1]

        # Sinyal karar
        if rsi < 35 and current < bb_lower * 1.01:
            return {
                "direction": 1,
                "reason": f"RSI:{rsi:.1f} + BB alt bandi",
                "entry_price": current,
                "confidence": 0.7,
                "regime": regime["regime"]
            }
        elif rsi > 65 and current > bb_upper * 0.99:
            return {
                "direction": -1,
                "reason": f"RSI:{rsi:.1f} + BB ust bandi",
                "entry_price": current,
                "confidence": 0.7,
                "regime": regime["regime"]
            }

        return {"direction": 0, "reason": f"RSI:{rsi:.1f}, BB orta"}

    def _apply_risk_management(self, signal: Dict) -> Dict:
        """Risk yonetimi uygula"""
        if signal["direction"] == 0:
            return signal

        # Gunluk limit kontrolu
        if self.state["total_trades_today"] >= 5:
            print("[RISK] Gunluk islem limitine ulasildi (5)")
            signal["direction"] = 0
            signal["reason"] += " [RISK: Gunluk limit]"
            return signal

        # Gunluk kayip kontrolu
        if self.state["daily_pnl"] < -500:  # 500 USDT kayip
            print("[RISK] Gunluk kayip limitine ulasildi")
            signal["direction"] = 0
            signal["reason"] += " [RISK: Gunluk kayip limiti]"
            return signal

        # Stop-loss ve take-profit ekle
        entry = signal["entry_price"]
        signal["stop_loss"] = entry * 0.98 if signal["direction"] == 1 else entry * 1.02
        signal["take_profit"] = entry * 1.04 if signal["direction"] == 1 else entry * 0.96
        signal["position_size"] = 0.1  # Bakiyenin %10'u

        return signal

    def execute_signal(self, signal: Dict) -> Dict:
        """Sinyali calistir (simulasyon)"""
        if signal["direction"] == 0:
            return {"status": "NO_TRADE", "reason": signal.get("reason", "")}

        self.state["total_trades_today"] += 1

        trade = {
            "timestamp": datetime.now().isoformat(),
            "side": "LONG" if signal["direction"] == 1 else "SHORT",
            "entry_price": signal["entry_price"],
            "stop_loss": signal.get("stop_loss"),
            "take_profit": signal.get("take_profit"),
            "position_size": signal.get("position_size"),
            "reason": signal["reason"],
            "regime": signal.get("regime"),
            "pattern_confidence": signal.get("pattern_confidence", 0)
        }

        print(f"[EXECUTE] {trade['side']} @ {trade['entry_price']:.2f}")
        print(f"[EXECUTE] SL: {trade['stop_loss']:.2f} | TP: {trade['take_profit']:.2f}")

        return {"status": "EXECUTED", "trade": trade}

    def get_status(self) -> Dict:
        """Brain durumunu raporla"""
        uptime = (datetime.now() - self.start_time).total_seconds()

        return {
            "version": self.version,
            "uptime_seconds": int(uptime),
            "state": self.state,
            "regime": self.regime_detector.current_regime,
            "pattern_memory_loaded": self.pattern_memory is not None,
            "modules": {
                "pattern_memory": PATTERN_MEMORY_AVAILABLE,
                "github": GITHUB_AVAILABLE
            }
        }

    def print_dashboard(self):
        """Konsol dashboard'u goster"""
        status = self.get_status()

        print("\n" + "="*60)
        print("ATLAS AI BRAIN v2 - DASHBOARD")
        print("="*60)
        print(f"Versiyon: {status['version']}")
        print(f"Calisma suresi: {status['uptime_seconds']} saniye")
        print(f"Mod: {status['state']['mode']}")
        print(f"Aktif rejim: {status['regime']}")
        print(f"Gunluk islem: {status['state']['total_trades_today']}/5")
        print(f"Gunluk PnL: {status['state']['daily_pnl']:.2f} USDT")
        print(f"Moduller: Pattern={status['modules']['pattern_memory']}, GitHub={status['modules']['github']}")
        print("="*60)


def demo_run():
    """Brain v2 demo calistir"""
    print("="*60)
    print("ATLAS AI BRAIN v2 - DEMO")
    print("="*60)

    brain = AtlasBrainV2()

    # Ornek piyasa verisi
    import random
    random.seed(42)

    base_price = 65000
    prices = [base_price]
    for i in range(100):
        change = random.gauss(0, 0.008)
        prices.append(prices[-1] * (1 + change))

    volumes = [random.gauss(1000, 200) for _ in range(100)]

    market_data = {
        "symbol": "BTCUSDT",
        "prices": prices,
        "highs": [p * 1.005 for p in prices],
        "lows": [p * 0.995 for p in prices],
        "volumes": volumes,
        "current_price": prices[-1],
        "timestamp": datetime.now().isoformat()
    }

    # Islem dongusu
    for i in range(3):
        print(f"\n[LOOP {i+1}/3]")

        # Son 50 mumu guncelle
        market_data["prices"] = prices[i*10:i*10+50]
        market_data["volumes"] = volumes[i*10:i*10+50]
        market_data["current_price"] = prices[i*10+49]

        # Isle
        signal = brain.process_market_data(market_data)
        result = brain.execute_signal(signal)

        time.sleep(0.5)

    # Dashboard goster
    brain.print_dashboard()

    print("\n[DEMO] Tamamlandi!")


if __name__ == "__main__":
    demo_run()
