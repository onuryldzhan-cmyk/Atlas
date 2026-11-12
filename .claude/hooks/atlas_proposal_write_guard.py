#!/usr/bin/env python3
"""PreToolUse guard for a research-scout subagent: defense in depth, not the boundary.

Reads a Claude Code PreToolUse hook payload on stdin and emits a JSON
permission decision on stdout. Wired through the `hooks:` frontmatter of
.claude/agents/atlas-dashboard-scout.md, so it runs only while that subagent is
active.

What is enforced where (P4-CLOSURE-004, findings F-3/F-4, review N-2):

- HARNESS-ENFORCED (does not depend on this file): the scout's `tools:` list
  holds no Write, Edit, Bash or Agent, so it cannot change any file; and
  `.claude/settings.json` denies Read/Edit of `.env*`, `secrets/`,
  `credentials/` and `~/.atlas/**` (the owner's signing key) to every agent.
- ENFORCED ONLY WHEN THE HARNESS RUNS THIS HOOK: everything below. In at least
  one environment the frontmatter hook was observed not to run at all, so
  nothing may rely on it. Whether settings.json Read-deny rules also cover
  Grep/Glob content searches is UNKNOWN.

Posture is ALLOWLIST-FIRST and fails closed:

- Read, Grep and Glob pass only inside the repository and never on secret
  material (`.env*`, keys/certificates, `secrets/`, `credentials/`, `.git/`,
  `.ssh`, `.atlas`). Grep/Glob patterns are matched as globs (brace sets
  expanded) against representative secret names, so `.e*` or `*.{pem,key}`
  are refused too. This narrows, but does not close, exfiltration: a
  repository-wide Grep with no pattern filter may still traverse files the
  harness does not hide.
- WebFetch passes only for plain https URLs to a public host name (no
  credentials, IP literals, localhost or internal names) of bounded length;
  WebSearch only for a bounded query. RESIDUAL RISK, not eliminated: a
  prompt-injected scout can still put repository text it read into a URL or
  query sent to an attacker-chosen public host. Without a host allowlist this
  cannot be closed at tool level; the bounds only limit each request.
- Write passes only for a NEW proposal file directly inside <repo>/proposals/
  (after symlink/junction and `..` resolution) whose content carries no diff.
  An existing proposal is immutable: overwriting it and Edit are refused; a
  revision is a new, separately named proposal (F-6).
- Every other tool, including any tool the scout should never hold (Bash,
  NotebookEdit, MultiEdit, Agent, MCP tools), is denied.

Known gaps in this hook, documented as residual (owner decision 2026-10-09,
review R5-4; the hook is defense in depth only):
- Glob patterns are compared literally against representative names, so a
  pattern such as `**/.e*`, `**/?env` or `**/.*` can still list secret file
  NAMES (not contents; content reads stay refused).
- The IP-literal check does not recognise every shorthand form: `https://127.1/`
  is not refused here, so "no IP literals" holds only for canonical forms.
- A diff fence indented inside a list (e.g. "   ```diff") is not detected; the
  scout holds no Write, so this only matters if the hook guards a writer.

The guard never emits "allow". A silent exit leaves the normal permission flow
(and the settings.json deny rules) in charge; this hook can only take authority
away, never grant it.

The proposals root is derived from this script's own location, not from the
payload, so a tool call cannot redirect the boundary by lying about its cwd.

Exit code is always 0: the decision is carried in the JSON body, per the
PreToolUse contract. A non-zero exit would surface as a hook error rather than
a clean permission denial.
"""

from __future__ import annotations

import json
import os
import re
import sys
from fnmatch import fnmatchcase
from pathlib import Path

# <repo>/.claude/hooks/this_file -> <repo>
REPO_ROOT = Path(__file__).resolve().parents[2]
PROPOSALS_ROOT = REPO_ROOT / "proposals"

READ_TOOLS = frozenset({"Read", "Grep", "Glob"})
WEB_TOOLS = frozenset({"WebSearch", "WebFetch"})
WRITE_TOOLS = frozenset({"Write", "Edit"})

