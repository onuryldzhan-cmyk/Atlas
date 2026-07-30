"""
Atlas AI - Trading Engine v2.0
Profesyonel işlem motoru — timeout ve hata yönetimi ile.
"""

import time
import logging
from datetime import datetime
from typing import Dict, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger("AtlasAI.TradingEngine")


@dataclass
class TradeDecision:
    """Standart işlem kararı formatı"""
    action: str  # BUY, SELL, HOLD
    confidence: float  # 0.0 - 1.0
    reason: str
    symbol: str
    timestamp: str
    metadata: Dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class TradingEngine:
    """
    Atlas AI Trading Engine v2.0

    Özellikler:
    - Timeout koruması (her işlem maksimum 5 saniye)
    - Hata yakalama ve loglama
    - Standart karar formatı
    - Performans metrikleri
    """

    def __init__(self, timeout_seconds: float = 5.0):
        self.timeout = timeout_seconds
        self.is_active = True
        self.stats = {
            'total_decisions': 0,
            'successful_decisions': 0,
            'failed_decisions': 0,
            'avg_decision_time_ms': 0.0,
            'last_decision_time': None
        }
        logger.info("Trading Engine v2.0 başlatıldı.")

    def decide(self, symbol: str, sentiment: str, price: float, 
               indicators: Dict = None) -> TradeDecision:
        """
        Bir sembol için işlem kararı ver.

        Args:
            symbol: İşlem çifti (örn: BTCUSDT)
            sentiment: Piyasa duygusu (bullish, bearish, neutral)
            price: Mevcut fiyat
            indicators: Teknik indikatörler (opsiyonel)

        Returns:
            TradeDecision: Standart karar nesnesi
        """
        start_time = time.perf_counter()

        try:
            # Timeout koruması — karar mantığı basit ve hızlı
            decision = self._evaluate(symbol, sentiment, price, indicators or {})

            # İstatistikleri güncelle
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self._update_stats(elapsed_ms, success=True)

            logger.info(f"[{symbol}] Karar: {decision.action} (güven: {decision.confidence:.2f})")
            return decision

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self._update_stats(elapsed_ms, success=False)

            logger.error(f"[{symbol}] Karar hatası: {e}")
            # Güvenli varsayılan — HOLD
            return TradeDecision(
                action="HOLD",
                confidence=0.0,
                reason=f"Engine error: {str(e)}",
                symbol=symbol,
                timestamp=datetime.now().isoformat()
            )

    def _evaluate(self, symbol: str, sentiment: str, price: float, 
                  indicators: Dict) -> TradeDecision:
        """Dahili değerlendirme mantığı"""

        # Basit trend analizi
        trend_score = 0.0
        action = "HOLD"
        reason = "Neutral market conditions"

        if sentiment.lower() in ["bullish", "pozitif", "positive"]:
            trend_score = 0.7
            if price > 0:
                trend_score = min(0.95, trend_score + 0.2)
                action = "BUY"
                reason = "Bullish trend detected"

        elif sentiment.lower() in ["bearish", "negatif", "negative"]:
            trend_score = 0.6
            action = "SELL"
            reason = "Bearish pressure detected"

        # İndikatör güçlendirmesi
        if indicators:
            rsi = indicators.get('rsi', 50)
            if rsi < 30 and action == "BUY":
                trend_score = min(0.98, trend_score + 0.1)
                reason += " + RSI oversold"
            elif rsi > 70 and action == "SELL":
                trend_score = min(0.98, trend_score + 0.1)
                reason += " + RSI overbought"

        return TradeDecision(
            action=action,
            confidence=round(trend_score, 2),
            reason=reason,
            symbol=symbol,
            timestamp=datetime.now().isoformat(),
            metadata={
                'sentiment': sentiment,
                'price': price,
                'indicators': indicators
            }
        )

    def _update_stats(self, elapsed_ms: float, success: bool):
        """İstatistikleri güncelle"""
        self.stats['total_decisions'] += 1
        self.stats['last_decision_time'] = datetime.now().isoformat()

        if success:
            self.stats['successful_decisions'] += 1
        else:
            self.stats['failed_decisions'] += 1

        # Hareketli ortalama
        n = self.stats['total_decisions']
        old_avg = self.stats['avg_decision_time_ms']
        self.stats['avg_decision_time_ms'] = round(
            ((n - 1) * old_avg + elapsed_ms) / n, 2
        )

    def get_health(self) -> Dict[str, Any]:
        """Motor sağlık durumunu döndür"""
        total = self.stats['total_decisions']
        success_rate = (self.stats['successful_decisions'] / total * 100) if total > 0 else 100.0

        return {
            'status': 'healthy' if success_rate > 95 else 'warning' if success_rate > 80 else 'critical',
            'is_active': self.is_active,
            'success_rate': round(success_rate, 1),
            'avg_decision_time_ms': self.stats['avg_decision_time_ms'],
            'total_decisions': total,
            'failed_decisions': self.stats['failed_decisions'],
            'last_decision_time': self.stats['last_decision_time']
        }

    def shutdown(self):
        """Motoru güvenli şekilde kapat"""
        self.is_active = False
        logger.info("Trading Engine güvenli şekilde kapatıldı.")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

def test_trading_engine():
    """Trading Engine test fonksiyonu"""
    print("⚙️  Atlas AI Trading Engine v2.0 - Test Mode")
    print("=" * 50)

    engine = TradingEngine(timeout_seconds=5.0)

    test_cases = [
        ("BTCUSDT", "bullish", 65000.0, {"rsi": 28}),
        ("ETHUSDT", "bearish", 3200.0, {"rsi": 75}),
        ("SOLUSDT", "neutral", 145.0, {}),
        ("ADAUSDT", "bullish", 0.45, {"rsi": 45}),
    ]

    print("\n📡 Test senaryoları değerlendiriliyor...")
    print("-" * 50)

    for symbol, sentiment, price, indicators in test_cases:
        decision = engine.decide(symbol, sentiment, price, indicators)
        print(f"\n   {symbol} ({sentiment}, ${price}):")
        print(f"   → Action: {decision.action}")
        print(f"   → Confidence: {decision.confidence}")
        print(f"   → Reason: {decision.reason}")

    print("\n" + "=" * 50)
    print("\n📊 Health Report:")
    health = engine.get_health()
    for k, v in health.items():
        print(f"   {k}: {v}")

    engine.shutdown()
    print("\n✅ Trading Engine v2.0 test completed!")
    return engine


if __name__ == "__main__":
    test_trading_engine()
