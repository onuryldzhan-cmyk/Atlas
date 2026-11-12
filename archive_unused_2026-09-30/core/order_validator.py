"""
============================================================
ATLAS ORDER VALIDATOR v1.0
============================================================
"""


class OrderValidator:



    VERSION = "1.0"



    def validate(
        self,
        decision
    ):


        errors = []


        symbol = decision.get(
            "symbol"
        )


        action = decision.get(
            "action"
        )


        confidence = decision.get(
            "confidence",
            0
        )


        price = decision.get(
            "price",
            0
        )



        if not symbol:

            errors.append(
                "Missing symbol"
            )


        if action not in [
            "BUY",
            "SELL",
            "CLOSE"
        ]:

            errors.append(
                "Invalid action"
            )


        if confidence <= 0:

            errors.append(
                "Invalid confidence"
            )


        if price <= 0:

            errors.append(
                "Invalid price"
            )



        return {


            "approved":

                len(errors)==0,


            "errors":

                errors

        }