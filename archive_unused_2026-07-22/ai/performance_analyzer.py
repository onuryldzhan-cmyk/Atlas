import json


class PerformanceAnalyzer:

    def __init__(self):
        self.file = "../database/trades.json"


    def analyze(self):

        try:
            with open(self.file, "r") as f:
                trades = json.load(f)

        except Exception:
            print("Veri bulunamadı.")
            return


        total = len(trades)

        if total == 0:
            print("Henüz işlem yok.")
            return


        wins = 0
        losses = 0
        total_profit = 0

        al_profit = 0
        sat_profit = 0


        for trade in trades:

            profit = trade.get("profit", 0)

            total_profit += profit


            if profit > 0:
                wins += 1

            elif profit < 0:
                losses += 1


            if trade["signal"] == "AL":
                al_profit += profit

            elif trade["signal"] == "SAT":
                sat_profit += profit



        success_rate = (wins / total) * 100


        print("==============================")
        print("Atlas Performance Analyzer")
        print("==============================")

        print("Toplam işlem:", total)

        print("Kazanan:", wins)

        print("Kaybeden:", losses)

        print(
            "Başarı oranı:",
            round(success_rate, 2),
            "%"
        )

        print(
            "Toplam kâr:",
            round(total_profit, 2),
            "TL"
        )

        print("")

        print(
            "AL toplam:",
            round(al_profit, 2),
            "TL"
        )

        print(
            "SAT toplam:",
            round(sat_profit, 2),
            "TL"
        )


if __name__ == "__main__":

    analyzer = PerformanceAnalyzer()

    analyzer.analyze()