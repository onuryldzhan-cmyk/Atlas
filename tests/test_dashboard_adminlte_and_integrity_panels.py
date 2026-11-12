"""Coverage for the AdminLTE dashboard redesign (Part L) and its new panels
(Part M): vendored-asset integrity and serving, agent evidence, risk
accounting, system integrity and the S-3/M-2 telemetry summary.

Conventions follow tests/test_web_app_signals_and_trades.py: real-shape
fakes, leak markers planted where an allowlist must drop them, explicit
fail-closed assertions, and loopback refusal on every new route. Stores are
real ones built under tmp_path; nothing touches the repository's runtime
state.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import tools.extract_candle_age_telemetry as telemetry_tool
import web_app

from core.audit_event_store import AuditEventStore
from core.market_loop import TELEMETRY_SCHEMA_VERSION, MarketLoop
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState
from observability import panel_sources
from observability.panel_router import build_observability_router
from tests.test_backlog001_macro_risk_wiring_and_fusion import (
    MACRO_READINGS,
    RISK_READINGS,
    FusingBrain,
    OfflineFeed,
    StubMacro,
    StubRisk,
)
from web_app import create_app


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPOSITORY_ROOT / "static" / "vendor"
NON_LOOPBACK = ("203.0.113.7", 44321)

NEW_ROUTES = (
    ("/api/agent-evidence", "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"),
    ("/api/risk-accounting", "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"),
    ("/api/system-integrity", "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"),
    ("/assets/adminlte.min.css", "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"),
    ("/assets/adminlte.min.js", "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"),
    ("/assets/chart.umd.min.js", "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"),
    ("/api/observability/telemetry-summary", "OBSERVABILITY_PANEL_IS_LOCALHOST_ONLY"),
)


class _Runtime:
    def __init__(self, **attributes: object) -> None:
        for name, value in attributes.items():
            setattr(self, name, value)


def _client(runtime: object | None = None, **kwargs: object) -> TestClient:
    return TestClient(create_app(runtime=runtime), **kwargs)


# =====================================================================
# Part L: vendored AdminLTE, no CDN, guarded asset route
# =====================================================================


EXTERNAL_REFERENCE = re.compile(
    r"""<(?:script|link|img|iframe)\b[^>]*(?:src|href)\s*=\s*["']?\s*(?:https?:)?//""",
    re.IGNORECASE,
)


@pytest.mark.parametrize("path", ["/dashboard", "/"])
def test_operator_pages_reference_no_external_resource(path: str) -> None:
    body = _client().get(path).text

    assert EXTERNAL_REFERENCE.search(body) is None
    assert "cdn." not in body
    assert 'href="/assets/adminlte.min.css"' in body
    assert 'data-bs-theme="dark"' in body


# Owner-approved successor (2026-09-27, AdminLTE widget redesign) of the
# original stylesheet-only invariant "no third-party JavaScript": the page
# now loads exactly two vendored scripts, each through the loopback-guarded
# /assets allowlist, each hash-pinned in VENDORED_ASSETS.json.
VENDORED_SCRIPTS = {
    "/assets/adminlte.min.js": "adminlte-4.9.1/adminlte.min.js",
    "/assets/chart.umd.min.js": "chartjs-4.5.1/chart.umd.min.js",
}


def test_dashboard_loads_only_the_vendored_allowlisted_javascript() -> None:
    body = _client().get("/dashboard").text

    sources = re.findall(r"""<script\b[^>]*\bsrc\s*=\s*["']([^"']*)["']""", body, re.IGNORECASE)
    assert sorted(sources) == sorted(VENDORED_SCRIPTS)

    manifest = json.loads((VENDOR_DIR / "VENDORED_ASSETS.json").read_text(encoding="utf-8"))
    recorded = {path for asset in manifest["assets"] for path in asset["files"]}

    for source, relative in VENDORED_SCRIPTS.items():
        name = source.removeprefix("/assets/")
        assert web_app.VENDORED_ASSETS[name][0] == VENDOR_DIR / relative
        assert relative in recorded


def test_dashboard_pins_the_dark_theme_against_adminlte_color_mode() -> None:
    # AdminLTE's ColorMode would otherwise let a stored theme override the
    # declared dark theme; "off" disables it and its localStorage access.
    body = _client().get("/dashboard").text

    assert re.search(r'<html\b[^>]*\bdata-lte-color-mode="off"', body) is not None


