"""
============================================================
ATLAS BOM / MOJIBAKE REPAIR TOOL v1.0
============================================================

Repairs only the 13 files identified in Phase 3E.

Fixes
-----
- UTF-8 BOM (U+FEFF)
- Mojibake prefix: ï»¿
- Byte-order-mark corruption at file start

Safety
------
- Creates a timestamped backup before modification
- Modifies only approved target files
- Verifies AST parsing after repair
- Writes a detailed manifest
============================================================
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
from datetime import datetime, UTC
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "reports" / "phase3_bom_repair"

TARGET_FILES = [
    "atlas_os/configuration/__init__.py",
    "atlas_os/secrets/__init__.py",
    "atlas_paper_trading/paper_trading_engine.py",
    "atlas_paper_trading/paper_trading_main.py",
    "atlas_paper_trading/performance_report.py",
    "atlas_paper_trading/position_tracker.py",
    "atlas_paper_trading/risk_guardian.py",
    "inspect_atlas_os_lifecycle.py",
    "test_atlas_infrastructure.py",
    "test_atlas_runtime_empty.py",
    "test_atlas_secure_core.py",
    "test_configuration_secrets_service.py",
    "web_app.py",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def clean_prefix(text: str) -> tuple[str, list[str]]:
    changes: list[str] = []

    while text.startswith("\ufeff"):
        text = text[1:]
        changes.append("REMOVED_U_FEFF")

    while text.startswith("ï»¿"):
        text = text[3:]
        changes.append("REMOVED_MOJIBAKE_PREFIX")

    # Covers common malformed variants produced by repeated conversions.
    while text.startswith("ï»¿"):
        text = text[len("ï»¿"):]
        changes.append("REMOVED_MOJIBAKE_PREFIX")

    return text, changes


def main() -> int:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_root = PROJECT_ROOT / f"phase3f_bom_backup_{timestamp}"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    failures: list[dict] = []

    print("=" * 72)
    print("ATLAS BOM / MOJIBAKE REPAIR TOOL v1.0")
    print("=" * 72)
    print(f"Project : {PROJECT_ROOT}")
    print(f"Backup  : {backup_root}")
    print()

    for relative in TARGET_FILES:
        source = PROJECT_ROOT / relative

        if not source.exists():
            failures.append({
                "path": relative,
                "error": "FILE_NOT_FOUND",
            })
            print(f"[MISSING] {relative}")
            continue

        original_hash = sha256(source)
        raw = source.read_bytes()

        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")

        cleaned, changes = clean_prefix(text)

        if not changes and cleaned == text:
            # utf-8-sig may already have consumed a real BOM.
            if raw.startswith(b"\xef\xbb\xbf"):
                changes.append("REMOVED_UTF8_BOM_BYTES")

        backup = backup_root / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup)

        source.write_text(
            cleaned,
            encoding="utf-8",
            newline="\n",
        )

        repaired_hash = sha256(source)

        try:
            ast.parse(
                source.read_text(
                    encoding="utf-8",
                    errors="strict",
                ),
                filename=str(source),
            )
            parse_ok = True
            parse_error = ""
        except SyntaxError as error:
            parse_ok = False
            parse_error = (
                f"{error.msg} "
                f"(line {error.lineno}, column {error.offset})"
            )

        record = {
            "path": relative,
            "backup_path": str(backup.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "original_sha256": original_hash,
            "repaired_sha256": repaired_hash,
            "changes": changes or ["NORMALIZED_UTF8_ENCODING"],
            "parse_ok": parse_ok,
            "parse_error": parse_error,
        }
        records.append(record)

        if parse_ok:
            print(f"[REPAIRED] {relative}")
        else:
            print(f"[PARSE FAIL] {relative}: {parse_error}")

    manifest = {
        "project_root": str(PROJECT_ROOT),
        "backup_root": str(backup_root),
        "target_count": len(TARGET_FILES),
        "processed_count": len(records),
        "failure_count": len(failures),
        "parse_success_count": sum(
            1 for record in records if record["parse_ok"]
        ),
        "parse_failure_count": sum(
            1 for record in records if not record["parse_ok"]
        ),
        "records": records,
        "failures": failures,
    }

    manifest_path = REPORT_DIR / "bom_repair_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print(f"Processed     : {manifest['processed_count']}")
    print(f"Parse success : {manifest['parse_success_count']}")
    print(f"Parse failure : {manifest['parse_failure_count']}")
    print(f"Missing       : {manifest['failure_count']}")
    print(f"Manifest      : {manifest_path}")
    print()

    if (
        manifest["failure_count"] > 0
        or manifest["parse_failure_count"] > 0
    ):
        print("REPAIR COMPLETED WITH ERRORS")
        return 1

    print("BOM REPAIR COMPLETED SUCCESSFULLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
