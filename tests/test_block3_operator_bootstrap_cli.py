"""Block 3 / Package 2, M-F: operator bootstrap CLI contract.

The CLI is the only supported operator workflow for creating durable
financial state. It must never overwrite/repair/migrate existing state,
never carry LIVE authority, never print state-file contents or secrets, and
must report failure through a machine-detectable non-zero exit code.

Exit-code contract:
    0  every store CREATED or VALID_EXISTING
    1  CLI usage / argument error
    2  at least one INVALID_EXISTING
    3  at least one FAILED
"""

from __future__ import annotations

import ast
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

import core.application as application_module
import tools.bootstrap_financial_state as cli_module
from core.financial_state_bootstrap import BootstrapOutcome

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = REPOSITORY_ROOT / "tools" / "bootstrap_financial_state.py"

STATE_FILES = (
    "risk_accounting_state.json",
    "capital_reservations.json",
    "execution_financial_state.json",
)


def run_cli(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *arguments],
        capture_output=True, text=True, cwd=str(REPOSITORY_ROOT),
    )


def outcomes(completed: subprocess.CompletedProcess) -> dict[str, str]:
    """Parse the human table's outcome column into {store: outcome}.

    Substring counting is unusable here: 'BOOTSTRAP_CREATED' contains
    'CREATED' and 'STATE_VALID_EXISTING' contains 'VALID_EXISTING'.
    """
    parsed = {}
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) == 4 and parts[0] != "store":
            parsed[parts[0]] = parts[2]
    return parsed


# ---------------------------------------------------------------------------
# exit-code contract
# ---------------------------------------------------------------------------


def test_fresh_directory_creates_all_three_stores_and_exits_zero(tmp_path):
    completed = run_cli("--state-directory", str(tmp_path), "--today-utc", "2026-01-01")
    assert completed.returncode == 0
    assert set(outcomes(completed).values()) == {"CREATED"}
    for name in STATE_FILES:
        assert (tmp_path / name).exists()


def test_existing_valid_state_exits_zero_as_valid_existing(tmp_path):
    assert run_cli("--state-directory", str(tmp_path), "--today-utc", "2026-01-01").returncode == 0
    completed = run_cli("--state-directory", str(tmp_path), "--today-utc", "2026-01-01")
    assert completed.returncode == 0
    assert set(outcomes(completed).values()) == {"VALID_EXISTING"}


def test_corrupt_state_exits_two_and_leaves_file_untouched(tmp_path):
    corrupt = tmp_path / "risk_accounting_state.json"
    corrupt.write_text("}{ not json", encoding="utf-8")
    before = corrupt.read_bytes()

    completed = run_cli("--state-directory", str(tmp_path), "--today-utc", "2026-01-01")
    assert completed.returncode == 2
    assert "INVALID_EXISTING" in completed.stdout
    assert corrupt.read_bytes() == before


def test_policy_version_mismatch_exits_two(tmp_path):
    assert run_cli(
        "--state-directory", str(tmp_path), "--today-utc", "2026-01-01",
    ).returncode == 0

    completed = run_cli(
        "--state-directory", str(tmp_path), "--today-utc", "2026-01-01",
        "--policy-version", "a-different-policy",
    )
    assert completed.returncode == 2
    assert "POLICY_VERSION_MISMATCH" in completed.stdout


def test_missing_required_state_directory_is_usage_error(tmp_path):
    completed = run_cli()
    # Must be 1, not argparse's default 2, which would be indistinguishable
    # from INVALID_EXISTING to a calling script.
    assert completed.returncode == 1
    assert "state-directory" in completed.stderr


def test_invalid_decimal_argument_is_usage_error(tmp_path):
    completed = run_cli(
        "--state-directory", str(tmp_path), "--total-capital", "not-a-number",
    )
    assert completed.returncode == 1
    assert "total-capital" in completed.stderr or "decimal" in completed.stderr


def test_non_positive_total_capital_is_rejected(tmp_path):
    completed = run_cli("--state-directory", str(tmp_path), "--total-capital", "0")
    assert completed.returncode == 1
    assert not (tmp_path / "risk_accounting_state.json").exists()


