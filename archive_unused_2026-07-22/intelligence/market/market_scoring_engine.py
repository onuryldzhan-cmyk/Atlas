class MarketScoringEngine:


    def calculate(self, market):


        score = 50


        # Volume

        if market["volume"]["signal"] == "STRONG":

            score += 15

        elif market["volume"]["signal"] == "WEAK":

            score -= 15


        # Order Flow

        if market["order_flow"]["pressure"] == "BUY_PRESSURE":

            score += 15

        elif market["order_flow"]["pressure"] == "SELL_PRESSURE":

            score -= 15


        # Structure

        if market["structure"]["trend"] == "UPTREND":

            score += 10

        elif market["structure"]["trend"] == "DOWNTREND":

            score -= 10


        # Support / Resistance

        if market["support_resistance"]["signal"] == "NEAR_SUPPORT":

            score += 10

        elif market["support_resistance"]["signal"] == "NEAR_RESISTANCE":

            score -= 10


        # Breakout

        if market["breakout"]["signal"] == "BREAKOUT_UP":

            score += 20

        elif market["breakout"]["signal"] == "BREAKOUT_DOWN":

            score -= 20


        # Volatility

        if market["volatility"]["signal"] == "HIGH":

            score -= 5

        elif market["volatility"]["signal"] == "LOW":

            score += 5


        score = max(

            0,

            min(

                score,

                100

            )

        )


        return score