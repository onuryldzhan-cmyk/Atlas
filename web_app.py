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
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request, Response
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

# Keys of the sanitised decision that may be published.
#
# DecisionAdapter.convert produces the full execution-ready contract
# (action, symbol, confidence, strategy, risk_level, price, created_at,
# metadata). All of it has passed sanitisation, so none of it is unsafe -
# but the dashboard reads only action, confidence and risk_level, and
# "metadata" in particular carries the decision's internal derivation
# (raw risk level, confidence provenance, the shadow phase-5 proposal).
# Least exposure is the default: publish what the client consumes, not
# everything that happens to be safe to publish.
#
# This is the same allowlist-projection pattern as PUBLIC_ANALYSIS_KEYS
# above, applied one level down. It adds no new sanitisation of its own.
PUBLIC_DECISION_KEYS = (
    "action",
    "confidence",
    "risk_level",
)

# The 5 agents AgentFusion.evaluate() (ai/core/intelligence/agent_fusion.py)
# always attempts, in the order its AGENT_EVIDENCE_STATUS_KEYS dict declares
# them. Each name is included in exactly one of a normalized decision's
# metadata.agents (evaluated: {"action", "score"}) or
# metadata.unavailable_agents ({name: reason string}) per cycle - never
# both, never neither - so listing them here lets /api/signals report a
# fixed 5-row breakdown per symbol instead of a breakdown that silently
# shrinks whenever an agent is excluded.
SIGNAL_AGENT_NAMES = (
    "technical",
    "macro",
    "sentiment",
    "risk",
    "momentum",
)

# Fields of a per-agent evaluation (metadata.agents[name]) that may be
# published. Same least-exposure allowlist pattern as PUBLIC_DECISION_KEYS:
# AgentFusion currently only ever puts "action" and "score" here, but this
# is enforced rather than assumed, so an internal field added later does
# not cross this boundary silently.
PUBLIC_AGENT_KEYS = (
    "action",
    "score",
)

# Keys of a normalized MarketLoop signal (one entry of last_signals[symbol])
# that may be published directly, before the agents/metadata projection
# below is added under a separate "agents" key. Mirrors PUBLIC_DECISION_KEYS
# - action/confidence/risk_level only, never metadata's fusion internals,
# reasoning text or memory diagnostics.
PUBLIC_SIGNAL_KEYS = (
    "action",
    "confidence",
    "risk_level",
)

# Fields of a closed-position archive record (core/execution_portfolio_
# foundation.py ClosedPositionArchiveStore) that may be published per trade.
# The full record also carries position_id, cost_quote, entry_fees,
# average_entry_price, mark_price and version - internal financial
# accounting detail the trade-history panel does not need and should not
# expose, per the same least-exposure default used throughout this module.
PUBLIC_TRADE_KEYS = (
    "symbol",
    "gross_pnl",
    "opened_at",
    "closed_at",
)

# Trade history responses are capped to the N most recently closed
# positions. The archive is unbounded and append-only; a dashboard panel
# has no use for the full lifetime history on every 30s poll.
TRADE_HISTORY_LIMIT = 50

NON_LOOPBACK_RESPONSE = {
    "status": "FORBIDDEN",
    "reason": "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY",
    "detail": (
        "Atlas runtime endpoints are restricted to loopback clients until "
        "authentication is implemented."
    ),
}


def _public_decision(
    decision: Any,
) -> dict[str, Any] | None:
    """
    Project a sanitised decision onto the fields the client consumes.

    Fails closed on shape: a decision that is not a mapping is published as
    null rather than passed through, because an unexpected shape is exactly
    the case where "publish only these keys" cannot be enforced. The
    dashboard already renders a null decision as "no decision".
    """

    if decision is None:
        return None

    if not isinstance(decision, dict):
        logger.warning(
            "Dropping decision with unexpected type: %s",
            type(decision).__name__,
        )

        return None

    return {
        key: decision[key]
        for key in PUBLIC_DECISION_KEYS
        if key in decision
    }


