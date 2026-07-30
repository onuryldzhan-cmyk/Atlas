class SmartExit:


    def __init__(self):

        self.trailing_active = False



    def check_exit(
        self,
        entry,
        current,
        signal,
        analysis
    ):


        profit_percent = (
            (current - entry) / entry
        ) * 100


        if signal == "SAT":

            profit_percent = (
                (entry - current) / entry
            ) * 100



        decision = {

            "exit": False,

            "reason": "",

            "profit_percent": round(
                profit_percent,
                3
            )

        }



        rsi = analysis.get(
            "rsi",
            50
        )


        trend = analysis.get(
            "trend",
            ""
        )



        # Kâr koruma

        if profit_percent >= 0.5:


            self.trailing_active = True


            decision["reason"] = (
                "Trailing stop aktif"
            )



        # Momentum kaybı


        if signal == "AL":


            if rsi > 75:

                decision["exit"] = True

                decision["reason"] = (
                    "RSI aşırı alım bölgesi"
                )



            if trend == "DUSUS":

                decision["exit"] = True

                decision["reason"] = (
                    "Trend dönüşü"
                )



        if signal == "SAT":


            if rsi < 25:

                decision["exit"] = True

                decision["reason"] = (
                    "RSI aşırı satım bölgesi"
                )



            if trend == "YUKSELIS":

                decision["exit"] = True

                decision["reason"] = (
                    "Trend dönüşü"
                )



        # Büyük kâr kilitleme


        if profit_percent >= 1:


            decision["exit"] = True

            decision["reason"] = (
                "Kâr hedefi kilitlendi"
            )



        return decision