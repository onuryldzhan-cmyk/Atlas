"""Deterministic build provenance record generator.

Produces a machine-readable summary of what code, dependencies, and
architecture state a build was made from: git commit/branch/dirty state,
Python version, and content hashes of the dependency, runtime-distribution
and architecture-map manifests already checked into the repository.

This is not a cryptographic build attestation (no SLSA/Sigstore/SBOM
tooling); it only records hashes of tracked files and current git state.

Safety
------
- Read-only except the explicit --output file.
- No network access.
- Never records a secret value.
- Refuses to record build_mode=LIVE; live_authority is always False.
- Deterministic for the same repository state, except build_timestamp
  (explicitly time-varying).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_MANIFEST = REPOSITORY_ROOT / "requirements.txt"
RUNTIME_MANIFEST = REPOSITORY_ROOT / "packaging" / "atlas_runtime_distribution_manifest.json"
ARCHITECTURE_MAP = REPOSITORY_ROOT / "packaging" / "atlas_architecture_map.json"


class ProvenanceError(RuntimeError):
    """Raised when required provenance input is missing or invalid."""


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ProvenanceError(f"required input missing: {path}")
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={REPOSITORY_ROOT.as_posix()}", *args],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_commit() -> str:
    return _git("rev-parse", "HEAD")


def _git_branch() -> str:
    return _git("rev-parse", "--abbrev-ref", "HEAD")


def _git_dirty() -> bool:
    return bool(_git("status", "--porcelain"))


def build_provenance_record(
    *, build_mode: str = "PAPER", test_result: str = "UNKNOWN",
) -> dict[str, Any]:
    if build_mode.strip().upper() == "LIVE":
        raise ProvenanceError(
            "LIVE build_mode is not authorized; PAPER-only remains the default"
        )

    commit = _git_commit()
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_id": f"atlas-{commit[:12]}",
        "git_commit": commit,
        "branch": _git_branch(),
        "dirty_worktree": _git_dirty(),
        "python_version": platform.python_version(),
        "dependency_manifest_hash": _sha256_file(DEPENDENCY_MANIFEST),
        "runtime_manifest_hash": _sha256_file(RUNTIME_MANIFEST),
        "architecture_map_hash": _sha256_file(ARCHITECTURE_MAP),
        "test_result": test_result,
        "build_timestamp": datetime.now(UTC).isoformat(),
        "build_mode": build_mode,
        "source_provenance": "local_worktree",
        "paper_only": True,
        "live_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-mode", default="PAPER")
    parser.add_argument("--test-result", default="UNKNOWN")
    args = parser.parse_args(argv)

    try:
        record = build_provenance_record(
            build_mode=args.build_mode, test_result=args.test_result,
        )
    except ProvenanceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(record, sort_keys=True, indent=2), encoding="utf-8",
    )
    print(f"Wrote provenance record to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
