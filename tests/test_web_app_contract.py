from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


WEB_APP_PATH = Path("web_app.py")


def _load_source() -> tuple[str, ast.Module]:
    source = WEB_APP_PATH.read_text(
        encoding="utf-8-sig",
    )

    return source, ast.parse(source)


def _call_name(node: ast.Call) -> str:
    function = node.func

    if isinstance(function, ast.Name):
        return function.id

    if isinstance(function, ast.Attribute):
        parts: list[str] = []
        current: ast.expr = function

        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value

        if isinstance(current, ast.Name):
            parts.append(current.id)

        return ".".join(reversed(parts))

    return ""


def test_web_app_exposes_application_factory() -> None:
    _, tree = _load_source()

    function_names = {
        node.name
        for node in tree.body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
    }

    assert "create_app" in function_names


def test_web_app_has_no_module_level_runtime_construction() -> None:
    _, tree = _load_source()

    forbidden_calls = {
        "DatabaseManager",
        "PaperTrader",
        "AtlasBrain",
        "AtlasApplication",
    }

    violations: list[str] = []

    for node in tree.body:
        candidate_nodes: list[ast.AST] = []

        if isinstance(node, ast.Assign):
            candidate_nodes.append(node.value)

        elif isinstance(node, ast.AnnAssign):
            if node.value is not None:
                candidate_nodes.append(node.value)

        elif isinstance(node, ast.Expr):
            candidate_nodes.append(node.value)

        for candidate in candidate_nodes:
            for descendant in ast.walk(candidate):
                if not isinstance(descendant, ast.Call):
                    continue

                name = _call_name(descendant)

                if name in forbidden_calls:
                    violations.append(
                        f"{name} at line {descendant.lineno}"
                    )

    assert violations == []


def test_web_app_does_not_call_requests_directly() -> None:
    _, tree = _load_source()

    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        name = _call_name(node)

        if name in {
            "requests.get",
            "requests.post",
            "requests.request",
        }:
            violations.append(
                f"{name} at line {node.lineno}"
            )

    assert violations == []


def test_web_app_import_succeeds_without_starting_server() -> None:
    command = [
        sys.executable,
        "-c",
        (
            "import web_app; "
            "assert hasattr(web_app, 'app'); "
            "assert hasattr(web_app, 'create_app')"
        ),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, (
        "web_app import failed.\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


class FakeBrain:
    def __init__(self) -> None:
        self.received: list[dict[str, object]] = []

    def process(
        self,
        observation: dict[str, object],
    ) -> dict[str, object]:
        self.received.append(observation)

        return {
            "status": "SUCCESS",
            "symbol": observation["symbol"],
            "decision": None,
        }


class FakeRuntime:
    def __init__(
        self,
        *,
        healthy: bool = True,
    ) -> None:
        self.brain = FakeBrain()
        self._healthy = healthy

    def health(self) -> dict[str, object]:
        return {
            "healthy": self._healthy,
            "state": (
                "HEALTHY"
                if self._healthy
                else "OFFLINE"
            ),
        }


def test_health_endpoint_fails_closed_without_runtime() -> None:
    from fastapi.testclient import TestClient

    from web_app import create_app

    client = TestClient(
        create_app()
    )

    response = client.get(
        "/api/health"
    )

    assert response.status_code == 503
    assert response.json() == {
        "healthy": False,
        "state": "OFFLINE",
        "reason": "RUNTIME_NOT_ATTACHED",
    }


def test_analysis_endpoint_fails_closed_without_brain() -> None:
    from fastapi.testclient import TestClient

    from web_app import create_app

    client = TestClient(
        create_app()
    )

    response = client.get(
        "/api/analysis",
        params={
            "symbol": "ethusdt",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "status": "OFFLINE",
        "reason": "BRAIN_NOT_ATTACHED",
        "symbol": "ETHUSDT",
    }


def test_health_endpoint_uses_injected_runtime() -> None:
    from fastapi.testclient import TestClient

    from web_app import create_app

    runtime = FakeRuntime()

    client = TestClient(
        create_app(
            runtime=runtime,
        )
    )

    response = client.get(
        "/api/health"
    )

    assert response.status_code == 200
    assert response.json() == {
        "healthy": True,
        "state": "HEALTHY",
    }


def test_analysis_endpoint_uses_injected_brain() -> None:
    from fastapi.testclient import TestClient

    from web_app import create_app

    runtime = FakeRuntime()

    client = TestClient(
        create_app(
            runtime=runtime,
        )
    )

    response = client.get(
        "/api/analysis",
        params={
            "symbol": "solusdt",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "SUCCESS",
        "symbol": "SOLUSDT",
        "decision": None,
    }

    assert runtime.brain.received == [
        {
            "symbol": "SOLUSDT",
            "source": "WEB_REQUEST",
        }
    ]


class FakeBrain:
    def __init__(self) -> None:
        self.received: list[dict[str, object]] = []

    def process(
        self,
        observation: dict[str, object],
    ) -> dict[str, object]:
        self.received.append(observation)

        return {
            "status": "SUCCESS",
            "symbol": observation["symbol"],
            "decision": None,
        }


class FakeRuntime:
    def __init__(
        self,
        *,
        healthy: bool = True,
    ) -> None:
        self.brain = FakeBrain()
        self._healthy = healthy

    def health(self) -> dict[str, object]:
        return {
            "healthy": self._healthy,
            "state": (
                "HEALTHY"
                if self._healthy
                else "OFFLINE"
            ),
        }


def test_health_endpoint_fails_closed_without_runtime() -> None:
    from fastapi.testclient import TestClient

    from web_app import create_app

    client = TestClient(
        create_app()
    )

    response = client.get(
        "/api/health"
    )

    assert response.status_code == 503
    assert response.json() == {
        "healthy": False,
        "state": "OFFLINE",
        "reason": "RUNTIME_NOT_ATTACHED",
    }


def test_analysis_endpoint_fails_closed_without_brain() -> None:
    from fastapi.testclient import TestClient

    from web_app import create_app

    client = TestClient(
        create_app()
    )

    response = client.get(
        "/api/analysis",
        params={
            "symbol": "ethusdt",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "status": "OFFLINE",
        "reason": "BRAIN_NOT_ATTACHED",
        "symbol": "ETHUSDT",
    }


def test_health_endpoint_uses_injected_runtime() -> None:
    from fastapi.testclient import TestClient

    from web_app import create_app

    runtime = FakeRuntime()

    client = TestClient(
        create_app(
            runtime=runtime,
        )
    )

    response = client.get(
        "/api/health"
    )

    assert response.status_code == 200
    assert response.json() == {
        "healthy": True,
        "state": "HEALTHY",
    }


def test_analysis_endpoint_uses_injected_brain() -> None:
    from fastapi.testclient import TestClient

    from web_app import create_app

    runtime = FakeRuntime()

    client = TestClient(
        create_app(
            runtime=runtime,
        )
    )

    response = client.get(
        "/api/analysis",
        params={
            "symbol": "solusdt",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "SUCCESS",
        "symbol": "SOLUSDT",
        "decision": None,
    }

    assert runtime.brain.received == [
        {
            "symbol": "SOLUSDT",
            "source": "WEB_REQUEST",
        }
    ]
