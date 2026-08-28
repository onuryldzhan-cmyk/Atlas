"""Leakage-safe chronological train/calibration/test splitting.

Observations are never shuffled and no random sampling is used. The split is
contiguous in time:

    |<---- TRAIN ---->|<-gap->|<-- CALIBRATION -->|<-gap->|<---- TEST ---->|

Each gap is at least ``label_horizon_bars + embargo_bars`` wide.

**Purge** removes observations whose label window reaches into the following
segment. If an observation at bar *t* carries a label depending on data
through *t + h*, the final *h* bars of the earlier segment know about the
start of the later one.

**Embargo** removes a further buffer, because purging eliminates direct label
overlap but not serial correlation: trailing-window features and
autocorrelated returns leak across a boundary even when label windows do not.

Both buffers are taken from the **earlier** segment. This is a deliberate
choice between two defensible conventions: it keeps the TEST segment a
function of ``test_fraction`` alone, so tuning the purge or embargo can never
silently change what the test set *is*. That removes a researcher degree of
freedom.

A split that cannot satisfy its invariants raises rather than returning a
degenerate result, because silent degeneracy in a splitter is
indistinguishable from leakage in the results downstream.

This module holds no market data and performs no I/O. It computes index
ranges only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

_FRACTION_TOLERANCE = 1e-9


class SplitError(Exception):
    """Raised when a split specification or a resulting split is invalid."""


@dataclass(frozen=True, slots=True)
class Segment:
    """A half-open contiguous index range ``[start, stop)``."""

    start: int
    stop: int

    def __post_init__(self) -> None:
        if not isinstance(self.start, int) or isinstance(self.start, bool):
            raise SplitError("segment start must be an int")
        if not isinstance(self.stop, int) or isinstance(self.stop, bool):
            raise SplitError("segment stop must be an int")
        if self.start < 0:
            raise SplitError(f"segment start must be >= 0, got {self.start}")
        if self.stop <= self.start:
            raise SplitError(
                f"segment must be non-empty, got [{self.start}, {self.stop})"
            )

    def __len__(self) -> int:
        return self.stop - self.start

    @property
    def indices(self) -> range:
        """The observation indices this segment covers."""
        return range(self.start, self.stop)

    def as_dict(self) -> dict[str, int]:
        return {"start": self.start, "stop": self.stop}


@dataclass(frozen=True, slots=True)
class SplitSpec:
    """Pre-registered split parameters.

    Sealed into a hypothesis's pre-registration, so the purge and embargo
    cannot be tuned after results are visible.
    """

    train_fraction: float
    calibration_fraction: float
    test_fraction: float
    label_horizon_bars: int
    embargo_pct: float

    def __post_init__(self) -> None:
        fractions = {
            "train_fraction": self.train_fraction,
            "calibration_fraction": self.calibration_fraction,
            "test_fraction": self.test_fraction,
        }
        for name, value in fractions.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise SplitError(f"{name} must be a number")
            if not math.isfinite(float(value)):
                raise SplitError(f"{name} must be finite")
            if value <= 0.0:
                raise SplitError(f"{name} must be > 0, got {value}")

        total = float(
            self.train_fraction + self.calibration_fraction + self.test_fraction
        )
        if abs(total - 1.0) > _FRACTION_TOLERANCE:
            raise SplitError(f"fractions must sum to 1.0, got {total}")

        if not isinstance(self.label_horizon_bars, int) or isinstance(
            self.label_horizon_bars, bool
        ):
            raise SplitError("label_horizon_bars must be an int")
        if self.label_horizon_bars < 0:
            raise SplitError(
                f"label_horizon_bars must be >= 0, got {self.label_horizon_bars}"
            )

        if not isinstance(self.embargo_pct, (int, float)) or isinstance(
            self.embargo_pct, bool
        ):
            raise SplitError("embargo_pct must be a number")
        if not 0.0 <= float(self.embargo_pct) < 1.0:
            raise SplitError(
                f"embargo_pct must be in [0.0, 1.0), got {self.embargo_pct}"
            )

    def embargo_bars(self, n_observations: int) -> int:
        """Bars removed for the embargo at each boundary."""
        return int(math.ceil(float(self.embargo_pct) * n_observations))

    def buffer_bars(self, n_observations: int) -> int:
        """Total bars removed from the earlier segment at each boundary."""
        return self.label_horizon_bars + self.embargo_bars(n_observations)

    def as_dict(self) -> dict[str, Any]:
        return {
            "train_fraction": float(self.train_fraction),
            "calibration_fraction": float(self.calibration_fraction),
            "test_fraction": float(self.test_fraction),
            "label_horizon_bars": int(self.label_horizon_bars),
            "embargo_pct": float(self.embargo_pct),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SplitSpec":
        try:
            return cls(
                train_fraction=float(payload["train_fraction"]),
                calibration_fraction=float(payload["calibration_fraction"]),
                test_fraction=float(payload["test_fraction"]),
                label_horizon_bars=int(payload["label_horizon_bars"]),
                embargo_pct=float(payload["embargo_pct"]),
            )
        except KeyError as exc:
            raise SplitError(f"split spec missing field {exc}") from exc


@dataclass(frozen=True, slots=True)
class DataSplit:
    """A validated three-way chronological split.

    The ordering and disjointness invariants are enforced on construction, so
    a hand-built DataSplit cannot express a leaking split either.
    """

    train: Segment
    calibration: Segment
    test: Segment
    n_observations: int
    spec: SplitSpec
    purged_bars: int
    embargo_bars: int

    def __post_init__(self) -> None:
        if self.n_observations <= 0:
            raise SplitError("n_observations must be > 0")
        if self.test.stop > self.n_observations:
            raise SplitError(
                f"test segment {self.test.stop} exceeds n_observations "
                f"{self.n_observations}"
            )

        required_gap = self.purged_bars + self.embargo_bars

        train_gap = self.calibration.start - self.train.stop
        if train_gap < required_gap:
            raise SplitError(
                f"train/calibration gap {train_gap} is smaller than the required "
                f"purge+embargo {required_gap}"
            )

        calibration_gap = self.test.start - self.calibration.stop
        if calibration_gap < required_gap:
            raise SplitError(
                f"calibration/test gap {calibration_gap} is smaller than the required "
                f"purge+embargo {required_gap}"
            )

    @property
    def segments(self) -> tuple[Segment, Segment, Segment]:
        return (self.train, self.calibration, self.test)

    @property
    def train_calibration_gap(self) -> int:
        return self.calibration.start - self.train.stop

    @property
    def calibration_test_gap(self) -> int:
        return self.test.start - self.calibration.stop

    @property
    def dropped_bars(self) -> int:
        """Observations excluded from every segment by purge and embargo."""
        return self.n_observations - sum(len(s) for s in self.segments)

    def as_dict(self) -> dict[str, Any]:
        return {
            "train": self.train.as_dict(),
            "calibration": self.calibration.as_dict(),
            "test": self.test.as_dict(),
            "n_observations": self.n_observations,
            "spec": self.spec.as_dict(),
            "purged_bars": self.purged_bars,
            "embargo_bars": self.embargo_bars,
        }


def make_purged_split(n_observations: int, spec: SplitSpec) -> DataSplit:
    """Build a purged, embargoed train/calibration/test split.

    Deterministic given ``(n_observations, spec)``. Raises SplitError when the
    sample is too small to satisfy the invariants, rather than returning a
    degenerate split.
    """
    if not isinstance(n_observations, int) or isinstance(n_observations, bool):
        raise SplitError("n_observations must be an int")
    if n_observations <= 0:
        raise SplitError(f"n_observations must be > 0, got {n_observations}")

    # Raw boundaries depend only on the fractions. The test segment is fixed
    # here and is never moved by the purge or embargo.
    #
    # The epsilon guards the floor against binary-fraction error: n * 0.6 can
    # land a hair below the integer it should be, which would silently shift
    # a boundary by one bar. The error is many orders of magnitude smaller
    # than the tolerance, so a boundary that is genuinely non-integral is
    # never bumped.
    train_stop_raw = int(
        math.floor(n_observations * spec.train_fraction + _FRACTION_TOLERANCE)
    )
    calibration_stop_raw = int(
        math.floor(
            n_observations * (spec.train_fraction + spec.calibration_fraction)
            + _FRACTION_TOLERANCE
        )
    )

    embargo_bars = spec.embargo_bars(n_observations)
    buffer_bars = spec.label_horizon_bars + embargo_bars

    train_stop = train_stop_raw - buffer_bars
    calibration_stop = calibration_stop_raw - buffer_bars

    if train_stop <= 0:
        raise SplitError(
            f"train segment is empty after purge+embargo ({buffer_bars} bars) "
            f"with n_observations={n_observations}; increase the sample or "
            f"reduce label_horizon_bars/embargo_pct"
        )
    if calibration_stop <= train_stop_raw:
        raise SplitError(
            f"calibration segment is empty after purge+embargo ({buffer_bars} bars) "
            f"with n_observations={n_observations}; increase the sample or "
            f"reduce label_horizon_bars/embargo_pct"
        )
    if calibration_stop_raw >= n_observations:
        raise SplitError(
            f"test segment is empty with n_observations={n_observations}; "
            f"increase the sample or reduce test_fraction"
        )

    return DataSplit(
        train=Segment(start=0, stop=train_stop),
        calibration=Segment(start=train_stop_raw, stop=calibration_stop),
        test=Segment(start=calibration_stop_raw, stop=n_observations),
        n_observations=n_observations,
        spec=spec,
        purged_bars=spec.label_horizon_bars,
        embargo_bars=embargo_bars,
    )
