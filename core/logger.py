"""
Atlas AI Logger System v5.0

Responsibility:
- Central logging configuration
- Provide consistent logging format
"""

from __future__ import annotations

import logging
import os
from datetime import datetime



LOG_DIR = "logs"



class AtlasLogger:
    """
    Central logger manager.
    """


    def __init__(
        self,
        name="AtlasAI",
        level=logging.INFO
    ):

        self.name = name

        self.level = level

        self._initialized = False



    def initialize(self):

        if self._initialized:
            return


        os.makedirs(
            LOG_DIR,
            exist_ok=True
        )


        log_file = os.path.join(
            LOG_DIR,
            "atlas.log"
        )


        formatter = logging.Formatter(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        )


        file_handler = logging.FileHandler(
            log_file,
            encoding="utf-8"
        )

        file_handler.setFormatter(
            formatter
        )


        console_handler = logging.StreamHandler()

        console_handler.setFormatter(
            formatter
        )


        root_logger = logging.getLogger()

        root_logger.setLevel(
            self.level
        )


        root_logger.addHandler(
            file_handler
        )

        root_logger.addHandler(
            console_handler
        )


        self._initialized = True


        logging.getLogger(
            self.name
        ).info(
            "Atlas Logger initialized."
        )



    def get(
        self,
        module_name: str
    ):

        return logging.getLogger(
            module_name
        )