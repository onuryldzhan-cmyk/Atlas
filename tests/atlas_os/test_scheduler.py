"""
============================================================
ATLAS OS SCHEDULER SERVICE TESTS
============================================================

Comprehensive unit and integration tests for SchedulerService.

Coverage
--------
- Scheduler worker lifecycle
- Manual task registration
- One-time task execution
- Interval task execution
- Retry policies
- Timeout detection
- Pause and resume
- Task cancellation
- Task removal
- Execution history
- Bounded history
- Scheduler statistics
- Scheduler snapshots
- Scheduler health reporting
- Event Bus integration

============================================================
"""

from __future__ import annotations

import threading
import time
import unittest

from atlas_os import (
    DuplicateTaskError,
    EventBusService,
    HealthStatus,
    InvalidTaskConfigurationError,
    RetryPolicy,
    ScheduledTaskState,
    SchedulerService,
    TaskExecutionStatus,
    TaskNotFoundError,
    TaskScheduleType,
)


class SchedulerServiceTests(unittest.TestCase):
    """
    Core SchedulerService tests.
    """

    def setUp(self) -> None:
        """
        Create and start a fresh scheduler before every test.
        """

        self.scheduler = SchedulerService(
            polling_interval_seconds=0.01,
            history_limit=10,
        )

        self.scheduler.start()

    def tearDown(self) -> None:
        """
        Stop the scheduler after every test.
        """

        if self.scheduler.is_running:
            self.scheduler.stop()

    def test_scheduler_starts_worker(self) -> None:
        """
        Scheduler start must activate the background worker.
        """

        self.assertTrue(
            self.scheduler.worker_alive
        )

    def test_manual_task_registration(self) -> None:
        """
        Manual tasks must be registered and discoverable.
        """

        task_id = self.scheduler.register_manual(
            "ManualTask",
            lambda: "done",
        )

        self.assertTrue(
            self.scheduler.task_exists(
                task_id
            )
        )

        snapshot = self.scheduler.task_snapshot(
            task_id
        )

        self.assertEqual(
            snapshot.schedule_type,
            TaskScheduleType.MANUAL,
        )

    def test_duplicate_task_name_is_rejected(
        self,
    ) -> None:
        """
        Task names must be unique without regard to case.
        """

        self.scheduler.register_manual(
            "DuplicateTask",
            lambda: None,
        )

        with self.assertRaises(
            DuplicateTaskError
        ):

            self.scheduler.register_manual(
                "duplicatetask",
                lambda: None,
            )

    def test_unknown_task_is_rejected(self) -> None:
        """
        Looking up an unknown task must raise TaskNotFoundError.
        """

        with self.assertRaises(
            TaskNotFoundError
        ):

            self.scheduler.task_snapshot(
                "MissingTask"
            )

    def test_manual_task_execution_success(
        self,
    ) -> None:
        """
        Successful manual execution must return its result.
        """

        self.scheduler.register_manual(
            "SuccessTask",
            lambda: {
                "status": "ok",
            },
        )

        record = self.scheduler.run_task(
            "SuccessTask"
        )

        self.assertEqual(
            record.status,
            TaskExecutionStatus.SUCCESS,
        )

        self.assertEqual(
            record.result,
            {
                "status": "ok",
            },
        )

    def test_failed_task_is_recorded(self) -> None:
        """
        Task exceptions must be isolated and recorded.
        """

        def failing_task() -> None:
            raise RuntimeError(
                "Simulated task failure."
            )

        self.scheduler.register_manual(
            "FailingTask",
            failing_task,
        )

        record = self.scheduler.run_task(
            "FailingTask"
        )

        self.assertEqual(
            record.status,
            TaskExecutionStatus.FAILED,
        )

        self.assertIn(
            "Simulated task failure",
            record.error,
        )

    def test_retry_policy_recovers_task(self) -> None:
        """
        A recoverable task must succeed within its retry policy.
        """

        attempts = {
            "count": 0,
        }

        def recoverable_task() -> str:

            attempts["count"] += 1

            if attempts["count"] < 3:
                raise RuntimeError(
                    "Temporary failure."
                )

            return "recovered"

        self.scheduler.register_manual(
            "RecoverableTask",
            recoverable_task,
            retry_policy=RetryPolicy(
                max_attempts=3,
            ),
        )

        record = self.scheduler.run_task(
            "RecoverableTask"
        )

        self.assertEqual(
            record.status,
            TaskExecutionStatus.SUCCESS,
        )

        self.assertEqual(
            record.attempt_count,
            3,
        )

        self.assertEqual(
            record.result,
            "recovered",
        )

    def test_task_timeout_is_recorded(self) -> None:
        """
        A task exceeding its timeout must be marked timed out.
        """

        def slow_task() -> None:

            time.sleep(
                0.05
            )

        self.scheduler.register_manual(
            "SlowTask",
            slow_task,
            timeout_seconds=0.005,
        )

        record = self.scheduler.run_task(
            "SlowTask"
        )

        self.assertEqual(
            record.status,
            TaskExecutionStatus.TIMED_OUT,
        )

        self.assertTrue(
            record.timed_out
        )

    def test_once_task_runs_automatically(
        self,
    ) -> None:
        """
        A one-time task must execute automatically once.
        """

        completed = threading.Event()

        self.scheduler.register_once(
            "OneTimeTask",
            completed.set,
            delay_seconds=0.01,
        )

        self.assertTrue(
            completed.wait(
                timeout=0.5
            )
        )

        time.sleep(
            0.02
        )

        snapshot = self.scheduler.task_snapshot(
            "OneTimeTask"
        )

        self.assertEqual(
            snapshot.run_count,
            1,
        )

        self.assertEqual(
            snapshot.state,
            ScheduledTaskState.COMPLETED,
        )

    def test_interval_task_runs_repeatedly(
        self,
    ) -> None:
        """
        Interval tasks must execute repeatedly.
        """

        lock = threading.Lock()

        executions = {
            "count": 0,
        }

        completed = threading.Event()

        def recurring_task() -> None:

            with lock:

                executions["count"] += 1

                if executions["count"] >= 3:
                    completed.set()

        self.scheduler.register_interval(
            "RecurringTask",
            recurring_task,
            interval_seconds=0.02,
            run_immediately=True,
        )

        self.assertTrue(
            completed.wait(
                timeout=1.0
            )
        )

        self.scheduler.pause_task(
            "RecurringTask"
        )

        with lock:
            count = executions["count"]

        self.assertGreaterEqual(
            count,
            3,
        )

    def test_pause_task(self) -> None:
        """
        Pausing a task must remove its next execution time.
        """

        task_id = self.scheduler.register_interval(
            "PauseTask",
            lambda: None,
            interval_seconds=1.0,
        )

        snapshot = self.scheduler.pause_task(
            task_id
        )

        self.assertEqual(
            snapshot.state,
            ScheduledTaskState.PAUSED,
        )

        self.assertIsNone(
            snapshot.next_run_at
        )

    def test_resume_task(self) -> None:
        """
        Resuming an interval task must schedule it again.
        """

        task_id = self.scheduler.register_interval(
            "ResumeTask",
            lambda: None,
            interval_seconds=1.0,
        )

        self.scheduler.pause_task(
            task_id
        )

        snapshot = self.scheduler.resume_task(
            task_id
        )

        self.assertEqual(
            snapshot.state,
            ScheduledTaskState.SCHEDULED,
        )

        self.assertIsNotNone(
            snapshot.next_run_at
        )

    def test_cancel_task(self) -> None:
        """
        Cancelling a task must prevent future execution.
        """

        task_id = self.scheduler.register_interval(
            "CancelTask",
            lambda: None,
            interval_seconds=1.0,
        )

        snapshot = self.scheduler.cancel_task(
            task_id
        )

        self.assertEqual(
            snapshot.state,
            ScheduledTaskState.CANCELLED,
        )

        self.assertIsNone(
            snapshot.next_run_at
        )

    def test_remove_task(self) -> None:
        """
        Removed tasks must no longer exist.
        """

        task_id = self.scheduler.register_manual(
            "RemoveTask",
            lambda: None,
        )

        snapshot = self.scheduler.remove_task(
            task_id
        )

        self.assertEqual(
            snapshot.name,
            "RemoveTask",
        )

        self.assertFalse(
            self.scheduler.task_exists(
                task_id
            )
        )

    def test_history_can_be_filtered(
        self,
    ) -> None:
        """
        Execution history must support status filtering.
        """

        self.scheduler.register_manual(
            "HistorySuccess",
            lambda: "ok",
        )

        def failing() -> None:
            raise RuntimeError(
                "Failure"
            )

        self.scheduler.register_manual(
            "HistoryFailure",
            failing,
        )

        self.scheduler.run_task(
            "HistorySuccess"
        )

        self.scheduler.run_task(
            "HistoryFailure"
        )

        failed_records = (
            self.scheduler.history(
                status=(
                    TaskExecutionStatus.FAILED
                )
            )
        )

        self.assertEqual(
            len(failed_records),
            1,
        )

        self.assertEqual(
            failed_records[0].task_name,
            "HistoryFailure",
        )

    def test_history_is_bounded(self) -> None:
        """
        Scheduler history must respect its configured limit.
        """

        for index in range(15):

            name = f"Task{index}"

            self.scheduler.register_manual(
                name,
                lambda: None,
            )

            self.scheduler.run_task(
                name
            )

        self.assertEqual(
            len(
                self.scheduler.history()
            ),
            10,
        )

    def test_statistics_are_recorded(self) -> None:
        """
        Successful executions must update statistics.
        """

        self.scheduler.register_manual(
            "StatisticsTask",
            lambda: "ok",
        )

        self.scheduler.run_task(
            "StatisticsTask"
        )

        statistics = (
            self.scheduler.statistics()
        )

        self.assertEqual(
            statistics.registered_tasks,
            1,
        )

        self.assertEqual(
            statistics.total_executions,
            1,
        )

        self.assertEqual(
            statistics.successful_executions,
            1,
        )

    def test_snapshot_contains_tasks(self) -> None:
        """
        Scheduler snapshots must contain registered tasks.
        """

        self.scheduler.register_manual(
            "SnapshotTask",
            lambda: None,
        )

        snapshot = (
            self.scheduler
            .scheduler_snapshot()
        )

        self.assertTrue(
            snapshot.running
        )

        self.assertTrue(
            snapshot.worker_alive
        )

        self.assertEqual(
            snapshot.task_count,
            1,
        )

        self.assertEqual(
            snapshot.tasks[0].name,
            "SnapshotTask",
        )

    def test_health_contains_scheduler_data(
        self,
    ) -> None:
        """
        Scheduler health reports must include runtime details.
        """

        self.scheduler.register_manual(
            "HealthTask",
            lambda: None,
        )

        report = self.scheduler.health()

        self.assertEqual(
            report.status,
            HealthStatus.HEALTHY,
        )

        self.assertEqual(
            report.details[
                "registered_tasks"
            ],
            1,
        )

        self.assertTrue(
            report.details[
                "worker_alive"
            ]
        )

    def test_invalid_interval_is_rejected(
        self,
    ) -> None:
        """
        Zero-length intervals must be rejected.
        """

        with self.assertRaises(
            InvalidTaskConfigurationError
        ):

            self.scheduler.register_interval(
                "InvalidInterval",
                lambda: None,
                interval_seconds=0,
            )

    def test_clear_history_preserves_tasks(
        self,
    ) -> None:
        """
        Clearing history must not remove task registrations.
        """

        self.scheduler.register_manual(
            "ClearHistoryTask",
            lambda: None,
        )

        self.scheduler.run_task(
            "ClearHistoryTask"
        )

        self.scheduler.clear_history()

        self.assertEqual(
            len(
                self.scheduler.history()
            ),
            0,
        )

        self.assertTrue(
            self.scheduler.task_exists(
                "ClearHistoryTask"
            )
        )


