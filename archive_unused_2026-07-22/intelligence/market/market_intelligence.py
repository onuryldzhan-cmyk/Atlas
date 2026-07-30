from intelligence.market.volume_analyzer import VolumeAnalyzer
from intelligence.market.order_flow_analyzer import OrderFlowAnalyzer
from intelligence.market.market_structure_analyzer import MarketStructureAnalyzer
from intelligence.market.support_resistance_analyzer import SupportResistanceAnalyzer


class MarketIntelligence:


    def __init__(self):

        self.volume = VolumeAnalyzer()

        self.order_flow = OrderFlowAnalyzer()

        self.structure = MarketStructureAnalyzer()

        self.support_resistance = SupportResistanceAnalyzer()


        print(
            "Market Intelligence hazır"
        )



    def analyze(
        self,
        data
    ):


        volume = self.volume.analyze(
            data
        )


        order_flow = self.order_flow.analyze(
            data
        )


        structure = self.structure.analyze(
            data
        )


        support = self.support_resistance.analyze(
            data
        )


        score = 50


        # Volume

        if volume["signal"] == "STRONG":

            score += 15


        elif volume["signal"] == "WEAK":

            score -= 15



        # Order Flow

        if order_flow["pressure"] == "BUY_PRESSURE":

            score += 15


        elif order_flow["pressure"] == "SELL_PRESSURE":

            score -= 15



        # Trend

        if structure["trend"] == "UPTREND":

            score += 10


        elif structure["trend"] == "DOWNTREND":

            score -= 10



        # Support / Resistance

        if support["signal"] == "NEAR_SUPPORT":

            score += 10


        elif support["signal"] == "NEAR_RESISTANCE":

            score -= 10



        score = max(
            0,
            min(
                score,
                100
            )
        )



        return {

            "market_score": score,

            "volume": volume,

            "order_flow": order_flow,

            "structure": structure,

            "support_resistance": support

        }