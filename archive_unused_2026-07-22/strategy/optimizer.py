import json


class StrategyOptimizer:

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
            print("Henüz yeterli veri yok.")
            return


        al_count = 0
        al_profit = 0

        sat_count = 0
        sat_profit = 0


        for trade in trades:

            if trade["signal"] == "AL":
                al_count += 1
                al_profit += trade["profit"]

            elif trade["signal"] == "SAT":
                sat_count += 1
                sat_profit += trade["profit"]


        print("===== Atlas Strategy Optimizer =====")

        print("Toplam işlem:", total)

        print("")
        print("AL işlemleri:")
        print("Adet:", al_count)
        print("Sonuç:", round(al_profit, 2), "TL")


        print("")
        print("SAT işlemleri:")
        print("Adet:", sat_count)
        print("Sonuç:", round(sat_profit, 2), "TL")


        if al_profit > sat_profit:
            print("")
            print("Öneri: AL stratejisi daha güçlü")

        else:
            print("")
            print("Öneri: SAT stratejisi daha güçlü")


if __name__ == "__main__":

    optimizer = StrategyOptimizer()
    optimizer.analyze()