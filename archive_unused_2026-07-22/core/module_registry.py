"""
Atlas Module Registry
Professional AI Module Manager
"""

import logging


logger = logging.getLogger("AtlasAI")


class ModuleRegistry:

    def __init__(self):

        self.modules = {}

    # ==========================================
    # REGISTER
    # ==========================================

    def register(
        self,
        name,
        module
    ):

        self.modules[name] = module

        logger.info(
            f"[REGISTRY] {name} registered."
        )

    # ==========================================
    # GET
    # ==========================================

    def get(
        self,
        name
    ):

        return self.modules.get(name)

    # ==========================================
    # EXISTS
    # ==========================================

    def exists(
        self,
        name
    ):

        return name in self.modules

    # ==========================================
    # REMOVE
    # ==========================================

    def remove(
        self,
        name
    ):

        if name in self.modules:

            del self.modules[name]

            logger.info(
                f"[REGISTRY] {name} removed."
            )

    # ==========================================
    # LIST
    # ==========================================

    def names(self):

        return list(
            self.modules.keys()
        )

    # ==========================================
    # EXECUTE
    # ==========================================

    def execute(
        self,
        name,
        *args,
        **kwargs
    ):

        module = self.get(name)

        if module is None:

            raise ValueError(
                f"Module '{name}' not found."
            )

        if hasattr(module, "run"):

            return module.run(
                *args,
                **kwargs
            )

        if hasattr(module, "analyze"):

            return module.analyze(
                *args,
                **kwargs
            )

        if hasattr(module, "execute"):

            return module.execute(
                *args,
                **kwargs
            )

        raise AttributeError(
            f"{name} has no run/analyze/execute method."
        )

    # ==========================================
    # INFO
    # ==========================================

    def info(self):

        return {

            "count": len(
                self.modules
            ),

            "modules": self.names()

        }

    # ==========================================
    # CLEAR
    # ==========================================

    def clear(self):

        self.modules.clear()

        logger.info(
            "[REGISTRY] cleared."
        )