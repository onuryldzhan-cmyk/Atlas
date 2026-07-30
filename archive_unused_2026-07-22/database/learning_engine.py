import json


class LearningEngine:


    def __init__(self):

        self.trade_file = "trades.json"

        self.memory_file = "model_memory.json"



    def learn(self):

        try:

            with open(
                self.trade_file,
                "r",
                encoding="utf-8"
            ) as file:

                trades = json.load(file)


        except Exception as e:

            print("Trade verisi bulunamadı.")
            print(e)
            return



        total = len(trades)


        if total == 0:

            print("Öğrenilecek veri yok.")
            return



        al_profit = 0
        sat_profit = 0

        al_win = 0
        sat_win = 0



        for trade in trades:


            profit = trade.get("profit",0)

            signal = trade.get("signal","")



            if signal == "AL":

                al_profit += profit

                if profit > 0:
                    al_win += 1



            elif signal == "SAT":

                sat_profit += profit

                if profit > 0:
                    sat_win += 1




        if al_profit > sat_profit:

            best_signal = "AL"


        elif sat_profit > al_profit:

            best_signal = "SAT"


        else:

            best_signal = "DENGELI"



        memory = {

            "total_trades": total,

            "AL_profit": round(al_profit,2),

            "SAT_profit": round(sat_profit,2),

            "AL_wins": al_win,

            "SAT_wins": sat_win,

            "best_signal": best_signal

        }



        with open(
            self.memory_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                memory,
                file,
                indent=4,
                ensure_ascii=False
            )



        print("==============================")
        print("Atlas Learning Engine")
        print("==============================")

        print("Toplam işlem:", total)

        print("AL performans:", round(al_profit,2),"TL")

        print("SAT performans:", round(sat_profit,2),"TL")

        print("En güçlü sinyal:", best_signal)

        print("Model hafızası güncellendi.")




if __name__ == "__main__":

    engine = LearningEngine()

    engine.learn()