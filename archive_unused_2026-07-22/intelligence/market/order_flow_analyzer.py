class OrderFlowAnalyzer:


    def __init__(self):

        self.name = "Order Flow Analyzer"



    def analyze(
        self,
        data
    ):


        close = data["close"]

        volume = data["volume"]



        last_price = float(
            close.iloc[-1]
        )


        previous_price = float(
            close.iloc[-2]
        )



        last_volume = float(
            volume.iloc[-1]
        )



        avg_volume = float(
            volume.mean()
        )



        price_change = (

            (last_price - previous_price)

            /

            previous_price

        ) * 100



        volume_strength = (

            last_volume /

            avg_volume

        )



        buyer_power = 50

        seller_power = 50



        if price_change > 0:


            buyer_power += (

                price_change * 10

            )


            buyer_power += (

                volume_strength * 5

            )



        else:


            seller_power += abs(

                price_change * 10

            )


            seller_power += (

                volume_strength * 5

            )



        buyer_power = round(

            min(
                buyer_power,
                100
            ),

            2

        )


        seller_power = round(

            min(
                seller_power,
                100
            ),

            2

        )



        pressure = "NEUTRAL"



        score = 50



        if buyer_power > seller_power + 15:


            pressure = "BUY_PRESSURE"

            score = 75



        elif seller_power > buyer_power + 15:


            pressure = "SELL_PRESSURE"

            score = 25



        return {


            "buyer_power": buyer_power,

            "seller_power": seller_power,

            "pressure": pressure,

            "score": score

        }