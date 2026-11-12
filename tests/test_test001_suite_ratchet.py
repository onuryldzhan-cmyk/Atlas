"""TEST-001 baseline ratchet (registry v5.27): the test suite may only grow.

Counted by AST (test_* functions in tests/**/test_*.py) so it does not
depend on collection or parametrization. Measured 2026-09-28: 192 files,
3466 functions (collected cases: 5551 passed + B2/D5 + 12 skipped).
Removing tests below the floor needs a successor registry record naming
why - never silently (CLAUDE.md: never weaken a test).
"""

import ast
from pathlib import Path

TEST_FILES_FLOOR = 192
TEST_FUNCTIONS_FLOOR = 3466

ROOT = Path(__file__).resolve().parents[1] / "tests"


def _count():
    files = functions = 0
    for path in ROOT.rglob("test_*.py"):
        files += 1
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                functions += 1
    return files, functions


def test_suite_never_shrinks():
    files, functions = _count()
    assert files >= TEST_FILES_FLOOR, files
    assert functions >= TEST_FUNCTIONS_FLOOR, functions
