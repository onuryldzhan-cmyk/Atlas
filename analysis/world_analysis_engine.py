"""
Atlas AI
World Analysis Engine v1.0

Market environment intelligence layer.
"""

from datetime import datetime, timezone


class WorldAnalysisEngine:


    VERSION = "1.0"


    def __init__(self):

        self.name = "World Analysis Engine"


    def build_market_data(
        self,
        symbol,
        price,
        analysis,
        score
    ):


        return {


            "symbol": symbol,

            "price": price,


            "technical_score": score,


            "rsi":
                analysis.get(
                    "rsi"
                ),


            "ema20":
                analysis.get(
                    "ema20"
                ),


            "ema50":
                analysis.get(
                    "ema50"
                ),


            "adx":
                analysis.get(
                    "adx"
                ),


            "trend":
                analysis.get(
                    "trend"
                ),


            "macro_score": 0.5,


            "sentiment_score": 0.5,


            "risk_score": 0.5,


            "timestamp":
                datetime.now(
                    timezone.utc
                ).isoformat()

        }



    def build_market_state(
        self,
        market_data
    ):


        return {


            "symbol":
                market_data["symbol"],


            "price":
                market_data["price"],


            "rsi":
                market_data["rsi"],


            "trend":
                market_data["trend"],


            "score":
                market_data["technical_score"],


            "timestamp":
                market_data["timestamp"]

        }