"""Coverage for the root conftest.py hook that keeps the observability
panel's test-results artifact fresh after a local full-suite run.

The property that matters most here is the negative one: a narrow or
truncated run must never overwrite the artifact with a misleadingly low
count. The eligibility and completeness decisions are therefore pure
functions over plain values, exercised exhaustively below, plus one
real subprocess run proving the wiring actually stands down in practice.
"""

from __future__ import annotations

import json
import subprocess
import sys

from datetime import UTC, datetime
from pathlib import Path

import pytest

import conftest as root_conftest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

FULL_SUITE_BASELINE = {
    "args": ["tests"],
    "testpaths": ["tests"],
    "args_from_testpaths": True,
    "keyword": "",
    "markexpr": "",
    "deselect": None,
    "last_failed": False,
    "stepwise": False,
    "collect_only": False,
    "xmlpath": None,
    "is_xdist_worker": False,
}


# =====================================================================
# Eligibility: which invocations count as a full-suite run
# =====================================================================


def test_bare_invocation_falling_back_to_testpaths_is_a_full_suite_run() -> None:
    assert root_conftest.is_full_suite_invocation(**FULL_SUITE_BASELINE)


def test_explicit_testpaths_argument_is_also_a_full_suite_run() -> None:
    """`pytest tests` is the same selection as a bare `pytest`."""

    assert root_conftest.is_full_suite_invocation(
        **{**FULL_SUITE_BASELINE, "args_from_testpaths": False}
    )


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"keyword": "trades"}, id="dash-k-filter"),
        pytest.param({"markexpr": "slow"}, id="dash-m-filter"),
        pytest.param({"deselect": ["tests/test_a.py::test_b"]}, id="deselect"),
        pytest.param({"last_failed": True}, id="last-failed"),
        pytest.param({"stepwise": True}, id="stepwise"),
        pytest.param({"collect_only": True}, id="collect-only"),
        pytest.param({"is_xdist_worker": True}, id="xdist-worker"),
        pytest.param(
            {"xmlpath": "reports/observability/test_results.junit.xml"},
            id="explicit-junitxml",
        ),
        pytest.param(
            {
                "args": ["tests/test_web_app_contract.py"],
                "args_from_testpaths": False,
            },
            id="single-file",
        ),
        pytest.param(
            {
                "args": ["tests/test_a.py::test_b"],
                "args_from_testpaths": False,
            },
            id="single-node-id",
        ),
        pytest.param(
            {"args": ["tests/architecture"], "args_from_testpaths": False},
            id="subdirectory",
        ),
    ],
)
def test_narrowed_invocations_are_not_full_suite_runs(
    override: dict[str, object],
) -> None:
    """Each of these restricts the selected set, so publishing the result
    as if it were the whole suite would understate the real count."""

    assert not root_conftest.is_full_suite_invocation(
        **{**FULL_SUITE_BASELINE, **override}
    )


def test_an_explicit_junitxml_always_wins_even_on_a_full_suite_run() -> None:
    """tools/generate_test_results_artifact.py runs the full suite with its
    own --junitxml and writes its own sidecar; the hook must not also fire
    and race it."""

    assert not root_conftest.is_full_suite_invocation(
        **{
            **FULL_SUITE_BASELINE,
            "xmlpath": "reports/observability/test_results.junit.xml",
        }
    )


def test_empty_testpaths_with_explicit_args_is_not_a_full_suite_run() -> None:
    assert not root_conftest.is_full_suite_invocation(
        **{
            **FULL_SUITE_BASELINE,
            "args": [],
            "testpaths": [],
            "args_from_testpaths": False,
        }
    )


# =====================================================================
# Completeness: whether a finished run may publish
# =====================================================================


@pytest.mark.parametrize("exit_status", [0, 1])
def test_completed_runs_publish_even_when_tests_failed(exit_status: int) -> None:
    """A red suite is a real result the panel should show - only an
    incomplete one is untrustworthy."""

    assert root_conftest.is_publishable_result(
        exit_status=exit_status,
        deselected_count=0,
        session_stopped_early=False,
    )


