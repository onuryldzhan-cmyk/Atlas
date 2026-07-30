"""
Atlas AI Capital Manager v8.0

Professional portfolio allocation engine.

Responsibilities
-----------------

- Dynamic capital allocation
- Risk pool management
- Position sizing
- Exposure control
- LONG / SHORT support
- Confidence based allocation
- Stop loss calculation
- Persistent portfolio state
- ExecutionManager compatibility


Architecture

Decision
   |
   v
ExecutionManager
   |
   v
CapitalManager
   |
   v
Position Size
   |
   v
PaperTrader / LiveTrader


"""


from __future__ import annotations


import json
import os
import logging


from datetime import datetime, timezone





logger = logging.getLogger(
    "AtlasAI.Capital"
)





class CapitalManager:



    VERSION = "8.0"




    def __init__(
        self,
        total_capital=10000,
        storage="data/capital_positions.json"
    ):


        self.total_capital = float(
            total_capital
        )


        self.storage = storage



        self.positions = {}



        self.max_positions = 10



        self.daily_loss = 0



        self.max_daily_loss = (

            self.total_capital * 0.03

        )



        # Risk allocation pools

        self.risk_pool = {


            "low":

            self.total_capital * 0.30,


            "medium":

            self.total_capital * 0.50,


            "high":

            self.total_capital * 0.20

        }




        self.used_risk = {


            "low":0,


            "medium":0,


            "high":0

        }




        self.load_positions()



        logger.info(

            f"Capital Manager v{self.VERSION} initialized "

            f"capital={self.total_capital}"

        )







    # ==================================================
    # RISK CLASSIFICATION
    # ==================================================


    def get_risk_level(
        self,
        confidence
    ):


        confidence=float(
            confidence
        )



        if confidence >= 80:

            return "high"


        if confidence >=60:

            return "medium"



        return "low"








    # ==================================================
    # POSITION SIZE
    # ==================================================


    def calculate_position_size(
        self,
        symbol,
        risk_level=None,
        confidence=70,
        price=None
    ):


        if not price:

            return 0



        allocation = self.allocate(

            symbol,

            confidence,

            price

        )



        if not allocation["success"]:


            logger.warning(

                allocation["error"]

            )

            return 0




        return allocation["amount"]







    # ==================================================
    # ALLOCATION
    # ==================================================


    def allocate(
        self,
        symbol,
        confidence,
        price
    ):


        confidence=float(
            confidence
        )


        price=float(
            price
        )



        risk=self.get_risk_level(
            confidence
        )



        ratios={


            "high":0.20,


            "medium":0.10,


            "low":0.05

        }




        capital=(

            self.total_capital

            *

            ratios[risk]

            *

            confidence/100

        )




        available=(

            self.risk_pool[risk]

            -

            self.used_risk[risk]

        )



        capital=min(

            capital,

            available

        )




        if capital <=0:


            return {


                "success":False,


                "error":

                "Risk pool exhausted"


            }





        amount=(

            capital / price

        )





        return {


            "success":True,


            "symbol":symbol,


            "risk":risk,


            "capital":round(
                capital,
                2
            ),


            "amount":round(
                amount,
                8
            ),


            "confidence":confidence


        }








    # ==================================================
    # POSITION CONTROL
    # ==================================================


    def can_open_position(
        self,
        symbol
    ):


        if symbol in self.positions:

            return False



        if len(self.positions)>=self.max_positions:

            return False



        if self.daily_loss >= self.max_daily_loss:

            return False



        return True







    # ==================================================
    # OPEN POSITION
    # ==================================================


    def open_position(
        self,
        symbol,
        price,
        amount=None,
        confidence=70,
        side="LONG"
    ):



        if not self.can_open_position(
            symbol
        ):


            return {


                "success":False,


                "error":

                "Position blocked"


            }






        if amount is None:


            amount=self.calculate_position_size(

                symbol,

                confidence=confidence,

                price=price

            )




        amount=float(
            amount
        )



        risk=self.get_risk_level(
            confidence
        )



        value=float(price)*amount




        stop_rate={


            "high":0.01,


            "medium":0.015,


            "low":0.02


        }[risk]



        if side=="SHORT":


            stop_loss=float(price)*(1+stop_rate)


        else:


            stop_loss=float(price)*(1-stop_rate)





        position={


            "symbol":

            symbol,


            "side":

            side,


            "entry_price":

            price,


            "amount":

            amount,


            "value":

            value,


            "confidence":

            confidence,


            "risk":

            risk,


            "stop_loss":

            stop_loss,


            "created":

            datetime.now(
                timezone.utc
            ).isoformat()


        }





        self.positions[symbol]=position



        self.used_risk[risk]+=value



        self.save_positions()



        logger.info(

            f"POSITION OPEN {symbol} "

            f"value={value}"

        )



        return {


            "success":True,


            "position":position


        }









    # ==================================================
    # PORTFOLIO STATUS
    # ==================================================


    def portfolio_value(self):


        value=self.total_capital



        for p in self.positions.values():

            value += p.get(
                "value",
                0
            )



        return round(
            value,
            2
        )







    def get_available_capital(self):


        used=sum(

            p.get(
                "value",
                0
            )

            for p in self.positions.values()

        )


        return {


            "total":

            self.total_capital,


            "used":

            round(
                used,
                2
            ),


            "available":

            round(
                self.total_capital-used,
                2
            ),


            "positions":

            len(self.positions)


        }








    def status(self):


        return {


            "version":

            self.VERSION,


            "capital":

            self.total_capital,


            "portfolio_value":

            self.portfolio_value(),


            "available":

            self.get_available_capital(),


            "positions":

            len(self.positions),


            "risk_usage":

            self.used_risk


        }







    # ==================================================
    # STORAGE
    # ==================================================


    def save_positions(self):


        try:


            os.makedirs(

                os.path.dirname(
                    self.storage
                ),

                exist_ok=True

            )



            with open(

                self.storage,

                "w",

                encoding="utf-8"

            ) as f:


                json.dump(

                    self.positions,

                    f,

                    indent=4

                )



        except Exception as e:


            logger.exception(e)








    def load_positions(self):


        if not os.path.exists(
            self.storage
        ):

            return



        try:


            with open(

                self.storage,

                "r",

                encoding="utf-8"

            ) as f:


                self.positions=json.load(f)



            for p in self.positions.values():


                risk=p.get(
                    "risk",
                    "low"
                )


                self.used_risk[risk]+=p.get(
                    "value",
                    0
                )



            logger.info(

                f"{len(self.positions)} positions loaded"

            )



        except Exception as e:


            logger.exception(e)






    def reset_daily(self):


        self.daily_loss=0






    def close_all_positions(self):


        self.positions={}


        self.used_risk={


            "low":0,


            "medium":0,


            "high":0


        }



        self.save_positions()