"""TEST-ISO-001 remediation proof.

governance/findings/TEST-ISO-001_PYTEST_SHARED_STATE_ROOT_ENVIRONMENT_HAZARD.md
records that a bare pytest invocation inherits ``ATLAS_STATE_DIRECTORY``,
``ATLAS_MARKET_ARCHIVE_DIRECTORY`` and ``ATLAS_EVIDENCE_DIRECTORY`` from the
shell with no isolation, so a shell exporting the operator's real, relocated
state roots would have every child pytest process silently open them. The
remediation lives in ``conftest.py``'s ``_isolate_state_root_environment``.

The hazard is a *process-inheritance* property, so it is proven the same way
here: a nested pytest subprocess is launched with the three variables pointed
at a real, pre-existing "sentinel" directory standing in for the operator's
real state root, and this test asserts that directory is never touched and
that the nested process actually observed different, isolated values.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

_ATLAS_STATE_ROOT_ENV_VARS = (
    "ATLAS_STATE_DIRECTORY",
    "ATLAS_MARKET_ARCHIVE_DIRECTORY",
    "ATLAS_EVIDENCE_DIRECTORY",
)


def test_state_root_isolation_keeps_an_inherited_override_untouched(
    tmp_path: Path,
) -> None:
    sentinels = {
        variable: tmp_path / f"sentinel_{variable.lower()}"
        for variable in _ATLAS_STATE_ROOT_ENV_VARS
    }
    for sentinel in sentinels.values():
        sentinel.mkdir()

    # Written inside tests/ (not tmp_path) and removed in `finally`: this
    # file's directory chain must actually pass through the repository root,
    # or the nested invocation would not reliably pick up the repository's
    # own conftest.py / pytest.ini at all, and the assertion below would
    # prove nothing about this repository's isolation hook.
    probe_path = (
        REPOSITORY_ROOT
        / "tests"
        / f"test_zz_generated_env_isolation_probe_{uuid.uuid4().hex}.py"
    )

    assertions = "\n".join(
        "    assert os.environ.get(%r) not in (None, %r), %r"
        % (variable, str(sentinel), variable)
        for variable, sentinel in sentinels.items()
    )
    probe_path.write_text(
        "import os\n"
        "\n"
        "\n"
        "def test_env_vars_are_not_the_inherited_sentinel() -> None:\n"
        f"{assertions}\n",
        encoding="utf-8",
    )

    try:
        env = dict(os.environ)
        for variable, sentinel in sentinels.items():
            env[variable] = str(sentinel)

        completed = subprocess.run(
            [sys.executable, "-m", "pytest", str(probe_path), "-q"],
            capture_output=True,
            text=True,
            cwd=str(REPOSITORY_ROOT),
            env=env,
        )

        assert completed.returncode == 0, completed.stdout + completed.stderr
    finally:
        probe_path.unlink(missing_ok=True)

    for variable, sentinel in sentinels.items():
        assert list(sentinel.iterdir()) == [], (
            f"{variable}'s sentinel directory {sentinel} was written to by "
            "the nested pytest run; state-root isolation did not engage"
        )
