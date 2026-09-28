"""
============================================================
PROJECT ATLAS AI — MERGED SERVICE ENTRY POINT v1.0
============================================================

Single-process composition entry point.

Atlas used to launch as two processes: ``main.py`` (the AtlasApplication
runtime) and ``uvicorn web_app:app`` (an operator web surface with no
runtime attached, so every runtime endpoint failed closed). This module
runs both in one process, with the live AtlasApplication injected into the
web surface through ``web_app.create_app``'s existing injection point.

Responsibilities
----------------
- Reuse ``main.AtlasProcess`` for the whole lifecycle, so the process keeps
  exactly one shutdown/exit-code authority.
- Build the FastAPI application against the *started* AtlasApplication.
- Serve it on loopback, off the main thread, so the main thread keeps
  ``AtlasProcess``'s signal handling.
- Stop the web surface before the runtime is torn down.

What this module deliberately does not do
-----------------------------------------
- It does not construct AtlasApplication. ``main.py`` remains the only
  module that does (tests/architecture/test_composition_root_is_unique.py
  enforces this), and ``core/application.py`` remains the only composition
  root for the services themselves.
- It does not import anything into ``web_app`` at module scope.
  ``web_app``'s module-level ``app`` stays unattached and import-safe;
  attachment happens here, per process start, against a running runtime.

Threading model
---------------
AtlasApplication is synchronous and owns its own daemon threads (MarketLoop
is one). uvicorn needs an asyncio loop. The two are composed by running
``uvicorn.Server.run()`` on a dedicated non-main thread:

- uvicorn's ``capture_signals`` is a no-op off the main thread (verified
  against uvicorn 0.52.1), so it cannot replace ``AtlasProcess``'s
  SIGINT / SIGTERM / SIGBREAK handlers. That matters on Windows, where
  Ctrl+C and Ctrl+Break are delivered to the main thread and
  ``AtlasProcess.run_forever()`` is the only thing allowed to observe them.
- Shutdown is therefore still driven by the main thread: it sets
  ``Server.should_exit`` and joins, rather than relying on a signal
  reaching uvicorn at all.

Security posture
----------------
The surface is loopback-only until authentication exists, and the guard is
``observability.panel_router.is_loopback_request``, which reads the socket
peer. ``proxy_headers`` is therefore disabled here: with uvicorn's default
(``proxy_headers=True``), ``X-Forwarded-For`` can rewrite the peer address
the guard reads, and the set of proxies trusted to do so is taken from the
``FORWARDED_ALLOW_IPS`` environment variable - so an environment variable
outside this repository could otherwise switch the guard off. See
``tests/test_merged_process_composition.py``.

============================================================
"""

from __future__ import annotations

import logging
import threading

from typing import Any

import uvicorn

from core.application import AtlasApplication
from main import AtlasProcess, configure_logging
from web_app import create_app


LOGGER_NAME = "AtlasAI.Service"

logger = logging.getLogger(LOGGER_NAME)


# The operator surface is loopback-only until authentication exists. Binding
# anything else would also invalidate the loopback guard, not just widen it.
WEB_HOST = "127.0.0.1"
WEB_PORT = 8000

# How long process startup waits for the server thread to report itself
# listening. Exceeding it is a startup failure, not a degraded start: a
# merged process that silently runs without its operator surface would hide
# the very condition the operator launched this entry point to watch.
WEB_STARTUP_TIMEOUT_SECONDS = 20.0

# How long shutdown waits for the server thread to finish its own graceful
# shutdown before giving up on it. Giving up is safe: the thread is a daemon
# and AtlasApplication.stop() - which flushes financial state - runs either
# way.
WEB_SHUTDOWN_TIMEOUT_SECONDS = 20.0