def _public_analysis_payload(
    result: dict[str, Any],
) -> dict[str, Any]:
    """
    Project a brain result onto the fields that are safe to publish.

    Only keys actually present in the result are emitted, so a brain that
    does not produce a field does not gain a fabricated null one. The
    ``decision`` value is projected a second time, onto
    PUBLIC_DECISION_KEYS.
    """

    payload = {
        key: result[key]
        for key in PUBLIC_ANALYSIS_KEYS
        if key in result
    }

    if "decision" in payload:
        payload["decision"] = _public_decision(
            payload["decision"]
        )

    return payload


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

            # str(exc) stays in the log and never in the body - the same
            # rule /api/analysis's except branch already follows. It
            # mattered less while no runtime was ever attached; now that
            # this calls AtlasApplication.health(), the message could carry
            # a state-directory path, an exchange client detail, or any
            # other internal a raising dependency chose to put in it. Only
            # the exception's class name is published.
            logger.debug(
                "Runtime %s error: %s",
                method_name,
                exc,
            )

            return {
                "healthy": False,
                "state": "ERROR",
                "reason": "RUNTIME_HEALTH_FAILED",
                "error_type": type(exc).__name__,
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


def _resolve_attr(
    runtime: Any | None,
    name: str,
) -> Any | None:
    """
    Resolve an attribute from an injected runtime, falling back to
    ``runtime.application`` the same way ``_resolve_brain`` does. Used for
    ``market_loop`` and ``portfolio_foundation``, which live on
    AtlasApplication next to ``brain``.
    """

    if runtime is None:
        return None

    value = getattr(
        runtime,
        name,
        None,
    )

    if value is not None:
        return value

    application = getattr(
        runtime,
        "application",
        None,
    )

    if application is not None:
        return getattr(
            application,
            name,
            None,
        )

    return None


def _public_signal(
    symbol: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    """
    Project one symbol's MarketLoop.last_signals entry onto public fields.

    Builds a fixed 5-row agent breakdown from metadata.agents (evaluated)
    and metadata.unavailable_agents (excluded, with a reason) so a symbol
    missing evidence for some agents still reports all 5 names rather than
    a shrinking list.
    """

    payload: dict[str, Any] = {
        "symbol": symbol,
        **{
            key: decision[key]
            for key in PUBLIC_SIGNAL_KEYS
            if key in decision
        },
    }

    metadata = decision.get("metadata")

    if not isinstance(metadata, dict):
        metadata = {}

    evaluated = metadata.get("agents")

    if not isinstance(evaluated, dict):
        evaluated = {}

    unavailable = metadata.get("unavailable_agents")

    if not isinstance(unavailable, dict):
        unavailable = {}

    agents: dict[str, Any] = {}

    for agent_name in SIGNAL_AGENT_NAMES:
        evaluation = evaluated.get(agent_name)

        if isinstance(evaluation, dict):
            agents[agent_name] = {
                "status": "EVALUATED",
                **{
                    key: evaluation[key]
                    for key in PUBLIC_AGENT_KEYS
                    if key in evaluation
                },
            }

            continue

        reason = unavailable.get(agent_name)

        agents[agent_name] = {
            "status": "EXCLUDED",
            "reason": reason if isinstance(reason, str) else "UNKNOWN",
        }

    payload["agents"] = agents

    return payload


def _public_trade(
    record: dict[str, Any],
) -> dict[str, Any]:
    """Project one closed-position archive record onto public fields."""

    return {
        key: record[key]
        for key in PUBLIC_TRADE_KEYS
        if key in record
    }


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
    ) -> Response:
        # Same guard as the API routes. Once a runtime is attached this
        # page renders live runtime state, so the 127.0.0.1 bind is no
        # longer the only thing that must stand between it and a peer.
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )

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
    ) -> Response:
        # The dashboard serves live price, runtime state and - through the
        # endpoints it polls - the current decision. It is guarded exactly
        # like those endpoints, and the guard runs before the price
        # provider is called, so a non-loopback peer cannot even induce an
        # exchange call.
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )

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

    @application.get(
        "/api/signals",
        response_class=JSONResponse,
    )
    async def api_signals(
        request: Request,
    ) -> JSONResponse:
        # All 5 symbols' latest MarketLoop decisions, including the
        # per-agent breakdown /api/analysis deliberately drops. Reads
        # MarketLoop.status() (its own lock-protected, already-public
        # accessor) rather than a fresh single-symbol brain.process() call,
        # so this reflects what the loop actually decided this cycle
        # instead of a lower-fidelity synchronous re-run.
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )

        market_loop = _resolve_attr(
            application.state.atlas_runtime,
            "market_loop",
        )

        if market_loop is None:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "OFFLINE",
                    "reason": "MARKET_LOOP_NOT_ATTACHED",
                },
            )

        status_method = getattr(
            market_loop,
            "status",
            None,
        )

        if not callable(status_method):
            return JSONResponse(
                status_code=503,
                content={
                    "status": "OFFLINE",
                    "reason": "MARKET_LOOP_STATUS_UNAVAILABLE",
                },
            )

        try:
            loop_status = status_method()

            if not isinstance(loop_status, dict):
                return JSONResponse(
                    status_code=500,
                    content={
                        "status": "ERROR",
                        "reason": "INVALID_MARKET_LOOP_STATUS",
                        "result_type": type(loop_status).__name__,
                    },
                )

            last_signals = loop_status.get("last_signals")

            if not isinstance(last_signals, dict):
                last_signals = {}

            signals = {
                symbol: _public_signal(symbol, decision)
                for symbol, decision in last_signals.items()
                if isinstance(decision, dict)
            }

            return JSONResponse(
                status_code=200,
                content={
                    "status": "SUCCESS",
                    "signals": signals,
                },
            )

        except Exception as exc:
            logger.exception(
                "Web signals request failed"
            )

            return JSONResponse(
                status_code=500,
                content={
                    "status": "ERROR",
                    "reason": "SIGNALS_FAILED",
                    "error_type": type(exc).__name__,
                },
            )

    @application.get(
        "/api/trades",
        response_class=JSONResponse,
    )
    async def api_trades(
        request: Request,
    ) -> JSONResponse:
        # Trade/performance history, sourced directly from the durable
        # closed-position archive (the financial-truth authority) rather
        # than MarketLoop or the dead AtlasMemoryCore. An empty archive is
        # reported as available with zero trades, never as an error - a
        # freshly bootstrapped book has no history yet, that is not a
        # failure. A corrupt archive fails closed (503) rather than
        # returning partial/fabricated figures.
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )

        portfolio_foundation = _resolve_attr(
            application.state.atlas_runtime,
            "portfolio_foundation",
        )

        if portfolio_foundation is None:
            return JSONResponse(
                status_code=503,
                content={
                    "available": False,
                    "reason": "PORTFOLIO_FOUNDATION_NOT_ATTACHED",
                },
            )

        closed_archive = getattr(
            portfolio_foundation,
            "closed_archive",
            None,
        )

        load_index = getattr(
            closed_archive,
            "load_index",
            None,
        )

        if not callable(load_index):
            return JSONResponse(
                status_code=503,
                content={
                    "available": False,
                    "reason": "CLOSED_ARCHIVE_UNAVAILABLE",
                },
            )

        # load_index() and every step derived from its result are inside
        # one try/except on purpose (unlike an earlier version of this
        # handler, which only wrapped load_index() itself): load_index()
        # already validates every record strictly (validate_closed_position_
        # record - required fields, a finite gross_pnl, a CLOSED status),
        # so a record that still fails to parse here, or a closed_at value
        # that breaks the sort below, is itself evidence of corruption, not
        # a case to skip and continue past. Silently excluding such a
        # record from the aggregate totals while still listing it in
        # recent_trades would produce exactly the partial/fabricated
        # figures this endpoint exists to avoid.
        try:
            index = load_index()

            records = getattr(
                index,
                "by_position_id",
                None,
            )

            if not isinstance(records, dict):
                records = {}

            # A closed position counts as a win when its realised gross
            # P&L is strictly positive. Breakeven (gross_pnl == 0) is
            # counted as a non-win (a loss) rather than excluded from the
            # denominator - a flat trade is not evidence of a winning
            # strategy, and silently excluding it would inflate the
            # reported win rate.
            wins = 0
            losses = 0
            total_gross_pnl = Decimal("0")

            for record in records.values():
                if not isinstance(record, dict):
                    raise ValueError(
                        "CLOSED_POSITION_RECORD_NOT_A_MAPPING"
                    )

                pnl = Decimal(
                    str(record["gross_pnl"])
                )

                total_gross_pnl += pnl

                if pnl > 0:
                    wins += 1
                else:
                    losses += 1

            total_trades = wins + losses

            win_rate = (
                round(
                    wins / total_trades * 100,
                    2,
                )
                if total_trades
                else None
            )

            recent = sorted(
                records.values(),
                key=lambda record: record["closed_at"],
                reverse=True,
            )[:TRADE_HISTORY_LIMIT]

        except (OSError, UnicodeDecodeError) as exc:
            logger.exception(
                "Closed position archive is unreadable"
            )

            # Distinct from CLOSED_ARCHIVE_CORRUPT: an I/O failure means
            # the data itself may be fine but could not be read (permission,
            # transient disk error, encoding), which the operator remediates
            # differently from genuine data corruption.
            return JSONResponse(
                status_code=503,
                content={
                    "available": False,
                    "reason": "CLOSED_ARCHIVE_UNREADABLE",
                    "error_type": type(exc).__name__,
                },
            )

        except Exception as exc:
            logger.exception(
                "Closed position archive read failed"
            )

            # str(exc) stays in the log only - the same rule every other
            # handler in this module follows. Here it could carry a
            # position_id, a sequence number or a file path from the
            # archive's own corruption diagnostics.
            return JSONResponse(
                status_code=503,
                content={
                    "available": False,
                    "reason": "CLOSED_ARCHIVE_CORRUPT",
                    "error_type": type(exc).__name__,
                },
            )

        return JSONResponse(
            status_code=200,
            content={
                "available": True,
                "total_trades": total_trades,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "total_gross_pnl": str(total_gross_pnl),
                "recent_trades": [
                    _public_trade(record) for record in recent
                ],
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
        "No Atlas runtime is attached. Run atlas_service.py for the "
        "merged process that attaches one."
    )

    uvicorn.run(
        "web_app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        # Every route here is loopback-guarded on the socket peer address.
        # uvicorn's default proxy_headers=True lets X-Forwarded-For rewrite
        # that address, with the trusted-proxy set coming from the
        # FORWARDED_ALLOW_IPS environment variable - so leaving the default
        # in place would let an environment variable disable the guard.
        proxy_headers=False,
        forwarded_allow_ips=[],
    )
