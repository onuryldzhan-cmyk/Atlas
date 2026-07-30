class PortfolioDashboard:


    def __init__(self, portfolio):

        self.portfolio = portfolio



    def show(self):

        data = self.portfolio.report()


        print("\n==============================")
        print("     ATLAS PORTFOLIO")
        print("==============================")

        print(
            "Balance      :",
            data["balance"],
            "USDT"
        )

        print(
            "Total Profit :",
            data["profit"],
            "USDT"
        )

        print(
            "Trades       :",
            data["trades"]
        )

        print(
            "Wins         :",
            data["wins"]
        )

        print(
            "Losses       :",
            data["losses"]
        )

        print(
            "Win Rate     :",
            data["win_rate"],
            "%"
        )


        print("==============================\n")



    def position(self):

        position = self.portfolio.open_position


        print("\n==============================")
        print("     OPEN POSITION")
        print("==============================")


        if position is None:

            print(
                "Açık pozisyon yok."
            )

        else:

            for key, value in position.items():

                print(
                    key,
                    ":",
                    value
                )


        print("==============================\n")