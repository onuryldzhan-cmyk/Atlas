"""
Atlas Agent Analyzer v1.0

Multi intelligence signal generator.

Responsibilities:

- Analyze independent intelligence sources
- Generate agent decisions
- Calculate momentum
- Normalize signals


"""


class AgentAnalyzer:


    VERSION = "1.0"



    def __init__(self):


        self.agents = [

            "technical",

            "momentum",

            "risk",

            "macro",

            "sentiment"

        ]






    # =================================================
    # MAIN ANALYSIS
    # =================================================


    def analyze(

        self,

        symbol,

        market_data

    ):


        signals = {}



        intelligence = {


            "technical":

            market_data.get(

                "technical_score",

                0.5

            ),



            "momentum":

            self.calculate_momentum(

                market_data

            ),



            "risk":

            market_data.get(

                "risk_score",

                0.5

            ),



            "macro":

            market_data.get(

                "macro_score",

                0.5

            ),



            "sentiment":

            market_data.get(

                "sentiment_score",

                0.5

            )

        }






        for name, score in intelligence.items():


            action = self.convert_action(

                score

            )



            signals[name] = {


                "action":

                action,


                "score":

                round(

                    score,

                    3

                )


            }



            print(

                f"[AGENT] {name}: {action} {score:.2f}"

            )




        return signals







    # =================================================
    # SCORE TO ACTION
    # =================================================


    def convert_action(

        self,

        score

    ):


        if score >= 0.60:


            return "BUY"



        elif score <= 0.40:


            return "SELL"



        return "HOLD"







    # =================================================
    # MOMENTUM MODEL
    # =================================================


    def calculate_momentum(

        self,

        market_data

    ):


        rsi = market_data.get(

            "rsi",

            50

        )


        trend = market_data.get(

            "trend",

            "SIDEWAYS"

        )



        score = 0.5






        if trend == "BULLISH":


            score += 0.20




        elif trend == "BEARISH":


            score -= 0.20





        if rsi < 35:


            score += 0.10




        elif rsi > 70:


            score -= 0.10






        return max(

            0,

            min(

                score,

                1

            )

        )