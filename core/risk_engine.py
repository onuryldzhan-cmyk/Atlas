"""
============================================================
ATLAS RISK ENGINE v1.0
============================================================

Professional risk control layer.

Responsibilities:

- Validate trade decisions
- Control exposure
- Limit positions
- Protect capital
- Block dangerous trades


Flow:

Decision
    |
Risk Engine
    |
Capital Manager
    |
Execution


============================================================
"""


from __future__ import annotations


import logging
from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.RiskEngine"
)





class RiskEngine:


    VERSION = "1.0"




    def __init__(

        self,

        max_positions=5,

        max_daily_loss_percent=5,

        min_confidence=60

    ):


        self.max_positions = max_positions

        self.max_daily_loss_percent = max_daily_loss_percent

        self.min_confidence = min_confidence


        self.open_positions = 0

        self.daily_loss = 0


        self.approved = 0

        self.blocked = 0



        logger.info(

            "Atlas Risk Engine v1.0 initialized"

        )







    # =====================================================
    # MAIN VALIDATION
    # =====================================================


    def validate(

        self,

        decision

    ):


        action = decision.get(

            "action"

        )



        confidence = decision.get(

            "confidence",

            0

        )





        # HOLD işlemleri engelleme


        if action != "BUY":


            return {


                "approved":

                False,


                "reason":

                "No trade action"


            }






        # Confidence kontrolü


        if confidence < self.min_confidence:


            self.blocked += 1


            return {


                "approved":

                False,


                "reason":

                "Low confidence"


            }







        # Pozisyon limiti


        if self.open_positions >= self.max_positions:


            self.blocked += 1


            return {


                "approved":

                False,


                "reason":

                "Maximum positions reached"


            }







        # Günlük zarar limiti


        if self.daily_loss >= self.max_daily_loss_percent:


            self.blocked += 1


            return {


                "approved":

                False,


                "reason":

                "Daily loss limit reached"


            }








        self.approved += 1



        return {


            "approved":

            True,


            "risk":

            "ACCEPTED",


            "time":

            datetime.now(

                UTC

            ).isoformat()


        }







    # =====================================================
    # POSITION TRACKING
    # =====================================================


    def position_opened(self):


        self.open_positions += 1





    def position_closed(self):


        if self.open_positions > 0:

            self.open_positions -= 1







    # =====================================================
    # LOSS UPDATE
    # =====================================================


    def update_loss(

        self,

        loss_percent

    ):


        self.daily_loss += loss_percent






    # =====================================================
    # STATUS
    # =====================================================


    def status(self):


        return {


            "version":

            self.VERSION,


            "open_positions":

            self.open_positions,


            "daily_loss":

            self.daily_loss,


            "approved":

            self.approved,


            "blocked":

            self.blocked

        }