"""
Market Events
"""


from .base_event import BaseEvent



class MarketUpdateEvent(BaseEvent):


    def __init__(
            self,
            symbol,
            price,
            data=None
    ):

        super().__init__(
            "MARKET_UPDATE"
        )


        self.symbol = symbol

        self.price = price

        self.data = data


    def info(self):

        base = super().info()


        base.update({

            "symbol": self.symbol,

            "price": self.price

        })


        return base