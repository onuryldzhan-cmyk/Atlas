"""False-discovery control shared by the research tools (2026-10-02).

When many groups are tested at once (coins, regimes, confidence bands, hours) some look
significant by luck. Each group gets an exact binomial p-value against a 50 % win rate
and all of them a Benjamini-Hochberg correction; a finding is kept only when q <= FDR_Q.
Values match scipy.stats.binomtest and statsmodels multipletests(method="fdr_bh")
(pinned in tests/test_experience_agent.py). Pure Python, no new dependency.
"""
from __future__ import annotations

import math

FDR_Q = 0.10


def binom_two_sided_p(k: int, n: int) -> float:
    """Exact two-sided binomial test against a 50 % win rate (sum of outcomes no likelier than k)."""
    if n <= 0:
        return 1.0
    logp = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) - n * math.log(2) for i in range(n + 1)]
    cut = logp[k] + 1e-9
    return min(1.0, math.fsum(math.exp(x) for x in logp if x <= cut))


def bh_qvalues(pvalues: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (same as statsmodels multipletests(method="fdr_bh"))."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvalues[i] * m / rank)
        q[i] = running
    return q
