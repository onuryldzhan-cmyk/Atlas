#!/usr/bin/env python3
"""Read-only SQLite query runner for atlas-db-reader.

There is no sqlite3 CLI on this machine, so the only route to Atlas's SQLite
stores is Python -- which the guard denies wholesale, because `python -c` can
execute anything. This script exists so that route can be reopened as a single
allowlisted path whose read-only guarantee does not depend on inspecting the
SQL text.

Two independent engine-level defenses, neither of which is a regex:

  1. The connection is opened with a `mode=ro` URI. SQLite itself refuses every
     write on such a connection, whatever statement arrives.
  2. An authorizer callback rejects every non-read operation before it runs, so
     a write is refused at prepare time with a named reason rather than
     surfacing as a generic "readonly database" error.

Usage:
    python .claude/tools/atlas_db_query.py <database-path> <sql> [--limit N]
    python .claude/tools/atlas_db_query.py <database-path> --tables

Never constructs AtlasApplication and never opens a writable handle, so it
cannot touch the runtime state files that Atlas persists execution and
paper-trading state into.

One caveat worth stating plainly, because "read-only" is easy to over-read:
Atlas's SQLite stores run in WAL mode, and a WAL database cannot be read at all
without its `-shm` shared-memory index. SQLite therefore materializes
`<db>-shm` and `<db>-wal` beside the database on first access even for a
`mode=ro` connection. The database file itself is never modified, and these
sidecars are ordinary SQLite bookkeeping rather than a change to Atlas state --
but they do appear on disk, so a caller expecting a literally zero-footprint
read should know it. Passing `immutable=1` would suppress them, and is
deliberately not used here: it asserts the file cannot change underneath the
reader, which is false whenever Atlas is running, and would risk stale or
inconsistent reads.
"""

from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

# sqlite3 authorizer actions that only read. Everything else is refused.
READ_ONLY_ACTIONS = frozenset({
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
})

# SQLITE_PRAGMA is deliberately NOT in READ_ONLY_ACTIONS: most pragmas are
# introspection (table_info, index_list) but some assign and mutate database
# state (journal_mode, writable_schema, foreign_keys=off). Blanket-allowing
# the action would reopen exactly the write surface -readonly/mode=ro is here
# to close. Only these named, verified-read-only pragmas are permitted; arg1
# on a PRAGMA action is the pragma name.
READ_ONLY_PRAGMAS = frozenset({
    "table_info", "table_xinfo", "index_list", "index_info", "index_xinfo",
    "foreign_key_list", "foreign_key_check", "database_list",
    "collation_list", "function_list", "module_list", "pragma_list",
    "compile_options", "integrity_check", "quick_check", "user_version",
    "application_id", "schema_version", "page_count", "page_size",
    "freelist_count", "encoding",
})

MAX_ROWS_DEFAULT = 100


def _authorizer(action, arg1, arg2, db_name, trigger):
    """Refuse anything that is not a plain read or a known-safe pragma."""
    if action in READ_ONLY_ACTIONS:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and (arg1 or "").lower() in READ_ONLY_PRAGMAS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a read-only query against an Atlas SQLite store.")
    parser.add_argument("database", help="path to the .sqlite3 file")
    parser.add_argument("sql", nargs="?", help="a single read-only statement")
    parser.add_argument("--tables", action="store_true",
                        help="list tables instead of running a query")
    parser.add_argument("--limit", type=int, default=MAX_ROWS_DEFAULT,
                        help=f"max rows to print (default {MAX_ROWS_DEFAULT})")
    args = parser.parse_args()

    path = pathlib.Path(args.database)
    if not path.exists():
        print(f"BLOCKED: no such database: {path}", file=sys.stderr)
        return 2
    if not args.tables and not args.sql:
        print("BLOCKED: supply a SQL statement or --tables", file=sys.stderr)
        return 2

    # mode=ro is the primary guarantee; the authorizer is the second.
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.set_authorizer(_authorizer)
    try:
        sql = ("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
               if args.tables else args.sql)
        try:
            cursor = connection.execute(sql)
        except sqlite3.DatabaseError as exc:
            # A denied authorizer action lands here, as does a genuine SQL error.
            print(f"BLOCKED: refused by read-only connection: {exc}",
                  file=sys.stderr)
            return 1

        if cursor.description:
            print(" | ".join(col[0] for col in cursor.description))
        for index, row in enumerate(cursor):
            if index >= args.limit:
                print(f"... truncated at --limit {args.limit}")
                break
            print(" | ".join("NULL" if v is None else str(v) for v in row))
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
