"""
Atlas AI Module Manager v8.0

Responsible for managing all Atlas modules.
"""

from __future__ import annotations

import logging

from core.module import AtlasModule


logger = logging.getLogger(
    "AtlasAI.ModuleManager"
)


class ModuleManager:

    def __init__(self):

        self.modules = {}

        logger.info(
            "Module Manager initialized."
        )


    def register(
        self,
        module: AtlasModule
    ):

        self.modules[module.name] = module

        logger.info(
            "Registered module: %s",
            module.name
        )


    def initialize_all(self):

        for module in self.modules.values():

            module.initialize()


    def start_all(self):

        for module in self.modules.values():

            module.start()


    def stop_all(self):

        for module in reversed(
            list(self.modules.values())
        ):

            module.stop()


    def heartbeat(self):

        for module in self.modules.values():

            module.heartbeat()


    def health(self):

        return {

            name: module.health()

            for name, module

            in self.modules.items()

        }


    def get(
        self,
        name: str
    ):

        return self.modules.get(name)