"""Evaluate one sealed generated study, adjudicate families, rank a shortlist (Task 006, research only).

GRANT-TASK-006-MULTI-STRATEGY-COMPARISON-SELECTION-RESEARCH-ONLY (registry v5.89).
Output is research evidence for the owner, never trading or capital authority:
no function here returns a weight, an allocation or a size. This module performs
no I/O and imports nothing outside ``research/`` except numpy (ADR-0009); the
tools layer verifies results against the canonical registry and does every write.

**Evaluation** (``evaluate_result``) of ONE verified REGISTERED result of a
generated study (exactly one variant against the realistic reference):

* the daily series: each variant's closed-trade net P/L per UTC exit day, with a
  0 for every day of the sealed window without an exit;
* d = variant - reference per day; the statistic is t = mean(d) / se(d), with
  se the batch-means standard error over ``BATCHES`` consecutive batches (robust
  to day-to-day dependence);
* p-value: one-sided studentized circular block bootstrap (block length = the
  batch length n / BATCHES): ``(1 + #{t* >= t}) / (B + 1)`` with
  t* = (mean* - mean(d)) / se*, never 0; the seed is derived from the result's
  digest, so the evaluation is reproducible. Calibration at the 90-day floor
  (2 000 null simulations at B = 999): the share of p <= 0.05 without any edge
  is 5.1% for i.i.d. days and 5.3% / 4.5% / 5.7% for AR(1) phi = 0.3 / 0.5 /
  0.7. Resamples without spread count against the hypothesis, and fewer than
  ``MIN_ACTIVE_DAYS`` days on which the variant and the reference differ at all
  is NO EVIDENCE (review N-2). Owner-accepted residual (reviews M-1, NEW-1;
  registry v5.89): for P/L with many small gains and RARE LARGE LOSSES no test
  of the mean can see a loss that never happened in the window, so the
  false-positive rate approaches the chance that the window holds no loss day
  (a peso problem): at 90 days about 3% (loss on 5% of days), 7% (3%) and
  14% (2%); milder lognormal skew 7-11%. The OUT_OF_SAMPLE check does not catch
  this (a loss-free window also passes it); BH across the family remains;
* effect size: mean(d) / sd(d);
* a two-sided bootstrap-t confidence interval for mean(d);
* Sharpe and Sortino of the variant's daily P/L (annualised over 365 days, per
  unit of P/L -- the replay has no fixed capital base), its maximum drawdown;
* EV per trade = P(W)E(W) - P(L)E(L) - C, where W/L split trades by their
  result before costs and C = fees + slippage (+ funding, 0 for the spot replay)
  per trade, for the variant and the reference;
* per-regime means of d over the window's daily regime labels and a stability
  share: of the regimes with at least ``MIN_REGIME_DAYS`` days (UNKNOWN
  excluded), the fraction where the variant beat the reference on average.

A verified run that carries no usable evidence -- fewer than ``MIN_DAYS``
days, a zero-variance difference (e.g. a variant identical to the reference),
or a result from before Task 006 without daily series -- is scored as NO
EVIDENCE: p = 1, effect 0, OUT_OF_SAMPLE FAIL (``no_evidence_record``). It still
counts as one of the family's m tests and can never pass; nothing optimistic is
invented. A run that crashed without any result is recorded the same way by the
owner (tools/strategy_selection ``record-failed-run``). The registry's sealed check plan of a
generated hypothesis requires OUT_OF_SAMPLE; its verdict is the study's own
pre-registered rule (``BETTER``: beat the reference in every window with no
worse drawdown).

**Adjudication readiness** (``adjudication_readiness``): a generated family is
adjudicated only when it is complete (``family_completeness``) and every member
is TESTED, or was rejected before the family's earliest sealed window began
(when no outcome data existed anywhere) and before any run of the family was
recorded. Both anchors are the registry's own wall-clock timestamps: a clock
set back past both could still open the gate, but only through direct
registry API writes, which bypass this gate anyway (residual, see below). A member rejected after its own run,
or abandoned once any sealed window had started (its market data can then be
replayed as EXPLORATORY even before a registered run), blocks the family for
good: leaving it out would shrink the family's m after an outcome could be seen
(reviews F-1, N-1, H-1). This rule is enforced by the tools layer
(tools/strategy_selection ``adjudicate``); a direct call of the registry's own
``adjudicate_family`` bypasses it (documented residual, like the unkeyed
registry).
An unrun member that is no longer wanted is counted instead, as NO EVIDENCE
(p = 1; tools/strategy_selection ``abandon``). A member whose run was spent without a TEST evaluation is
reported, never guessed.

**Shortlist** (``shortlist``): reads ONLY recorded TEST evaluations of CANDIDATE
hypotheses (the sealed window of an untested hypothesis is never read). An idea
is listed only when every one of its sealed periods is CANDIDATE. Ideas are
ranked by the lowest confidence-interval bound over their periods (the most
conservative), then de-duplicated by risk, greedily in rank order against the
already listed representatives: an idea whose daily P/L correlates above
``max_correlation`` with one of them joins that idea's cluster instead of being
listed. When a correlation cannot be measured (too little overlap, a flat
series) the idea is listed but flagged ``correlation_unknown_with`` -- it is not
shown as independent risk.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

import numpy as np

from research.hypothesis_generation import GENERATION_KEY, family_completeness
from research.hypothesis_registry import (
    CheckName,
    CheckResult,
    CheckVerdict,
    EvaluationRecord,
    HypothesisRegistry,
)
from research.lifecycle import HypothesisState

MIN_DAYS = 90  # owner decision 2026-10-09 (review NEW-1): rare-loss risk shrinks with the window
MIN_ACTIVE_DAYS = 10  # days on which variant and reference differ at all (review N-2)
BATCHES = 4
MIN_REGIME_DAYS = 5
MIN_OVERLAP_DAYS = 10
BOOTSTRAP_SAMPLES = 10_000
CONFIDENCE = 0.95
DAYS_PER_YEAR = 365
PAYLOAD_KEY = "task006"


class EvaluationError(ValueError):
    """The result cannot be evaluated (malformed, not a generated study); nothing is recorded."""


class InsufficientSampleError(EvaluationError):
    """A verified run without usable evidence (too few days, no spread, no daily series).

    The tools layer records it as NO EVIDENCE (``no_evidence_record``: p = 1), never as a pass.
    """


def _decimal(value: Any, what: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise EvaluationError(f"{what} is not a number: {value!r:.40}") from exc
    if not number.is_finite():
        raise EvaluationError(f"{what} is not finite: {value!r:.40}")
    return number


def _window_days(result: Mapping[str, Any]) -> list[str]:
    """Every UTC day of the sealed window, from the verified dataset manifest."""
    symbols = ((result.get("dataset") or {}).get("symbols") or {})
    spans = [(info.get("first_open"), info.get("last_open")) for info in symbols.values() if isinstance(info, Mapping)]
    if not spans or not all(isinstance(a, int) and isinstance(b, int) for a, b in spans):
        raise EvaluationError("the result has no sealed dataset span")
    first = datetime.fromtimestamp(min(a for a, _ in spans) / 1000, tz=timezone.utc).date()
    last = datetime.fromtimestamp(max(b for _, b in spans) / 1000, tz=timezone.utc).date()
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def _daily(rows: Any, days: Sequence[str], what: str) -> np.ndarray:
    if not isinstance(rows, list) or not rows:
        raise EvaluationError(f"{what}: no per-window rows")
    totals: dict[str, Decimal] = {}
    for row in rows:
        series = row.get("daily_net") if isinstance(row, Mapping) else None
        if not isinstance(series, Mapping):
            raise InsufficientSampleError(f"{what}: a window row has no daily_net series (a result from before "
                                          f"Task 006)")
        for day, value in series.items():
            if day not in days:
                raise EvaluationError(f"{what}: P/L on {day!r}, outside the sealed window")
            totals[day] = totals.get(day, Decimal("0")) + _decimal(value, f"{what} {day}")
    return np.array([float(totals.get(day, Decimal("0"))) for day in days], dtype=float)


def _ev(rows: list[Mapping[str, Any]], what: str) -> dict[str, Any]:
    parts = {"trades": 0, "wins": 0, "losses": 0}
    sums = {"win_sum": Decimal("0"), "loss_sum": Decimal("0"), "fees": Decimal("0"), "slippage": Decimal("0"),
            "funding": Decimal("0")}
    for row in rows:
        ev = row.get("ev") if isinstance(row, Mapping) else None
        if not isinstance(ev, Mapping):
            raise InsufficientSampleError(f"{what}: a window row has no EV components (a result from before Task 006)")
        for key in parts:
            value = ev.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise EvaluationError(f"{what}: malformed EV count {key}={value!r}")
            parts[key] += value
        for key in sums:
            sums[key] += _decimal(ev.get(key), f"{what} EV {key}")
    n = parts["trades"]
    if n != parts["wins"] + parts["losses"]:
        raise EvaluationError(f"{what}: EV counts do not add up")
    if n == 0:
        return {**parts, "p_win": None, "avg_win": None, "p_loss": None, "avg_loss": None, "cost_per_trade": None,
                "ev_per_trade": None, "funding_note": "spot replay: no funding"}
    p_win, p_loss = Decimal(parts["wins"]) / n, Decimal(parts["losses"]) / n
    avg_win = sums["win_sum"] / parts["wins"] if parts["wins"] else Decimal("0")
    avg_loss = sums["loss_sum"] / parts["losses"] if parts["losses"] else Decimal("0")
    cost = (sums["fees"] + sums["slippage"] + sums["funding"]) / n
    ev = p_win * avg_win - p_loss * avg_loss - cost
    return {**parts, "p_win": str(p_win), "avg_win": str(avg_win), "p_loss": str(p_loss), "avg_loss": str(avg_loss),
            "cost_per_trade": str(cost), "fees": str(sums["fees"]), "slippage": str(sums["slippage"]),
            "funding": str(sums["funding"]), "funding_note": "spot replay: no funding",
            "ev_per_trade": str(ev)}


def _block_index(n: int, block: int, samples: int, rng: np.random.Generator) -> np.ndarray:
    """Indices of circular block-bootstrap resamples (keeps short-range serial dependence)."""
    blocks = math.ceil(n / block)
    starts = rng.integers(0, n, size=(samples, blocks))
    return (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(samples, -1)[:, :n] % n


def _batch_se(x: np.ndarray) -> np.ndarray | float:
    """Batch-means standard error of the mean over the last axis (BATCHES consecutive batches)."""
    n = x.shape[-1]
    b = n // BATCHES
    means = x[..., : BATCHES * b].reshape(*x.shape[:-1], BATCHES, b).mean(axis=-1)
    return means.std(axis=-1, ddof=1) / math.sqrt(BATCHES)


def studentized_block_bootstrap(d: np.ndarray, *, samples: int, seed: int) -> tuple[float, float, float, int]:
    """One-sided p-value for mean(d) > 0 and a two-sided bootstrap-t interval (see the module docstring).

    Raises InsufficientSampleError when d has no spread (no test statistic exists).
    """
    d = np.asarray(d, dtype=float)
    if np.count_nonzero(d) < MIN_ACTIVE_DAYS:
        raise InsufficientSampleError(f"only {np.count_nonzero(d)} days where the variant and the reference differ; "
                                      f"at least {MIN_ACTIVE_DAYS} are needed")
    mean, se0 = float(d.mean()), float(_batch_se(d))
    if not float(d.std(ddof=1)) > 0 or not se0 > 0:
        raise InsufficientSampleError("the variant-minus-reference series has no spread: no test statistic")
    rng = np.random.default_rng(seed)
    block = len(d) // BATCHES
    resampled = d[_block_index(len(d), block, samples, rng)]
    se_star = _batch_se(resampled)
    valid = se_star > 0
    # A resample without spread has no t*; it counts AGAINST the hypothesis (+inf), never for it (review N-2).
    t_star = np.where(valid, (resampled.mean(axis=1) - mean) / np.where(valid, se_star, 1.0), np.inf)
    p_value = float((1 + np.count_nonzero(t_star >= mean / se0)) / (samples + 1))
    tail = (1 - CONFIDENCE) / 2
    if valid.any():
        q_low, q_high = (float(q) for q in np.quantile(t_star[valid], [tail, 1 - tail]))
    else:
        q_low, q_high = math.inf, -math.inf
    return p_value, mean - q_high * se0, mean - q_low * se0, block


def _drawdown(series: np.ndarray) -> float:
    equity = np.cumsum(series)
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))[1:]
    return float(np.max(peak - equity)) if len(series) else 0.0


def _ratio(mean: float, spread: float) -> float | None:
    return None if spread <= 0 or not math.isfinite(spread) else mean / spread * math.sqrt(DAYS_PER_YEAR)


@dataclass(frozen=True)
class StudyEvaluation:
    hypothesis_id: str
    variant: str
    days: tuple[str, ...]
    variant_daily: tuple[float, ...]
    reference_daily: tuple[float, ...]
    mean_difference: float
    effect_size: float
    p_value: float
    ci_low: float
    ci_high: float
    better_verdict: bool
    stats: Mapping[str, Any]

    def payload(self) -> dict[str, Any]:
        """What the TEST evaluation records (JSON): everything the shortlist needs, nothing else."""
        return {PAYLOAD_KEY: {"variant": self.variant, "days": list(self.days),
                              "variant_daily": list(self.variant_daily), "reference_daily": list(self.reference_daily),
                              "mean_difference": self.mean_difference, "ci": [self.ci_low, self.ci_high],
                              "better_verdict": self.better_verdict, **dict(self.stats)}}


def evaluate_result(result: Mapping[str, Any], *, samples: int = BOOTSTRAP_SAMPLES,
                    min_days: int = MIN_DAYS) -> StudyEvaluation:
    """Evaluate a VERIFIED registered result of a generated study (the caller verifies it)."""
    study = result.get("study") if isinstance(result.get("study"), Mapping) else {}
    spec = study.get("parameters") if isinstance(study.get("parameters"), Mapping) else {}
    if study.get("status") != "REGISTERED" or "variant_args" not in spec:
        raise EvaluationError("only a registered generated study (sealed variant arguments) can be evaluated")
    reference = spec.get("reference")
    variants = [name for name in spec.get("variants", []) if name != reference]
    if len(variants) != 1:
        raise EvaluationError(f"a generated study tests exactly one variant against the reference, got {variants}")
    variant = variants[0]
    table = result.get("table") if isinstance(result.get("table"), Mapping) else {}
    days = _window_days(result)
    v = _daily(table.get(variant), days, variant)
    r = _daily(table.get(reference), days, str(reference))
    if len(days) < min_days:
        raise InsufficientSampleError(f"{len(days)} days in the sealed window; at least {min_days} are needed "
                                      f"for an honest p-value")
    d = v - r
    mean, sd = float(d.mean()), float(d.std(ddof=1))
    digest = str(study.get("result_digest") or "")
    seed = int(hashlib.sha256(("task006:" + digest).encode("ascii")).hexdigest()[:16], 16)
    p_value, ci_low, ci_high, block = studentized_block_bootstrap(d, samples=samples, seed=seed)

    regimes = result.get("regimes") if isinstance(result.get("regimes"), Mapping) else {}
    by_regime: dict[str, dict[str, Any]] = {}
    for i, day in enumerate(days):
        label = str(regimes.get(day, "UNKNOWN"))
        entry = by_regime.setdefault(label, {"days": 0, "sum": 0.0})
        entry["days"] += 1
        entry["sum"] += float(d[i])
    regime_stats = {label: {"days": e["days"], "mean_difference": e["sum"] / e["days"]} for label, e in by_regime.items()}
    judged = [e for label, e in regime_stats.items() if label != "UNKNOWN" and e["days"] >= MIN_REGIME_DAYS]
    downside = float(np.sqrt(np.mean(np.minimum(v, 0.0) ** 2)))
    verdicts = result.get("verdicts") if isinstance(result.get("verdicts"), Mapping) else {}
    stats = {
        "days_n": len(days), "block_length": block, "batches": BATCHES, "bootstrap_samples": samples,
        "seed": seed, "method": "studentized circular block bootstrap, batch-means standard error",
        "sharpe": _ratio(float(v.mean()), float(v.std(ddof=1))), "sortino": _ratio(float(v.mean()), downside),
        "max_drawdown": _drawdown(v), "reference_max_drawdown": _drawdown(r),
        "ev": {"variant": _ev(table.get(variant), variant), "reference": _ev(table.get(reference), str(reference))},
        "regimes": regime_stats,
        "regime_stability": (sum(1 for e in judged if e["mean_difference"] > 0) / len(judged)) if judged else None,
    }
    return StudyEvaluation(hypothesis_id=str(study.get("hypothesis_id")), variant=variant, days=tuple(days),
                           variant_daily=tuple(float(x) for x in v), reference_daily=tuple(float(x) for x in r),
                           mean_difference=mean, effect_size=mean / sd, p_value=p_value, ci_low=ci_low,
                           ci_high=ci_high, better_verdict=verdicts.get(variant) == "BETTER", stats=stats)


def evaluation_record(evaluation: StudyEvaluation) -> EvaluationRecord:
    """The single TEST evaluation for the registry, with the plan's OUT_OF_SAMPLE check."""
    check = CheckResult(check_name=CheckName.OUT_OF_SAMPLE,
                        verdict=CheckVerdict.PASS if evaluation.better_verdict else CheckVerdict.FAIL,
                        statistic_value=evaluation.mean_difference, p_value=evaluation.p_value,
                        effect_size=evaluation.effect_size, payload=evaluation.payload())
    return EvaluationRecord(segment="TEST", statistic_value=evaluation.mean_difference, p_value=evaluation.p_value,
                            effect_size=evaluation.effect_size,
                            notes="Task 006: one-sided circular block bootstrap of mean daily variant-minus-reference "
                                  "net P/L over the sealed window", checks=(check,))


