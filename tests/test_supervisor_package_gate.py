"""SUPERVISOR-1 final gate: the three steps audited as one aggregate change.

Steps 1-3 were reviewed in isolation and each passed. This file covers what
none of those reviews could see - the seams between them, exercised end to
end through real processes rather than through any one step's unit scope:

ORPHANING
    The supervisor holds a live child. Anything that escapes its main loop
    would leave that child running with nobody watching it and durable
    financial state still open. The loop must give the child back to the
    operating system on every exit path it can take, including the one a
    bare ``except Exception`` cannot catch.

EXIT 0 WHILE HALTED
    Step 2 made health() tell the truth about a runtime halted in
    RECOVERY_REQUIRED; step 3 made exit code 0 terminal. A graceful stop of
    an already-halted runtime lands on both rules at once, and the outcome
    has to be right for an operator, not merely defensible.

PROVENANCE ROUND TRIP
    supervisor epoch and restart count leave the supervisor as environment
    variables and have to arrive as fields on /api/health. Step 3 proved
    each hop separately; this proves the whole path across a real restart.

INJECTION
    Those same fields are published verbatim in an HTTP response body. The
    rejection of a malformed value is asserted against the serialised JSON,
    not against the parsing helper that produces it.

No test here starts Atlas's runtime. AtlasApplication is *constructed*
against an isolated scratch state directory - which is what health() needs
and all it needs - and never started, so nothing reaches an exchange and no
durable store of the repository's is touched.
"""

from __future__ import annotations

import json
import subprocess
import sys

from pathlib import Path

import pytest

import atlas_supervisor

from atlas_supervisor import ProcessSupervisor, RestartPolicy


