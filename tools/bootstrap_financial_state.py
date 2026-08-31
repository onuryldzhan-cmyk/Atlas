"""
============================================================
ATLAS OPERATOR FINANCIAL-STATE BOOTSTRAP
============================================================

Explicit, operator-invoked entry point that creates or validates the three
canonical durable financial-state stores:

- risk_accounting_state.json
- capital_reservations.json
- execution_financial_state.json

This tool is never called by AtlasApplication. Startup remains fail-closed:
a missing or corrupt store leaves the corresponding service not-ready and
Atlas refuses new risk. Running this tool is a deliberate operator action.

It never overwrites, repairs, deletes, or migrates an existing state file.
An existing store is loaded through its own canonical validator and reported
as VALID_EXISTING or INVALID_EXISTING; diagnosing and resolving an
INVALID_EXISTING store is an operator decision made outside this tool.

It has no LIVE authority: there is no mode switch, no --force, no --repair,
and no --overwrite. It reads and writes only the three files above, under the
state directory the operator names explicitly.

See docs/adr/0005-operator-bootstrap-runbook.md.
============================================================
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from atlas_security import sanitize_sensitive_text  # noqa: E402
from core.financial_state_bootstrap import (  # noqa: E402
    BootstrapOutcome,
    FinancialStateBootstrapResult,
    bootstrap_financial_state,
)
from core.risk_engine import RiskPolicy  # noqa: E402
from portfolio.capital_manager import CapitalManager  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_INVALID_EXISTING = 2
EXIT_FAILED = 3


class _UsageExitParser(argparse.ArgumentParser):
    """argparse exits 2 on usage errors, which would collide with this
    tool's exit code 2 (INVALID_EXISTING) and make a provisioning script
    read a mistyped flag as corrupt financial state."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def canonical_policy(total_capital: Decimal | None = None) -> RiskPolicy:
    """Build the same RiskPolicy the composition root builds.

    Capital defaults to the canonical CapitalManager configuration rather
    than to a literal repeated here, so policy version, allocatable capital,
    and total capital all trace back to one source.
    """
    if total_capital is None:
        total_capital = Decimal(str(CapitalManager().total_capital))
    return RiskPolicy(total_capital=total_capital)


def _decimal_argument(raw: str) -> Decimal:
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"not a valid decimal: {raw!r}") from exc
    if not value.is_finite() or value <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite decimal")
    return value


def _date_argument(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = _UsageExitParser(
        prog="bootstrap_financial_state",
        description=(
            "Create or validate Atlas durable financial state. PAPER-only; "
            "never overwrites, repairs, or migrates existing state."
        ),
    )
    parser.add_argument(
        "--state-directory", required=True, type=Path,
        help="Explicit durable state directory. Required; there is no default.",
    )
    parser.add_argument(
        "--total-capital", type=_decimal_argument, default=None,
        help="Override canonical total capital. Defaults to the canonical "
             "CapitalManager configuration.",
    )
    parser.add_argument(
        "--policy-version", type=str, default=None,
        help="Override canonical risk policy version. Defaults to the "
             "canonical RiskPolicy version.",
    )
    parser.add_argument(
        "--today-utc", type=_date_argument, default=None,
        help="Deterministic UTC accounting date (YYYY-MM-DD). Testing input.",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit a structured JSON result instead of the human table.",
    )
    parser.add_argument(
        "--verify-only", action="store_true",
        help="Validate existing state only. Creates and modifies nothing.",
    )
    return parser


def _exit_code(result: FinancialStateBootstrapResult) -> int:
    outcomes = {item.outcome for item in result.results}
    if BootstrapOutcome.FAILED in outcomes:
        return EXIT_FAILED
    if BootstrapOutcome.INVALID_EXISTING in outcomes:
        return EXIT_INVALID_EXISTING
    return EXIT_OK


def _render_human(result: FinancialStateBootstrapResult, exit_code: int) -> str:
    lines = ["store | path | outcome | reason_code"]
    for item in result.results:
        lines.append(
            f"{item.store} | {sanitize_sensitive_text(item.path)} | "
            f"{item.outcome.value} | {sanitize_sensitive_text(item.reason_code)}"
        )
    verdict = "OK" if exit_code == EXIT_OK else "ACTION_REQUIRED"
    lines.append(f"verdict: {verdict} (exit {exit_code})")
    return "\n".join(lines)


def _render_json(result: FinancialStateBootstrapResult, exit_code: int) -> str:
    return json.dumps(
        {
            "policy_version": sanitize_sensitive_text(result.policy_version),
            "succeeded": result.succeeded,
            "exit_code": exit_code,
            "stores": [
                {
                    "store": item.store,
                    "path": sanitize_sensitive_text(item.path),
                    "outcome": item.outcome.value,
                    "reason_code": sanitize_sensitive_text(item.reason_code),
                }
                for item in result.results
            ],
        },
        indent=2, sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    policy = canonical_policy(arguments.total_capital)
    if arguments.policy_version is not None and not arguments.policy_version.strip():
        # An explicitly blank override must fail rather than silently
        # falling back to the canonical version.
        parser.error("--policy-version must not be blank")
    policy_version = arguments.policy_version or policy.version

    state_directory = Path(arguments.state_directory)

    try:
        result = bootstrap_financial_state(
            state_directory=state_directory,
            initial_capital=policy.total_capital,
            allocatable_capital=policy.allocatable_capital,
            policy_version=policy_version,
            today_utc=arguments.today_utc,
            verify_only=arguments.verify_only,
        )
    except ValueError as exc:
        parser.error(sanitize_sensitive_text(str(exc)))
        return EXIT_USAGE

    exit_code = _exit_code(result)
    rendered = (
        _render_json(result, exit_code) if arguments.as_json
        else _render_human(result, exit_code)
    )
    print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
