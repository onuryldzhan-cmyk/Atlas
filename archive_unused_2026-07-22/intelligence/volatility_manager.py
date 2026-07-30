class VolatilityManager:


    def __init__(self):

        pass



    def calculate_risk(
        self,
        candles
    ):


        prices = []


        for candle in candles:

            prices.append(
                float(candle["close"])
            )



        if len(prices) < 20:

            return {

                "volatility": "LOW",

                "stop_percent": 0.5,

                "target_percent": 1

            }



        changes = []


        for i in range(1,len(prices)):

            change = abs(
                prices[i] - prices[i-1]
            ) / prices[i-1] * 100


            changes.append(change)



        average = sum(changes) / len(changes)



        if average < 0.2:


            return {

                "volatility": "LOW",

                "stop_percent": 0.4,

                "target_percent": 0.8

            }



        elif average < 0.8:


            return {

                "volatility": "NORMAL",

                "stop_percent": 0.7,

                "target_percent": 1.8

            }



        else:


            return {

                "volatility": "HIGH",

                "stop_percent": 1.2,

                "target_percent": 3

            }