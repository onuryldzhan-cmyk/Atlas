"""Check strategy_compare results against the PRE-REGISTERED regime-filter bar.

  python -m tools.regime_bar_check --registry <hypotheses.json> <result.json> [<second_period_result.json> ...]

The bar comes from proposals/2026-09-30_regime_filter_runtime_DRAFT.md and was
fixed before the data, so it is applied here verbatim and cannot be moved:

1. the regime filter beats the reference in at least 2 of 3 windows, with
   drawdown no worse in ANY window;
2. at least 30 closed trades in total across the windows;
3. the same holds on a second, non-overlapping period (a second result file
   with a different dataset hash).

A result counts only if it is a REGISTERED study that re-verifies against the
hypothesis registry (seal, pre-registration hash, sealed specification, data
inside the sealed window and after registration: strategy_compare
.verify_registered_result; audit F-2 / review N-1). All periods must share one
sealed study specification and one family, the supplied periods must be every
registered hypothesis of that family whatever its specification (no best-of-N
selection by hypothesis or by specification, reviews NF-3 / NEW-2), each
hypothesis hosts exactly one recorded run (strategy_compare.start_study_run),
and no two periods may overlap in time: each period's span runs from its
earliest to its latest candle over all of its symbols, so two universes over
the same dates are one period, not two (bar item 3 "non-overlapping", reviews
NF-2 / NEW-1). A family that loses a member (e.g. a crashed or rejected run)
can therefore never clear the bar; that is deliberate. Selection across whole
families stays visible in the registry but is not decided here (residual). An EXPLORATORY, unlabelled or
unverifiable result cannot clear any part of the bar; without --registry
nothing can.

Read-only research tool. It prints a verdict and never changes the runtime.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

REFERENCE = "gerçekçi dolum (referans)"
FILTER = "rejim filtresi (sadece TREND_UP)"
MIN_WINDOWS_WON, MIN_CLOSED = 2, 30


def _span(result: dict[str, Any]) -> tuple[int, int]:
    """Earliest to latest candle over every symbol of a verified period (NEW-1)."""
    symbols = (result.get("dataset") or {}).get("symbols") or {}
    return (min(info["first_open"] for info in symbols.values()), max(info["last_open"] for info in symbols.values()))


def check_period(result: dict[str, Any], registry: str | Path | None = None) -> dict[str, Any]:
    from tools.strategy_compare import StudyRegistrationError, verify_registered_result

    try:
        study = verify_registered_result(result, registry)
    except StudyRegistrationError as exc:
        return {"ok": False, "reason": f"not a verified registered study ({exc}): exploratory, not evidence"}
    table = result.get("table") or {}
    ref, flt = table.get(REFERENCE), table.get(FILTER)
    if not ref or not flt or len(ref) != len(flt):
        return {"ok": False, "reason": "regime filter or reference missing from this result (run with --only rejim)"}
    try:
        won = sum(1 for r, b in zip(flt, ref) if Decimal(str(r["net_pnl"])) > Decimal(str(b["net_pnl"])))
        dd_ok = all(Decimal(str(r["max_drawdown"])) <= Decimal(str(b["max_drawdown"])) for r, b in zip(flt, ref))
        closed = sum(int(r["closed_trades"]) for r in flt)
    except (KeyError, ValueError, ArithmeticError) as exc:
        return {"ok": False, "reason": f"malformed result: {exc}"}
    reasons = []
    if won < MIN_WINDOWS_WON:
        reasons.append(f"won {won}/{len(flt)} windows (need {MIN_WINDOWS_WON})")
    if not dd_ok:
        reasons.append("drawdown worse than the reference in at least one window")
    if closed < MIN_CLOSED:
        reasons.append(f"{closed} closed trades (need {MIN_CLOSED})")
    return {"ok": not reasons, "won": won, "windows": len(flt), "drawdown_no_worse": dd_ok, "closed": closed,
            "dataset": (result.get("dataset") or {}).get("dataset_sha256"), "hypothesis_id": study["hypothesis_id"],
            "specification": json.dumps(study.get("parameters"), sort_keys=True),
            "span": _span(result),
            "reason": "; ".join(reasons) or "bar items 1-2 met"}


def verdict(results: list[dict[str, Any]], registry: str | Path | None = None) -> dict[str, Any]:
    periods = [check_period(r, registry) for r in results]
    datasets = {p.get("dataset") for p in periods if p["ok"] and p.get("dataset")}
    if not periods or not all(p["ok"] for p in periods):
        return {"verdict": "NOT PROVEN", "periods": periods}
    if len({p["specification"] for p in periods}) != 1:
        return {"verdict": "NOT PROVEN", "periods": periods,
                "note": "periods come from different sealed study specifications"}
    for i, a in enumerate(periods):
        for b in periods[i + 1:]:
            (a0, a1), (b0, b1) = a["span"], b["span"]
            if a0 <= b1 and b0 <= a1:
                return {"verdict": "NOT PROVEN", "periods": periods,
                        "note": "periods overlap in time; bar item 3 needs non-overlapping periods"}
    from research.hypothesis_registry import HypothesisRegistry

    reg = HypothesisRegistry(registry_path=registry)
    records = [reg.get(p["hypothesis_id"]) for p in periods]
    families = {r.family_id for r in records}
    if len(families) != 1:
        return {"verdict": "NOT PROVEN", "periods": periods, "note": "periods come from different hypothesis families"}
    family = [r.hypothesis_id for r in reg.family(next(iter(families)))]
    if sorted(family) != sorted(p["hypothesis_id"] for p in periods):
        return {"verdict": "NOT PROVEN", "periods": periods,
                "note": f"every registered hypothesis of the family must be included, once: {sorted(family)}"}
    if len(datasets) < 2:
        return {"verdict": "PENDING SECOND PERIOD", "periods": periods,
                "note": "bar item 3: a second, non-overlapping period with a different dataset is required"}
    return {"verdict": "BAR CLEARED", "periods": periods,
            "note": "the DRAFT may now be filed as a proposal; runtime still needs implementation, audit and owner approval"}


def main(argv: list[str] | None = None) -> int:
    paths = list(sys.argv[1:] if argv is None else argv)
    registry = None
    if "--registry" in paths:
        i = paths.index("--registry")
        registry = paths[i + 1] if i + 1 < len(paths) else None
        del paths[i:i + 2]
    if not paths:
        print(__doc__)
        return 2
    try:
        results = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    except (OSError, ValueError) as exc:
        print(f"HATA: {exc}")
        return 2
    out = verdict(results, registry)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
