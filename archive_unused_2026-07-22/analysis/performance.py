import json


class PerformanceAnalyzer:

    def __init__(self):
        self.file = "../database/trades.json"


    def report(self):

        try:
            with open(self.file, "r") as f:
                trades = json.load(f)

        except Exception:
            print("Henüz işlem yok.")
            return


        total = len(trades)

        profitable = 0
        total_profit = 0


        for trade in trades:

            profit = trade["profit"]

            total_profit += profit

            if profit > 0:
                profitable += 1


        success_rate = (profitable / total) * 100


        print("===== Atlas Performans =====")
        print("Toplam işlem:", total)
        print("Kârlı işlem:", profitable)
        print("Başarı oranı:", round(success_rate, 2), "%")
        print("Toplam sonuç:", round(total_profit, 2), "TL")


if __name__ == "__main__":

    analyzer = PerformanceAnalyzer()
    analyzer.report()