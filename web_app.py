"""
ATLAS WEB APPLICATION v2.0

Safe FastAPI dashboard entry point.

Design principles
-----------------
- Importing this module never starts Atlas runtime services.
- Importing this module never connects to an exchange.
- Importing this module never creates orders or paper trades.
- Runtime dependencies are injected explicitly.
- Missing runtime dependencies fail closed.
- Uvicorn starts only when this file is executed directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.templating import Jinja2Templates

from observability.panel_router import (
    build_observability_router,
    is_loopback_request,
)


logger = logging.getLogger("AtlasAI.WebApp")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"

PriceProvider = Callable[[str], float]

# The symbol the dashboard observes. Kept identical to /api/analysis's own
# default so the server-rendered price tile and the polled decision tile
# always describe the same instrument on the same venue (binance_global,
# which is what AtlasApplication defaults to).
DEFAULT_SYMBOL = "BTCUSDT"

# Keys of a brain ``process()`` result that may be exposed over HTTP.
#
# "analysis" is deliberately excluded. core/brain.py stores the intelligence
# engine's raw return value at analysis["result"] - a core.decision.Decision
# dataclass, which is not JSON serialisable - alongside unsanitised
# internals (world analysis output, brain session id, confidence
# explanation, phase-5 audit record). Only "decision" has passed through
# DecisionAdapter.convert / sanitize_sensitive_mapping, so only "decision"
# may cross this boundary.
#
# Free-form error strings ("error") are excluded for the same reason: the
# reason codes below are fixed, non-sensitive identifiers.
PUBLIC_ANALYSIS_KEYS = (
    "status",
    "symbol",
    "time",
    "decision",
    "reason",
)

NON_LOOPBACK_RESPONSE = {
    "status": "FORBIDDEN",
    "reason": "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY",
    "detail": (
        "Atlas runtime endpoints are restricted to loopback clients until "
        "authentication is implemented."
    ),
}


def _public_analysis_payload(
    result: dict[str, Any],
) -> dict[str, Any]:
    """
    Project a brain result onto the fields that are safe to publish.

    Only keys actually present in the result are emitted, so a brain that
    does not produce a field does not gain a fabricated null one.
    """

    return {
        key: result[key]
        for key in PUBLIC_ANALYSIS_KEYS
        if key in result
    }


def _safe_runtime_health(
    runtime: Any | None,
) -> dict[str, Any]:
    """
    Return lifecycle-aware runtime health without starting anything.
    """

    if runtime is None:
        return {
            "healthy": False,
            "state": "OFFLINE",
            "reason": "RUNTIME_NOT_ATTACHED",
        }

    for method_name in (
        "health",
        "status",
    ):
        method = getattr(
            runtime,
            method_name,
            None,
        )

        if not callable(method):
            continue

        try:
            result = method()
        except Exception as exc:
            logger.exception(
                "Runtime %s call failed",
                method_name,
            )

            return {
                "healthy": False,
                "state": "ERROR",
                "reason": "RUNTIME_HEALTH_FAILED",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

        if isinstance(result, dict):
            return result

        return {
            "healthy": False,
            "state": "DEGRADED",
            "reason": "INVALID_RUNTIME_HEALTH_RESULT",
            "result_type": type(result).__name__,
        }

    return {
        "healthy": False,
        "state": "DEGRADED",
        "reason": "RUNTIME_HEALTH_UNAVAILABLE",
    }


def _resolve_brain(
    runtime: Any | None,
) -> Any | None:
    """
    Resolve a brain service from an injected application/runtime object.
    """

    if runtime is None:
        return None

    brain = getattr(
        runtime,
        "brain",
        None,
    )

    if brain is not None:
        return brain

    application = getattr(
        runtime,
        "application",
        None,
    )

    if application is not None:
        return getattr(
            application,
            "brain",
            None,
        )

    return None


def create_app(
    *,
    runtime: Any | None = None,
    price_provider: PriceProvider | None = None,
) -> FastAPI:
    """
    Build the Atlas web application.

    No Atlas runtime service is constructed or started here. Production
    composition must inject a managed runtime explicitly.
    """

    application = FastAPI(
        title="Project Atlas AI",
        description=(
            "Lifecycle-safe Atlas monitoring and control interface"
        ),
        version="2.0",
    )

    templates = Jinja2Templates(
        directory=str(TEMPLATE_DIR),
    )

    application.state.atlas_runtime = runtime
    application.state.price_provider = price_provider

    # Read-only observability panels (test results artifact, GOV-DRIFT
    # status). Mounting only registers routes: no file is read here, so
    # create_app stays free of file I/O. Every read happens per request
    # inside observability.panel_sources.
    #
    # These routes are LOCALHOST-ONLY until authentication exists: /login
    # below is still a stub, and the router refuses non-loopback peers.
    application.include_router(
        build_observability_router(),
    )

    @application.get(
        "/",
        response_class=HTMLResponse,
    )
    async def root(
        request: Request,
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "runtime_state": _safe_runtime_health(
                    application.state.atlas_runtime
                ),
            },
        )

    @application.get(
        "/dashboard",
        response_class=HTMLResponse,
    )
    async def dashboard(
        request: Request,
    ) -> HTMLResponse:
        provider = application.state.price_provider
        price = 0.0
        price_status = "UNAVAILABLE"

        if callable(provider):
            try:
                price = float(
                    provider(DEFAULT_SYMBOL)
                )
                price_status = "AVAILABLE"
            except Exception as exc:
                logger.exception(
                    "Dashboard price provider failed"
                )
                price_status = "ERROR"

                logger.debug(
                    "Price provider error: %s",
                    exc,
                )

        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "symbol": DEFAULT_SYMBOL,
                "price": price,
                "price_status": price_status,
                "runtime_state": _safe_runtime_health(
                    application.state.atlas_runtime
                ),
            },
        )

    @application.get(
        "/api/health",
        response_class=JSONResponse,
    )
    async def api_health(
        request: Request,
    ) -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )

        health = _safe_runtime_health(
            application.state.atlas_runtime
        )

        status_code = (
            200
            if health.get("healthy") is True
            else 503
        )

        return JSONResponse(
            status_code=status_code,
            content=health,
        )

    @application.get(
        "/api/analysis",
        response_class=JSONResponse,
    )
    async def api_analysis(
        request: Request,
        symbol: str = DEFAULT_SYMBOL,
    ) -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )

        brain = _resolve_brain(
            application.state.atlas_runtime
        )

        if brain is None:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "OFFLINE",
                    "reason": "BRAIN_NOT_ATTACHED",
                    "symbol": symbol.upper(),
                },
            )

        process = getattr(
            brain,
            "process",
            None,
        )

        if not callable(process):
            return JSONResponse(
                status_code=503,
                content={
                    "status": "OFFLINE",
                    "reason": "BRAIN_PROCESS_UNAVAILABLE",
                    "symbol": symbol.upper(),
                },
            )

        observation = {
            "symbol": symbol.upper(),
            "source": "WEB_REQUEST",
        }

        # The response body is built inside this try/except on purpose.
        # JSONResponse serialises its content during construction, so a
        # non-serialisable brain field raises here rather than escaping the
        # handler as an unhandled 500 - which is exactly how a real runtime
        # used to break this endpoint.
        try:
            result = process(
                observation
            )

            if not isinstance(result, dict):
                return JSONResponse(
                    status_code=500,
                    content={
                        "status": "ERROR",
                        "reason": "INVALID_BRAIN_RESULT",
                        "result_type": type(result).__name__,
                    },
                )

            response_code = (
                200
                if result.get("status") == "SUCCESS"
                else 503
                if result.get("status") == "OFFLINE"
                else 200
            )

            return JSONResponse(
                status_code=response_code,
                content=_public_analysis_payload(
                    result
                ),
            )

        except Exception as exc:
            logger.exception(
                "Web analysis request failed"
            )

            # str(exc) stays in the log and never in the body. Moving the
            # response construction into this try widened what reaches
            # here - adapter and serialisation faults now land in this
            # branch - and an exception message from an exchange client,
            # a filesystem path or a third-party library is exactly the
            # unsanitised content the allowlist above exists to keep out.
            return JSONResponse(
                status_code=500,
                content={
                    "status": "ERROR",
                    "symbol": symbol.upper(),
                    "reason": "ANALYSIS_FAILED",
                    "error_type": type(exc).__name__,
                },
            )

    @application.post(
        "/login",
        response_class=RedirectResponse,
    )
    async def login() -> RedirectResponse:
        """
        Temporary dashboard redirect.

        Authentication must be implemented before external exposure.
        """

        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    logger.warning(
        "Starting Atlas web dashboard in observation-only mode. "
        "No Atlas runtime is attached."
    )

    uvicorn.run(
        "web_app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
