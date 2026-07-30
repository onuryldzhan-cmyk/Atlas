class Scalper:


    def __init__(self):

        pass



    def analyze(
        self,
        candles
    ):


        closes = []


        for candle in candles:

            closes.append(
                candle["close"]
            )



        first = closes[0]

        last = closes[-1]



        if last > first:

            trend = "YUKSELIS"

            signal = "AL"


        elif last < first:

            trend = "DUSUS"

            signal = "SAT"


        else:

            trend = "YATAY"

            signal = "BEKLE"



        return {

            "trend": trend,

            "signal": signal,

            "strength": abs(
                last - first
            )

        }