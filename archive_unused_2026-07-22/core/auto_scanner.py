import time
import json
import os
from datetime import datetime



class AutoScanner:


    def __init__(self, engine):

        self.engine = engine


        self.coins = [

            "BTCUSDT",
            "ETHUSDT",
            "BNBUSDT"

        ]


        self.file = "data/auto_history.json"


        os.makedirs(
            "data",
            exist_ok=True
        )


        if not os.path.exists(self.file):

            with open(
                self.file,
                "w"
            ) as f:

                json.dump(
                    [],
                    f,
                    indent=4
                )



    def save_result(self, result):


        try:

            with open(
                self.file,
                "r"
            ) as f:

                data = json.load(f)



            record = {

                "time": str(datetime.now()),

                "symbol": result.get(
                    "symbol"
                ),

                "price": result.get(
                    "price"
                ),

                "decision": result.get(
                    "ai_decision",
                    {}
                ).get(
                    "decision"
                ),

                "confidence": result.get(
                    "ai_decision",
                    {}
                ).get(
                    "confidence"
                ),

                "strategy": result.get(
                    "strategy",
                    {}
                ).get(
                    "strategy"
                ),

                "risk": result.get(
                    "risk",
                    {}
                ).get(
                    "level"
                )

            }


            data.append(
                record
            )


            with open(
                self.file,
                "w"
            ) as f:

                json.dump(
                    data,
                    f,
                    indent=4
                )


        except Exception as e:

            print(
                "AUTO kayıt hatası:",
                e
            )



    def analyze_coin(self, symbol):


        try:


            print("\n================================")
            print(
                symbol,
                "analiz ediliyor..."
            )
            print("================================")


            result = self.engine.start(
                symbol
            )


            self.save_result(
                result
            )


            print("\n------------------------------")
            print(
                "AUTO ANALİZ:",
                symbol
            )


            print(
                "Karar:",
                result["ai_decision"]["decision"]
            )


            print(
                "Güven:",
                result["ai_decision"]["confidence"]
            )


            print(
                "Strateji:",
                result["strategy"]["strategy"]
            )


            print(
                "Risk:",
                result["risk"]["level"]
            )


            print("------------------------------")



        except Exception as e:

            print(
                "AUTO HATA:",
                symbol,
                e
            )



    def start(self):


        print("\n================================")
        print("      ATLAS AUTO SCANNER")
        print("================================")


        print(
            "Takip edilen coinler:",
            self.coins
        )


        for coin in self.coins:


            self.analyze_coin(
                coin
            )


            time.sleep(2)



        print("\nAUTO TARAMA TAMAMLANDI")