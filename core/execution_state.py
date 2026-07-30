"""
============================================================
ATLAS EXECUTION STATE v2.1
============================================================

Central execution persistence layer.

Responsibilities:

- Active position storage
- Trade lifecycle tracking
- Recovery
- Persistence
- Audit compatibility

============================================================
"""


from pathlib import Path
from datetime import datetime, UTC

import json
import threading



class ExecutionState:



    VERSION = "2.1"



    def __init__(

        self,

        storage="database",

        audit=None

    ):


        self.lock = threading.RLock()


        self.audit = audit


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

        self.recovered = False


        self.load()



    # ==================================================
    # ADD POSITION
    # ==================================================


    def add(

        self,

        trade

    ):


        with self.lock:


            symbol = trade.get(

                "symbol"

            )


            self.active[symbol] = trade



            self.history.append(

                {

                "event":

                "OPEN",


                "symbol":

                symbol,


                "trade":

                trade,


                "time":

                self.time()

                }

            )



            self.audit_event(

                "POSITION_OPENED",

                trade

            )


            self.save()



            return trade





    # ==================================================
    # CLOSE POSITION
    # ==================================================


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



            event = {


                "event":

                "CLOSE",


                "symbol":

                symbol,


                "result":

                result,


                "time":

                self.time()


            }



            self.history.append(

                event

            )


            self.audit_event(

                "POSITION_CLOSED",

                event

            )


            self.save()



            return trade





    # ==================================================
    # CHECK
    # ==================================================


    def exists(

        self,

        symbol

    ):


        return symbol in self.active





    def get(

        self,

        symbol

    ):


        return self.active.get(

            symbol

        )





    # ==================================================
    # RECOVERY
    # ==================================================


    def recover(self):


        self.load()


        self.recovered = True



        self.audit_event(

            "RECOVERY",

            {

            "active":

            len(self.active)

            }

        )


        return self.active





    # ==================================================
    # STORAGE
    # ==================================================


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

                self.history,


                "updated":

                self.time()


                },


                f,

                indent=4,

                default=str

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





    # ==================================================
    # AUDIT
    # ==================================================


    def audit_event(

        self,

        event,

        data

    ):


        if self.audit:


            if hasattr(

                self.audit,

                "record"

            ):


                self.audit.record(

                    event,

                    data

                )





    def time(self):


        return datetime.now(

            UTC

        ).isoformat()





    # ==================================================
    # STATUS
    # ==================================================


    def status(self):


        return {


            "version":

            self.VERSION,


            "active":

            len(self.active),


            "history":

            len(self.history),


            "recovered":

            self.recovered,


            "file":

            str(self.file)

        }