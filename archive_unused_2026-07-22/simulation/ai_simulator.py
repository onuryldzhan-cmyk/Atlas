from analytics.ai_performance import AIPerformance
import random



class AISimulator:


    def __init__(self):

        self.performance = AIPerformance()



    def simulate(
        self,
        symbol="BTCUSDT",
        tests=100
    ):


        strategies = [
            "scalping",
            "trend",
            "reversal"
        ]


        total_tests = 0
        wins = 0
        losses = 0


        strategy_data = {

            "scalping": {
                "wins":0,
                "losses":0
            },

            "trend": {
                "wins":0,
                "losses":0
            },

            "reversal": {
                "wins":0,
                "losses":0
            }

        }



        for i in range(tests):


            strategy = random.choice(
                strategies
            )


            chance = random.randint(
                40,
                75
            )



            if random.randint(1,100) <= chance:


                result = "WIN"

                wins += 1

                strategy_data[strategy]["wins"] += 1


            else:


                result = "LOSS"

                losses += 1

                strategy_data[strategy]["losses"] += 1



            total_tests += 1



            self.performance.add_result(
                strategy,
                result
            )



        success_rate = 0


        if total_tests > 0:

            success_rate = round(
                (wins / total_tests) * 100,
                2
            )



        return {


            "total_tests": total_tests,

            "wins": wins,

            "losses": losses,

            "success_rate": success_rate,

            "strategies": strategy_data

        }