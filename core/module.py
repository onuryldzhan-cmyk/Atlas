"""
Atlas AI Module Base v8.0

All Atlas modules inherit from AtlasModule.
"""

from __future__ import annotations

from abc import ABC
import logging
from datetime import datetime, timezone


class AtlasModule(ABC):

    def __init__(self, name: str):

        self.name = name

        self.logger = logging.getLogger(
            f"AtlasAI.{name}"
        )

        self.started = False

        self.enabled = True

        self.initialized = False

        self.created_at = datetime.now(
            timezone.utc
        )

        self.last_heartbeat = None


    def initialize(self):

        self.initialized = True

        self.logger.info(
            "%s initialized",
            self.name
        )


    def start(self):

        self.started = True

        self.logger.info(
            "%s started",
            self.name
        )


    def stop(self):

        self.started = False

        self.logger.info(
            "%s stopped",
            self.name
        )


    def heartbeat(self):

        self.last_heartbeat = datetime.now(
            timezone.utc
        )


    def health(self):

        return {

            "name": self.name,

            "enabled": self.enabled,

            "initialized": self.initialized,

            "started": self.started,

            "heartbeat": (
                self.last_heartbeat.isoformat()
                if self.last_heartbeat
                else None
            )
        }