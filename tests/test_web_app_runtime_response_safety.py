"""Discriminating coverage for the web surface under a *real* runtime shape.

The existing ``tests/test_web_app_contract.py`` fakes exercise a brain whose
``process()`` returns an already-flat, already-JSON-native dict. That shape
can never reproduce the two defects covered here:

A1  ``ai.core.atlas_brain.AtlasBrain.analyze_and_decide`` returns a
    ``core.decision.Decision`` dataclass, which ``core/brain.py`` stores
    verbatim at ``analysis["result"]``. Serialising the brain result
    wholesale therefore raises ``TypeError`` inside ``JSONResponse`` the
    instant a real runtime is attached, and the ``analysis`` subtree also
    carries unsanitised intelligence internals (world analysis output,
    brain session id, confidence explanation, phase-5 audit record). Only
    the ``decision`` key is sanitised, by ``DecisionAdapter.convert``.

C2/C3/C5
    The dashboard template must render the server state ``web_app`` already
    passes into its context instead of hardcoding an "online" claim, must
    ask for the same symbol ``/api/analysis`` defaults to, and the root page
    must not present a login form that authenticates nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from fastapi.testclient import TestClient

from core.decision import Decision, DecisionAction, RiskLevel
from core.decision_adapter import DecisionAdapter
from web_app import create_app


# Markers planted only inside the unsanitised ``analysis`` subtree. None of
# them is reachable through ``DecisionAdapter.convert``, so any appearance in
# a response body is a genuine leak of intelligence internals.
WORLD_ANALYSIS_MARKER = "LEAK-WORLD-ANALYSIS-REGIME-NARRATIVE"
SESSION_ID_MARKER = "LEAK-BRAIN-SESSION-0f9c1d"
CONFIDENCE_EXPLANATION_MARKER = "LEAK-CONFIDENCE-EXPLANATION-CHAIN"
AUDIT_RECORD_MARKER = "LEAK-PHASE5-AUDIT-RECORD"

LEAK_MARKERS = (
    WORLD_ANALYSIS_MARKER,
    SESSION_ID_MARKER,
    CONFIDENCE_EXPLANATION_MARKER,
    AUDIT_RECORD_MARKER,
)

# Every key the HTTP response is allowed to expose. ``analysis`` is
# deliberately absent: it is the unsanitised half of the brain result.
ALLOWED_RESPONSE_KEYS = frozenset(
    {
        "status",
        "symbol",
        "time",
        "decision",
        "reason",
    }
)


class RealShapeBrain:
    """A brain whose ``process()`` mirrors ``core/brain.py`` exactly.

    ``decision`` is the sanitised ``DecisionAdapter`` output; ``analysis``
    holds the raw ``Decision`` dataclass plus intelligence internals, as the
    production brain genuinely returns.
    """

    def __init__(self) -> None:
        self.received: list[dict[str, object]] = []

    def process(
        self,
        observation: dict[str, object],
    ) -> dict[str, object]:
        self.received.append(observation)

        symbol = str(observation["symbol"])
        timestamp = datetime.now(UTC).isoformat()

        decision = Decision(
            action=DecisionAction.BUY,
            symbol=symbol,
            confidence=71.5,
            reasoning="momentum continuation",
            risk_level=RiskLevel.MEDIUM,
        )

        return {
            "status": "SUCCESS",
            "symbol": symbol,
            "decision": DecisionAdapter.convert(decision),
            "analysis": {
                "status": "SUCCESS",
                "symbol": symbol,
                # The real, unserialisable dataclass instance.
                "result": decision,
                "world_analysis": {
                    "regime": WORLD_ANALYSIS_MARKER,
                },
                "brain_session_id": SESSION_ID_MARKER,
                "confidence_explanation": CONFIDENCE_EXPLANATION_MARKER,
                "phase5_proposal": {
                    "audit_record": AUDIT_RECORD_MARKER,
                },
                "timestamp": timestamp,
            },
            "time": timestamp,
        }


class RealShapeRuntime:
    def __init__(self) -> None:
        self.brain = RealShapeBrain()

    def health(self) -> dict[str, object]:
        return {
            "healthy": True,
            "state": "HEALTHY",
        }


def _client() -> TestClient:
    return TestClient(
        create_app(
            runtime=RealShapeRuntime(),
        )
    )


# =====================================================================
# A1
# =====================================================================


def test_analysis_endpoint_survives_a_real_decision_dataclass() -> None:
    """A1: the endpoint must not 500 when analysis carries a Decision."""

    response = _client().get(
        "/api/analysis",
        params={"symbol": "btcusdt"},
    )

    assert response.status_code != 500, (
        "/api/analysis returned 500 under a real runtime shape:\n"
        f"{response.text}"
    )
    assert response.status_code == 200


def test_analysis_endpoint_does_not_leak_unsanitised_analysis() -> None:
    """A1: no unsanitised intelligence internal may reach the client."""

    response = _client().get(
        "/api/analysis",
        params={"symbol": "btcusdt"},
    )

    body = response.text

    for marker in LEAK_MARKERS:
        assert marker not in body, (
            f"unsanitised analysis content leaked into the response: {marker}"
        )

    payload = response.json()

    assert "analysis" not in payload
    assert set(payload) <= ALLOWED_RESPONSE_KEYS, (
        "unexpected keys in /api/analysis response: "
        f"{sorted(set(payload) - ALLOWED_RESPONSE_KEYS)}"
    )


def test_analysis_endpoint_still_returns_the_sanitised_decision() -> None:
    """A1 must drop ``analysis`` without dropping the useful decision.

    The decision itself is now projected onto web_app.PUBLIC_DECISION_KEYS
    (action, confidence, risk_level) rather than published whole, so the
    instrument is read from the response's own ``symbol`` field. The
    decision's ``symbol`` was redundant with it: both name the symbol the
    request asked about.
    """

    payload = (
        _client()
        .get(
            "/api/analysis",
            params={"symbol": "btcusdt"},
        )
        .json()
    )

    assert payload["status"] == "SUCCESS"
    assert payload["symbol"] == "BTCUSDT"
    assert payload["decision"]["action"] == "BUY"
    assert payload["decision"]["risk_level"] == "MEDIUM"
    assert isinstance(payload["time"], str)


class OfflineBrain:
    """The fail-closed shape: no decision, and a reason the UI can show."""

    def process(
        self,
        observation: dict[str, object],
    ) -> dict[str, object]:
        return {
            "status": "OFFLINE",
            "reason": "BRAIN_NOT_RUNNING",
            "symbol": observation["symbol"],
            "decision": None,
            "analysis": {
                "status": "OFFLINE",
                "reason": "BRAIN_NOT_RUNNING",
                "world_analysis": WORLD_ANALYSIS_MARKER,
            },
            "time": datetime.now(UTC).isoformat(),
        }


class ErrorBrain:
    """core/brain.py's own except branch: carries a free-form error string."""

    def process(
        self,
        observation: dict[str, object],
    ) -> dict[str, object]:
        return {
            "status": "ERROR",
            "symbol": observation["symbol"],
            "decision": None,
            "error_type": "RuntimeError",
            "error": SESSION_ID_MARKER,
            "time": datetime.now(UTC).isoformat(),
        }