SENSITIVE_DIRS = frozenset({".git", ".ssh", ".aws", ".gnupg", ".atlas", "secrets", "credentials", ".venv"})
SENSITIVE_FILE = re.compile(
    r"^(?:\.env(?:\..*)?|.*\.(?:key|pem|p12|pfx|kdbx|keystore)|id_(?:rsa|dsa|ecdsa|ed25519).*|\.netrc|\.pgpass)$",
    re.IGNORECASE)
MAX_URL, MAX_QUERY = 512, 256
INTERNAL_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home", ".corp", ".intranet")

# <UTC ISO8601 compact>_<kebab-slug>.md, mirroring the checkpoints/ convention.
# Pinning the name also keeps the scout off proposals/README.md.
PROPOSAL_NAME = re.compile(r"^\d{8}T\d{6}Z_[a-z0-9]+(?:-[a-z0-9]+)*\.md$")

# A proposal is prose. A unified-diff header or a fenced diff/patch block means
# the scout is shipping an implementation instead of proposing one.
DIFF_MARKERS = re.compile(
    r"^(?:---|\+\+\+) (?:a|b)/|^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@|^(?:```|~~~)\s*(?:diff|patch)\b|^diff --git ",
    re.MULTILINE | re.IGNORECASE,
)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _sensitive(path: str) -> bool:
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    return any(p.lower() in SENSITIVE_DIRS for p in parts) or bool(parts and SENSITIVE_FILE.match(parts[-1]))


# Representative secret paths a search pattern must never be able to reach.
SECRET_PROBES = (".env", ".env.local", ".env.production", "server.pem", "owner.key", "cert.p12", "id_rsa",
                 "id_ed25519", ".netrc", "secrets/token.txt", "credentials/api.json", ".git/config",
                 ".atlas/owner.key", ".ssh/id_rsa", ".aws/credentials")


def _expand_braces(pattern: str) -> list[str]:
    match = re.search(r"\{([^{}]*)\}", pattern)
    if not match:
        return [pattern]
    head, tail = pattern[:match.start()], pattern[match.end():]
    return [v for option in match.group(1).split(",") for v in _expand_braces(head + option + tail)]


def _pattern_reaches_secrets(pattern: str) -> bool:
    """True when a glob could match secret material (N-2: match as a glob, not literally)."""
    for variant in _expand_braces(pattern.replace("\\", "/")):
        if _sensitive(variant):
            return True
        tail = variant.split("/")[-1].lower()
        for probe in SECRET_PROBES:
            name = probe.split("/")[-1]
            if fnmatchcase(probe, variant.lower().lstrip("/")) or fnmatchcase(probe, variant.lower().replace("**/", "")):
                return True
            if "/" not in probe and fnmatchcase(name, tail):
                return True
    return False


def check_read(tool_name: str, tool_input: dict) -> tuple[bool, str]:
    raw = tool_input.get("file_path") if tool_name == "Read" else tool_input.get("path")
    if tool_name == "Read" and (not isinstance(raw, str) or not raw.strip()):
        return False, "Read has no file_path"
    for pattern in (tool_input.get("pattern") if tool_name == "Glob" else None, tool_input.get("glob")):
        if isinstance(pattern, str) and (os.path.isabs(pattern) or ".." in pattern.replace("\\", "/").split("/")):
            return False, f"{tool_name} pattern must stay inside the repository: {pattern}"
        if isinstance(pattern, str) and (_sensitive(pattern) or (tool_name == "Grep" and _pattern_reaches_secrets(pattern))):
            return False, f"{tool_name} pattern can reach secret material: {pattern}"
    if raw is None:  # Grep/Glob default to the repository root
        return True, "repository search"
    if not isinstance(raw, str) or not os.path.isabs(raw):
        return False, f"{tool_name} path must be absolute: {raw}"
    target, repo = _norm(raw), _norm(str(REPO_ROOT))
    try:
        inside = os.path.commonpath([target, repo]) == repo
    except ValueError:
        inside = False
    if not inside:
        return False, f"{tool_name} outside the repository: {raw}"
    if _sensitive(os.path.relpath(target, repo)) or _sensitive(raw):
        return False, f"{tool_name} on secret material: {raw}"
    return True, "repository read"


