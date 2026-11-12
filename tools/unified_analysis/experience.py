"""Experience and learning layer (the TradingAgents decision log + settlement idea, on Atlas's durable storage).

Storage layers, kept apart:
  raw observations        the market archive / Binance bars (not copied here; referenced by sha256 digests)
  immutable audit record  PREDICTION records: the full report and its wall-clock recorded_at_ms, written BEFORE its
                          OUTCOME record (for an archive cutoff the market outcome may already exist: hindsight)
  validated experience    OUTCOME records: a separate, later record that references the prediction's hash
  analytical report       reports/<analysis_id>.json (a readable copy; the ledger is the authority)
  long-term knowledge     only through the governed memory log and an owner decision (calibration is evidence,
                          not policy); nothing here changes a gate, a parameter or an order

The ledger is core.durable_append_log (fsync'd append, torn-tail detection, OS lock, strict sequence) plus a
SHA-256 hash chain over every record, so an edited, reordered or truncated history is refused as a whole (halt,
never continue). Records are never rewritten: a prediction cannot be changed by its outcome.

Idempotency: one prediction per (symbol, cutoff, profile). Re-recording the identical report is a no-op; a different
report for the same id is refused (the first one stands, so a re-run cannot pick the better answer in hindsight).
One outcome per prediction; a second is refused.

Look-ahead and leakage: settlement reads only the bars of [entry_from, entry_from + horizon), where entry_from is
the first bar boundary at or after the decision time; it needs the whole window to have closed (otherwise PENDING)
and enters at that first bar's open. Calibration takes ``as_of_ms`` and uses only outcomes closed by then.

Skill vs hindsight: calibration counts only settled predictions that are calibration samples, charges a round-trip
cost before a direction counts as a hit (and counts a thesis that hit its own invalidation as a miss), and reports a
class as MEASURED only when both the older and the newer half of its history clear MIN_SAMPLES/2 and a hit rate above
0.5 (walk-forward). MEASURED is a diagnostic only: it never raises the confidence cap (review 48 H1), and it counts
only forward-recorded samples: a PREDICTION carries its wall-clock ``recorded_at_ms``, and one recorded after its
outcome window began (every archive analysis and replay) is hindsight, which counts only as a miss in the cap (review
50 F-50-1, review 51 F-51-1). This relies on an honest host clock; record-time order is not enforced (F-51-2). It is keyed on
the scored class (the candidate for a capped or rejected result), so the cap cannot stop its own record from growing.

Calibration samples (review 48 H1): a prediction is a sample only if its horizon is CALIBRATION_HORIZON_MS and its
entry_from lies on the UTC grid of that horizon (00:00 UTC for 24 h), and, when several predictions of one key share a
symbol and entry, only the first one recorded (review 49 H-new-1: the ledger is append-only, so a later prediction,
settled or not, can never displace an earlier sample). Whether a prediction is a sample depends only on the prediction
and on what was recorded before it, never on which outcomes have arrived or in what order, and samples of one symbol
never overlap. So an extra settled hit only adds a hit, an extra miss only adds a miss, and a later prediction adds
nothing to a slot already taken: the record, and the cap built from it, move in the right direction.

Tamper evidence (review 48 M1): the hash chain detects an edited, reordered or torn record, but it has no anchor
outside the file. A clean cut at a record boundary (dropping the newest records), or a consistent rewrite of the whole
file, passes. The idempotency rule therefore stops the tool, not someone with write access to the file, from replacing
an answer; an external anchor is deferred.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from core.durable_append_log import DurableAppendLog
from core.market_cycle import INTERVAL_MS, closed_bars

from tools.unified_analysis.contracts import AnalysisReport, Classification, DIRECTIONAL, to_jsonable

LOG_NAME = "unified_analysis_experience"
LOG_VERSION = 1
GENESIS = "0" * 64
# 0.1 % fee per side (Atlas's fee estimate) + 5 bps slippage per side (tools/experience_agent.py SLIPPAGE_BPS)
ROUND_TRIP_COST = 0.003
MIN_SAMPLES = 30
# Only predictions with this horizon, entered on its UTC grid, are calibration samples (equal to pipeline
# DEFAULT_HORIZON_HOURS; pinned by a test). Other horizons are recorded and settled, but not calibrated.
CALIBRATION_HORIZON_MS = 24 * 3_600_000
# fields the ledger sets itself; an outcome mapping may never supply them (review 50 F-50-3)
RESERVED_OUTCOME_KEYS = frozenset({"record_type", "analysis_id", "prediction_hash", "prev_hash", "hash", "sequence"})
Z95 = 1.959964
SETTLE_TIMEFRAME = "1h"


class ExperienceLedgerError(RuntimeError):
    """The ledger cannot be trusted (chain broken, record altered) or a write would violate an invariant."""


class ExperienceConflict(ExperienceLedgerError):
    """A different record already exists for this id; the existing one stands."""


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps({k: v for k, v in payload.items() if k not in ("hash", "sequence")}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def analysis_id(symbol: str, cutoff_ms: int, profile: str) -> str:
    return f"UA-{symbol}-{cutoff_ms}-{profile}"


class ExperienceLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._log = DurableAppendLog(self.path, log_name=LOG_NAME, version=LOG_VERSION)

    def records(self) -> list[dict[str, Any]]:
        """Every record, chain-verified. Raises ExperienceLedgerError on any break (fail closed)."""
        try:
            records = self._log.read()
        except Exception as exc:  # corrupt framing, torn tail, recovery marker
            raise ExperienceLedgerError(f"experience ledger unreadable: {exc}") from exc
        prev = GENESIS
        for i, rec in enumerate(records):
            if rec.get("prev_hash") != prev:
                raise ExperienceLedgerError(f"record {i}: hash chain broken")
            if rec.get("hash") != _hash(rec):
                raise ExperienceLedgerError(f"record {i}: record altered")
            if rec.get("record_type") not in ("PREDICTION", "OUTCOME"):
                raise ExperienceLedgerError(f"record {i}: unknown record type")
            prev = rec["hash"]
        return records

    def _append(self, records: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
        payload = {**payload, "prev_hash": records[-1]["hash"] if records else GENESIS}
        payload["hash"] = _hash(payload)
        try:
            self._log.append([payload])
        except Exception as exc:  # serialization, I/O, a poisoned writer or a concurrent writer (review F8)
            raise ExperienceLedgerError(f"experience ledger append failed: {type(exc).__name__}: {exc}") from exc
        return payload

    def predictions(self) -> dict[str, dict[str, Any]]:
        return {r["analysis_id"]: r for r in self.records() if r["record_type"] == "PREDICTION"}

    def outcomes(self) -> dict[str, dict[str, Any]]:
        return {r["analysis_id"]: r for r in self.records() if r["record_type"] == "OUTCOME"}

    def record_prediction(self, report: AnalysisReport, *, now_ms: int | None = None) -> dict[str, Any]:
        """``now_ms`` is the wall-clock record time (tests only); never the analysis cutoff (review 50 F-50-1)."""
        recorded_at = int(time.time() * 1000) if now_ms is None else int(now_ms)
        body = report.to_dict()
        # the run's own latency is not part of the analysis: without this no re-run could ever be identical
        stable = {**body, "metrics": {k: v for k, v in body["metrics"].items() if k != "timings"}}
        report_sha = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        records = self.records()
        for r in records:
            if r["record_type"] == "PREDICTION" and r["analysis_id"] == report.analysis_id:
                if r["report_sha256"] == report_sha:
                    return r  # idempotent re-record
                raise ExperienceConflict(f"{report.analysis_id} is already recorded with a different report")
        primary = next((s for s in body["scenarios"] if s["name"] == body["primary_scenario"]), None)
        basis = body.get("confidence_basis") or {}
        return self._append(records, {
            "record_type": "PREDICTION", "analysis_id": report.analysis_id, "symbol": report.symbol,
            "cutoff_ms": report.cutoff_ms, "entry_from_ms": report.entry_from_ms or report.cutoff_ms,
            "horizon_ms": report.horizon_hours * 3_600_000,
            "classification": report.classification.value, "confidence": str(report.confidence),
            "candidate": basis.get("candidate"), "candidate_confidence": basis.get("candidate_confidence"),
            "risk_approved": report.risk.approved,
            "reference_close": report.reference_close,
            "invalidation": primary["invalidation"] if primary else [],
            "recorded_at_ms": recorded_at, "report_sha256": report_sha, "report": body})

    def record_outcome(self, analysis_id_: str, outcome: Mapping[str, Any]) -> dict[str, Any]:
        records = self.records()
        prediction = next((r for r in records if r["record_type"] == "PREDICTION"
                           and r["analysis_id"] == analysis_id_), None)
        if prediction is None:
            raise ExperienceLedgerError(f"no prediction {analysis_id_}")
        if any(r["record_type"] == "OUTCOME" and r["analysis_id"] == analysis_id_ for r in records):
            raise ExperienceConflict(f"{analysis_id_} is already settled")
        first, through = outcome.get("first_bar_open_ms"), outcome.get("through_ms")
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (first, through)):
            raise ExperienceLedgerError("outcome window fields must be integers")
        start = _entry_from(prediction)
        if first < start:
            raise ExperienceLedgerError("outcome uses a bar from before the cutoff")
        if through < start + prediction["horizon_ms"]:
            raise ExperienceLedgerError("outcome does not cover the whole horizon")
        if RESERVED_OUTCOME_KEYS & set(outcome) or not isinstance(outcome.get("hit"), (bool, type(None))):
            raise ExperienceLedgerError("outcome carries a reserved field or a non-boolean hit")   # review 50 F-50-3
        return self._append(records, {**to_jsonable(dict(outcome)), "record_type": "OUTCOME",
                                      "analysis_id": analysis_id_, "prediction_hash": prediction["hash"]})


def forward_recorded(prediction: Mapping[str, Any]) -> bool:
    """Recorded (wall clock) no later than the start of its outcome window (review 50 F-50-1). A prediction without
    a record time, or recorded once its window had begun (every archive analysis and replay), is hindsight: part of
    its outcome already existed, so a chosen set of such predictions could be a chosen set of winners."""
    at = prediction.get("recorded_at_ms")
    return isinstance(at, int) and not isinstance(at, bool) and at <= _entry_from(prediction)


def _entry_from(prediction: Mapping[str, Any]) -> int:
    return int(prediction.get("entry_from_ms") or prediction["cutoff_ms"])


def scored_class(prediction: Mapping[str, Any]) -> str | None:
    """The class a prediction is scored and calibrated as: its classification when that is a claim, else the
    candidate the evidence pointed to before the calibration cap, the threshold or the risk gate (so a capped or
    rejected class keeps accumulating a record instead of freezing at its first misses)."""
    cls = prediction["classification"]
    if cls in {c.value for c in DIRECTIONAL} or cls == Classification.NEUTRAL_RANGE.value:
        return cls
    return prediction.get("candidate")


@dataclass(frozen=True)
class Pending:
    reason: str


def evaluate(prediction: Mapping[str, Any], rows: Any, *, now_ms: int,
             benchmark_rows: Any = None) -> dict[str, Any] | Pending:
    """Score one prediction on the bars of its own horizon only.

    The window is [entry_from, entry_from + horizon): it starts at the first bar boundary at or after the decision
    (never earlier, so context read during the cutoff hour cannot "predict" a move it already saw). The entry price
    is that first bar's open; every bar outside the window is ignored."""
    start, horizon = _entry_from(prediction), int(prediction["horizon_ms"])
    end = start + horizon
    if now_ms < end:
        return Pending("HORIZON_NOT_ELAPSED")
    step = INTERVAL_MS[SETTLE_TIMEFRAME]
    window = [r for r in (rows or []) if isinstance(r, (list, tuple)) and r and start <= int(r[0]) < end]
    bars, reason = closed_bars(window, interval=SETTLE_TIMEFRAME, cutoff_ms=end)
    if bars is None or bars[0].open_ms != start or len(bars) != horizon // step:
        return Pending(f"INCOMPLETE_WINDOW ({reason or 'missing bars'})")
    try:
        entry = float(next(r for r in window if int(r[0]) == start)[1])
    except (TypeError, ValueError, IndexError):
        return Pending("MALFORMED_ENTRY_BAR")
    if not math.isfinite(entry) or entry <= 0:
        return Pending("MALFORMED_ENTRY_BAR")
    closes = [b.close for b in bars]
    ret = closes[-1] / entry - 1.0
    invalidated_at = None
    for b in bars:
        for cond in prediction.get("invalidation") or []:
            if (b.close < cond["threshold"]) if cond["operator"] == "<" else (b.close > cond["threshold"]):
                invalidated_at = b.close_ms
                break
        if invalidated_at is not None:
            break
    cls = scored_class(prediction)
    sign = 1.0 if cls == Classification.BULLISH_SETUP.value else -1.0 if cls == Classification.BEARISH_SETUP.value else 0.0
    out: dict[str, Any] = {"first_bar_open_ms": bars[0].open_ms, "through_ms": bars[-1].close_ms + 1,
                           "bars": len(bars), "entry_open": entry, "return": round(ret, 8),
                           "invalidated_at_ms": invalidated_at, "round_trip_cost": ROUND_TRIP_COST, "scored_as": cls}
    if sign:
        signed = sign * ret
        adverse = min(sign * (c / entry - 1.0) for c in closes)
        # a thesis that hit its own invalidation is wrong even if price came back (review F10)
        hit = signed - ROUND_TRIP_COST > 0 and invalidated_at is None
        bound = prediction.get("candidate_confidence") or prediction.get("confidence") or "0"
        out.update({"signed_return": round(signed, 8), "max_adverse_close": round(adverse, 8), "hit": hit,
                    # diagnostic only: the confidence is an evidence bound, not a probability
                    "brier_on_bound": round((float(bound) - (1.0 if hit else 0.0)) ** 2, 8)})
    elif cls == Classification.NEUTRAL_RANGE.value:
        out["hit"] = invalidated_at is None
    else:
        out["hit"] = None  # no claim and no candidate: nothing to score; the move is kept for review
    if benchmark_rows is not None:
        bwin = [r for r in benchmark_rows if isinstance(r, (list, tuple)) and r and start <= int(r[0]) < end]
        bbars, _ = closed_bars(bwin, interval=SETTLE_TIMEFRAME, cutoff_ms=end)
        try:
            bopen = float(next(r for r in bwin if int(r[0]) == start)[1])
        except (StopIteration, TypeError, ValueError, IndexError):
            bopen = None
        if bbars and bopen and bopen > 0 and bbars[0].open_ms == start and len(bbars) == horizon // step:
            bench = bbars[-1].close / bopen - 1.0
            out.update({"benchmark_return": round(bench, 8), "excess_return": round(ret - bench, 8)})
    return out


