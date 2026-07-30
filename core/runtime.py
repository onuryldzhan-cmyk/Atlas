"""
Atlas AI Core Runtime v5.0

Responsibility:
- Manage Atlas lifecycle state
- Provide system runtime status
- Handle controlled state transitions

This module does NOT:
- Trade
- Analyze markets
- Manage portfolio
- Communicate with exchanges

It only manages the application lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, Any
import logging


logger = logging.getLogger("AtlasAI.Runtime")


class RuntimeState(Enum):
    """
    Atlas lifecycle states.
    """

    OFFLINE = "OFFLINE"
    BOOTING = "BOOTING"
    INITIALIZING = "INITIALIZING"
    CONNECTING = "CONNECTING"
    READY = "READY"
    RUNNING = "RUNNING"

    PAUSED = "PAUSED"
    DEGRADED = "DEGRADED"

    STOPPING = "STOPPING"
    STOPPED = "STOPPED"

    FAILED = "FAILED"


@dataclass
class RuntimeInfo:
    """
    Runtime metadata.
    """

    state: RuntimeState = RuntimeState.OFFLINE

    started_at: datetime | None = None

    last_transition: datetime | None = None

    previous_state: RuntimeState | None = None

    reason: str = ""

    version: str = "5.0"

    healthy: bool = True

    emergency_mode: bool = False

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


class AtlasRuntime:
    """
    Central lifecycle controller for Atlas.

    Thread-safe.
    """

    def __init__(self):

        self._lock = Lock()

        self.info = RuntimeInfo()

        logger.info(
            "Atlas Runtime initialized."
        )


    def _transition(
        self,
        new_state: RuntimeState,
        reason: str = ""
    ):

        with self._lock:

            old_state = self.info.state

            self.info.previous_state = old_state

            self.info.state = new_state

            self.info.last_transition = (
                datetime.now(timezone.utc)
            )

            self.info.reason = reason


            logger.info(
                "Runtime transition %s -> %s | %s",
                old_state.value,
                new_state.value,
                reason
            )


    def boot(self):

        self._transition(
            RuntimeState.BOOTING,
            "System boot started"
        )


    def initialize(self):

        self._transition(
            RuntimeState.INITIALIZING,
            "Core initialization"
        )


    def connect(self):

        self._transition(
            RuntimeState.CONNECTING,
            "Connecting infrastructure"
        )


    def ready(self):

        self._transition(
            RuntimeState.READY,
            "System ready"
        )


    def start(self):

        with self._lock:

            if self.info.started_at is None:

                self.info.started_at = (
                    datetime.now(timezone.utc)
                )


        self._transition(
            RuntimeState.RUNNING,
            "Atlas running"
        )


    def pause(
        self,
        reason: str = "Manual pause"
    ):

        self._transition(
            RuntimeState.PAUSED,
            reason
        )


    def resume(self):

        self._transition(
            RuntimeState.RUNNING,
            "Runtime resumed"
        )


    def degrade(
        self,
        reason: str
    ):

        self.info.healthy = False

        self._transition(
            RuntimeState.DEGRADED,
            reason
        )


    def fail(
        self,
        reason: str
    ):

        self.info.healthy = False

        self._transition(
            RuntimeState.FAILED,
            reason
        )


    def stop(self):

        self._transition(
            RuntimeState.STOPPING,
            "Shutdown started"
        )


    def shutdown(self):

        self._transition(
            RuntimeState.STOPPED,
            "Shutdown completed"
        )


    def status(self) -> Dict[str, Any]:

        with self._lock:

            return {

                "state":
                    self.info.state.value,

                "healthy":
                    self.info.healthy,

                "started_at":
                    str(self.info.started_at),

                "last_transition":
                    str(self.info.last_transition),

                "reason":
                    self.info.reason,

                "version":
                    self.info.version,

                "emergency_mode":
                    self.info.emergency_mode

            }


    def health(self) -> bool:

        with self._lock:

            return self.info.healthy