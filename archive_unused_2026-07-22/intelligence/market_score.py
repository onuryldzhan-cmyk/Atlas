from intelligence.market.market_intelligence import MarketIntelligence



class MarketScore:


    def __init__(self):

        self.market_intelligence = MarketIntelligence()



    def calculate(
        self,
        analysis,
        data=None
    ):


        score = 50



        rsi = analysis.get(
            "rsi",
            50
        )


        macd_signal = analysis.get(
            "macd_signal",
            "HOLD"
        )


        ema_signal = analysis.get(
            "ema_signal",
            "HOLD"
        )



        # RSI ANALİZİ

        if 45 <= rsi <= 60:

            score += 15


        elif 30 <= rsi < 45:

            score += 5


        elif 60 < rsi <= 70:

            score += 5


        elif rsi > 70:

            score -= 10


        elif rsi < 30:

            score -= 10




        # MACD

        if macd_signal == "BUY":

            score += 15


        elif macd_signal == "SELL":

            score -= 15




        # EMA

        if ema_signal == "BUY":

            score += 15


        elif ema_signal == "SELL":

            score -= 15




        # MARKET INTELLIGENCE

        market_data = None


        if data is not None:


            market_data = self.market_intelligence.analyze(

                data

            )


            score += (

                market_data["market_score"]

                -

                50

            ) * 0.3




        score = round(

            max(

                0,

                min(

                    100,

                    score

                )

            ),

            2

        )



        return score