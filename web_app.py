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


logger = logging.getLogger("AtlasAI.WebApp")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"

PriceProvider = Callable[[str], float]


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
                    provider("BTCTRY")
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
    async def api_health() -> JSONResponse:
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
        symbol: str = "BTCUSDT",
    ) -> JSONResponse:
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

        try:
            result = process(
                observation
            )
        except Exception as exc:
            logger.exception(
                "Web analysis request failed"
            )

            return JSONResponse(
                status_code=500,
                content={
                    "status": "ERROR",
                    "symbol": symbol.upper(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
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
            content=result,
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
