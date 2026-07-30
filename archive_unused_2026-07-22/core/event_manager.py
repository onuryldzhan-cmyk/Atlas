"""
Atlas Event Manager
Central Event System Controller
"""

import logging

from core.event_bus import EventBus


logger = logging.getLogger("AtlasAI")


class EventManager:

    def __init__(self):

        self.bus = EventBus()

        logger.info(
            "Atlas Event Manager initialized"
        )


    # =====================================
    # Register Listener
    # =====================================

    def register(
        self,
        event,
        callback
    ):

        self.bus.subscribe(
            event,
            callback
        )

        logger.info(
            f"Listener registered: {event}"
        )


    # =====================================
    # Emit Event
    # =====================================

    def emit(
        self,
        event,
        data=None
    ):

        self.bus.publish(
            event,
            data
        )


    # =====================================
    # Remove Listener
    # =====================================

    def remove(
        self,
        event,
        callback
    ):

        self.bus.unsubscribe(
            event,
            callback
        )


    # =====================================
    # System Status
    # =====================================

    def status(self):

        return {

            "events":
                self.bus.events(),

            "listeners":
                len(self.bus.listeners)

        }


# Global Event Manager

event_manager = EventManager()