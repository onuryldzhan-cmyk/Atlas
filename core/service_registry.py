"""
Atlas AI Service Registry v5.0

Tracks available Atlas services.

Registry does NOT:
- Create services
- Execute services
- Manage business logic
"""


from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any
import logging



logger = logging.getLogger(
    "AtlasAI.Registry"
)



@dataclass
class ServiceInfo:
    """
    Service metadata.
    """

    name: str

    category: str

    instance: Any = None

    enabled: bool = True

    created_at: datetime = field(
        default_factory=lambda:
        datetime.now(
            timezone.utc
        )
    )


    def to_dict(self):

        return {

            "name":
                self.name,

            "category":
                self.category,

            "enabled":
                self.enabled,

            "created_at":
                self.created_at.isoformat()

        }



class ServiceRegistry:
    """
    Atlas service catalog.
    """


    def __init__(self):

        self.services: Dict[
            str,
            ServiceInfo
        ] = {}


        logger.info(
            "Service Registry initialized."
        )



    def register(
        self,
        name: str,
        category: str,
        instance=None
    ):

        service = ServiceInfo(

            name=name,

            category=category,

            instance=instance

        )


        self.services[name] = service


        logger.info(
            "Service registered: %s",
            name
        )



    def get(
        self,
        name: str
    ):

        service = (
            self.services.get(name)
        )


        if service:

            return service.instance


        return None



    def exists(
        self,
        name: str
    ):

        return (
            name in self.services
        )



    def enable(
        self,
        name: str
    ):

        if name in self.services:

            self.services[name].enabled = True



    def disable(
        self,
        name: str
    ):

        if name in self.services:

            self.services[name].enabled = False



    def list_services(self):

        return [

            service.to_dict()

            for service
            in self.services.values()

        ]



    def clear(self):

        self.services.clear()