class RaisingBrain:
    def process(
        self,
        observation: dict[str, object],
    ) -> dict[str, object]:
        raise RuntimeError(AUDIT_RECORD_MARKER)


class _BrainRuntime:
    def __init__(self, brain: object) -> None:
        self.brain = brain

    def health(self) -> dict[str, object]:
        return {"healthy": True, "state": "HEALTHY"}


def test_offline_brain_result_is_also_key_restricted() -> None:
    """The allowlist must hold on the non-SUCCESS branches too."""

    response = TestClient(
        create_app(runtime=_BrainRuntime(OfflineBrain()))
    ).get("/api/analysis")

    assert response.status_code == 503
    assert WORLD_ANALYSIS_MARKER not in response.text

    payload = response.json()

    assert set(payload) <= ALLOWED_RESPONSE_KEYS
    assert payload["decision"] is None
    # C4 needs a reason to render; it must survive the allowlist.
    assert payload["reason"] == "BRAIN_NOT_RUNNING"


def test_brain_error_string_never_reaches_the_client() -> None:
    response = TestClient(
        create_app(runtime=_BrainRuntime(ErrorBrain()))
    ).get("/api/analysis")

    assert SESSION_ID_MARKER not in response.text
    assert set(response.json()) <= ALLOWED_RESPONSE_KEYS