def no_evidence_record(reason: str) -> EvaluationRecord:
    """A spent run without usable evidence: scored p = 1, effect 0, OUT_OF_SAMPLE FAIL.

    It stays one of the family's m tests (so leaving it out can never help a sibling) and it
    can never pass any gate.
    """
    check = CheckResult(check_name=CheckName.OUT_OF_SAMPLE, verdict=CheckVerdict.FAIL, statistic_value=0.0,
                        p_value=1.0, effect_size=0.0, payload={PAYLOAD_KEY: {"no_evidence": str(reason)}})
    return EvaluationRecord(segment="TEST", statistic_value=0.0, p_value=1.0, effect_size=0.0,
                            notes=f"Task 006: NO EVIDENCE ({reason}); scored p = 1 and counted as one of the "
                                  f"family's tests", checks=(check,))


def run_recorded(record) -> bool:
    """Whether the hypothesis's one study run was ever recorded (REGISTERED -> CALIBRATED)."""
    return any(t.to_state is HypothesisState.CALIBRATED for t in record.state_chain)


# -- adjudication readiness -----------------------------------------------------


def _earliest_window(members) -> datetime:
    return min(datetime.fromisoformat(m.preregistration.data_start) for m in members)


def adjudication_readiness(registry: HypothesisRegistry, family_id: str) -> dict[str, Any]:
    """Whether a family may be adjudicated now, and exactly why not if it may not."""
    members = registry.family(family_id)
    if not members:
        return {"ready": False, "reason": f"no family {family_id}", "blocking": {}}
    registered, sealed = family_completeness(registry, family_id)
    blocking: dict[str, str] = {}
    if sealed is None:  # review L-2: this engine adjudicates generated families only (sealed q, aware dates)
        return {"ready": False, "blocking": {}, "reason": f"{family_id} is not a generated family; Task 006 "
                                                          f"adjudicates generated families only"}
    # Before the earliest sealed window starts, no outcome data of the family exists anywhere; after it,
    # market data can be replayed as EXPLORATORY even before any registered run (review H-1).
    earliest_window = _earliest_window(members)
    runs = [t.recorded_at for m in members for t in m.state_chain if t.to_state is HypothesisState.CALIBRATED]
    first_run = datetime.fromisoformat(min(runs)) if runs else None  # both anchors block; wall-clock based
    if sealed is not None and registered != sealed:
        return {"ready": False, "blocking": {},
                "reason": f"the generated family has {registered} of its sealed {sealed} members; resume its "
                          f"registration (same template) before adjudicating"}
    for record in members:
        state = record.state
        if state is HypothesisState.TESTED:
            continue
        if state is HypothesisState.REJECTED and record.test_evaluation is None:
            rejected_at = datetime.fromisoformat(record.state_chain[-1].recorded_at)
            if run_recorded(record):
                blocking[record.hypothesis_id] = ("rejected AFTER its run was recorded: its result may have been seen, "
                                                  "and leaving it out would shrink the family's m after the fact; this "
                                                  "family can no longer be adjudicated")
            elif rejected_at >= earliest_window or (first_run is not None and rejected_at >= first_run):
                blocking[record.hypothesis_id] = ("abandoned AFTER the family's earliest sealed window had started or "
                                                  "a sibling's run was recorded (an outcome could be seen): leaving it "
                                                  "out would shrink m after the fact; this family can no longer be "
                                                  "adjudicated. Use 'abandon' instead, which counts an unrun member as "
                                                  "p = 1")
            continue  # abandoned before any sealed window began: no outcome existed, so not one of the m tests
        elif state is HypothesisState.REGISTERED:
            blocking[record.hypothesis_id] = "not run yet"
        elif state is HypothesisState.CALIBRATED:
            blocking[record.hypothesis_id] = ("run recorded but no TEST evaluation: evaluate its verified result; if "
                                              "the run crashed without a result, record it as a failed run (p = 1)")
        else:
            blocking[record.hypothesis_id] = f"state {state.value}: the family has already been adjudicated"
    if blocking:
        return {"ready": False, "reason": "not every member is tested", "blocking": blocking}
    return {"ready": True, "reason": "", "blocking": {}}


