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
before any replay (reviews N-1, NF-1, NF-5, R4-1): its symbols must equal the
sealed universe and its candles must be exactly the sealed window, one per
minute with no gap -- a window that starts on a whole minute, lasts exactly
the sealed ``days`` and lies wholly after the registration (the later of
``preregistered_at`` and the registry's own genesis time, set by
``register()``, not by the caller). Results seen before the registration can
never be re-labelled as a study, and no slice of a wider window can be chosen
after exploratory looks. A registered run downloads exactly that window.
A refused registered run (exit 2) writes a REFUSED result to ``--output``
(never evidence) so the daily agent can record the refusal instead of
waiting on it (review R5-1); a run that crashes instead (a download, parse or
replay error) writes a FAILED result (never evidence) the same way (R6-1).
Neither marks anything here: the daily agent records them and decides what
to retry. A sealed window whose exchange history has a gap
can never be run: it is refused before the run is recorded, and the owner
registers a new hypothesis.
Registered studies use one canonical registry, ``canonical_registry()``
(``<state root>/research/hypotheses.json``; review R4-2): a registry file
anywhere else is refused, so a family cannot be registered N times and the
best copy shown.
One hypothesis hosts exactly one run (review NEW-2): once the data has passed
those checks, and immediately before the replay, the run is recorded in the
registry's own durable state chain by advancing the hypothesis REGISTERED ->
CALIBRATED (``start_study_run``). A second run under the same hypothesis is
refused, so a study cannot be re-run until a good-looking result appears; a
new run needs a new hypothesis, which joins the family and must then be
reported with it (tools/regime_bar_check). A run that crashes after this point
still consumed its hypothesis -- its data was read. A registered result
carries a digest over its table, verdicts, dataset and its own study block
(hypothesis, pre-registration hash, parameters, run start; NF-4, NEW-3).
Consumers (the daily agent, tools/regime_bar_check) re-verify a
REGISTERED result against the registry with ``verify_registered_result``.
What that verification establishes: the registration exists, is sealed and
non-terminal, its one recorded run is this result's run, the result's
parameters match it, the dataset manifest claims exactly the sealed span
(first and last candle, row count; contiguity itself is checked on the raw
candles before the replay, not at verification), and the result was not
relabelled or altered after the run. What it cannot establish: that the
candle prices are genuine market data, or authenticity against someone who
rewrites the local registry or result file and recomputes the unkeyed hashes
(registry-level limit NEW-M3/U1; closing it needs keyed signing, an owner
decision).

Further documented residuals (owner decision 2026-10-09, review round 5):
- R5-2: for a names-only study the sealed specification fixes the variant
  *names*, the reference and the run parameters, not what each variant does:
  changing a variant's arguments in ``VARIANTS`` after the registration is not
  detected. A generated study (Task 005) seals each variant's exact arguments
  and their digest and runs exactly those, with the realistic reference
  enforced, which closes this part for it. For both kinds, changes to the
  replay / brain code are not detected and no code version is recorded.
- R5-5: "canonical" is per state root: ``ATLAS_STATE_DIRECTORY`` selects the
  root, so another root has another canonical registry (file-write residual).
