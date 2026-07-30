from exchange.exchange_adapter import ExchangeAdapter



class DataProvider:


    def __init__(self):

        self.exchange = ExchangeAdapter()

        print(
            "Data Provider hazır"
        )



    def get_market_data(
        self,
        symbol,
        timeframe="5m",
        limit=100
    ):


        data = self.exchange.get_ohlcv(

            symbol,

            timeframe,

            limit

        )


        return data