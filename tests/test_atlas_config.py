"""CFG-001: one-pass configuration validation at startup (registry v5.20/v5.21)."""

from __future__ import annotations

import pytest

import main
from core import atlas_config
from core.application import (
    resolve_evidence_directory,
    resolve_log_directory,
    resolve_market_archive_directory,
    resolve_state_directory,
)
from core.atlas_config import (
    RUNTIME_ATLAS_VARIABLES,
    AtlasConfigError,
    load_config,
)


def _load(environ=None, mode="PAPER"):
    import os
    return load_config(os.environ if environ is None else environ,
                       execution_mode=mode, paper_confidence_experiment=True)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    dirs = {}
    for var in ("ATLAS_STATE_DIRECTORY", "ATLAS_MARKET_ARCHIVE_DIRECTORY", "ATLAS_EVIDENCE_DIRECTORY"):
        d = tmp_path / var.lower()
        d.mkdir()
        monkeypatch.setenv(var, str(d))
        dirs[var] = d
    return dirs


def test_valid_environment_matches_what_application_resolves(roots):
    config = _load()
    assert config.execution_mode == "PAPER"
    assert config.state_directory == resolve_state_directory()
    assert config.market_archive_directory == resolve_market_archive_directory()
    assert config.evidence_directory == resolve_evidence_directory()
    assert config.log_directory == resolve_log_directory()


@pytest.mark.parametrize("mode", ["LIVE", "SHADOW", "live", "", "PAPERX"])
def test_non_paper_mode_is_refused(roots, mode):
    with pytest.raises(AtlasConfigError) as exc:
        _load(mode=mode)
    assert "only PAPER is permitted" in str(exc.value)


def test_lowercase_paper_is_normalised(roots):
    assert _load(mode=" paper ").execution_mode == "PAPER"


@pytest.mark.parametrize("name", ["ATLAS_STATE_DIRECTRY", "ATLAS_EXECUTION_MODE",
                                  "ATLAS_LIVE_ENABLED", "atlas_kill_switch"])
def test_unknown_atlas_variable_refuses_start(roots, monkeypatch, name):
    monkeypatch.setenv(name, "x")
    import os
    with pytest.raises(AtlasConfigError) as exc:
        _load(dict(os.environ))
    assert any(name in e for e in exc.value.errors)


def test_tool_only_and_non_atlas_variables_are_tolerated(roots, monkeypatch):
    monkeypatch.setenv("ATLAS_PYTEST_BASETEMP", "x")
    monkeypatch.setenv("PATH_EXTRA_ATLAS", "x")
    monkeypatch.setenv("ATLASX", "x")
    _load()


