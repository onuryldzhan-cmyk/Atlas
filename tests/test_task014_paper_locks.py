"""Task 014 (registry v5.98): paper-lock edge cases, delta tests only.

The audit found the lock chain intact (main.py's fixed PAPER, core/atlas_config refusing any other mode, the policy
manifest refusing any non-PAPER manifest and blocking new risk on a mismatch, ExecutionManager without live
authority and without a live adapter); each of those layers already has its own tests. The one gap: AtlasApplication
stored any mode string as given, while ExecutionManager normalised it, so an unknown mode was reported as itself
while orders ran as PAPER, and a padded mode was reported unpadded by one and padded by the other.
"""
from __future__ import annotations

import pytest

from core.application import AtlasApplication
from tests.test_block5c_upstream_sizing_authority import seed_state


@pytest.mark.parametrize("mode", ["SHADOW", "TESTNET", "", "PAPER_SIMULATION", None])
def test_an_unknown_execution_mode_is_refused_at_construction(tmp_path, mode):
    state = seed_state(tmp_path / "state")
    with pytest.raises(ValueError, match="is not PAPER or LIVE"):
        AtlasApplication(state_directory=state, execution_mode=mode)
    # In code the refusal comes before the instance lock is taken (this test cannot observe the lock); a correct start
    # in the same directory still succeeds.
    app = AtlasApplication(state_directory=state, execution_mode="PAPER")
    assert app.execution_mode == "PAPER"
    app.stop()


@pytest.mark.parametrize("given, mode", [(" paper ", "PAPER"), ("Paper", "PAPER"), ("LIVE ", "LIVE"), (" live", "LIVE")])
def test_the_application_and_its_execution_manager_report_the_same_mode(tmp_path, given, mode):
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"), execution_mode=given)
    try:
        assert app.execution_mode == app.execution.mode == mode
        assert app.execution.live_execution_enabled is False  # the application never grants live authority
    finally:
        app.stop()
