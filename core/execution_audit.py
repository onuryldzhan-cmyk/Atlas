"""
============================================================
ATLAS EXECUTION AUDIT v1.0
============================================================

Professional execution event recorder.

Tracks:

- Open trades
- Closed trades
- Errors
- Risk blocks
- Recovery events

============================================================
"""


from pathlib import Path
from datetime import datetime, UTC
import json
import threading



class ExecutionAudit:


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

            "execution_audit.json"

        )


        self.events = []


        self.load()





    def record(

        self,

        event,

        data

    ):


        with self.lock:


            item = {


                "event":

                event,


                "data":

                data,


                "time":

                datetime.now(

                    UTC

                ).isoformat()


            }


            self.events.append(

                item

            )


            self.save()


            return item





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


                "events":

                self.events


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


            self.events=data.get(

                "events",

                []

            )


        except Exception:


            self.events=[]





    def status(self):


        return {


            "version":

            self.VERSION,


            "events":

            len(self.events),


            "file":

            str(self.file)


        }