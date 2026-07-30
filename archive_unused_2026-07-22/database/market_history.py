import json
import os
from datetime import datetime


class MarketHistory:

    def __init__(self):

        self.file = "database/market_history.json"

        if not os.path.exists(self.file):

            with open(self.file, "w") as f:
                json.dump([], f)


    def save_candle(self, candle):

        with open(self.file, "r") as f:
            data = json.load(f)


        candle["time"] = str(datetime.now())

        data.append(candle)


        with open(self.file, "w") as f:
            json.dump(
                data,
                f,
                indent=4
            )


    def get_history(self):

        with open(self.file, "r") as f:
            return json.load(f)