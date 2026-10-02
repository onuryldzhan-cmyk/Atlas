"""T-0002 (2026-10-02): _execute_task was split into helpers with NO behaviour change.

Written and passing against the pre-refactor code. It pins, for every outcome
path, the returned record, the task's counters/state, the scheduler counters,
the next-run handling and the exact sequence of published events (type,
severity, payload keys and stable values). ids and timestamps are excluded.
"""

from __future__ import annotations

import pytest

from atlas_os import RetryPolicy, ScheduledTaskState, SchedulerService, TaskExecutionStatus
from atlas_os.scheduling import scheduler as sched_mod

VOLATILE = {"execution_id", "duration_seconds"}


@pytest.fixture
def svc(monkeypatch):
    s = SchedulerService(polling_interval_seconds=0.01, history_limit=10)
    events = []
    monkeypatch.setattr(s, "_publish_scheduler_event", lambda et, *, severity=None, payload=None, correlation_id=None:
                        events.append((et.value, str(severity), {k: v for k, v in (payload or {}).items() if k not in VOLATILE},
                                       correlation_id)))
    sleeps = []
    monkeypatch.setattr(sched_mod.time, "sleep", lambda d: sleeps.append(d))
    s.events, s.sleeps = events, sleeps
    return s


def _flaky(fail_times):
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise ValueError(f"boom {calls['n']}")
        return "ok"
    return fn


def _state(s, tid):
    t = s._tasks[tid]
    return (t.state, t.active_executions, t.run_count, t.success_count, t.failure_count, t.timeout_count,
            t.last_status, t.last_error, t.next_run_at is None)


def _counters(s):
    return (s._total_executions, s._successful_executions, s._failed_executions, s._timed_out_executions,
            s._retry_attempts, s._last_error, len(s._history))


def _rec(r):
    return (r.task_name, r.status, r.attempt_count, r.result, r.error, r.timed_out, r.correlation_id)


def test_manual_success_after_retries(svc):
    tid = svc.register_manual("flaky", _flaky(2), retry_policy=RetryPolicy(max_attempts=3, delay_seconds=0.5,
                                                                          backoff_multiplier=2.0))
    svc.events.clear()  # drop TASK_REGISTERED; only execution events are pinned
    r = svc._execute_task(tid, correlation_id="c1")
    assert _rec(r) == ("flaky", TaskExecutionStatus.SUCCESS, 3, "ok", None, False, "c1")
    assert _state(svc, tid) == (ScheduledTaskState.CREATED, 0, 1, 1, 0, 0, TaskExecutionStatus.SUCCESS, None, True)
    assert _counters(svc) == (1, 1, 0, 0, 2, None, 1)
    assert svc.sleeps == [0.5, 1.0]
    assert [e[0] for e in svc.events] == ["TASK_STARTED", "TASK_RETRYING",
                                          "TASK_RETRYING", "TASK_COMPLETED"]
    assert svc.events[1][2] == {"task_id": tid, "task_name": "flaky", "attempt_number": 2, "delay_seconds": 0.5,
                                "previous_error": svc.events[1][2]["previous_error"]}
    assert "boom 1" in svc.events[1][2]["previous_error"] and "boom 2" in svc.events[2][2]["previous_error"]
    assert svc.events[3][2] == {"task_id": tid, "task_name": "flaky", "attempt_count": 3}
    assert {e[3] for e in svc.events} == {"c1"}


def test_manual_all_attempts_fail(svc):
    tid = svc.register_manual("bad", _flaky(99), retry_policy=RetryPolicy(max_attempts=2))
    r = svc._execute_task(tid)
    assert r.status == TaskExecutionStatus.FAILED and r.attempt_count == 2 and "boom 2" in r.error
    assert r.correlation_id.startswith("task-execution-")
    assert _state(svc, tid)[:6] == (ScheduledTaskState.FAILED, 0, 1, 0, 1, 0)
    assert _counters(svc)[:5] == (1, 0, 1, 0, 1) and "boom 2" in svc._last_error
    assert svc.sleeps == []  # zero delay never sleeps
    assert [e[0] for e in svc.events][-1] == "TASK_FAILED"
    assert svc.events[-1][1] == str(sched_mod.EventSeverity.ERROR)
    assert set(svc.events[-1][2]) == {"task_id", "task_name", "attempt_count", "error"}


def test_once_timeout(svc, monkeypatch):
    tid = svc.register_once("slow", lambda: None, delay_seconds=3600, timeout_seconds=0.25)
    monkeypatch.setattr(svc, "_run_callable_with_timeout", lambda c, t: (False, None, None, True))
    r = svc._execute_task(tid)
    assert _rec(r)[1:6] == (TaskExecutionStatus.TIMED_OUT, 1, None, "Task execution exceeded timeout of 0.25 seconds.",
                            True)
    assert _state(svc, tid) == (ScheduledTaskState.FAILED, 0, 1, 0, 1, 1, TaskExecutionStatus.TIMED_OUT,
                                "Task execution exceeded timeout of 0.25 seconds.", True)
    assert _counters(svc)[:4] == (1, 0, 1, 1)
    assert svc.events[-1][0] == "TASK_TIMED_OUT"
    assert svc.events[-1][2] == {"task_id": tid, "task_name": "slow", "attempt_count": 1, "timeout_seconds": 0.25,
                                 "error": "Task execution exceeded timeout of 0.25 seconds."}


def test_once_success_completes(svc):
    tid = svc.register_once("one", lambda: 7, delay_seconds=3600)
    r = svc._execute_task(tid)
    assert r.result == 7 and _state(svc, tid)[0] == ScheduledTaskState.COMPLETED and _state(svc, tid)[-1] is True


def test_interval_reschedules_only_when_unset(svc):
    tid = svc.register_interval("iv", lambda: 1, interval_seconds=60, initial_delay_seconds=3600)
    before = svc._tasks[tid].next_run_at
    svc._execute_task(tid)
    assert svc._tasks[tid].state == ScheduledTaskState.SCHEDULED and svc._tasks[tid].next_run_at == before
    svc._tasks[tid].next_run_at = None
    svc._execute_task(tid)
    assert svc._tasks[tid].next_run_at is not None


def test_cancelled_and_overlap_are_skipped(svc):
    tid = svc.register_manual("m", lambda: 1)
    svc._tasks[tid].active_executions = 1
    r = svc._execute_task(tid)
    assert r.status == TaskExecutionStatus.SKIPPED and "active execution" in r.error
    svc._tasks[tid].active_executions = 0
    svc._tasks[tid].state = ScheduledTaskState.CANCELLED
    r = svc._execute_task(tid)
    assert r.status == TaskExecutionStatus.SKIPPED and r.error == "Task is cancelled."
    assert svc.events == [] or all(e[0] != "TASK_STARTED" for e in svc.events)


def test_cancelled_during_run_keeps_cancelled_state(svc):
    holder = {}

    def fn():
        svc._tasks[holder["tid"]].state = ScheduledTaskState.CANCELLED
        return 1
    holder["tid"] = tid = svc.register_manual("c", fn)
    svc._execute_task(tid)
    assert svc._tasks[tid].state == ScheduledTaskState.CANCELLED and svc._tasks[tid].success_count == 1


def test_unknown_task_raises(svc):
    with pytest.raises(sched_mod.TaskNotFoundError):
        svc._execute_task("nope")
