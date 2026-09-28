"""Typed runtime configuration, validated in one pass at startup (CFG-001).

Registry v5.20 records the owner decisions: an invalid configuration ends
the process with exit code 1 (the supervisor retries within its budget),
and an unknown ``ATLAS_*`` environment variable refuses the start - a typo
must never be silently ignored while the operator believes it is in force.

This module adds no setting and changes no default. It reuses the existing
resolve functions of core/application.py, so a valid environment yields
exactly the values AtlasApplication already resolves for itself. Its job
is to report *every* problem at once, before the instance lock is taken
and before any state is touched.

The execution mode is not configurable: main.py fixes it to PAPER, and
``load_config`` refuses anything else while live authority is DENIED.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from core.application import (
    EVIDENCE_DIRECTORY_ENV,
    LOG_DIRECTORY_ENV,
    MARKET_ARCHIVE_DIRECTORY_ENV,
    STATE_DIRECTORY_ENV,
    SUPERVISOR_EPOCH_ENV,
    SUPERVISOR_RESTART_COUNT_ENV,
    ConfiguredDirectoryError,
    resolve_evidence_directory,
    resolve_log_directory,
    resolve_market_archive_directory,
    resolve_state_directory,
)

PERMITTED_EXECUTION_MODE = "PAPER"

HEARTBEAT_FILE_ENV = "ATLAS_SUPERVISOR_HEARTBEAT_FILE"

# Every ATLAS_* variable the runtime reads. Anything else with the prefix
# is refused (owner decision, registry v5.20).
RUNTIME_ATLAS_VARIABLES = frozenset({
    STATE_DIRECTORY_ENV,
    MARKET_ARCHIVE_DIRECTORY_ENV,
    EVIDENCE_DIRECTORY_ENV,
    LOG_DIRECTORY_ENV,
    SUPERVISOR_EPOCH_ENV,
    SUPERVISOR_RESTART_COUNT_ENV,
    HEARTBEAT_FILE_ENV,
})

# Read only by development tools, never by the runtime; tolerated so a
# developer shell does not block Atlas.
TOOL_ONLY_ATLAS_VARIABLES = frozenset({
    "ATLAS_PYTEST_BASETEMP",
})

_ATLAS_PREFIX = "ATLAS_"


class AtlasConfigError(RuntimeError):
    """The configuration is invalid; ``errors`` lists every problem found."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class AtlasConfig:
    execution_mode: str
    paper_confidence_experiment: bool
    state_directory: Path
    market_archive_directory: Path
    evidence_directory: Path
    log_directory: Path | None

    def describe(self) -> dict[str, str]:
        """Effective values for display. Holds no secrets by construction."""

        return {
            "execution_mode": self.execution_mode,
            "paper_confidence_experiment": str(self.paper_confidence_experiment),
            "state_directory": str(self.state_directory),
            "market_archive_directory": str(self.market_archive_directory),
            "evidence_directory": str(self.evidence_directory),
            "log_directory": str(self.log_directory) if self.log_directory else "(not configured)",
        }


def load_config(
    environ: Mapping[str, str],
    *,
    execution_mode: str,
    paper_confidence_experiment: bool,
) -> AtlasConfig:
    """Validate everything; raise AtlasConfigError listing all problems.

    The directory resolvers read ``os.environ``; ``environ`` is used for the
    unknown-variable check and must be the same process environment in
    production (main.py passes ``os.environ``).
    """

    errors: list[str] = []

    mode = str(execution_mode).strip().upper()
    if mode != PERMITTED_EXECUTION_MODE:
        errors.append(
            f"execution_mode {execution_mode!r} is refused: only PAPER is permitted "
            f"(live_authority=DENIED)"
        )

    for name in sorted(environ):
        if name.upper().startswith(_ATLAS_PREFIX) and name.upper() not in (
            RUNTIME_ATLAS_VARIABLES | TOOL_ONLY_ATLAS_VARIABLES
        ):
            errors.append(
                f"unknown environment variable {name}: Atlas does not read it "
                f"(a typo, or a setting this runtime does not have). Unset it."
            )

    resolved: dict[str, object] = {}
    for key, resolver in (
        ("state_directory", resolve_state_directory),
        ("market_archive_directory", resolve_market_archive_directory),
        ("evidence_directory", resolve_evidence_directory),
        ("log_directory", resolve_log_directory),
    ):
        try:
            resolved[key] = resolver()
        except ConfiguredDirectoryError as exc:
            errors.append(str(exc))

    if errors:
        raise AtlasConfigError(errors)

    return AtlasConfig(
        execution_mode=mode,
        paper_confidence_experiment=bool(paper_confidence_experiment),
        **resolved,
    )