def test_raised_exception_message_never_reaches_the_client() -> None:
    """A raised exception's text is a log detail, never a response body."""

    response = TestClient(
        create_app(runtime=_BrainRuntime(RaisingBrain()))
    ).get("/api/analysis")

    assert response.status_code == 500

    payload = response.json()

    assert AUDIT_RECORD_MARKER not in response.text
    assert payload["reason"] == "ANALYSIS_FAILED"
    # Only the exception's class name may be published, never its message.
    assert payload["error_type"] == "RuntimeError"
    assert "error" not in payload


# =====================================================================
# A6-guard
# =====================================================================


def test_runtime_endpoints_refuse_non_loopback_clients() -> None:
    client = TestClient(
        create_app(runtime=RealShapeRuntime()),
        client=("203.0.113.7", 44321),
    )

    for route in ("/api/health", "/api/status", "/api/analysis"):
        response = client.get(route)

        assert response.status_code == 403, route
        assert (
            response.json()["reason"] == "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"
        ), route


# =====================================================================
# /api/status
# =====================================================================


class RealShapeRuntimeWithStatus(RealShapeRuntime):
    """RealShapeRuntime plus a status() in AtlasApplication.status()'s shape.

    Carries the operator-only detail the real status() carries - a raw
    halt_reason in execution.operational_state, and health()'s classified
    execution_halt_reason - so the route's allowlist is exercised against
    the shape it is written for.
    """

    def status(self) -> dict[str, object]:
        return {
            "application": {"name": "AtlasApplication", "version": "13.0"},
            "execution": {
                "name": "ExecutionManager",
                "operational_state": {
                    "execution_halted": True,
                    "recovery_required": True,
                    "halt_reason": "SOURCE_DISAGREEMENT",
                },
            },
            "health": {
                "healthy": False,
                "execution_halted": True,
                "execution_halt_reason": "SOURCE_DISAGREEMENT",
            },
        }


def test_status_endpoint_publishes_the_allowlisted_status() -> None:
    """The halt reason appears only as health()'s classified code."""

    response = TestClient(
        create_app(runtime=RealShapeRuntimeWithStatus()),
    ).get("/api/status")

    assert response.status_code == 200

    payload = response.json()

    assert payload["application"] == {
        "name": "AtlasApplication",
        "version": "13.0",
    }
    assert payload["health"]["execution_halt_reason"] == "SOURCE_DISAGREEMENT"
    assert payload["execution"]["operational_state"] == {
        "execution_halted": True,
        "recovery_required": True,
    }


# Planted in every free-form field AtlasApplication.status() can carry. Any
# of them in the /api/status body is a leak.
STATUS_SECRET_MARKERS = (
    "EXEC-SECRET-0001",
    "C:\\secret\\path",
    "secret",
    "Traceback",
    "hunter2",
)


