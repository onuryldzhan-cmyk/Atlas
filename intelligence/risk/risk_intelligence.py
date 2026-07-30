from __future__ import annotations

from datetime import datetime, UTC



class RiskIntelligence:


    VERSION = "2.0"



    def __init__(self):

        self.max_position_percent = 0.25

        self.daily_loss_limit = 0.05



    def analyze(

        self,

        decision,

        confidence,

        balance,

        price=65000,

        risk_level="MEDIUM"

    ):


        result = {


            "decision":

                decision,


            "risk_level":

                risk_level,


            "position_size":

                0,


            "stop_loss_price":

                0,


            "take_profit_price":

                0,


            "approved":

                False,


            "time":

                datetime.now(UTC).isoformat()

        }



        if decision != "BUY":

            return result



        if confidence >= 80:

            risk_percent = 0.05


        elif confidence >= 60:

            risk_percent = 0.03


        else:

            risk_percent = 0.01



        capital = balance * risk_percent



        max_position = balance * self.max_position_percent



        position_size = min(

            capital / 0.02,

            max_position

        )



        stop_loss = price * 0.98

        take_profit = price * 1.05



        result.update({


            "position_size":

                round(position_size,2),


            "stop_loss_price":

                round(stop_loss,2),


            "take_profit_price":

                round(take_profit,2),


            "approved":

                True,


            "risk_percent":

                risk_percent

        })



        return result