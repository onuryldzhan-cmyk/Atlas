"""D7 / S5: PAPER/default-deny posture must remain explicit.

The live composition root must never activate LIVE execution by default.
This is a black-box construction of the real AtlasApplication (no mocking).
"""

from __future__ import annotations

from pathlib import Path

from core.application import AtlasApplication
from core.execution_manager import ExecutionManager


def test_live_execution_is_denied_by_default(tmp_path: Path) -> None:
    # Constructed against tmp_path, never the default root: a bare
    # AtlasApplication() binds to the real durable state directory and
    # would let a test read - or on any execution path write - the
    # operator's live financial state.
    app = AtlasApplication(state_directory=tmp_path)

    assert app.execution_mode == ExecutionManager.MODE_PAPER
    assert app.execution.mode == ExecutionManager.MODE_PAPER
    assert app.execution.live_execution_enabled is False


def test_atlas_application_default_execution_mode_constant_is_paper() -> None:
    import inspect

    signature = inspect.signature(AtlasApplication.__init__)
    assert signature.parameters["execution_mode"].default == "PAPER"
