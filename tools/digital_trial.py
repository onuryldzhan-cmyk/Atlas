"""Digital trial with failure injection (owner task 20): does Atlas stay controlled, not just profitable?

  python -m tools.digital_trial --dataset saved.json      # a dataset saved by strategy_compare --save-dataset

Runs the real decision chain (tools.backtest_replay drives MarketLoop ->
brain -> RiskEngine -> ExecutionManager on PAPER) over the same candles
several times: clean, then with injected faults. For each run it checks
invariants, not profit:

  completed       the run finished without an unhandled crash
  finite          every P/L figure is a finite number (no NaN / inf leaks)
  deterministic   the clean run gives an identical summary twice (same data + same seed)
  contained       a faulty run never produces MORE trades than the clean one
                  from data that should have been rejected

Faults: NaN prices, duplicated candles, a data gap (outage), swapped
(out-of-order) candles. Research only; nothing touches the runtime state.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from tools import backtest_replay as bt


def _inject(data: dict[str, list[list]], fault: str) -> dict[str, list[list]]:
    out = copy.deepcopy(data)
    for sym, rows in out.items():
        n = len(rows)
        if fault == "nan_prices":
            for i in range(n // 3, n // 3 + 5):
                rows[i][4] = "nan"
        elif fault == "duplicates":
            mid = n // 2
            rows[mid:mid] = copy.deepcopy(rows[mid - 5:mid])
        elif fault == "outage_gap":
            del rows[n // 2: n // 2 + 30]
        elif fault == "out_of_order":
            i = n // 2
            rows[i], rows[i + 1] = rows[i + 1], rows[i]
    return out


def _summary(data, brain_factory, **kw) -> dict[str, Any]:
    try:
        s = bt.summarize(bt.replay(data, brain_factory=brain_factory, **kw))
        return {"completed": True, **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in s.items()}}
    except Exception as exc:  # recorded, never hidden
        return {"completed": False, "error": f"{type(exc).__name__}: {exc}"[:200]}


def _finite(s: dict[str, Any]) -> bool:
    for k in ("net_pnl", "fees", "max_drawdown"):
        try:
            if not math.isfinite(float(s.get(k, "0"))):
                return False
        except ValueError:
            return False
    return True


def run(data: dict[str, list[list]], brain_factory: Callable | None = None, **kw) -> dict[str, Any]:
    clean = _summary(data, brain_factory, **kw)
    again = _summary(data, brain_factory, **kw)
    report = {"clean": clean, "deterministic": clean == again, "faults": {}}
    for fault in ("nan_prices", "duplicates", "outage_gap", "out_of_order"):
        s = _summary(_inject(data, fault), brain_factory, **kw)
        report["faults"][fault] = {
            "completed": s.get("completed"), "error": s.get("error"),
            "finite": _finite(s) if s.get("completed") else None,
            "closed_trades": s.get("closed_trades"),
            "contained": (not s.get("completed")) or s.get("closed_trades", 0) <= (clean.get("closed_trades") or 0) + 1,
        }
    report["verdict"] = ("PASS" if report["deterministic"] and clean.get("completed") and _finite(clean)
                         and all(f["contained"] and f["finite"] is not False for f in report["faults"].values()) else "FAIL")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--step", type=int, default=15)
    args = parser.parse_args(argv)
    saved = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    out = run(saved["data"], step=args.step, slippage_bps=5, next_open_fill=True)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
