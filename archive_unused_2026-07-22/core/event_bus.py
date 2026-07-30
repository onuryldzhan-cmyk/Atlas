"""
Atlas Event Bus
Professional Event System
"""

import logging


logger = logging.getLogger("AtlasAI")


class EventBus:

    def __init__(self):

        self.listeners = {}

    # ==========================================
    # Subscribe
    # ==========================================

    def subscribe(
        self,
        event,
        callback
    ):

        if event not in self.listeners:

            self.listeners[event] = []

        self.listeners[event].append(
            callback
        )

    # ==========================================
    # Publish
    # ==========================================

    def publish(
        self,
        event,
        data=None
    ):

        callbacks = self.listeners.get(
            event,
            []
        )

        logger.info(
            f"[EVENT] {event}"
        )

        for callback in callbacks:

            try:

                callback(data)

            except Exception as e:

                logger.exception(e)

    # ==========================================
    # Unsubscribe
    # ==========================================

    def unsubscribe(
        self,
        event,
        callback
    ):

        if event not in self.listeners:

            return

        if callback in self.listeners[event]:

            self.listeners[event].remove(
                callback
            )

    # ==========================================
    # Clear
    # ==========================================

    def clear(self):

        self.listeners.clear()

    # ==========================================
    # Registered Events
    # ==========================================

    def events(self):

        return list(

            self.listeners.keys()

        )