"""Repository-root pytest configuration.

Keeps the observability panel's test-results artifact fresh automatically.

Why this exists
---------------
``observability.panel_sources.read_test_results_panel`` renders the dashboard's
"Test Sonuçları" panel from ``reports/observability/test_results.junit.xml``
plus its ``.meta.json`` sidecar. Those files are produced by
``tools/generate_test_results_artifact.py``, a manual on-demand script, and are
gitignored - so nothing refreshes them unless an operator remembers to run that
script, and the panel silently shows a months-old count until they do. That is
exactly the staleness this hook removes: a normal local full-suite run now
refreshes the artifact as a side effect.

How it works
------------
``pytest_configure`` points pytest's own built-in ``--junitxml`` machinery at a
temporary file (so the XML is produced by the same code path the manual script
triggers - never a reimplementation of pytest's XML format), and
``pytest_sessionfinish`` promotes that temporary file over the real artifact and
writes the provenance sidecar via the script's own
``write_meta_sidecar``.

Two properties this must never violate
--------------------------------------
1. A narrow run must never overwrite the artifact. A ``-k``-filtered run, a
   single-file run, or a run cut short by ``-x`` would publish a
   misleadingly low count that looks like the whole suite. Eligibility is
   therefore decided from pytest's *parsed options* (never argv string
   matching) before collection, and re-checked for completeness after the run;
   anything that restricts or truncates the selected set stands the hook down
   and leaves the existing artifact untouched.
2. This bookkeeping must never fail a test run. Every hook body is wrapped:
   an exception here would otherwise surface as a pytest INTERNALERROR and
   turn a green suite red for a reporting-mechanism problem.
"""

from __future__ import annotations

import os
import sys

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parent

# Written by pytest's junitxml plugin, then promoted over the real artifact
# only once the run is known to have been a complete full-suite run. Lives
# beside the artifact (same directory, therefore same filesystem) so the
# promotion is a single atomic replace rather than a copy.
TEMP_ARTIFACT_RELPATH = "reports/observability/.test_results.junit.xml.partial"

# pytest exit statuses that represent a run which actually completed.
# 0 = all passed, 1 = tests failed (still a complete, publishable result -
# a red suite is exactly what the panel should show). Everything else
# (2 interrupted, 3 internal error, 4 usage error, 5 no tests collected)
# means the result set is not a trustworthy picture of the suite.
_COMPLETE_EXIT_STATUSES = frozenset({0, 1})

_STATE_KEY = pytest.StashKey[dict]()


def is_full_suite_invocation(
    *,
    args: Sequence[str],
    testpaths: Sequence[str],
    args_from_testpaths: bool,
    keyword: str,
    markexpr: str,
    deselect: Sequence[str] | None,
    last_failed: bool,
    stepwise: bool,
    collect_only: bool,
    xmlpath: str | None,
    is_xdist_worker: bool,
) -> bool:
    """Decide whether this invocation selects the entire suite.

    Deliberately takes plain values rather than a ``Config`` so the decision
    is exhaustively testable without constructing a pytest session, and so
    every input is visible in one signature.

    The inputs are pytest's *parsed* options, not raw argv text: ``-k x`` and
    ``-k=x``, ``--junitxml`` and its ``--junit-xml`` alias, and every other
    spelling collapse to the same parsed value, which argv substring matching
    would miss.

    Note what is deliberately NOT disqualifying: ``--ff``/``--nf`` reorder the
    suite but still run all of it, and ``-x``/``--maxfail`` only *might*
    truncate - whether they actually did is knowable after the run, and is
    checked then (see ``is_publishable_result``) rather than pessimistically
    assumed here.
    """

    # An explicit --junitxml means someone else owns the output path -
    # including tools/generate_test_results_artifact.py's own subprocess run,
    # which passes the artifact path directly and writes its own sidecar.
    # Never fight that.
    if xmlpath:
        return False

    # xdist workers each see a shard of the suite; only the controller has
    # the whole picture. pytest's own junitxml plugin guards the same way.
    if is_xdist_worker:
        return False

    # --collect-only produces no results to publish.
    if collect_only:
        return False

    # Every one of these restricts which collected tests actually run.
    if keyword or markexpr or deselect or last_failed or stepwise:
        return False

    # Either no path arguments were given (so pytest fell back to the
    # testpaths ini, which is by definition the whole suite), or the paths
    # given are exactly the testpaths. Anything narrower - one file, one
    # node id, one subdirectory - is not a full-suite run.
    if args_from_testpaths:
        return True

    return list(args) == list(testpaths) and bool(testpaths)


def is_publishable_result(
    *,
    exit_status: int,
    deselected_count: int,
    session_stopped_early: bool,
) -> bool:
    """Decide whether a finished, eligible run may overwrite the artifact.

    Catches what eligibility could not know before the run: a suite cut short
    by ``-x``/``--maxfail`` or Ctrl-C, and items removed by a plugin's
    deselection hook after collection.
    """

    if session_stopped_early:
        return False

    if deselected_count:
        return False

    return exit_status in _COMPLETE_EXIT_STATUSES


