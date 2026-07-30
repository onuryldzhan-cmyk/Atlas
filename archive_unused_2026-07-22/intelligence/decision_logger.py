import json
import os
from datetime import datetime



class DecisionLogger:


    def __init__(self):

        self.file = "data/ai_decisions.json"


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



    def save(self, data):


        try:


            with open(
                self.file,
                "r"
            ) as f:

                history = json.load(f)



            data["time"] = str(
                datetime.now()
            )


            history.append(
                data
            )



            with open(
                self.file,
                "w"
            ) as f:

                json.dump(
                    history,
                    f,
                    indent=4
                )



            print(
                "AI karar hafızaya kaydedildi."
            )



        except Exception as e:


            print(
                "AI karar kayıt hatası:",
                e
            )



    def history(self):


        try:

            with open(
                self.file,
                "r"
            ) as f:

                return json.load(f)


        except Exception:


            return []