"""Owner principle #14 (registry v5.61): claim -> evidence -> counter-evidence on memory records."""

from __future__ import annotations

import pytest

from atlas_org import memory_records
from tools import atlas_org_cli as cli

BASE = {"type": "DECISION", "authority": "PROPOSED", "title": "t", "body": "b", "author": "research", "source": "test"}


def _add(tmp_path, rid, **extra):
    return cli.add_memory_record(tmp_path, {"record_id": rid, **BASE, **extra})


def test_records_without_claims_stay_valid(tmp_path):
    _add(tmp_path, "R-1")
    assert memory_records.replay(cli.read_log(tmp_path / cli.MEMORY_LOG))["R-1"]["claims"] is None


def test_complete_claim_is_kept_and_published(tmp_path):
    claim = {"claim": "ATR stop lowers drawdown", "evidence": "replay 2026-09", "counter_evidence": "none found"}
    _add(tmp_path, "R-1", claims=[claim])
    view = memory_records.public_view(memory_records.replay(cli.read_log(tmp_path / cli.MEMORY_LOG)))
    assert view[0]["claims"] == [claim]


@pytest.mark.parametrize("claims", [
    [],
    [{"claim": "x", "evidence": "y"}],
    [{"claim": "x", "evidence": "", "counter_evidence": "z"}],
    [{"claim": "x", "evidence": "y", "counter_evidence": "   "}],
    ["x"],
    {"claim": "x", "evidence": "y", "counter_evidence": "z"},
])
def test_incomplete_claims_are_refused_and_nothing_is_written(tmp_path, claims):
    with pytest.raises(memory_records.MemoryLogError):
        _add(tmp_path, "R-1", claims=claims)
    assert cli.read_log(tmp_path / cli.MEMORY_LOG) == []
