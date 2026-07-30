class BreakoutAnalyzer:


    def analyze(
        self,
        data
    ):


        highs = data["high"].tail(20)

        lows = data["low"].tail(20)

        close = float(
            data["close"].iloc[-1]
        )


        highest = float(
            highs.max()
        )

        lowest = float(
            lows.min()
        )


        signal = "NONE"


        if close >= highest:

            signal = "BREAKOUT_UP"


        elif close <= lowest:

            signal = "BREAKOUT_DOWN"



        return {

            "highest": round(
                highest,
                2
            ),

            "lowest": round(
                lowest,
                2
            ),

            "signal": signal

        }