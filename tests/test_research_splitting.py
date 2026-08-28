"""Contract tests for leakage-safe purged/embargoed splitting."""

from __future__ import annotations

import pytest

from research.splitting import (
    DataSplit,
    Segment,
    SplitError,
    SplitSpec,
    make_purged_split,
)


def make_spec(**overrides) -> SplitSpec:
    params = {
        "train_fraction": 0.6,
        "calibration_fraction": 0.2,
        "test_fraction": 0.2,
        "label_horizon_bars": 10,
        "embargo_pct": 0.01,
    }
    params.update(overrides)
    return SplitSpec(**params)


# --- SplitSpec validation ------------------------------------------------


def test_fractions_must_sum_to_one():
    with pytest.raises(SplitError, match="sum to 1.0"):
        SplitSpec(
            train_fraction=0.6,
            calibration_fraction=0.2,
            test_fraction=0.3,
            label_horizon_bars=0,
            embargo_pct=0.0,
        )


def test_every_fraction_must_be_positive():
    with pytest.raises(SplitError, match="must be > 0"):
        SplitSpec(
            train_fraction=0.8,
            calibration_fraction=0.0,
            test_fraction=0.2,
            label_horizon_bars=0,
            embargo_pct=0.0,
        )


def test_label_horizon_must_not_be_negative():
    with pytest.raises(SplitError, match="label_horizon_bars"):
        make_spec(label_horizon_bars=-1)


@pytest.mark.parametrize("embargo_pct", [-0.01, 1.0, 1.5])
def test_embargo_pct_must_lie_in_unit_interval(embargo_pct):
    with pytest.raises(SplitError, match="embargo_pct"):
        make_spec(embargo_pct=embargo_pct)


def test_booleans_are_rejected_as_numbers():
    with pytest.raises(SplitError):
        make_spec(label_horizon_bars=True)


# --- split geometry ------------------------------------------------------


def test_split_boundaries_are_exact():
    split = make_purged_split(1000, make_spec())
    # embargo = ceil(0.01 * 1000) = 10, purge = 10, buffer = 20
    assert (split.train.start, split.train.stop) == (0, 580)
    assert (split.calibration.start, split.calibration.stop) == (600, 780)
    assert (split.test.start, split.test.stop) == (800, 1000)
    assert split.purged_bars == 10
    assert split.embargo_bars == 10
    assert split.dropped_bars == 40


def test_segments_are_ordered_and_disjoint():
    split = make_purged_split(1000, make_spec())
    train = set(split.train.indices)
    calibration = set(split.calibration.indices)
    test = set(split.test.indices)

    assert train & calibration == set()
    assert calibration & test == set()
    assert train & test == set()
    assert max(train) < min(calibration)
    assert max(calibration) < min(test)


def test_gaps_are_at_least_purge_plus_embargo():
    spec = make_spec(label_horizon_bars=25, embargo_pct=0.02)
    split = make_purged_split(2000, spec)
    required = split.purged_bars + split.embargo_bars
    assert split.train_calibration_gap >= required
    assert split.calibration_test_gap >= required


def test_no_training_label_window_can_reach_the_next_segment():
    """The purge exists so this is true for every remaining observation."""
    horizon = 30
    spec = make_spec(label_horizon_bars=horizon, embargo_pct=0.0)
    split = make_purged_split(1000, spec)
    last_train_label_end = (split.train.stop - 1) + horizon
    assert last_train_label_end < split.calibration.start

    last_calibration_label_end = (split.calibration.stop - 1) + horizon
    assert last_calibration_label_end < split.test.start


