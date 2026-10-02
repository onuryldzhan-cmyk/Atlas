"""
============================================================
ATLAS OS SCHEDULER SERVICE v1.0
============================================================

Enterprise task scheduling infrastructure for AtlasOS.

Responsibilities
----------------
- Register scheduled tasks
- Execute one-time tasks
- Execute recurring tasks
- Execute delayed tasks
- Support manual execution
- Support task pause and resume
- Support task cancellation
- Support retry policies
- Support execution timeout detection
- Maintain task execution history
- Maintain scheduler statistics
- Publish scheduler events
- Isolate task failures
- Operate as an AtlasOS managed service

Architecture
------------
AtlasOS Components
        |
        +-- Health checks
        +-- Market scans
        +-- Metrics snapshots
        +-- Audit maintenance
        +-- Agent tasks
        |
        v
SchedulerService
        |
        +-- Task Registry
        +-- Background Worker
        +-- Execution Engine
        +-- Retry Controller
        +-- Timeout Controller
        +-- History Store
        +-- Event Publisher

Design Principles
-----------------
- Thread safe
- Failure isolated
- Deterministic task identity
- Bounded execution history
- Explicit lifecycle
- No external dependency
- No trading-specific dependency
- Event-driven observability
- Human-controlled task registration

============================================================
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Callable, Mapping

from atlas_os.contracts import (
    ServiceIdentity,
)
from atlas_os.events import (
    EventBusService,
    EventSeverity,
)
from atlas_os.services import (
    BaseAtlasService,
)


logger = logging.getLogger(
    "AtlasAI.AtlasOS.Scheduler"
)


# =========================================================
# TYPE ALIASES
# =========================================================

TaskCallable = Callable[[], Any]


# =========================================================
# ENUMERATIONS
# =========================================================

class TaskScheduleType(StrEnum):
    """
    Supported scheduler task types.
    """

    ONCE = "ONCE"
    INTERVAL = "INTERVAL"
    MANUAL = "MANUAL"


class ScheduledTaskState(StrEnum):
    """
    Runtime state of a scheduled task.
    """

    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskExecutionStatus(StrEnum):
    """
    Final state of one task execution.
    """

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class SchedulerEventType(StrEnum):
    """
    Events published by SchedulerService.
    """

    SCHEDULER_STARTED = "SCHEDULER_STARTED"
    SCHEDULER_STOPPING = "SCHEDULER_STOPPING"
    SCHEDULER_STOPPED = "SCHEDULER_STOPPED"

    TASK_REGISTERED = "TASK_REGISTERED"
    TASK_STARTED = "TASK_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_TIMED_OUT = "TASK_TIMED_OUT"
    TASK_RETRYING = "TASK_RETRYING"
    TASK_PAUSED = "TASK_PAUSED"
    TASK_RESUMED = "TASK_RESUMED"
    TASK_CANCELLED = "TASK_CANCELLED"
    TASK_REMOVED = "TASK_REMOVED"


# =========================================================
# EXCEPTIONS
# =========================================================

class SchedulerError(RuntimeError):
    """
    Base scheduler exception.
    """


class TaskNotFoundError(SchedulerError):
    """
    Raised when a requested task does not exist.
    """


class DuplicateTaskError(SchedulerError):
    """
    Raised when a duplicate task name or ID is registered.
    """


class InvalidTaskConfigurationError(SchedulerError):
    """
    Raised when task configuration is invalid.
    """


class TaskExecutionError(SchedulerError):
    """
    Raised when manual task execution fails.
    """


# =========================================================
# DATA MODELS
# =========================================================

@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """
    Immutable retry policy.

    max_attempts includes the initial execution.

    Example
    -------
    RetryPolicy(
        max_attempts=3,
        delay_seconds=1.0,
        backoff_multiplier=2.0,
    )
    """

    max_attempts: int = 1
    delay_seconds: float = 0.0
    backoff_multiplier: float = 1.0

    def __post_init__(self) -> None:

        if self.max_attempts <= 0:
            raise ValueError(
                "max_attempts must be greater than zero."
            )

        if self.delay_seconds < 0:
            raise ValueError(
                "delay_seconds cannot be negative."
            )

        if self.backoff_multiplier < 1:
            raise ValueError(
                "backoff_multiplier must be at least 1."
            )

    def delay_for_attempt(
        self,
        attempt_number: int,
    ) -> float:
        """
        Return delay before the specified retry attempt.

        attempt_number starts from 2 for the first retry.
        """

        if attempt_number <= 1:
            return 0.0

        retry_index = attempt_number - 2

        return (
            self.delay_seconds
            * (
                self.backoff_multiplier
                ** retry_index
            )
        )


@dataclass(frozen=True, slots=True)
class TaskConfiguration:
    """
    Immutable task configuration.
    """

    name: str
    schedule_type: TaskScheduleType
    interval_seconds: float | None
    initial_delay_seconds: float
    timeout_seconds: float | None
    retry_policy: RetryPolicy
    run_immediately: bool
    allow_overlap: bool
    enabled: bool
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:

        normalized_name = self.name.strip()

        if not normalized_name:
            raise InvalidTaskConfigurationError(
                "Task name cannot be empty."
            )

        if self.initial_delay_seconds < 0:
            raise InvalidTaskConfigurationError(
                "initial_delay_seconds cannot be negative."
            )

        if (
            self.timeout_seconds is not None
            and self.timeout_seconds <= 0
        ):
            raise InvalidTaskConfigurationError(
                "timeout_seconds must be greater than zero."
            )

        if self.schedule_type == TaskScheduleType.INTERVAL:

            if (
                self.interval_seconds is None
                or self.interval_seconds <= 0
            ):
                raise InvalidTaskConfigurationError(
                    "Interval tasks require interval_seconds "
                    "greater than zero."
                )

        elif self.interval_seconds is not None:

            if self.interval_seconds <= 0:
                raise InvalidTaskConfigurationError(
                    "interval_seconds must be greater than zero."
                )

        object.__setattr__(
            self,
            "name",
            normalized_name,
        )

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(
                dict(self.metadata)
            ),
        )


@dataclass(frozen=True, slots=True)
class TaskExecutionRecord:
    """
    Immutable record of one task execution.
    """

    execution_id: str
    task_id: str
    task_name: str
    status: TaskExecutionStatus
    attempt_count: int
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    result: Any
    error: str | None
    correlation_id: str
    timed_out: bool


@dataclass(frozen=True, slots=True)
class ScheduledTaskSnapshot:
    """
    Immutable runtime snapshot of one task.
    """

    task_id: str
    name: str
    schedule_type: TaskScheduleType
    state: ScheduledTaskState
    enabled: bool
    interval_seconds: float | None
    timeout_seconds: float | None
    retry_policy: RetryPolicy
    allow_overlap: bool
    next_run_at: datetime | None
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_status: TaskExecutionStatus | None
    run_count: int
    success_count: int
    failure_count: int
    timeout_count: int
    skipped_count: int
    active_executions: int
    last_error: str | None
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class SchedulerStatistics:
    """
    Immutable scheduler statistics.
    """

    registered_tasks: int
    scheduled_tasks: int
    paused_tasks: int
    completed_tasks: int
    failed_tasks: int
    cancelled_tasks: int
    active_executions: int
    total_executions: int
    successful_executions: int
    failed_executions: int
    timed_out_executions: int
    skipped_executions: int
    retry_attempts: int
    event_publication_failures: int
    history_size: int
    worker_alive: bool
    last_executed_task: str | None
    last_error: str | None
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True)
class SchedulerSnapshot:
    """
    Complete immutable Scheduler Service snapshot.
    """

    running: bool
    worker_alive: bool
    polling_interval_seconds: float
    task_count: int
    history_limit: int
    tasks: tuple[ScheduledTaskSnapshot, ...]
    history: tuple[TaskExecutionRecord, ...]
    statistics: SchedulerStatistics
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(slots=True)
class _ScheduledTask:
    """
    Internal mutable scheduled task representation.
    """

    task_id: str
    configuration: TaskConfiguration
    callable: TaskCallable
    state: ScheduledTaskState
    created_at: datetime
    next_run_at: datetime | None

    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_status: TaskExecutionStatus | None = None
    last_error: str | None = None

    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    skipped_count: int = 0
    active_executions: int = 0


# =========================================================
# SCHEDULER SERVICE
# =========================================================

class SchedulerService(BaseAtlasService):
    """
    Central AtlasOS task scheduling service.

    The scheduler maintains a background worker that checks due tasks
    and dispatches their executions into isolated daemon threads.

    Tasks may be:

    - ONCE:
      Runs once after an optional delay.

    - INTERVAL:
      Runs repeatedly using a fixed interval.

    - MANUAL:
      Runs only when run_task() is called.
    """

    VERSION = "1.0.0"

    NAME = "AtlasOSScheduler"

    def __init__(
        self,
        *,
        polling_interval_seconds: float = 0.05,
        history_limit: int = 1000,
        event_bus: EventBusService | None = None,
        publish_events: bool = False,
    ) -> None:

        if polling_interval_seconds <= 0:
            raise ValueError(
                "polling_interval_seconds must be greater than zero."
            )

        if history_limit <= 0:
            raise ValueError(
                "history_limit must be greater than zero."
            )

        if (
            event_bus is not None
            and not isinstance(
                event_bus,
                EventBusService,
            )
        ):
            raise TypeError(
                "event_bus must be an EventBusService instance."
            )

        if publish_events and event_bus is None:
            raise ValueError(
                "event_bus is required when publish_events is enabled."
            )

        super().__init__(
            ServiceIdentity(
                name=self.NAME,
                version=self.VERSION,
                service_type="SCHEDULER",
                description=(
                    "Central task scheduling and execution "
                    "service for AtlasOS."
                ),
            )
        )

        self._polling_interval_seconds = float(
            polling_interval_seconds
        )

        self._history_limit = int(
            history_limit
        )

        self._event_bus = event_bus
        self._publish_events = bool(
            publish_events
        )

        self._tasks: dict[
            str,
            _ScheduledTask,
        ] = {}

        self._task_name_index: dict[
            str,
            str,
        ] = {}

        self._history: deque[
            TaskExecutionRecord
        ] = deque(
            maxlen=self._history_limit
        )

        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()

        self._total_executions = 0
        self._successful_executions = 0
        self._failed_executions = 0
        self._timed_out_executions = 0
        self._skipped_executions = 0
        self._retry_attempts = 0
        self._event_publication_failures = 0

        self._last_executed_task: str | None = None
        self._last_error: str | None = None

        self._scheduler_lock = threading.RLock()

    # =====================================================
    # PROPERTIES
    # =====================================================

    @property
    def polling_interval_seconds(self) -> float:
        """
        Return worker polling interval.
        """

        return self._polling_interval_seconds

    @property
    def history_limit(self) -> int:
        """
        Return bounded execution history limit.
        """

        return self._history_limit

    @property
    def worker_alive(self) -> bool:
        """
        Return True when the scheduler worker is alive.
        """

        thread = self._worker_thread

        return (
            thread is not None
            and thread.is_alive()
        )

    @property
    def task_count(self) -> int:
        """
        Return number of registered tasks.
        """

        with self._scheduler_lock:
            return len(self._tasks)

    # =====================================================
    # SERVICE LIFECYCLE
    # =====================================================

    def _on_start(self) -> None:
        """
        Start scheduler worker.
        """

        self._stop_event.clear()
        self._wake_event.clear()

        with self._scheduler_lock:

            now = datetime.now(UTC)

            for task in self._tasks.values():

                if (
                    task.configuration.enabled
                    and task.state
                    not in {
                        ScheduledTaskState.CANCELLED,
                        ScheduledTaskState.COMPLETED,
                    }
                ):

                    if (
                        task.configuration.schedule_type
                        == TaskScheduleType.MANUAL
                    ):
                        task.state = (
                            ScheduledTaskState.CREATED
                        )
                        task.next_run_at = None

                    else:
                        task.state = (
                            ScheduledTaskState.SCHEDULED
                        )

                        if task.next_run_at is None:
                            task.next_run_at = (
                                self._calculate_initial_run(
                                    task.configuration,
                                    now,
                                )
                            )

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="AtlasOSSchedulerWorker",
            daemon=True,
        )

        self._worker_thread.start()

        self._publish_scheduler_event(
            SchedulerEventType.SCHEDULER_STARTED,
            payload={
                "task_count": self.task_count,
                "polling_interval_seconds": (
                    self._polling_interval_seconds
                ),
            },
        )

        logger.info(
            "AtlasOS Scheduler started | tasks=%s",
            self.task_count,
        )

    def _on_stop(self) -> None:
        """
        Stop scheduler worker.
        """

        self._publish_scheduler_event(
            SchedulerEventType.SCHEDULER_STOPPING,
            payload={
                "task_count": self.task_count,
                "active_executions": (
                    self._active_execution_count()
                ),
            },
        )

        self._stop_event.set()
        self._wake_event.set()

        worker = self._worker_thread

        if (
            worker is not None
            and worker.is_alive()
        ):
            worker.join(
                timeout=max(
                    1.0,
                    self._polling_interval_seconds * 4,
                )
            )

        self._worker_thread = None

        self._publish_scheduler_event(
            SchedulerEventType.SCHEDULER_STOPPED,
            payload={
                "task_count": self.task_count,
                "history_size": len(
                    self._history
                ),
            },
        )

        logger.info(
            "AtlasOS Scheduler stopped."
        )

    # =====================================================
    # TASK REGISTRATION
    # =====================================================

    def register_task(
        self,
        name: str,
        callable: TaskCallable,
        *,
        schedule_type: TaskScheduleType = (
            TaskScheduleType.MANUAL
        ),
        interval_seconds: float | None = None,
        initial_delay_seconds: float = 0.0,
        timeout_seconds: float | None = None,
        retry_policy: RetryPolicy | None = None,
        run_immediately: bool = False,
        allow_overlap: bool = False,
        enabled: bool = True,
        metadata: Mapping[str, Any] | None = None,
        task_id: str | None = None,
    ) -> str:
        """
        Register a task and return its task ID.
        """

        if not callable or not hasattr(
            callable,
            "__call__",
        ):
            raise TypeError(
                "callable must be callable."
            )

        resolved_schedule_type = (
            TaskScheduleType(
                schedule_type
            )
        )

        configuration = TaskConfiguration(
            name=name,
            schedule_type=resolved_schedule_type,
            interval_seconds=interval_seconds,
            initial_delay_seconds=float(
                initial_delay_seconds
            ),
            timeout_seconds=timeout_seconds,
            retry_policy=(
                retry_policy
                if retry_policy is not None
                else RetryPolicy()
            ),
            run_immediately=bool(
                run_immediately
            ),
            allow_overlap=bool(
                allow_overlap
            ),
            enabled=bool(
                enabled
            ),
            metadata=dict(
                metadata or {}
            ),
        )

        resolved_task_id = (
            task_id.strip()
            if task_id is not None
            else str(uuid.uuid4())
        )

        if not resolved_task_id:
            raise InvalidTaskConfigurationError(
                "task_id cannot be empty."
            )

        normalized_name = (
            configuration.name.casefold()
        )

        now = datetime.now(UTC)

        with self._scheduler_lock:

            if resolved_task_id in self._tasks:
                raise DuplicateTaskError(
                    f"Task ID already registered: "
                    f"{resolved_task_id}"
                )

            if normalized_name in self._task_name_index:
                raise DuplicateTaskError(
                    f"Task name already registered: "
                    f"{configuration.name}"
                )

            next_run_at = None

            if (
                configuration.enabled
                and configuration.schedule_type
                != TaskScheduleType.MANUAL
            ):
                next_run_at = (
                    self._calculate_initial_run(
                        configuration,
                        now,
                    )
                )

            initial_state = (
                ScheduledTaskState.SCHEDULED
                if next_run_at is not None
                else ScheduledTaskState.CREATED
            )

            task = _ScheduledTask(
                task_id=resolved_task_id,
                configuration=configuration,
                callable=callable,
                state=initial_state,
                created_at=now,
                next_run_at=next_run_at,
            )

            self._tasks[
                resolved_task_id
            ] = task

            self._task_name_index[
                normalized_name
            ] = resolved_task_id

        self._wake_event.set()

        self._publish_scheduler_event(
            SchedulerEventType.TASK_REGISTERED,
            payload={
                "task_id": resolved_task_id,
                "task_name": configuration.name,
                "schedule_type": (
                    configuration.schedule_type.value
                ),
                "interval_seconds": (
                    configuration.interval_seconds
                ),
                "enabled": configuration.enabled,
            },
            correlation_id=(
                f"task-registration-"
                f"{resolved_task_id}"
            ),
        )

        return resolved_task_id

    def register_once(
        self,
        name: str,
        callable: TaskCallable,
        *,
        delay_seconds: float = 0.0,
        timeout_seconds: float | None = None,
        retry_policy: RetryPolicy | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        """
        Register a one-time task.
        """

        return self.register_task(
            name,
            callable,
            schedule_type=TaskScheduleType.ONCE,
            initial_delay_seconds=delay_seconds,
            timeout_seconds=timeout_seconds,
            retry_policy=retry_policy,
            metadata=metadata,
        )

    def register_interval(
        self,
        name: str,
        callable: TaskCallable,
        *,
        interval_seconds: float,
        initial_delay_seconds: float = 0.0,
        timeout_seconds: float | None = None,
        retry_policy: RetryPolicy | None = None,
        run_immediately: bool = False,
        allow_overlap: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        """
        Register a recurring interval task.
        """

        return self.register_task(
            name,
            callable,
            schedule_type=TaskScheduleType.INTERVAL,
            interval_seconds=interval_seconds,
            initial_delay_seconds=initial_delay_seconds,
            timeout_seconds=timeout_seconds,
            retry_policy=retry_policy,
            run_immediately=run_immediately,
            allow_overlap=allow_overlap,
            metadata=metadata,
        )

    def register_manual(
        self,
        name: str,
        callable: TaskCallable,
        *,
        timeout_seconds: float | None = None,
        retry_policy: RetryPolicy | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        """
        Register a manually triggered task.
        """

        return self.register_task(
            name,
            callable,
            schedule_type=TaskScheduleType.MANUAL,
            timeout_seconds=timeout_seconds,
            retry_policy=retry_policy,
            metadata=metadata,
        )

    # =====================================================
    # TASK LOOKUP
    # =====================================================

    def task_exists(
        self,
        task_reference: str,
    ) -> bool:
        """
        Return True when a task exists by ID or name.
        """

        with self._scheduler_lock:

            return (
                task_reference in self._tasks
                or task_reference.casefold()
                in self._task_name_index
            )

    def _resolve_task_id(
        self,
        task_reference: str,
    ) -> str:
        """
        Resolve a task ID from an ID or name.
        """

        normalized_reference = (
            task_reference.strip()
        )

        if not normalized_reference:
            raise TaskNotFoundError(
                "Task reference cannot be empty."
            )

        with self._scheduler_lock:

            if normalized_reference in self._tasks:
                return normalized_reference

            task_id = self._task_name_index.get(
                normalized_reference.casefold()
            )

            if task_id is None:
                raise TaskNotFoundError(
                    f"Task not found: "
                    f"{task_reference}"
                )

            return task_id

    # =====================================================
    # MANUAL EXECUTION
    # =====================================================

    def run_task(
        self,
        task_reference: str,
        *,
        wait: bool = True,
        raise_on_failure: bool = False,
    ) -> TaskExecutionRecord | str:
        """
        Run a task immediately.

        When wait=True, returns TaskExecutionRecord.
        When wait=False, returns execution correlation ID.
        """

        task_id = self._resolve_task_id(
            task_reference
        )

        with self._scheduler_lock:

            task = self._tasks[
                task_id
            ]

            if task.state == ScheduledTaskState.CANCELLED:
                raise TaskExecutionError(
                    f"Task is cancelled: "
                    f"{task.configuration.name}"
                )

            if (
                task.active_executions > 0
                and not task.configuration.allow_overlap
            ):
                record = self._create_skipped_record(
                    task,
                    reason=(
                        "Task already has an active execution."
                    ),
                )

                if raise_on_failure:
                    raise TaskExecutionError(
                        record.error or (
                            "Task execution was skipped."
                        )
                    )

                return record

        if wait:

            record = self._execute_task(
                task_id
            )

            if (
                raise_on_failure
                and record.status
                not in {
                    TaskExecutionStatus.SUCCESS,
                }
            ):
                raise TaskExecutionError(
                    record.error
                    or (
                        f"Task execution failed: "
                        f"{record.task_name}"
                    )
                )

            return record

        correlation_id = (
            f"task-run-{uuid.uuid4()}"
        )

        thread = threading.Thread(
            target=self._execute_task,
            args=(task_id,),
            kwargs={
                "correlation_id": correlation_id,
            },
            name=(
                f"AtlasTask-"
                f"{task.configuration.name}"
            ),
            daemon=True,
        )

        thread.start()

        return correlation_id

    # =====================================================
    # PAUSE / RESUME / CANCEL / REMOVE
    # =====================================================

    def pause_task(
        self,
        task_reference: str,
    ) -> ScheduledTaskSnapshot:
        """
        Pause future scheduled executions.
        """

        task_id = self._resolve_task_id(
            task_reference
        )

        with self._scheduler_lock:

            task = self._tasks[
                task_id
            ]

            if task.state == ScheduledTaskState.CANCELLED:
                raise SchedulerError(
                    "Cancelled tasks cannot be paused."
                )

            task.state = ScheduledTaskState.PAUSED
            task.next_run_at = None

            snapshot = self._snapshot_task(
                task
            )

        self._publish_scheduler_event(
            SchedulerEventType.TASK_PAUSED,
            payload={
                "task_id": task_id,
                "task_name": snapshot.name,
            },
        )

        return snapshot

    def resume_task(
        self,
        task_reference: str,
    ) -> ScheduledTaskSnapshot:
        """
        Resume a paused task.
        """

        task_id = self._resolve_task_id(
            task_reference
        )

        with self._scheduler_lock:

            task = self._tasks[
                task_id
            ]

            if task.state != ScheduledTaskState.PAUSED:
                raise SchedulerError(
                    "Only paused tasks can be resumed."
                )

            if (
                task.configuration.schedule_type
                == TaskScheduleType.MANUAL
            ):
                task.state = ScheduledTaskState.CREATED
                task.next_run_at = None

            else:
                task.state = ScheduledTaskState.SCHEDULED
                task.next_run_at = (
                    datetime.now(UTC)
                    + timedelta(
                        seconds=(
                            task.configuration
                            .initial_delay_seconds
                        )
                    )
                )

            snapshot = self._snapshot_task(
                task
            )

        self._wake_event.set()

        self._publish_scheduler_event(
            SchedulerEventType.TASK_RESUMED,
            payload={
                "task_id": task_id,
                "task_name": snapshot.name,
                "next_run_at": (
                    snapshot.next_run_at.isoformat()
                    if snapshot.next_run_at
                    is not None
                    else None
                ),
            },
        )

        return snapshot

    def cancel_task(
        self,
        task_reference: str,
    ) -> ScheduledTaskSnapshot:
        """
        Cancel all future task executions.
        """

        task_id = self._resolve_task_id(
            task_reference
        )

        with self._scheduler_lock:

            task = self._tasks[
                task_id
            ]

            task.state = ScheduledTaskState.CANCELLED
            task.next_run_at = None

            snapshot = self._snapshot_task(
                task
            )

        self._publish_scheduler_event(
            SchedulerEventType.TASK_CANCELLED,
            payload={
                "task_id": task_id,
                "task_name": snapshot.name,
            },
        )

        return snapshot

    def remove_task(
        self,
        task_reference: str,
        *,
        force: bool = False,
    ) -> ScheduledTaskSnapshot:
        """
        Remove a task from the scheduler.
        """

        task_id = self._resolve_task_id(
            task_reference
        )

        with self._scheduler_lock:

            task = self._tasks[
                task_id
            ]

            if (
                task.active_executions > 0
                and not force
            ):
                raise SchedulerError(
                    "Cannot remove a task with "
                    "active executions."
                )

            snapshot = self._snapshot_task(
                task
            )

            del self._tasks[
                task_id
            ]

            self._task_name_index.pop(
                task.configuration.name.casefold(),
                None,
            )

        self._publish_scheduler_event(
            SchedulerEventType.TASK_REMOVED,
            payload={
                "task_id": task_id,
                "task_name": snapshot.name,
                "forced": force,
            },
        )

        return snapshot

    # =====================================================
    # WORKER
    # =====================================================

    def _worker_loop(self) -> None:
        """
        Background task scheduling loop.
        """

        while not self._stop_event.is_set():

            try:

                due_task_ids = (
                    self._collect_due_tasks()
                )

                for task_id in due_task_ids:

                    if self._stop_event.is_set():
                        break

                    thread = threading.Thread(
                        target=self._execute_task,
                        args=(task_id,),
                        name=(
                            f"AtlasScheduledTask-"
                            f"{task_id}"
                        ),
                        daemon=True,
                    )

                    thread.start()

            except Exception as exc:

                error = (
                    f"{type(exc).__name__}: {exc}"
                )

                with self._scheduler_lock:
                    self._last_error = error

                logger.exception(
                    "AtlasOS Scheduler worker failure."
                )

            self._wake_event.wait(
                timeout=(
                    self._polling_interval_seconds
                )
            )

            self._wake_event.clear()

    def _collect_due_tasks(
        self,
    ) -> list[str]:
        """
        Return task IDs that are currently due.
        """

        now = datetime.now(UTC)

        due_task_ids: list[str] = []

        with self._scheduler_lock:

            for task_id, task in self._tasks.items():

                if (
                    not task.configuration.enabled
                    or task.state
                    != ScheduledTaskState.SCHEDULED
                    or task.next_run_at is None
                    or task.next_run_at > now
                ):
                    continue

                if (
                    task.active_executions > 0
                    and not task.configuration.allow_overlap
                ):

                    self._create_skipped_record(
                        task,
                        reason=(
                            "Scheduled execution skipped "
                            "because a previous execution "
                            "is still running."
                        ),
                    )

                    self._schedule_next_run(
                        task,
                        now,
                    )

                    continue

                due_task_ids.append(
                    task_id
                )

                if (
                    task.configuration.schedule_type
                    == TaskScheduleType.INTERVAL
                ):
                    self._schedule_next_run(
                        task,
                        now,
                    )

                else:
                    task.next_run_at = None

        return due_task_ids

    # =====================================================
    # EXECUTION ENGINE
    # =====================================================

    def _execute_task(
        self,
        task_id: str,
        *,
        correlation_id: str | None = None,
    ) -> TaskExecutionRecord:
        """
        Execute one task using its retry and timeout policy.
        """
        begun = self._begin_execution(
            task_id
        )

        if isinstance(
            begun,
            TaskExecutionRecord,
        ):
            return begun

        (
            task,
            started_at,
            task_name,
            retry_policy,
            timeout_seconds,
        ) = begun

        resolved_correlation_id = (
            correlation_id
            or f"task-execution-{uuid.uuid4()}"
        )

        execution_id = str(
            uuid.uuid4()
        )

        self._publish_scheduler_event(
            SchedulerEventType.TASK_STARTED,
            payload={
                "execution_id": execution_id,
                "task_id": task_id,
                "task_name": task_name,
            },
            correlation_id=resolved_correlation_id,
        )

        (
            final_status,
            attempt_count,
            result,
            error,
            timed_out,
        ) = self._run_attempts(
            task,
            execution_id=execution_id,
            task_id=task_id,
            task_name=task_name,
            retry_policy=retry_policy,
            timeout_seconds=timeout_seconds,
            correlation_id=resolved_correlation_id,
        )

        finished_at = datetime.now(UTC)

        duration_seconds = max(
            0.0,
            (
                finished_at
                - started_at
            ).total_seconds(),
        )

        record = TaskExecutionRecord(
            execution_id=execution_id,
            task_id=task_id,
            task_name=task_name,
            status=final_status,
            attempt_count=attempt_count,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            result=result,
            error=error,
            correlation_id=resolved_correlation_id,
            timed_out=timed_out,
        )

        self._finish_execution(
            task,
            record,
        )

        self._publish_execution_outcome(
            record,
            timeout_seconds,
        )

        return record

    def _begin_execution(
        self,
        task_id: str,
    ) -> TaskExecutionRecord | tuple[Any, ...]:
        """
        Claim the task for one execution, or return the skipped record.
        """

        with self._scheduler_lock:

            task = self._tasks.get(
                task_id
            )

            if task is None:
                raise TaskNotFoundError(
                    f"Task not found: {task_id}"
                )

            if task.state == ScheduledTaskState.CANCELLED:

                return self._create_skipped_record(
                    task,
                    reason="Task is cancelled.",
                )

            if (
                task.active_executions > 0
                and not task.configuration.allow_overlap
            ):

                return self._create_skipped_record(
                    task,
                    reason=(
                        "Task already has an active execution."
                    ),
                )

            task.active_executions += 1
            task.state = ScheduledTaskState.RUNNING
            task.last_started_at = datetime.now(UTC)
            task.last_error = None

            started_at = task.last_started_at
            task_name = task.configuration.name
            retry_policy = task.configuration.retry_policy
            timeout_seconds = task.configuration.timeout_seconds

            return (
                task,
                started_at,
                task_name,
                retry_policy,
                timeout_seconds,
            )

    def _run_attempts(
        self,
        task: Any,
        *,
        execution_id: str,
        task_id: str,
        task_name: str,
        retry_policy: RetryPolicy,
        timeout_seconds: float | None,
        correlation_id: str,
    ) -> tuple[TaskExecutionStatus, int, Any, str | None, bool]:
        """
        Run the task's attempts under its retry and timeout policy.
        """

        resolved_correlation_id = correlation_id

        attempt_count = 0
        result: Any = None
        error: str | None = None
        final_status = TaskExecutionStatus.FAILED
        timed_out = False

        for attempt_number in range(
            1,
            retry_policy.max_attempts + 1,
        ):

            attempt_count = attempt_number

            if attempt_number > 1:

                with self._scheduler_lock:
                    self._retry_attempts += 1

                delay = retry_policy.delay_for_attempt(
                    attempt_number
                )

                self._publish_scheduler_event(
                    SchedulerEventType.TASK_RETRYING,
                    severity=EventSeverity.WARNING,
                    payload={
                        "execution_id": execution_id,
                        "task_id": task_id,
                        "task_name": task_name,
                        "attempt_number": attempt_number,
                        "delay_seconds": delay,
                        "previous_error": error,
                    },
                    correlation_id=(
                        resolved_correlation_id
                    ),
                )

                if delay > 0:
                    time.sleep(
                        delay
                    )

            (
                completed,
                result,
                execution_error,
                timed_out,
            ) = self._run_callable_with_timeout(
                task.callable,
                timeout_seconds,
            )

            if completed and execution_error is None:

                final_status = (
                    TaskExecutionStatus.SUCCESS
                )

                error = None

                break

            if timed_out:

                final_status = (
                    TaskExecutionStatus.TIMED_OUT
                )

                error = (
                    f"Task execution exceeded timeout "
                    f"of {timeout_seconds} seconds."
                )

            else:

                final_status = (
                    TaskExecutionStatus.FAILED
                )

                error = execution_error

        return (
            final_status,
            attempt_count,
            result,
            error,
            timed_out,
        )

    def _finish_execution(
        self,
        task: Any,
        record: TaskExecutionRecord,
    ) -> None:
        """
        Apply one finished execution to the task and scheduler counters.
        """

        finished_at = record.finished_at
        final_status = record.status
        error = record.error
        task_name = record.task_name

        with self._scheduler_lock:

            task.active_executions = max(
                0,
                task.active_executions - 1,
            )

            task.run_count += 1
            task.last_finished_at = finished_at
            task.last_status = final_status
            task.last_error = error

            self._total_executions += 1
            self._last_executed_task = task_name
            self._last_error = error

            if final_status == TaskExecutionStatus.SUCCESS:

                task.success_count += 1
                self._successful_executions += 1

            elif final_status == TaskExecutionStatus.TIMED_OUT:

                task.timeout_count += 1
                task.failure_count += 1

                self._timed_out_executions += 1
                self._failed_executions += 1

            else:

                task.failure_count += 1
                self._failed_executions += 1

            if task.state != ScheduledTaskState.CANCELLED:

                if (
                    task.configuration.schedule_type
                    == TaskScheduleType.ONCE
                ):

                    task.state = (
                        ScheduledTaskState.COMPLETED
                        if final_status
                        == TaskExecutionStatus.SUCCESS
                        else ScheduledTaskState.FAILED
                    )

                    task.next_run_at = None

                elif (
                    task.configuration.schedule_type
                    == TaskScheduleType.INTERVAL
                ):

                    task.state = (
                        ScheduledTaskState.SCHEDULED
                    )

                    if task.next_run_at is None:
                        self._schedule_next_run(
                            task,
                            finished_at,
                        )

                else:

                    task.state = (
                        ScheduledTaskState.CREATED
                        if final_status
                        == TaskExecutionStatus.SUCCESS
                        else ScheduledTaskState.FAILED
                    )

            self._history.append(
                record
            )

    def _publish_execution_outcome(
        self,
        record: TaskExecutionRecord,
        timeout_seconds: float | None,
    ) -> None:
        """
        Publish the completed / timed-out / failed event for one execution.
        """

        final_status = record.status
        execution_id = record.execution_id
        task_id = record.task_id
        task_name = record.task_name
        attempt_count = record.attempt_count
        duration_seconds = record.duration_seconds
        error = record.error
        resolved_correlation_id = record.correlation_id

        if final_status == TaskExecutionStatus.SUCCESS:

            self._publish_scheduler_event(
                SchedulerEventType.TASK_COMPLETED,
                payload={
                    "execution_id": execution_id,
                    "task_id": task_id,
                    "task_name": task_name,
                    "attempt_count": attempt_count,
                    "duration_seconds": (
                        duration_seconds
                    ),
                },
                correlation_id=(
                    resolved_correlation_id
                ),
            )

        elif final_status == TaskExecutionStatus.TIMED_OUT:

            self._publish_scheduler_event(
                SchedulerEventType.TASK_TIMED_OUT,
                severity=EventSeverity.ERROR,
                payload={
                    "execution_id": execution_id,
                    "task_id": task_id,
                    "task_name": task_name,
                    "attempt_count": attempt_count,
                    "timeout_seconds": (
                        timeout_seconds
                    ),
                    "error": error,
                },
                correlation_id=(
                    resolved_correlation_id
                ),
            )

        else:

            self._publish_scheduler_event(
                SchedulerEventType.TASK_FAILED,
                severity=EventSeverity.ERROR,
                payload={
                    "execution_id": execution_id,
                    "task_id": task_id,
                    "task_name": task_name,
                    "attempt_count": attempt_count,
                    "error": error,
                },
                correlation_id=(
                    resolved_correlation_id
                ),
            )

    @staticmethod
    def _run_callable_with_timeout(
        callable: TaskCallable,
        timeout_seconds: float | None,
    ) -> tuple[
        bool,
        Any,
        str | None,
        bool,
    ]:
        """
        Execute a callable in an isolated thread.

        Returns
        -------
        completed
            True when the callable completed before timeout.

        result
            Callable return value.

        error
            Normalized exception text.

        timed_out
            True when timeout was exceeded.

        Notes
        -----
        Python threads cannot be terminated safely. A timed-out task
        thread remains daemonized until the underlying callable returns.
        """

        result_container: dict[
            str,
            Any,
        ] = {}

        completed_event = threading.Event()

        def runner() -> None:

            try:

                result_container["result"] = (
                    callable()
                )

            except BaseException as exc:

                result_container["error"] = (
                    f"{type(exc).__name__}: {exc}"
                )

            finally:

                completed_event.set()

        execution_thread = threading.Thread(
            target=runner,
            name="AtlasSchedulerCallable",
            daemon=True,
        )

        execution_thread.start()

        completed = completed_event.wait(
            timeout=timeout_seconds
        )

        if not completed:

            return (
                False,
                None,
                None,
                True,
            )

        return (
            True,
            result_container.get(
                "result"
            ),
            result_container.get(
                "error"
            ),
            False,
        )

    # =====================================================
    # SKIPPED EXECUTIONS
    # =====================================================

    def _create_skipped_record(
        self,
        task: _ScheduledTask,
        *,
        reason: str,
    ) -> TaskExecutionRecord:
        """
        Create and store a skipped execution record.
        """

        timestamp = datetime.now(UTC)

        record = TaskExecutionRecord(
            execution_id=str(
                uuid.uuid4()
            ),
            task_id=task.task_id,
            task_name=task.configuration.name,
            status=TaskExecutionStatus.SKIPPED,
            attempt_count=0,
            started_at=timestamp,
            finished_at=timestamp,
            duration_seconds=0.0,
            result=None,
            error=reason,
            correlation_id=(
                f"task-skipped-{uuid.uuid4()}"
            ),
            timed_out=False,
        )

        with self._scheduler_lock:

            task.skipped_count += 1
            task.last_status = (
                TaskExecutionStatus.SKIPPED
            )
            task.last_error = reason

            self._total_executions += 1
            self._skipped_executions += 1
            self._last_executed_task = (
                task.configuration.name
            )
            self._last_error = reason

            self._history.append(
                record
            )

        return record

    # =====================================================
    # SCHEDULING CALCULATIONS
    # =====================================================

    @staticmethod
    def _calculate_initial_run(
        configuration: TaskConfiguration,
        now: datetime,
    ) -> datetime | None:
        """
        Calculate initial task execution time.
        """

        if (
            configuration.schedule_type
            == TaskScheduleType.MANUAL
        ):
            return None

        if (
            configuration.schedule_type
            == TaskScheduleType.INTERVAL
            and configuration.run_immediately
        ):
            return now

        return (
            now
            + timedelta(
                seconds=(
                    configuration
                    .initial_delay_seconds
                )
            )
        )

    @staticmethod
    def _schedule_next_run(
        task: _ScheduledTask,
        reference_time: datetime,
    ) -> None:
        """
        Calculate next execution time for an interval task.
        """

        interval = (
            task.configuration.interval_seconds
        )

        if interval is None:
            task.next_run_at = None
            return

        task.next_run_at = (
            reference_time
            + timedelta(
                seconds=interval
            )
        )

    # =====================================================
    # TASK SNAPSHOTS
    # =====================================================

    def task_snapshot(
        self,
        task_reference: str,
    ) -> ScheduledTaskSnapshot:
        """
        Return snapshot for one task.
        """

        task_id = self._resolve_task_id(
            task_reference
        )

        with self._scheduler_lock:

            return self._snapshot_task(
                self._tasks[
                    task_id
                ]
            )

    def task_snapshots(
        self,
    ) -> tuple[
        ScheduledTaskSnapshot,
        ...,
    ]:
        """
        Return all task snapshots.
        """

        with self._scheduler_lock:

            return tuple(
                self._snapshot_task(
                    task
                )
                for task in sorted(
                    self._tasks.values(),
                    key=lambda current: (
                        current
                        .configuration
                        .name
                        .casefold()
                    ),
                )
            )

    @staticmethod
    def _snapshot_task(
        task: _ScheduledTask,
    ) -> ScheduledTaskSnapshot:
        """
        Convert internal task state into immutable snapshot.
        """

        return ScheduledTaskSnapshot(
            task_id=task.task_id,
            name=task.configuration.name,
            schedule_type=(
                task.configuration.schedule_type
            ),
            state=task.state,
            enabled=task.configuration.enabled,
            interval_seconds=(
                task.configuration.interval_seconds
            ),
            timeout_seconds=(
                task.configuration.timeout_seconds
            ),
            retry_policy=(
                task.configuration.retry_policy
            ),
            allow_overlap=(
                task.configuration.allow_overlap
            ),
            next_run_at=task.next_run_at,
            last_started_at=task.last_started_at,
            last_finished_at=(
                task.last_finished_at
            ),
            last_status=task.last_status,
            run_count=task.run_count,
            success_count=task.success_count,
            failure_count=task.failure_count,
            timeout_count=task.timeout_count,
            skipped_count=task.skipped_count,
            active_executions=(
                task.active_executions
            ),
            last_error=task.last_error,
            metadata=MappingProxyType(
                dict(
                    task.configuration.metadata
                )
            ),
        )

    # =====================================================
    # HISTORY
    # =====================================================

    def history(
        self,
        *,
        task_reference: str | None = None,
        status: TaskExecutionStatus | None = None,
        limit: int | None = None,
        newest_first: bool = False,
    ) -> tuple[
        TaskExecutionRecord,
        ...,
    ]:
        """
        Query bounded task execution history.
        """

        if (
            limit is not None
            and limit < 0
        ):
            raise ValueError(
                "limit cannot be negative."
            )

        task_id: str | None = None

        if task_reference is not None:
            task_id = self._resolve_task_id(
                task_reference
            )

        resolved_status = (
            TaskExecutionStatus(status)
            if status is not None
            else None
        )

        with self._scheduler_lock:

            records = list(
                self._history
            )

        if task_id is not None:

            records = [
                record
                for record in records
                if record.task_id == task_id
            ]

        if resolved_status is not None:

            records = [
                record
                for record in records
                if record.status
                == resolved_status
            ]

        if newest_first:
            records.reverse()

        if limit is not None:
            records = records[:limit]

        return tuple(
            records
        )

    def clear_history(
        self,
        *,
        reset_statistics: bool = False,
    ) -> None:
        """
        Clear execution history.
        """

        with self._scheduler_lock:

            self._history.clear()

            if reset_statistics:

                self._total_executions = 0
                self._successful_executions = 0
                self._failed_executions = 0
                self._timed_out_executions = 0
                self._skipped_executions = 0
                self._retry_attempts = 0
                self._last_executed_task = None
                self._last_error = None

    # =====================================================
    # STATISTICS / SNAPSHOT
    # =====================================================

    def _active_execution_count(self) -> int:
        """
        Return total active task executions.
        """

        with self._scheduler_lock:

            return sum(
                task.active_executions
                for task in self._tasks.values()
            )

    def statistics(
        self,
    ) -> SchedulerStatistics:
        """
        Return immutable Scheduler statistics.
        """

        with self._scheduler_lock:

            states = [
                task.state
                for task in self._tasks.values()
            ]

            return SchedulerStatistics(
                registered_tasks=len(
                    self._tasks
                ),
                scheduled_tasks=sum(
                    state
                    == ScheduledTaskState.SCHEDULED
                    for state in states
                ),
                paused_tasks=sum(
                    state
                    == ScheduledTaskState.PAUSED
                    for state in states
                ),
                completed_tasks=sum(
                    state
                    == ScheduledTaskState.COMPLETED
                    for state in states
                ),
                failed_tasks=sum(
                    state
                    == ScheduledTaskState.FAILED
                    for state in states
                ),
                cancelled_tasks=sum(
                    state
                    == ScheduledTaskState.CANCELLED
                    for state in states
                ),
                active_executions=sum(
                    task.active_executions
                    for task in self._tasks.values()
                ),
                total_executions=(
                    self._total_executions
                ),
                successful_executions=(
                    self._successful_executions
                ),
                failed_executions=(
                    self._failed_executions
                ),
                timed_out_executions=(
                    self._timed_out_executions
                ),
                skipped_executions=(
                    self._skipped_executions
                ),
                retry_attempts=(
                    self._retry_attempts
                ),
                event_publication_failures=(
                    self._event_publication_failures
                ),
                history_size=len(
                    self._history
                ),
                worker_alive=self.worker_alive,
                last_executed_task=(
                    self._last_executed_task
                ),
                last_error=self._last_error,
            )

    def scheduler_snapshot(
        self,
    ) -> SchedulerSnapshot:
        """
        Return complete Scheduler diagnostics.
        """

        return SchedulerSnapshot(
            running=self.is_running,
            worker_alive=self.worker_alive,
            polling_interval_seconds=(
                self._polling_interval_seconds
            ),
            task_count=self.task_count,
            history_limit=self._history_limit,
            tasks=self.task_snapshots(),
            history=self.history(),
            statistics=self.statistics(),
        )

    # =====================================================
    # EVENT PUBLICATION
    # =====================================================

    def _publish_scheduler_event(
        self,
        event_type: SchedulerEventType,
        *,
        severity: EventSeverity = EventSeverity.INFO,
        payload: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """
        Publish a scheduler event safely.
        """

        if (
            not self._publish_events
            or self._event_bus is None
        ):
            return

        try:

            self._event_bus.publish_event(
                event_type=event_type.value,
                source=self.identity.name,
                severity=severity,
                payload=dict(
                    payload or {}
                ),
                correlation_id=correlation_id,
            )

        except Exception as exc:

            error = (
                f"{type(exc).__name__}: {exc}"
            )

            with self._scheduler_lock:

                self._event_publication_failures += 1
                self._last_error = error

            logger.exception(
                "AtlasOS Scheduler event publication "
                "failed | event=%s",
                event_type.value,
            )

    # =====================================================
    # BASE SERVICE DIAGNOSTICS
    # =====================================================

    def _health_details(
        self,
    ) -> Mapping[str, Any]:
        """
        Return scheduler health details.
        """

        statistics = self.statistics()

        return {
            "worker_alive": (
                statistics.worker_alive
            ),
            "registered_tasks": (
                statistics.registered_tasks
            ),
            "scheduled_tasks": (
                statistics.scheduled_tasks
            ),
            "paused_tasks": (
                statistics.paused_tasks
            ),
            "active_executions": (
                statistics.active_executions
            ),
            "total_executions": (
                statistics.total_executions
            ),
            "successful_executions": (
                statistics.successful_executions
            ),
            "failed_executions": (
                statistics.failed_executions
            ),
            "timed_out_executions": (
                statistics.timed_out_executions
            ),
            "skipped_executions": (
                statistics.skipped_executions
            ),
            "retry_attempts": (
                statistics.retry_attempts
            ),
            "event_publication_failures": (
                statistics
                .event_publication_failures
            ),
            "history_size": (
                statistics.history_size
            ),
            "last_executed_task": (
                statistics.last_executed_task
            ),
            "last_error": (
                statistics.last_error
            ),
        }

    def _snapshot_metadata(
        self,
    ) -> Mapping[str, Any]:
        """
        Return scheduler configuration metadata.
        """

        return {
            "polling_interval_seconds": (
                self._polling_interval_seconds
            ),
            "history_limit": (
                self._history_limit
            ),
            "publish_events": (
                self._publish_events
            ),
            "event_bus_configured": (
                self._event_bus is not None
            ),
            "supported_schedule_types": [
                schedule_type.value
                for schedule_type
                in TaskScheduleType
            ],
        }