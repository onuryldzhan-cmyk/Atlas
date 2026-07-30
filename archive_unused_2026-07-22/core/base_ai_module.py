"""
Atlas Base AI Module
All AI modules inherit from this class.
"""

import logging
import time


logger = logging.getLogger("AtlasAI")


class BaseAIModule:

    def __init__(self):

        self.name = self.__class__.__name__

        self.enabled = True

        self.version = "1.0"

        self.execution_count = 0

        self.error_count = 0

        self.total_runtime = 0.0

        self.last_runtime = 0.0

        self.last_error = None

    # ======================================

    def before_run(
        self,
        context
    ):

        self.execution_count += 1

        self._start_time = time.perf_counter()

    # ======================================

    def process(
        self,
        context
    ):

        """
        Override this method.
        """

        raise NotImplementedError

    # ======================================

    def after_run(
        self,
        context
    ):

        elapsed = (

            time.perf_counter()

            -

            self._start_time

        )

        self.last_runtime = elapsed

        self.total_runtime += elapsed

    # ======================================

    def run(
        self,
        context
    ):

        if not self.enabled:

            return context

        try:

            self.before_run(context)

            self.process(context)

            self.after_run(context)

            return context

        except Exception as e:

            self.error_count += 1

            self.last_error = str(e)

            logger.exception(

                f"[{self.name}] {e}"

            )

            context.errors.append(

                f"{self.name}: {e}"

            )

            return context

    # ======================================

    def enable(self):

        self.enabled = True

    # ======================================

    def disable(self):

        self.enabled = False

    # ======================================

    def statistics(self):

        average = 0

        if self.execution_count > 0:

            average = (

                self.total_runtime

                /

                self.execution_count

            )

        return {

            "name": self.name,

            "version": self.version,

            "enabled": self.enabled,

            "runs": self.execution_count,

            "errors": self.error_count,

            "last_runtime": round(

                self.last_runtime,

                6

            ),

            "average_runtime": round(

                average,

                6

            )

        }