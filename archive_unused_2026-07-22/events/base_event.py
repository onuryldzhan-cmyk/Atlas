"""
Atlas AI Event System
Base Event Definition
"""


from datetime import datetime


class BaseEvent:
    """
    Atlas içerisindeki tüm eventlerin temel sınıfı.
    """

    def __init__(self, event_type: str):

        self.event_type = event_type

        self.timestamp = datetime.utcnow()


    def info(self):

        return {

            "event_type": self.event_type,

            "timestamp": self.timestamp.isoformat()

        }