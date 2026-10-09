"""Compare every strategy variant on the same real data, window by window.

  python -m tools.strategy_compare --days 21 --windows 3
  python -m tools.strategy_compare --days 21 --windows 3 --symbols-file config/universe_selection.json

Downloads the Binance 1-minute history ONCE and replays the real Atlas
decision chain (tools/backtest_replay.replay) for each variant on each
consecutive window (walk-forward style: a variant has to hold up in every
window, not just on average - docs/research/TRADING_STRATEGY_COMPARISON_2026-09-29.md
recommendation 6). All variants use realistic fills (slippage + next-candle
fill) except the explicit "today" baseline.

Verdict per variant: BETTER only if its net P/L beats the realistic
baseline in EVERY window and its worst drawdown is not larger; otherwise
NOT PROVEN. Research evidence only; nothing in the runtime changes.

Pre-registration (P4-1, audit P4-CLOSURE-003 F-2): a run is a REGISTERED
study only when ``--registry`` and ``--hypothesis`` name a sealed hypothesis
whose ``feature_spec["strategy_compare"]`` equals this run's parameters
(variants, reference, days, windows, embargo, step, exp001). The binding is
checked before any data is downloaded; a mismatch, broken seal, unknown or
terminal hypothesis is refused (exit 2). The data itself is then checked
before any replay (reviews N-1, NF-1, NF-5): its symbols must equal the
sealed universe and every candle must lie inside the sealed window and after
the registration -- the later of ``preregistered_at`` (caller-supplied) and the
registry's own genesis time (set by ``register()``, not by the caller) -- so
results seen before the registration can never be re-labelled as a study.
A registered result carries a digest over its table, verdicts and dataset
(NF-4). Consumers (the daily agent, tools/regime_bar_check) re-verify a
REGISTERED result against the registry with ``verify_registered_result``.
What that verification establishes: the registration exists, is sealed and
non-terminal, the result's parameters and data range match it, and the
result was not relabelled or altered after the run. What it cannot
establish: authenticity against someone who rewrites the local registry or
result file and recomputes the unkeyed hashes (registry-level limit
NEW-M3/U1; closing it needs keyed signing, an owner decision). Without a registration the run is
EXPLORATORY: its table is kept, but every BETTER / NOT PROVEN verdict is
replaced by EXPLORATORY and the result is marked ``evidence_eligible: false``,
so it can never be promoted as evidence. Nothing is registered after the
fact.
"""

from __future__ import annotations

import argparse
import json
import os
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from tools import backtest_replay as bt

REALISTIC = {"slippage_bps": 5, "next_open_fill": True}
VARIANTS: dict[str, dict[str, Any]] = {
    "bugün (iyimser dolum)": {},
    "gerçekçi dolum (referans)": dict(REALISTIC),
    "min tutma 60 dk": {**REALISTIC, "min_hold_min": 60},
    "satış onayı 2": {**REALISTIC, "sell_confirm": 2},
    "1s trend filtresi EMA20": {**REALISTIC, "trend_ema_hours": 20},
    "ATR stop 2x": {**REALISTIC, "atr_stop": 2},
    "ATR stop 2x + %1 risk": {**REALISTIC, "atr_stop": 2, "risk_per_trade": 0.01},
    "aşamalı + paylar": {**REALISTIC, "staged": True, "sleeves": True},
    "maliyet kapısı 3x": {**REALISTIC, "cost_gate": 3},
    "rejim filtresi (sadece TREND_UP)": {**REALISTIC, "regime_filter": True},
    "aşamalı + paylar + maliyet kapısı": {**REALISTIC, "staged": True, "sleeves": True, "cost_gate": 3},
    "rejim filtresi + aşamalı + paylar": {**REALISTIC, "regime_filter": True, "staged": True, "sleeves": True},
    "füzyon düzeltmesi (muhalif oy güveni artırmaz)": {**REALISTIC, "fusion_fix": True},
}
REFERENCE = "gerçekçi dolum (referans)"
STUDY_SPEC_KEY = "strategy_compare"
EXPLORATORY = "EXPLORATORY"


class StudyRegistrationError(ValueError):
    """The run is not bound to a valid, sealed pre-registration."""