def wilson_lower(hits: int, n: int, z: float = Z95) -> float:
    if n <= 0:
        return 0.0
    p = hits / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / (1 + z * z / n))


def _sample_ids(predictions: Iterable[Mapping[str, Any]]) -> set[str]:
    """The predictions that are calibration samples, decided from the predictions alone (review 48 H1).

    On the CALIBRATION_HORIZON_MS grid, one per (key, symbol, entry), the first in ledger order: windows of one symbol
    never overlap, no outcome, settled or late, can change which predictions count, and a later prediction can never
    displace an earlier sample (review 49 H-new-1). ``predictions`` must be in ledger order."""
    chosen: dict[tuple[str, str, int], str] = {}
    for pred in predictions:
        key = _key(pred)
        entry = _entry_from(pred)
        if key is None or int(pred["horizon_ms"]) != CALIBRATION_HORIZON_MS or entry % CALIBRATION_HORIZON_MS:
            continue
        slot = (key, pred["symbol"], entry)
        chosen.setdefault(slot, pred["analysis_id"])
    return set(chosen.values())


def _key(prediction: Mapping[str, Any]) -> str | None:
    """Emitted claims and capped candidates whose risk gate passed share one key (the same situations, held back
    only by the cap, threshold or objections). A risk-rejected candidate is kept under its own ``:risk_rejected``
    key (review N3): situations the class is never emitted in must not set the cap of approved results."""
    cls = scored_class(prediction)
    if cls is None:
        return None
    roster = (prediction.get("report") or {}).get("confidence_basis", {}).get("roster") or "live"
    if prediction["classification"] == Classification.RISK_REJECTED.value or prediction.get("risk_approved") is False:
        return f"{roster}:{cls}:risk_rejected"
    return f"{roster}:{cls}"


