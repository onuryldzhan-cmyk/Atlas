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

        gains = []
        losses = []

        for i in range(1, len(prices)):

            diff = prices[i] - prices[i - 1]

            if diff > 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(diff))

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100

        rs = avg_gain / avg_loss

        rsi = 100 - (100 / (1 + rs))

        return round(rsi, 2)


    def analyze(self, candles):

        closes = [c["close"] for c in candles]

        ema20 = self.ema(closes, 20)
        ema50 = self.ema(closes, 50)
        rsi = self.rsi(closes)

        return {

            "ema20": ema20,

            "ema50": ema50,

            "rsi": rsi

        }