@pytest.mark.parametrize(
    "exit_status",
    [2, 3, 4, 5],
    ids=["interrupted", "internal-error", "usage-error", "no-tests-collected"],
)
def test_incomplete_exit_statuses_do_not_publish(exit_status: int) -> None:
    assert not root_conftest.is_publishable_result(
        exit_status=exit_status,
        deselected_count=0,
        session_stopped_early=False,
    )


def test_a_run_cut_short_does_not_publish() -> None:
    """-x / --maxfail can truncate a run that was eligible before it started."""

    assert not root_conftest.is_publishable_result(
        exit_status=1,
        deselected_count=0,
        session_stopped_early=True,
    )


def test_a_run_with_deselected_items_does_not_publish() -> None:
    assert not root_conftest.is_publishable_result(
        exit_status=0,
        deselected_count=3,
        session_stopped_early=False,
    )


# =====================================================================
# sessionfinish behaviour
# =====================================================================


class FakePluginManager:
    def get_plugin(self, name: str) -> None:
        return None


class FakeConfig:
    def __init__(self, state: dict | None) -> None:
        self.stash: dict = {}
        self.args = ["tests"]
        self.pluginmanager = FakePluginManager()

        if state is not None:
            self.stash[root_conftest._STATE_KEY] = state


class FakeSession:
    def __init__(self, config: FakeConfig) -> None:
        self.config = config
        self.shouldstop = False
        self.shouldfail = False


def _state(temp_path: Path) -> dict:
    return {
        "temp_path": temp_path,
        "started_at": datetime.now(UTC),
        "deselected": 0,
    }


def test_sessionfinish_promotes_the_temp_artifact_on_a_clean_full_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Redirect the whole publication at a scratch root so this test can
    # never overwrite the repository's real artifact.
    monkeypatch.setattr(root_conftest, "REPOSITORY_ROOT", tmp_path)

    temp_path = tmp_path / "reports" / "observability" / ".partial.xml"
    temp_path.parent.mkdir(parents=True)
    temp_path.write_text("<testsuite tests='7'/>", encoding="utf-8")

    config = FakeConfig(_state(temp_path))

    root_conftest.pytest_sessionfinish(FakeSession(config), 0)

    artifact = tmp_path / "reports" / "observability" / "test_results.junit.xml"
    meta = tmp_path / "reports" / "observability" / "test_results.meta.json"

    assert artifact.read_text(encoding="utf-8") == "<testsuite tests='7'/>"
    assert not temp_path.exists(), "the temporary file must not be left behind"

    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["pytest_exit_code"] == 0
    assert payload["artifact"] == "reports/observability/test_results.junit.xml"
    assert payload["target"] == "tests"


def test_sessionfinish_discards_the_temp_artifact_on_a_truncated_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(root_conftest, "REPOSITORY_ROOT", tmp_path)

    temp_path = tmp_path / "reports" / "observability" / ".partial.xml"
    temp_path.parent.mkdir(parents=True)
    temp_path.write_text("<testsuite tests='2'/>", encoding="utf-8")

    config = FakeConfig(_state(temp_path))
    session = FakeSession(config)
    session.shouldstop = True

    root_conftest.pytest_sessionfinish(session, 1)

    artifact = tmp_path / "reports" / "observability" / "test_results.junit.xml"

    assert not artifact.exists(), "a truncated run must not publish"
    assert not temp_path.exists(), "the temporary file must still be cleaned up"


def test_sessionfinish_is_a_no_op_when_the_run_was_never_eligible() -> None:
    """No stash state means pytest_configure stood the hook down."""

    config = FakeConfig(None)

    root_conftest.pytest_sessionfinish(FakeSession(config), 0)


