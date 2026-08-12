"""
Atlas Candle Processor v2.0

Exchange candle normalization layer.

Responsibilities:

- Convert Binance candles
- Validate OHLCV
- Remove invalid candles
- Sort candles
- Prepare data for intelligence layer

"""

from __future__ import annotations

import logging
from datetime import datetime, timezone


logger = logging.getLogger(
    "AtlasAI.CandleProcessor"
)


class CandleProcessor:


    def __init__(self):

        self.version = "2.0"



    def normalize(
        self,
        candles
    ):

        if not candles:

            return []


        result = []


        for candle in candles:


            try:


                normalized = self._parse(
                    candle
                )


                if normalized:

                    result.append(
                        normalized
                    )


            except Exception as e:

                logger.warning(
                    f"Candle skipped: {e}"
                )



        result = self._clean(
            result
        )


        return result



    # =================================
    # PARSER
    # =================================


    def _parse(
        self,
        candle
    ):


        if isinstance(
            candle,
            list
        ):


            return {

                "timestamp":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),


                "open":
                    float(candle[1]),


                "high":
                    float(candle[2]),


                "low":
                    float(candle[3]),


                "close":
                    float(candle[4]),


                "volume":
                    float(candle[5])

            }



        elif isinstance(
            candle,
            dict
        ):


            return {

                "timestamp":
                    candle.get(
                        "timestamp",
                        datetime.now(
                            timezone.utc
                        ).isoformat()
                    ),


                "open":
                    float(
                        candle["open"]
                    ),


                "high":
                    float(
                        candle["high"]
                    ),


                "low":
                    float(
                        candle["low"]
                    ),


                "close":
                    float(
                        candle["close"]
                    ),


                "volume":
                    float(
                        candle.get(
                            "volume",
                            0
                        )
                    )

            }


        return None



    # =================================
    # VALIDATION
    # =================================


    def _clean(
        self,
        candles
    ):


        cleaned = []


        for c in candles:


            if (

                c["high"] < c["low"]

                or

                c["close"] <= 0

                or

                c["open"] <= 0

            ):

                continue



            cleaned.append(
                c
            )



        return cleaned



    # =================================
    # HELPERS
    # =================================


    def latest_price(
        self,
        candles
    ):


        if not candles:

            return None


        return candles[-1]["close"]



    def candle_count(
        self,
        candles
    ):


        return len(
            candles
        )