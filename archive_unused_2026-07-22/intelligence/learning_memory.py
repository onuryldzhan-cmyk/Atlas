import json
import os
from datetime import datetime


class LearningMemory:


    def __init__(self):

        self.file = "data/atlas_memory.json"

        os.makedirs(
            "data",
            exist_ok=True
        )


        if not os.path.exists(self.file):

            with open(
                self.file,
                "w"
            ) as f:

                json.dump(
                    [],
                    f,
                    indent=4
                )



    def save_trade(self, trade):

        try:

            with open(
                self.file,
                "r"
            ) as f:

                memory = json.load(f)



            trade["time"] = str(
                datetime.now()
            )


            memory.append(
                trade
            )



            with open(
                self.file,
                "w"
            ) as f:

                json.dump(
                    memory,
                    f,
                    indent=4
                )


            print(
                "Atlas hafızaya kayıt yaptı."
            )


        except Exception as e:

            print(
                "Memory kayıt hatası:",
                e
            )



    def update_trade_result(
        self,
        symbol,
        result,
        profit
    ):


        try:

            with open(
                self.file,
                "r"
            ) as f:

                memory = json.load(f)



            for trade in reversed(memory):


                if (
                    trade.get("symbol") == symbol
                    and trade.get("status") == "OPEN"
                ):

                    trade["status"] = "CLOSED"

                    trade["result"] = result

                    trade["profit"] = profit

                    trade["close_time"] = str(
                        datetime.now()
                    )

                    break



            with open(
                self.file,
                "w"
            ) as f:

                json.dump(
                    memory,
                    f,
                    indent=4
                )


        except Exception as e:

            print(
                "Trade güncelleme hatası:",
                e
            )



    def get_history(self):


        try:

            with open(
                self.file,
                "r"
            ) as f:

                return json.load(f)


        except Exception:

            return []



    def statistics(self):


        history = self.get_history()


        total = len(history)

        wins = 0

        losses = 0


        profit = 0



        for trade in history:


            if trade.get("result") == "WIN":

                wins += 1


            elif trade.get("result") == "LOSS":

                losses += 1



            profit += trade.get(
                "profit",
                0
            )



        closed = wins + losses



        win_rate = 0


        if closed > 0:

            win_rate = round(
                (wins / closed) * 100,
                2
            )



        return {


            "total_trades": total,

            "wins": wins,

            "losses": losses,

            "profit": round(
                profit,
                2
            ),

            "win_rate": win_rate

        }