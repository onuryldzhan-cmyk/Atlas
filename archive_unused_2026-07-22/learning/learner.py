import json


class Learner:

    def __init__(self):

        self.file = "../database/trades.json"


    def analyze_history(self):

        try:

            with open(self.file, "r") as f:
                trades = json.load(f)

        except Exception:

            print("Geçmiş işlem yok.")
            return


        if len(trades) == 0:

            print("Henüz veri yok.")
            return


        opened = [
            trade for trade in trades
            if trade.get("status") == "OPEN"
        ]


        passed = [
            trade for trade in trades
            if trade.get("status") == "PASSED"
        ]


        wins = [
            trade for trade in opened
            if trade.get("profit", 0) > 0
        ]


        total_profit = sum(
            trade.get("profit", 0)
            for trade in opened
        )


        print("Toplam sinyal:", len(trades))
        print("Açılan işlem:", len(opened))
        print("Pas geçilen:", len(passed))
        print("Kazanan işlem:", len(wins))


        if len(opened) > 0:

            success = (len(wins) / len(opened)) * 100

            print(
                "Başarı oranı:",
                round(success, 2),
                "%"
            )


        print(
            "Toplam kâr:",
            total_profit
        )



if __name__ == "__main__":

    learner = Learner()

    learner.analyze_history()