def check_web(tool_name: str, tool_input: dict) -> tuple[bool, str]:
    from ipaddress import ip_address
    from urllib.parse import urlsplit

    if tool_name == "WebSearch":
        query = tool_input.get("query")
        if not isinstance(query, str) or len(query) > MAX_QUERY:
            return False, f"WebSearch query must be text of at most {MAX_QUERY} characters"
        return True, "bounded web search"
    url = tool_input.get("url")
    if not isinstance(url, str) or len(url) > MAX_URL:
        return False, f"WebFetch url must be text of at most {MAX_URL} characters"
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        has_userinfo = parts.username is not None or parts.password is not None
    except ValueError:
        return False, f"unparseable url: {url}"
    if parts.scheme != "https":
        return False, f"only https URLs: {url}"
    if has_userinfo:
        return False, "credentials in a URL are refused"
    if not host or "." not in host or host == "localhost" or host.endswith(INTERNAL_SUFFIXES):
        return False, f"not a public host name: {host or url}"
    try:
        ip_address(host.strip("[]"))
    except ValueError:
        return True, "public https fetch"
    return False, f"IP-literal hosts are refused: {host}"


def check_write(tool_name: str, tool_input: dict) -> tuple[bool, str]:
    raw = tool_input.get("file_path")
    if not isinstance(raw, str) or not raw.strip():
        return False, f"{tool_name} has no file_path"
    if not os.path.isabs(raw):
        return False, f"relative path refused: {raw}"
    # An NTFS alternate data stream (`x.md:evil`) would pass a prefix check.
    drive, rest = os.path.splitdrive(raw)
    if ":" in rest:
        return False, f"alternate data stream refused: {raw}"

    target = _norm(raw)
    root = _norm(str(PROPOSALS_ROOT))
    try:
        inside = os.path.commonpath([target, root]) == root
    except ValueError:  # different drives
        inside = False
    if not inside or target == root:
        return False, f"path is outside proposals/: {raw}"
    if os.path.dirname(target) != root:
        return False, f"proposals/ subdirectories are not writable: {raw}"
    if not PROPOSAL_NAME.match(os.path.basename(os.path.realpath(raw))):
        return False, ("file name must match <YYYYMMDDTHHMMSSZ>_<kebab-slug>.md: "
                       f"{os.path.basename(raw)}")
    if tool_name == "Edit" or os.path.lexists(raw) or os.path.exists(target):
        return False, ("an existing proposal is immutable; write a new, separately named "
                       "proposal that supersedes it")

    content = tool_input.get("content") if tool_name == "Write" else tool_input.get("new_string")
    if isinstance(content, str) and DIFF_MARKERS.search(content):
        return False, "proposal contains a code diff; proposals are text only"
    return True, "proposal write inside proposals/"


def evaluate(payload: dict) -> tuple[bool | None, str]:
    """Return (decision, reason). None means pass through silently."""
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    for tools, check in ((READ_TOOLS, check_read), (WEB_TOOLS, check_web), (WRITE_TOOLS, check_write)):
        if tool_name in tools:
            ok, reason = check(tool_name, tool_input)
            return (None if ok else False), reason
    return False, f"tool '{tool_name}' is not available to a research scout"


def main() -> int:
    try:
        # Decode the raw bytes as UTF-8 explicitly. Claude Code sends
        # non-ASCII paths unescaped, and sys.stdin would decode them with the
        # locale codepage (cp1254 on this host), mangling the repo path so that
        # every legitimate proposal write is refused.
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except (json.JSONDecodeError, ValueError):  # UnicodeDecodeError is a ValueError
        # Fail closed: an unparseable payload must not silently permit a write.
        decision, reason = False, "unparseable hook payload"
    else:
        decision, reason = evaluate(payload)

    if decision is False:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"BLOCKED: {reason}. A research scout may write only proposal "
                f"files directly inside proposals/. Report this as "
                f"'BLOCKED: {reason}' and stop; do not seek an alternate path."
            ),
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
