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

import json
import logging
import math
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request, Response
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from observability.organization import organization_public
from observability import command_center, governance_records, panel_sources, portfolio_view, readiness, research_view, roadmap_view, security_view
from observability.panel_router import (
    build_observability_router,
    is_loopback_request,
    is_same_origin_request,
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

# Fields of the per-cycle macro / market_risk evidence (MarketLoop
# .last_agent_evidence, produced by WorldAnalysisEngine) that may be
# published. The provider "source" label is left out, and so is anything
# added later: same least-exposure allowlist as PUBLIC_AGENT_KEYS.
PUBLIC_MACRO_EVIDENCE_KEYS = (
    "observed_date",
    "ten_year_change_bp",
    "curve_spread_bp",
    "curve_inverted",
    "move",
    "vote",
    "reason",
)

PUBLIC_MARKET_RISK_EVIDENCE_KEYS = (
    "regime",
    "realized_volatility",
    "p20",
    "p80",
    "reference_windows",
    "vote",
    "reason",
)

# Venue-rule freshness fields for the System Integrity panel. "source",
# "source_version" and "schema_version" are config provenance detail the
# at-a-glance panel does not need.
PUBLIC_VENUE_RULES_KEYS = (
    "status",
    "venue",
    "observed_at",
    "age_seconds",
    "maximum_age_seconds",
    "evaluated_at",
    "reason",
)

# Audit event types ExecutionManager writes for the automatic PAPER
# risk-accounting day rollover (registry v4.81; refusal event added in
# v4.88). Mirrored as literals rather than imported: web_app is L5 and may
# not import core.execution_manager.
RISK_DAY_ROLLOVER_PREPARED = "RISK_ACCOUNTING_DAY_ROLLOVER_PREPARED"
RISK_DAY_ROLLOVER_COMMITTED = "RISK_ACCOUNTING_DAY_ROLLOVER_COMMITTED"
RISK_DAY_ROLLOVER_REFUSED = "RISK_ACCOUNTING_DAY_ROLLOVER_REFUSED"
RISK_ACCOUNTING_AGGREGATE = "risk_accounting_state"

# Audit event types ExecutionManager writes per execution request, used by
# the execution-gates panel to show each symbol's latest risk-stage outcome.
# RISK_REJECTED / RISK_APPROVED carry no symbol or confidence of their own;
# both are chained (causation_id) to the request's EXECUTION_REQUEST_VALIDATED
# event, which does. Literals for the same L5 reason as above.
EXECUTION_REQUEST_AGGREGATE = "execution_request"
EXECUTION_REQUEST_VALIDATED = "EXECUTION_REQUEST_VALIDATED"
RISK_STAGE_OUTCOMES = {
    "RISK_REJECTED": "REJECTED",
    "RISK_APPROVED": "APPROVED",
}

# Only the tail of the append-only audit log is scanned for rollover
# events, so a 30s poll never reads an unbounded file. The audit store's
# own lock is deliberately not taken: holding it would stall execution's
# audit appends for the length of a dashboard read.
AUDIT_SCAN_MAX_BYTES = 4 * 1024 * 1024

# Vendored UI assets, served only through the loopback-guarded /assets
# route below. A fixed allowlist: the route never maps a request path onto
# the filesystem. Provenance is in static/vendor/VENDORED_ASSETS.json.
VENDORED_ASSETS = {
    "adminlte.min.css": (
        BASE_DIR / "static" / "vendor" / "adminlte-4.9.1" / "adminlte.min.css",
        "text/css",
    ),
    "adminlte.min.js": (
        BASE_DIR / "static" / "vendor" / "adminlte-4.9.1" / "adminlte.min.js",
        "text/javascript",
    ),
    "chart.umd.min.js": (
        BASE_DIR / "static" / "vendor" / "chartjs-4.5.1" / "chart.umd.min.js",
        "text/javascript",
    ),
}

# Defense-in-depth response headers applied to every response this
# application serves (registry v4.86/v4.87 backlog item A2). script-src and
# style-src keep 'unsafe-inline' because templates/dashboard.html renders
# inline <script> blocks and inline style="" attributes with no nonce
# infrastructure yet; tightening that is a separate, larger change. Every
# other directive is as strict as the current templates and vendored
# /assets allow: no third-party origins, no framing, no plugins.
SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

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


# =====================================================================
# /api/status ALLOWLIST
# =====================================================================
#
# AtlasApplication.status() is the console's view and carries operator-
# only detail: str(error) and a full traceback in errors.latest (file
# paths, exchange error text), the raw execution halt_reason (which can
# embed an execution_id, idempotency_key or position_id), audit-failure
# records, and per-symbol signal/execution snapshots. /api/status is an
# HTTP body, so it is rebuilt here from an explicit allowlist instead of
# being returned verbatim; status() itself is left unchanged for the
# console.
#
# Fail closed throughout: a key not named below is dropped, a value of the
# wrong type or shape is published as null, and strings are only published
# when they match a narrow pattern that cannot carry a path, a URL, a
# sentence or a traceback. Error records reduce to a category and an
# exception type name. The halt reason is published only as health()'s
# already-classified execution_halt_reason - the same allowlist code
# /api/health publishes - and never from execution.operational_state.

_STATUS_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_STATUS_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}")
_STATUS_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+\-]\d{2}:\d{2})?"
)


def _status_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _status_number(value: Any) -> int | float | str | None:
    """Finite int/float as-is; a finite Decimal as its exact string form."""

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, Decimal):
        return format(value, "f") if value.is_finite() else None

    return None


def _status_pattern(pattern: re.Pattern[str]) -> Callable[[Any], str | None]:
    def sanitize(value: Any) -> str | None:
        if isinstance(value, str) and pattern.fullmatch(value):
            return value

        return None

    return sanitize


_status_code = _status_pattern(_STATUS_CODE_PATTERN)
_status_identifier = _status_pattern(_STATUS_IDENTIFIER_PATTERN)


def _status_timestamp(value: Any) -> str | None:
    if isinstance(value, datetime):
        value = value.isoformat()

    if isinstance(value, str) and _STATUS_TIMESTAMP_PATTERN.fullmatch(value):
        return value

    return None


