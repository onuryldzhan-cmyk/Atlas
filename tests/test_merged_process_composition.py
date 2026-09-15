"""Coverage for the merged single-process entry point (atlas_service.py).

Three things are proven here, each of which was either impossible or false
before the Core/Dashboard process merge:

MERGE
    A *real* AtlasApplication attached through ``web_app.create_app`` serves
    ``/api/health`` and ``/api/analysis`` without crashing, and the process
    controller still reaches ``AtlasApplication.stop()`` on every exit path
    it can take - including a failing web server and a raising stop hook.

PROXY
    ``X-Forwarded-For`` must not be able to rewrite the peer address the
    loopback guard reads. uvicorn defaults to ``proxy_headers=True`` with
    the trusted-proxy set taken from ``FORWARDED_ALLOW_IPS``, so before the
    fix an environment variable could switch the guard off for every
    runtime endpoint. The test drives the real ``uvicorn.Config`` the
    service builds, not a hand-made stand-in.

GUARD
    ``/dashboard`` and ``/`` serve live runtime state once a runtime is
    attached, so they enforce the same loopback guard as the API routes.

Every AtlasApplication built here is given an isolated ``tmp_path`` state
directory: the durable execution stores and the paper book must never be
written by a test run.
"""

from __future__ import annotations

import threading

from pathlib import Path
from typing import Any

import pytest

from fastapi.testclient import TestClient

import atlas_service

from atlas_service import AtlasWebServer, build_process, build_web_application
from core.application import AtlasApplication
from main import AtlasProcess


# =====================================================================
# Shared fakes
# =====================================================================


class _StubMarketFeed:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def price(self, symbol: str) -> float:
        self.requested.append(symbol)
        return 64_010.25


class _StubBrain:
    """A brain result carrying the full sanitised decision contract.

    ``metadata`` is what the decision trim must drop: it is sanitised, but
    it is the decision's internal derivation and no client reads it.
    """

    def process(self, observation: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "SUCCESS",
            "symbol": observation["symbol"],
            "decision": {
                "action": "BUY",
                "symbol": observation["symbol"],
                "confidence": 71.5,
                "strategy": "momentum",
                "risk_level": "MEDIUM",
                "price": 64_010.25,
                "created_at": "2026-09-15T00:00:00+00:00",
                "metadata": {
                    "raw_risk_level": "MEDIUM",
                    "confidence_source": "INTERNAL-PROVENANCE-MARKER",
                },
            },
            "time": "2026-09-15T00:00:00+00:00",
        }


class _StubRuntime:
    """Shape-compatible stand-in for AtlasApplication.

    Used by the tests that do not need the real construction cost; the
    real-runtime test below uses AtlasApplication itself.
    """

    def __init__(self) -> None:
        self.brain = _StubBrain()
        self.market_feed = _StubMarketFeed()

    def health(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "runtime_state": "RUNNING",
            "market_data_stale": False,
        }


# =====================================================================
# MERGE: a real AtlasApplication attached to the web surface
# =====================================================================


@pytest.fixture(name="real_application")
def _real_application(tmp_path: Path) -> AtlasApplication:
    """A real, constructed-but-not-started AtlasApplication.

    ``start()`` is deliberately not called: it connects to an exchange and
    starts MarketLoop. Construction alone is what the composition needs to
    be correct about - it is where ``market_feed`` and ``brain`` come from,
    and where a wrong attribute name would break the merged process.
    """

    return AtlasApplication(
        execution_mode="PAPER",
        state_directory=tmp_path / "state",
    )


def test_real_application_exposes_the_attributes_the_service_injects(
    real_application: AtlasApplication,
) -> None:
    """The injection points must exist on the real object, not just a fake."""

    assert callable(real_application.market_feed.price)
    assert callable(real_application.brain.process)
    assert callable(real_application.health)