def test_status_endpoint_never_publishes_a_planted_secret(
    tmp_path: Path,
) -> None:
    """The /api/status counterpart of test_health_never_publishes_the_halt_reason.

    Built on a real AtlasApplication (isolated state directory), so the
    body under test is the real status() shape: a raw halt_reason
    embedding an execution id in the execution service's status, and a
    real error record - str(error) carrying a file path, and the traceback
    captured while it was being handled.
    """

    from core.application import AtlasApplication

    class _HaltedExecution:
        def status(self) -> dict[str, object]:
            return {
                "name": "ExecutionManager",
                "running": True,
                "operational_state": {
                    "execution_halted": True,
                    "recovery_required": True,
                    "halt_reason": (
                        "FINANCIAL_APPLIED_AUTHORITY_CORRUPT: "
                        "execution_id=EXEC-SECRET-0001 line=42"
                    ),
                    "last_audit_failure": {
                        "stage": "PRE_EXECUTION",
                        "request_id": "EXEC-SECRET-0001",
                        "error_type": "OSError",
                        "error": "C:\\secret\\path is locked",
                    },
                },
                "errors": {
                    "count": 1,
                    "latest": {
                        "phase": "execute",
                        "type": "RuntimeError",
                        "error": "exchange said: password=hunter2",
                        "traceback": "Traceback (most recent call last): ...",
                    },
                },
            }

    application = AtlasApplication(state_directory=tmp_path / "state")
    application.execution = _HaltedExecution()

    try:
        raise OSError("cannot open C:\\secret\\path\\ledger.json")
    except OSError as error:
        application._record_error(phase="startup", error=error)

    # The console's status() still carries all of it, unchanged.
    raw = repr(application.status())
    assert "EXEC-SECRET-0001" in raw
    assert "Traceback" in raw

    response = TestClient(
        create_app(runtime=application),
    ).get("/api/status")

    assert response.status_code == 200

    for marker in STATUS_SECRET_MARKERS:
        assert marker not in response.text, marker

    payload = response.json()

    assert payload["health"]["execution_halt_reason"] == (
        "EXECUTION_HALT_REASON_UNCLASSIFIED"
    )
    assert payload["errors"] == {
        "count": 1,
        "latest": {
            "category": "startup",
            "type": "OSError",
            "time": payload["errors"]["latest"]["time"],
        },
    }
    assert payload["execution"]["errors"]["latest"] == {
        "category": "execute",
        "type": "RuntimeError",
        "time": None,
    }
    assert "halt_reason" not in payload["execution"]["operational_state"]
    assert "last_audit_failure" not in payload["execution"]["operational_state"]


def test_status_endpoint_drops_unknown_keys_and_unsafe_strings() -> None:
    """Fail closed: nothing outside the allowlist, no free text inside it."""

    class _PlantedEverywhere:
        def status(self) -> dict[str, object]:
            return {
                "application": {
                    "name": "EXEC-SECRET-0001 C:\\secret\\path",
                    "exchange": "https://secret.example/api",
                    "created_at": "Traceback (most recent call last)",
                    "unknown_field": "hunter2",
                },
                "execution": {
                    "operational_state": {
                        "halt_reason": "EXEC-SECRET-0001",
                        "audit_runtime_state": "C:\\secret\\path",
                    },
                    "venue_rules": {"source": "C:\\secret\\path"},
                },
                "health": {"execution_halt_reason": "EXEC-SECRET-0001"},
                "market_loop": {
                    "last_executions": {"BTCUSDT": "EXEC-SECRET-0001"},
                    "symbols": ["BTCUSDT", "C:\\secret\\path"],
                },
                "debug_dump": {"traceback": "Traceback ... hunter2"},
            }

    response = TestClient(
        create_app(runtime=_PlantedEverywhere()),
    ).get("/api/status")

    assert response.status_code == 200

    for marker in STATUS_SECRET_MARKERS:
        assert marker not in response.text, marker

    payload = response.json()

    assert "debug_dump" not in payload
    assert payload["application"] == {
        "name": None,
        "exchange": None,
        "created_at": None,
    }
    assert payload["health"] == {"execution_halt_reason": None}
    assert payload["market_loop"] == {"symbols": ["BTCUSDT", None]}


