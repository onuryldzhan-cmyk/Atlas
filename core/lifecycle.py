"""
Atlas AI Lifecycle Manager v5.0

Responsibility:
- Manage service startup/shutdown order
- Control service lifecycle
- Handle graceful recovery

Lifecycle does NOT:
- Execute business logic
- Trade
- Analyze markets
"""

from __future__ import annotations

from typing import List, Any
import logging


logger = logging.getLogger(
    "AtlasAI.Lifecycle"
)



class LifecycleManager:
    """
    Controls Atlas service lifecycle.
    """


    def __init__(self):

        self.services: List[Any] = []

        self.started = False


        logger.info(
            "Lifecycle Manager initialized."
        )



    def register(
        self,
        service: Any
    ):
        """
        Add service to lifecycle control.
        """

        self.services.append(
            service
        )


        logger.info(
            "Lifecycle registered: %s",
            service.__class__.__name__
        )



    def initialize_all(self):
        """
        Initialize every service.
        """

        for service in self.services:

            if hasattr(
                service,
                "initialize"
            ):

                try:

                    service.initialize()

                    logger.info(
                        "%s initialized",
                        service.__class__.__name__
                    )


                except Exception:

                    logger.exception(
                        "Initialization failed: %s",
                        service.__class__.__name__
                    )

                    raise



    def start_all(self):
        """
        Start every service.
        """

        for service in self.services:

            if hasattr(
                service,
                "start"
            ):

                try:

                    service.start()

                    logger.info(
                        "%s started",
                        service.__class__.__name__
                    )


                except Exception:

                    logger.exception(
                        "Start failed: %s",
                        service.__class__.__name__
                    )

                    raise


        self.started = True



    def stop_all(self):
        """
        Stop services.
        """

        for service in reversed(
            self.services
        ):

            if hasattr(
                service,
                "stop"
            ):

                try:

                    service.stop()

                    logger.info(
                        "%s stopped",
                        service.__class__.__name__
                    )


                except Exception:

                    logger.exception(
                        "Stop failed: %s",
                        service.__class__.__name__
                    )



    def shutdown_all(self):
        """
        Final cleanup.
        """

        for service in reversed(
            self.services
        ):

            if hasattr(
                service,
                "shutdown"
            ):

                try:

                    service.shutdown()

                    logger.info(
                        "%s shutdown",
                        service.__class__.__name__
                    )


                except Exception:

                    logger.exception(
                        "Shutdown failed: %s",
                        service.__class__.__name__
                    )


        self.started = False



    def health_check(self):

        result = {}

        for service in self.services:

            name = service.__class__.__name__

            try:

                if hasattr(
                    service,
                    "health"
                ):

                    result[name] = (
                        service.health()
                    )

                else:

                    result[name] = True


            except Exception:

                result[name] = False


        return result