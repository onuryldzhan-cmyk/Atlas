"""
============================================================
ATLAS EXECUTION EVENT SYSTEM v1.0
============================================================
"""


from datetime import datetime, UTC


class ExecutionEvent:


    def __init__(
        self,
        event,
        payload=None
    ):

        self.event = event

        self.payload = payload or {}

        self.time = datetime.now(
            UTC
        ).isoformat()



    def to_dict(self):

        return {

            "event": self.event,

            "payload": self.payload,

            "time": self.time

        }