def _temp_artifact_path() -> Path:
    return REPOSITORY_ROOT / TEMP_ARTIFACT_RELPATH


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Route this run's JUnit XML to a temporary file when eligible.

    Runs ``tryfirst`` because pytest's junitxml plugin reads
    ``config.option.xmlpath`` in its own ``pytest_configure`` to decide
    whether to register its ``LogXML`` reporter; setting it afterwards would
    have no effect.
    """

    try:
        eligible = is_full_suite_invocation(
            args=config.args,
            testpaths=config.getini("testpaths"),
            args_from_testpaths=(
                config.args_source == pytest.Config.ArgsSource.TESTPATHS
            ),
            keyword=config.getoption("keyword", ""),
            markexpr=config.getoption("markexpr", ""),
            deselect=config.getoption("deselect", None),
            last_failed=bool(config.getoption("lf", False)),
            stepwise=bool(config.getoption("stepwise", False)),
            collect_only=bool(config.getoption("collectonly", False)),
            xmlpath=config.getoption("xmlpath", None),
            is_xdist_worker=hasattr(config, "workerinput"),
        )

        if not eligible:
            return

        temp_path = _temp_artifact_path()
        temp_path.parent.mkdir(parents=True, exist_ok=True)

        # Stash before redirecting xmlpath, never after: if anything below
        # failed in between, the session would write a temporary file that
        # sessionfinish had no record of, and so would never clean up.
        config.stash[_STATE_KEY] = {
            "temp_path": temp_path,
            "started_at": datetime.now(UTC),
            "deselected": 0,
        }
        config.option.xmlpath = str(temp_path)

    except Exception:  # never let artifact bookkeeping break a test run
        pass


def pytest_deselected(items: Sequence[Any]) -> None:
    """Record deselections so a partially-deselected run cannot publish."""

    if not items:
        return

    try:
        config = items[0].config
    except Exception:
        return

    state = config.stash.get(_STATE_KEY, None)

    if state:
        state["deselected"] = state.get("deselected", 0) + len(items)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(
    session: pytest.Session,
    exitstatus: int,
) -> None:
    """Promote the temporary XML over the real artifact, or discard it.

    Runs ``trylast`` so pytest's own ``LogXML.pytest_sessionfinish`` has
    already written the temporary file by the time this executes.
    """

    config = session.config
    state = config.stash.get(_STATE_KEY, None)

    if not state:
        return

    temp_path = state.get("temp_path")

    if not isinstance(temp_path, Path):
        return

    try:
        publishable = is_publishable_result(
            exit_status=int(exitstatus),
            deselected_count=state.get("deselected", 0),
            session_stopped_early=bool(
                getattr(session, "shouldstop", False)
                or getattr(session, "shouldfail", False)
            ),
        )

        if not publishable or not temp_path.is_file():
            return

        _publish(
            config=config,
            session=session,
            exitstatus=int(exitstatus),
            started_at=state["started_at"],
            temp_path=temp_path,
        )

    except Exception:
        # Deliberately silent and non-fatal: a stale artifact is a cosmetic
        # dashboard problem, a raised exception here is an INTERNALERROR that
        # would report a green suite as failed.
        pass

    finally:
        _discard_temp(temp_path)


def _publish(
    *,
    config: pytest.Config,
    session: pytest.Session,
    exitstatus: int,
    started_at: datetime,
    temp_path: Path,
) -> None:
    """Move the temporary XML into place and stamp the provenance sidecar."""

    if str(REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT))

    # Imported here rather than at module import: conftest is imported for
    # every pytest run in this repository, and a problem in either module
    # must not be able to break collection - only this optional refresh.
    from observability.panel_sources import (
        TEST_RESULTS_ARTIFACT_RELPATH,
        read_head_commit,
    )
    from tools.generate_test_results_artifact import write_meta_sidecar

    artifact_path = REPOSITORY_ROOT / TEST_RESULTS_ARTIFACT_RELPATH
    artifact_path.parent.mkdir(parents=True, exist_ok=True)

    os.replace(temp_path, artifact_path)

    write_meta_sidecar(
        repository_root=REPOSITORY_ROOT,
        commit=read_head_commit(REPOSITORY_ROOT),
        started_at=started_at,
        finished_at=datetime.now(UTC),
        command=list(sys.argv),
        pytest_exit_code=exitstatus,
        target=" ".join(config.args),
    )

    reporter = config.pluginmanager.get_plugin("terminalreporter")

    if reporter is not None:
        reporter.write_line(
            f"observability: refreshed {TEST_RESULTS_ARTIFACT_RELPATH}",
        )


def _discard_temp(temp_path: Path) -> None:
    try:
        temp_path.unlink(missing_ok=True)
    except Exception:
        pass
