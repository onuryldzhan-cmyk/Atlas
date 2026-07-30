class Simulator:


    def __init__(self):

        pass



    def run(
        self,
        signal,
        entry,
        plan
    ):


        if "take_profit_2" in plan:

            target = plan["take_profit_2"]

        else:

            target = plan.get(
                "take_profit",
                entry
            )



        if signal == "AL":


            profit = target - entry


        else:


            profit = entry - target



        if profit > 0:


            return {

                "result": "WIN",

                "profit": round(
                    profit,
                    4
                )

            }



        else:


            return {

                "result": "LOSS",

                "profit": round(
                    profit,
                    4
                )

            }