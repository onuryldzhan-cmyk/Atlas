"""Thin read-only FastAPI router for the lightweight observability panel.

Security posture
----------------
This router is LOCALHOST-ONLY until real authentication exists. ``web_app``'s
``/login`` is still a stub redirect, so there is no authenticated identity to
authorise against. Every route here therefore refuses any request whose peer
address is not a loopback address, and ``web_app`` binds ``127.0.0.1``. Do
not expose these routes through a reverse proxy or bind a non-loopback
interface before authentication is implemented: the peer address seen here
would then be the proxy's, and the guard would no longer mean anything.

The router itself holds no logic: it imports and calls
``observability.panel_sources``. It performs no file I/O at import time, and
reads happen per request, never during application construction.
"""

from __future__ import annotations

import logging

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from observability import panel_sources

logger = logging.getLogger("AtlasAI.Observability.Panel")

# Loopback peer addresses. "testclient" is the in-process ASGI transport
# identity used by starlette's TestClient; it is never a network peer and
# cannot be presented by a remote client, since this value comes from the
# socket, not from a request header.
LOOPBACK_HOSTS = frozenset(
    {
        "127.0.0.1",
        "::1",
        "::ffff:127.0.0.1",
        "localhost",
        "testclient",
    }
)

NON_LOOPBACK_RESPONSE = {
    "status": "FORBIDDEN",
    "reason": "OBSERVABILITY_PANEL_IS_LOCALHOST_ONLY",
    "detail": (
        "The observability panel is restricted to loopback clients until "
        "authentication is implemented."
    ),
}


def is_loopback_request(request: Request) -> bool:
    """Return True when the request's peer address is a loopback address.

    This is the single loopback predicate for the whole web surface:
    ``web_app`` imports it to guard its own runtime endpoints
    (``/api/health``, ``/api/analysis``) so that both the panel routes and
    the runtime routes refuse the same set of peers, rather than drifting
    apart behind two separate implementations.
    """

    client = request.client

    if client is None:
        return False

    host = (client.host or "").strip().lower()

    if host.startswith("127."):
        return True

    return host in LOOPBACK_HOSTS


def _respond(payload: dict[str, Any]) -> JSONResponse:
    """Fail closed: an unavailable source is a 503, never a fabricated 200."""

    status_code = 200 if payload.get("available") is True else 503

    return JSONResponse(status_code=status_code, content=payload)


def build_observability_router(
    *,
    repository_root: Path | None = None,
) -> APIRouter:
    """Build the read-only observability router.

    ``repository_root`` exists for tests; production uses the module default
    resolved from this package's location. Nothing is read here — only when
    a request arrives.
    """

    router = APIRouter(prefix="/api/observability", tags=["observability"])

    @router.get("/test-results", response_class=JSONResponse)
    async def test_results(request: Request) -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)

        try:
            payload = panel_sources.read_test_results_panel(repository_root)
        except Exception as error:  # defensive: the panel must not 500 loudly
            logger.exception("Test results panel read failed")

            return JSONResponse(
                status_code=503,
                content={
                    "available": False,
                    "reason": "PANEL_READ_FAILED",
                    "error_type": type(error).__name__,
                },
            )

        return _respond(payload)

    @router.get("/governance", response_class=JSONResponse)
    async def governance(request: Request) -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)

        try:
            payload = panel_sources.read_governance_panel(repository_root)
        except Exception as error:  # defensive: the panel must not 500 loudly
            logger.exception("Governance panel read failed")

            return JSONResponse(
                status_code=503,
                content={
                    "available": False,
                    "reason": "PANEL_READ_FAILED",
                    "error_type": type(error).__name__,
                },
            )

        return _respond(payload)

    @router.get("/telemetry-summary", response_class=JSONResponse)
    async def telemetry_summary(request: Request) -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)

        try:
            payload = panel_sources.read_telemetry_summary(repository_root)
        except Exception as error:  # defensive: the panel must not 500 loudly
            logger.exception("Telemetry summary panel read failed")

            return JSONResponse(
                status_code=503,
                content={
                    "available": False,
                    "reason": "PANEL_READ_FAILED",
                    "error_type": type(error).__name__,
                },
            )

        return _respond(payload)

    return router