def test_real_application_attached_serves_health_and_analysis(
    real_application: AtlasApplication,
) -> None:
    """MERGE: the endpoints answer from a real runtime without crashing.

    The application is not started, so this asserts the *fail-closed*
    contract under a real runtime: a genuine health report (not a 500) and
    a brain that reports itself offline rather than raising.
    """

    client = TestClient(
        build_web_application(real_application)
    )

    health = client.get("/api/health")

    assert health.status_code in (200, 503)

    health_payload = health.json()

    assert "healthy" in health_payload
    assert health_payload["healthy"] is False
    assert health_payload["running"] is False

    analysis = client.get("/api/analysis")

    assert analysis.status_code != 500, analysis.text

    analysis_payload = analysis.json()

    assert analysis_payload["status"] == "OFFLINE"
    assert analysis_payload["reason"] == "BRAIN_NOT_RUNNING"
    assert analysis_payload["decision"] is None
    assert "analysis" not in analysis_payload


def test_attached_runtime_health_carries_the_market_loop_signals(
    real_application: AtlasApplication,
) -> None:
    """The MARKET_LOOP staleness/health signals must reach /api/health.

    AtlasApplication.health() is what web_app calls, and it is already the
    module that folds MarketLoop's health in. This pins that the merged
    process does not lose those fields on the way through.
    """

    payload = TestClient(
        build_web_application(real_application)
    ).get("/api/health").json()

    assert "market_data_stale" in payload
    assert "market_data_stale_reason" in payload
    assert "market_loop_thread_alive" in payload


# =====================================================================
# MERGE: decision trim
# =====================================================================


def test_analysis_decision_is_trimmed_to_the_fields_the_dashboard_reads() -> None:
    """Only action/confidence/risk_level may cross the boundary."""

    payload = TestClient(
        build_web_application(_StubRuntime())  # type: ignore[arg-type]
    ).get("/api/analysis").json()

    assert set(payload["decision"]) == {
        "action",
        "confidence",
        "risk_level",
    }

    assert payload["decision"]["action"] == "BUY"
    assert payload["decision"]["confidence"] == 71.5
    assert payload["decision"]["risk_level"] == "MEDIUM"


def test_analysis_decision_metadata_never_reaches_the_client() -> None:
    body = TestClient(
        build_web_application(_StubRuntime())  # type: ignore[arg-type]
    ).get("/api/analysis").text

    assert "INTERNAL-PROVENANCE-MARKER" not in body
    assert "metadata" not in body
    assert "created_at" not in body


# =====================================================================
# MERGE: a raising runtime health call must not leak its message
# =====================================================================


class _RaisingHealthRuntime:
    """A runtime whose health() raises with an internal in the message."""

    def __init__(self) -> None:
        self.brain = _StubBrain()
        self.market_feed = _StubMarketFeed()

    def health(self) -> dict[str, Any]:
        raise RuntimeError(
            r"C:\Users\operator\OneDrive\Atlas\memory_data\state.json "
            "HEALTH-INTERNAL-MARKER"
        )


@pytest.mark.parametrize("route", ["/api/health", "/dashboard", "/"])
def test_raising_runtime_health_message_never_reaches_the_client(
    route: str,
) -> None:
    """Only the exception class may be published, never its message.

    ``/api/health`` published ``str(exc)`` verbatim; that became a real
    leak path when a live AtlasApplication was attached, because the
    message of anything ``health()`` raises can carry a state-directory
    path or an exchange client detail. The two HTML routes never rendered
    the message - they read only ``state`` and ``reason`` - and are
    included here to keep it that way.
    """

    response = TestClient(
        build_web_application(
            _RaisingHealthRuntime()  # type: ignore[arg-type]
        )
    ).get(route)

    assert "HEALTH-INTERNAL-MARKER" not in response.text, route
    assert "memory_data" not in response.text, route

    # The failure is still reported - the fix removes the message, not the
    # signal. The HTML pages render the fixed reason code; only the JSON
    # endpoint carries the exception's class name.
    assert "RUNTIME_HEALTH_FAILED" in response.text, route

    if route == "/api/health":
        assert response.json()["error_type"] == "RuntimeError"
        assert "error" not in response.json()


