"""
Atlas AI - Scalping Strategy Module
Kisa vadeli hizli islem stratejisi
"""
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class ScalpingSignal:
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    reason: str

class ScalpingStrategy:
    """
    Scalping Stratejisi:
    - Kucuk fiyat hareketlerinden kar elde etme
    - Hizli giris/cikis
    - Siki stop-loss
    """

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.min_profit_ticks = self.config.get("min_profit_ticks", 5)
        self.max_hold_time = self.config.get("max_hold_time", 300)  # 5 dakika
        self.risk_reward = self.config.get("risk_reward", 1.5)
        self.min_volume = self.config.get("min_volume", 1000)

    def analyze(self, candles: List[Dict]) -> Optional[ScalpingSignal]:
        """Son mumlari analiz et ve sinyal uret"""
        if len(candles) < 5:
            return None

        latest = candles[-1]
        prev = candles[-2]

        # Hacim kontrolu
        if latest.get("volume", 0) < self.min_volume:
            return None

        # Fiyat hareketi
        price_change = (latest["close"] - prev["close"]) / prev["close"]

        # EMA5 / EMA10 kesişimi
        closes = [c["close"] for c in candles]
        ema5 = self._ema(closes, 5)
        ema10 = self._ema(closes, 10)

        if ema5 is None or ema10 is None:
            return None

        # Long sinyali
        if ema5 > ema10 and price_change > 0.001:
            sl = latest["close"] * 0.998
            tp = latest["close"] * 1.003
            return ScalpingSignal(
                direction="LONG",
                entry_price=latest["close"],
                stop_loss=sl,
                take_profit=tp,
                confidence=min(1.0, abs(price_change) * 100),
                reason=f"EMA5({ema5:.2f})>EMA10({ema10:.2f}), Hacim:{latest.get('volume',0):.0f}"
            )

        # Short sinyali
        elif ema5 < ema10 and price_change < -0.001:
            sl = latest["close"] * 1.002
            tp = latest["close"] * 0.997
            return ScalpingSignal(
                direction="SHORT",
                entry_price=latest["close"],
                stop_loss=sl,
                take_profit=tp,
                confidence=min(1.0, abs(price_change) * 100),
                reason=f"EMA5({ema5:.2f})<EMA10({ema10:.2f}), Hacim:{latest.get('volume',0):.0f}"
            )

        return None

    def _ema(self, prices: List[float], period: int) -> Optional[float]:
        """EMA hesapla"""
        if len(prices) < period:
            return None
        alpha = 2 / (period + 1)
        ema = np.mean(prices[:period])
        for p in prices[period:]:
            ema = alpha * p + (1 - alpha) * ema
        return ema

    def get_stats(self) -> Dict:
        """Strateji istatistikleri"""
        return {
            "name": "Scalping",
            "min_profit_ticks": self.min_profit_ticks,
            "max_hold_time": self.max_hold_time,
            "risk_reward": self.risk_reward,
            "min_volume": self.min_volume
        }

