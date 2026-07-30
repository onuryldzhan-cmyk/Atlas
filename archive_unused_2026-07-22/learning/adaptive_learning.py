import json


class AdaptiveLearning:


    def __init__(self):

        self.trade_file = "../database/trades.json"

        self.memory_file = "../database/model_memory.json"



    def learn(self):


        try:

            with open(
                self.trade_file,
                "r",
                encoding="utf-8"
            ) as file:

                trades = json.load(file)


        except Exception as e:

            print("Trade verisi okunamadı.")
            print(e)
            return




        total = len(trades)


        if total == 0:

            print("Yeterli veri yok.")

            return




        al_total = 0
        sat_total = 0

        al_count = 0
        sat_count = 0



        for trade in trades:


            profit = trade.get(
                "profit",
                0
            )


            signal = trade.get(
                "signal",
                ""
            )



            if signal == "AL":

                al_total += profit

                al_count += 1



            elif signal == "SAT":

                sat_total += profit

                sat_count += 1





        al_average = 0
        sat_average = 0



        if al_count > 0:

            al_average = al_total / al_count



        if sat_count > 0:

            sat_average = sat_total / sat_count






        if al_average > sat_average:

            preferred = "AL"


        elif sat_average > al_average:

            preferred = "SAT"


        else:

            preferred = "DENGELI"





        memory = {


            "total_trades": total,

            "AL_average": round(al_average,2),

            "SAT_average": round(sat_average,2),

            "preferred_signal": preferred,

            "learning_status": "ACTIVE"


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
        print("Atlas Adaptive Learning")
        print("==============================")

        print(
            "Toplam işlem:",
            total
        )

        print(
            "AL ortalama:",
            round(al_average,2),
            "TL"
        )

        print(
            "SAT ortalama:",
            round(sat_average,2),
            "TL"
        )

        print(
            "Tercih:",
            preferred
        )

        print(
            "Adaptif öğrenme aktif."
        )




if __name__ == "__main__":


    ai = AdaptiveLearning()

    ai.learn()