def test_invalid_today_utc_is_usage_error(tmp_path):
    completed = run_cli(
        "--state-directory", str(tmp_path), "--today-utc", "01-01-2026",
    )
    assert completed.returncode == 1
    assert "YYYY-MM-DD" in completed.stderr


def test_usage_errors_never_collide_with_state_outcome_exit_codes(tmp_path):
    # A usage error must be distinguishable from INVALID_EXISTING (2) and
    # FAILED (3) so provisioning automation can branch correctly.
    for arguments in (
        (),
        ("--state-directory", str(tmp_path), "--total-capital", "-5"),
        ("--state-directory", str(tmp_path), "--policy-version", ""),
        ("--state-directory", str(tmp_path), "--unknown-flag"),
    ):
        completed = run_cli(*arguments)
        assert completed.returncode == 1, arguments


# ---------------------------------------------------------------------------
# --verify-only
# ---------------------------------------------------------------------------


def test_verify_only_creates_nothing_on_empty_directory_and_exits_two(tmp_path):
    completed = run_cli("--state-directory", str(tmp_path), "--verify-only")
    assert completed.returncode == 2
    assert "STATE_ABSENT" in completed.stdout
    assert list(tmp_path.iterdir()) == []


def test_verify_only_on_valid_state_exits_zero_and_modifies_nothing(tmp_path):
    assert run_cli("--state-directory", str(tmp_path), "--today-utc", "2026-01-01").returncode == 0
    before = {name: (tmp_path / name).read_bytes() for name in STATE_FILES}

    completed = run_cli("--state-directory", str(tmp_path), "--verify-only")
    assert completed.returncode == 0
    assert set(outcomes(completed).values()) == {"VALID_EXISTING"}
    for name in STATE_FILES:
        assert (tmp_path / name).read_bytes() == before[name]


def test_verify_only_on_corrupt_state_exits_two_and_modifies_nothing(tmp_path):
    assert run_cli("--state-directory", str(tmp_path), "--today-utc", "2026-01-01").returncode == 0
    corrupt = tmp_path / "capital_reservations.json"
    corrupt.write_text("}{ not json", encoding="utf-8")
    before = corrupt.read_bytes()

    completed = run_cli("--state-directory", str(tmp_path), "--verify-only")
    assert completed.returncode == 2
    assert corrupt.read_bytes() == before


