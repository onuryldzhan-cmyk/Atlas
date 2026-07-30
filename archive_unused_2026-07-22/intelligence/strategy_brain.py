from intelligence.strategy_memory import StrategyMemory
from analytics.ai_performance import AIPerformance



class StrategyBrain:


    def __init__(self):

        self.memory = StrategyMemory()

        self.ai_performance = AIPerformance()



    def choose_strategy(
        self,
        analysis,
        score,
        risk
    ):


        rsi = analysis["rsi"]

        macd = analysis["macd_signal"]

        ema = analysis["ema_signal"]



        strategies = {

            "scalping":50,

            "trend":50,

            "reversal":50

        }



        # Teknik analiz etkisi


        if rsi < 30:

            strategies["scalping"] += 25


        elif rsi > 70:

            strategies["scalping"] += 20



        if ema == macd:

            strategies["trend"] += 25



        if rsi < 20 or rsi > 80:

            strategies["reversal"] += 30




        # Gerçek trade hafızası


        history = self.memory.performance()


        for name in strategies:


            total = (
                history[name]["wins"]
                +
                history[name]["losses"]
            )


            if total > 0:


                win_rate = (

                    history[name]["wins"]

                    /

                    total

                ) * 100



                strategies[name] += (
                    win_rate * 0.2
                )




        # AI simülasyon öğrenmesi


        try:

            ai_history = self.ai_performance.report()



            for name in strategies:


                if name in ai_history.get(
                    "strategies",
                    {}
                ):


                    data = ai_history["strategies"][name]


                    total = (
                        data["wins"]
                        +
                        data["losses"]
                    )


                    if total > 0:


                        ai_rate = (

                            data["wins"]

                            /

                            total

                        ) * 100



                        # AI öğrenme ağırlığı

                        strategies[name] += (
                            ai_rate * 0.3
                        )


        except Exception:


            pass




        best = max(
            strategies,
            key=strategies.get
        )



        confidence = round(
            strategies[best],
            2
        )



        return {


            "strategy": best,


            "confidence": confidence,


            "scores": strategies,


            "memory": history[best]

        }