def test_a_failing_refresh_never_fails_the_test_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The artifact refresh piggybacks on a real run; a problem in it must
    never turn a green suite red with an INTERNALERROR."""

    monkeypatch.setattr(root_conftest, "REPOSITORY_ROOT", tmp_path)

    def exploding_publish(**_: object) -> None:
        raise RuntimeError("artifact publication blew up")

    monkeypatch.setattr(root_conftest, "_publish", exploding_publish)

    temp_path = tmp_path / ".partial.xml"
    temp_path.write_text("<testsuite tests='7'/>", encoding="utf-8")

    config = FakeConfig(_state(temp_path))

    # Must return normally rather than propagating.
    root_conftest.pytest_sessionfinish(FakeSession(config), 0)

    assert not temp_path.exists(), "the temporary file must still be cleaned up"


# =====================================================================
# Real wiring
# =====================================================================


def _build_mini_repository(root: Path) -> None:
    """Stand up a throwaway repository that uses the real root conftest.

    The conftest is copied verbatim, so its own ``REPOSITORY_ROOT`` resolves
    to this scratch root and every artifact it writes lands here instead of
    in the real repository. ``observability``/``tools`` still import from the
    real tree via PYTHONPATH (see the runner below) - they only supply path
    constants and the sidecar writer, and write nothing on their own.
    """

    (root / "conftest.py").write_bytes(
        (REPOSITORY_ROOT / "conftest.py").read_bytes()
    )
    (root / "pytest.ini").write_text(
        "[pytest]\ntestpaths = minitests\npython_files = test_*.py\n",
        encoding="utf-8",
    )

    minitests = root / "minitests"
    minitests.mkdir()
    (minitests / "test_mini.py").write_text(
        "def test_ok():\n    assert True\n\n\ndef test_ok_too():\n    assert True\n",
        encoding="utf-8",
    )


def _run_mini_pytest(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    import os

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)

    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def test_a_real_full_suite_run_refreshes_the_artifact(tmp_path: Path) -> None:
    """End-to-end proof of the positive path, isolated from the real repo.

    Exercises the whole wiring for real: pytest_configure redirecting
    --junitxml before the junitxml plugin configures, pytest's own LogXML
    writing the file, and pytest_sessionfinish promoting it and stamping the
    sidecar.
    """

    _build_mini_repository(tmp_path)

    completed = _run_mini_pytest(tmp_path)

    assert completed.returncode == 0, (
        f"mini-suite run failed.\nSTDOUT:\n{completed.stdout}\n"
        f"STDERR:\n{completed.stderr}"
    )

    artifact = tmp_path / "reports/observability/test_results.junit.xml"
    meta = tmp_path / "reports/observability/test_results.meta.json"

    assert artifact.is_file(), (
        "a full-suite run did not refresh the artifact.\n"
        f"STDOUT:\n{completed.stdout}"
    )
    assert 'tests="2"' in artifact.read_text(encoding="utf-8")
    assert not (tmp_path / root_conftest.TEMP_ARTIFACT_RELPATH).exists()

    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["pytest_exit_code"] == 0
    assert payload["target"] == "minitests"


def test_a_real_narrow_run_does_not_create_the_artifact(tmp_path: Path) -> None:
    """The same wiring, one node id: nothing may be written at all."""

    _build_mini_repository(tmp_path)

    completed = _run_mini_pytest(tmp_path, "minitests/test_mini.py::test_ok")

    assert completed.returncode == 0, completed.stdout
    assert not (tmp_path / "reports/observability/test_results.junit.xml").exists()
    assert not (tmp_path / root_conftest.TEMP_ARTIFACT_RELPATH).exists()


def test_a_real_narrow_pytest_run_leaves_the_artifact_untouched() -> None:
    """End-to-end proof that the hook stands down for a partial run.

    Runs a single node id in a subprocess against this repository and
    asserts both artifact files are byte-identical afterwards.
    """

    artifact = REPOSITORY_ROOT / "reports/observability/test_results.junit.xml"
    meta = REPOSITORY_ROOT / "reports/observability/test_results.meta.json"

    if not artifact.is_file() or not meta.is_file():
        pytest.skip("no existing artifact to protect in this checkout")

    before = (artifact.read_bytes(), meta.read_bytes())

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_observability_artifact_freshness.py::test_sessionfinish_is_a_no_op_when_the_run_was_never_eligible",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert completed.returncode == 0, (
        f"inner pytest run failed.\nSTDOUT:\n{completed.stdout}\n"
        f"STDERR:\n{completed.stderr}"
    )

    after = (artifact.read_bytes(), meta.read_bytes())

    assert before == after, (
        "a single-node-id run overwrote the full-suite artifact"
    )
