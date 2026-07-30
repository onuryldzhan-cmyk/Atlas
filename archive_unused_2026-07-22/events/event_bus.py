"""
Atlas AI Event Bus

Central communication layer.
"""


import logging


logger = logging.getLogger("AtlasAI")


class EventBus:


    def __init__(self):

        self.listeners = {}


    def subscribe(self, event_type, callback):

        if event_type not in self.listeners:

            self.listeners[event_type] = []


        self.listeners[event_type].append(callback)


        logger.info(
            f"Event listener added: {event_type}"
        )


    def publish(self, event):

        event_type = event.event_type


        logger.info(
            f"Event published: {event_type}"
        )


        listeners = self.listeners.get(
            event_type,
            []
        )


        for callback in listeners:

            try:

                callback(event)


            except Exception as e:

                logger.error(
                    f"Event error: {e}"
                )