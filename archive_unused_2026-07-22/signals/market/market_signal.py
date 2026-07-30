from signals.base_signal import BaseSignal



class MarketSignal(BaseSignal):


    def __init__(self):

        super().__init__(
            "Market Signal"
        )



    def generate(
        self,
        market
    ):


        score = 50

        reasons = []



        market_score = market.get(
            "market_score",
            50
        )


        order_flow = market.get(
            "order_flow",
            "NEUTRAL"
        )


        structure = market.get(
            "structure",
            "SIDEWAYS"
        )



        # Market Score

        if market_score >= 60:

            score += 20

            reasons.append(
                "Market güçlü"
            )


        elif market_score <= 40:

            score -= 20

            reasons.append(
                "Market zayıf"
            )



        # Order Flow

        if order_flow == "BUY":

            score += 15

            reasons.append(
                "Order flow alış baskısı"
            )


        elif order_flow == "SELL":

            score -= 15

            reasons.append(
                "Order flow satış baskısı"
            )



        # Market Structure

        if structure == "UPTREND":

            score += 15

            reasons.append(
                "Yükselen piyasa yapısı"
            )


        elif structure == "DOWNTREND":

            score -= 15

            reasons.append(
                "Düşen piyasa yapısı"
            )



        score = max(
            0,
            min(
                score,
                100
            )
        )



        if score >= 65:

            signal = "BUY"


        elif score <= 35:

            signal = "SELL"


        else:

            signal = "HOLD"



        return self.result(

            signal,

            score,

            ", ".join(
                reasons
            )

        )