def test_vendored_files_match_recorded_provenance() -> None:
    manifest = json.loads((VENDOR_DIR / "VENDORED_ASSETS.json").read_text(encoding="utf-8"))

    checked = 0

    for asset in manifest["assets"]:
        # permissive licenses only; Apache-2.0 added for lightweight-charts (v5.72, owner-approved adoption)
        assert asset["license"] in ("MIT", "Apache-2.0")

        for relative, record in asset["files"].items():
            digest = hashlib.sha256((VENDOR_DIR / relative).read_bytes()).hexdigest()
            assert digest == record["sha256"], relative
            assert record["modified"] is False
            checked += 1

    # 9 -> 12 on 2026-10-02: three.js r185 (module, core, LICENSE) vendored for the owner-approved 3D HQ.
    assert checked == 12
    assert "MIT License" in (VENDOR_DIR / "three-0.185.1" / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in (VENDOR_DIR / "adminlte-4.9.1" / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in (VENDOR_DIR / "lightweight-charts-4.2.3" / "LICENSE").read_text(encoding="utf-8")


def test_lightweight_charts_makes_no_network_request_and_runs_no_dynamic_code() -> None:
    script = (VENDOR_DIR / "lightweight-charts-4.2.3" / "lightweight-charts.standalone.production.js").read_text(encoding="utf-8")
    for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource", "importScripts",
                      "Worker(", "import(", "eval(", "new Function", "document.cookie", "window.open", "localStorage"):
        assert forbidden not in script, forbidden
    urls = set(re.findall(r"""https?://[^\s"'<>)]+""", script))
    assert {u.split("?")[0] for u in urls} <= {"http://www.w3.org/2000/svg", "https://www.apache.org/licenses/LICENSE-2.0",
                                               "https://www.tradingview.com/"}


def test_vendored_stylesheet_makes_no_network_request() -> None:
    css = (VENDOR_DIR / "adminlte-4.9.1" / "adminlte.min.css").read_text(encoding="utf-8")

    assert "@import" not in css
    assert re.search(r"url\(\s*['\"]?\s*(?:https?:)?//", css) is None


@pytest.mark.parametrize("relative", sorted(VENDORED_SCRIPTS.values()))
def test_vendored_scripts_make_no_network_request_and_run_no_dynamic_code(relative: str) -> None:
    script = (VENDOR_DIR / relative).read_text(encoding="utf-8")

    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "sendBeacon",
        "EventSource",
        "importScripts",
        "Worker(",
        "import(",
        "eval(",
        "new Function",
        "document.cookie",
        "window.open",
        'createElement("script")',
        "createElement('script')",
    ):
        assert forbidden not in script, forbidden

    urls = set(re.findall(r"""https?://[^\s"'<>)]+""", script))
    assert urls <= {
        "https://adminlte.io",
        "https://colorlib.com",
        "https://github.com/ColorlibHQ/AdminLTE/blob/master/LICENSE",
        "https://www.chartjs.org",
        "https://github.com/kurkle/color#readme",
    }


