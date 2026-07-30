"""
ATLAS PHASE 6A3 — MARKETFEED COMPATIBILITY PATCHER
"""

from __future__ import annotations

import ast
import hashlib
import json
import py_compile
import shutil
import subprocess
import sys

from datetime import UTC
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "exchange" / "market_feed.py"
TEST_TARGET = (
    ROOT
    / "tests"
    / "phase6"
    / "test_market_feed_compatibility.py"
)
SOURCE = (
    Path(__file__).resolve().parent
    / "payload"
    / "market_feed.py"
)
TEST_SOURCE = (
    Path(__file__).resolve().parent
    / "payload"
    / "test_market_feed_compatibility.py"
)
BACKUP_ROOT = (
    ROOT
    / "backups"
    / "phase6a3_market_feed_adapter"
)
REPORT_ROOT = (
    ROOT
    / "reports"
    / "phase6_market_feed_adapter"
)


def digest(path: Path) -> str:
    value = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            value.update(chunk)

    return value.hexdigest()


def validate_existing_target() -> None:
    if not TARGET.exists():
        raise FileNotFoundError(
            f"Target not found: {TARGET}"
        )

    source = TARGET.read_text(
        encoding="utf-8",
        errors="replace",
    )
    tree = ast.parse(
        source,
        filename=str(TARGET),
    )

    cls = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "MarketFeed"
        ),
        None,
    )

    if cls is None:
        raise RuntimeError(
            "Existing exchange/market_feed.py does not define MarketFeed."
        )

    methods = {
        node.name
        for node in cls.body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
    }

    required = {
        "__init__",
        "start",
        "stop",
        "price",
        "candles",
    }

    missing = required - methods

    if missing:
        raise RuntimeError(
            "Unexpected legacy MarketFeed contract. "
            f"Missing methods: {sorted(missing)}"
        )


def validate_payload(path: Path, class_name: str | None = None) -> None:
    source = path.read_text(
        encoding="utf-8",
    )
    tree = ast.parse(
        source,
        filename=str(path),
    )

    if class_name is not None:
        if not any(
            isinstance(node, ast.ClassDef)
            and node.name == class_name
            for node in tree.body
        ):
            raise RuntimeError(
                f"Payload missing class {class_name}: {path}"
            )


def rollback(
    target_backup: Path,
    test_backup: Path | None,
    test_existed: bool,
) -> None:
    shutil.copy2(
        target_backup,
        TARGET,
    )

    if test_existed and test_backup is not None:
        TEST_TARGET.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(
            test_backup,
            TEST_TARGET,
        )
    elif TEST_TARGET.exists():
        TEST_TARGET.unlink()


def main() -> int:
    validate_existing_target()
    validate_payload(
        SOURCE,
        "MarketFeed",
    )
    validate_payload(
        TEST_SOURCE,
    )

    timestamp = datetime.now(UTC).strftime(
        "%Y%m%d_%H%M%S"
    )
    backup_dir = BACKUP_ROOT / timestamp
    backup_dir.mkdir(
        parents=True,
        exist_ok=False,
    )
    REPORT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    target_backup = (
        backup_dir
        / "exchange"
        / "market_feed.py"
    )
    target_backup.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    shutil.copy2(
        TARGET,
        target_backup,
    )

    test_existed = TEST_TARGET.exists()
    test_backup = None

    if test_existed:
        test_backup = (
            backup_dir
            / "tests"
            / "phase6"
            / "test_market_feed_compatibility.py"
        )
        test_backup.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(
            TEST_TARGET,
            test_backup,
        )

    before_hash = digest(
        TARGET
    )

    report = {
        "phase": "6A3",
        "generated_utc": datetime.now(UTC).isoformat(),
        "target": str(TARGET.relative_to(ROOT)),
        "before_sha256": before_hash,
        "backup": str(backup_dir),
        "status": "STARTED",
        "checks": {},
    }

    try:
        shutil.copy2(
            SOURCE,
            TARGET,
        )
        TEST_TARGET.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(
            TEST_SOURCE,
            TEST_TARGET,
        )

        py_compile.compile(
            str(TARGET),
            doraise=True,
        )
        py_compile.compile(
            str(TEST_TARGET),
            doraise=True,
        )
        report["checks"]["compilation"] = "PASSED"

        validate_payload(
            TARGET,
            "MarketFeed",
        )
        report["checks"]["ast_validation"] = "PASSED"

        command = [
            sys.executable,
            "-m",
            "unittest",
            "tests.phase6.test_market_feed_compatibility",
            "-v",
        ]

        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )

        report["checks"]["contract_tests"] = {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

        if completed.returncode != 0:
            raise RuntimeError(
                "Offline compatibility contract tests failed."
            )

        report["checks"]["contract_tests"]["status"] = "PASSED"
        report["after_sha256"] = digest(
            TARGET
        )
        report["status"] = "COMPLETED"

    except Exception as exc:
        rollback(
            target_backup,
            test_backup,
            test_existed,
        )
        report["status"] = "ROLLED_BACK"
        report["error"] = str(exc)

        report_path = (
            REPORT_ROOT
            / f"phase6a3_adapter_{timestamp}.json"
        )
        report_path.write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        print("=" * 72)
        print("ATLAS PHASE 6A3 - ROLLED BACK")
        print("=" * 72)
        print(f"Error  : {exc}")
        print(f"Backup : {backup_dir}")
        print(f"Report : {report_path}")

        return 1

    report_path = (
        REPORT_ROOT
        / f"phase6a3_adapter_{timestamp}.json"
    )
    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("=" * 72)
    print("ATLAS PHASE 6A3 - MARKETFEED COMPATIBILITY ADAPTER")
    print("=" * 72)
    print("Modified files : 2")
    print("[UPDATED] exchange/market_feed.py")
    print("[ADDED]   tests/phase6/test_market_feed_compatibility.py")
    print()
    print("Compilation     : PASSED")
    print("AST validation  : PASSED")
    print("Contract tests  : PASSED")
    print(f"Backup          : {backup_dir}")
    print(f"Report          : {report_path}")
    print()
    print("PHASE 6A3 COMPLETED")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
