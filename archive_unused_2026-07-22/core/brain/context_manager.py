"""
Atlas AI - Context Manager Module
Piyasa baglamini yonet - atlas_brain.py'den ayrildi
"""
from datetime import datetime
from typing import Dict, List
from enum import Enum

class MarketRegime(Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"

class ContextManager:
    """Piyasa durumunu ve baglami yonet"""

    def __init__(self):
        self.current_regime = MarketRegime.UNKNOWN
        self.regime_history = []
        self.volatility_threshold = 0.02  # %2
        self.trend_threshold = 0.05  # %5

    def detect_regime(self, price_data: List[float]) -> MarketRegime:
        """Piyasa rejimini tespit et"""
        if len(price_data) < 20:
            return MarketRegime.UNKNOWN

        # Volatilite hesapla
        returns = [(price_data[i] - price_data[i-1]) / price_data[i-1] 
                   for i in range(1, len(price_data))]
        volatility = sum(r**2 for r in returns) / len(returns)

        # Trend hesapla
        total_change = (price_data[-1] - price_data[0]) / price_data[0]

        if volatility > self.volatility_threshold:
            regime = MarketRegime.VOLATILE
        elif total_change > self.trend_threshold:
            regime = MarketRegime.TRENDING_UP
        elif total_change < -self.trend_threshold:
            regime = MarketRegime.TRENDING_DOWN
        else:
            regime = MarketRegime.RANGING

        self.current_regime = regime
        self.regime_history.append({
            "regime": regime.value,
            "timestamp": datetime.now().isoformat(),
            "volatility": volatility,
            "trend": total_change
        })

        return regime

    def get_regime_stats(self) -> Dict:
        """Rejim istatistikleri"""
        if not self.regime_history:
            return {}

        regimes = [r["regime"] for r in self.regime_history]
        return {
            "current": self.current_regime.value,
            "history_count": len(self.regime_history),
            "most_common": max(set(regimes), key=regimes.count) if regimes else "unknown"
        }

    def should_trade(self) -> bool:
        """Su an islem yapilmali mi?"""
        if self.current_regime == MarketRegime.VOLATILE:
            return False  # Volatilitede islem yapma
        if self.current_regime == MarketRegime.UNKNOWN:
            return False
        return True

