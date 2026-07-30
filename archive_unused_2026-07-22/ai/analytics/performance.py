from datetime import datetime


class PerformanceCenter:

    def __init__(self):

        self.total_trades = 0
        self.wins = 0
        self.losses = 0

        self.total_profit = 0

        self.best_trade = 0
        self.worst_trade = 0

        self.total_confidence = 0

        self.scalp_count = 0
        self.normal_count = 0


    def add_trade(self, decision, result):

        self.total_trades += 1

        profit = result.get("profit", 0)

        self.total_profit += profit

        if result.get("result") == "WIN":
            self.wins += 1
        else:
            self.losses += 1

        if profit > self.best_trade:
            self.best_trade = profit

        if profit < self.worst_trade:
            self.worst_trade = profit

        self.total_confidence += decision.get("confidence", 0)

        if decision.get("mode") == "SCALP":
            self.scalp_count += 1
        else:
            self.normal_count += 1


    def report(self):

        if self.total_trades == 0:
            winrate = 0
            avg_confidence = 0
        else:
            winrate = round(
                (self.wins / self.total_trades) * 100,
                2
            )

            avg_confidence = round(
                self.total_confidence / self.total_trades,
                2
            )

        if self.scalp_count >= self.normal_count:
            best_strategy = "SCALP"
        else:
            best_strategy = "NORMAL"

        print("\n========== ATLAS PERFORMANCE ==========")

        print("Tarih:", datetime.now())

        print("Toplam İşlem:", self.total_trades)

        print("Kazanan:", self.wins)

        print("Kaybeden:", self.losses)

        print("Başarı Oranı:", str(winrate) + "%")

        print("Toplam Kar:", round(self.total_profit, 2))

        print("En İyi İşlem:", round(self.best_trade, 2))

        print("En Kötü İşlem:", round(self.worst_trade, 2))

        print("Ortalama Güven:", avg_confidence)

        print("En Başarılı Mod:", best_strategy)

        print("=======================================\n")