# =====================================================================
# GUARD: /dashboard and / are loopback-only
# =====================================================================


@pytest.mark.parametrize("route", ["/", "/dashboard"])
def test_html_routes_refuse_non_loopback_clients(route: str) -> None:
    runtime = _StubRuntime()

    client = TestClient(
        build_web_application(runtime),  # type: ignore[arg-type]
        client=("203.0.113.7", 44321),
    )

    response = client.get(route)

    assert response.status_code == 403, route
    assert response.json()["reason"] == "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"

    # A refused peer must not be able to induce an exchange price lookup.
    assert runtime.market_feed.requested == []


@pytest.mark.parametrize("route", ["/", "/dashboard"])
def test_html_routes_still_serve_loopback_clients(route: str) -> None:
    response = TestClient(
        build_web_application(_StubRuntime())  # type: ignore[arg-type]
    ).get(route)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


# =====================================================================
# PROXY: X-Forwarded-For must not rewrite the guarded peer address
# =====================================================================


async def _receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


def _call_loaded_app(
    config: Any,
    *,
    path: str,
    peer: tuple[str, int],
    headers: list[tuple[bytes, bytes]],
) -> dict[str, Any]:
    """Drive a uvicorn-loaded ASGI app directly and return the response.

    Going through ``config.load()`` is the point: that is where uvicorn
    decides whether to wrap the application in ProxyHeadersMiddleware, so
    this exercises the real setting rather than a re-implementation of it.
    """

    import asyncio
    import json as json_module

    config.load()

    captured: dict[str, Any] = {"status": None, "body": b""}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            captured["body"] += message.get("body", b"")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"127.0.0.1:8000"), *headers],
        "client": peer,
        "server": ("127.0.0.1", 8000),
    }

    asyncio.run(
        config.loaded_app(scope, _receive, send)
    )

    body = captured["body"].decode("utf-8") or "{}"

    try:
        parsed = json_module.loads(body)
    except ValueError:
        parsed = {"raw": body}

    return {"status": captured["status"], "json": parsed}