def _status_identifier_list(value: Any) -> list[str | None] | None:
    if not isinstance(value, (list, tuple)):
        return None

    return [_status_identifier(item) for item in value[:256]]


def _status_error_record(value: Any) -> dict[str, Any] | None:
    """Reduce an error record to its category and exception type name.

    Never the message, the traceback, a request id or anything else the
    record carries. The field names differ between services (phase/stage,
    type/error_type, time/timestamp), so each is read from either.
    """

    if not isinstance(value, dict):
        return None

    return {
        "category": _status_identifier(
            value.get("phase", value.get("stage")),
        ),
        "type": _status_identifier(
            value.get("type", value.get("error_type")),
        ),
        "time": _status_timestamp(
            value.get("time", value.get("timestamp")),
        ),
    }


def _status_mapping(
    key_sanitizer: Callable[[Any], str | None],
    value_spec: Any,
) -> Callable[[Any], dict[str, Any] | None]:
    """A dict with data-dependent keys (symbols, journal states)."""

    def sanitize(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None

        result: dict[str, Any] = {}

        for key, item in list(value.items())[:256]:
            safe_key = key_sanitizer(key)

            if safe_key is not None:
                result[safe_key] = _apply_status_spec(value_spec, item)

        return result

    return sanitize


def _apply_status_spec(spec: Any, value: Any) -> Any:
    """Apply a nested allowlist: a dict of key -> spec, or a leaf callable."""

    if callable(spec):
        return spec(value)

    if not isinstance(value, dict):
        return None

    return {
        key: _apply_status_spec(child_spec, value.get(key))
        for key, child_spec in spec.items()
        if key in value
    }


_STATUS_ERRORS_SPEC = {
    "count": _status_number,
    "latest": _status_error_record,
}

_STATUS_BRAIN_SPEC = {
    "name": _status_identifier,
    "version": _status_identifier,
    "initialized": _status_bool,
    "running": _status_bool,
    "intelligence_loaded": _status_bool,
    "cycles": _status_number,
    "errors": _status_number,
    "rejections": _status_number,
    "created_at": _status_timestamp,
    "started_at": _status_timestamp,
    "stopped_at": _status_timestamp,
    "last_error": _status_error_record,
}

_STATUS_EXECUTION_SPEC = {
    "name": _status_identifier,
    "version": _status_identifier,
    "mode": _status_code,
    "running": _status_bool,
    "minimum_confidence": _status_number,
    "live_execution_enabled": _status_bool,
    # halt_reason and last_audit_failure deliberately absent - see above.
    "operational_state": {
        "audit_runtime_state": _status_code,
        "execution_halted": _status_bool,
        "recovery_required": _status_bool,
        "audit_incident_count": _status_number,
    },
    # source (a URL) deliberately absent.
    "venue_rules": {
        "status": _status_code,
        "venue": _status_code,
        "schema_version": _status_identifier,
        "symbol_count": _status_number,
        "source_version": _status_identifier,
        "observed_at": _status_timestamp,
        "age_seconds": _status_number,
        "maximum_age_seconds": _status_number,
        "evaluated_at": _status_timestamp,
        "reason": _status_code,
    },
    "transaction_journal": {
        "name": _status_identifier,
        "version": _status_identifier,
        "loaded": _status_bool,
        "load_failed": _status_bool,
        "migration_required": _status_bool,
        "entries": _status_number,
        "unresolved_entries": _status_number,
        "state_counts": _status_mapping(_status_code, _status_number),
        "last_loaded_at": _status_timestamp,
        "last_saved_at": _status_timestamp,
        "statistics": _status_mapping(_status_identifier, _status_number),
    },
    "durable_financial_state": {
        "ready": _status_bool,
        "recovery_required": _status_bool,
        "reason": _status_code,
    },
    "history": _status_number,
    "rejections": _status_number,
    "errors": _STATUS_ERRORS_SPEC,
    "statistics": _status_mapping(_status_identifier, _status_number),
    "dependencies": _status_mapping(_status_identifier, _status_bool),
}

# last_signals / last_agent_evidence / last_executions /
# last_processed_candles deliberately absent: per-symbol snapshots with
# free-form content (execution ids among them). /api/signals and
# /api/trades are the operator surfaces for that detail.
_STATUS_MARKET_LOOP_SPEC = {
    "name": _status_identifier,
    "version": _status_identifier,
    "running": _status_bool,
    "thread_alive": _status_bool,
    "started_at": _status_timestamp,
    "stopped_at": _status_timestamp,
    "symbols": _status_identifier_list,
    "symbol_count": _status_number,
    "interval": _status_number,
    "last_cycle": _status_timestamp,
    "last_cycle_duration": _status_number,
    "metrics": _status_mapping(_status_identifier, _status_number),
    "market_data_staleness": _status_mapping(
        _status_identifier,
        {
            "seconds_since_last_success": _status_number,
            "stale": _status_bool,
        },
    ),
    "errors": _STATUS_ERRORS_SPEC,
    "dependencies": _status_mapping(_status_identifier, _status_bool),
}

# Keys every AtlasApplication._safe_status fallback can produce in place of
# a service's own status(). status_error (str(exc)) deliberately absent.
_STATUS_SERVICE_FALLBACK_SPEC = {
    "available": _status_bool,
    "status_supported": _status_bool,
    "healthy": _status_bool,
}


def _status_service(spec: dict[str, Any]) -> dict[str, Any]:
    return {**_STATUS_SERVICE_FALLBACK_SPEC, **spec}


_STATUS_RESPONSE_SPEC = {
    "application": {
        "name": _status_identifier,
        "version": _status_identifier,
        "initialized": _status_bool,
        "running": _status_bool,
        "created_at": _status_timestamp,
        "started_at": _status_timestamp,
        "stopped_at": _status_timestamp,
        "execution_mode": _status_code,
        "exchange": _status_identifier,
    },
    "runtime": _status_service(
        {
            "state": _status_code,
            "healthy": _status_bool,
            "started_at": _status_timestamp,
            "last_transition": _status_timestamp,
            "reason": _status_code,
            "version": _status_identifier,
            "emergency_mode": _status_bool,
        }
    ),
    "brain": _status_service(_STATUS_BRAIN_SPEC),
    "execution": _status_service(_STATUS_EXECUTION_SPEC),
    "market_feed": _status_service({}),
    "market_loop": _status_service(_STATUS_MARKET_LOOP_SPEC),
    "controller": _status_service(
        {
            "name": _status_identifier,
            "version": _status_identifier,
            "state": _status_code,
            "running": _status_bool,
            "created_at": _status_timestamp,
            "started_at": _status_timestamp,
            "stopped_at": _status_timestamp,
            "timestamp": _status_timestamp,
            "start_count": _status_number,
            "stop_count": _status_number,
            "errors": _status_number,
            "last_error": _status_error_record,
            "brain": _status_service(_STATUS_BRAIN_SPEC),
            "market_loop": _status_service(_STATUS_MARKET_LOOP_SPEC),
            "execution": _status_service(_STATUS_EXECUTION_SPEC),
        }
    ),
    "capital": _status_service(
        {
            "version": _status_identifier,
            "capital": _status_number,
            "portfolio_value": _status_number,
            "available": {
                "total": _status_number,
                "used": _status_number,
                "available": _status_number,
                "positions": _status_number,
            },
            "positions": _status_number,
            "risk_usage": _status_mapping(_status_identifier, _status_number),
        }
    ),
    "position_controller": _status_service(
        {
            "name": _status_identifier,
            "version": _status_identifier,
            "active": _status_number,
            "closed": _status_number,
            "symbols": _status_identifier_list,
            "total_exposure": _status_number,
            "unrealized_pnl": _status_number,
            "realized_pnl": _status_number,
            "open_count": _status_number,
            "close_count": _status_number,
            "update_count": _status_number,
            "rejected_count": _status_number,
            "error_count": _status_number,
            "last_error": _status_error_record,
        }
    ),
    "services": {
        "registered": _status_identifier_list,
        "started": _status_identifier_list,
    },
    # health() is already the /api/health contract; it is still passed
    # through its own allowlist here rather than trusted wholesale.
    "health": {
        "healthy": _status_bool,
        "running": _status_bool,
        "execution_halted": _status_bool,
        "execution_recovery_required": _status_bool,
        "execution_halt_reason": _status_code,
        "supervised": _status_bool,
        "supervisor_epoch": _status_identifier,
        "supervisor_restart_count": _status_number,
        "runtime_state": _status_code,
        "error_count": _status_number,
        "market_data_stale": _status_bool,
        "market_data_stale_reason": _status_code,
        "market_loop_thread_alive": _status_bool,
    },
    "errors": _STATUS_ERRORS_SPEC,
}


def _public_runtime_status(status: dict[str, Any]) -> dict[str, Any]:
    """Rebuild status() for /api/status from the allowlist above."""

    return _apply_status_spec(_STATUS_RESPONSE_SPEC, status)


def _safe_runtime_status(
    runtime: Any | None,
) -> dict[str, Any]:
    """
    Return AtlasApplication.status(), rebuilt from the /api/status
    allowlist above, without allowing a raising runtime to break the
    route. Same exception-handling contract as _safe_runtime_health - only
    the exception's class name is published, never str(exc).

    The loopback guard is not treated as a reason to publish status()
    verbatim: an HTTP body is copied, cached and pasted in ways a console
    line is not, so this route publishes no more than the allowlist names.
    A result that still cannot be encoded as strict JSON is reported with
    the same RUNTIME_STATUS_FAILED shape as a raising status() rather than
    becoming a 500.
    """

    if runtime is None:
        return {
            "available": False,
            "reason": "RUNTIME_NOT_ATTACHED",
        }

    status_method = getattr(
        runtime,
        "status",
        None,
    )

    if not callable(status_method):
        return {
            "available": True,
            "reason": "RUNTIME_STATUS_UNAVAILABLE",
        }

    try:
        result = status_method()
    except Exception as exc:
        logger.exception(
            "Runtime status call failed",
        )

        logger.debug(
            "Runtime status error: %s",
            exc,
        )

        return {
            "available": True,
            "reason": "RUNTIME_STATUS_FAILED",
            "error_type": type(exc).__name__,
        }

    if not isinstance(result, dict):
        return {
            "available": True,
            "reason": "INVALID_RUNTIME_STATUS_RESULT",
            "result_type": type(result).__name__,
        }

    try:
        public = _public_runtime_status(result)

        # The same strict encoding JSONResponse applies, run here so a
        # value it would reject is caught inside this function.
        json.dumps(public, allow_nan=False)
    except Exception as exc:
        logger.exception(
            "Runtime status could not be made publishable",
        )

        return {
            "available": True,
            "reason": "RUNTIME_STATUS_FAILED",
            "error_type": type(exc).__name__,
        }

    return public


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


def _account_totals(portfolio_foundation: Any) -> dict[str, str] | None:
    """Account-level realized net P&L and fees from the durable book, or None."""

    snapshot = getattr(portfolio_foundation, "snapshot", None)
    if not callable(snapshot):
        return None
    try:
        snap = snapshot()
        return {
            "realized_net_pnl": str(Decimal(str(snap["realized_net_pnl"]))),
            "fees": str(Decimal(str(snap["fees"]))),
        }
    except Exception:
        logger.debug("Account totals unavailable", exc_info=True)
        return None


def _public_trade(
    record: dict[str, Any],
) -> dict[str, Any]:
    """Project one closed-position archive record onto public fields."""

    return {
        key: record[key]
        for key in PUBLIC_TRADE_KEYS
        if key in record
    }


def _public_scalars(
    value: Any,
    keys: tuple[str, ...],
) -> dict[str, Any] | None:
    """
    Allowlist projection that also refuses non-scalar values, so a nested
    structure added under an allowed key later cannot cross the boundary.
    A value that is not a mapping is published as null.
    """

    if not isinstance(value, dict):
        return None

    return {
        key: value[key]
        for key in keys
        if key in value
        and (
            value[key] is None
            or isinstance(value[key], (str, int, float, bool))
        )
    }


def _public_agent_evidence(
    entry: Any,
) -> dict[str, Any]:
    """
    One symbol's last_agent_evidence, keyed by the dashboard's agent names
    (AgentFusion's "risk" agent reads the "market_risk" evidence).
    """

    if not isinstance(entry, dict):
        entry = {}

    return {
        "macro": _public_scalars(
            entry.get("macro"),
            PUBLIC_MACRO_EVIDENCE_KEYS,
        ),
        "risk": _public_scalars(
            entry.get("market_risk"),
            PUBLIC_MARKET_RISK_EVIDENCE_KEYS,
        ),
    }


def _read_audit_tail_lines(
    path: Path,
) -> tuple[list[str], bool]:
    """
    Return complete lines from the last AUDIT_SCAN_MAX_BYTES of the audit
    log, and whether the scan was truncated. A missing file is no lines.
    """

    if not path.is_file():
        return [], False

    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        start = max(0, size - AUDIT_SCAN_MAX_BYTES)
        handle.seek(start)
        raw = handle.read(size - start)

    lines = raw.decode("utf-8", errors="replace").splitlines()

    if start > 0 and lines:
        # The first line of a mid-file window is almost always partial.
        lines = lines[1:]

    return lines, start > 0


def _latest_rollover(
    lines: list[str],
) -> dict[str, Any] | None:
    """
    The most recent rollover PREPARED record, and whether a COMMITTED
    record points back at it. Only day labels and timestamps are
    published; the equity figures in the payload stay out.
    """

    prepared: dict[str, Any] | None = None
    committed_by_cause: dict[str, str] = {}

    for line in lines:
        line = line.strip()

        if not line:
            continue

        try:
            event = json.loads(line)
        except ValueError:
            continue

        if (
            not isinstance(event, dict)
            or event.get("aggregate_type") != RISK_ACCOUNTING_AGGREGATE
        ):
            continue

        event_type = event.get("event_type")

        if event_type == RISK_DAY_ROLLOVER_PREPARED:
            prepared = event
        elif event_type == RISK_DAY_ROLLOVER_COMMITTED:
            cause = event.get("causation_id")

            if isinstance(cause, str):
                timestamp = event.get("timestamp")
                committed_by_cause[cause] = (
                    timestamp if isinstance(timestamp, str) else ""
                )

    if prepared is None:
        return None

    payload = prepared.get("payload")

    if not isinstance(payload, dict):
        payload = {}

    event_id = prepared.get("event_id")
    committed_at = committed_by_cause.get(event_id) if isinstance(event_id, str) else None

    def _text(value: Any) -> str | None:
        return value if isinstance(value, str) else None

    return {
        "outcome": "COMMITTED" if committed_at is not None else "PREPARED_ONLY",
        "from_accounting_day_utc": _text(payload.get("from_accounting_day_utc")),
        "to_accounting_day_utc": _text(payload.get("to_accounting_day_utc")),
        "prepared_at": _text(prepared.get("timestamp")),
        "committed_at": committed_at or None,
    }


def _latest_rollover_refusal(
    lines: list[str],
    *,
    stored_day: str | None,
    today: str,
) -> dict[str, Any] | None:
    """
    The most recent RISK_ACCOUNTING_DAY_ROLLOVER_REFUSED record that
    explains why the rollover from ``stored_day`` to ``today`` is still
    refused, or None.

    A refusal is only reported when its payload names exactly this
    transition (``from_accounting_day_utc == stored_day`` and
    ``to_accounting_day_utc == today``). A refusal left over from an
    earlier, since-resolved transition - or one for a day pair that is not
    the currently stored day - is never shown as if it were still active;
    that would misreport a resolved state as an ongoing one.
    """

    if stored_day is None:
        return None

    latest: dict[str, Any] | None = None

    for line in lines:
        line = line.strip()

        if not line:
            continue

        try:
            event = json.loads(line)
        except ValueError:
            continue

        if (
            not isinstance(event, dict)
            or event.get("aggregate_type") != RISK_ACCOUNTING_AGGREGATE
            or event.get("event_type") != RISK_DAY_ROLLOVER_REFUSED
        ):
            continue

        payload = event.get("payload")

        if not isinstance(payload, dict):
            continue

        if (
            payload.get("from_accounting_day_utc") == stored_day
            and payload.get("to_accounting_day_utc") == today
        ):
            latest = event

    if latest is None:
        return None

    payload = latest.get("payload")
    reason = payload.get("reason") if isinstance(payload, dict) else None

    if not isinstance(reason, str):
        return None

    timestamp = latest.get("timestamp")

    return {
        "reason": reason,
        "refused_at": timestamp if isinstance(timestamp, str) else None,
    }


def _risk_accounting_payload(
    runtime: Any | None,
) -> tuple[int, dict[str, Any]]:
    """Build the Risk Accounting panel body. Read-only throughout."""

    if runtime is None:
        return 503, {"available": False, "reason": "RUNTIME_NOT_ATTACHED"}

    store = _resolve_attr(runtime, "risk_state_store")
    policy = _resolve_attr(runtime, "risk_policy")
    policy_version = getattr(policy, "version", None)

    if not callable(getattr(store, "load", None)) or not isinstance(policy_version, str):
        return 503, {"available": False, "reason": "RISK_STATE_STORE_UNAVAILABLE"}

    today = datetime.now(UTC).date()
    day: dict[str, Any]

    # JsonRiskStateStore.load is a plain file read with validation; it
    # never rolls or repairs anything.
    try:
        restored = store.load(
            expected_policy_version=policy_version,
            today_utc=today,
        )
        accounting_day = restored.accounting_day_utc
        day = {
            "state": "CURRENT" if accounting_day == today else "BEHIND_TODAY",
            "accounting_day_utc": accounting_day.isoformat(),
        }
    except FileNotFoundError:
        day = {"state": "RISK_STATE_MISSING", "accounting_day_utc": None}
    except (OSError, UnicodeDecodeError) as exc:
        logger.exception("Risk accounting state is unreadable")
        day = {
            "state": "RISK_STATE_UNREADABLE",
            "accounting_day_utc": None,
            "error_type": type(exc).__name__,
        }
    except Exception as exc:
        # Schema, policy-version or future-day refusal: the text can carry
        # internal detail, so only the class name is published.
        logger.exception("Risk accounting state failed validation")
        day = {
            "state": "RISK_STATE_INVALID",
            "accounting_day_utc": None,
            "error_type": type(exc).__name__,
        }

    audit_store = _resolve_attr(runtime, "audit_store")
    audit_path = getattr(audit_store, "file_path", None)
    rollover: dict[str, Any]
    refusal_reason: str | None = None
    refusal_reason_source: str

    if not isinstance(audit_path, Path):
        rollover = {"available": False, "reason": "AUDIT_STORE_UNAVAILABLE"}
        refusal_reason_source = "AUDIT_STORE_UNAVAILABLE"
    else:
        try:
            lines, truncated = _read_audit_tail_lines(audit_path)
        except (OSError, UnicodeDecodeError) as exc:
            logger.exception("Audit log is unreadable")
            rollover = {
                "available": False,
                "reason": "AUDIT_LOG_UNREADABLE",
                "error_type": type(exc).__name__,
            }
            refusal_reason_source = "AUDIT_LOG_UNREADABLE"
        else:
            rollover = {
                "available": True,
                "latest": _latest_rollover(lines),
                "scan_truncated": truncated,
                "scan_limit_bytes": AUDIT_SCAN_MAX_BYTES,
            }
            refusal = _latest_rollover_refusal(
                lines,
                stored_day=day.get("accounting_day_utc"),
                today=today.isoformat(),
            )
            if refusal is not None:
                refusal_reason = refusal["reason"]
                refusal_reason_source = "AUDIT_TRAIL"
            else:
                refusal_reason_source = "NO_REFUSAL_RECORDED"

    return 200, {
        "available": True,
        "today_utc": today.isoformat(),
        "accounting_day": day,
        "rollover": rollover,
        # v4.88 wired ExecutionManager's rollover-refusal audit event, so the
        # reason is now sourced from the audit trail instead of the
        # WARNING-log-only state left by v4.81 (registry v4.88 CONFLICT).
        "refusal_reason": refusal_reason,
        "refusal_reason_source": refusal_reason_source,
    }


def _system_integrity_payload(
    runtime: Any | None,
) -> dict[str, Any]:
    """Venue-rule freshness, registry head, and known limitations."""

    venue_rules: dict[str, Any]
    execution = _resolve_attr(runtime, "execution")
    assess = getattr(execution, "assess_venue_rule_freshness", None)

    if runtime is None:
        venue_rules = {"available": False, "reason": "RUNTIME_NOT_ATTACHED"}
    elif not callable(assess):
        venue_rules = {"available": False, "reason": "VENUE_RULES_UNAVAILABLE"}
    else:
        try:
            report = assess()
            projected = _public_scalars(
                report.to_dict(),
                PUBLIC_VENUE_RULES_KEYS,
            )
            venue_rules = (
                {"available": True, **projected}
                if projected is not None
                else {"available": False, "reason": "VENUE_RULES_MALFORMED"}
            )
        except Exception as exc:
            logger.exception("Venue rule freshness assessment failed")
            venue_rules = {
                "available": False,
                "reason": "VENUE_RULES_ASSESSMENT_FAILED",
                "error_type": type(exc).__name__,
            }

    resolved = panel_sources.resolve_current_registry()

    if resolved.get("available") is True:
        schema_version = resolved["payload"].get("schema_version")
        registry = {
            "available": True,
            "version": schema_version if isinstance(schema_version, str) else None,
            "file": resolved["head"],
        }
    else:
        registry = {"available": False, "reason": resolved.get("reason")}

    return {
        "available": True,
        "venue_rules": venue_rules,
        "registry": registry,
        "known_limitations": [
            dict(item) for item in panel_sources.KNOWN_LIMITATIONS
        ],
    }


def _confidence_pct(value: Any) -> float | None:
    """A RiskPolicy 0-1 Decimal as a 0-100 display number, or None."""

    if not isinstance(value, Decimal) or not value.is_finite():
        return None

    return float(value * 100)


def _risk_policy_gates(
    runtime: Any | None,
) -> dict[str, Any]:
    """
    The per-bucket confidence floors of the RiskPolicy instance the running
    RiskEngine evaluates against (AtlasApplication shares one instance
    between RiskEngine and PositionSizingService). Read, never copied from
    a default: a policy built with different buckets is shown as built.

    ``required_confidence_pct`` mirrors core/risk_engine.py's BUY check,
    ``confidence < max(global_minimum_confidence, bucket.minimum_confidence)``,
    so it is the floor that bucket actually enforces.
    """

    # Reads runtime.risk_policy, not runtime.risk_engine.policy. They are
    # the same instance today (core/application.py:768-778 constructs one
    # RiskPolicy and passes it into RiskEngine) but that identity isn't
    # enforced here, so a future divergence between the two attributes
    # would go unnoticed by this read.
    policy = _resolve_attr(runtime, "risk_policy")
    version = getattr(policy, "version", None)
    global_pct = _confidence_pct(
        getattr(policy, "global_minimum_confidence", None)
    )
    buckets = getattr(policy, "buckets", None)

    if (
        not isinstance(version, str)
        or global_pct is None
        or not isinstance(buckets, dict)
        or not buckets
    ):
        return {"available": False, "reason": "RISK_POLICY_UNAVAILABLE"}

    published: dict[str, Any] = {}

    for key, bucket_policy in buckets.items():
        name = getattr(key, "value", key)
        bucket_pct = _confidence_pct(
            getattr(bucket_policy, "minimum_confidence", None)
        )

        if not isinstance(name, str) or bucket_pct is None:
            return {"available": False, "reason": "RISK_POLICY_MALFORMED"}

        published[name] = {
            "minimum_confidence_pct": bucket_pct,
            "required_confidence_pct": max(global_pct, bucket_pct),
        }

    return {
        "available": True,
        "version": version,
        "global_minimum_confidence_pct": global_pct,
        "buckets": published,
    }


def _experiment_gate(
    runtime: Any | None,
    risk_policy: dict[str, Any],
) -> dict[str, Any]:
    """
    The paper confidence-floor experiment attached to the running
    RiskEngine (EXP-001, registry v5.01), read from
    ``RiskEngine.experiment_status()``. While it is active it replaces the
    policy floor for its buckets with
    ``max(global_minimum_confidence, experiment.minimum_confidence)`` -
    the same expression as ``RiskEngine._experiment_floor`` - so the page
    must not show the policy floor as the one being enforced.

    Anything unreadable is reported as unavailable, never as "no
    experiment": the page then keeps saying the floor is unknown.
    """

    engine = _resolve_attr(runtime, "risk_engine")
    status_reader = getattr(engine, "experiment_status", None)

    if not callable(status_reader):
        return {"available": False, "reason": "RISK_ENGINE_UNAVAILABLE"}

    try:
        status = status_reader()
    except Exception:
        logger.exception("Experiment status is unreadable")
        return {"available": False, "reason": "EXPERIMENT_STATUS_UNREADABLE"}

    if status is None:
        return {"available": True, "attached": False}

    if not isinstance(status, dict):
        return {"available": False, "reason": "EXPERIMENT_STATUS_MALFORMED"}

    if risk_policy.get("available") is not True:
        return {"available": False, "reason": "RISK_POLICY_UNAVAILABLE"}

    try:
        minimum_pct = _confidence_pct(Decimal(str(status.get("minimum_confidence"))))
    except (InvalidOperation, ValueError):
        minimum_pct = None

    global_pct = risk_policy.get("global_minimum_confidence_pct")
    buckets = status.get("buckets")

    if (
        minimum_pct is None
        or not isinstance(global_pct, (int, float))
        or not isinstance(buckets, list)
        or not all(isinstance(name, str) for name in buckets)
        or not isinstance(status.get("active"), bool)
    ):
        return {"available": False, "reason": "EXPERIMENT_STATUS_MALFORMED"}

    return {
        "available": True,
        "attached": True,
        "experiment_id": str(status.get("experiment_id")),
        "active": status["active"],
        "closed_reason": status.get("closed_reason"),
        "buckets": buckets,
        "required_confidence_pct": max(global_pct, minimum_pct),
        "admissions": status.get("admissions"),
        "max_admissions": status.get("max_admissions"),
        "starts_at": status.get("starts_at"),
        "ends_at": status.get("ends_at"),
    }


def _latest_risk_decisions(
    lines: list[str],
) -> dict[str, dict[str, Any]]:
    """
    Each symbol's most recent risk-stage outcome in the scanned audit tail.

    A RISK_REJECTED / RISK_APPROVED event is attributed to a symbol only
    through its causation link to an EXECUTION_REQUEST_VALIDATED event in
    the same window; an outcome whose validation event is outside the
    window (or malformed) is skipped rather than attributed by parsing its
    request id. Only codes, the action, the confidence and the timestamp
    are published; the allocation and equity figures in the details stay
    out.
    """

    validated: dict[str, dict[str, Any]] = {}
    latest: dict[str, dict[str, Any]] = {}

    for line in lines:
        line = line.strip()

        if not line:
            continue

        try:
            event = json.loads(line)
        except ValueError:
            continue

        if (
            not isinstance(event, dict)
            or event.get("aggregate_type") != EXECUTION_REQUEST_AGGREGATE
        ):
            continue

        event_type = event.get("event_type")
        payload = event.get("payload")

        if not isinstance(payload, dict):
            continue

        if event_type == EXECUTION_REQUEST_VALIDATED:
            event_id = event.get("event_id")
            symbol = payload.get("symbol")
            action = payload.get("action")
            confidence = payload.get("confidence")

            if (
                isinstance(event_id, str)
                and isinstance(symbol, str)
                and isinstance(action, str)
                and isinstance(confidence, (int, float))
                and not isinstance(confidence, bool)
                and math.isfinite(confidence)
            ):
                validated[event_id] = {
                    "symbol": symbol,
                    "action": action,
                    "confidence": confidence,
                }

            continue

        outcome = RISK_STAGE_OUTCOMES.get(event_type)

        if outcome is None:
            continue

        cause = event.get("causation_id")
        origin = validated.get(cause) if isinstance(cause, str) else None

        if origin is None:
            continue

        reason = payload.get("reason") if outcome == "REJECTED" else event_type
        timestamp = event.get("timestamp")

        latest[origin["symbol"]] = {
            "outcome": outcome,
            "reason": reason if isinstance(reason, str) else None,
            "action": origin["action"],
            "confidence": origin["confidence"],
            "decided_at": timestamp if isinstance(timestamp, str) else None,
        }

    return latest


def _execution_gates_payload(
    runtime: Any | None,
) -> tuple[int, dict[str, Any]]:
    """
    The two confidence gates a BUY passes on its way to execution, and each
    symbol's latest risk-stage outcome. Read-only throughout.

    ExecutionManager checks its flat ``minimum_confidence`` (0-100) first;
    RiskEngine then applies the per-bucket floor (0-1, converted here to
    0-100). They are published separately so the page never presents one
    as the other.
    """

    if runtime is None:
        return 503, {"available": False, "reason": "RUNTIME_NOT_ATTACHED"}

    execution = _resolve_attr(runtime, "execution")
    execution_minimum = getattr(execution, "minimum_confidence", None)

    if (
        not isinstance(execution_minimum, (int, float))
        or isinstance(execution_minimum, bool)
        or not math.isfinite(execution_minimum)
    ):
        execution_minimum = None

    audit_store = _resolve_attr(runtime, "audit_store")
    audit_path = getattr(audit_store, "file_path", None)
    decisions: dict[str, Any]

    if not isinstance(audit_path, Path):
        decisions = {"available": False, "reason": "AUDIT_STORE_UNAVAILABLE"}
    else:
        try:
            lines, truncated = _read_audit_tail_lines(audit_path)
        except (OSError, UnicodeDecodeError) as exc:
            logger.exception("Audit log is unreadable")
            decisions = {
                "available": False,
                "reason": "AUDIT_LOG_UNREADABLE",
                "error_type": type(exc).__name__,
            }
        else:
            decisions = {
                "available": True,
                "by_symbol": _latest_risk_decisions(lines),
                "scan_truncated": truncated,
            }

    risk_policy = _risk_policy_gates(runtime)

    return 200, {
        "available": True,
        "execution_minimum_confidence": execution_minimum,
        "risk_policy": risk_policy,
        "experiment": _experiment_gate(runtime, risk_policy),
        "latest_risk_decisions": decisions,
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
        # The auto-mounted /docs, /redoc and /openapi.json below reuse
        # is_loopback_request instead of FastAPI's unguarded defaults, so
        # those defaults are switched off here.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    templates = Jinja2Templates(
        directory=str(TEMPLATE_DIR),
    )

    application.state.atlas_runtime = runtime
    application.state.price_provider = price_provider

    @application.middleware("http")
    async def _apply_security_headers(
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        response = await call_next(request)

        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value

        return response

    @application.get("/openapi.json", include_in_schema=False)
    async def openapi_schema(request: Request) -> Response:
        if not is_loopback_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)

        return JSONResponse(application.openapi())

    @application.get(
        "/docs",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def swagger_docs(request: Request) -> Response:
        if not is_loopback_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)

        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title=f"{application.title} - Swagger UI",
        )

    @application.get(
        "/redoc",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def redoc_docs(request: Request) -> Response:
        if not is_loopback_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)

        return get_redoc_html(
            openapi_url="/openapi.json",
            title=f"{application.title} - ReDoc",
        )

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
        "/agents",
        response_class=HTMLResponse,
    )
    async def agents_page(
        request: Request,
    ) -> Response:
        # Registry v5.29: the organization / agents page. Static shell; all
        # data comes from the read-only /api/organization, /api/signals and
        # /api/agent-evidence endpoints it polls. Guarded like every page.
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )

        return templates.TemplateResponse(
            request=request,
            name="agents.html",
            context={},
        )

    # Registry v5.40 (owner: a simple start page, details on other pages).
    for _path, _template in (("/home", "home.html"), ("/trading", "trading.html"), ("/governance", "governance.html"),
                             ("/system", "system.html"), ("/security", "security.html"),
                             ("/roadmap", "roadmap.html"), ("/research", "research.html"),
                             ("/decisions", "decisions.html")):
        async def _static_page(request: Request, _template=_template) -> Response:
            if not is_loopback_request(request):
                return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)
            return templates.TemplateResponse(request=request, name=_template, context={})

        application.add_api_route(_path, _static_page, methods=["GET"], response_class=HTMLResponse)

    @application.get("/hq", response_class=HTMLResponse)
    async def hq_page(request: Request) -> Response:
        # Registry v5.38: Atlas HQ. Static shell; the 3D view is presentation
        # only and every value comes from the read-only APIs it polls.
        if not is_loopback_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)
        return templates.TemplateResponse(request=request, name="hq.html", context={})

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
        "/api/status",
        response_class=JSONResponse,
    )
    async def api_status(
        request: Request,
    ) -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )

        status = _safe_runtime_status(
            application.state.atlas_runtime
        )

        return JSONResponse(
            status_code=200,
            content=status,
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

        content = {
            "available": True,
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_gross_pnl": str(total_gross_pnl),
            "recent_trades": [
                _public_trade(record) for record in recent
            ],
        }
        # Registry v5.24 (owner, recommended option): account-level realized
        # net P&L and total fees only - aggregates the operator already sees
        # in tools/exp001_report. Per-position cost, fees and prices stay off
        # the web surface. Present only when the durable book can be read;
        # never a placeholder.
        account = _account_totals(portfolio_foundation)
        if account is not None:
            content["account"] = account
        return JSONResponse(
            status_code=200,
            content=content,
        )

    @application.get(
        "/api/organization",
        response_class=JSONResponse,
    )
    async def api_organization(
        request: Request,
    ) -> JSONResponse:
        # Registry v5.25: the Atlas organization roster (every corporate unit
        # and agent from the owner's vision documents) with its real status.
        # Static, read-only data; ACTIVE only where running code backs it.
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )
        return JSONResponse(
            status_code=200,
            content=organization_public(),
        )

    # Registry v5.34 (owner: "Önce yönetişim temeli"): proposals, Atlas
    # Memory and agent permissions. Read-only replays of the hash-chained
    # logs in governance/records/; a corrupted log reads as unavailable.
    for path, reader in (
        ("/api/proposals", governance_records.read_proposals),
        ("/api/memory", governance_records.read_memory),
        ("/api/permissions", governance_records.read_permissions),
        ("/api/tasks", governance_records.read_tasks),
        ("/api/security", security_view.read_security),
        ("/api/roadmap", roadmap_view.read_roadmap),
        ("/api/research", research_view.read_research),
    ):
        async def _governance_route(request: Request, _reader=reader) -> JSONResponse:
            if not is_loopback_request(request):
                return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)
            return JSONResponse(status_code=200, content=await run_in_threadpool(_reader))

        application.add_api_route(path, _governance_route, methods=["GET"],
                                  response_class=JSONResponse)

    # Registry v5.37: Command Center brief and Atlas Chat. Both only read
    # the payloads above (health, account totals, proposals, tasks, memory);
    # the chat is deterministic and cannot act.
    def _command_center_brief() -> dict:
        runtime = application.state.atlas_runtime
        return command_center.compose(
            health=_safe_runtime_health(runtime),
            account=_account_totals(_resolve_attr(runtime, "portfolio_foundation")),
            proposals=governance_records.read_proposals(),
            tasks=governance_records.read_tasks(),
            memory=governance_records.read_memory(),
            portfolio=_portfolio_payload(),
        )

    # Registry v5.40 (owner: real-time capital and P/L, not fake data): the
    # durable PAPER book valued at MarketLoop's latest real prices. Read-only:
    # snapshot() and status() are the runtime's own public accessors.
    def _portfolio_payload() -> dict:
        runtime = application.state.atlas_runtime
        foundation = _resolve_attr(runtime, "portfolio_foundation")
        snapshot_method = getattr(foundation, "snapshot", None)
        if not callable(snapshot_method):
            return {"available": False, "reason": "PORTFOLIO_FOUNDATION_NOT_ATTACHED"}
        try:
            snapshot = snapshot_method()
        except Exception as exc:
            logger.debug("Portfolio snapshot unavailable", exc_info=True)
            return {"available": False, "reason": "PORTFOLIO_SNAPSHOT_FAILED", "error_type": type(exc).__name__}
        prices, signals, price_time = {}, {}, None
        market_loop = _resolve_attr(runtime, "market_loop")
        loop_status = getattr(market_loop, "status", None)
        if callable(loop_status):
            try:
                status = loop_status()
                price_time = status.get("last_cycle")
                for symbol, decision in (status.get("last_signals") or {}).items():
                    if isinstance(decision, dict) and decision.get("price") is not None:
                        prices[symbol] = decision["price"]
                        signals[symbol] = {k: decision.get(k) for k in PUBLIC_SIGNAL_KEYS}
            except Exception:
                logger.debug("Market loop status unavailable for portfolio", exc_info=True)
        payload = portfolio_view.build(snapshot, prices, price_time)
        if payload.get("available"):
            # Every scanned coin with its latest real price and the loop's decision.
            payload["market"] = [{"symbol": sym, "price": str(prices[sym]), **signals[sym]} for sym in sorted(prices)]
        return payload

    # Registry v5.58 (master command §24/§26): liveness and readiness.
    @application.get("/api/liveness", response_class=JSONResponse)
    async def api_liveness(request: Request) -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)
        # The web process answered: that is all liveness claims.
        return JSONResponse(status_code=200, content={"alive": True, "at": datetime.now(UTC).isoformat()})

    @application.get("/api/readiness", response_class=JSONResponse)
    async def api_readiness(request: Request) -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)
        result = readiness.evaluate(_safe_runtime_status(application.state.atlas_runtime))
        return JSONResponse(status_code=200 if result["ready"] else 503, content=result)

    @application.get("/api/portfolio", response_class=JSONResponse)
    async def api_portfolio(request: Request) -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)
        return JSONResponse(status_code=200, content=await run_in_threadpool(_portfolio_payload))

    @application.get("/api/command-center", response_class=JSONResponse)
    async def api_command_center(request: Request) -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)
        brief = await run_in_threadpool(_command_center_brief)
        brief.pop("_proposals", None)
        brief.pop("_portfolio", None)
        return JSONResponse(status_code=200, content=brief)

    @application.get("/api/chat", response_class=JSONResponse)
    async def api_chat(request: Request, q: str = "") -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)
        brief = await run_in_threadpool(_command_center_brief)
        return JSONResponse(status_code=200, content=command_center.answer(q[:500], brief))

    @application.get(
        "/api/agent-evidence",
        response_class=JSONResponse,
    )
    async def api_agent_evidence(
        request: Request,
    ) -> JSONResponse:
        # The data behind the macro and risk votes /api/signals reports:
        # 10Y move and curve for macro, volatility regime and its p20/p80
        # for risk. Kept off /api/signals so that endpoint's published
        # shape does not change.
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )

        market_loop = _resolve_attr(
            application.state.atlas_runtime,
            "market_loop",
        )

        status_method = getattr(market_loop, "status", None)

        if not callable(status_method):
            return JSONResponse(
                status_code=503,
                content={
                    "status": "OFFLINE",
                    "reason": "MARKET_LOOP_NOT_ATTACHED",
                },
            )

        try:
            loop_status = status_method()
            evidence = (
                loop_status.get("last_agent_evidence")
                if isinstance(loop_status, dict)
                else None
            )

            if not isinstance(evidence, dict):
                evidence = {}

            return JSONResponse(
                status_code=200,
                content={
                    "status": "SUCCESS",
                    "evidence": {
                        str(symbol): _public_agent_evidence(entry)
                        for symbol, entry in evidence.items()
                    },
                },
            )

        except Exception as exc:
            logger.exception("Web agent evidence request failed")

            return JSONResponse(
                status_code=500,
                content={
                    "status": "ERROR",
                    "reason": "AGENT_EVIDENCE_FAILED",
                    "error_type": type(exc).__name__,
                },
            )

    @application.get(
        "/api/risk-accounting",
        response_class=JSONResponse,
    )
    async def api_risk_accounting(
        request: Request,
    ) -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )

        try:
            status_code, payload = await run_in_threadpool(
                _risk_accounting_payload,
                application.state.atlas_runtime,
            )
        except Exception as exc:
            logger.exception("Risk accounting panel read failed")

            return JSONResponse(
                status_code=503,
                content={
                    "available": False,
                    "reason": "PANEL_READ_FAILED",
                    "error_type": type(exc).__name__,
                },
            )

        return JSONResponse(status_code=status_code, content=payload)

    @application.get(
        "/api/system-integrity",
        response_class=JSONResponse,
    )
    async def api_system_integrity(
        request: Request,
    ) -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )

        try:
            payload = await run_in_threadpool(
                _system_integrity_payload,
                application.state.atlas_runtime,
            )
        except Exception as exc:
            logger.exception("System integrity panel read failed")

            return JSONResponse(
                status_code=503,
                content={
                    "available": False,
                    "reason": "PANEL_READ_FAILED",
                    "error_type": type(exc).__name__,
                },
            )

        return JSONResponse(status_code=200, content=payload)

    @application.get(
        "/api/execution-gates",
        response_class=JSONResponse,
    )
    async def api_execution_gates(
        request: Request,
    ) -> JSONResponse:
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )

        try:
            status_code, payload = await run_in_threadpool(
                _execution_gates_payload,
                application.state.atlas_runtime,
            )
        except Exception as exc:
            logger.exception("Execution gates panel read failed")

            return JSONResponse(
                status_code=503,
                content={
                    "available": False,
                    "reason": "PANEL_READ_FAILED",
                    "error_type": type(exc).__name__,
                },
            )

        return JSONResponse(status_code=status_code, content=payload)

    @application.get(
        "/assets/{asset_name}",
    )
    async def vendored_asset(
        request: Request,
        asset_name: str,
    ) -> Response:
        # Same guard as every other route: the page's own stylesheet and
        # scripts are served locally, never from a CDN, and never to a non-loopback
        # peer.
        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content=NON_LOOPBACK_RESPONSE,
            )

        asset = VENDORED_ASSETS.get(asset_name)

        if asset is None or not asset[0].is_file():
            return JSONResponse(
                status_code=404,
                content={"status": "NOT_FOUND", "reason": "ASSET_NOT_VENDORED"},
            )

        return FileResponse(asset[0], media_type=asset[1])

    @application.post(
        "/login",
        response_class=RedirectResponse,
    )
    async def login(request: Request) -> Response:
        """
        Temporary dashboard redirect.

        Authentication must be implemented before external exposure. Guarded
        like every other route here, plus an Origin check: POST is the one
        state-changing method this application exposes, so it is the one
        route where a mismatched Origin - not just a mismatched Host - must
        be refused.
        """

        if not is_loopback_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)

        if not is_same_origin_request(request):
            return JSONResponse(status_code=403, content=NON_LOOPBACK_RESPONSE)

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
