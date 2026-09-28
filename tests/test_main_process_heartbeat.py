"""SUPERVISOR-1: main.AtlasProcess's half of hung-child detection.

atlas_supervisor.py watches a heartbeat file's mtime; this is the other end
- main.AtlasProcess writes it once per run_forever() tick, only when told
where by ATLAS_SUPERVISOR_HEARTBEAT_FILE (main.HEARTBEAT_FILE_ENV), and
never otherwise. See tests/test_process_supervisor.py for the supervisor
side of the same feature.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from main import AtlasProcess, HEARTBEAT_FILE_ENV


class _StubRunningApplication:
    """Just enough application for run_forever() to keep looping."""

    def __init__(self) -> None:
        self.running = True


def test_heartbeat_file_is_unresolved_when_env_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(HEARTBEAT_FILE_ENV, raising=False)

    assert AtlasProcess()._heartbeat_file is None


def test_heartbeat_file_resolves_from_the_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "supervisor_heartbeat.json"
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, str(target))

    assert AtlasProcess()._heartbeat_file == target


def test_write_heartbeat_is_a_no_op_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env var set -> no file, no error - the unsupervised default."""

    monkeypatch.delenv(HEARTBEAT_FILE_ENV, raising=False)

    process = AtlasProcess()

    # Must not raise even though there is nothing to write to.
    process._write_heartbeat()


def test_write_heartbeat_creates_a_fresh_readable_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "supervisor_heartbeat.json"
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, str(target))

    process = AtlasProcess()
    process._write_heartbeat()

    assert target.exists()

    payload = json.loads(target.read_text(encoding="utf-8"))

    assert isinstance(payload["written_at"], (int, float))


def test_write_heartbeat_overwrites_on_every_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The supervisor reads mtime alone; each call must genuinely refresh it."""

    target = tmp_path / "supervisor_heartbeat.json"
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, str(target))

    process = AtlasProcess()
    process._write_heartbeat()

    first = json.loads(target.read_text(encoding="utf-8"))["written_at"]

    process._write_heartbeat()

    second = json.loads(target.read_text(encoding="utf-8"))["written_at"]

    assert second >= first


def test_write_heartbeat_survives_an_unwritable_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A best-effort write: an OSError here must never propagate.

    Pointing the configured path at a directory (rather than a file) is a
    reliable, portable way to force write_text() to raise.
    """

    target = tmp_path / "a_directory"
    target.mkdir()
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, str(target))

    process = AtlasProcess()

    process._write_heartbeat()


def test_run_forever_writes_at_least_one_heartbeat_per_tick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: the configured file is actually touched by the real loop."""

    target = tmp_path / "supervisor_heartbeat.json"
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, str(target))

    process = AtlasProcess()
    process.application = _StubRunningApplication()

    release = threading.Timer(1.5, process.shutdown_event.set)
    release.start()

    try:
        process.run_forever()
    finally:
        release.cancel()

    assert target.exists()

    payload = json.loads(target.read_text(encoding="utf-8"))

    assert isinstance(payload["written_at"], (int, float))
