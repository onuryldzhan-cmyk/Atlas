"""Unified analysis CLI (Task 017). Advisory research only: it never places, sizes or approves an order.

  python -m tools.unified_analysis analyze --symbol BTCUSDT              # live Binance, deterministic (no model)
  python -m tools.unified_analysis analyze --symbol BTCUSDT --ai         # + model narrative and court (ai_gateway)
  python -m tools.unified_analysis replay --symbol BTCUSDT --archive <market_data.sqlite3> \
      --start 2026-06-01T00:00:00Z --end 2026-09-01T00:00:00Z --every 24 # historical analyses, then settled
  python -m tools.unified_analysis settle [--archive <market_data.sqlite3>] # score predictions whose horizon passed
  python -m tools.unified_analysis calibration                           # track record per roster:classification

State: <state>/research/unified_analysis/experience.jsonl (append-only, hash-chained) and reports/<id>.json.
Exit codes: 0 done, 2 usage error, 3 the experience ledger is corrupt (nothing written; resolve before continuing),
4 refused: a different analysis is already recorded for this symbol, cutoff and profile (the first one stands).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.unified_analysis.contracts import AnalysisReport, to_jsonable
from tools.unified_analysis.experience import (
    ExperienceConflict,
    ExperienceLedger,
    ExperienceLedgerError,
    Pending,
    analysis_id,
    calibration,
    evaluate,
)
from tools.unified_analysis.market_intelligence import (
    INTERVAL_MS,
    ArchiveUnavailable,
    collect_archive,
    collect_binance,
    floor_cutoff,
    read_archive_rows,
)
from tools.unified_analysis.pipeline import DEFAULT_HORIZON_HOURS, DEFAULT_MAX_INFERENCE_CALLS, run_analysis

GATEWAY_AGENT = "unified_analysis"   # the name tools.ai_gateway.AI_AGENTS lists for this package
BENCHMARK = "BTCUSDT"


def default_state_dir() -> Path:
    from core.application import resolve_state_directory

    return resolve_state_directory() / "research" / "unified_analysis"


def gateway_ask(model: str | None, effort: str | None):
    """Bind tools.ai_gateway.ask: the only model path (schema-validated, sanitized, budgeted, ABSTAIN on failure)."""
    from tools import ai_gateway as ai

    ledger = ai.UsageLedger(default_state_dir().parent / ai.USAGE_FILE)

    def ask(system: str, prompt: str, schema: dict[str, Any]):
        return ai.ask(system, prompt, schema, model=model or ai.DEFAULT_MODEL, effort=effort or ai.DEFAULT_EFFORT,
                      ledger=ledger, agent=GATEWAY_AGENT)

    return ask


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("times must carry a timezone (e.g. ...Z)")
    return parsed.astimezone(UTC)


def _save_report(state: Path, report: AnalysisReport, suffix: str = "") -> Path:
    path = state / "reports" / f"{report.analysis_id}{suffix}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def render(report: AnalysisReport) -> str:
    lines = [f"ATLAS UNIFIED ANALYSIS - {report.symbol} at {report.as_of.isoformat()} (advisory, not a trade)",
             f"  classification  {report.classification.value}   confidence {report.confidence} "
             f"({report.confidence_basis.get('calibration', {}).get('status', 'n/a')}, roster "
             f"{report.confidence_basis.get('roster')})",
             f"  reasons         {', '.join(report.reason_codes) or '-'}"]
    for s in report.scenarios:
        mark = "*" if s.name == report.primary_scenario else " "
        lines.append(f" {mark}{s.name:<8} support {s.support_score:<6} groups {', '.join(s.independent_groups) or '-'}"
                     f" | invalid if: {'; '.join(c.description for c in s.invalidation) or '-'}")
    for r in report.specialists:
        lines.append(f"  [{r.agent:<11}] {r.status.value:<7} {r.stance.value:<8} {r.strength:<6} {r.reason}")
    lines.append(f"  review          court {report.review.court_status}, {len(report.review.objections)} objection(s)")
    for o in report.review.objections:
        lines.append(f"    {o.severity.value:<8} {o.category}: {o.statement}")
    for q in report.review.unresolved_questions:
        lines.append(f"    ? {q}")
    fails = report.verification.failures
    lines.append(f"  verification    {'PASS' if report.verification.passed else 'FAIL'}"
                 + (": " + "; ".join(f"{c.check_id} {c.detail}" for c in fails) if fails else ""))
    lines.append(f"  risk            {'approved' if report.risk.approved else 'REJECTED: ' + ', '.join(report.risk.rejections)}"
                 + (f" (warnings: {', '.join(report.risk.warnings)})" if report.risk.warnings else ""))
    m = report.metrics
    lines.append(f"  cost            {m.get('inference_calls', 0)} model call(s), {m.get('cost_usd')} USD, "
                 f"{m.get('timings', {}).get('total_ms')} ms")
    return "\n".join(lines)


def cmd_analyze(args: argparse.Namespace, ledger: ExperienceLedger, state: Path) -> int:
    if args.source == "archive":
        if not args.archive or not args.cutoff:
            print("--source archive needs --archive and --cutoff", file=sys.stderr)
            return 2
        inputs = collect_archive(Path(args.archive), args.symbol, floor_cutoff(args.cutoff))
    else:
        if args.cutoff:
            print("--cutoff applies only to --source archive (a live analysis is always now)", file=sys.stderr)
            return 2
        inputs = collect_binance(args.symbol)
    decision_ms = int(inputs.fetched_at.timestamp() * 1000)
    cal = calibration(ledger.records(), as_of_ms=decision_ms)   # only outcomes known at the decision time
    ask = gateway_ask(args.model, args.effort) if args.ai else None
    report = run_analysis(inputs, ask=ask, calibration=cal, horizon_hours=args.horizon,
                          max_inference_calls=args.max_calls, jurors=args.jurors)
    status, code = "not recorded (--no-record)", 0
    if not args.no_record:
        if report.reason_codes[:1] != ("DATA_UNUSABLE",):
            try:
                ledger.record_prediction(report)
                status = f"recorded in {ledger.path}"
            except ExperienceConflict as exc:
                status, code = f"NOT recorded: {exc} (the first one stands)", 4
        else:
            status = "not recorded (data unusable: not an analysis)"
    path = _save_report(state, report, suffix="" if code == 0 else f".rerun-{decision_ms}")
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=1) if args.json else render(report))
    print(f"  report          {path}  ({status})")
    return code


def cmd_replay(args: argparse.Namespace, ledger: ExperienceLedger, state: Path) -> int:
    archive = Path(args.archive)
    step = timedelta(hours=args.every)
    if args.every < args.horizon:
        print("--every must be >= --horizon: overlapping windows are not independent samples", file=sys.stderr)
        return 2
    moment, done = args.start, 0
    while moment <= args.end:
        cutoff = floor_cutoff(moment)
        if analysis_id(args.symbol, cutoff, "hist-det") in ledger.predictions():
            print(f"  {datetime.fromtimestamp(cutoff / 1000, UTC).isoformat()}  already recorded (the first one stands)")
            moment += step
            continue
        # settle what had closed by this cutoff, then calibrate on it: no outcome from after the cutoff is used
        _settle_from_archive(ledger, archive, now_ms=cutoff, only=None)
        cal = calibration(ledger.records(), as_of_ms=cutoff)
        report = run_analysis(collect_archive(archive, args.symbol, cutoff), calibration=cal,
                              horizon_hours=args.horizon, ledger=None)
        if report.reason_codes[:1] != ("DATA_UNUSABLE",):
            ledger.record_prediction(report)
        print(f"  {report.as_of.isoformat()}  {report.classification.value:<22} {report.confidence}")
        moment += step
        done += 1
    settled = _settle_from_archive(ledger, archive, now_ms=floor_cutoff(datetime.now(UTC)), only=None)
    print(f"replayed {done} cutoff(s); settled {settled} prediction(s) whose horizon has closed")
    return 0


def _settle_from_archive(ledger: ExperienceLedger, archive: Path, *, now_ms: int, only: str | None) -> int:
    settled = 0
    outcomes = ledger.outcomes()
    step = INTERVAL_MS["1h"]
    for aid, pred in ledger.predictions().items():
        if aid in outcomes or (only and pred["symbol"] != only):
            continue
        start = int(pred.get("entry_from_ms") or pred["cutoff_ms"])
        end = start + pred["horizon_ms"]
        if now_ms < end:
            continue
        try:
            rows = read_archive_rows(archive, pred["symbol"], "1h", start, end - step)
            bench = read_archive_rows(archive, BENCHMARK, "1h", start, end - step)
        except ArchiveUnavailable:
            continue
        result = evaluate(pred, rows, now_ms=now_ms, benchmark_rows=bench)
        if not isinstance(result, Pending):
            ledger.record_outcome(aid, result)
            settled += 1
    return settled


def cmd_settle(args: argparse.Namespace, ledger: ExperienceLedger, state: Path) -> int:
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    if args.archive:
        settled = _settle_from_archive(ledger, Path(args.archive), now_ms=now_ms, only=args.symbol)
        print(f"settled {settled} prediction(s) from the archive")
        return 0
    from tools.select_universe import http_get

    settled = pending = 0
    outcomes = ledger.outcomes()
    for aid, pred in ledger.predictions().items():
        if aid in outcomes or (args.symbol and pred["symbol"] != args.symbol):
            continue
        start = int(pred.get("entry_from_ms") or pred["cutoff_ms"])
        end = start + pred["horizon_ms"]
        if now_ms < end:
            pending += 1
            continue
        try:
            path = "/api/v3/klines?symbol={}&interval=1h&startTime={}&endTime={}&limit=1000"
            rows = http_get(path.format(pred["symbol"], start, end - 1))
            bench = http_get(path.format(BENCHMARK, start, end - 1))
        except Exception as exc:
            print(f"  {aid}: fetch failed ({type(exc).__name__}), left pending")
            pending += 1
            continue
        result = evaluate(pred, rows, now_ms=now_ms, benchmark_rows=bench)
        if isinstance(result, Pending):
            print(f"  {aid}: pending ({result.reason})")
            pending += 1
            continue
        ledger.record_outcome(aid, result)
        settled += 1
    print(f"settled {settled}, pending {pending}")
    return 0


def cmd_calibration(args: argparse.Namespace, ledger: ExperienceLedger, state: Path) -> int:
    cal = calibration(ledger.records(), as_of_ms=int(datetime.now(UTC).timestamp() * 1000))
    if args.json:
        print(json.dumps(to_jsonable(cal), indent=1))
        return 0
    if not cal:
        print("no settled prediction yet: every confidence is UNCALIBRATED (capped)")
    for key, v in sorted(cal.items()):
        print(f"  {key:<34} n {v['n']:<4} hit {v['hit_rate']}  wilson95 {v['wilson_lower']}  older {v['older_hit_rate']}"
              f"  newer {v['newer_hit_rate']}  {'MEASURED' if v['measured'] else 'not measured'}")
    return 0


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return number


def _non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.unified_analysis", description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyze")
    a.add_argument("--symbol", required=True, type=str.upper)
    a.add_argument("--source", choices=("binance", "archive"), default="binance")
    a.add_argument("--archive")
    a.add_argument("--cutoff", type=_parse_time)
    a.add_argument("--ai", action="store_true", help="add the model narrative and court (tools.ai_gateway)")
    a.add_argument("--model", default=None)
    a.add_argument("--effort", default=None)
    a.add_argument("--jurors", type=_non_negative_int, default=3)
    a.add_argument("--max-calls", type=_non_negative_int, default=DEFAULT_MAX_INFERENCE_CALLS)
    a.add_argument("--horizon", type=_positive_int, default=DEFAULT_HORIZON_HOURS)
    a.add_argument("--no-record", action="store_true")
    a.add_argument("--json", action="store_true")
    r = sub.add_parser("replay")
    r.add_argument("--symbol", required=True, type=str.upper)
    r.add_argument("--archive", required=True)
    r.add_argument("--start", required=True, type=_parse_time)
    r.add_argument("--end", required=True, type=_parse_time)
    r.add_argument("--every", type=_positive_int, default=24, help="hours between cutoffs (>= horizon)")
    r.add_argument("--horizon", type=_positive_int, default=DEFAULT_HORIZON_HOURS)
    s = sub.add_parser("settle")
    s.add_argument("--archive")
    s.add_argument("--symbol", type=str.upper)
    c = sub.add_parser("calibration")
    c.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state = args.state_dir or default_state_dir()
    ledger = ExperienceLedger(state / "experience.jsonl")
    handler = {"analyze": cmd_analyze, "replay": cmd_replay, "settle": cmd_settle,
               "calibration": cmd_calibration}[args.command]
    try:
        return handler(args, ledger, state)
    except ExperienceConflict as exc:
        print(f"refused: {exc} (the recorded analysis stands)", file=sys.stderr)
        return 4
    except ExperienceLedgerError as exc:
        print(f"HALT: experience ledger cannot be trusted: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
