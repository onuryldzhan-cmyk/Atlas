#!/usr/bin/env python3
"""PreToolUse guard: confine a research-scout subagent's writes to proposals/.

Reads a Claude Code PreToolUse hook payload on stdin and emits a JSON
permission decision on stdout. Wired through the `hooks:` frontmatter of
.claude/agents/atlas-dashboard-scout.md, so it runs only while that subagent is
active.

Unlike atlas_db_read_guard.py, this guard is LOAD-BEARING, not defense in
depth. The scout must hold the Write tool to produce its proposal, and the
harness `tools:` restriction cannot narrow Write to a directory. This hook is
therefore the only thing standing between the scout and the application tree.

Posture is ALLOWLIST-FIRST and fails closed:

- Read-only and web tools (Read, Grep, Glob, WebSearch, WebFetch) pass through
  silently to the normal permission flow.
- Write and Edit pass only when the target resolves -- after symlink/junction
  and `..` resolution -- to a new-style proposal file directly inside
  <repo>/proposals/, and the content carries no unified-diff hunk.
- Every other tool, including any tool the scout should never hold (Bash,
  NotebookEdit, MultiEdit, Agent, MCP tools), is denied.

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
from pathlib import Path

# <repo>/.claude/hooks/this_file -> <repo>
REPO_ROOT = Path(__file__).resolve().parents[2]
PROPOSALS_ROOT = REPO_ROOT / "proposals"

PASS_THROUGH_TOOLS = frozenset({"Read", "Grep", "Glob", "WebSearch", "WebFetch"})
WRITE_TOOLS = frozenset({"Write", "Edit"})

# <UTC ISO8601 compact>_<kebab-slug>.md, mirroring the checkpoints/ convention.
# Pinning the name also keeps the scout off proposals/README.md.
PROPOSAL_NAME = re.compile(r"^\d{8}T\d{6}Z_[a-z0-9]+(?:-[a-z0-9]+)*\.md$")

# A proposal is prose. A unified-diff header or a fenced diff/patch block means
# the scout is shipping an implementation instead of proposing one.
DIFF_MARKERS = re.compile(
    r"^(?:---|\+\+\+) (?:a|b)/|^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@|^```\s*(?:diff|patch)\b",
    re.MULTILINE | re.IGNORECASE,
)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


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

    content = tool_input.get("content") if tool_name == "Write" else tool_input.get("new_string")
    if isinstance(content, str) and DIFF_MARKERS.search(content):
        return False, "proposal contains a code diff; proposals are text only"
    return True, "proposal write inside proposals/"


def evaluate(payload: dict) -> tuple[bool | None, str]:
    """Return (decision, reason). None means pass through silently."""
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if tool_name in PASS_THROUGH_TOOLS:
        return None, "read-only tool"
    if tool_name in WRITE_TOOLS:
        ok, reason = check_write(tool_name, tool_input if isinstance(tool_input, dict) else {})
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
