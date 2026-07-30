"""
Atlas AI Risk Manager v4

Adaptive Hedge Fund Capital Protection
"""


class RiskManager:


    def __init__(
        self,
        max_risk=0.02
    ):

        self.max_risk = max_risk



    def calculate(
        self,
        capital: float,
        entry_price: float,
        action: str,
        confidence: float
    ):


        if action == "BEKLE":

            return {

                "approved": False,

                "reason":
                "No trade signal"

            }



        if entry_price <= 0:

            return {

                "approved": False,

                "reason":
                "Geçersiz giriş fiyatı"

            }



        # =========================
        # ADAPTIVE RISK ENGINE
        # =========================


        if confidence >= 90:

            risk_percent = 0.02
            stop_percent = 0.015
            target_percent = 0.05



        elif confidence >= 75:

            risk_percent = 0.015
            stop_percent = 0.02
            target_percent = 0.045



        elif confidence >= 65:

            risk_percent = 0.01
            stop_percent = 0.025
            target_percent = 0.05



        elif confidence >= 55:

            risk_percent = 0.005
            stop_percent = 0.02
            target_percent = 0.04



        else:

            return {

                "approved": False,

                "reason":
                "Confidence düşük"

            }



        risk_amount = capital * risk_percent



        # =========================
        # PRICE LEVELS
        # =========================


        if action == "BUY":


            stop_loss = entry_price * (
                1 - stop_percent
            )


            take_profit = entry_price * (
                1 + target_percent
            )



        elif action == "SELL":


            stop_loss = entry_price * (
                1 + stop_percent
            )


            take_profit = entry_price * (
                1 - target_percent
            )


        else:

            return {

                "approved": False,

                "reason":
                "Geçersiz işlem yönü"

            }



        risk_distance = abs(
            entry_price - stop_loss
        )


        reward_distance = abs(
            take_profit - entry_price
        )



        risk_reward = round(
            reward_distance / risk_distance,
            2
        )



        # =========================
        # REWARD FILTER
        # =========================


        if risk_reward < 1.5:

            return {

                "approved": False,

                "reason":
                "Risk Reward yetersiz",

                "risk_reward":
                risk_reward

            }



        # =========================
        # POSITION SIZE
        # =========================


        if risk_distance == 0:

            position_size = 0


        else:

            position_size = (
                risk_amount /
                risk_distance
            )



        return {


            "approved": True,


            "risk_amount":
            round(
                risk_amount,
                2
            ),


            "position_size":
            round(
                position_size,
                6
            ),


            "stop_loss":
            round(
                stop_loss,
                4
            ),


            "take_profit":
            round(
                take_profit,
                4
            ),


            "risk_reward":
            risk_reward,


            "risk_percent":
            risk_percent * 100,


            "confidence":
            confidence

        }