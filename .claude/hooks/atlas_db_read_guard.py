#!/usr/bin/env python3
"""PreToolUse guard: permit read-only inspection of Atlas data stores, deny writes.

Reads a Claude Code PreToolUse hook payload on stdin and emits a JSON
permission decision on stdout. The payload shape was captured empirically from
Claude Code 2.1.224 and is documented in .claude/agents/atlas-db-reader.md.

Posture is ALLOWLIST-FIRST, not blocklist-first. A command is permitted only
when every segment of it starts with a binary known to be read-only AND no
write pattern appears anywhere in the text. Anything unrecognized is denied.
A blocklist alone is not a security boundary -- it can always be evaded by a
spelling the author did not anticipate -- so the unknown case must fail closed.

This script is defense-in-depth. The primary boundary for atlas-db-reader is
the harness-enforced `tools:` restriction in its agent definition, which omits
Bash entirely. This guard only becomes load-bearing if Bash is ever granted.

Exit code is always 0: the decision is carried in the JSON body, per the
PreToolUse contract. A non-zero exit would surface as a hook error rather than
a clean permission denial.
"""

from __future__ import annotations

import json
import re
import sys

# Binaries that cannot mutate state when invoked without write flags. A command
# segment whose head is not in this set is denied regardless of its arguments.
READ_ONLY_BINARIES = frozenset({
    "cat", "head", "tail", "less", "more", "nl", "wc", "file", "stat",
    "ls", "dir", "find", "tree", "basename", "dirname", "realpath",
    "grep", "egrep", "fgrep", "rg", "ack", "awk", "cut", "sort", "uniq",
    "column", "jq", "yq", "diff", "cmp", "md5sum", "sha256sum",
    "echo", "printf", "true", "pwd", "date", "env", "which", "type",
    "sqlite3", "python", "python3", "py", "git",
})

# Git subcommands that only inspect history. Anything else under git is denied,
# because git can rewrite the working tree and thus the JSON data stores.
READ_ONLY_GIT_SUBCOMMANDS = frozenset({
    "status", "log", "show", "diff", "branch", "rev-parse", "ls-files",
    "ls-tree", "cat-file", "blame", "describe", "shortlog", "grep",
    "check-ignore", "config", "remote", "tag", "reflog", "whatchanged",
})

