class SupportResistanceAnalyzer:


    def analyze(
        self,
        data
    ):


        highs = data["high"].tail(20)

        lows = data["low"].tail(20)

        close = float(
            data["close"].iloc[-1]
        )


        resistance = float(
            highs.max()
        )

        support = float(
            lows.min()
        )


        signal = "MIDDLE"


        distance_support = (

            (close - support)

            /

            close

        ) * 100


        distance_resistance = (

            (resistance - close)

            /

            close

        ) * 100


        if distance_support < 1:

            signal = "NEAR_SUPPORT"


        elif distance_resistance < 1:

            signal = "NEAR_RESISTANCE"



        return {

            "support": round(
                support,
                2
            ),

            "resistance": round(
                resistance,
                2
            ),

            "signal": signal

        }