def study_parameters(variants: dict[str, dict[str, Any]], *, days: int, windows: int, embargo: int,
                     step: int, exp001: bool) -> dict[str, Any]:
    """Exactly what a sealed registration must fix before the run."""
    return {"variants": sorted(variants), "reference": REFERENCE, "days": days, "windows": windows,
            "embargo": embargo, "step": step, "exp001": exp001}


def _sealed_record(registry_path: str | Path, hypothesis_id: str):
    from research.hypothesis_registry import RegistryError, HypothesisRegistry

    path = Path(registry_path)
    if not path.is_file():
        raise StudyRegistrationError(f"no hypothesis registry at {path}")
    try:
        record = HypothesisRegistry(registry_path=path).get(str(hypothesis_id))
        record.verify_seal()
        record.verify_state_chain()
    except RegistryError as exc:
        raise StudyRegistrationError(f"{hypothesis_id}: {exc}") from exc
    return record


def _window(record) -> tuple[Any, Any]:
    """[earliest allowed candle, latest allowed candle] for a sealed study (NF-1, NF-7)."""
    from datetime import datetime

    pre = record.preregistration
    try:
        moments = [datetime.fromisoformat(t) for t in
                   (pre.data_start, pre.preregistered_at, record.state_chain[0].recorded_at, pre.data_end)]
    except (ValueError, IndexError) as exc:
        raise StudyRegistrationError(f"{record.hypothesis_id}: unreadable sealed window: {exc}") from exc
    if any(m.tzinfo is None or m.utcoffset() is None for m in moments):
        raise StudyRegistrationError(f"{record.hypothesis_id}: the sealed window needs timezone-aware times")
    return max(moments[:3]), moments[3]


def _check_rows(record, data: dict[str, list[list]]) -> None:
    """Every replayed candle, not just the first and last (NF-5)."""
    from datetime import UTC, datetime

    start, end = _window(record)
    if set(data) != set(record.preregistration.universe):
        raise StudyRegistrationError(f"{record.hypothesis_id}: dataset symbols {sorted(data)} are not the "
                                     f"sealed universe {sorted(record.preregistration.universe)}")
    for symbol, rows in data.items():
        for row in rows:
            moment = datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC)
            if not start <= moment <= end:
                raise StudyRegistrationError(f"{record.hypothesis_id}: {symbol} has a candle at {moment.isoformat()} "
                                             f"outside the sealed window or before the registration")


