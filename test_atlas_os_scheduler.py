"""
============================================================
ATLAS OS SCHEDULER INTEGRATION TEST
============================================================
"""

from __future__ import annotations

import json
import threading
import time

from atlas_os import (
    AuditLogService,
    EventBusService,
    MetricsService,
    RetryPolicy,
    SchedulerService,
)


def main() -> None:

    print("=" * 60)
    print("ATLAS OS SCHEDULER SERVICE v1.0")
    print("=" * 60)

    event_bus = EventBusService(
        history_limit=1000
    )

    event_bus.start()

    audit = AuditLogService(
        event_bus,
        audit_file=(
            "runtime_data/audit/"
            "atlas_os_scheduler_demo.jsonl"
        ),
        history_limit=1000,
    )

    audit.start()

    metrics = MetricsService(
        event_bus=event_bus,
        collect_event_metrics=True,
        histogram_history_limit=100,
    )

    metrics.start()

    scheduler = SchedulerService(
        polling_interval_seconds=0.01,
        history_limit=1000,
        event_bus=event_bus,
        publish_events=True,
    )

    scheduler.start()

    recurring_complete = threading.Event()

    execution_state = {
        "health_checks": 0,
        "market_scans": 0,
        "retry_attempts": 0,
    }

    def health_check() -> dict[str, object]:

        execution_state[
            "health_checks"
        ] += 1

        metrics.increment(
            "atlas.scheduler.health_checks.total"
        )

        print(
            "[TASK] Health check completed."
        )

        return {
            "healthy": True,
            "check_number": (
                execution_state[
                    "health_checks"
                ]
            ),
        }

    def market_scan() -> dict[str, object]:

        execution_state[
            "market_scans"
        ] += 1

        metrics.increment(
            "atlas.scheduler.market_scans.total"
        )

        print(
            "[TASK] Market scan completed."
        )

        if (
            execution_state[
                "market_scans"
            ] >= 3
        ):
            recurring_complete.set()

        return {
            "symbols_scanned": 25,
            "scan_number": (
                execution_state[
                    "market_scans"
                ]
            ),
        }

    def recoverable_task() -> str:

        execution_state[
            "retry_attempts"
        ] += 1

        print(
            "[TASK] Recoverable task attempt:",
            execution_state[
                "retry_attempts"
            ],
        )

        if (
            execution_state[
                "retry_attempts"
            ] < 3
        ):
            raise RuntimeError(
                "Temporary simulated failure."
            )

        return "RECOVERED"

    scheduler.register_once(
        "InitialHealthCheck",
        health_check,
        delay_seconds=0.01,
    )

    scheduler.register_interval(
        "MarketScanner",
        market_scan,
        interval_seconds=0.05,
        run_immediately=True,
        allow_overlap=False,
    )

    scheduler.register_manual(
        "RecoverableTask",
        recoverable_task,
        retry_policy=RetryPolicy(
            max_attempts=3,
            delay_seconds=0.01,
            backoff_multiplier=1.0,
        ),
    )

    print("\nMANUAL RETRY TASK")
    print("-" * 60)

    retry_record = scheduler.run_task(
        "RecoverableTask"
    )

    recurring_complete.wait(
        timeout=2.0
    )

    scheduler.pause_task(
        "MarketScanner"
    )

    time.sleep(
        0.05
    )

    snapshot = (
        scheduler.scheduler_snapshot()
    )

    statistics = (
        snapshot.statistics
    )

    print("\nSCHEDULER SNAPSHOT")
    print("-" * 60)

    print(
        json.dumps(
            {
                "running": snapshot.running,
                "worker_alive": (
                    snapshot.worker_alive
                ),
                "task_count": (
                    snapshot.task_count
                ),
                "history_size": (
                    statistics.history_size
                ),
                "total_executions": (
                    statistics.total_executions
                ),
                "successful_executions": (
                    statistics
                    .successful_executions
                ),
                "failed_executions": (
                    statistics.failed_executions
                ),
                "timed_out_executions": (
                    statistics
                    .timed_out_executions
                ),
                "retry_attempts": (
                    statistics.retry_attempts
                ),
                "event_publication_failures": (
                    statistics
                    .event_publication_failures
                ),
                "health_checks": (
                    execution_state[
                        "health_checks"
                    ]
                ),
                "market_scans": (
                    execution_state[
                        "market_scans"
                    ]
                ),
                "recoverable_status": (
                    retry_record.status.value
                ),
                "recoverable_attempts": (
                    retry_record.attempt_count
                ),
                "audit_records": (
                    audit.statistics()
                    .records_persisted
                ),
                "event_metrics": (
                    metrics.counter_value(
                        "atlas.events.total",
                        default=0,
                    )
                ),
            },
            indent=4,
        )
    )

    print("\nTASKS")
    print("-" * 60)

    for task in snapshot.tasks:

        print(
            f"{task.name:<24} | "
            f"{task.schedule_type.value:<8} | "
            f"{task.state.value:<10} | "
            f"runs={task.run_count:<3} | "
            f"success={task.success_count:<3} | "
            f"failures={task.failure_count:<3}"
        )

    print("\nEXECUTION HISTORY")
    print("-" * 60)

    for index, record in enumerate(
        snapshot.history,
        start=1,
    ):

        print(
            f"{index:02d}. "
            f"{record.task_name:<24} | "
            f"{record.status.value:<10} | "
            f"attempts={record.attempt_count:<2} | "
            f"duration={record.duration_seconds:.6f}"
        )

    scheduler.stop()
    metrics.stop()
    audit.stop()
    event_bus.stop()


if __name__ == "__main__":
    main()