class SchedulerEventBusTests(unittest.TestCase):
    """
    Scheduler and EventBus integration tests.
    """

    def setUp(self) -> None:
        """
        Create Event Bus and event-enabled Scheduler.
        """

        self.event_bus = EventBusService(
            history_limit=100
        )

        self.event_bus.start()

        self.scheduler = SchedulerService(
            polling_interval_seconds=0.01,
            history_limit=100,
            event_bus=self.event_bus,
            publish_events=True,
        )

        self.scheduler.start()

    def tearDown(self) -> None:
        """
        Stop Scheduler before stopping Event Bus.
        """

        if self.scheduler.is_running:
            self.scheduler.stop()

        if self.event_bus.is_running:
            self.event_bus.stop()

    def test_scheduler_events_are_published(
        self,
    ) -> None:
        """
        Scheduler registration and execution events must be published.
        """

        self.scheduler.register_manual(
            "EventTask",
            lambda: "done",
        )

        self.scheduler.run_task(
            "EventTask"
        )

        event_types = [
            event.event_type
            for event
            in self.event_bus.event_history()
        ]

        self.assertIn(
            "TASK_REGISTERED",
            event_types,
        )

        self.assertIn(
            "TASK_STARTED",
            event_types,
        )

        self.assertIn(
            "TASK_COMPLETED",
            event_types,
        )

    def test_failed_task_event_is_published(
        self,
    ) -> None:
        """
        Failed task executions must publish TASK_FAILED.
        """

        def failing_task() -> None:

            raise RuntimeError(
                "Scheduler event failure."
            )

        self.scheduler.register_manual(
            "FailureEventTask",
            failing_task,
        )

        self.scheduler.run_task(
            "FailureEventTask"
        )

        event_types = [
            event.event_type
            for event
            in self.event_bus.event_history()
        ]

        self.assertIn(
            "TASK_FAILED",
            event_types,
        )

    def test_timeout_event_is_published(
        self,
    ) -> None:
        """
        Timed-out task executions must publish TASK_TIMED_OUT.
        """

        self.scheduler.register_manual(
            "TimeoutEventTask",
            lambda: time.sleep(
                0.05
            ),
            timeout_seconds=0.005,
        )

        self.scheduler.run_task(
            "TimeoutEventTask"
        )

        event_types = [
            event.event_type
            for event
            in self.event_bus.event_history()
        ]

        self.assertIn(
            "TASK_TIMED_OUT",
            event_types,
        )


if __name__ == "__main__":
    unittest.main()