def test_status_endpoint_publishes_non_json_values_safely() -> None:
    """LOW-6: a Decimal or datetime in status() must not become a 500."""

    from decimal import Decimal

    moment = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)

    class _NonJsonValues:
        def status(self) -> dict[str, object]:
            return {
                "application": {"started_at": moment},
                "capital": {
                    "capital": Decimal("10000.10"),
                    "portfolio_value": float("nan"),
                },
            }

    response = TestClient(
        create_app(runtime=_NonJsonValues()),
    ).get("/api/status")

    assert response.status_code == 200
    assert response.json() == {
        "application": {"started_at": "2026-09-28T12:00:00+00:00"},
        "capital": {"capital": "10000.10", "portfolio_value": None},
    }


def test_status_endpoint_reports_an_unpublishable_status_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOW-6: if the result still cannot be encoded, the route answers
    with the existing "unavailable + reason" shape, never a 500."""

    import web_app

    def refuse(status: dict[str, object]) -> dict[str, object]:
        raise TypeError("Object of type Widget is not JSON serializable")

    monkeypatch.setattr(web_app, "_public_runtime_status", refuse)

    response = TestClient(
        create_app(runtime=RealShapeRuntimeWithStatus()),
    ).get("/api/status")

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "reason": "RUNTIME_STATUS_FAILED",
        "error_type": "TypeError",
    }


def test_status_endpoint_fails_closed_with_no_runtime_attached() -> None:
    response = TestClient(create_app()).get("/api/status")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "reason": "RUNTIME_NOT_ATTACHED",
    }


def test_status_endpoint_survives_a_runtime_with_no_status_method() -> None:
    """RealShapeRuntime exposes health() but not status()."""

    response = TestClient(
        create_app(runtime=RealShapeRuntime()),
    ).get("/api/status")

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "reason": "RUNTIME_STATUS_UNAVAILABLE",
    }


def test_status_endpoint_survives_a_raising_status_method() -> None:
    class RaisingStatusRuntime:
        def status(self) -> dict[str, object]:
            raise RuntimeError("db connection lost: password=hunter2")

    response = TestClient(
        create_app(runtime=RaisingStatusRuntime()),
    ).get("/api/status")

    assert response.status_code == 200

    payload = response.json()

    assert payload["error_type"] == "RuntimeError"
    assert "hunter2" not in response.text


# =====================================================================
# C2 / C3 / C5
# =====================================================================


def test_dashboard_renders_server_state_instead_of_hardcoding_online() -> None:
    """C2: the template must use the context ``web_app`` already passes."""

    client = TestClient(create_app())

    body = client.get("/dashboard").text

    # No runtime and no price provider: the page must say so.
    assert "UNAVAILABLE" in body
    assert "OFFLINE" in body
    assert "AKTİF (Online)" not in body


def test_dashboard_requests_the_same_symbol_as_the_analysis_default() -> None:
    """C3: dashboard symbol/venue must match /api/analysis's default.

    Asserted behaviourally - the price provider records what it was asked
    for - rather than by grepping web_app.py for a literal, which would
    pass on a literal that is present but unused.
    """

    requested: list[str] = []

    def recording_provider(symbol: str) -> float:
        requested.append(symbol)
        return 63500.5

    client = TestClient(
        create_app(
            price_provider=recording_provider,
        )
    )

    body = client.get("/dashboard").text

    assert requested == ["BTCUSDT"]
    assert "BTCUSDT" in body
    assert "BTCTRY" not in body

    # The endpoint the dashboard polls must default to the same symbol.
    analysis = TestClient(
        create_app(
            runtime=RealShapeRuntime(),
        )
    ).get("/api/analysis")

    assert analysis.json()["symbol"] == "BTCUSDT"


def test_root_page_presents_no_authentication_form() -> None:
    """C5 (stub-only half): stop implying authentication that does not exist."""

    body = TestClient(create_app()).get("/").text

    assert 'name="username"' not in body
    assert "<form" not in body
