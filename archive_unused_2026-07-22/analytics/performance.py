import csv
import os


class PerformanceCenter:

    def __init__(self, file_name="trade_history.csv"):

        self.file = file_name

    def report(self):

        if not os.path.exists(self.file):

            print("Trade geçmişi bulunamadı.")
            return

        total = 0
        wins = 0
        losses = 0
        profit = 0.0

        with open(
            self.file,
            "r",
            encoding="utf-8"
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:

                total += 1

                pnl = float(row["profit"])

                profit += pnl

                if pnl > 0:
                    wins += 1
                else:
                    losses += 1

        winrate = 0

        if total > 0:

            winrate = round(
                wins / total * 100,
                2
            )

        print("\n===== PERFORMANCE CENTER =====")
        print("Toplam İşlem :", total)
        print("Kazanan      :", wins)
        print("Kaybeden     :", losses)
        print("Win Rate     :", f"{winrate}%")
        print("Toplam Kar   :", round(profit, 2))
        print("==============================")