def calibration(records: list[dict[str, Any]], *, as_of_ms: int | None = None) -> dict[str, dict[str, Any]]:
    """Track record per "<roster>:<scored class>" from settled predictions (the decision layer's confidence cap).

    ``as_of_ms`` (review F5): only outcomes whose whole window had closed by then count, so an analysis at a past
    cutoff (replay, archive analysis) never sees an outcome from its own future. Live and historical rosters are
    never pooled."""
    preds = {r["analysis_id"]: r for r in records if r["record_type"] == "PREDICTION"}   # ledger order is kept
    samples = _sample_ids(preds.values())
    pairs = [(preds[r["analysis_id"]], r) for r in records
             if r["record_type"] == "OUTCOME" and r["analysis_id"] in samples and isinstance(r.get("hit"), bool)
             and (as_of_ms is None or int(r.get("through_ms", 0)) <= as_of_ms)]
    out: dict[str, dict[str, Any]] = {}
    for key in {k for k in (_key(p) for p, _ in pairs) if k is not None}:
        cls = key.split(":")[1]
        rows = sorted(((p, o) for p, o in pairs if _key(p) == key), key=lambda x: (_entry_from(x[0]), x[0]["symbol"]))
        n = len(rows)
        hits = sum(1 for _, o in rows if o["hit"])
        # review 50 F-50-1: only forward-recorded samples can show skill; hindsight samples may only lower the cap
        forward = [(p, o) for p, o in rows if forward_recorded(p)]
        f_n, f_hits = len(forward), sum(1 for _, o in forward if o["hit"])
        half = f_n // 2
        older, newer = forward[:half], forward[half:]
        rate = (lambda xs: sum(1 for _, o in xs if o["hit"]) / len(xs) if xs else None)
        measured = (f_n >= MIN_SAMPLES and len(older) >= MIN_SAMPLES // 2 and len(newer) >= MIN_SAMPLES // 2
                    and (rate(older) or 0) > 0.5 and (rate(newer) or 0) > 0.5)
        briers = [o["brier_on_bound"] for _, o in rows if "brier_on_bound" in o]
        out[key] = {"n": n, "hits": hits, "hit_rate": round(hits / n, 4) if n else None,
                    "forward_n": f_n, "forward_hits": f_hits,
                    "wilson_lower": round(wilson_lower(f_hits, f_n), 4), "older_hit_rate": rate(older),
                    "newer_hit_rate": rate(newer), "measured": measured,
                    "mean_brier_on_bound": round(sum(briers) / len(briers), 4) if briers else None,
                    "directional": cls in {c.value for c in DIRECTIONAL}}
    return out
