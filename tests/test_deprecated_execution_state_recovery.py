from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.execution_state import (
    ExecutionState,
    ExecutionStateRecoveryRequired,
)


@pytest.mark.parametrize(
    "persisted",
    [
        '{"version":"2.1","active":',
        "not-json",
        "[]",
        '{"version":"1.0","active":{},"history":[]}',
        '{"version":"2.1","active":[],"history":{}}',
    ],
)
def test_invalid_persisted_state_requires_recovery(
    tmp_path: Path,
    persisted: str,
) -> None:
    state_file = tmp_path / "execution_state.json"
    state_file.write_text(persisted, encoding="utf-8")

    state = ExecutionState(storage=tmp_path)

    assert state.recovery_required is True
    assert state.load_failed is True
    assert state.active == {}
    assert state.history == []
    assert state.last_error is not None
    assert state_file.read_text(encoding="utf-8") == persisted
    assert state.recovery_marker_file.exists()

    with pytest.raises(ExecutionStateRecoveryRequired):
        state.add({"symbol": "BTCUSDT"})
    with pytest.raises(ExecutionStateRecoveryRequired):
        state.close("BTCUSDT", {})
    with pytest.raises(ExecutionStateRecoveryRequired):
        state.save()


def test_read_failure_requires_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "execution_state.json"
    state_file.write_text(
        json.dumps({"version": "2.1", "active": {}, "history": []}),
        encoding="utf-8",
    )
    original_open = Path.open

    def denied_open(path: Path, *args: object, **kwargs: object):
        if path == state_file:
            raise PermissionError("simulated read denial")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied_open)
    state = ExecutionState(storage=tmp_path)

    assert state.recovery_required is True
    assert state.last_error["type"] == "PermissionError"
    with pytest.raises(ExecutionStateRecoveryRequired):
        state.add({"symbol": "BTCUSDT"})


def test_restart_after_failed_load_remains_recovery_required(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "execution_state.json"
    state_file.write_text("{truncated", encoding="utf-8")

    first = ExecutionState(storage=tmp_path)
    second = ExecutionState(storage=tmp_path)

    assert first.recovery_required is True
    assert second.recovery_required is True
    assert state_file.read_text(encoding="utf-8") == "{truncated"


def test_recovery_marker_blocks_restart_if_corrupt_file_is_removed(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "execution_state.json"
    state_file.write_text("{truncated", encoding="utf-8")
    first = ExecutionState(storage=tmp_path)
    assert first.recovery_marker_file.exists()

    state_file.unlink()
    restarted = ExecutionState(storage=tmp_path)

    assert restarted.recovery_required is True
    assert restarted.last_error["type"] == "PersistedRecoveryMarker"
    with pytest.raises(ExecutionStateRecoveryRequired):
        restarted.add({"symbol": "BTCUSDT"})


def test_explicit_reconciliation_preserves_original_and_reopens_operations(
    tmp_path: Path,
) -> None:
    original = "{truncated"
    state_file = tmp_path / "execution_state.json"
    state_file.write_text(original, encoding="utf-8")
    state = ExecutionState(storage=tmp_path)

    resolved = state.resolve_recovery(
        active={
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "status": "OPEN",
            }
        },
        history=[{"event": "RECONCILED"}],
        operator_reference="OWNER-RECONCILIATION-001",
    )

    preserved = tmp_path / "execution_state.json.recovery-original"
    assert preserved.read_text(encoding="utf-8") == original
    assert resolved["BTCUSDT"]["status"] == "OPEN"
    assert state.recovery_required is False
    assert state.recovered is True
    assert state.recovery_marker_file.exists() is False

    restarted = ExecutionState(storage=tmp_path)
    assert restarted.recovery_required is False
    assert restarted.exists("BTCUSDT") is True
    restarted.add({"symbol": "ETHUSDT", "status": "OPEN"})
    assert restarted.exists("ETHUSDT") is True


def test_recovery_requires_explicit_operator_reference(tmp_path: Path) -> None:
    (tmp_path / "execution_state.json").write_text("bad", encoding="utf-8")
    state = ExecutionState(storage=tmp_path)

    with pytest.raises(ValueError, match="operator_reference"):
        state.resolve_recovery(
            active={},
            history=[],
            operator_reference="",
        )
