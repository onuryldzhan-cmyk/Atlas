"""Experience and learning layer (the TradingAgents decision log + settlement idea, on Atlas's durable storage).

Storage layers, kept apart:
  raw observations        the market archive / Binance bars (not copied here; referenced by sha256 digests)
  immutable audit record  PREDICTION records: the full report, written BEFORE any outcome exists
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

Look-ahead and leakage: settlement reads only bars that open at or after the prediction's cutoff, needs the whole
horizon to have closed (otherwise PENDING), and scores against the reference close known at the cutoff.

Skill vs hindsight: calibration counts only settled, non-overlapping predictions per symbol (overlapping horizons
are not independent), charges a round-trip cost before a direction counts as a hit, and calls a class MEASURED only
when both the older and the newer half of its history clear MIN_SAMPLES/2 and a hit rate above 0.5 (walk-forward).
"""

from __future__ import annotations

import hashlib
import json
import math
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
        self._log.append([payload])
        return payload

    def predictions(self) -> dict[str, dict[str, Any]]:
        return {r["analysis_id"]: r for r in self.records() if r["record_type"] == "PREDICTION"}

    def outcomes(self) -> dict[str, dict[str, Any]]:
        return {r["analysis_id"]: r for r in self.records() if r["record_type"] == "OUTCOME"}

    def record_prediction(self, report: AnalysisReport) -> dict[str, Any]:
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
        return self._append(records, {
            "record_type": "PREDICTION", "analysis_id": report.analysis_id, "symbol": report.symbol,
            "cutoff_ms": report.cutoff_ms, "horizon_ms": report.horizon_hours * 3_600_000,
            "classification": report.classification.value, "confidence": str(report.confidence),
            "reference_close": report.reference_close,
            "invalidation": primary["invalidation"] if primary else [],
            "report_sha256": report_sha, "report": body})

    def record_outcome(self, analysis_id_: str, outcome: Mapping[str, Any]) -> dict[str, Any]:
        records = self.records()
        prediction = next((r for r in records if r["record_type"] == "PREDICTION"
                           and r["analysis_id"] == analysis_id_), None)
        if prediction is None:
            raise ExperienceLedgerError(f"no prediction {analysis_id_}")
        if any(r["record_type"] == "OUTCOME" and r["analysis_id"] == analysis_id_ for r in records):
            raise ExperienceConflict(f"{analysis_id_} is already settled")
        if outcome.get("first_bar_open_ms", -1) < prediction["cutoff_ms"]:
            raise ExperienceLedgerError("outcome uses a bar from before the cutoff")
        if outcome.get("through_ms", -1) < prediction["cutoff_ms"] + prediction["horizon_ms"]:
            raise ExperienceLedgerError("outcome does not cover the whole horizon")
        return self._append(records, {"record_type": "OUTCOME", "analysis_id": analysis_id_,
                                      "prediction_hash": prediction["hash"], **to_jsonable(dict(outcome))})


@dataclass(frozen=True)
class Pending:
    reason: str


