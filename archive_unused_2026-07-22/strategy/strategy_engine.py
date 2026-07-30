class StrategyEngine:


    def __init__(self):

        self.strategies = {

            "scalping": {
                "wins":0,
                "losses":0
            },

            "trend": {
                "wins":0,
                "losses":0
            },

            "reversal": {
                "wins":0,
                "losses":0
            }

        }



    def evaluate(self, analysis, score, risk):


        results = {}



        rsi = analysis["rsi"]

        macd = analysis["macd_signal"]

        ema = analysis["ema_signal"]



        # Scalping

        if rsi < 30:

            results["scalping"] = "BUY"

        elif rsi > 70:

            results["scalping"] = "SELL"

        else:

            results["scalping"] = "WAIT"



        # Trend

        if ema == "BUY" and macd == "BUY":

            results["trend"] = "BUY"

        elif ema == "SELL" and macd == "SELL":

            results["trend"] = "SELL"

        else:

            results["trend"] = "WAIT"



        # Reversal

        if rsi < 20:

            results["reversal"] = "WATCH BUY"

        elif rsi > 80:

            results["reversal"] = "WATCH SELL"

        else:

            results["reversal"] = "WAIT"



        return results