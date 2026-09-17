"""Generate the pytest JUnit XML artifact read by the observability panel.

This is a manual, on-demand tool. The observability panel never invokes it
and never runs pytest itself; the panel only reads what this script last
wrote. A stale artifact stays stale until someone re-runs this script, and
the panel surfaces that staleness by comparing the stamped commit with HEAD.

Outputs (both paths are fixed and are what observability.panel_sources
reads):

    reports/observability/test_results.junit.xml
    reports/observability/test_results.meta.json

The sidecar stamps the commit the run was executed at, the UTC timestamp,
the exact pytest argv, the target, and pytest's exit code. Nothing in
pytest.ini is modified and normal test invocation is unaffected: the JUnit
options are passed on this command line only.

Usage
-----
    python tools/generate_test_results_artifact.py
    python tools/generate_test_results_artifact.py --target tests/architecture
    python tools/generate_test_results_artifact.py --basetemp C:/tmp/atlas

Host note: if the machine's default temporary-directory root is not usable
by pytest (a non-ASCII user profile path is the usual cause), pass an ASCII
``--basetemp`` or set ``ATLAS_PYTEST_BASETEMP``. That is an environment
concern, not a property of the tests.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from observability.panel_sources import (  # noqa: E402
    TEST_RESULTS_ARTIFACT_RELPATH,
    TEST_RESULTS_META_RELPATH,
    read_head_commit,
)

DEFAULT_TARGET = "tests"


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run pytest with --junitxml and refresh the observability "
            "panel's test-results artifact."
        ),
    )
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET,
        help=f"pytest target path (default: {DEFAULT_TARGET})",
    )
    parser.add_argument(
        "--basetemp",
        default=os.environ.get("ATLAS_PYTEST_BASETEMP"),
        help=(
            "explicit pytest --basetemp; required on hosts whose default "
            "temporary-directory root pytest cannot use"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the pytest command that would run and exit",
    )

    return parser.parse_args(argv)


def write_meta_sidecar(
    *,
    repository_root: Path,
    commit: str | None,
    started_at: datetime,
    finished_at: datetime,
    command: list[str],
    pytest_exit_code: int,
    target: str,
) -> Path:
    """Write the provenance sidecar the observability panel reads.

    Shared by this script's own ``main()`` and by the repository-root
    ``conftest.py`` hook that refreshes the artifact after a local
    full-suite run, so both producers stamp provenance identically rather
    than maintaining two copies of the same payload shape.
    """

    meta_path = repository_root / TEST_RESULTS_META_RELPATH
    meta_path.parent.mkdir(parents=True, exist_ok=True)

    meta = {
        "commit": commit,
        "generated_at": finished_at.isoformat(),
        "started_at": started_at.isoformat(),
        "command": command,
        "pytest_exit_code": pytest_exit_code,
        "target": target,
        "artifact": TEST_RESULTS_ARTIFACT_RELPATH,
    }

    meta_path.write_text(
        json.dumps(meta, indent=2) + "\n",
        encoding="utf-8",
    )

    return meta_path


def build_command(
    *,
    target: str,
    artifact_path: Path,
    basetemp: str | None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        target,
        "-q",
        "-p",
        "no:cacheprovider",
        f"--junitxml={artifact_path}",
    ]

    if basetemp:
        command.append(f"--basetemp={basetemp}")

    return command


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(argv)

    artifact_path = REPOSITORY_ROOT / TEST_RESULTS_ARTIFACT_RELPATH
    meta_path = REPOSITORY_ROOT / TEST_RESULTS_META_RELPATH
    artifact_path.parent.mkdir(parents=True, exist_ok=True)

    command = build_command(
        target=arguments.target,
        artifact_path=artifact_path,
        basetemp=arguments.basetemp,
    )

    if arguments.dry_run:
        print(" ".join(command))
        return 0

    commit = read_head_commit(REPOSITORY_ROOT)

    if commit is None:
        print(
            "WARNING: HEAD commit could not be resolved from .git; the "
            "artifact will be stamped with a null commit and the panel will "
            "report its provenance as incomplete.",
            file=sys.stderr,
        )

    started_at = datetime.now(UTC)
    completed = subprocess.run(command, cwd=REPOSITORY_ROOT, check=False)
    finished_at = datetime.now(UTC)

    if not artifact_path.is_file():
        print(
            f"ERROR: pytest produced no artifact at {artifact_path}. "
            "The sidecar was not written; the panel will keep reporting the "
            "previous state.",
            file=sys.stderr,
        )
        return 1

    write_meta_sidecar(
        repository_root=REPOSITORY_ROOT,
        commit=commit,
        started_at=started_at,
        finished_at=finished_at,
        command=command,
        pytest_exit_code=completed.returncode,
        target=arguments.target,
    )

    print(f"\nArtifact: {artifact_path}")
    print(f"Sidecar:  {meta_path}")
    print(f"Commit:   {commit or 'UNRESOLVED'}")
    print(f"pytest exit code: {completed.returncode}")

    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
