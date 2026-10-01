"""Check strategy_compare results against the PRE-REGISTERED regime-filter bar.

  python -m tools.regime_bar_check <result.json> [<second_period_result.json> ...]

The bar comes from proposals/2026-09-30_regime_filter_runtime_DRAFT.md and was
fixed before the data, so it is applied here verbatim and cannot be moved:

1. the regime filter beats the reference in at least 2 of 3 windows, with
   drawdown no worse in ANY window;
2. at least 30 closed trades in total across the windows;
3. the same holds on a second, non-overlapping period (a second result file
   with a different dataset hash).

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


def check_period(result: dict[str, Any]) -> dict[str, Any]:
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
            "dataset": (result.get("dataset") or {}).get("dataset_sha256"), "reason": "; ".join(reasons) or "bar items 1-2 met"}


def verdict(results: list[dict[str, Any]]) -> dict[str, Any]:
    periods = [check_period(r) for r in results]
    datasets = {p.get("dataset") for p in periods if p["ok"] and p.get("dataset")}
    if not periods or not all(p["ok"] for p in periods):
        return {"verdict": "NOT PROVEN", "periods": periods}
    if len(datasets) < 2:
        return {"verdict": "PENDING SECOND PERIOD", "periods": periods,
                "note": "bar item 3: a second, non-overlapping period with a different dataset is required"}
    return {"verdict": "BAR CLEARED", "periods": periods,
            "note": "the DRAFT may now be filed as a proposal; runtime still needs implementation, audit and owner approval"}


def main(argv: list[str] | None = None) -> int:
    paths = sys.argv[1:] if argv is None else argv
    if not paths:
        print(__doc__)
        return 2
    try:
        results = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    except (OSError, ValueError) as exc:
        print(f"HATA: {exc}")
        return 2
    out = verdict(results)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
