"""Thin read-only FastAPI router for the lightweight observability panel.

Security posture
----------------
This router is LOCALHOST-ONLY until real authentication exists. ``web_app``'s
``/login`` is still a stub redirect, so there is no authenticated identity to
authorise against. Every route here therefore refuses any request whose peer
address is not a loopback address or whose Host header does not name a
loopback host (DNS-rebinding defence), and ``web_app`` binds ``127.0.0.1``. Do
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
from urllib.parse import urlsplit

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

# Host header names the operator surface answers to. A loopback peer address
# alone does not prove a loopback client: under DNS rebinding a hostile web
# page resolves its own name to 127.0.0.1, so the victim's browser connects
# from a loopback address while sending ``Host: attacker.example``. The Host
# header is what still carries the page's origin, so it is checked too.
# Hostnames are compared case-insensitively; IPv6 must be bracketed, as the
# Host header grammar requires. Any port is accepted, because the hostname is
# what defeats rebinding and a local port-forward legitimately changes the port.
LOOPBACK_HOST_HEADER_NAMES = frozenset(
    {
        "127.0.0.1",
        "localhost",
        "[::1]",
    }
)

# starlette's TestClient sends ``Host: testserver`` from the in-process
# ``testclient`` peer. That pair is accepted only together, and only as the
# exact single header value ``testserver`` (no port): "testserver" is
# never a loopback Host name for a network peer, and "testclient" can only
# come from the in-process ASGI transport, never from a socket.
IN_PROCESS_TEST_PEER = "testclient"
IN_PROCESS_TEST_HOST_HEADER = "testserver"


def _host_header_name(request: Request) -> str | None:
    """Return the lower-cased hostname of the single Host header, or None.

    None - and therefore a refusal - covers a missing Host header, repeated
    Host headers, an empty or malformed value, and any port that is not a
    plain decimal number in 1..65535. A client that sends no Host header at
    all (HTTP/1.0, a raw socket) is refused: fail closed.
    """

    values = request.headers.getlist("host")

    if len(values) != 1:
        return None

    raw = values[0].lower()

    if raw.startswith("["):
        end = raw.find("]")

        if end == -1:
            return None

        name, rest = raw[: end + 1], raw[end + 1 :]
    else:
        name, separator, port = raw.partition(":")
        rest = separator + port

    if rest:
        port = rest[1:]

        if not (
            rest.startswith(":")
            and port.isascii()
            and port.isdigit()
            and len(port) <= 5
            and 1 <= int(port) <= 65535
        ):
            return None

    return name or None


def is_loopback_request(request: Request) -> bool:
    """Return True for a loopback peer that addressed a loopback Host name.

    This is the single loopback predicate for the whole web surface:
    ``web_app`` imports it to guard its own runtime endpoints, the HTML
    pages and the vendored ``/assets`` route, so that every route refuses
    the same set of requests rather than drifting apart behind separate
    implementations.

    Both conditions are required. The peer address must be loopback, and
    the Host header must name ``127.0.0.1``, ``localhost`` or ``[::1]``
    (optionally with a port); the latter is what refuses a DNS-rebinding
    request, which arrives from a loopback peer under a foreign Host name.
    """

    client = request.client

    if client is None:
        return False

    peer = (client.host or "").strip().lower()

    if not (peer.startswith("127.") or peer in LOOPBACK_HOSTS):
        return False

    host_name = _host_header_name(request)

    if host_name in LOOPBACK_HOST_HEADER_NAMES:
        return True

    return peer == IN_PROCESS_TEST_PEER and request.headers.getlist(
        "host"
    ) == [IN_PROCESS_TEST_HOST_HEADER]


def _in_process_test_request(request: Request) -> bool:
    """Return True only for the in-process TestClient peer+Host pair.

    Factored out of ``is_loopback_request`` so ``is_same_origin_request``
    below can grant the identical narrow carve-out for the Origin header
    without duplicating the peer/Host comparison.
    """

    client = request.client
    peer = (client.host if client is not None else "") or ""

    return peer.strip().lower() == IN_PROCESS_TEST_PEER and request.headers.getlist(
        "host"
    ) == [IN_PROCESS_TEST_HOST_HEADER]


def _origin_header_name(request: Request) -> str | None:
    """Return the lower-cased hostname of the single Origin header, or None.

    None covers a missing Origin header, a repeated one, an empty value, or
    one that does not parse as ``scheme://host[:port]`` with a hostname -
    the same fail-closed shape ``_host_header_name`` holds for Host. Any
    port is accepted and ignored, exactly as for the Host header: the
    hostname is what defeats a cross-origin request, and a local
    port-forward legitimately changes the port. An IPv6 hostname is
    re-bracketed so it compares equal to the bracketed form used in
    ``LOOPBACK_HOST_HEADER_NAMES``.
    """

    values = request.headers.getlist("origin")

    if len(values) != 1:
        return None

    raw = values[0].strip()

    if not raw:
        return None

    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
    except ValueError:
        return None

    if not hostname:
        return None

    hostname = hostname.lower()

    return f"[{hostname}]" if ":" in hostname else hostname


def is_same_origin_request(request: Request) -> bool:
    """Return True when a non-GET request's Origin header names a loopback host.

    Applies to state-changing requests (POST and beyond) the same
    ``LOOPBACK_HOST_HEADER_NAMES`` allowlist the Host header is already
    checked against. This closes the gap where a hostile page on another
    local port passes the Host check (the request still targets
    ``127.0.0.1``/``localhost``) - browser same-origin policy already stops
    it from reading the response, but this makes the server itself refuse
    the request rather than relying on that alone.

    A missing, repeated, empty or unparsable Origin header fails closed,
    matching the posture ``_host_header_name`` already holds for Host: a
    same-origin browser request always carries an Origin header on a
    non-GET request, so its absence means the request did not come from a
    browser applying same-origin rules, or is malformed.
    """

    origin_name = _origin_header_name(request)

    if origin_name in LOOPBACK_HOST_HEADER_NAMES:
        return True

    return origin_name == IN_PROCESS_TEST_HOST_HEADER and _in_process_test_request(
        request
    )


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
