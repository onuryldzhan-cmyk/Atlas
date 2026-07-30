from __future__ import annotations

from datetime import datetime, UTC


class CoinScanner:


    VERSION = "1.0"



    def __init__(self):

        self.watchlist = [

            "BTCUSDT",
            "ETHUSDT",
            "BNBUSDT",
            "SOLUSDT",
            "XRPUSDT"

        ]



    def get_watchlist(self):

        return self.watchlist



    def analyze_coin(
        self,
        symbol,
        price,
        volume,
        change
    ):


        score = 0



        if change > 0:

            score += 30


        if volume > 0:

            score += 20


        if abs(change) > 2:

            score += 20



        if score >= 60:

            risk = "MEDIUM"


        elif score >= 40:

            risk = "HIGH"


        else:

            risk = "LOW"



        return {


            "symbol":
                symbol,


            "price":
                price,


            "volume":
                volume,


            "change":
                change,


            "score":
                score,


            "risk":
                risk,


            "time":
                datetime.now(UTC).isoformat()


        }