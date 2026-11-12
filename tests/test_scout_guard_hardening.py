"""Audit P4-CLOSURE-003 F-4 and F-6: the scout guard bounds reads, web calls and proposal writes.

F-4: Read/Grep/Glob were passed through unchecked, so a prompt-injected scout
could read secret material (the owner's signing key lives in ~/.atlas) and
send it out with WebFetch. The guard now keeps reads inside the repository and
off secret material, and bounds web calls. Residual risk (documented in the
guard): repository text can still be put into a request to a public host.

F-6: an existing (possibly already reviewed) proposal could be overwritten or
edited, and some diff formats slipped through.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = REPOSITORY_ROOT / ".claude" / "hooks" / "atlas_proposal_write_guard.py"
PROPOSALS = REPOSITORY_ROOT / "proposals"


def _load():
    spec = importlib.util.spec_from_file_location("scout_guard_hardening", GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load()


def call(tool, **tool_input):
    return guard.evaluate({"tool_name": tool, "tool_input": tool_input})[0]


# -- F-4: reads stay inside the repository and off secret material ---------


@pytest.mark.parametrize("path", [
    REPOSITORY_ROOT / "CLAUDE.md",
    REPOSITORY_ROOT / "templates" / "dashboard.html",
])
def test_ordinary_repository_reads_pass(path):
    assert call("Read", file_path=str(path)) is None


@pytest.mark.parametrize("path", [
    str(Path.home() / ".atlas" / "owner.key"),
    "/etc/passwd",
    str(Path.home() / ".ssh" / "id_ed25519"),
    str(REPOSITORY_ROOT) + "/../outside.txt",
    str(REPOSITORY_ROOT / ".env"),
    str(REPOSITORY_ROOT / ".env.local"),
    str(REPOSITORY_ROOT / "secrets" / "api.txt"),
    str(REPOSITORY_ROOT / "credentials" / "binance.json"),
    str(REPOSITORY_ROOT / ".git" / "config"),
    str(REPOSITORY_ROOT / "deploy" / "server.pem"),
    str(REPOSITORY_ROOT / "keys" / "owner.key"),
    "CLAUDE.md",  # relative
    "",
])
def test_reads_outside_the_repository_or_of_secrets_are_denied(path):
    assert call("Read", file_path=path) is False


def test_search_tools_are_bounded_the_same_way():
    assert call("Grep", pattern="def ") is None  # default: repository root
    assert call("Grep", pattern="def ", path=str(REPOSITORY_ROOT / "core")) is None
    assert call("Glob", pattern="**/*.py") is None
    assert call("Grep", pattern="KEY", path=str(Path.home() / ".atlas")) is False
    assert call("Grep", pattern="x", glob="*.pem") is False
    assert call("Glob", pattern="/home/**/owner.key") is False
    assert call("Glob", pattern="../**/*") is False
    assert call("Glob", pattern="**/.env") is False
    assert call("Glob", pattern="*", path=str(REPOSITORY_ROOT / "secrets")) is False


# -- F-4: web calls are bounded --------------------------------------------


@pytest.mark.parametrize("url", [
    "https://github.com/ColorlibHQ/AdminLTE",
    "https://www.chartjs.org/docs/latest/",
])
def test_public_https_fetches_pass(url):
    assert call("WebFetch", url=url, prompt="summarise") is None


@pytest.mark.parametrize("url", [
    "http://github.com/x",
    "https://user:pass@example.com/",
    "https://127.0.0.1/",
    "https://[::1]/",
    "https://169.254.169.254/latest/meta-data/",
    "https://localhost/",
    "https://service.internal/",
    "https://intranet/",
    "file:///etc/passwd",
    "https://example.com/" + "a" * 600,
    None,
])
def test_risky_or_unbounded_fetches_are_denied(url):
    assert call("WebFetch", url=url, prompt="x") is False


def test_web_search_queries_are_bounded():
    assert call("WebSearch", query="adminlte dark mode table") is None
    assert call("WebSearch", query="x" * 257) is False
    assert call("WebSearch") is False


# -- F-6: proposals are immutable; more diff formats are caught -------------


def test_an_existing_proposal_cannot_be_overwritten_or_edited():
    existing = sorted(p for p in PROPOSALS.glob("2*Z_*.md"))
    assert existing, "the repository holds reviewed proposals"
    assert call("Write", file_path=str(existing[0]), content="replaced") is False
    assert call("Edit", file_path=str(existing[0]), old_string="a", new_string="b") is False
    assert call("Write", file_path=str(PROPOSALS / "20991231T235959Z_dashboard-new.md"), content="ok") is None


@pytest.mark.parametrize("content", [
    "intro\n~~~diff\n-a\n+b\n~~~\n",
    "intro\ndiff --git a/core/x.py b/core/x.py\n",
])
def test_additional_diff_formats_are_refused(content):
    assert call("Write", file_path=str(PROPOSALS / "20991231T235959Z_dashboard-new.md"), content=content) is False


# -- the real entry point ---------------------------------------------------


def test_real_entry_point_denies_a_secret_read():
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": str(Path.home() / ".atlas" / "owner.key")}})
    out = subprocess.run([sys.executable, str(GUARD_PATH)], input=payload.encode("utf-8"), capture_output=True, check=True)
    decision = json.loads(out.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny" and "outside the repository" in decision["permissionDecisionReason"]


# -- F-3: harness-enforced controls (the hook is not relied upon) ----------


def test_scout_cannot_write_at_all_and_the_owner_key_is_denied_to_every_agent():
    agent = (REPOSITORY_ROOT / ".claude" / "agents" / "atlas-dashboard-scout.md").read_text(encoding="utf-8")
    tools_line = next(line for line in agent.split("---")[1].splitlines() if line.startswith("tools:"))
    tools = {t.strip() for t in tools_line.split(":", 1)[1].split(",")}
    assert not tools & {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "Agent"}
    deny = json.loads((REPOSITORY_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["deny"]
    assert {"Read(~/.atlas/**)", "Edit(~/.atlas/**)", "Read(./.env)", "Read(./secrets/**)"} <= set(deny)


# -- review N-2: Grep glob filters are matched as globs, not literally ------


@pytest.mark.parametrize("glob", [".env*", ".e*", "*env", "**/*.{pem,key}", "*", "id_*", "**/secrets/*"])
def test_grep_globs_that_can_reach_secrets_are_denied(glob):
    assert call("Grep", pattern="x", glob=glob) is False


@pytest.mark.parametrize("glob", ["*.py", "**/*.md", "*.html", "core/*.py", "*.{py,md}"])
def test_ordinary_grep_globs_still_pass(glob):
    assert call("Grep", pattern="x", glob=glob) is None


def test_guard_docstring_does_not_overclaim():
    doc = guard.__doc__
    assert "LOAD-BEARING" not in doc and "impossible" not in doc
    assert "HARNESS-ENFORCED" in doc and "ENFORCED ONLY WHEN THE HARNESS RUNS THIS HOOK" in doc
