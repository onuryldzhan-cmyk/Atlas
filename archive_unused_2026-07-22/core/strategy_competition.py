"""
Atlas AI v5.6
Adaptive Strategy Competition Engine

Institutional Multi Strategy Voting System

Features:
- Trend Priority
- RSI Timing Filter
- ADX Confirmation
- Volatility Awareness
- Learning Weight Support
"""


from core.weight_optimizer import WeightOptimizer



class StrategyCompetition:


    def __init__(
        self,
        learning=None
    ):


        self.learning = learning


        self.weights = {


            "Trend-Follow": 2.5,

            "Breakout": 1.8,

            "Momentum": 1.4,

            "RSI-Scalping": 1.0,

            "Defensive": 0.3


        }



    def update_weights(self):


        if self.learning:


            optimizer = WeightOptimizer(
                self.learning
            )


            self.weights = optimizer.optimize()



    def run(
        self,
        fusion
    ):


        self.update_weights()



        signal = fusion.get(
            "signal",
            "BEKLE"
        )


        score = fusion.get(
            "score",
            50
        )


        strength = fusion.get(
            "strength",
            "WEAK"
        )



        technical = fusion.get(
            "technical",
            {}
        )


        trend = technical.get(
            "trend",
            ""
        )


        rsi = technical.get(
            "rsi",
            50
        )


        adx = technical.get(
            "adx",
            0
        )


        volatility = fusion.get(
            "market",
            {}
        ).get(
            "volatility",
            0
        )



        strategies = {}



        # =====================================
        # TREND FOLLOW
        # Ana strateji
        # =====================================


        trend_score = 50


        trend_vote = "WAIT"



        if trend == "BULLISH":


            trend_score += 30


            if signal == "AL":

                trend_vote = "BUY"

                trend_score += 15



        elif trend == "BEARISH":


            trend_score += 30


            if signal == "SAT":

                trend_vote = "SELL"

                trend_score += 15



        if adx > 25:

            trend_score += 10



        strategies["Trend-Follow"] = {


            "vote":

                trend_vote,


            "score":

                min(
                    trend_score,
                    100
                )


        }




        # =====================================
        # BREAKOUT
        # =====================================


        breakout_score = 50


        breakout_vote = "WAIT"



        if strength == "STRONG":


            breakout_score += 30



            if signal == "AL":

                breakout_vote = "BUY"


            elif signal == "SAT":

                breakout_vote = "SELL"




        if adx > 30:

            breakout_score += 10




        strategies["Breakout"] = {


            "vote":

                breakout_vote,


            "score":

                min(
                    breakout_score,
                    100
                )


        }




        # =====================================
        # MOMENTUM
        # =====================================


        momentum_score = 50


        momentum_vote = "WAIT"



        if rsi > 60:


            momentum_vote = "BUY"

            momentum_score += 30



        elif rsi < 40:


            momentum_vote = "SELL"

            momentum_score += 30




        strategies["Momentum"] = {


            "vote":

                momentum_vote,


            "score":

                momentum_score


        }




        # =====================================
        # RSI SCALPING
        # Giriş zamanlama
        # =====================================


        rsi_score = 50


        rsi_vote = "WAIT"



        if rsi < 35:


            rsi_vote = "BUY"

            rsi_score = 80



        elif rsi > 75:


            rsi_vote = "SELL"

            rsi_score = 80




        strategies["RSI-Scalping"] = {


            "vote":

                rsi_vote,


            "score":

                rsi_score


        }




        # =====================================
        # DEFENSIVE
        # =====================================


        defensive_vote = "WAIT"


        defensive_score = 40



        if volatility > 0.02:


            defensive_score = 90




        strategies["Defensive"] = {


            "vote":

                defensive_vote,


            "score":

                defensive_score


        }




        # =====================================
        # FINAL WEIGHTED DECISION
        # =====================================


        weighted = {


            "BUY":0,

            "SELL":0,

            "WAIT":0


        }




        for name,data in strategies.items():


            vote = data["vote"]


            value = (

                data["score"]

                *

                self.weights.get(
                    name,
                    1
                )

            )


            weighted[vote] += value





        final_vote = max(
            weighted,
            key=weighted.get
        )



        total = sum(
            weighted.values()
        )



        confidence = 0


        if total:


            confidence = (

                weighted[final_vote]

                /

                total

            ) * 100




        best_strategy = max(

            strategies,

            key=lambda x:

                strategies[x]["score"]

        )





        return {


            "strategy":

                best_strategy,


            "score":

                round(
                    confidence,
                    2
                ),



            "final_vote":

                final_vote,



            "strategies":

                strategies,



            "weighted_votes":

                {

                    k:

                    round(
                        v,
                        2
                    )

                    for k,v in weighted.items()

                },



            "strategy_confidence":

                round(
                    confidence,
                    2
                ),



            "weights":

                self.weights


        }