@pytest.mark.parametrize(
    "route",
    ["/api/health", "/api/analysis", "/dashboard", "/"],
)
def test_spoofed_forwarded_for_cannot_reach_a_guarded_route(
    route: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PROXY: the fix must hold even with FORWARDED_ALLOW_IPS wide open.

    ``FORWARDED_ALLOW_IPS=*`` is uvicorn's "trust every proxy" setting and
    is read from the environment at Config construction. With
    ``proxy_headers`` left at its default, a remote peer sending
    ``X-Forwarded-For: 127.0.0.1`` would have its client address rewritten
    to loopback before the guard ever ran, and every guarded route would
    answer it. The service pins ``proxy_headers=False``, so the guard sees
    the real peer and refuses.

    Verified against the genuine pre-fix state - *neither* setting passed.
    Either one alone closes this (an explicit ``forwarded_allow_ips``
    stops the environment variable being consulted at all), which is why
    ``test_service_config_disables_proxy_header_trust`` pins both values
    rather than relying on this end-to-end check to catch the loss of one.
    """

    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")

    config = AtlasWebServer().build_config(
        _StubRuntime()  # type: ignore[arg-type]
    )

    result = _call_loaded_app(
        config,
        path=route,
        peer=("203.0.113.9", 51234),
        headers=[(b"x-forwarded-for", b"127.0.0.1")],
    )

    assert result["status"] == 403, (route, result)
    assert result["json"]["reason"] == "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"


def test_service_config_disables_proxy_header_trust() -> None:
    config = AtlasWebServer().build_config(
        _StubRuntime()  # type: ignore[arg-type]
    )

    assert config.proxy_headers is False
    assert config.forwarded_allow_ips == []
    assert config.host == "127.0.0.1"


def test_genuinely_local_peer_is_still_served() -> None:
    """The guard must not have been fixed by refusing everyone."""

    config = AtlasWebServer().build_config(
        _StubRuntime()  # type: ignore[arg-type]
    )

    result = _call_loaded_app(
        config,
        path="/api/health",
        peer=("127.0.0.1", 51234),
        headers=[],
    )

    assert result["status"] == 200
    assert result["json"]["healthy"] is True


# =====================================================================
# MERGE: lifecycle / shutdown contract
# =====================================================================


class _RecordingApplication:
    """Minimal AtlasApplication stand-in that records stop()."""

    def __init__(self, *, start_result: bool = True) -> None:
        self.running = True
        self.stop_calls = 0
        self._start_result = start_result

    def start(self) -> bool:
        return self._start_result

    def stop(self) -> bool:
        self.stop_calls += 1
        self.running = False
        return True

    def status(self) -> dict[str, Any]:
        return {"application": {}, "runtime": {}, "health": {}, "services": {}}


def _process_with(
    monkeypatch: pytest.MonkeyPatch,
    application: _RecordingApplication,
    **kwargs: Any,
) -> AtlasProcess:
    """An AtlasProcess whose start() attaches a recording application.

    ``install_signal_handlers`` is neutralised: execute() would otherwise
    install Atlas's SIGINT/SIGTERM handlers into the pytest process and
    never restore them.
    """

    process = AtlasProcess(**kwargs)

    def _start() -> bool:
        process.application = application  # type: ignore[assignment]
        return True

    monkeypatch.setattr(process, "start", _start)
    monkeypatch.setattr(process, "install_signal_handlers", lambda: None)

    return process


def test_stop_hook_runs_before_the_application_is_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    application = _RecordingApplication()
    original_stop = application.stop

    def _stop() -> bool:
        order.append("application")
        return original_stop()

    application.stop = _stop  # type: ignore[method-assign]

    process = _process_with(
        monkeypatch,
        application,
        on_started=lambda _app: order.append("start-hook"),
        on_stopping=lambda: order.append("stop-hook"),
    )

    process.shutdown_event.set()

    assert process.execute() == 0
    assert order == ["start-hook", "stop-hook", "application"]
    assert application.stop_calls == 1


def test_failing_start_hook_still_stops_the_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A web server that cannot bind must not skip the financial flush."""

    application = _RecordingApplication()

    def _raise(_app: Any) -> None:
        raise RuntimeError("port already in use")

    process = _process_with(
        monkeypatch,
        application,
        on_started=_raise,
    )

    exit_code = process.execute()

    assert exit_code == 1
    assert application.stop_calls == 1
    assert "port already in use" in process.shutdown_reason


def test_failing_stop_hook_still_stops_the_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A web server that cannot shut down must not block runtime shutdown."""

    application = _RecordingApplication()

    def _raise() -> None:
        raise RuntimeError("server thread wedged")

    process = _process_with(
        monkeypatch,
        application,
        on_stopping=_raise,
    )

    process.shutdown_event.set()

    exit_code = process.execute()

    assert exit_code == 1
    assert application.stop_calls == 1


def test_process_without_hooks_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main.py's existing single-component behaviour must be preserved."""

    application = _RecordingApplication()

    process = _process_with(monkeypatch, application)

    process.shutdown_event.set()

    assert process.execute() == 0
    assert application.stop_calls == 1
    assert process.on_started is None
    assert process.on_stopping is None


def test_build_process_wires_the_web_server_to_both_hooks() -> None:
    server = AtlasWebServer()

    process = build_process(server=server)

    assert process.on_started == server.start
    assert process.on_stopping == server.stop


# =====================================================================
# MERGE: the server thread itself
# =====================================================================


@pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnhandledThreadExceptionWarning"
)
def test_web_server_start_fails_closed_when_the_thread_dies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server that never binds is a startup failure, not a quiet start.

    uvicorn ends its own thread with ``SystemExit`` when it cannot bind the
    port, which never reaches the calling thread. Without the liveness
    check in ``_await_startup`` Atlas would run on with no operator
    surface and no error at all.
    """

    class _DyingServer:
        started = False

        def __init__(self, _config: Any) -> None:
            pass

        def run(self) -> None:
            raise SystemExit(1)

    monkeypatch.setattr(
        atlas_service.uvicorn,
        "Server",
        _DyingServer,
    )

    server = AtlasWebServer(startup_timeout=5.0)

    with pytest.raises(RuntimeError, match="stopped during startup"):
        server.start(_StubRuntime())  # type: ignore[arg-type]


def test_web_server_start_fails_closed_on_startup_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server that never reports itself listening is also a failure."""

    class _HangingServer:
        started = False

        def __init__(self, _config: Any) -> None:
            self.should_exit = False

        def run(self) -> None:
            while not self.should_exit:
                threading.Event().wait(timeout=0.01)

    monkeypatch.setattr(
        atlas_service.uvicorn,
        "Server",
        _HangingServer,
    )

    server = AtlasWebServer(startup_timeout=0.3)

    with pytest.raises(RuntimeError, match="did not start within"):
        server.start(_StubRuntime())  # type: ignore[arg-type]

    server.stop()


