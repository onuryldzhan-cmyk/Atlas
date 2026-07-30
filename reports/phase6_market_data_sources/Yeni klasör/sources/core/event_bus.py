"""
============================================================
ATLAS AI EVENT BUS v5.0
============================================================

Institutional Event Communication Layer


Responsibilities
----------------

- Publish system events
- Subscribe listeners
- Decouple modules
- Support async architecture
- Maintain event history
- Provide diagnostics


Architecture


MarketLoop
    |
    v

EventBus

    |
    +---- Learning System
    |
    +---- Trade Memory
    |
    +---- Audit System
    |
    +---- Analytics
    |
    +---- Monitoring


============================================================
"""


from __future__ import annotations


import logging
import threading


from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.EventBus"
)





class EventBus:


    VERSION = "5.0"



    def __init__(self):


        self.listeners = {}

        self.history = []

        self.lock = threading.Lock()



        logger.info(
            "Event Bus v%s initialized",
            self.VERSION
        )





    # =====================================================
    # SUBSCRIBE
    # =====================================================


    def subscribe(

        self,

        event,

        callback

    ):


        with self.lock:


            if event not in self.listeners:

                self.listeners[event] = []


            self.listeners[event].append(
                callback
            )



    # =====================================================
    # PUBLISH
    # =====================================================


    def publish(

        self,

        event,

        data=None

    ):


        payload = {


            "event":

            event,


            "data":

            data,


            "timestamp":

            datetime.now(
                UTC
            ).isoformat()


        }



        with self.lock:


            self.history.append(
                payload
            )



            listeners = self.listeners.get(

                event,

                []

            )



        for callback in listeners:


            try:


                callback(
                    payload
                )


            except Exception:


                logger.exception(
                    "Event listener failed"
                )



    # =====================================================
    # HISTORY
    # =====================================================


    def get_history(

        self,

        limit=100

    ):


        return self.history[-limit:]





    # =====================================================
    # STATUS
    # =====================================================


    def status(self):


        return {


            "version":

            self.VERSION,


            "listeners":

            len(
                self.listeners
            ),


            "events":

            len(
                self.history
            )


        }