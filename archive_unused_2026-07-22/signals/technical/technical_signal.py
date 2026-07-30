from signals.base_signal import BaseSignal



class TechnicalSignal(BaseSignal):


    def __init__(self):

        super().__init__(
            "Technical Signal"
        )



    def generate(
        self,
        analysis
    ):


        score = 50

        reasons = []


        rsi = analysis.get(
            "rsi",
            50
        )


        macd = analysis.get(
            "macd_signal",
            "HOLD"
        )


        ema = analysis.get(
            "ema_signal",
            "HOLD"
        )



        # RSI değerlendirme

        if rsi < 30:

            score += 20

            reasons.append(
                "RSI oversold"
            )


        elif rsi > 70:

            score -= 15

            reasons.append(
                "RSI overbought"
            )



        # MACD

        if macd == "BUY":

            score += 15

            reasons.append(
                "MACD bullish"
            )


        elif macd == "SELL":

            score -= 15

            reasons.append(
                "MACD bearish"
            )



        # EMA

        if ema == "BUY":

            score += 15

            reasons.append(
                "EMA trend positive"
            )


        elif ema == "SELL":

            score -= 15

            reasons.append(
                "EMA trend negative"
            )



        score = max(
            0,
            min(
                score,
                100
            )
        )



        if score >= 60:

            signal = "BUY"


        elif score <= 40:

            signal = "SELL"


        else:

            signal = "HOLD"



        return self.result(

            signal,

            score,

            ", ".join(
                reasons
            )

        )