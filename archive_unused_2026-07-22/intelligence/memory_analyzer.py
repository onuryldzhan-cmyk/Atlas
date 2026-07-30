from intelligence.learning_memory import LearningMemory



class MemoryAnalyzer:


    def __init__(self):

        self.memory = LearningMemory()



    def analyze_coin(self, symbol):


        history = self.memory.get_history()


        trades = []


        for trade in history:


            if trade.get("symbol") == symbol:

                trades.append(trade)



        total = len(trades)


        wins = 0

        losses = 0



        for trade in trades:


            if trade.get("result") == "WIN":

                wins += 1


            elif trade.get("result") == "LOSS":

                losses += 1



        win_rate = 0


        if total > 0:


            win_rate = round(

                (wins / total) * 100,

                2

            )



        return {


            "symbol": symbol,

            "total_trades": total,

            "wins": wins,

            "losses": losses,

            "win_rate": win_rate

        }





    def decision_score(self, symbol):


        data = self.analyze_coin(symbol)


        score = 50



        if data["total_trades"] == 0:


            return {


                "score": score,

                "reason": "Yeterli geçmiş veri yok."

            }



        if data["win_rate"] >= 70:


            score += 30



        elif data["win_rate"] >= 55:


            score += 15



        elif data["win_rate"] < 40:


            score -= 25



        return {


            "score": max(0, min(score,100)),

            "memory": data

        }