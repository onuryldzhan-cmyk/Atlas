import pandas as pd


class TechnicalAnalyzer:

    def analyze(self, df):

        if df is None or len(df) < 50:
            return {
                "rsi": 50,
                "macd_signal": "HOLD",
                "ema_signal": "HOLD"
            }

        close = df["close"]

        # EMA
        ema20 = close.ewm(span=20).mean().iloc[-1]
        ema50 = close.ewm(span=50).mean().iloc[-1]

        if ema20 > ema50:
            ema_signal = "BUY"
        elif ema20 < ema50:
            ema_signal = "SELL"
        else:
            ema_signal = "HOLD"

        # RSI
        delta = close.diff()

        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        rsi = round(float(rsi.iloc[-1]), 2)

        # MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()

        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()

        if macd.iloc[-1] > signal.iloc[-1]:
            macd_signal = "BUY"
        elif macd.iloc[-1] < signal.iloc[-1]:
            macd_signal = "SELL"
        else:
            macd_signal = "HOLD"

        return {
            "rsi": rsi,
            "macd_signal": macd_signal,
            "ema_signal": ema_signal
        }