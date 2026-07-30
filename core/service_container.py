"""
Atlas AI Service Container v5.0

Responsibility:
- Manage service instances
- Centralize dependency management
- Provide service lifecycle control

Container does NOT:
- Execute business logic
- Make decisions
- Trade
"""

from __future__ import annotations

from typing import Dict, Type, Any
from threading import Lock
import logging


logger = logging.getLogger(
    "AtlasAI.Container"
)



class ServiceContainer:
    """
    Central dependency manager.

    Uses singleton-like service registration,
    but container itself is not global.
    """


    def __init__(self):

        self._services: Dict[
            Type,
            Any
        ] = {}

        self._factories: Dict[
            Type,
            Any
        ] = {}

        self._lock = Lock()


        logger.info(
            "Service Container initialized."
        )



    def register(
        self,
        service_type: Type,
        instance: Any
    ):
        """
        Register existing service instance.
        """


        with self._lock:

            self._services[
                service_type
            ] = instance


        logger.info(
            "Service registered: %s",
            service_type.__name__
        )



    def register_factory(
        self,
        service_type: Type,
        factory
    ):
        """
        Register lazy creator.
        """


        with self._lock:

            self._factories[
                service_type
            ] = factory



    def get(
        self,
        service_type: Type
    ):
        """
        Retrieve service instance.
        """


        with self._lock:

            if service_type in self._services:

                return self._services[
                    service_type
                ]


            if service_type in self._factories:

                instance = (
                    self._factories[
                        service_type
                    ]()
                )


                self._services[
                    service_type
                ] = instance


                return instance



        raise KeyError(
            f"Service not registered: {service_type}"
        )



    def contains(
        self,
        service_type: Type
    ) -> bool:


        with self._lock:

            return (
                service_type in self._services
                or
                service_type in self._factories
            )



    def remove(
        self,
        service_type: Type
    ):

        with self._lock:

            self._services.pop(
                service_type,
                None
            )

            self._factories.pop(
                service_type,
                None
            )



    def clear(self):

        with self._lock:

            self._services.clear()

            self._factories.clear()



    def list_services(self):

        with self._lock:

            return [
                cls.__name__
                for cls in self._services.keys()
            ]