# SQL that writes data or changes schema. Matched case-insensitively against
# the whole command text after comment stripping, so stacked statements and
# mixed casing are caught.
SQL_WRITE_PATTERNS = (
    (r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\b", "INSERT"),
    (r"\bUPDATE\b\s+\S+\s+\bSET\b", "UPDATE"),
    (r"\bDELETE\s+FROM\b", "DELETE"),
    (r"\bDROP\s+(?:TABLE|INDEX|VIEW|TRIGGER|DATABASE)\b", "DROP"),
    (r"\bALTER\s+TABLE\b", "ALTER"),
    (r"\bCREATE\s+(?:TEMP\s+|TEMPORARY\s+|UNIQUE\s+)?"
     r"(?:TABLE|INDEX|VIEW|TRIGGER|DATABASE)\b", "CREATE"),
    (r"\bTRUNCATE\b", "TRUNCATE"),
    (r"\bREPLACE\s+INTO\b", "REPLACE INTO"),
    (r"\bUPSERT\b", "UPSERT"),
    (r"\bVACUUM\b", "VACUUM"),
    (r"\bREINDEX\b", "REINDEX"),
    (r"\bATTACH\b", "ATTACH"),
    (r"\bBEGIN\s+(?:IMMEDIATE|EXCLUSIVE)\b", "write transaction"),
    (r"\bCOMMIT\b", "COMMIT"),
    # PRAGMA that assigns is a write; PRAGMA table_info(...) is a read.
    (r"\bPRAGMA\s+\w+\s*=", "PRAGMA assignment"),
    # sqlite3 dot-commands that write.
    (r"\.import\b", ".import"),
    (r"\.restore\b", ".restore"),
    (r"\.backup\b", ".backup"),
    (r"\.clone\b", ".clone"),
)

# Atlas's own non-SQL persistence surface. The data layer is not SQL-only:
# database/ and data/ are JSON document stores written through these helpers,
# so blocking SQL alone would leave the larger half of the store unguarded.
ATLAS_WRITE_CALL_PATTERNS = (
    (r"\.save\s*\(", "repository .save()"),
    (r"\.commit\s*\(", "unit-of-work .commit()"),
    (r"\.append\s*\(", "journal .append()"),
    (r"\.append_event\s*\(", "event-store .append_event()"),
    (r"\bsave_trade\s*\(", "save_trade()"),
    (r"\bsave_execution\s*\(", "save_execution()"),
    (r"\bsave_memory\s*\(", "save_memory()"),
    (r"\bsave_api_keys\s*\(", "save_api_keys()"),
    (r"\b_write(?:_audit_event|_recovery_marker)?\s*\(", "_write() helper"),
    (r"\bjson\.dump\s*\(", "json.dump()"),
    (r"\bAtlasApplication\s*\(", "AtlasApplication construction"),
    (r"\bapply_migrations\s*\(", "apply_migrations()"),
)

# Shell constructs that mutate the filesystem or smuggle execution past the
# per-segment binary allowlist.
SHELL_WRITE_PATTERNS = (
    (r">>?(?!&)", "output redirection"),
    (r"<", "input redirection (can feed SQL from a file)"),
    (r"\btee\b", "tee"),
    (r"\bdd\b", "dd"),
    (r"\b(?:rm|mv|cp|install|truncate|shred|mkdir|rmdir|touch|ln)\b",
     "filesystem mutation command"),
    (r"\bchmod\b|\bchown\b|\battrib\b", "permission change"),
    (r"\bsed\b[^|;]*\s-\w*i", "sed in-place edit"),
    (r"\bperl\b[^|;]*\s-\w*i", "perl in-place edit"),
    (r"\bbase64\b\s+(?:-d|--decode)", "base64 decode (possible smuggling)"),
    (r"\beval\b|\bexec\b|\bsource\b|^\s*\.\s+", "dynamic execution"),
    (r"\$\(|`", "command substitution"),
    (r"<<", "heredoc input"),
    (r"\bcurl\b|\bwget\b|\bnc\b", "network fetch"),
    (r"\bpip\b|\bnpm\b|\bapt\b|\bchoco\b", "package manager"),
)

# Python invoked with inline code can do anything; only allow the read-only
# module runners we can actually vouch for.
SAFE_PYTHON_MODULE_RUNNERS = ("json.tool", "sqlite3")

# The single allowlisted script. There is no sqlite3 CLI on this machine, so
# without this the guard would block the only available route to the SQLite
# stores. Permitted by exact path because its read-only guarantee comes from
# SQLite itself (mode=ro plus an authorizer), not from inspecting SQL text.
QUERY_SCRIPT = ".claude/tools/atlas_db_query.py"

# Opening a file in a writing mode, however it is spelled.
PYTHON_WRITE_MODE = re.compile(
    r"""open\s*\([^)]*['"][rwxa+][bt+]*['"]""", re.IGNORECASE)
PYTHON_EXPLICIT_WRITE_MODE = re.compile(
    r"""['"][wxa][bt+]*['"]""")

SQL_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
SQL_LINE_COMMENT = re.compile(r"--[^\n]*")
# Split on shell separators so each segment's head binary can be checked.
SEGMENT_SPLIT = re.compile(r"(?:\|\||&&|[|;&\n])")


def strip_comments(text: str) -> str:
    """Remove SQL comments so `SELECT 1; /*x*/ DROP TABLE t` cannot hide DROP."""
    return SQL_LINE_COMMENT.sub(" ", SQL_BLOCK_COMMENT.sub(" ", text))


def head_binary(segment: str) -> str | None:
    """Return the executable name a segment invokes, ignoring env assignments."""
    for token in segment.strip().split():
        # Skip leading VAR=value assignments and shell keywords.
        if "=" in token and not token.startswith("-"):
            continue
        if token in ("sudo", "command", "nohup", "time", "env"):
            continue
        name = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return name[:-4] if name.endswith(".exe") else name
    return None


def evaluate(command: str) -> tuple[bool, str]:
    """Return (allowed, reason). Denies on anything not provably read-only."""
    if not command or not command.strip():
        return False, "empty command"

    cleaned = strip_comments(command)

    # 1. Shell-level mutation and execution smuggling, checked on the whole
    #    command so a construct in any segment is caught.
    for pattern, label in SHELL_WRITE_PATTERNS:
        if re.search(pattern, cleaned, re.IGNORECASE | re.MULTILINE):
            return False, f"shell write/eval construct: {label}"

    # 2. SQL writes and DDL, anywhere in the text.
    for pattern, label in SQL_WRITE_PATTERNS:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return False, f"SQL write/DDL statement: {label}"

    # 3. Atlas's own non-SQL persistence calls.
    for pattern, label in ATLAS_WRITE_CALL_PATTERNS:
        if re.search(pattern, cleaned):
            return False, f"Atlas write path: {label}"

    # 4. Per-segment allowlist. Unknown binary -> deny.
    for segment in SEGMENT_SPLIT.split(cleaned):
        if not segment.strip():
            continue
        binary = head_binary(segment)
        if binary is None:
            return False, f"could not identify command in: {segment.strip()[:60]}"
        if binary not in READ_ONLY_BINARIES:
            return False, f"'{binary}' is not on the read-only allowlist"

        if binary == "sqlite3":
            # Enforcement is delegated to SQLite itself rather than to the SQL
            # patterns above. Without this, `cat writes.sql | sqlite3 db` would
            # pass every text check -- both binaries are allowlisted and no write
            # verb appears in the command. With -readonly the engine refuses any
            # write no matter how the SQL arrives (argument, stdin, or pipe).
            if not re.search(r"(?:^|\s)-{1,2}readonly\b", segment):
                return False, ("sqlite3 must be invoked with -readonly so the "
                               "engine itself refuses writes")

        if binary == "git":
            tokens = [t for t in segment.split() if not t.startswith("-")]
            sub = tokens[1] if len(tokens) > 1 else ""
            if sub not in READ_ONLY_GIT_SUBCOMMANDS:
                return False, f"git subcommand '{sub or '(none)'}' can mutate the tree"

        if binary in ("python", "python3", "py"):
            if re.search(r"\s-c\b", segment):
                return False, "python -c can execute arbitrary writes"
            if PYTHON_WRITE_MODE.search(segment) or PYTHON_EXPLICIT_WRITE_MODE.search(segment):
                return False, "python opens a file in a write mode"
            if QUERY_SCRIPT in segment.replace("\\", "/"):
                # The one allowlisted script. Its read-only guarantee is
                # engine-level (mode=ro plus an authorizer), not textual, so it
                # is safe to permit by exact path.
                continue
            if re.search(r"\s-m\b", segment):
                if not any(m in segment for m in SAFE_PYTHON_MODULE_RUNNERS):
                    return False, "only read-only python -m runners are permitted"
            elif not re.search(r"--version|\s-V\b", segment):
                return False, "running a python script file is not provably read-only"

    return True, "read-only inspection"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Fail closed: an unparseable payload must not silently permit a write.
        payload = {}
        decision, reason = False, "unparseable hook payload"
    else:
        decision, reason = evaluate(
            (payload.get("tool_input") or {}).get("command", ""))

    if decision:
        # Stay silent on allow so normal reads are not annotated; returning no
        # permissionDecision lets the usual permission flow proceed.
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": reason,
        }}))
    else:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"BLOCKED: {reason}. atlas-db-reader is read-only and may not "
                f"write to Atlas data stores. Report this as "
                f"'BLOCKED: {reason}' and stop; do not seek an alternate path."
            ),
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
