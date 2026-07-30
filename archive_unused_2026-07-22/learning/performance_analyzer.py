class PerformanceAnalyzer:


    def __init__(self):

        pass



    def analyze(self, trades):


        total = len(trades)


        if total == 0:

            return {

                "total_trades": 0,

                "win_rate": 0,

                "profit": 0,

                "message": "Henüz yeterli işlem verisi yok."

            }



        wins = 0

        losses = 0

        profit = 0



        for trade in trades:


            result = trade.get(
                "result",
                0
            )


            profit += result



            if result > 0:

                wins += 1


            else:

                losses += 1



        win_rate = (
            wins / total
        ) * 100



        if win_rate >= 60:

            message = (
                "Strateji başarılı çalışıyor."
            )


        elif win_rate >= 45:

            message = (
                "Strateji dengeli durumda."
            )


        else:

            message = (
                "Strateji zayıf, optimizasyon gerekli."
            )



        return {


            "total_trades": total,


            "wins": wins,


            "losses": losses,


            "win_rate": round(
                win_rate,
                2
            ),


            "profit": round(
                profit,
                2
            ),


            "message": message

        }