def test_every_problem_is_reported_at_once(roots, monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", "relative/path")
    monkeypatch.setenv("ATLAS_EVIDENCE_DIRECTORY", str(tmp_path / "missing"))
    monkeypatch.setenv("ATLAS_TYPO", "1")
    with pytest.raises(AtlasConfigError) as exc:
        _load(mode="LIVE")
    joined = " | ".join(exc.value.errors)
    assert len(exc.value.errors) == 4
    assert "ATLAS_STATE_DIRECTORY" in joined and "ATLAS_EVIDENCE_DIRECTORY" in joined
    assert "ATLAS_TYPO" in joined and "only PAPER" in joined


def test_runtime_variable_list_covers_every_name_the_runtime_reads():
    import atlas_supervisor
    from core import application
    assert {application.STATE_DIRECTORY_ENV, application.MARKET_ARCHIVE_DIRECTORY_ENV,
            application.EVIDENCE_DIRECTORY_ENV, application.LOG_DIRECTORY_ENV,
            application.SUPERVISOR_EPOCH_ENV, application.SUPERVISOR_RESTART_COUNT_ENV,
            main.HEARTBEAT_FILE_ENV, atlas_supervisor.ENV_EPOCH,
            atlas_supervisor.ENV_RESTART_COUNT, atlas_supervisor.ENV_HEARTBEAT_FILE,
            atlas_supervisor.LOG_DIRECTORY_ENV} <= RUNTIME_ATLAS_VARIABLES
    assert atlas_config.HEARTBEAT_FILE_ENV == main.HEARTBEAT_FILE_ENV


def test_main_mode_is_paper_and_passes_its_own_validation(roots):
    assert main.EXECUTION_MODE == "PAPER"
    # Test policy change 2026-10-01: the owner switched on EXP-002 (EXP-001 stays stopped, v5.71).
    assert main.PAPER_CONFIDENCE_EXPERIMENT is True and main.PAPER_CONFIDENCE_EXPERIMENT_ID == "EXP-002"
    config = load_config({}, execution_mode=main.EXECUTION_MODE,
                         paper_confidence_experiment=main.PAPER_CONFIDENCE_EXPERIMENT)
    assert config.execution_mode == "PAPER"


def test_every_allowlisted_variable_at_once_is_accepted(roots, tmp_path):
    environ = {name: "x" for name in RUNTIME_ATLAS_VARIABLES}
    # 2026-10-02: ATLAS_FILL_MODEL is the first allowlisted variable whose VALUE is validated
    # (LAST_PRICE or BOOK); "x" is rightly refused, so it gets its default. The name check stays.
    environ["ATLAS_FILL_MODEL"] = "LAST_PRICE"
    # Task 019: ATLAS_MARKET is the second (CRYPTO or FOREX); the same pattern applies.
    environ["ATLAS_MARKET"] = "CRYPTO"
    config = load_config(environ, execution_mode="PAPER", paper_confidence_experiment=True)
    assert config.execution_mode == "PAPER"


def test_no_runtime_module_reads_an_atlas_variable_missing_from_the_allowlist():
    """Drift guard: scans every runtime-closure module for ATLAS_* names used
    as environment variables, so a new one cannot be refused at start."""
    import json
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    modules = json.loads((root / "packaging" / "atlas_runtime_closure.json").read_text(encoding="utf-8"))["modules"]
    env_constant = re.compile(r'[A-Z_]*ENV[A-Z_]*\s*=\s*"(ATLAS_[A-Z0-9_]+)"')
    env_read = re.compile(r'(?:environ(?:\.get)?\s*[\[(]|getenv\s*\(|environment_variable\s*=)\s*"(ATLAS_[A-Z0-9_]+)"')
    found = set()
    for module in modules + ["main.py", "atlas_supervisor.py", "atlas_service.py"]:
        text = (root / module).read_text(encoding="utf-8-sig")
        found |= set(env_constant.findall(text)) | set(env_read.findall(text))
    assert found, "scan found nothing - the pattern is broken"
    assert found <= RUNTIME_ATLAS_VARIABLES, sorted(found - RUNTIME_ATLAS_VARIABLES)


def test_windows_style_uppercase_environment_is_matched(roots):
    with pytest.raises(AtlasConfigError):
        load_config({"ATLAS_STATE_DIRECTRY": "x"}, execution_mode="PAPER", paper_confidence_experiment=True)


def test_invalid_config_stops_before_lock_with_exit_1(roots, monkeypatch):
    monkeypatch.setenv("ATLAS_TYPO", "1")
    calls = []
    process = main.AtlasProcess.__new__(main.AtlasProcess)
    process.exit_code = 0
    process.shutdown_reason = ""
    monkeypatch.setattr(main.AtlasProcess, "_acquire_instance_lock",
                        lambda self: calls.append("lock") or True)
    assert process.start() is False
    assert process.exit_code == 1
    assert calls == []
    assert "Invalid configuration" in process.shutdown_reason


def test_show_config_tool(roots, monkeypatch, capsys):
    from tools import show_config
    assert show_config.main() == 0
    out = capsys.readouterr().out
    assert "execution_mode: PAPER" in out and "OK" in out
    monkeypatch.setenv("ATLAS_TYPO", "1")
    assert show_config.main() == 1
    assert "ATLAS_TYPO" in capsys.readouterr().out
