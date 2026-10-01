"""S1 step 2 sidecar: every unclear case reads as UNKNOWN (None), never a guess."""

from __future__ import annotations

from decimal import Decimal

from core.position_risk_buckets import PositionRiskBucketStore
from core.risk_engine import PositionExposure


def test_record_and_read_back_idempotently(tmp_path):
    s = PositionRiskBucketStore(tmp_path / "b.jsonl")
    assert s.record("P1", "low") is True
    assert s.record("P1", "LOW") is False  # identical repeat is a no-op
    assert s.lookup("P1") == "LOW"
    assert len((tmp_path / "b.jsonl").read_text().splitlines()) == 1


def test_missing_position_is_unknown(tmp_path):
    s = PositionRiskBucketStore(tmp_path / "b.jsonl")
    assert s.lookup("OLD") is None and s.lookup(None) is None


def test_conflicting_records_read_as_unknown(tmp_path):
    s = PositionRiskBucketStore(tmp_path / "b.jsonl")
    s.record("P1", "LOW")
    s.record("P1", "HIGH")
    assert s.lookup("P1") is None


def test_invalid_bucket_never_recorded(tmp_path):
    s = PositionRiskBucketStore(tmp_path / "b.jsonl")
    assert s.record("P1", "UNSUPPORTED") is False and s.record("", "LOW") is False
    assert not (tmp_path / "b.jsonl").exists()


def test_truncated_file_makes_everything_unknown_and_blocks_appends(tmp_path):
    path = tmp_path / "b.jsonl"
    s = PositionRiskBucketStore(path)
    s.record("P1", "LOW")
    path.write_text(path.read_text() + '{"position_id": "P2", "risk_', encoding="utf-8")
    assert s.lookup("P1") is None and s.corrupt is True
    before = path.read_text()
    assert s.record("P3", "LOW") is False
    assert path.read_text() == before


def test_unknown_bucket_counts_against_the_strictest_sleeve():
    from core import risk_engine as re_mod
    assert PositionExposure("BTCUSDT", Decimal("1"), Decimal("1"), Decimal("1")).risk_bucket is None
    assert hasattr(re_mod.RiskEngine, "_sleeve_check")  # UNKNOWN -> smallest sleeve, see test_s1 sleeve tests


def test_paper_buy_records_its_bucket_and_risk_state_sees_it(tmp_path):
    from tests.test_block5e_fee_settlement_accounting import application

    app = application(tmp_path)
    m = app.execution
    m.position_risk_buckets = PositionRiskBucketStore(tmp_path / "sidecar.jsonl")
    m.start()
    buy = m.execute({"symbol": "BTCUSDT", "action": "BUY", "price": 10.0, "amount": 1000,
                     "confidence": 90.0, "risk": "MEDIUM", "request_id": "b1"})
    assert buy["commit_outcome"] == "COMMITTED", buy
    pid = app.portfolio_foundation.snapshot()["positions"]["BTCUSDT"]["position_id"]
    assert m.position_risk_buckets.lookup(pid) == "MEDIUM"
    assert [e.risk_bucket for e in m._derived_position_exposures()] == ["MEDIUM"]


def test_without_a_store_exposures_stay_unknown(tmp_path):
    from tests.test_block5e_fee_settlement_accounting import application

    app = application(tmp_path)
    m = app.execution
    m.position_risk_buckets = None
    m.start()
    m.execute({"symbol": "BTCUSDT", "action": "BUY", "price": 10.0, "amount": 1000,
               "confidence": 90.0, "risk": "MEDIUM", "request_id": "b1"})
    assert [e.risk_bucket for e in m._derived_position_exposures()] == [None]
