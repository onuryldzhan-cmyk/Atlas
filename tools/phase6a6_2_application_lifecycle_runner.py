from __future__ import annotations

import json
import py_compile
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = (
    ROOT
    / "tools"
    / "payload"
    / "test_application_lifecycle_integration.py"
)
TARGET = (
    ROOT
    / "tests"
    / "phase6"
    / "test_application_lifecycle_integration.py"
)
REPORT_DIR = (
    ROOT
    / "reports"
    / "phase6_application_lifecycle_integration"
)


def main() -> int:
    print("=" * 72)
    print("ATLAS PHASE 6A6.2 - APPLICATION LIFECYCLE INTEGRATION TEST")
    print("=" * 72)

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup = None

    if TARGET.exists():
        backup_dir = (
            ROOT
            / "backups"
            / "phase6a6_2_application_lifecycle"
            / timestamp
        )
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / TARGET.name
        shutil.copy2(TARGET, backup)

    shutil.copy2(PAYLOAD, TARGET)

    compile_targets = [
        TARGET,
        ROOT / "core" / "application.py",
        ROOT / "core" / "market_loop.py",
        ROOT / "exchange" / "market_feed.py",
        ROOT / "main.py",
    ]

    compile_passed = True
    compile_error = None

    try:
        for path in compile_targets:
            py_compile.compile(str(path), doraise=True)
    except Exception as exc:
        compile_passed = False
        compile_error = repr(exc)

    command = [
        sys.executable,
        "-m",
        "unittest",
        "tests.phase6.test_application_lifecycle_integration",
        "-v",
    ]

    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    tests_passed = completed.returncode == 0

    report = {
        "phase": "6A6.2",
        "generated_utc": datetime.now(UTC).isoformat(),
        "test_file": str(TARGET.relative_to(ROOT)),
        "compile_passed": compile_passed,
        "compile_error": compile_error,
        "tests_passed": tests_passed,
        "return_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "backup": str(backup) if backup else None,
        "production_source_files_modified": False,
        "network_used": False,
        "trading_execution_used": False,
    }

    report_path = (
        REPORT_DIR
        / f"phase6a6_2_application_lifecycle_{timestamp}.json"
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Test file       : {TARGET.relative_to(ROOT)}")
    print(
        "Compilation     : "
        + ("PASSED" if compile_passed else "FAILED")
    )
    print(
        "Lifecycle tests : "
        + ("PASSED" if tests_passed else "FAILED")
    )
    print(f"Report          : {report_path}")

    if completed.stdout.strip():
        print()
        print("[STDOUT]")
        print(completed.stdout)

    if completed.stderr.strip():
        print()
        print("[STDERR]")
        print(completed.stderr)

    if not compile_passed or not tests_passed:
        print()
        print(
            "PHASE 6A6.2 FAILED - "
            "PRODUCTION SOURCES WERE NOT MODIFIED"
        )
        return 1

    print()
    print("PHASE 6A6.2 COMPLETED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