def result_digest(result: dict[str, Any]) -> str:
    """Binds a registered result's numbers to its study block (NF-4; unkeyed, detects relabelling)."""
    import hashlib

    body = {"table": result.get("table"), "verdicts": result.get("verdicts"), "dataset": result.get("dataset")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _check_data(record, manifest: dict[str, Any]) -> None:
    """The replayed data must be inside the sealed window, after registration, on the sealed universe."""
    from datetime import UTC, datetime

    pre = record.preregistration
    start, end = _window(record)
    symbols = (manifest or {}).get("symbols") or {}
    if set(symbols) != set(pre.universe):
        raise StudyRegistrationError(f"{record.hypothesis_id}: dataset symbols {sorted(symbols)} are not the "
                                     f"sealed universe {sorted(pre.universe)}")
    for symbol, info in symbols.items():
        first, last = (info or {}).get("first_open"), (info or {}).get("last_open")
        if not isinstance(first, int) or not isinstance(last, int):
            raise StudyRegistrationError(f"{record.hypothesis_id}: {symbol} has no candle time range")
        if datetime.fromtimestamp(first / 1000, tz=UTC) < start:
            raise StudyRegistrationError(f"{record.hypothesis_id}: {symbol} data starts before the sealed window or "
                                         f"before the registration; results seen earlier cannot become a study")
        if datetime.fromtimestamp(last / 1000, tz=UTC) > end:
            raise StudyRegistrationError(f"{record.hypothesis_id}: {symbol} data runs past the sealed window")


def check_study_data(registry_path: str | Path, hypothesis_id: str, manifest: dict[str, Any],
                     data: dict[str, list[list]] | None = None) -> None:
    record = _sealed_record(registry_path, hypothesis_id)
    _check_data(record, manifest)
    if data is not None:
        _check_rows(record, data)


def verify_registered_result(result: dict[str, Any], registry_path: str | Path | None) -> dict[str, Any]:
    """Re-verify a result that claims REGISTERED; raise StudyRegistrationError if it is not.

    A malformed result or registry is refused, never raised as some other error (NF-7).
    """
    try:
        return _verify_registered_result(result, registry_path)
    except StudyRegistrationError:
        raise
    except (AttributeError, TypeError, ValueError, KeyError, OSError) as exc:
        raise StudyRegistrationError(f"malformed registered result or registry: {type(exc).__name__}: {exc}") from exc


def _verify_registered_result(result: dict[str, Any], registry_path: str | Path | None) -> dict[str, Any]:
    study = result.get("study") if isinstance(result.get("study"), dict) else {}
    if study.get("status") != "REGISTERED" or not study.get("hypothesis_id"):
        raise StudyRegistrationError("not a registered study")
    if registry_path is None:
        raise StudyRegistrationError("a registered study cannot be verified without its registry")
    from research.lifecycle import is_terminal

    record = _sealed_record(registry_path, study["hypothesis_id"])
    if is_terminal(record.state):  # NF-6
        raise StudyRegistrationError(f"{record.hypothesis_id} is {record.state.value}; its results are not evidence")
    if record.preregistration_hash != study.get("preregistration_hash"):
        raise StudyRegistrationError(f"{record.hypothesis_id}: pre-registration hash does not match the registry")
    if record.preregistration.feature_spec.get(STUDY_SPEC_KEY) != study.get("parameters"):
        raise StudyRegistrationError(f"{record.hypothesis_id}: result parameters are not the sealed specification")
    _check_data(record, result.get("dataset") or {})
    if study.get("result_digest") != result_digest(result):
        raise StudyRegistrationError(f"{record.hypothesis_id}: the result was altered or relabelled after the run")
    sealed = study["parameters"]
    table = result.get("table") or {}
    if sorted(table) != sorted(sealed.get("variants", [])) or any(len(rows) != sealed.get("windows") for rows in table.values()):
        raise StudyRegistrationError(f"{record.hypothesis_id}: the result table is not the sealed study's shape")
    return study


def bind_study(registry_path: str | Path, hypothesis_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Bind a run to its sealed pre-registration, or refuse."""
    from research.lifecycle import is_terminal

    record = _sealed_record(registry_path, hypothesis_id)
    if is_terminal(record.state):
        raise StudyRegistrationError(f"{hypothesis_id} is {record.state.value}; no new study can run under it")
    sealed = record.preregistration.feature_spec.get(STUDY_SPEC_KEY)
    if sealed != json.loads(json.dumps(parameters)):
        raise StudyRegistrationError(f"{hypothesis_id}: this run does not match the sealed study specification")
    return {"status": "REGISTERED", "evidence_eligible": True, "hypothesis_id": record.hypothesis_id,
            "preregistration_hash": record.preregistration_hash,
            "preregistered_at": record.preregistration.preregistered_at, "parameters": parameters}


def quarantine(result: dict[str, Any]) -> dict[str, Any]:
    """An unregistered run: keep the numbers, withhold every verdict."""
    result["verdicts"] = {name: (v if v == "-" else EXPLORATORY) for name, v in (result.get("verdicts") or {}).items()}
    result["study"] = {"status": EXPLORATORY, "evidence_eligible": False, "reason": "NO_SEALED_PREREGISTRATION"}
    return result


def dataset_manifest(data: dict[str, list[list]]) -> dict[str, Any]:
    """Content hash + shape of the exact candles replayed (task 9 reproducibility)."""
    import hashlib

    per = {}
    h = hashlib.sha256()
    for sym in sorted(data):
        rows = data[sym]
        blob = json.dumps(rows, separators=(",", ":"), default=str).encode()
        h.update(sym.encode() + blob)
        per[sym] = {"rows": len(rows), "first_open": rows[0][0] if rows else None,
                    "last_open": rows[-1][0] if rows else None, "sha256": hashlib.sha256(blob).hexdigest()[:16]}
    return {"dataset_sha256": h.hexdigest(), "symbols": per}


def split(data: dict[str, list[list]], windows: int, embargo: int = 0) -> list[dict[str, list[list]]]:
    """Consecutive, non-overlapping windows.

    embargo > 0 (roadmap C-3, purge/embargo): the first `embargo` candles of
    every window after the first are dropped, so a trend or position spilling
    over a window boundary cannot inflate the next window's result. 0 keeps
    the historical split exactly.
    """
    if embargo < 0:
        raise ValueError("embargo must be >= 0")
    length = min(len(rows) for rows in data.values())
    size = length // windows
    if size - embargo <= bt.WINDOW + 60:
        raise ValueError(f"window too short: {size - embargo} candles after embargo; use more --days or fewer --windows")
    return [{s: rows[i * size + (embargo if i else 0):(i + 1) * size] for s, rows in data.items()} for i in range(windows)]


def _one(job: tuple) -> dict[str, Any]:
    part, step, exp001, brain_factory, kw = job
    logging.getLogger("AtlasAI.MarketLoop").setLevel(logging.ERROR)
    return bt.summarize(bt.replay(part, step=step, exp001=exp001, brain_factory=brain_factory, **kw))


def compare(data: dict[str, list[list]], windows: int, step: int, exp001: bool,
            brain_factory=None, variants: dict[str, dict[str, Any]] = VARIANTS, jobs: int = 1,
            embargo: int = 0) -> dict[str, Any]:
    """Every variant on every window. jobs > 1 runs the independent replays in parallel
    processes (same inputs, same deterministic results, just faster)."""
    parts = split(data, windows, embargo)
    work = [(name, i, (part, step, exp001, brain_factory, kw))
            for name, kw in variants.items() for i, part in enumerate(parts)]
    results: dict[tuple[str, int], dict[str, Any]] = {}
    total = len(work)
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(_one, job): (name, i) for name, i, job in work}
            for n, fut in enumerate(as_completed(futures), 1):
                results[futures[fut]] = fut.result()
                print(f"  {n}/{total} bitti ({futures[fut][0]}) - paralel {jobs}", file=sys.stderr, flush=True)
    else:
        for n, (name, i, job) in enumerate(work, 1):
            results[(name, i)] = _one(job)
            print(f"  {n}/{total} bitti ({name}) - Ctrl+C'ye basma", file=sys.stderr, flush=True)
    table = {name: [results[(name, i)] for i in range(len(parts))] for name in variants}
    ref = table[REFERENCE]
    verdicts = {}
    for name, rows in table.items():
        # A verdict needs realistic fills: slippage AND next-candle-open fills (idea: freqtrade
        # lookahead-analysis / backtesting realism). Same-candle-close variants get no verdict.
        if (name == REFERENCE or name not in variants or not variants[name].get("slippage_bps")
                or not variants[name].get("next_open_fill")):
            verdicts[name] = "-"
            continue
        beats = all(r["net_pnl"] > b["net_pnl"] for r, b in zip(rows, ref))
        no_worse_dd = max(r["max_drawdown"] for r in rows) <= max(b["max_drawdown"] for b in ref)
        verdicts[name] = "BETTER" if beats and no_worse_dd else "NOT PROVEN"
    tried = sum(1 for v in verdicts.values() if v != "-")
    # Multiple testing (Bailey & López de Prado 2014, deflated Sharpe idea): the more variants
    # are compared, the likelier one "wins" by luck. Reported, never used to pick a winner.
    return {"windows": windows, "table": table, "verdicts": verdicts,
            "multiple_testing": {"variants_judged": tried,
                                 "note": "a BETTER verdict among many variants can be luck; confirm on a second, non-overlapping period"}}


def main(argv: list[str] | None = None, fetch=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=21)
    parser.add_argument("--windows", type=int, default=3)
    parser.add_argument("--embargo", type=int, default=0,
                        help="candles dropped at the start of every window after the first (no spill-over between windows)")
    parser.add_argument("--step", type=int, default=15)
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                        help="parallel processes (default: all cores but one)")
    parser.add_argument("--output", default=None, help="also write the JSON result here atomically (used by the research agent)")
    parser.add_argument("--quick", action="store_true", help="fast check: 14 days, 2 windows, step 30")
    parser.add_argument("--symbols", default=",".join(bt.DEFAULT_SYMBOLS))
    parser.add_argument("--symbols-file", default=None, help="JSON with a 'symbols' list (config/universe_selection.json)")
    parser.add_argument("--no-exp001", action="store_true", help="replay without the EXP-001 floor")
    parser.add_argument("--only", default=None, help="comma-separated words; run only variants whose name contains one (the reference always runs)")
    parser.add_argument("--save-dataset", default=None, help="write the downloaded candles to this JSON file")
    parser.add_argument("--dataset", default=None, help="replay a saved dataset instead of downloading (reproducible)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--registry", default=None, help="hypothesis registry file holding this study's sealed pre-registration")
    parser.add_argument("--hypothesis", default=None, help="HYP-NNNN whose sealed feature_spec['strategy_compare'] fixes this run")
    args = parser.parse_args(argv)
    if bool(args.registry) != bool(args.hypothesis):
        print("--registry and --hypothesis go together", file=sys.stderr)
        return 2
    if args.quick:
        args.days, args.windows, args.step = 14, 2, 30
    variants = VARIANTS
    if args.only:
        words = [w.strip().lower() for w in args.only.split(",") if w.strip()]
        variants = {k: v for k, v in VARIANTS.items() if k == REFERENCE or any(w in k.lower() for w in words)}
    study = None
    if args.hypothesis:
        try:  # checked before any data is downloaded or replayed
            study = bind_study(args.registry, args.hypothesis, study_parameters(
                variants, days=args.days, windows=args.windows, embargo=args.embargo, step=args.step,
                exp001=not args.no_exp001))
        except StudyRegistrationError as exc:
            print(f"STUDY REFUSED: {exc}", file=sys.stderr)
            return 2
    logging.getLogger("AtlasAI.MarketLoop").setLevel(logging.ERROR)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.symbols_file:
        symbols = json.loads(Path(args.symbols_file).read_text(encoding="utf-8"))["symbols"]
    if fetch is None:
        from tools.measure_volatility_ceiling import fetch_page as fetch
    if args.dataset:
        saved = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
        data = saved["data"]
        if dataset_manifest(data)["dataset_sha256"] != saved["manifest"]["dataset_sha256"]:
            print("DATASET CORRUPTED: hash mismatch, refusing to replay", file=sys.stderr)
            return 2
    else:
        data = {}
        for symbol in symbols:
            print(f"downloading {symbol} ({args.days} days)...", file=sys.stderr, flush=True)
            data[symbol] = bt._history(symbol, args.days, fetch)
    manifest = dataset_manifest(data)
    if study is not None:
        try:  # before any replay: the data must be the sealed window, after registration
            check_study_data(args.registry, args.hypothesis, manifest, data)
        except StudyRegistrationError as exc:
            print(f"STUDY REFUSED: {exc}", file=sys.stderr)
            return 2
    if args.save_dataset:
        Path(args.save_dataset).write_text(json.dumps({"manifest": manifest, "data": data}, default=str), encoding="utf-8")
    print(f"replaying {len(variants)} variants x {args.windows} windows (this takes a while)...", file=sys.stderr, flush=True)
    result = compare(data, args.windows, args.step, not args.no_exp001, variants=variants, jobs=args.jobs, embargo=args.embargo)
    result["dataset"] = manifest
    if study is None:
        quarantine(result)
    else:
        result["study"] = {**study, "result_digest": result_digest(result)}
    if args.output:
        out = Path(args.output)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps({**result, "finished_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()},
                                  default=str, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, out)
    result["parameters"] = {"embargo": args.embargo, "windows": args.windows, "step": args.step, "exp001": not args.no_exp001,
                            "variants": sorted(variants)}
    if args.json:
        print(json.dumps(result, default=str, ensure_ascii=False, indent=2))
        return 0
    print(f"STRATEJİ KARŞILAŞTIRMASI — {len(symbols)} coin, {args.days} gün, {args.windows} pencere, "
          f"makro/sentiment hariç, ücret %0.1/taraf")
    header = "".join(f"  pencere {i + 1:<17}" for i in range(args.windows))
    print(f"{'strateji':<28}{header}  karar")
    for name, rows in result["table"].items():
        cells = "".join(f"  net {Decimal(r['net_pnl']):>8.2f} dd {Decimal(r['max_drawdown']):>6.2f} n {r['closed_trades']:>3}/{r['open_at_end']}" for r in rows)
        print(f"{name:<28}{cells}  {result['verdicts'][name]}")
    if study is None:
        print("\nKEŞİF: ön kaydı olmayan bir çalışma; kararlar verilmedi (EXPLORATORY) ve sonuç kanıt sayılmaz.")
    print("\nBETTER = her pencerede gerçekçi referanstan daha iyi net ve daha kötü olmayan en büyük düşüş. "
          "n = kapanan/pencere sonunda açık işlem. Araştırma kanıtıdır; hiçbir şey değiştirilmedi.")
    print(f"Veri seti özeti (sha256): {manifest['dataset_sha256'][:16]} — aynı sonucu almak için --save-dataset / --dataset kullan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