def family_q(registry: HypothesisRegistry, family_id: str) -> float:
    """The FDR level sealed into a generated family (its template's alpha)."""
    qs = {((m.preregistration.feature_spec.get(GENERATION_KEY) or {}).get("multiple_testing") or {}).get("q")
          for m in registry.family(family_id)}
    if len(qs) != 1 or None in qs:
        raise EvaluationError(f"family {family_id} has no single sealed q; it is not a generated family")
    return float(qs.pop())


# -- the shortlist ------------------------------------------------------------------


def _correlation(a: Mapping[str, float], b: Mapping[str, float]) -> float | None:
    common = sorted(set(a) & set(b))
    if len(common) < MIN_OVERLAP_DAYS:
        return None
    x = np.array([a[d] for d in common], dtype=float)
    y = np.array([b[d] for d in common], dtype=float)
    if x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def shortlist(registry: HypothesisRegistry, *, max_correlation: float = 0.8) -> dict[str, Any]:
    """Rank CANDIDATE ideas from their recorded TEST evaluations; never weights, never allocation."""
    if not 0 < max_correlation <= 1:
        raise EvaluationError("max_correlation must lie in (0, 1]")
    ideas: dict[str, dict[str, Any]] = {}
    for record in registry.all_records():
        gen = record.preregistration.feature_spec.get(GENERATION_KEY) or {}
        fingerprint = gen.get("idea_fingerprint")
        if not fingerprint:
            continue
        idea = ideas.setdefault(fingerprint, {"members": [], "family_id": record.family_id})
        idea["members"].append(record)
    listed, held_back = [], []
    for fingerprint, idea in ideas.items():
        members = idea["members"]
        if not all(m.state is HypothesisState.CANDIDATE for m in members):
            continue
        payloads = []
        for m in members:
            checks = m.test_evaluation.checks if m.test_evaluation is not None else ()
            payload = next((dict(c.payload).get(PAYLOAD_KEY) for c in checks if PAYLOAD_KEY in c.payload), None)
            if payload is None:
                held_back.append({"idea": fingerprint, "reason": f"{m.hypothesis_id} has no Task 006 evaluation"})
                break
            payloads.append((m.hypothesis_id, payload))
        else:
            daily = {day: value for _, p in payloads for day, value in zip(p["days"], p["variant_daily"])}
            listed.append({"idea": fingerprint, "family_id": idea["family_id"], "variant": payloads[0][1]["variant"],
                           "hypotheses": [h for h, _ in payloads],
                           "conservative_ci_low": min(p["ci"][0] for _, p in payloads),
                           "mean_difference": [p["mean_difference"] for _, p in payloads],
                           "p_values": [registry.get(h).test_evaluation.p_value for h, _ in payloads],
                           "sharpe": [p.get("sharpe") for _, p in payloads],
                           "max_drawdown": [p.get("max_drawdown") for _, p in payloads],
                           "ev": [p.get("ev") for _, p in payloads],
                           "regime_stability": [p.get("regime_stability") for _, p in payloads],
                           "_daily": daily})
    listed.sort(key=lambda e: (-e["conservative_ci_low"], e["idea"]))
    shortlist_, clusters = [], {}
    for entry in listed:
        relations = {rep["idea"]: _correlation(entry["_daily"], rep["_daily"]) for rep in shortlist_}
        twin = next((idea for idea, corr in relations.items() if corr is not None and corr > max_correlation), None)
        entry["correlations"] = relations
        entry["correlation_unknown_with"] = sorted(idea for idea, corr in relations.items() if corr is None)
        if twin is not None:
            clusters.setdefault(twin, []).append({"idea": entry["idea"], "correlation": relations[twin]})
            continue
        shortlist_.append(entry)
    for entry in shortlist_:
        entry["cluster"] = clusters.get(entry["idea"], [])
        entry.pop("_daily")
    return {"evidence_eligible": False, "capital_weights": None,
            "note": "research shortlist: ranked by the lowest confidence bound; correlated ideas are clustered "
                    "behind one representative; no weights, sizes or allocation (Risk/Capital decide those)",
            "max_correlation": max_correlation, "shortlist": shortlist_, "held_back": held_back}
