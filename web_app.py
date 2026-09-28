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
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from observability import panel_sources
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
# risk-accounting day rollover (registry v4.81). Mirrored as literals rather
# than imported: web_app is L5 and may not import core.execution_manager.
RISK_DAY_ROLLOVER_PREPARED = "RISK_ACCOUNTING_DAY_ROLLOVER_PREPARED"
RISK_DAY_ROLLOVER_COMMITTED = "RISK_ACCOUNTING_DAY_ROLLOVER_COMMITTED"
RISK_DAY_ROLLOVER_REFUSED = "RISK_ACCOUNTING_DAY_ROLLOVER_REFUSED"
RISK_ACCOUNTING_AGGREGATE = "risk_accounting_state"

# A refusal reason is a fixed upper-case code (registry v4.88 C3). Anything
# else read from the log is published as this placeholder, never verbatim.
REFUSAL_REASON_UNRECOGNIZED = "UNRECOGNIZED_REASON"
REFUSAL_REASON_MAX_LENGTH = 64

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


def _refusal_reason_code(value: Any) -> str:
    if (
        isinstance(value, str)
        and 0 < len(value) <= REFUSAL_REASON_MAX_LENGTH
        and value.isascii()
        and all(char.isupper() or char.isdigit() or char == "_" for char in value)
    ):
        return value

    return REFUSAL_REASON_UNRECOGNIZED


def _scan_rollover_events(
    lines: list[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    The most recent rollover PREPARED record, and whether a COMMITTED
    record points back at it; and the most recent REFUSED record, and
    whether a PREPARED record follows it in the log. Only day labels,
    timestamps and the refusal code are published; the equity figures in
    the payload stay out.
    """

    prepared: dict[str, Any] | None = None
    committed_by_cause: dict[str, str] = {}
    refused: dict[str, Any] | None = None
    refusal_superseded = False

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
            refusal_superseded = refused is not None
        elif event_type == RISK_DAY_ROLLOVER_REFUSED:
            refused = event
            refusal_superseded = False
        elif event_type == RISK_DAY_ROLLOVER_COMMITTED:
            cause = event.get("causation_id")

            if isinstance(cause, str):
                timestamp = event.get("timestamp")
                committed_by_cause[cause] = (
                    timestamp if isinstance(timestamp, str) else ""
                )

    def _text(value: Any) -> str | None:
        return value if isinstance(value, str) else None

    def _payload(event: dict[str, Any]) -> dict[str, Any]:
        payload = event.get("payload")
        return payload if isinstance(payload, dict) else {}

    latest_rollover: dict[str, Any] | None = None

    if prepared is not None:
        payload = _payload(prepared)
        event_id = prepared.get("event_id")
        committed_at = committed_by_cause.get(event_id) if isinstance(event_id, str) else None
        latest_rollover = {
            "outcome": "COMMITTED" if committed_at is not None else "PREPARED_ONLY",
            "from_accounting_day_utc": _text(payload.get("from_accounting_day_utc")),
            "to_accounting_day_utc": _text(payload.get("to_accounting_day_utc")),
            "prepared_at": _text(prepared.get("timestamp")),
            "committed_at": committed_at or None,
        }

    latest_refusal: dict[str, Any] | None = None

    if refused is not None:
        payload = _payload(refused)
        latest_refusal = {
            "reason": _refusal_reason_code(payload.get("reason")),
            "from_accounting_day_utc": _text(payload.get("from_accounting_day_utc")),
            "to_accounting_day_utc": _text(payload.get("to_accounting_day_utc")),
            "refused_at": _text(refused.get("timestamp")),
            "superseded_by_later_rollover": refusal_superseded,
        }

    return latest_rollover, latest_refusal


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
    latest_refusal: dict[str, Any] | None = None

    if not isinstance(audit_path, Path):
        rollover = {"available": False, "reason": "AUDIT_STORE_UNAVAILABLE"}
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
        else:
            latest, latest_refusal = _scan_rollover_events(lines)
            rollover = {
                "available": True,
                "latest": latest,
                "latest_refusal": latest_refusal,
                "scan_truncated": truncated,
                "scan_limit_bytes": AUDIT_SCAN_MAX_BYTES,
            }

    # Since registry v4.88 (C3) ExecutionManager writes a refused automatic
    # rollover to the audit log, so the reason is sourced from there. It is
    # reported as the current reason only while it still applies: the day
    # is behind, the refusal was for today, and no rollover followed it.
    # Refusals ExecutionManager does not audit (audit disabled, journal lock
    # unavailable, unreadable stored state) remain in the WARNING log only.
    execution = _resolve_attr(runtime, "execution")

    if getattr(execution, "audit_enabled", None) is False:
        refusal_reason_source = "AUDIT_DISABLED_NOT_RECORDED"
    elif rollover.get("available") is not True:
        refusal_reason_source = "AUDIT_LOG_UNAVAILABLE"
    else:
        refusal_reason_source = "AUDIT_LOG"

    refusal_reason = None

    if (
        refusal_reason_source == "AUDIT_LOG"
        and latest_refusal is not None
        and not latest_refusal["superseded_by_later_rollover"]
        and latest_refusal["to_accounting_day_utc"] == today.isoformat()
        and day["state"] == "BEHIND_TODAY"
    ):
        refusal_reason = latest_refusal["reason"]

    return 200, {
        "available": True,
        "today_utc": today.isoformat(),
        "accounting_day": day,
        "rollover": rollover,
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