- R5-6: exploratory runs may cover a sealed window's dates before its
  registered run (the daily agent's own exploratory runs do), so abandoning a
  family after such a look is possible; selection across families stays
  visible in the canonical registry but is not prevented (cross-family
  residual).
- Result files and memory records written before this rule may still read
  BETTER; the memory log is append-only and they are not relabelled. Without a registration the run is
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
                     step: int, exp001: bool, variant_args: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Exactly what a sealed registration must fix before the run.

    With ``variant_args`` (a generated study, Task 005) the specification also seals each
    variant's exact arguments and their digest (research.hypothesis_generation.study_spec).
    """
    if variant_args is not None:
        from research.hypothesis_generation import study_spec

        return study_spec(variant_args, reference=REFERENCE, days=days, windows=windows, embargo=embargo,
                          step=step, exp001=exp001)
    return {"variants": sorted(variants), "reference": REFERENCE, "days": days, "windows": windows,
            "embargo": embargo, "step": step, "exp001": exp001}


def _check_reference(sealed: dict[str, dict[str, Any]]) -> None:
    """A generated study tests against the realistic reference, and every variant fills exactly like it.

    Task 005 reviews F-3 (a weaker reference) and N-1 (a variant with cheaper fills): either would
    let a variant beat the reference by construction.
    """
    from research.hypothesis_generation import FILL_KNOBS, normalize_args

    realistic = normalize_args(VARIANTS[REFERENCE])
    if sealed.get(REFERENCE) != realistic:
        raise StudyRegistrationError(f"the sealed reference is not {REFERENCE!r} with realistic fills "
                                     f"{VARIANTS[REFERENCE]}; a weaker baseline cannot become a study")
    for name, args in sealed.items():
        if any(args.get(knob) != realistic.get(knob) for knob in FILL_KNOBS):
            raise StudyRegistrationError(f"variant {name!r} does not fill like the realistic reference "
                                         f"({', '.join(FILL_KNOBS)}); cheaper fills cannot become a study")


def sealed_variants(registry_path: str | Path, hypothesis_id: str) -> dict[str, dict[str, Any]] | None:
    """The sealed variant arguments of a generated study (Task 005), digest-checked; None for a names-only study."""
    from research.hypothesis_generation import GenerationError, sealed_variant_args

    record = _sealed_record(registry_path, hypothesis_id)
    try:
        return sealed_variant_args(record.preregistration.feature_spec.get(STUDY_SPEC_KEY))
    except GenerationError as exc:
        raise StudyRegistrationError(f"{hypothesis_id}: {exc}") from exc


MINUTE_MS = 60_000


def canonical_registry() -> Path:
    """The one hypothesis registry a registered study may use (review R4-2, owner decision 2026-10-09).

    ``<state root>/research/hypotheses.json``, next to the daily research files. It is
    pinned here, in tools/, not in research/ (the registry module keeps no default
    path) and not in core/ or config/. Registering a family in another registry
    file and showing only the best one is refused: no other file verifies.
    """
    from core.application import ConfiguredDirectoryError, resolve_state_directory

    try:
        return resolve_state_directory() / "research" / "hypotheses.json"
    except ConfiguredDirectoryError as exc:
        raise StudyRegistrationError(f"no canonical registry: {exc}") from exc


def _sealed_record(registry_path: str | Path, hypothesis_id: str):
    from research.hypothesis_registry import RegistryError, HypothesisRegistry

    path = Path(registry_path)
    if not path.is_file():
        raise StudyRegistrationError(f"no hypothesis registry at {path}")
    if path.resolve() != canonical_registry().resolve():
        raise StudyRegistrationError(f"{path} is not the canonical registry {canonical_registry()}")
    try:
        record = HypothesisRegistry(registry_path=path).get(str(hypothesis_id))
        record.verify_seal()
        record.verify_state_chain()
    except RegistryError as exc:
        raise StudyRegistrationError(f"{hypothesis_id}: {exc}") from exc
    return record


def _window(record) -> tuple[int, int]:
    """The sealed span as [first candle open, end) in ms -- exactly what a registered run replays.

    The span must start on a whole minute, last exactly the sealed ``days`` (review
    R4-1: no slice of a wider window can be chosen after exploratory looks) and lie
    wholly after the registration -- the later of ``preregistered_at`` and the
    registry's own genesis time, set by ``register()`` (NF-1). Naive or unreadable
    times are refused (NF-7).
    """
    from datetime import datetime, timedelta

    pre = record.preregistration
    try:
        moments = [datetime.fromisoformat(t) for t in
                   (pre.data_start, pre.data_end, pre.preregistered_at, record.state_chain[0].recorded_at)]
        days = pre.feature_spec[STUDY_SPEC_KEY]["days"]
    except (ValueError, IndexError, KeyError, TypeError) as exc:
        raise StudyRegistrationError(f"{record.hypothesis_id}: unreadable sealed window: {exc}") from exc
    if any(m.tzinfo is None or m.utcoffset() is None for m in moments):
        raise StudyRegistrationError(f"{record.hypothesis_id}: the sealed window needs timezone-aware times")
    start, end, *registered = moments
    if start < max(registered):
        raise StudyRegistrationError(f"{record.hypothesis_id}: the sealed window starts before the registration; "
                                     f"results seen earlier cannot become a study")
    if not isinstance(days, int) or isinstance(days, bool) or end - start != timedelta(days=days):
        raise StudyRegistrationError(f"{record.hypothesis_id}: the sealed window is not exactly the sealed {days!r} days")
    start_ms = int(start.timestamp() * 1000)
    if start_ms % MINUTE_MS:
        raise StudyRegistrationError(f"{record.hypothesis_id}: the sealed window must start on a whole minute")
    return start_ms, start_ms + days * 1440 * MINUTE_MS


def _check_universe(record, symbols) -> None:
    if set(symbols) != set(record.preregistration.universe):
        raise StudyRegistrationError(f"{record.hypothesis_id}: dataset symbols {sorted(symbols)} are not the "
                                     f"sealed universe {sorted(record.preregistration.universe)}")


def _candle_open(row) -> int:
    """A Binance 1-minute kline, checked in full before a registered run is recorded (reviews R5-3, R6-2).

    The checks live in research.screening.validate_candle (Task 005), shared with the
    pre-registration screening so both apply exactly the same rules; anything malformed
    raises, so a malformed dataset is refused while the hypothesis is still unspent.
    """
    from research.screening import validate_candle

    return validate_candle(row)


def _check_rows(record, data: dict[str, list[list]]) -> None:
    """Every candle: exactly the sealed span, contiguous at one minute (NF-5, R4-1)."""
    start, end = _window(record)
    _check_universe(record, data)
    for symbol, rows in data.items():
        try:
            opens = [_candle_open(row) for row in rows]
        except (TypeError, ValueError, IndexError, ArithmeticError) as exc:
            raise StudyRegistrationError(f"{record.hypothesis_id}: {symbol} has a malformed candle: {exc}") from exc
        if opens != list(range(start, end, MINUTE_MS)):
            raise StudyRegistrationError(f"{record.hypothesis_id}: {symbol} data is not exactly the sealed window, "
                                         f"one candle per minute (a gap, an extra candle, or data before the "
                                         f"registration or outside the window)")


def result_digest(result: dict[str, Any]) -> str:
    """Binds a registered result's numbers to its study block (NF-4, NEW-3; unkeyed, detects relabelling)."""
    import hashlib

    study = result.get("study") if isinstance(result.get("study"), dict) else {}
    body = {"table": result.get("table"), "verdicts": result.get("verdicts"), "dataset": result.get("dataset"),
            "study": {k: v for k, v in study.items() if k != "result_digest"}}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _check_data(record, manifest: dict[str, Any]) -> None:
    """The manifest of the replayed data must be the sealed span on the sealed universe (R4-1)."""
    start, end = _window(record)
    symbols = (manifest or {}).get("symbols") or {}
    _check_universe(record, symbols)
    for symbol, info in symbols.items():
        info = info if isinstance(info, dict) else {}
        span = (info.get("first_open"), info.get("last_open"), info.get("rows"))
        if span != (start, end - MINUTE_MS, (end - start) // MINUTE_MS):
            where = "before the registration or the sealed window" if isinstance(span[0], int) and span[0] < start else "the sealed window"
            raise StudyRegistrationError(f"{record.hypothesis_id}: {symbol} data is not exactly {where} "
                                         f"(first, last, rows = {span})")


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
    if study.get("run_started_at") != _run_started_at(record):  # NEW-2: the one recorded run
        raise StudyRegistrationError(f"{record.hypothesis_id}: this result is not the hypothesis's one recorded run")
    sealed_args = sealed_variants(registry_path, record.hypothesis_id)
    if sealed_args is not None:
        _check_reference(sealed_args)
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
    """Bind a run to its sealed pre-registration, or refuse. Validates only; start_study_run records it."""
    record = _sealed_record(registry_path, hypothesis_id)
    if record.state is not _unrun():  # terminal (NF-6) or its one run already recorded (NEW-2)
        raise StudyRegistrationError(f"{hypothesis_id} is {record.state.value}; a study runs only under a "
                                     f"{_unrun().value} hypothesis, once")
    sealed = record.preregistration.feature_spec.get(STUDY_SPEC_KEY)
    if sealed != json.loads(json.dumps(parameters)):
        raise StudyRegistrationError(f"{hypothesis_id}: this run does not match the sealed study specification")
    return {"status": "REGISTERED", "evidence_eligible": True, "hypothesis_id": record.hypothesis_id,
            "preregistration_hash": record.preregistration_hash,
            "preregistered_at": record.preregistration.preregistered_at, "parameters": parameters,
            "window_ms": list(_window(record)), "universe": sorted(record.preregistration.universe)}


def _unrun():
    from research.lifecycle import HypothesisState

    return HypothesisState.REGISTERED  # the only state a study run may start from


def _run_started_at(record) -> str | None:
    """When the hypothesis's one study run was recorded (REGISTERED -> CALIBRATED), if it was."""
    from research.lifecycle import HypothesisState

    starts = [t.recorded_at for t in record.state_chain
              if t.from_state is _unrun() and t.to_state is HypothesisState.CALIBRATED]
    return starts[0] if len(starts) == 1 else None


def start_study_run(registry_path: str | Path, study: dict[str, Any]) -> dict[str, Any]:
    """Record the run in the registry's durable state chain; a second run is refused (NEW-2)."""
    from research.hypothesis_registry import HypothesisRegistry, RegistryError
    from research.lifecycle import HypothesisState, LifecycleError
    from research.registry_lock import registry_write_lock

    with registry_write_lock(registry_path):  # Task 005 review F-1: no lost update of the run record
        record = _sealed_record(registry_path, study["hypothesis_id"])  # re-read inside the lock
        if record.state is not _unrun() or record.preregistration_hash != study["preregistration_hash"]:
            raise StudyRegistrationError(f"{record.hypothesis_id} is {record.state.value}; its one run is already recorded")
        try:
            updated = HypothesisRegistry(registry_path=Path(registry_path)).advance(
                record.hypothesis_id, HypothesisState.CALIBRATED)
        except (RegistryError, LifecycleError) as exc:
            raise StudyRegistrationError(f"{record.hypothesis_id}: the run could not be recorded: {exc}") from exc
    return {**study, "run_started_at": updated.state_chain[-1].recorded_at}


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


def _write_output(path: str, payload: dict[str, Any]) -> None:
    from datetime import datetime, timezone

    out = Path(path)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps({**payload, "finished_at": datetime.now(timezone.utc).isoformat()},
                              default=str, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out)


def _refused(args, exc: Exception) -> int:
    """Exit 2; with --output, leave a REFUSED result (never evidence) for the daily agent to record (R5-1)."""
    if args.output:
        _write_output(args.output, {"study": {"status": "REFUSED", "evidence_eligible": False,
                                              "hypothesis_id": str(args.hypothesis), "reason": str(exc)}})
    return 2


def _failed(args, exc: Exception) -> int:
    """Exit 2 on a crash (download, parse, replay); with --output, leave a FAILED result (never evidence).

    Review R6-1: a crash must not leave the daily agent waiting on a result that never comes.
    A FAILED run is not a refusal: the cause may be transient, so nothing is marked; if the
    crash came after ``start_study_run``, the hypothesis's one run is spent all the same.
    """
    if args.output:
        _write_output(args.output, {"study": {"status": "FAILED", "evidence_eligible": False,
                                              "hypothesis_id": None if args.hypothesis is None else str(args.hypothesis),
                                              "reason": f"{type(exc).__name__}: {exc}"}})
    return 2


def _run(args, variants: dict[str, dict[str, Any]], study: dict[str, Any] | None, fetch) -> dict[str, Any]:
    """Download or load, check, record the run (registered studies) and replay; raises on any failure."""
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
            raise ValueError("the saved dataset does not match its own hash")
    else:
        data = {}
        for symbol in symbols:
            print(f"downloading {symbol} ({args.days} days)...", file=sys.stderr, flush=True)
            # a registered study replays exactly its sealed window, never "the latest N days" (R4-1)
            data[symbol] = bt._history(symbol, args.days, fetch,
                                       window=tuple(study["window_ms"]) if study is not None else None)
    manifest = dataset_manifest(data)
    if study is not None:
        # before any replay: the data must be the sealed window, after registration
        check_study_data(args.registry, args.hypothesis, manifest, data)
        study = start_study_run(args.registry, study)  # last step before the replay
    if args.save_dataset:
        Path(args.save_dataset).write_text(json.dumps({"manifest": manifest, "data": data}, default=str), encoding="utf-8")
    print(f"replaying {len(variants)} variants x {args.windows} windows (this takes a while)...", file=sys.stderr, flush=True)
    result = compare(data, args.windows, args.step, not args.no_exp001, variants=variants, jobs=args.jobs, embargo=args.embargo)
    result["dataset"] = manifest
    if study is None:
        quarantine(result)
    else:
        result["study"] = dict(study)
        result["study"]["result_digest"] = result_digest(result)
    if args.output:
        _write_output(args.output, result)
    return result


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
            sealed = sealed_variants(args.registry, args.hypothesis)
            if sealed is not None:  # a generated study runs exactly its sealed arguments (Task 005, closes R5-2)
                if args.only:
                    raise StudyRegistrationError("--only cannot narrow a study with sealed variant arguments")
                from research.hypothesis_generation import replay_kwargs

                _check_reference(sealed)
                variants = {name: replay_kwargs(kw) for name, kw in sealed.items()}
            study = bind_study(args.registry, args.hypothesis, study_parameters(
                variants, days=args.days, windows=args.windows, embargo=args.embargo, step=args.step,
                exp001=not args.no_exp001, variant_args=sealed))
        except StudyRegistrationError as exc:
            print(f"STUDY REFUSED: {exc}", file=sys.stderr)
            return _refused(args, exc)
    try:
        result = _run(args, variants, study, fetch)
    except StudyRegistrationError as exc:
        print(f"STUDY REFUSED: {exc}", file=sys.stderr)
        return _refused(args, exc)
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, ArithmeticError) as exc:
        import traceback

        traceback.print_exc()
        return _failed(args, exc)
    result["parameters"] = {"embargo": args.embargo, "windows": args.windows, "step": args.step, "exp001": not args.no_exp001,
                            "variants": sorted(variants)}
    if args.json:
        print(json.dumps(result, default=str, ensure_ascii=False, indent=2))
        return 0
    manifest = result["dataset"]
    print(f"STRATEJİ KARŞILAŞTIRMASI — {len(manifest['symbols'])} coin, {args.days} gün, {args.windows} pencere, "
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
