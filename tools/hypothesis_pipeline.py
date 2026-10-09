"""Generate, screen and register a family of strategy hypotheses (Task 005, research only).

  python -m tools.hypothesis_pipeline --template research_template.json --dry-run
  python -m tools.hypothesis_pipeline --template research_template.json --output report.json

GRANT-TASK-005-HYPOTHESIS-GENERATION-SCREENING-RESEARCH-ONLY (registry v5.88). The
pipeline itself lives in research/hypothesis_generation.py; this entry point only
supplies what research/ may not reach (ADR-0009):

- the canonical registry, ``strategy_compare.canonical_registry()``
  (``<state root>/research/hypotheses.json``) -- generated hypotheses are never
  registered anywhere else;
- the historical screening data: the last ``--history-days`` of closed one-minute
  candles, ending at the registration time, so screening never reads a sealed window;
- the quick exploratory replay (``tools.backtest_replay``, coarse ``--quick-step``)
  whose closed-trade count feeds the minimum-trades screen.

Every variant is tested against the realistic reference with realistic fills
(slippage + next-candle-open), as strategy_compare requires for a verdict. A
registered hypothesis is then run once, later, after its sealed window has ended:
``python -m tools.strategy_compare --registry <canonical> --hypothesis HYP-NNNN
--days D --windows W --embargo E --step S``, which executes exactly the sealed
arguments. The report printed here is never evidence. Exit 0 on a completed run
(whatever the candidates' statuses), 2 on a refused request or a failed download.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools import backtest_replay as bt
from tools import strategy_compare as sc

TEMPLATE_FIELDS = {"name", "family_id", "author", "universe", "base_args", "grid", "periods", "economic_rationale",
                   "days", "windows", "embargo", "step", "exp001", "alpha", "minimum_effect_size", "correction"}


def load_template(raw: dict[str, Any]):
    """A template file -> research Template, tested against the realistic reference with realistic fills."""
    from research.hypothesis_generation import GenerationError, Template

    if not isinstance(raw, dict):
        raise GenerationError("the template must be a JSON object")
    unknown = set(raw) - TEMPLATE_FIELDS
    if unknown:
        raise GenerationError(f"unknown template fields {sorted(unknown)}; the reference is always "
                              f"{sc.REFERENCE!r} with realistic fills")
    base = dict(raw.get("base_args") or {})
    for key, value in sc.REALISTIC.items():
        if base.get(key, value) != value:
            raise GenerationError(f"base_args.{key} must stay {value!r}: verdicts need realistic fills")
        base[key] = value
    try:
        return Template(**{**raw, "universe": tuple(raw.get("universe") or ()), "periods": tuple(raw.get("periods") or ()),
                           "base_args": base, "reference": sc.REFERENCE, "reference_args": dict(sc.REALISTIC)})
    except TypeError as exc:
        raise GenerationError(f"the template is missing a field: {exc}") from exc


def quick_trades(step: int, exp001: bool):
    """A coarse exploratory replay of one candidate on the screening data; returns its closed trades."""
    from research.hypothesis_generation import replay_kwargs

    def run(candidate, data) -> int:
        logging.getLogger("AtlasAI.MarketLoop").setLevel(logging.ERROR)
        result = bt.replay({s: list(rows) for s, rows in data.items()}, step=step, exp001=exp001,
                           **replay_kwargs(candidate.args))
        return int(bt.summarize(result)["closed_trades"])

    return run


def main(argv: list[str] | None = None, fetch=None, now: datetime | None = None) -> int:
    from research.hypothesis_generation import GenerationError, run_pipeline
    from research.hypothesis_registry import HypothesisRegistry, RegistryError
    from research.screening import ScreeningError, ScreeningSpec

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--template", required=True, help="JSON template (see research/hypothesis_generation.Template)")
    parser.add_argument("--history-days", type=int, default=30, help="screening data: this many days before now")
    parser.add_argument("--quick-step", type=int, default=60, help="decision step (minutes) of the quick replay")
    parser.add_argument("--max-zero-volume", default="0.05", help="largest allowed fraction of zero-volume candles")
    parser.add_argument("--minimum-trades", type=int, default=30, help="closed trades the quick replay must make")
    parser.add_argument("--dry-run", action="store_true", help="screen and plan, register nothing")
    parser.add_argument("--output", default=None, help="also write the report (JSON) here")
    args = parser.parse_args(argv)

    now = now or datetime.now(timezone.utc)
    end_ms = int(now.timestamp() * 1000) // 60_000 * 60_000
    start_ms = end_ms - args.history_days * 1440 * 60_000
    try:
        template = load_template(json.loads(Path(args.template).read_text(encoding="utf-8")))
        spec = ScreeningSpec(start_ms=start_ms, end_ms=end_ms, cutoff_ms=int(now.timestamp() * 1000),
                             max_zero_volume_fraction=args.max_zero_volume, minimum_trades=args.minimum_trades)
        path = sc.canonical_registry()
        path.parent.mkdir(parents=True, exist_ok=True)  # the research folder of the state root (R4-2)
        HypothesisRegistry(registry_path=path)  # an unreadable registry is refused before any download
    except (OSError, ValueError, GenerationError, ScreeningError, RegistryError, sc.StudyRegistrationError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if fetch is None:
        from tools.measure_volatility_ceiling import fetch_page as fetch
    try:
        historical = {symbol: bt._history(symbol, args.history_days, fetch, window=(start_ms, end_ms))
                      for symbol in template.universe}
    except (OSError, ValueError, TypeError, IndexError) as exc:
        print(f"FAILED: the screening data could not be downloaded: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    try:
        report = run_pipeline(template, path, historical=historical, screening=spec, now=now,
                              quick_trades=quick_trades(args.quick_step, template.exp001), dry_run=args.dry_run)
    except (GenerationError, ScreeningError, RegistryError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:  # e.g. the registry lock is held (RegistryLockError): transient, nothing written
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    report["registry"] = str(path)
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
