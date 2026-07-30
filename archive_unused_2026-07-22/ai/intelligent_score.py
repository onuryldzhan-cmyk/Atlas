import json
import os


class IntelligentScore:


    def __init__(self):

        self.file = "database/model_memory.json"

        if not os.path.exists(self.file):

            self.file = "../database/model_memory.json"



    def get_bonus(self, signal):


        try:

            with open(self.file, "r") as f:

                memory = json.load(f)

        except Exception:

            return 0



        best = memory.get(
            "best_signal",
            ""
        )



        if signal == best:

            return 15



        return -10
