"""
============================================================
ATLAS CAPITAL MANAGER v1.0
============================================================

Professional capital allocation engine.

Responsibilities:

- Portfolio balance tracking
- Risk based allocation
- Position sizing
- Exposure control
- Capital protection


Flow:

Decision
    |
Risk Level
    |
Capital Manager
    |
Position Size
    |
Execution


============================================================
"""


from __future__ import annotations

import logging
from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.CapitalManager"
)




class CapitalManager:


    VERSION = "1.0"



    def __init__(

        self,

        balance=10000,

        max_position_percent=25

    ):


        self.balance = float(balance)

        self.initial_balance = float(balance)

        self.max_position_percent = max_position_percent


        self.allocated = {}

        self.history = []



        logger.info(

            "Atlas Capital Manager v1.0 initialized"

        )






    # =====================================================
    # CAPITAL ALLOCATION
    # =====================================================


    def allocate(

        self,

        symbol,

        confidence,

        price,

        risk_level="MEDIUM"

    ):



        if price is None or price <= 0:


            return {


                "success":

                False,


                "error":

                "Invalid price"


            }




        risk_multiplier = self.risk_multiplier(

            risk_level

        )



        confidence_multiplier = min(

            confidence / 100,

            1

        )



        allocation_percent = (

            self.max_position_percent

            *

            risk_multiplier

            *

            confidence_multiplier

        )




        amount = (

            self.balance

            *

            allocation_percent

            /

            100

        )




        if amount <= 0:


            return {


                "success":

                False,


                "error":

                "Zero allocation"


            }






        self.allocated[symbol] = amount



        self.history.append({


            "symbol":

            symbol,


            "amount":

            amount,


            "risk":

            risk_level,


            "confidence":

            confidence,


            "time":

            datetime.now(

                UTC

            ).isoformat()


        })





        return {


            "success":

            True,


            "symbol":

            symbol,


            "amount":

            round(

                amount,

                2

            ),


            "allocation_percent":

            round(

                allocation_percent,

                2

            )


        }







    # =====================================================
    # RISK MODEL
    # =====================================================


    def risk_multiplier(

        self,

        risk_level

    ):



        level = str(

            risk_level

        ).upper()



        if level == "LOW":

            return 0.5



        if level == "MEDIUM":

            return 0.75



        if level == "HIGH":

            return 1



        return 0.25







    # =====================================================
    # PORTFOLIO STATUS
    # =====================================================


    def status(self):


        return {


            "version":

            self.VERSION,


            "balance":

            self.balance,


            "allocated_positions":

            len(

                self.allocated

            ),


            "allocated":

            self.allocated


        }