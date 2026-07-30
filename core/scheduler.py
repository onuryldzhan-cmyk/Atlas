"""
Atlas AI Scheduler v5.0

Responsibility:
- Execute scheduled tasks
- Manage background workers
- Control recurring jobs

Scheduler does NOT:
- Analyze market
- Make decisions
- Execute trades
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Thread, Event, Lock
from typing import Callable, Dict
import time
import logging


logger = logging.getLogger(
    "AtlasAI.Scheduler"
)


@dataclass
class ScheduledTask:
    """
    Represents a recurring task.
    """

    name: str

    function: Callable

    interval: float

    last_run: datetime | None = None

    executions: int = 0

    enabled: bool = True



class Scheduler:
    """
    Thread-safe task scheduler.
    """


    def __init__(self):

        self.tasks: Dict[
            str,
            ScheduledTask
        ] = {}

        self.running = False

        self._stop_event = Event()

        self._thread: Thread | None = None

        self._lock = Lock()


        logger.info(
            "Scheduler initialized."
        )



    def add_task(
        self,
        name: str,
        function: Callable,
        interval: float
    ):
        """
        Register new task.
        """

        with self._lock:

            self.tasks[name] = ScheduledTask(
                name=name,
                function=function,
                interval=interval
            )


        logger.info(
            "Task added: %s every %ss",
            name,
            interval
        )



    def remove_task(
        self,
        name: str
    ):

        with self._lock:

            if name in self.tasks:

                del self.tasks[name]



    def start(self):
        """
        Start scheduler worker.
        """

        if self.running:
            return


        self.running = True

        self._stop_event.clear()


        self._thread = Thread(
            target=self._run,
            daemon=True
        )

        self._thread.start()


        logger.info(
            "Scheduler started."
        )



    def _run(self):

        while not self._stop_event.is_set():

            now = datetime.now(
                timezone.utc
            )


            with self._lock:

                tasks = list(
                    self.tasks.values()
                )


            for task in tasks:

                if not task.enabled:
                    continue


                should_run = (
                    task.last_run is None
                    or
                    (
                        now -
                        task.last_run
                    ).total_seconds()
                    >= task.interval
                )


                if should_run:

                    self._execute(
                        task
                    )


            time.sleep(1)



    def _execute(
        self,
        task: ScheduledTask
    ):

        try:

            logger.info(
                "Executing task: %s",
                task.name
            )


            task.function()


            task.last_run = (
                datetime.now(
                    timezone.utc
                )
            )


            task.executions += 1


        except Exception:

            logger.exception(
                "Task failed: %s",
                task.name
            )



    def stop(self):
        """
        Stop scheduler.
        """

        if not self.running:
            return


        self.running = False

        self._stop_event.set()


        if self._thread:

            self._thread.join(
                timeout=5
            )


        logger.info(
            "Scheduler stopped."
        )



    def status(self):

        with self._lock:

            return {

                "running":
                    self.running,

                "tasks":
                    list(
                        self.tasks.keys()
                    )

            }