def test_verify_only_does_not_create_a_partially_missing_store(tmp_path):
    assert run_cli("--state-directory", str(tmp_path), "--today-utc", "2026-01-01").returncode == 0
    (tmp_path / "capital_reservations.json").unlink()

    completed = run_cli("--state-directory", str(tmp_path), "--verify-only")
    assert completed.returncode == 2
    assert not (tmp_path / "capital_reservations.json").exists()
    # The stores that do exist are still validated rather than skipped.
    assert outcomes(completed) == {
        "risk_accounting_state": "VALID_EXISTING",
        "capital_reservations": "INVALID_EXISTING",
        "execution_financial_state": "VALID_EXISTING",
    }
    assert "STATE_ABSENT" in completed.stdout


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def test_json_output_is_structured_and_machine_detectable(tmp_path):
    completed = run_cli(
        "--state-directory", str(tmp_path), "--today-utc", "2026-01-01", "--json",
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["succeeded"] is True
    assert payload["exit_code"] == 0
    assert {item["store"] for item in payload["stores"]} == {
        "risk_accounting_state", "capital_reservations", "execution_financial_state",
    }
    assert {item["outcome"] for item in payload["stores"]} == {"CREATED"}


def test_json_output_reports_invalid_existing(tmp_path):
    (tmp_path / "execution_financial_state.json").write_text("}{", encoding="utf-8")
    completed = run_cli(
        "--state-directory", str(tmp_path), "--today-utc", "2026-01-01", "--json",
    )
    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["succeeded"] is False
    assert payload["exit_code"] == 2


# ---------------------------------------------------------------------------
# output safety
# ---------------------------------------------------------------------------


def test_output_never_contains_state_file_contents(tmp_path):
    assert run_cli("--state-directory", str(tmp_path), "--today-utc", "2026-01-01").returncode == 0
    financial_contents = (tmp_path / "execution_financial_state.json").read_text(encoding="utf-8")

    completed = run_cli("--state-directory", str(tmp_path), "--verify-only")
    assert financial_contents not in completed.stdout
    assert "applied_executions" not in completed.stdout
    assert "schema_version" not in completed.stdout


def test_reason_codes_are_fixed_tokens_not_exception_text(tmp_path):
    (tmp_path / "risk_accounting_state.json").write_text("}{ not json", encoding="utf-8")
    completed = run_cli(
        "--state-directory", str(tmp_path), "--today-utc", "2026-01-01", "--json",
    )
    payload = json.loads(completed.stdout)
    risk = next(item for item in payload["stores"] if item["store"] == "risk_accounting_state")
    assert risk["reason_code"] == "RISK_STATE_UNREADABLE"
    assert "Expecting" not in completed.stdout  # no raw json.JSONDecodeError text


# ---------------------------------------------------------------------------
# LIVE / PAPER authority and startup isolation
# ---------------------------------------------------------------------------


def test_cli_exposes_no_live_or_destructive_flags():
    parser = cli_module.build_parser()
    option_strings = {
        option for action in parser._actions for option in action.option_strings
    }
    for forbidden in ("--live", "--force", "--repair", "--overwrite", "--mode", "--migrate"):
        assert forbidden not in option_strings


def test_cli_never_constructs_a_runtime_or_selects_an_execution_mode():
    # Inspect the executable code, not the module docstring (which
    # legitimately explains that AtlasApplication never calls this tool).
    tree = ast.parse(CLI_PATH.read_text(encoding="utf-8"))
    names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    for forbidden in ("AtlasApplication", "ExecutionManager", "execution_mode"):
        assert forbidden not in names


def test_cli_rejects_unknown_flags(tmp_path):
    completed = run_cli("--state-directory", str(tmp_path), "--force")
    assert completed.returncode == 1
    assert not (tmp_path / "risk_accounting_state.json").exists()


def test_application_startup_still_does_not_invoke_bootstrap_or_cli():
    source = inspect.getsource(application_module)
    assert "financial_state_bootstrap" not in source
    assert "bootstrap_financial_state" not in source


def test_cli_never_touches_legacy_paper_trades(tmp_path):
    source = inspect.getsource(cli_module)
    assert "paper_trades" not in source

    legacy = tmp_path / "paper_trades.json"
    legacy.write_text('{"trades": []}', encoding="utf-8")
    before = legacy.read_bytes()

    assert run_cli("--state-directory", str(tmp_path), "--today-utc", "2026-01-01").returncode == 0
    assert legacy.read_bytes() == before


def test_cli_has_no_default_state_directory():
    parser = cli_module.build_parser()
    action = next(a for a in parser._actions if "--state-directory" in a.option_strings)
    assert action.required is True
    assert action.default is None


# ---------------------------------------------------------------------------
# canonical defaults are derived, not duplicated
# ---------------------------------------------------------------------------


def test_canonical_policy_is_derived_from_capital_manager():
    from decimal import Decimal as D

    from portfolio.capital_manager import CapitalManager
    from core.risk_engine import RiskPolicy

    expected = RiskPolicy(total_capital=D(str(CapitalManager().total_capital)))
    policy = cli_module.canonical_policy()
    assert policy.total_capital == expected.total_capital
    assert policy.version == expected.version
    assert policy.allocatable_capital == expected.allocatable_capital


def test_cli_does_not_hard_code_financial_policy_literals():
    source = inspect.getsource(cli_module)
    assert "phase3-risk-v1" not in source
    assert "10000" not in source
    assert "0.8" not in source


def test_cli_default_run_writes_canonically_compatible_state(tmp_path):
    from datetime import date

    from core.risk_state_store import JsonRiskStateStore

    assert run_cli("--state-directory", str(tmp_path), "--today-utc", "2026-01-01").returncode == 0

    policy = cli_module.canonical_policy()
    restored = JsonRiskStateStore(tmp_path / "risk_accounting_state.json").load(
        expected_policy_version=policy.version, today_utc=date(2026, 1, 1),
    )
    assert restored.policy_version == policy.version
    assert restored.current_equity == policy.total_capital
