"""
core/technical_analyzer.py
Teknik analiz (EMA, RSI, ADX) - Liste tabanlı (pandas gerektirmez)
"""
class TechnicalAnalyzer:
    def ema(self, prices, period):
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return round(ema, 4)

    def rsi(self, prices, period=14):
        if len(prices) <= period:
            return None
        gains, losses = [], []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i-1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)

    def adx(self, candles, period=14):
        """
        Basit ADX hesaplaması (list of dict ile)
        """
        if len(candles) < period * 2:
            return 0
        # TR ve DM hesaplamaları
        tr_list = []
        plus_dm = []
        minus_dm = []
        for i in range(1, len(candles)):
            high = candles[i]["high"]
            low = candles[i]["low"]
            prev_high = candles[i-1]["high"]
            prev_low = candles[i-1]["low"]
            prev_close = candles[i-1]["close"]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
            plus_dm.append(max(high - prev_high, 0) if high - prev_high > prev_low - low else 0)
            minus_dm.append(max(prev_low - low, 0) if prev_low - low > high - prev_high else 0)
        # TR, +DM, -DM için basit ortalama
        atr = sum(tr_list[-period:]) / period if len(tr_list) >= period else 0
        avg_plus = sum(plus_dm[-period:]) / period if len(plus_dm) >= period else 0
        avg_minus = sum(minus_dm[-period:]) / period if len(minus_dm) >= period else 0
        if atr == 0:
            return 0
        plus_di = 100 * avg_plus / atr
        minus_di = 100 * avg_minus / atr
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) != 0 else 0
        # ADX için basit smoothing (son 14 dx'in ortalaması)
        if len(candles) < period * 2 + period:
            return round(dx, 2)
        return round(dx, 2)

    def analyze(self, candles):
        """
        candles: list of dict (open, high, low, close, volume)
        """
        if not candles or len(candles) < 20:
            return {"rsi": None, "ema20": None, "ema50": None, "adx": 0, "last_close": 0}
        closes = [c["close"] for c in candles]
        last_close = closes[-1]
        ema20 = self.ema(closes, 20)
        ema50 = self.ema(closes, 50)
        rsi_val = self.rsi(closes, 14)
        adx_val = self.adx(candles, 14)
        trend = "BEARISH" if ema20 and ema50 and ema20 < ema50 else "BULLISH" if ema20 and ema50 and ema20 > ema50 else "NEUTRAL"
        return {
            "ema20": ema20,
            "ema50": ema50,
            "rsi": rsi_val,
            "adx": adx_val,
            "last_close": last_close,
            "trend": trend
        }