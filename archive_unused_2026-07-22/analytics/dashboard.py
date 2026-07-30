import csv
import os


class AnalyticsDashboard:

    def __init__(self):

        self.file = "trade_history.csv"

    def show(self):

        if not os.path.exists(self.file):

            print("Trade geçmişi bulunamadı.")

            return

        total = 0
        wins = 0
        losses = 0

        total_profit = 0

        biggest_win = None
        biggest_loss = None

        win_sum = 0
        loss_sum = 0

        with open(
            self.file,
            "r",
            encoding="utf-8"
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:

                total += 1

                profit = float(row["profit"])

                total_profit += profit

                if biggest_win is None or profit > biggest_win:
                    biggest_win = profit

                if biggest_loss is None or profit < biggest_loss:
                    biggest_loss = profit

                if profit > 0:

                    wins += 1
                    win_sum += profit

                else:

                    losses += 1
                    loss_sum += abs(profit)

        if total > 0:
            winrate = (wins / total) * 100
        else:
            winrate = 0

        average_win = (
            win_sum / wins
            if wins > 0
            else 0
        )

        average_loss = (
            loss_sum / losses
            if losses > 0
            else 0
        )

        if loss_sum > 0:
            profit_factor = (
                win_sum / loss_sum
            )
        else:
            profit_factor = 999

        print()
        print("========== ATLAS ANALYTICS ==========")

        print("Toplam İşlem :", total)
        print("Kazanan      :", wins)
        print("Kaybeden     :", losses)

        print("Win Rate     :", round(winrate, 2), "%")

        print()

        print("Net Kar      :", round(total_profit, 2))

        print("Ort Kazanç   :", round(average_win, 2))

        print("Ort Zarar    :", round(average_loss, 2))

        print()

        print(
            "ProfitFactor :",
            round(profit_factor, 2)
        )

        print(
            "En Büyük Kar :",
            round(biggest_win, 2)
            if biggest_win is not None
            else 0
        )

        print(
            "En Büyük Zarar :",
            round(biggest_loss, 2)
            if biggest_loss is not None
            else 0
        )

        print("====================================")


if __name__ == "__main__":

    AnalyticsDashboard().show()