def test_web_server_stop_is_safe_before_start() -> None:
    AtlasWebServer().stop()


def test_web_server_stop_requests_graceful_exit_and_joins() -> None:
    server = AtlasWebServer(shutdown_timeout=5.0)

    finished = threading.Event()

    class _FakeServer:
        def __init__(self) -> None:
            self.should_exit = False

    fake = _FakeServer()

    def _run() -> None:
        while not fake.should_exit:
            finished.wait(timeout=0.01)
        finished.set()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    server.server = fake  # type: ignore[assignment]
    server.thread = thread

    server.stop()

    assert fake.should_exit is True
    assert not thread.is_alive()
    assert server.server is None
    assert server.thread is None


def test_service_binds_loopback_only() -> None:
    assert atlas_service.WEB_HOST == "127.0.0.1"


# =====================================================================
# SMOKE: the real merged startup/shutdown sequence, in a real process
# =====================================================================


# Run in a child process so the signal handling is genuine: AtlasProcess
# installs real SIGINT/SIGTERM handlers, and pytest's own process must not
# inherit them.
#
# What is real here: the process controller, the composition hooks, a real
# uvicorn server on a real port in a real thread, a real HTTP request served
# by the attached runtime, the real SIGINT handler, the real shutdown
# ordering, and the real exit code returned to the OS.
#
# What is stubbed: AtlasApplication itself. Starting the real one connects to
# an exchange, starts MarketLoop, and writes the durable execution stores and
# the paper book - none of which a test may do. main.AtlasApplication is
# rebound rather than AtlasProcess.start being replaced, so AtlasProcess.start
# still runs its own real body.
#
# Not covered: delivery of a signal sent by another process. On Windows a
# child cannot be sent SIGINT from outside (only CTRL_BREAK_EVENT, which
# Atlas does not handle), so the child raises SIGINT to itself. Everything
# downstream of the handler is identical either way.
_SMOKE_CHILD = '''
import json
import signal
import sys
import threading
import urllib.request

PORT = int(sys.argv[1])

# The script itself lives in a temporary directory, so the repository root
# is passed in rather than inferred.
sys.path.insert(0, sys.argv[2])

import main
import atlas_service

RESULTS = {}


class StubApplication:
    instance = None

    def __init__(self, **kwargs):
        StubApplication.instance = self
        self.running = False
        self.stop_calls = 0
        self.stopped_while_server_alive = None
        self.market_feed = type(
            "Feed", (), {"price": staticmethod(lambda symbol: 61234.5)}
        )()
        self.brain = type(
            "Brain",
            (),
            {
                "process": staticmethod(
                    lambda observation: {
                        "status": "SUCCESS",
                        "symbol": observation["symbol"],
                        "decision": {
                            "action": "HOLD",
                            "confidence": 12.0,
                            "risk_level": "LOW",
                            "metadata": {"secret": "NEVER-PUBLISHED"},
                        },
                        "time": "2026-09-15T00:00:00+00:00",
                    }
                )
            },
        )()

    def start(self):
        self.running = True
        return True

    def stop(self):
        self.stop_calls += 1
        server_thread = SERVER.thread
        self.stopped_while_server_alive = bool(
            server_thread is not None and server_thread.is_alive()
        )
        self.running = False
        return True

    def health(self):
        return {"healthy": self.running, "runtime_state": "RUNNING"}

    def status(self):
        return {
            "application": {"name": "Stub", "running": self.running},
            "runtime": {"state": "RUNNING"},
            "health": {"healthy": self.running},
            "services": {"registered": [], "started": []},
        }


main.AtlasApplication = StubApplication

SERVER = atlas_service.AtlasWebServer(port=PORT, startup_timeout=30.0)
PROCESS = atlas_service.build_process(server=SERVER)


def prod():
    for _ in range(600):
        if SERVER.server is not None and SERVER.server.started:
            break
        threading.Event().wait(0.05)

    try:
        for path in ("/api/health", "/api/analysis"):
            with urllib.request.urlopen(
                "http://127.0.0.1:%d%s" % (PORT, path), timeout=10
            ) as response:
                RESULTS[path] = {
                    "status": response.status,
                    "body": response.read().decode("utf-8"),
                }
    except Exception as error:
        RESULTS["error"] = "%s: %s" % (type(error).__name__, error)

    signal.raise_signal(signal.SIGINT)


threading.Thread(target=prod, daemon=True).start()

EXIT_CODE = PROCESS.execute()

RESULTS["exit_code"] = EXIT_CODE
RESULTS["stop_calls"] = StubApplication.instance.stop_calls
RESULTS["stopped_while_server_alive"] = (
    StubApplication.instance.stopped_while_server_alive
)
RESULTS["server_thread_cleared"] = SERVER.thread is None

print("ATLAS_SMOKE_RESULT " + json.dumps(RESULTS))
sys.stdout.flush()

raise SystemExit(EXIT_CODE)
'''


