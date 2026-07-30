"""
Atlas Position Monitor v1.0

Professional position surveillance engine.

Responsibilities:

- Monitor open positions
- Update market prices
- Calculate PNL
- Detect exit signals
- Trigger close execution
- Report position health

Architecture:

Market Data
      |
Position Monitor
      |
Position Manager
      |
Exit Decision
      |
Execution Manager
      |
Trade Memory

"""


import logging
from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.PositionMonitor"
)



class PositionMonitor:



    VERSION = "1.0"



    def __init__(

        self,

        position_manager=None,

        execution_manager=None,

        price_provider=None

    ):


        self.position_manager = position_manager

        self.execution_manager = execution_manager

        self.price_provider = price_provider



        logger.info(
            "Atlas Position Monitor v1.0 initialized"
        )





    # ==========================================
    # SCAN ALL POSITIONS
    # ==========================================


    def scan(self):


        if not self.position_manager:


            return {


                "status":
                "NO_POSITION_MANAGER"

            }



        positions = (
            self.position_manager.positions
        )



        results = []



        for symbol in list(
            positions.keys()
        ):


            result = self.check_position(
                symbol
            )


            results.append(
                result
            )



        return {


            "time":
            datetime.now(
                UTC
            ).isoformat(),


            "checked":
            len(results),


            "results":
            results

        }





    # ==========================================
    # CHECK POSITION
    # ==========================================


    def check_position(

        self,

        symbol

    ):



        price = self.get_price(
            symbol
        )



        if price is None:


            return {


                "symbol":
                symbol,


                "status":
                "NO_PRICE"

            }




        update = self.position_manager.update(

            symbol,

            price

        )




        decision = update.get(
            "decision"
        )



        if decision:


            action = decision.get(
                "action"
            )


            if action == "CLOSE":


                close_result = (
                    self.close_position(
                        symbol,
                        decision
                    )
                )



                return {


                    "symbol":
                    symbol,


                    "price":
                    price,


                    "action":
                    "CLOSED",


                    "reason":
                    decision.get(
                        "reason"
                    ),


                    "result":
                    close_result

                }




        return {


            "symbol":
            symbol,


            "price":
            price,


            "pnl":
            update.get(
                "pnl"
            ),


            "action":
            "HOLD"

        }





    # ==========================================
    # PRICE SOURCE
    # ==========================================


    def get_price(

        self,

        symbol

    ):



        if self.price_provider:


            return self.price_provider.get_price(
                symbol
            )



        #
        # TEST FALLBACK
        #

        position = (

            self.position_manager.positions.get(
                symbol
            )

        )



        if position:


            return position["entry"]



        return None





    # ==========================================
    # CLOSE REQUEST
    # ==========================================


    def close_position(

        self,

        symbol,

        reason

    ):



        if not self.execution_manager:


            return {


                "status":
                "NO_EXECUTION"

            }



        return self.execution_manager.close_position(

            symbol

        )






    # ==========================================
    # STATUS
    # ==========================================


    def status(self):


        return {


            "version":
            self.VERSION,


            "active":
            self.position_manager is not None,


            "execution":
            self.execution_manager is not None

        }