WINDOWS_ONLY = pytest.mark.skipif(
    not hasattr(__import__("signal"), "CTRL_BREAK_EVENT"),
    reason="CTRL_BREAK_EVENT / CREATE_NEW_PROCESS_GROUP are Windows-only",
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

_FAST_POLICY = RestartPolicy(
    max_attempts=5,
    backoff_seconds=(0.01,) * 5,
    healthy_run_seconds=600.0,
)


# =====================================================================
# Child programs
# =====================================================================


# Stays alive until it is killed, so the parent can assert on whether the
# supervisor let go of it.
_CHILD_LONG_RUNNING = '''
import sys
import threading
import time

print("ATLAS_AUDIT_READY")
sys.stdout.flush()

idle = threading.Event()
deadline = time.monotonic() + 300
while time.monotonic() < deadline:
    idle.wait(0.2)
'''


# Builds the real health pipeline - a real AtlasApplication on a scratch
# state directory, the real web_app factory, the real /api/health route -
# and reports the serialised response. Never started: construction is what
# reads the supervisor environment, and health() needs nothing more.
_CHILD_REPORTS_HEALTH = '''
import json
import os
import sys

sys.path.insert(0, sys.argv[1])

from fastapi.testclient import TestClient

from core.application import AtlasApplication
from web_app import create_app

runtime = AtlasApplication(state_directory=sys.argv[2])
api = create_app(runtime=runtime, price_provider=lambda symbol: 1.0)

with TestClient(api) as client:
    response = client.get("/api/health")

print("ATLAS_AUDIT_HEALTH " + json.dumps({
    "status": response.status_code,
    "body": response.text,
}))
sys.stdout.flush()

# Crash once, then exit cleanly, so the parent observes a real restart.
restarts = int(os.environ.get("ATLAS_SUPERVISOR_RESTART_COUNT", "0"))

raise SystemExit(0 if restarts >= 1 else 1)
'''


def _write_child(tmp_path: Path, source: str, name: str) -> Path:
    script = tmp_path / name
    script.write_text(source, encoding="utf-8")
    return script


def _collect(process: subprocess.Popen, marker: str) -> list[dict]:
    assert process.stdout is not None

    payloads = []

    for line in process.stdout:
        if line.startswith(marker):
            payloads.append(json.loads(line[len(marker):]))

    return payloads


# =====================================================================
# 1. The supervisor must never orphan a live Atlas
# =====================================================================


def _supervisor_over_a_live_child(
    tmp_path: Path,
    fault: BaseException,
) -> tuple[ProcessSupervisor, list[subprocess.Popen]]:
    """Launch a real long-running child, then fault the supervisor's loop.

    The clock is the injection point only because it is the first thing the
    loop touches after the child is live; the finding is about any fault in
    that window, not about the clock.
    """

    script = _write_child(tmp_path, _CHILD_LONG_RUNNING, "atlas_long_child.py")

    spawned: list[subprocess.Popen] = []

    def launch(environment: dict[str, str]) -> subprocess.Popen:
        process = subprocess.Popen(
            [sys.executable, str(script)],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=atlas_supervisor.CREATION_FLAGS,
        )
        spawned.append(process)

        assert process.stdout is not None
        for line in process.stdout:
            if line.startswith("ATLAS_AUDIT_READY"):
                break

        return process

    def faulting_monotonic() -> float:
        raise fault

    supervisor = ProcessSupervisor(
        policy=_FAST_POLICY,
        launch=launch,
        monotonic=faulting_monotonic,
    )

    return supervisor, spawned


@WINDOWS_ONLY
def test_a_fault_in_the_loop_does_not_orphan_a_live_child(
    tmp_path: Path,
) -> None:
    """An escaping exception must still hand the child back to the OS.

    The supervisor is the only thing holding this process. If it dies while
    the child is live, Atlas keeps running with nobody watching it and its
    durable financial state still open - the precise outcome this package
    exists to prevent, arrived at from the other direction.
    """

    supervisor, spawned = _supervisor_over_a_live_child(
        tmp_path,
        RuntimeError("fault inside the supervisor loop"),
    )

    with pytest.raises(RuntimeError):
        supervisor.run()

    assert spawned, "no child was launched"

    assert spawned[0].poll() is not None, (
        "the supervisor died and left a live Atlas process behind"
    )
    assert supervisor.child is None


@WINDOWS_ONLY
def test_a_keyboard_interrupt_does_not_orphan_a_live_child(
    tmp_path: Path,
) -> None:
    """The case a bare ``except Exception`` would miss.

    KeyboardInterrupt is a BaseException, and it is the realistic fault here:
    a supervisor used without install_signal_handlers() gets one straight
    through on Ctrl+C. Only a finally-shaped cleanup covers it.
    """

    supervisor, spawned = _supervisor_over_a_live_child(
        tmp_path,
        KeyboardInterrupt(),
    )

    with pytest.raises(KeyboardInterrupt):
        supervisor.run()

    assert spawned, "no child was launched"

    assert spawned[0].poll() is not None, (
        "Ctrl+C killed the supervisor and left a live Atlas process behind"
    )
    assert supervisor.child is None


# =====================================================================
# 2. Exit 0 from an already-halted runtime
# =====================================================================


@WINDOWS_ONLY
def test_a_graceful_stop_of_a_halted_runtime_is_terminal(
    tmp_path: Path,
) -> None:
    """Step 2's halt reporting and step 3's exit-0 rule, together.

    A runtime halted in RECOVERY_REQUIRED still exits 0 when an operator
    stops it, because the *stop* was clean even though the runtime was not.
    Restarting it would be strictly wrong: the halt is a durable-state
    condition, so a restarted Atlas re-reads the same state and halts again.
    Only an operator can clear it, and a supervisor that kept restarting
    would bury that fact under a restart loop.
    """

    halted_then_clean_exit = '''
import sys

print("ATLAS_AUDIT_HEALTH " + '{"healthy": false, '
      '"execution_recovery_required": true}')
sys.stdout.flush()

raise SystemExit(0)
'''

    script = _write_child(
        tmp_path,
        halted_then_clean_exit,
        "atlas_halted_child.py",
    )

    launches: list[subprocess.Popen] = []

    def launch(environment: dict[str, str]) -> subprocess.Popen:
        process = subprocess.Popen(
            [sys.executable, str(script)],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=atlas_supervisor.CREATION_FLAGS,
        )
        launches.append(process)
        return process

    supervisor = ProcessSupervisor(policy=_FAST_POLICY, launch=launch)

    assert supervisor.run() == 0

    # Launched once and never restarted.
    assert len(launches) == 1

    reported = _collect(launches[0], "ATLAS_AUDIT_HEALTH ")

    assert reported and reported[0]["execution_recovery_required"] is True


# =====================================================================
# 3. Provenance round trip, across a real restart
# =====================================================================


@WINDOWS_ONLY
def test_supervisor_provenance_reaches_api_health_across_a_restart(
    tmp_path: Path,
) -> None:
    """env var -> child -> AtlasApplication.health() -> /api/health.

    Each hop was proven separately in step 3. This is the whole path, twice,
    with a genuine restart in between, against the real web application.
    """

    script = _write_child(
        tmp_path,
        _CHILD_REPORTS_HEALTH,
        "atlas_health_child.py",
    )

    launches: list[subprocess.Popen] = []

    def launch(environment: dict[str, str]) -> subprocess.Popen:
        index = len(launches)
        process = subprocess.Popen(
            [
                sys.executable,
                str(script),
                str(REPOSITORY_ROOT),
                str(tmp_path / f"state-{index}"),
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=atlas_supervisor.CREATION_FLAGS,
        )
        launches.append(process)
        return process

    supervisor = ProcessSupervisor(
        policy=_FAST_POLICY,
        launch=launch,
        epoch="e" * 32,
    )

    assert supervisor.run() == 0
    assert len(launches) == 2, "the child was not restarted"

    reports = []
    for process in launches:
        payloads = _collect(process, "ATLAS_AUDIT_HEALTH ")
        assert payloads, "child produced no /api/health payload"
        reports.append(payloads[0])

    bodies = [json.loads(report["body"]) for report in reports]

    # The epoch is stable across the restart; the count advances with it.
    assert [body["supervised"] for body in bodies] == [True, True]
    assert [body["supervisor_epoch"] for body in bodies] == [
        "e" * 32,
        "e" * 32,
    ]
    assert [body["supervisor_restart_count"] for body in bodies] == [0, 1]


# =====================================================================
# 4. Injection rejection, asserted on the serialised response body
# =====================================================================


@WINDOWS_ONLY
def test_a_poisoned_supervisor_environment_never_reaches_the_response_body(
    tmp_path: Path,
) -> None:
    """The threat model the validation exists for.

    A supervisor-launched child always receives a well-formed epoch, because
    the supervisor overwrites both variables. The exposure is a child started
    by anything else - an operator, a script, another tool - carrying a
    hostile value in its environment into a field that is serialised
    verbatim into an HTTP response.
    """

    import os

    script = _write_child(
        tmp_path,
        _CHILD_REPORTS_HEALTH,
        "atlas_poisoned_child.py",
    )

    poison = '"><script>alert(1)</script>'

    environment = dict(os.environ)
    environment["ATLAS_SUPERVISOR_EPOCH"] = poison
    environment["ATLAS_SUPERVISOR_RESTART_COUNT"] = "; DROP TABLE positions"

    process = subprocess.Popen(
        [
            sys.executable,
            str(script),
            str(REPOSITORY_ROOT),
            str(tmp_path / "state"),
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=atlas_supervisor.CREATION_FLAGS,
    )

    try:
        payloads = _collect(process, "ATLAS_AUDIT_HEALTH ")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=30)

    assert payloads, "child produced no /api/health payload"

    body_text = payloads[0]["body"]
    body = json.loads(body_text)

    assert body["supervised"] is False
    assert body["supervisor_epoch"] is None
    assert body["supervisor_restart_count"] is None

    # Asserted against the serialised body, not the parsed dict: the point is
    # that nothing hostile is transmitted, in any encoding.
    assert "script" not in body_text
    assert "DROP TABLE" not in body_text