def test_test_segment_does_not_move_when_purge_or_embargo_changes():
    """The stated convention: buffers come out of the earlier segment only.

    Tuning the purge or embargo must never change what the test set *is*.
    """
    baseline = make_purged_split(
        1000, make_spec(label_horizon_bars=0, embargo_pct=0.0)
    )
    for horizon, embargo in [(5, 0.0), (0, 0.05), (40, 0.03), (10, 0.01)]:
        split = make_purged_split(
            1000, make_spec(label_horizon_bars=horizon, embargo_pct=embargo)
        )
        assert split.test.start == baseline.test.start
        assert split.test.stop == baseline.test.stop
        assert len(split.test) == len(baseline.test)


def test_larger_buffers_only_shrink_the_earlier_segments():
    small = make_purged_split(
        1000, make_spec(label_horizon_bars=5, embargo_pct=0.0)
    )
    large = make_purged_split(
        1000, make_spec(label_horizon_bars=50, embargo_pct=0.0)
    )
    assert len(large.train) < len(small.train)
    assert len(large.calibration) < len(small.calibration)
    assert len(large.test) == len(small.test)


def test_split_is_deterministic():
    spec = make_spec()
    first = make_purged_split(1500, spec)
    second = make_purged_split(1500, spec)
    assert first.as_dict() == second.as_dict()


def test_split_is_chronological_and_starts_at_zero():
    split = make_purged_split(1000, make_spec())
    assert split.train.start == 0
    assert split.test.stop == split.n_observations


@pytest.mark.parametrize("n_observations", [200, 501, 1000, 2500, 9999])
def test_invariants_hold_across_sample_sizes(n_observations):
    split = make_purged_split(n_observations, make_spec())
    assert len(split.train) > 0
    assert len(split.calibration) > 0
    assert len(split.test) > 0
    assert split.train.stop <= split.calibration.start
    assert split.calibration.stop <= split.test.start
    assert split.test.stop == n_observations


# --- fail-closed behaviour ----------------------------------------------


def test_sample_too_small_raises_rather_than_degenerating():
    """A degenerate split is indistinguishable from leakage downstream."""
    with pytest.raises(SplitError):
        make_purged_split(20, make_spec(label_horizon_bars=100))


def test_empty_train_segment_is_reported_explicitly():
    with pytest.raises(SplitError, match="train segment is empty"):
        make_purged_split(100, make_spec(label_horizon_bars=60, embargo_pct=0.0))


@pytest.mark.parametrize("n_observations", [0, -5])
def test_non_positive_sample_is_rejected(n_observations):
    with pytest.raises(SplitError, match="n_observations"):
        make_purged_split(n_observations, make_spec())


def test_segment_must_be_non_empty():
    with pytest.raises(SplitError, match="non-empty"):
        Segment(start=10, stop=10)


def test_hand_built_split_with_an_insufficient_gap_is_rejected():
    """DataSplit enforces its own invariants, not just the factory."""
    spec = make_spec(label_horizon_bars=10, embargo_pct=0.01)
    with pytest.raises(SplitError, match="gap"):
        DataSplit(
            train=Segment(start=0, stop=599),
            calibration=Segment(start=600, stop=780),
            test=Segment(start=800, stop=1000),
            n_observations=1000,
            spec=spec,
            purged_bars=10,
            embargo_bars=10,
        )


def test_hand_built_split_cannot_exceed_the_sample():
    spec = make_spec(label_horizon_bars=0, embargo_pct=0.0)
    with pytest.raises(SplitError, match="exceeds n_observations"):
        DataSplit(
            train=Segment(start=0, stop=60),
            calibration=Segment(start=60, stop=80),
            test=Segment(start=80, stop=120),
            n_observations=100,
            spec=spec,
            purged_bars=0,
            embargo_bars=0,
        )


# --- serialisation -------------------------------------------------------


def test_split_spec_round_trips_through_a_dict():
    spec = make_spec()
    assert SplitSpec.from_dict(spec.as_dict()) == spec


def test_split_spec_from_dict_reports_missing_fields():
    payload = make_spec().as_dict()
    del payload["embargo_pct"]
    with pytest.raises(SplitError, match="missing field"):
        SplitSpec.from_dict(payload)
