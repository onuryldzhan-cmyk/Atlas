class VolatilityAnalyzer:


    def analyze(
        self,
        data
    ):


        high = data["high"]

        low = data["low"]


        atr = (

            high - low

        ).rolling(14).mean().iloc[-1]


        close = float(
            data["close"].iloc[-1]
        )


        volatility = (

            atr

            /

            close

        ) * 100


        signal = "NORMAL"


        if volatility > 2:

            signal = "HIGH"


        elif volatility < 0.7:

            signal = "LOW"



        return {

            "atr": round(
                atr,
                2
            ),

            "volatility": round(
                volatility,
                2
            ),

            "signal": signal

        }