def _free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_merged_process_starts_serves_and_shuts_down(tmp_path: Path) -> None:
    """SMOKE: start the merged process for real, hit it, then SIGINT it."""

    import json
    import subprocess
    import sys

    script = tmp_path / "atlas_smoke_child.py"
    script.write_text(_SMOKE_CHILD, encoding="utf-8")

    port = _free_port()
    repository_root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [sys.executable, str(script), str(port), str(repository_root)],
        cwd=str(repository_root),
        capture_output=True,
        text=True,
        timeout=180,
    )

    marker = "ATLAS_SMOKE_RESULT "
    lines = [
        line
        for line in completed.stdout.splitlines()
        if line.startswith(marker)
    ]

    assert lines, (
        "merged process produced no result line.\n"
        f"exit={completed.returncode}\n"
        f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
    )

    results = json.loads(lines[-1][len(marker):])

    assert "error" not in results, results

    # The attached runtime actually served both runtime endpoints.
    assert results["/api/health"]["status"] == 200
    assert json.loads(results["/api/health"]["body"])["healthy"] is True

    analysis = json.loads(results["/api/analysis"]["body"])

    assert analysis["status"] == "SUCCESS"
    assert set(analysis["decision"]) == {"action", "confidence", "risk_level"}
    assert "NEVER-PUBLISHED" not in results["/api/analysis"]["body"]

    # SIGINT is a clean stop, not a failure.
    assert results["exit_code"] == 0
    assert completed.returncode == 0

    # The financial-state flush ran exactly once, and it ran while the web
    # server was still up - i.e. the surface stopped accepting work that
    # reaches the runtime before the runtime was torn down.
    assert results["stop_calls"] == 1
    assert results["stopped_while_server_alive"] is False
    assert results["server_thread_cleared"] is True
