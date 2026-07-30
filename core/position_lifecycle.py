"""
Atlas Position Lifecycle v2.0

Professional position state manager.

Responsibilities
-----------------

- Track open positions
- Track partial exits
- Manage runner mode
- Track highest price
- Activate trailing
- Prepare re-entry

"""


import logging
from datetime import datetime


logger = logging.getLogger(
    "AtlasAI.PositionLifecycle"
)



class PositionLifecycle:


    def __init__(self):

        self.version = "2.0"


        self.positions = {}


        logger.info(
            "Position Lifecycle v2.0 initialized"
        )



    # =====================================================
    # CREATE POSITION
    # =====================================================


    def create(

        self,

        symbol,

        entry_price,

        amount,

        plan

    ):


        position = {


            "symbol":
            symbol,


            "entry_price":
            entry_price,


            "initial_amount":
            amount,


            "remaining_amount":
            amount,


            "sold_percent":
            0,


            "plan":
            plan,


            "state":
            "ACTIVE",


            "highest_price":
            entry_price,


            "lowest_price":
            entry_price,


            "trailing_active":
            False,


            "reentry_allowed":
            False,


            "created":

            datetime.now().isoformat()


        }



        self.positions[symbol] = position



        logger.info(

            f"[POSITION OPEN] {symbol}"

        )


        return position




    # =====================================================
    # UPDATE PRICE
    # =====================================================


    def update(

        self,

        symbol,

        price

    ):


        position = self.positions.get(

            symbol

        )


        if not position:

            return None



        if price > position["highest_price"]:


            position["highest_price"] = price



        if price < position["lowest_price"]:


            position["lowest_price"] = price




        plan = position["plan"]


        target = plan.get(

            "target_profit",

            0

        )


        profit = self._profit(

            position["entry_price"],

            price

        )



        if profit >= target * 0.5:


            position["trailing_active"] = True




        return position





    # =====================================================
    # PARTIAL EXIT
    # =====================================================


    def partial_exit(

        self,

        symbol,

        percent

    ):


        position = self.positions.get(

            symbol

        )


        if not position:

            return None



        position["sold_percent"] += percent



        if position["sold_percent"] >= 85:


            position["state"] = "RUNNER"



        logger.info(

            f"[PARTIAL EXIT] {symbol} {percent}%"

        )


        return position





    # =====================================================
    # CLOSE
    # =====================================================


    def close(

        self,

        symbol

    ):


        position = self.positions.get(

            symbol

        )


        if position:


            position["state"] = "CLOSED"



            logger.info(

                f"[POSITION CLOSED] {symbol}"

            )



        return position




    # =====================================================
    # GET
    # =====================================================


    def get(

        self,

        symbol

    ):


        return self.positions.get(

            symbol

        )




    # =====================================================
    # PROFIT
    # =====================================================


    def _profit(

        self,

        entry,

        price

    ):


        return round(

            (

                (price-entry)

                /

                entry

            )

            *

            100,

            2

        )