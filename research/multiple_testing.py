"""Benjamini-Hochberg false discovery rate control.

For ``m`` p-values in one family, sorted ``p_(1) <= ... <= p_(m)``, BH finds
the largest ``k`` with ``p_(k) <= (k / m) * q`` and rejects ``H_(1)..H_(k)``.
Adjusted p-values are the standard monotone step-up::

    p_adj_(i) = min( 1, min over j >= i of ( m / j ) * p_(j) )

Rejecting exactly those with ``p_adj <= q`` is equivalent to the step-up
procedure, and that equivalence is asserted by the tests.

**Why FDR rather than FWER.** Bonferroni bounds the probability of *any*
false discovery and at research scale is conservative enough to discard real
edges. Bounding the expected *proportion* of false discoveries is the
appropriate trade for strategy screening, where a known and stated fraction
of false positives is acceptable.

**The family is the load-bearing part.** BH controls FDR only when the family
contains every hypothesis tested, including those that failed or were
abandoned. Applying BH to survivors reproduces the selection bias it exists
to correct, and is worse than not correcting at all because the result looks
corrected. This is why the hypothesis registry is append-only: it is the only
structure that can honestly enumerate a family.

**Dependence.** BH controls FDR under independence or positive regression
dependence (PRDS). Strategy p-values computed on overlapping windows of the
same market are positively correlated, generally within PRDS, so BH is
applied as specified. Benjamini-Yekutieli (dividing the threshold by the
harmonic number) holds under arbitrary dependence at a real power cost; it is
not implemented here.

No p-value is computed in this module. It takes p-values as input; producing
them is the test procedure's concern. Implemented in numpy, adding no
dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np


class MultipleTestingError(Exception):
    """Raised when an FDR correction input is invalid."""


@dataclass(frozen=True, slots=True)
class FDRDecision:
    """The outcome of one family-level Benjamini-Hochberg correction."""

    labels: tuple[str, ...]
    p_values: tuple[float, ...]
    adjusted_p_values: tuple[float, ...]
    rejected: tuple[bool, ...]
    q: float
    n_tests: int
    n_rejected: int
    critical_p_value: float | None

    @property
    def rejected_labels(self) -> tuple[str, ...]:
        """Labels of the hypotheses declared discoveries, in input order."""
        return tuple(
            label for label, flag in zip(self.labels, self.rejected) if flag
        )

    def is_rejected(self, label: str) -> bool:
        """Return True when ``label`` was declared a discovery."""
        try:
            index = self.labels.index(label)
        except ValueError as exc:
            raise MultipleTestingError(
                f"label {label!r} is not part of this family"
            ) from exc
        return self.rejected[index]

    def adjusted_p_value(self, label: str) -> float:
        """Return the BH-adjusted p-value for ``label``."""
        try:
            index = self.labels.index(label)
        except ValueError as exc:
            raise MultipleTestingError(
                f"label {label!r} is not part of this family"
            ) from exc
        return self.adjusted_p_values[index]

    def as_dict(self) -> dict[str, Any]:
        return {
            "labels": list(self.labels),
            "p_values": list(self.p_values),
            "adjusted_p_values": list(self.adjusted_p_values),
            "rejected": list(self.rejected),
            "q": self.q,
            "n_tests": self.n_tests,
            "n_rejected": self.n_rejected,
            "critical_p_value": self.critical_p_value,
        }


def _validated_p_values(p_values: Sequence[float] | Iterable[float]) -> np.ndarray:
    array = np.asarray(list(p_values), dtype=float)
    if array.ndim != 1:
        raise MultipleTestingError("p_values must be one-dimensional")
    if array.size == 0:
        raise MultipleTestingError("p_values must contain at least one test")
    if not np.all(np.isfinite(array)):
        raise MultipleTestingError("p_values must all be finite")
    if np.any(array < 0.0) or np.any(array > 1.0):
        raise MultipleTestingError("p_values must all lie in [0.0, 1.0]")
    return array


def _validated_labels(
    labels: Sequence[str] | None, n_tests: int
) -> tuple[str, ...]:
    if labels is None:
        return tuple(f"test_{index}" for index in range(n_tests))
    resolved = tuple(str(label) for label in labels)
    if len(resolved) != n_tests:
        raise MultipleTestingError(
            f"labels length {len(resolved)} does not match "
            f"p_values length {n_tests}"
        )
    if len(set(resolved)) != len(resolved):
        raise MultipleTestingError("labels must be unique within a family")
    return resolved


def benjamini_hochberg(
    p_values: Sequence[float] | Iterable[float],
    *,
    q: float,
    labels: Sequence[str] | None = None,
) -> FDRDecision:
    """Apply the Benjamini-Hochberg step-up procedure at FDR level ``q``.

    Args:
        p_values: One p-value per hypothesis in the family. Must include
            every hypothesis tested, not only the survivors.
        q: Target false discovery rate, in ``(0, 1)``.
        labels: Optional unique identifiers, aligned with ``p_values``.

    Returns:
        An FDRDecision whose fields are aligned with the input order.
    """
    if not isinstance(q, (int, float)) or isinstance(q, bool):
        raise MultipleTestingError("q must be a number")
    if not math.isfinite(float(q)):
        raise MultipleTestingError("q must be finite")
    if not 0.0 < float(q) < 1.0:
        raise MultipleTestingError(f"q must lie in (0.0, 1.0), got {q}")

    values = _validated_p_values(p_values)
    n_tests = int(values.size)
    resolved_labels = _validated_labels(labels, n_tests)

    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    ranks = np.arange(1, n_tests + 1, dtype=float)

    # Step-up from the largest index down, then clip: this is the standard
    # monotone BH adjustment.
    scaled = (n_tests / ranks) * sorted_values
    adjusted_sorted = np.minimum.accumulate(scaled[::-1])[::-1]
    adjusted_sorted = np.minimum(adjusted_sorted, 1.0)

    rejected_sorted = adjusted_sorted <= float(q)
    n_rejected = int(np.count_nonzero(rejected_sorted))
    critical_p_value = (
        float(sorted_values[n_rejected - 1]) if n_rejected > 0 else None
    )

    adjusted = np.empty(n_tests, dtype=float)
    adjusted[order] = adjusted_sorted
    rejected = np.zeros(n_tests, dtype=bool)
    rejected[order] = rejected_sorted

    return FDRDecision(
        labels=resolved_labels,
        p_values=tuple(float(value) for value in values),
        adjusted_p_values=tuple(float(value) for value in adjusted),
        rejected=tuple(bool(flag) for flag in rejected),
        q=float(q),
        n_tests=n_tests,
        n_rejected=n_rejected,
        critical_p_value=critical_p_value,
    )