def evaluate(prediction: Mapping[str, Any], rows: Any, *, now_ms: int,
             benchmark_rows: Any = None) -> dict[str, Any] | Pending:
    """Score one prediction on the bars of its own horizon (only bars after the cutoff). Never reads earlier bars."""
    cutoff, horizon = int(prediction["cutoff_ms"]), int(prediction["horizon_ms"])
    end = cutoff + horizon
    if now_ms < end:
        return Pending("HORIZON_NOT_ELAPSED")
    ref = prediction.get("reference_close")
    if not isinstance(ref, (int, float)) or not math.isfinite(ref) or ref <= 0:
        return Pending("NO_REFERENCE_CLOSE")
    step = INTERVAL_MS[SETTLE_TIMEFRAME]
    window = [r for r in (rows or []) if isinstance(r, (list, tuple)) and r and cutoff <= int(r[0]) < end]
    bars, reason = closed_bars(window, interval=SETTLE_TIMEFRAME, cutoff_ms=end)
    if bars is None or bars[0].open_ms != cutoff or len(bars) != horizon // step:
        return Pending(f"INCOMPLETE_WINDOW ({reason or 'missing bars'})")
    closes = [b.close for b in bars]
    ret = closes[-1] / ref - 1.0
    invalidated_at = None
    for b in bars:
        for cond in prediction.get("invalidation") or []:
            if (b.close < cond["threshold"]) if cond["operator"] == "<" else (b.close > cond["threshold"]):
                invalidated_at = b.close_ms
                break
        if invalidated_at is not None:
            break
    cls = prediction["classification"]
    sign = 1.0 if cls == Classification.BULLISH_SETUP.value else -1.0 if cls == Classification.BEARISH_SETUP.value else 0.0
    out: dict[str, Any] = {"first_bar_open_ms": bars[0].open_ms, "through_ms": bars[-1].close_ms + 1,
                           "bars": len(bars), "return": round(ret, 8), "invalidated_at_ms": invalidated_at,
                           "round_trip_cost": ROUND_TRIP_COST}
    if sign:
        signed = sign * ret
        adverse = min(sign * (c / ref - 1.0) for c in closes)
        hit = signed - ROUND_TRIP_COST > 0
        out.update({"signed_return": round(signed, 8), "max_adverse_close": round(adverse, 8), "hit": hit,
                    "brier": round((float(prediction["confidence"]) - (1.0 if hit else 0.0)) ** 2, 8)})
    elif cls == Classification.NEUTRAL_RANGE.value:
        out["hit"] = invalidated_at is None
    else:
        out["hit"] = None  # INSUFFICIENT_EVIDENCE / RISK_REJECTED: no claim to score; the move is kept for review
    if benchmark_rows is not None:
        bwin = [r for r in benchmark_rows if isinstance(r, (list, tuple)) and r and cutoff - step <= int(r[0]) < end]
        bbars, _ = closed_bars(bwin, interval=SETTLE_TIMEFRAME, cutoff_ms=end)
        if bbars and bbars[0].open_ms == cutoff - step and len(bbars) == horizon // step + 1:
            bench = bbars[-1].close / bbars[0].close - 1.0
            out.update({"benchmark_return": round(bench, 8), "excess_return": round(ret - bench, 8)})
    return out


def wilson_lower(hits: int, n: int, z: float = Z95) -> float:
    if n <= 0:
        return 0.0
    p = hits / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / (1 + z * z / n))


def _non_overlapping(rows: Iterable[tuple[dict, dict]]) -> list[tuple[dict, dict]]:
    """Per symbol, keep a prediction only if its window starts after the previous kept one ended."""
    kept: list[tuple[dict, dict]] = []
    last_end: dict[str, int] = {}
    for pred, out in sorted(rows, key=lambda x: (x[0]["symbol"], x[0]["cutoff_ms"])):
        if pred["cutoff_ms"] >= last_end.get(pred["symbol"], -1):
            kept.append((pred, out))
            last_end[pred["symbol"]] = pred["cutoff_ms"] + pred["horizon_ms"]
    return kept


def _key(prediction: Mapping[str, Any]) -> str:
    roster = (prediction.get("report") or {}).get("confidence_basis", {}).get("roster") or "live"
    return f"{roster}:{prediction['classification']}"


def calibration(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Track record per "<roster>:<classification>" from settled predictions (the decision layer's confidence cap).
    Live and historical (archive replay) analyses use different rosters and are never pooled."""
    preds = {r["analysis_id"]: r for r in records if r["record_type"] == "PREDICTION"}
    pairs = [(preds[r["analysis_id"]], r) for r in records
             if r["record_type"] == "OUTCOME" and r["analysis_id"] in preds and isinstance(r.get("hit"), bool)]
    out: dict[str, dict[str, Any]] = {}
    for key in {_key(p) for p, _ in pairs}:
        cls = key.split(":", 1)[1]
        rows = sorted(_non_overlapping((p, o) for p, o in pairs if _key(p) == key), key=lambda x: x[0]["cutoff_ms"])
        n = len(rows)
        hits = sum(1 for _, o in rows if o["hit"])
        half = n // 2
        older, newer = rows[:half], rows[half:]
        rate = (lambda xs: sum(1 for _, o in xs if o["hit"]) / len(xs) if xs else None)
        measured = (n >= MIN_SAMPLES and len(older) >= MIN_SAMPLES // 2 and len(newer) >= MIN_SAMPLES // 2
                    and (rate(older) or 0) > 0.5 and (rate(newer) or 0) > 0.5)
        briers = [o["brier"] for _, o in rows if "brier" in o]
        out[key] = {"n": n, "hits": hits, "hit_rate": round(hits / n, 4) if n else None,
                    "wilson_lower": round(wilson_lower(hits, n), 4), "older_hit_rate": rate(older),
                    "newer_hit_rate": rate(newer), "measured": measured,
                    "mean_brier": round(sum(briers) / len(briers), 4) if briers else None,
                    "directional": cls in {c.value for c in DIRECTIONAL}}
    return out
