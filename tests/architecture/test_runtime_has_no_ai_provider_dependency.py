"""ADR-0011 D1: the live runtime never depends on an AI provider.

Every module in the checked-in runtime closure
(packaging/atlas_runtime_closure.json, itself pinned to the recomputed
closure by test_runtime_closure_matches_inventory) is scanned for:

- a static import of an AI provider / LLM client SDK;
- a dynamic import (``importlib.import_module`` / ``__import__``) of one;
- a string constant naming a hosted LLM API or a local LLM server endpoint.

Atlas's deterministic core must start and keep its safety behaviour with
every AI service absent (docs/adr/0011-ai-independent-deterministic-core.md).
When the provider-neutral AI layer of ADR-0011 D2 is built, its adapter
module(s) enter this allowlist by an explicit, owner-approved change, never
silently. The allowlist is empty today because no such adapter exists.
"""

from __future__ import annotations

import ast

from tools.build_architecture_inventory import (
    REPOSITORY_ROOT,
    _resolve_imports,
    load_runtime_closure,
)

# Root packages of AI provider / LLM client SDKs.
_PROVIDER_SDK_ROOTS = frozenset({
    "anthropic",
    "openai",
    "ollama",
    "langchain",
    "langchain_core",
    "langchain_community",
    "langchain_openai",
    "langchain_anthropic",
    "llama_index",
    "litellm",
    "cohere",
    "mistralai",
    "groq",
    "claude_agent_sdk",
})

# Dotted prefixes for SDKs that live under a shared namespace package.
_PROVIDER_SDK_PREFIXES = (
    "google.generativeai",
    "google.genai",
)

# Hosted LLM APIs and the local Ollama server.
_LLM_ENDPOINT_MARKERS = (
    "api.anthropic.com",
    "api.openai.com",
    "generativelanguage.googleapis.com",
    "api.mistral.ai",
    "api.cohere.ai",
    "api.groq.com",
    "localhost:11434",
    "127.0.0.1:11434",
    "/v1/messages",
    "/v1/chat/completions",
)

# Runtime modules sanctioned to talk to an AI provider (ADR-0011 D2).
_SANCTIONED_AI_PROVIDER_ADAPTERS: frozenset[str] = frozenset()

_DYNAMIC_IMPORT_CALLS = frozenset({"import_module", "__import__"})


def _is_provider_sdk(dotted: str) -> bool:
    if dotted.split(".", 1)[0] in _PROVIDER_SDK_ROOTS:
        return True
    return any(dotted == prefix or dotted.startswith(prefix + ".") for prefix in _PROVIDER_SDK_PREFIXES)


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _violations_in(relative_path: str, source: str) -> list[str]:
    tree = ast.parse(source, filename=relative_path)
    found: list[str] = []

    for dotted in _resolve_imports(relative_path, tree):
        if _is_provider_sdk(dotted):
            found.append(f"{relative_path}: imports {dotted}")

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and _called_name(node) in _DYNAMIC_IMPORT_CALLS
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and _is_provider_sdk(node.args[0].value)
        ):
            found.append(f"{relative_path}: dynamically imports {node.args[0].value}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            for marker in _LLM_ENDPOINT_MARKERS:
                if marker in lowered:
                    found.append(f"{relative_path}: references LLM endpoint {marker!r}")

    return found


def _runtime_modules() -> list[str]:
    modules = list(load_runtime_closure()["modules"])
    # Guard against a vacuous pass: the closure must contain the core.
    assert "core/execution_manager.py" in modules
    assert "core/application.py" in modules
    return modules


def test_runtime_closure_has_no_ai_provider_dependency() -> None:
    violations: list[str] = []

    for relative_path in _runtime_modules():
        if relative_path in _SANCTIONED_AI_PROVIDER_ADAPTERS:
            continue
        source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8-sig")
        violations.extend(_violations_in(relative_path, source))

    assert violations == [], (
        "ADR-0011 D1: the live runtime must not depend on an AI provider. "
        "A provider adapter enters _SANCTIONED_AI_PROVIDER_ADAPTERS only by an "
        f"explicit owner-approved change. Found: {sorted(violations)}"
    )


def test_sanctioned_adapter_allowlist_is_empty_until_owner_approval() -> None:
    assert _SANCTIONED_AI_PROVIDER_ADAPTERS == frozenset()


def test_detector_catches_each_violation_shape() -> None:
    # The scanner itself must not pass vacuously.
    samples = {
        "import anthropic\n": "imports anthropic",
        "from openai import OpenAI\n": "imports openai",
        "import ollama.client as c\n": "imports ollama.client",
        "from langchain_core.messages import HumanMessage\n": "imports langchain_core",
        "import google.generativeai as genai\n": "imports google.generativeai",
        "import importlib\nm = importlib.import_module('anthropic')\n": "dynamically imports anthropic",
        "m = __import__('ollama')\n": "dynamically imports ollama",
        "URL = 'http://localhost:11434/api/chat'\n": "localhost:11434",
        "URL = 'https://API.OPENAI.COM/v1/chat/completions'\n": "api.openai.com",
        "PATH = '/v1/messages'\n": "/v1/messages",
    }
    for source, expected in samples.items():
        found = _violations_in("core/sample.py", source)
        assert any(expected in item for item in found), (source, found)


def test_detector_ignores_non_provider_code() -> None:
    clean = (
        "import json\n"
        "import google_auth_stub\n"
        "from core import risk_state_store\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import anthropic\n"
        "NOTE = 'openai-compatible wording in prose is fine'\n"
        "m = __import__('json')\n"
    )
    assert _violations_in("core/sample.py", clean) == []
