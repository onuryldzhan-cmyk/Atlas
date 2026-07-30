"""
Atlas Trade Plan Engine v2.0

Professional trading plan generator.

Responsibilities
-----------------

- Dynamic profit target calculation
- AI confidence adjustment
- Risk based planning
- Partial exit strategy
- Runner position management
- Trailing stop configuration
- Re-entry rules

"""


import logging


logger = logging.getLogger(
    "AtlasAI.TradePlan"
)



class TradePlanEngine:


    def __init__(self):

        self.version = "2.0"


        logger.info(
            "Trade Plan Engine v2.0 initialized"
        )



    # =====================================================
    # CREATE PLAN
    # =====================================================


    def create_plan(

        self,

        symbol,

        entry_price,

        analysis

    ):


        """
        Example analysis:

        {
            "expected_growth":30,
            "confidence":82,
            "risk":"MEDIUM",
            "market_regime":"BULLISH"
        }

        """


        target = self._calculate_target(
            analysis
        )


        confidence = analysis.get(
            "confidence",
            50
        )


        risk = analysis.get(
            "risk",
            "MEDIUM"
        )


        regime = analysis.get(
            "market_regime",
            "NORMAL"
        )



        levels = self._create_levels(

            target,

            confidence,

            risk

        )



        runner = self._calculate_runner(

            confidence,

            regime

        )



        trailing = self._create_trailing(

            target

        )



        reentry = self._create_reentry(

            confidence

        )



        plan = {


            "symbol":
            symbol,


            "entry_price":
            entry_price,


            "target_profit":
            target,


            "confidence":
            confidence,


            "risk":
            risk,


            "market_regime":
            regime,


            "profit_levels":
            levels,


            "runner_percentage":
            runner,


            "trailing":
            trailing,


            "reentry":
            reentry,


            "status":
            "ACTIVE"

        }



        logger.info(

            f"[PLAN] {symbol} target +{target}% confidence {confidence}"

        )


        return plan




    # =====================================================
    # TARGET
    # =====================================================


    def _calculate_target(

        self,

        analysis

    ):


        target = analysis.get(

            "expected_growth",

            5

        )


        if target < 3:

            target = 3



        if target > 100:

            target = 100



        return round(

            target,

            2

        )




    # =====================================================
    # PROFIT LEVELS
    # =====================================================


    def _create_levels(

        self,

        target,

        confidence,

        risk

    ):


        levels = []



        if target <= 5:


            levels.append(

                {

                    "trigger":
                    target,

                    "sell_percent":
                    100

                }

            )


            return levels




        if target <= 15:


            ratios = [

                (0.40,30),

                (0.70,30),

                (1.00,40)

            ]


        else:


            ratios = [

                (0.20,15),

                (0.40,20),

                (0.70,30),

                (1.00,20)

            ]



        for ratio, sell in ratios:


            levels.append(

                {


                    "trigger":

                    round(

                        target * ratio,

                        2

                    ),


                    "sell_percent":

                    sell


                }

            )



        return levels




    # =====================================================
    # RUNNER
    # =====================================================


    def _calculate_runner(

        self,

        confidence,

        regime

    ):


        runner = 10



        if confidence >= 80:

            runner += 10



        if regime == "BULLISH":

            runner += 10



        if runner > 35:

            runner = 35



        return runner




    # =====================================================
    # TRAILING
    # =====================================================


    def _create_trailing(

        self,

        target

    ):


        return {


            "enabled":
            True,


            "activation":

            round(

                target * 0.5,

                2

            ),


            "distance":

            5


        }




    # =====================================================
    # REENTRY
    # =====================================================


    def _create_reentry(

        self,

        confidence

    ):


        return {


            "enabled":
            True,


            "minimum_confidence":

            max(

                70,

                confidence - 10

            ),


            "require_trend_confirmation":

            True


        }