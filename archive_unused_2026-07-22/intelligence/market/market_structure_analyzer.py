class MarketStructureAnalyzer:


    def __init__(self):

        self.name = "Market Structure Analyzer"



    def analyze(
        self,
        data
    ):


        close = data["close"]



        current = float(
            close.iloc[-1]
        )


        previous = float(
            close.iloc[-20]
            )



        highest = float(
            close.tail(20).max()
        )


        lowest = float(
            close.tail(20).min()
        )



        trend = "SIDEWAYS"

        score = 50



        change = (

            (current - previous)

            /

            previous

        ) * 100



        if change > 1:


            trend = "UPTREND"

            score = 75



        elif change < -1:


            trend = "DOWNTREND"

            score = 25



        breakout = False



        if current >= highest:


            breakout = True

            score += 10



        if current <= lowest:


            breakout = True

            score -= 10



        score = max(

            0,

            min(

                score,

                100

            )

        )



        return {


            "trend": trend,

            "breakout": breakout,

            "high": highest,

            "low": lowest,

            "score": score

        }