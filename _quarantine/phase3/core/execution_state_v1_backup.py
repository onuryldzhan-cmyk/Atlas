"""
============================================================
ATLAS EXECUTION STATE v1.0
============================================================

Central execution state storage.

Responsibilities:

- Active trades
- Execution history
- Recovery
- Persistence

============================================================
"""


from pathlib import Path
import json
import threading

from datetime import datetime, UTC



class ExecutionState:



    VERSION = "1.0"



    def __init__(

        self,

        storage="database"

    ):


        self.lock = threading.RLock()


        self.path = Path(storage)

        self.path.mkdir(

            exist_ok=True

        )


        self.file = (

            self.path /

            "execution_state.json"

        )


        self.active = {}

        self.history = []


        self.load()





    def add(

        self,

        trade

    ):


        with self.lock:


            symbol = trade["symbol"]


            self.active[symbol] = trade


            self.history.append({

                "event":

                "OPEN",


                "trade":

                trade,


                "time":

                datetime.now(

                    UTC

                ).isoformat()

            })


            self.save()





    def close(

        self,

        symbol,

        result

    ):


        with self.lock:


            trade = self.active.pop(

                symbol,

                None

            )


            self.history.append({

                "event":

                "CLOSE",


                "symbol":

                symbol,


                "result":

                result,


                "time":

                datetime.now(

                    UTC

                ).isoformat()

            })


            self.save()


            return trade





    def exists(

        self,

        symbol

    ):


        return symbol in self.active






    def save(self):


        with open(

            self.file,

            "w",

            encoding="utf-8"

        ) as f:


            json.dump(

                {

                "version":

                self.VERSION,


                "active":

                self.active,


                "history":

                self.history

                },


                f,

                indent=4

            )





    def load(self):


        if not self.file.exists():

            return


        try:


            with open(

                self.file,

                "r",

                encoding="utf-8"

            ) as f:


                data=json.load(f)



            self.active=data.get(

                "active",

                {}

            )


            self.history=data.get(

                "history",

                []

            )


        except Exception:


            self.active={}

            self.history=[]





    def status(self):


        return {


            "version":

            self.VERSION,


            "active":

            len(self.active),


            "history":

            len(self.history),


            "file":

            str(self.file)

        }