class AtlasWebServer:
    """
    Owns the in-process uvicorn server for an attached AtlasApplication.

    One instance serves one process lifetime: ``start`` is called once with
    the started application, ``stop`` once on the way down. ``stop`` is
    idempotent and safe to call when ``start`` never ran or failed.
    """

    def __init__(
        self,
        *,
        host: str = WEB_HOST,
        port: int = WEB_PORT,
        startup_timeout: float = WEB_STARTUP_TIMEOUT_SECONDS,
        shutdown_timeout: float = WEB_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        self.host = str(host)
        self.port = int(port)
        self.startup_timeout = float(startup_timeout)
        self.shutdown_timeout = float(shutdown_timeout)

        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None

    # --------------------------------------------------------
    # CONFIGURATION
    # --------------------------------------------------------

    def build_config(
        self,
        application: AtlasApplication,
    ) -> uvicorn.Config:
        """
        Build the server configuration for a started application.

        ``proxy_headers=False`` and ``forwarded_allow_ips=[]`` are the
        security-relevant settings here: together they guarantee that
        ``request.client`` is the real socket peer and can never be
        rewritten from a request header, which is what the loopback guard
        on every runtime endpoint depends on.
        """

        return uvicorn.Config(
            app=build_web_application(
                application
            ),
            host=self.host,
            port=self.port,
            # Never trust forwarding headers: the loopback guard reads the
            # peer address, so a rewritable peer address is a bypass.
            proxy_headers=False,
            # Belt and braces: even if the middleware were reinstated, no
            # peer is trusted to present X-Forwarded-For, and this ignores
            # FORWARDED_ALLOW_IPS from the environment.
            forwarded_allow_ips=[],
            # Atlas configures the root logger in main.configure_logging;
            # leaving uvicorn's own dictConfig out keeps one log format.
            log_config=None,
            reload=False,
        )

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    def start(
        self,
        application: AtlasApplication,
    ) -> None:
        """
        Serve the attached application on a dedicated thread.

        Raises:
            RuntimeError: the server thread did not report itself listening
                within the startup timeout, or stopped during startup.
        """

        if self.server is not None:
            raise RuntimeError(
                "Atlas web server is already started"
            )

        server = uvicorn.Server(
            self.build_config(
                application
            )
        )

        # uvicorn only installs signal handlers from the main thread, so
        # running the server here leaves AtlasProcess's
        # SIGINT/SIGTERM/SIGBREAK handlers in place - which is why the
        # thread is not optional.
        thread = threading.Thread(
            target=server.run,
            name="atlas-web-server",
            daemon=True,
        )

        self.server = server
        self.thread = thread

        logger.info(
            "Starting Atlas web surface on http://%s:%s",
            self.host,
            self.port,
        )

        thread.start()

        self._await_startup()

        logger.info(
            "Atlas web surface is listening | runtime attached"
        )

    def _await_startup(self) -> None:
        """
        Block until the server is listening, or fail closed.

        A bind failure inside uvicorn ends the server thread rather than
        raising into this one, so thread liveness is checked as well as the
        started flag: without that check a port conflict would leave Atlas
        running with no operator surface and no error.
        """

        server = self.server
        thread = self.thread

        if server is None or thread is None:
            raise RuntimeError(
                "Atlas web server start was not initiated"
            )

        waited = 0.0
        interval = 0.05

        while waited < self.startup_timeout:
            if server.started:
                return

            if not thread.is_alive():
                raise RuntimeError(
                    "Atlas web server thread stopped during startup "
                    f"(host={self.host} port={self.port}). The port is "
                    "most likely already in use."
                )

            thread.join(
                timeout=interval
            )

            waited += interval

        raise RuntimeError(
            "Atlas web server did not start within "
            f"{self.startup_timeout} seconds "
            f"(host={self.host} port={self.port})"
        )

    # --------------------------------------------------------
    # LIVENESS
    # --------------------------------------------------------

    def is_alive(self) -> bool:
        """
        Report whether a started web surface is still serving.

        ``_await_startup`` only covers the startup window. After it returns,
        nothing watches the server thread: ``AtlasProcess.run_forever()``
        watches ``application.running``, which a dead *web* thread never
        changes. Atlas would then keep running with no operator surface and
        no error - the merged process hiding exactly the condition the
        operator launched it to watch.

        False means the one condition that is genuinely wrong: a thread that
        came up and has since died. Every other state reports True, because
        every other state is either fine or not yet knowable:

        - never started (``thread is None``) - ``start()`` has not run, and
          a process that has not started its surface has not lost it.
        - assigned but not yet running - ``start()`` sets ``self.thread``
          before it calls ``thread.start()``, and a Thread reports
          ``is_alive() is False`` until it is started. Reading that window
          as a death would be wrong, so ``ident`` (None until the thread
          actually starts, and never cleared afterwards) separates "has not
          begun" from "has ended". Today the composition hook runs to
          completion before ``run_forever()`` polls, so nothing observes the
          window - this does not depend on that staying true.
        - already stopping or stopped - ``stop()`` clears ``server`` and
          ``thread`` *before* it joins, so a graceful shutdown never reads
          as an unexpected death on its way down.
        """

        thread = self.thread

        if thread is None:
            return True

        if thread.ident is None:
            return True

        return thread.is_alive()

    # --------------------------------------------------------
    # STOP
    # --------------------------------------------------------

    def stop(self) -> None:
        """
        Ask the server to shut down gracefully and wait for its thread.

        Never raises: this runs on the shutdown path, ahead of
        AtlasApplication.stop(), and must not be able to prevent it.
        """

        server = self.server
        thread = self.thread

        self.server = None
        self.thread = None

        if server is None:
            return

        logger.info(
            "Stopping Atlas web surface"
        )

        # should_exit is what uvicorn's own signal handler sets; setting it
        # directly is the same graceful path without needing a signal to
        # reach the server thread.
        server.should_exit = True

        if thread is None:
            return

        thread.join(
            timeout=self.shutdown_timeout,
        )

        if thread.is_alive():
            logger.warning(
                "Atlas web surface did not stop within %s seconds; "
                "continuing with runtime shutdown",
                self.shutdown_timeout,
            )

            return

        logger.info(
            "Atlas web surface stopped"
        )


# ============================================================
# WEB APPLICATION COMPOSITION
# ============================================================


def build_web_application(
    application: AtlasApplication,
) -> Any:
    """
    Attach a started AtlasApplication to a fresh FastAPI application.

    This is the whole point of the merge: ``web_app.create_app`` has always
    accepted an injected runtime, and until now nothing ever passed one, so
    every runtime endpoint answered "RUNTIME_NOT_ATTACHED".
    """

    return create_app(
        runtime=application,
        price_provider=application.market_feed.price,
    )


# ============================================================
# PUBLIC MAIN
# ============================================================


def build_process(
    *,
    server: AtlasWebServer | None = None,
) -> AtlasProcess:
    """
    Build the merged process controller.

    The lifecycle authority stays ``AtlasProcess``; this only supplies the
    web surface as a subordinate component of it.
    """

    web_server = (
        server
        if server is not None
        else AtlasWebServer()
    )

    # The started application, kept so the panel can be restarted against
    # the same runtime (registry v5.15: panel and trading decoupled).
    started: dict[str, AtlasApplication] = {}

    def start(application: AtlasApplication) -> None:
        started["application"] = application
        web_server.start(application)

    def restart() -> None:
        application = started.get("application")

        if application is None:
            raise RuntimeError("no started application to attach the panel to")

        web_server.stop()
        web_server.start(application)

    return AtlasProcess(
        on_started=start,
        on_stopping=web_server.stop,
        is_subordinate_alive=web_server.is_alive,
        restart_subordinate=restart,
    )


def main() -> int:
    """
    Atlas merged-process command-line entry point.
    """

    configure_logging()

    print()
    print("=" * 64)
    print("PROJECT ATLAS AI")
    print("Institutional AI Investment Platform")
    print(f"Operator surface: http://{WEB_HOST}:{WEB_PORT} (loopback only)")
    print("=" * 64)
    print()

    return build_process().execute()


# ============================================================
# SCRIPT ENTRY
# ============================================================


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
