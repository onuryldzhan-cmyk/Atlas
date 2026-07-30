"""
Atlas AI Adaptive Weight Engine v4.2
Self Optimizing Strategy Weights
"""


class AdaptiveWeights:


    def __init__(self, learning):

        self.learning = learning


        self.base_weights = {

            "Trend-Follow": 2.0,

            "Breakout": 1.5,

            "Momentum": 1.2,

            "RSI-Scalping": 1.0,

            "Defensive": 0.5

        }



    def get_weights(self):


        weights = {}



        for strategy,base in self.base_weights.items():


            score = self.learning.get_strategy_score(
                strategy
            )


            multiplier = score / 50



            adjusted = base * multiplier



            adjusted = max(
                min(
                    adjusted,
                    3.0
                ),
                0.2
            )


            weights[strategy] = round(
                adjusted,
                2
            )



        return weights





    def get_best_strategy(self):


        insight = self.learning.get_insight()


        return insight.get(
            "best_strategy",
            "Trend-Follow"
        )




    def explain(self):


        weights = self.get_weights()


        print(
            "\n===== ADAPTIVE STRATEGY WEIGHTS ====="
        )


        for name,value in weights.items():

            print(
                f"{name}: {value}"
            )


        print(
            "====================================\n"
        )


        return weights