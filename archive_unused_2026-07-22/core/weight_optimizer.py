"""
Atlas AI v4.7
Strategy Weight Optimizer

Adaptive strategy performance based weighting
"""


class WeightOptimizer:


    def __init__(self, learning):

        self.learning = learning


        self.base_weights = {

            "Trend-Follow": 2.0,

            "Breakout": 1.5,

            "Momentum": 1.2,

            "RSI-Scalping": 1.0,

            "Defensive": 0.5

        }



    def optimize(self):


        weights = self.base_weights.copy()


        try:


            data = self.learning.data


            strategies = data.get(
                "strategies",
                {}
            )



            for name, info in strategies.items():


                trades = info.get(
                    "trades",
                    0
                )


                wins = info.get(
                    "wins",
                    0
                )



                if trades < 5:

                    continue



                win_rate = (

                    wins /
                    trades

                ) * 100



                if win_rate >= 70:


                    weights[name] += 0.3



                elif win_rate <= 40:


                    weights[name] -= 0.3




                if weights[name] < 0.1:

                    weights[name] = 0.1





        except Exception as e:


            print(
                "[WEIGHT OPTIMIZER ERROR]",
                e
            )



        return weights