"""
Atlas Market Scanner v3.0

Institutional market scanning engine.

Finds:

- Liquid assets
- Strong trends
- Momentum opportunities
- Volume expansions

"""


import logging


logger = logging.getLogger(
    "AtlasAI.MarketScanner"
)



class MarketScanner:


    def __init__(
        self,
        opportunity_engine
    ):


        self.opportunity_engine = opportunity_engine


        self.min_volume = 10_000_000


        logger.info(
            "Market Scanner v3.0 initialized"
        )



    # ==================================
    # SCAN MARKET
    # ==================================


    def scan(

        self,

        markets

    ):


        opportunities=[]



        for symbol, data in markets.items():


            if not self._liquidity_check(
                data
            ):

                continue



            if not self._trend_check(
                data
            ):

                continue



            result = self.opportunity_engine.analyze(

                symbol,

                data

            )



            if result["decision"] != "IGNORE":


                opportunities.append(
                    result
                )




        opportunities.sort(

            key=lambda x:x["score"],

            reverse=True

        )



        logger.info(

            f"Scanner found {len(opportunities)} opportunities"

        )



        return opportunities




    # ==================================
    # LIQUIDITY
    # ==================================


    def _liquidity_check(

        self,

        data

    ):


        volume=data.get(

            "volume_24h",

            0

        )


        return volume >= self.min_volume




    # ==================================
    # TREND
    # ==================================


    def _trend_check(

        self,

        data

    ):


        return data.get(

            "trend"

        ) != "BEARISH"