def test_vendored_files_are_exempt_from_end_of_line_conversion() -> None:
    # core.autocrlf would rewrite the vendored files as CRLF on a fresh
    # checkout and break their pinned hashes.
    attributes = (REPOSITORY_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()

    assert "static/vendor/** -text" in attributes


@pytest.mark.parametrize(("source", "relative"), sorted(VENDORED_SCRIPTS.items()))
def test_asset_route_serves_the_vendored_scripts_byte_exact(source: str, relative: str) -> None:
    response = _client().get(source)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.content == (VENDOR_DIR / relative).read_bytes()


def test_asset_route_serves_the_vendored_stylesheet_byte_exact() -> None:
    response = _client().get("/assets/adminlte.min.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert response.content == (VENDOR_DIR / "adminlte-4.9.1" / "adminlte.min.css").read_bytes()


@pytest.mark.parametrize(
    "name",
    [
        "adminlte.css",
        "LICENSE",
        "..%2Fweb_app.py",
        "VENDORED_ASSETS.json",
        "web_app.py",
        "adminlte.js",
        "chart.js",
        "chart.umd.js",
        "KURKLE_COLOR_LICENSE.md",
    ],
)
def test_asset_route_serves_only_the_allowlist(name: str) -> None:
    response = _client().get(f"/assets/{name}")

    assert response.status_code == 404
    assert "import" not in response.text


@pytest.mark.parametrize(("route", "reason"), NEW_ROUTES)
def test_every_new_route_refuses_non_loopback_peers(route: str, reason: str) -> None:
    response = _client(client=NON_LOOPBACK).get(route)

    assert response.status_code == 403
    assert response.json()["reason"] == reason


def test_existing_dashboard_contract_survives_the_redesign() -> None:
    body = _client().get("/dashboard").text

    for element_id in (
        "price-display",
        "signals-grid",
        "trade-log",
        "execution-health-panel",
        "trade-history-panel",
        "test-results-panel",
        "governance-panel",
        "risk-accounting-panel",
        "system-integrity-panel",
        "telemetry-panel",
        "known-limitations-panel",
        "price-sparkline",
    ):
        assert f'id="{element_id}"' in body

    assert "<form" not in body


def test_price_sparkline_is_fed_only_by_a_real_server_rendered_price() -> None:
    # The sparkline's only data source is the data-price attribute; it is
    # present exactly when the price provider returned a price.
    available = TestClient(create_app(price_provider=lambda symbol: 63500.5)).get("/dashboard").text
    unavailable = _client().get("/dashboard").text

    assert 'data-price="63500.5"' in available
    assert "data-price=" not in unavailable


# =====================================================================
# Part M-1: macro / risk evidence behind the votes
# =====================================================================


def test_market_loop_retains_the_evidence_of_a_real_cycle() -> None:
    loop = MarketLoop(
        brain=FusingBrain(),
        market_feed=OfflineFeed(),
        execution=None,
        symbols=["BTCUSDT"],
        macro_provider=StubMacro(MACRO_READINGS["FALLING_INVERTED"]),
        market_risk_provider=StubRisk(RISK_READINGS["HIGH"]),
    )

    with contextlib.redirect_stdout(io.StringIO()):
        loop.process_symbol("BTCUSDT")

    evidence = loop.status()["last_agent_evidence"]["BTCUSDT"]

    assert evidence["macro"]["ten_year_change_bp"] == -40
    assert evidence["macro"]["curve_spread_bp"] == -20
    assert evidence["macro"]["curve_inverted"] is True
    assert evidence["market_risk"]["regime"] == "HIGH"
    assert evidence["market_risk"]["p20"] == 1.0
    assert evidence["market_risk"]["p80"] == 2.0


def test_market_loop_records_absent_providers_as_none_not_values() -> None:
    loop = MarketLoop(
        brain=FusingBrain(),
        market_feed=OfflineFeed(),
        execution=None,
        symbols=["BTCUSDT"],
    )

    with contextlib.redirect_stdout(io.StringIO()):
        loop.process_symbol("BTCUSDT")

    assert loop.status()["last_agent_evidence"]["BTCUSDT"] == {
        "macro": None,
        "market_risk": None,
    }


def test_evidence_snapshot_is_a_copy_and_tolerates_malformed_market_data() -> None:
    source = {"macro_evidence": {"vote": "SELL"}, "market_risk_evidence": ["not", "a", "dict"]}

    snapshot = MarketLoop._agent_evidence_snapshot(source)
    source["macro_evidence"]["vote"] = "MUTATED"

    assert snapshot == {"macro": {"vote": "SELL"}, "market_risk": None}
    assert MarketLoop._agent_evidence_snapshot(None) == {"macro": None, "market_risk": None}


EVIDENCE_LEAK_MARKER = "LEAK-EVIDENCE-INTERNAL"


class _EvidenceLoop:
    def status(self) -> dict:
        return {
            "last_signals": {},
            "last_agent_evidence": {
                "BTCUSDT": {
                    "macro": {
                        "source": EVIDENCE_LEAK_MARKER,
                        "observed_date": "2026-09-24",
                        "ten_year_change_bp": 52,
                        "curve_spread_bp": 31,
                        "curve_inverted": False,
                        "move": "RISING",
                        "vote": "SELL",
                        "reason": "OK",
                        "internal": {"nested": EVIDENCE_LEAK_MARKER},
                    },
                    "market_risk": {
                        "source": EVIDENCE_LEAK_MARKER,
                        "regime": "NEUTRAL",
                        "realized_volatility": 1.5,
                        "p20": 1.0,
                        "p80": 2.0,
                        "reference_windows": 168,
                        "vote": "HOLD",
                        "reason": {"nested": EVIDENCE_LEAK_MARKER},
                    },
                },
                "ETHUSDT": {"macro": None, "market_risk": None},
            },
        }


def test_agent_evidence_endpoint_projects_the_allowlist_only() -> None:
    response = _client(_Runtime(market_loop=_EvidenceLoop())).get("/api/agent-evidence")

    assert response.status_code == 200
    assert EVIDENCE_LEAK_MARKER not in response.text

    evidence = response.json()["evidence"]

    assert evidence["BTCUSDT"]["macro"] == {
        "observed_date": "2026-09-24",
        "ten_year_change_bp": 52,
        "curve_spread_bp": 31,
        "curve_inverted": False,
        "move": "RISING",
        "vote": "SELL",
        "reason": "OK",
    }
    # AgentFusion's "risk" agent reads the "market_risk" evidence; a
    # non-scalar value under an allowed key is dropped, not stringified.
    assert evidence["BTCUSDT"]["risk"] == {
        "regime": "NEUTRAL",
        "realized_volatility": 1.5,
        "p20": 1.0,
        "p80": 2.0,
        "reference_windows": 168,
        "vote": "HOLD",
    }
    assert evidence["ETHUSDT"] == {"macro": None, "risk": None}


def test_agent_evidence_fails_closed_without_a_market_loop() -> None:
    response = _client(_Runtime(market_loop=None)).get("/api/agent-evidence")

    assert response.status_code == 503
    assert response.json()["reason"] == "MARKET_LOOP_NOT_ATTACHED"


def test_agent_evidence_hides_exception_text() -> None:
    class _Broken:
        def status(self) -> dict:
            raise RuntimeError(EVIDENCE_LEAK_MARKER)

    response = _client(_Runtime(market_loop=_Broken())).get("/api/agent-evidence")

    assert response.status_code == 500
    assert response.json()["error_type"] == "RuntimeError"
    assert EVIDENCE_LEAK_MARKER not in response.text


def test_signals_endpoint_shape_is_unchanged_by_the_evidence_store() -> None:
    response = _client(_Runtime(market_loop=_EvidenceLoop())).get("/api/signals")

    assert response.json() == {"status": "SUCCESS", "signals": {}}


# =====================================================================
# Part M-2: risk accounting panel
# =====================================================================


POLICY_VERSION = "risk-policy-test-v1"
EQUITY_LEAK = "98765.4321"


class _Policy:
    version = POLICY_VERSION


def _risk_runtime(tmp_path: Path, *, day: date | None) -> _Runtime:
    store = JsonRiskStateStore(tmp_path / "risk_accounting_state.json")

    if day is not None:
        store.initialize(
            RestoredRiskState(
                day,
                Decimal("0"),
                Decimal(EQUITY_LEAK),
                Decimal(EQUITY_LEAK),
                POLICY_VERSION,
            )
        )

    audit = AuditEventStore(tmp_path / "audit" / "events.jsonl", fsync_enabled=False)

    return _Runtime(risk_state_store=store, risk_policy=_Policy(), audit_store=audit)


def _append_rollover(audit: AuditEventStore, from_day: date, to_day: date, *, commit: bool) -> None:
    prepared = audit.append(
        event_type=web_app.RISK_DAY_ROLLOVER_PREPARED,
        source="ExecutionManager",
        aggregate_type="risk_accounting_state",
        aggregate_id=to_day.isoformat(),
        payload={
            "mode": "PAPER",
            "from_accounting_day_utc": from_day.isoformat(),
            "to_accounting_day_utc": to_day.isoformat(),
            "current_equity": EQUITY_LEAK,
        },
        correlation_id=to_day.isoformat(),
    )

    if commit:
        audit.append(
            event_type=web_app.RISK_DAY_ROLLOVER_COMMITTED,
            source="ExecutionManager",
            aggregate_type="risk_accounting_state",
            aggregate_id=to_day.isoformat(),
            payload={"mode": "PAPER", "new_state": {"current_equity": EQUITY_LEAK}},
            correlation_id=to_day.isoformat(),
            causation_id=prepared.event_id,
        )


def _today() -> date:
    return datetime.now(UTC).date()


def test_risk_accounting_reports_current_day_and_committed_rollover(tmp_path: Path) -> None:
    today = _today()
    runtime = _risk_runtime(tmp_path, day=today)
    _append_rollover(runtime.audit_store, today - timedelta(days=2), today - timedelta(days=1), commit=True)
    _append_rollover(runtime.audit_store, today - timedelta(days=1), today, commit=True)

    response = _client(runtime).get("/api/risk-accounting")
    payload = response.json()

    assert response.status_code == 200
    assert payload["accounting_day"] == {"state": "CURRENT", "accounting_day_utc": today.isoformat()}
    latest = payload["rollover"]["latest"]
    assert latest["outcome"] == "COMMITTED"
    assert latest["from_accounting_day_utc"] == (today - timedelta(days=1)).isoformat()
    assert latest["to_accounting_day_utc"] == today.isoformat()
    assert latest["committed_at"] is not None
    assert payload["rollover"]["scan_truncated"] is False
    assert EQUITY_LEAK not in response.text


def _append_rollover_refusal(
    audit: AuditEventStore, reason: str, from_day: date, to_day: date,
) -> None:
    audit.append(
        event_type=web_app.RISK_DAY_ROLLOVER_REFUSED,
        source="ExecutionManager",
        aggregate_type="risk_accounting_state",
        aggregate_id=to_day.isoformat(),
        payload={
            "mode": "PAPER",
            "reason": reason,
            "from_accounting_day_utc": from_day.isoformat(),
            "to_accounting_day_utc": to_day.isoformat(),
        },
        correlation_id=to_day.isoformat(),
    )


def test_risk_accounting_reports_no_refusal_when_none_recorded(tmp_path: Path) -> None:
    payload = _client(_risk_runtime(tmp_path, day=_today())).get("/api/risk-accounting").json()

    assert payload["refusal_reason"] is None
    assert payload["refusal_reason_source"] == "NO_REFUSAL_RECORDED"


def test_risk_accounting_surfaces_the_real_refusal_reason_from_the_audit_trail(
    tmp_path: Path,
) -> None:
    today = _today()
    stale = today - timedelta(days=1)
    runtime = _risk_runtime(tmp_path, day=stale)
    _append_rollover_refusal(runtime.audit_store, "UNRESOLVED_JOURNAL_ENTRY", stale, today)

    payload = _client(runtime).get("/api/risk-accounting").json()

    assert payload["refusal_reason"] == "UNRESOLVED_JOURNAL_ENTRY"
    assert payload["refusal_reason_source"] == "AUDIT_TRAIL"


def test_risk_accounting_ignores_a_refusal_for_an_already_resolved_transition(
    tmp_path: Path,
) -> None:
    today = _today()
    # The state has since rolled forward to today, so a refusal logged for
    # an earlier transition must not be shown as if it still applies.
    runtime = _risk_runtime(tmp_path, day=today)
    _append_rollover_refusal(
        runtime.audit_store,
        "UNRESOLVED_JOURNAL_ENTRY",
        today - timedelta(days=2),
        today - timedelta(days=1),
    )

    payload = _client(runtime).get("/api/risk-accounting").json()

    assert payload["refusal_reason"] is None
    assert payload["refusal_reason_source"] == "NO_REFUSAL_RECORDED"


def test_risk_accounting_reports_a_stale_day_and_no_rollover_yet(tmp_path: Path) -> None:
    stale = _today() - timedelta(days=3)

    payload = _client(_risk_runtime(tmp_path, day=stale)).get("/api/risk-accounting").json()

    assert payload["accounting_day"] == {"state": "BEHIND_TODAY", "accounting_day_utc": stale.isoformat()}
    assert payload["rollover"]["available"] is True
    assert payload["rollover"]["latest"] is None


def test_risk_accounting_reports_prepared_without_commit(tmp_path: Path) -> None:
    today = _today()
    runtime = _risk_runtime(tmp_path, day=today - timedelta(days=1))
    _append_rollover(runtime.audit_store, today - timedelta(days=1), today, commit=False)

    latest = _client(runtime).get("/api/risk-accounting").json()["rollover"]["latest"]

    assert latest["outcome"] == "PREPARED_ONLY"
    assert latest["committed_at"] is None


def test_risk_accounting_ignores_a_commit_for_a_different_prepare(tmp_path: Path) -> None:
    today = _today()
    runtime = _risk_runtime(tmp_path, day=today)
    _append_rollover(runtime.audit_store, today - timedelta(days=2), today - timedelta(days=1), commit=True)
    _append_rollover(runtime.audit_store, today - timedelta(days=1), today, commit=False)

    latest = _client(runtime).get("/api/risk-accounting").json()["rollover"]["latest"]

    assert latest["to_accounting_day_utc"] == today.isoformat()
    assert latest["outcome"] == "PREPARED_ONLY"


def test_risk_accounting_missing_state_is_reported_not_invented(tmp_path: Path) -> None:
    payload = _client(_risk_runtime(tmp_path, day=None)).get("/api/risk-accounting").json()

    assert payload["accounting_day"] == {"state": "RISK_STATE_MISSING", "accounting_day_utc": None}


def test_risk_accounting_policy_mismatch_is_invalid_without_detail(tmp_path: Path) -> None:
    runtime = _risk_runtime(tmp_path, day=_today())

    class _OtherPolicy:
        version = "some-other-policy"

    runtime.risk_policy = _OtherPolicy()

    response = _client(runtime).get("/api/risk-accounting")

    assert response.json()["accounting_day"] == {
        "state": "RISK_STATE_INVALID",
        "accounting_day_utc": None,
        "error_type": "ValueError",
    }
    assert "mismatch" not in response.text


def test_risk_accounting_bounded_scan_drops_the_partial_first_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = _today()
    runtime = _risk_runtime(tmp_path, day=today)
    _append_rollover(runtime.audit_store, today - timedelta(days=1), today, commit=True)
    size = runtime.audit_store.file_path.stat().st_size

    # A window smaller than the file cuts into the PREPARED record, so the
    # rollover must not be reported from a fragment.
    monkeypatch.setattr(web_app, "AUDIT_SCAN_MAX_BYTES", size - 10)

    rollover = _client(runtime).get("/api/risk-accounting").json()["rollover"]

    assert rollover["scan_truncated"] is True
    assert rollover["latest"] is None


def test_risk_accounting_fails_closed_without_runtime_or_store() -> None:
    assert _client().get("/api/risk-accounting").status_code == 503

    response = _client(_Runtime(risk_state_store=None)).get("/api/risk-accounting")

    assert response.status_code == 503
    assert response.json()["reason"] == "RISK_STATE_STORE_UNAVAILABLE"


# =====================================================================
# Part M-3: system integrity panel
# =====================================================================


VENUE_LEAK_MARKER = "LEAK-VENUE-SOURCE-ENDPOINT"


class _Report:
    def to_dict(self) -> dict:
        return {
            "status": "STALE",
            "venue": "binance_global",
            "schema_version": "1",
            "symbol_count": 5,
            "source": VENUE_LEAK_MARKER,
            "source_version": VENUE_LEAK_MARKER,
            "observed_at": "2026-09-01T00:00:00+00:00",
            "age_seconds": 2_160_000,
            "maximum_age_seconds": 604_800,
            "evaluated_at": "2026-09-26T00:00:00+00:00",
            "reason": "VENUE_RULES_STALE",
        }


class _Execution:
    def assess_venue_rule_freshness(self) -> _Report:
        return _Report()


def test_system_integrity_reports_venue_freshness_through_the_allowlist() -> None:
    response = _client(_Runtime(execution=_Execution())).get("/api/system-integrity")
    venue = response.json()["venue_rules"]

    assert response.status_code == 200
    assert VENUE_LEAK_MARKER not in response.text
    assert venue == {
        "available": True,
        "status": "STALE",
        "venue": "binance_global",
        "observed_at": "2026-09-01T00:00:00+00:00",
        "age_seconds": 2_160_000,
        "maximum_age_seconds": 604_800,
        "evaluated_at": "2026-09-26T00:00:00+00:00",
        "reason": "VENUE_RULES_STALE",
    }


def test_system_integrity_registry_version_is_the_real_chain_head() -> None:
    resolved = panel_sources.resolve_current_registry()
    registry = _client().get("/api/system-integrity").json()["registry"]

    assert resolved["available"] is True
    assert registry == {
        "available": True,
        "version": resolved["payload"]["schema_version"],
        "file": resolved["head"],
    }


def test_system_integrity_lists_the_known_limitations_in_plain_language() -> None:
    limitations = _client().get("/api/system-integrity").json()["known_limitations"]

    ids = {item["id"] for item in limitations}

    assert {"EXEC-MGR-COMMIT-UNKNOWN-GAP-001", "DAILY-LOSS-LIMIT-WIRING"} <= ids

    for item in limitations:
        assert set(item) == {"id", "status", "registry_reference", "summary"}
        assert item["summary"] and item["registry_reference"]


def test_system_integrity_venue_rules_fail_closed() -> None:
    assert _client().get("/api/system-integrity").json()["venue_rules"] == {
        "available": False,
        "reason": "RUNTIME_NOT_ATTACHED",
    }

    class _Raising:
        def assess_venue_rule_freshness(self) -> None:
            raise RuntimeError(VENUE_LEAK_MARKER)

    response = _client(_Runtime(execution=_Raising())).get("/api/system-integrity")

    assert response.json()["venue_rules"] == {
        "available": False,
        "reason": "VENUE_RULES_ASSESSMENT_FAILED",
        "error_type": "RuntimeError",
    }
    assert VENUE_LEAK_MARKER not in response.text


# =====================================================================
# Part M-4 / M-5: S-3 / M-2 telemetry summary
# =====================================================================


def _telemetry_record(symbol: str, cycle: int, duration: float, age: float | None, status: str) -> str:
    return json.dumps(
        {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "symbol": symbol,
            "cycle": cycle,
            "cycle_duration_seconds": duration,
            "candle_age_seconds": age,
            "candle_age_status": status,
        }
    )


def _write_telemetry(log_directory: Path) -> Path:
    lines = [
        _telemetry_record("BTCUSDT", 1, 2.5, 4.0, "MEASURED"),
        _telemetry_record("ETHUSDT", 1, 2.5, 6.0, "MEASURED"),
        _telemetry_record("BTCUSDT", 2, 3.5, 8.0, "MEASURED"),
        _telemetry_record("ETHUSDT", 2, 3.5, None, "NO_CANDLE"),
        "not json",
        # cycle goes backwards: a second run
        _telemetry_record("BTCUSDT", 1, 9.0, 12.0, "MEASURED"),
    ]
    path = log_directory / "market_loop_telemetry.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _artifact_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "reports" / "observability").mkdir(parents=True)
    return root


def _save_tool_report(root: Path, log_directory: Path, *, encoding: str = "utf-8") -> dict:
    """What the documented command does: run the real tool, save its --json."""

    stdout = io.StringIO()

    with contextlib.redirect_stdout(stdout):
        exit_code = telemetry_tool.main(["--json", "--log-directory", str(log_directory)])

    (root / panel_sources.TELEMETRY_SUMMARY_ARTIFACT_RELPATH).write_text(
        stdout.getvalue(), encoding=encoding
    )

    return {"exit_code": exit_code, "report": json.loads(stdout.getvalue())}


def test_telemetry_summary_reuses_the_tool_numbers_exactly(tmp_path: Path) -> None:
    root = _artifact_root(tmp_path)
    _write_telemetry(tmp_path)
    report = _save_tool_report(root, tmp_path)["report"]

    summary = panel_sources.read_telemetry_summary(root)

    assert summary["available"] is True and summary["has_data"] is True
    assert summary["parsed_records"] == 5
    assert summary["skipped_lines"] == 1
    assert summary["run_count"] == 2

    overall_age = report["candle_age_s3"]["overall_measured_distribution"]
    for key in ("count", "p50", "p90", "p95", "p99", "max"):
        assert summary["candle_age_seconds"][key] == overall_age[key]

    assert summary["cycle_duration_seconds"]["max"] == report["cycle_duration_m2"]["overall"]["max"]
    assert summary["cycle_duration_latest_run_seconds"] == {
        key: value
        for key, value in report["cycle_duration_m2"]["per_run"]["1"].items()
        if key in panel_sources.TELEMETRY_DISTRIBUTION_KEYS
    }
    assert summary["candle_age_status_counts"] == {"MEASURED": 4, "NO_CANDLE": 1}
    assert summary["artifact_written_at"]
    assert str(tmp_path) not in json.dumps(summary)


def test_telemetry_summary_reads_a_powershell_utf16_artifact(tmp_path: Path) -> None:
    root = _artifact_root(tmp_path)
    _write_telemetry(tmp_path)
    _save_tool_report(root, tmp_path, encoding="utf-16")

    assert panel_sources.read_telemetry_summary(root)["has_data"] is True


def test_telemetry_summary_missing_artifact_is_no_data_with_the_command(tmp_path: Path) -> None:
    summary = panel_sources.read_telemetry_summary(_artifact_root(tmp_path))

    assert summary["available"] is False
    assert summary["reason"] == "ARTIFACT_MISSING"
    assert summary["generate_command"] == panel_sources.TELEMETRY_GENERATE_COMMAND
    assert "candle_age_seconds" not in summary


def test_telemetry_summary_empty_artifact_is_no_data(tmp_path: Path) -> None:
    root = _artifact_root(tmp_path)
    (root / panel_sources.TELEMETRY_SUMMARY_ARTIFACT_RELPATH).write_text("", encoding="utf-8")

    assert panel_sources.read_telemetry_summary(root)["reason"] == "ARTIFACT_EMPTY"


def test_telemetry_summary_empty_log_is_no_data_not_zeros(tmp_path: Path) -> None:
    root = _artifact_root(tmp_path)
    (tmp_path / "market_loop_telemetry.jsonl").write_text("", encoding="utf-8")
    _save_tool_report(root, tmp_path)

    summary = panel_sources.read_telemetry_summary(root)

    assert summary["available"] is True
    assert summary["has_data"] is False
    assert summary["reason"] == "NO_RECORDS"
    assert "candle_age_seconds" not in summary


def test_telemetry_summary_missing_log_is_no_data(tmp_path: Path) -> None:
    root = _artifact_root(tmp_path)
    _save_tool_report(root, tmp_path)

    summary = panel_sources.read_telemetry_summary(root)

    assert (summary["has_data"], summary["reason"]) == (False, "LOG_FILE_NOT_FOUND")


def test_telemetry_summary_unconfigured_directory_is_no_data() -> None:
    report = {"log_path": None, "log_file_found": False, "parse": {}, "candle_age_s3": {}, "cycle_duration_m2": {}}

    assert panel_sources.summarize_telemetry_report(report) == {
        "available": True,
        "has_data": False,
        "reason": "LOG_DIRECTORY_NOT_CONFIGURED",
    }


def test_telemetry_tool_refusal_publishes_the_code_not_the_path(tmp_path: Path) -> None:
    root = _artifact_root(tmp_path)
    result = _save_tool_report(root, tmp_path / "PRIVATE-PATH-MARKER")

    summary = panel_sources.read_telemetry_summary(root)

    assert result["exit_code"] == 1
    assert summary["available"] is False
    assert summary["reason"] == "TELEMETRY_TOOL_REFUSED"
    assert summary["tool_error"] == "LogDirectoryNotFound"
    assert "PRIVATE-PATH-MARKER" not in json.dumps(summary)


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"not json", "ARTIFACT_MALFORMED"),
        (b"[1, 2]", "TELEMETRY_REPORT_MALFORMED"),
        (b"\xff\xfe\x00", "ARTIFACT_MALFORMED"),
        (b'{"log_path": "x", "parse": []}', "TELEMETRY_REPORT_MALFORMED"),
    ],
)
def test_telemetry_summary_fails_closed_on_a_malformed_artifact(
    tmp_path: Path,
    content: bytes,
    reason: str,
) -> None:
    root = _artifact_root(tmp_path)
    (root / panel_sources.TELEMETRY_SUMMARY_ARTIFACT_RELPATH).write_bytes(content)

    summary = panel_sources.read_telemetry_summary(root)

    assert summary["available"] is False
    assert summary["reason"] == reason


def test_telemetry_summary_refuses_an_oversized_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _artifact_root(tmp_path)
    (root / panel_sources.TELEMETRY_SUMMARY_ARTIFACT_RELPATH).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(panel_sources, "MAX_ARTIFACT_BYTES", 1)

    assert panel_sources.read_telemetry_summary(root)["reason"] == "ARTIFACT_TOO_LARGE"


def test_telemetry_route_serves_the_artifact_and_503s_without_it(tmp_path: Path) -> None:
    root = _artifact_root(tmp_path)
    application = FastAPI()
    application.include_router(build_observability_router(repository_root=root))
    client = TestClient(application)

    missing = client.get("/api/observability/telemetry-summary")
    assert missing.status_code == 503
    assert missing.json()["reason"] == "ARTIFACT_MISSING"

    _write_telemetry(tmp_path)
    _save_tool_report(root, tmp_path)

    present = client.get("/api/observability/telemetry-summary")
    assert present.status_code == 200
    assert present.json()["has_data"] is True
