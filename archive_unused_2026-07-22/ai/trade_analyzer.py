import json


class TradeAnalyzer:


    def __init__(self):

        self.file = "../database/trades.json"



    def analyze(self):

        try:

            with open(self.file, "r") as f:
                trades = json.load(f)

        except Exception:

            print("İşlem geçmişi bulunamadı.")
            return



        total = len(trades)


        if total == 0:

            print("Yeterli veri yok.")
            return



        take_profit = 0
        stop_loss = 0
        time_exit = 0

        total_profit = 0

        al_profit = 0
        sat_profit = 0



        for trade in trades:


            profit = trade.get("profit", 0)

            total_profit += profit



            reason = trade.get(
                "exit_reason",
                "UNKNOWN"
            )


            if reason == "TAKE_PROFIT":

                take_profit += 1


            elif reason == "STOP_LOSS":

                stop_loss += 1


            elif reason == "TIME_EXIT":

                time_exit += 1



            if trade["signal"] == "AL":

                al_profit += profit


            elif trade["signal"] == "SAT":

                sat_profit += profit




        print("==============================")
        print("Atlas Trade Analyzer")
        print("==============================")


        print("Toplam işlem:", total)

        print("TAKE PROFIT:", take_profit)

        print("STOP LOSS:", stop_loss)

        print("TIME EXIT:", time_exit)


        print("")

        print(
            "AL performansı:",
            round(al_profit,2),
            "TL"
        )


        print(
            "SAT performansı:",
            round(sat_profit,2),
            "TL"
        )


        print(
            "Toplam sonuç:",
            round(total_profit,2),
            "TL"
        )



if __name__ == "__main__":

    analyzer = TradeAnalyzer()

    analyzer.analyze()