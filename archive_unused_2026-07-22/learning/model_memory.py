import json
import os


class ModelMemory:


    def __init__(self):

        self.file = "learning/model_memory.json"


        if not os.path.exists(self.file):

            with open(
                self.file,
                "w"
            ) as f:

                json.dump(
                    [],
                    f
                )



    def add_trade(
        self,
        data
    ):


        with open(
            self.file,
            "r"
        ) as f:

            memory = json.load(f)



        memory.append(data)



        with open(
            self.file,
            "w"
        ) as f:

            json.dump(
                memory,
                f,
                indent=4
            )



    def get_memory(self):

        with open(
            self.file,
            "r"
        ) as f:

            return json.load(f)