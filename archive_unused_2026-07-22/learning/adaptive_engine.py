import json
import os


class AdaptiveEngine:


    def __init__(self):

        self.trade_file = "../database/trades.json"
        self.memory_file = "../database/model_memory.json"



    def load_trades(self):

        if not os.path.exists(self.trade_file):

            return []


        with open(
            self.trade_file,
            "r"
        ) as f:

            return json.load(f)



    def learn(self):

        trades = self.load_trades()


        if len(trades) == 0:

            print("Öğrenilecek veri yok.")
            return



        total = len(trades)

        wins = 0

        losses = 0


        al_profit = 0

        sat_profit = 0



        for trade in trades:


            profit = trade["profit"]


            if profit > 0:

                wins += 1


            elif profit < 0:

                losses += 1



            if trade["signal"] == "AL":

                al_profit += profit


            elif trade["signal"] == "SAT":

                sat_profit += profit




        win_rate = round(
            (wins / total) * 100,
            2
        )



        memory = {


            "total_trades": total,


            "win_rate": win_rate,


            "winning_trades": wins,


            "losing_trades": losses,


            "AL_score": round(al_profit,2),


            "SAT_score": round(sat_profit,2)


        }



        with open(
            self.memory_file,
            "w"
        ) as f:


            json.dump(
                memory,
                f,
                indent=4
            )



        print("==============================")

        print("Atlas Adaptive Learning")

        print("==============================")


        print(
            "Toplam işlem:",
            total
        )


        print(
            "Başarı oranı:",
            win_rate,
            "%"
        )


        print(
            "AL performans:",
            round(al_profit,2),
            "TL"
        )


        print(
            "SAT performans:",
            round(sat_profit,2),
            "TL"
        )


        print("Model hafızası güncellendi.")



if __name__ == "__main__":


    ai = AdaptiveEngine()

    ai.learn()