"""Evaluate, adjudicate and shortlist sealed generated studies (Task 006, research only).

  python -m tools.strategy_selection evaluate --result out.json      # one verified run -> its single TEST evaluation
  python -m tools.strategy_selection adjudicate --family FAM-...     # BH (+ sealed Bonferroni) over a complete family
  python -m tools.strategy_selection status --family FAM-...         # why a family is not ready (read-only)
  python -m tools.strategy_selection record-failed-run --hypothesis HYP-... --reason "..."   # crashed, no result
  python -m tools.strategy_selection abandon --hypothesis HYP-... --reason "..."             # never run: p = 1
  python -m tools.strategy_selection shortlist [--max-correlation 0.8] [--output report.json]   # read-only

GRANT-TASK-006-MULTI-STRATEGY-COMPARISON-SELECTION-RESEARCH-ONLY (registry v5.89).
The statistics live in research/strategy_evaluation.py; this entry point supplies
what research/ may not reach (ADR-0009):

- only the canonical registry (``strategy_compare.canonical_registry()``) is used;
- ``evaluate`` first re-verifies the result with ``strategy_compare
  .verify_registered_result`` (seal, one recorded run, sealed window, digest,
  realistic reference and fills): an EXPLORATORY, REFUSED, FAILED, forged or
  unregistered result is refused and nothing is recorded;
- every registry write (the TEST evaluation, the adjudication) happens under the
  registry write lock on a registry re-read inside it. The registry itself
  refuses a second TEST evaluation of the same hypothesis.

Exit 0 on success, 2 on a refusal (nothing written) or a transient failure such
as a held lock (nothing written; retry). Output is never trading or capital
authority: no weights, no sizes, no allocation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools import strategy_compare as sc


def _evaluate(args) -> dict[str, Any]:
    from research.hypothesis_registry import HypothesisRegistry
    from research.registry_lock import registry_write_lock
    from research.strategy_evaluation import (InsufficientSampleError, evaluate_result, evaluation_record,
                                              no_evidence_record)

    registry = sc.canonical_registry()
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise sc.StudyRegistrationError("the result is not a JSON object")
    study = sc.verify_registered_result(result, registry)  # never trust the file's own claim
    try:
        evaluation = evaluate_result(result)
    except InsufficientSampleError as exc:  # a genuine run without usable evidence: counted, never passed
        with registry_write_lock(registry):
            fresh = HypothesisRegistry(registry_path=registry)  # re-read inside the lock
            sc.verify_registered_result(result, registry)
            fresh.record_evaluation(study["hypothesis_id"], no_evidence_record(str(exc)))
        return {"hypothesis_id": study["hypothesis_id"], "state": "TESTED", "status": "NO_EVIDENCE", "p_value": 1.0,
                "reason": str(exc), "evidence_eligible": False,
                "note": "scored p = 1 and counted as one of the family's tests; it can never pass"}
    with registry_write_lock(registry):
        fresh = HypothesisRegistry(registry_path=registry)  # re-read inside the lock
        sc.verify_registered_result(result, registry)       # still the hypothesis's one verified run
        fresh.record_evaluation(study["hypothesis_id"], evaluation_record(evaluation))
    return {"hypothesis_id": study["hypothesis_id"], "state": "TESTED", "p_value": evaluation.p_value,
            "effect_size": evaluation.effect_size, "mean_difference": evaluation.mean_difference,
            "ci": [evaluation.ci_low, evaluation.ci_high], "better_verdict": evaluation.better_verdict,
            "stats": evaluation.stats, "evidence_eligible": False,
            "note": "recorded once as the hypothesis's TEST evaluation; the family decides after adjudication"}


def _adjudicate(args) -> dict[str, Any]:
    from research.hypothesis_registry import HypothesisRegistry
    from research.registry_lock import registry_write_lock
    from research.strategy_evaluation import adjudication_readiness, family_q

    registry = sc.canonical_registry()
    with registry_write_lock(registry):
        fresh = HypothesisRegistry(registry_path=registry)
        readiness = adjudication_readiness(fresh, args.family)
        if not readiness["ready"]:
            raise _NotReady(readiness)
        q = family_q(fresh, args.family)
        decision = fresh.adjudicate_family(args.family, q=q)
    after = HypothesisRegistry(registry_path=registry)
    return {"family_id": args.family, "q": q, "n_tests": decision.n_tests, "n_rejected_by_bh": decision.n_rejected,
            "states": {r.hypothesis_id: r.state.value for r in after.family(args.family)},
            "note": "CANDIDATE confers no trading authority; it passed BH, its own sealed alpha, its effect size and "
                    "its sealed checks"}


def _record_failed_run(args) -> dict[str, Any]:
    """A run that crashed without any result: recorded as NO EVIDENCE (p = 1), so it stays one of the m tests."""
    from research.hypothesis_registry import HypothesisRegistry
    from research.lifecycle import HypothesisState
    from research.registry_lock import registry_write_lock
    from research.strategy_evaluation import no_evidence_record, run_recorded

    if not str(args.reason).strip():
        raise ValueError("a failed run needs a reason")
    registry = sc.canonical_registry()
    with registry_write_lock(registry):
        fresh = HypothesisRegistry(registry_path=registry)
        record = fresh.get(args.hypothesis)
        if record.state is not HypothesisState.CALIBRATED or not run_recorded(record):
            raise ValueError(f"{args.hypothesis} is {record.state.value}: only a recorded run without a TEST "
                             f"evaluation can be recorded as failed")
        fresh.record_evaluation(args.hypothesis, no_evidence_record(f"run failed without a result: {args.reason}"))
    return {"hypothesis_id": args.hypothesis, "state": "TESTED", "status": "NO_EVIDENCE", "p_value": 1.0,
            "reason": args.reason, "evidence_eligible": False}


def _abandon(args) -> dict[str, Any]:
    """An unrun member no longer wanted: counted as NO EVIDENCE (p = 1), so m never shrinks (review N-1).

    The registry's test segment is readable only from CALIBRATED, so the member is advanced
    REGISTERED -> CALIBRATED (no data is read: no result for it can ever verify, because no
    run of it produced one) and its single TEST evaluation is recorded as p = 1.
    """
    from research.hypothesis_registry import HypothesisRegistry
    from research.lifecycle import HypothesisState
    from research.registry_lock import registry_write_lock
    from research.strategy_evaluation import no_evidence_record

    if not str(args.reason).strip():
        raise ValueError("abandoning a member needs a reason")
    registry = sc.canonical_registry()
    with registry_write_lock(registry):
        fresh = HypothesisRegistry(registry_path=registry)
        if fresh.get(args.hypothesis).state is not HypothesisState.REGISTERED:
            raise ValueError(f"{args.hypothesis} is {fresh.get(args.hypothesis).state.value}: only a member that "
                             f"never ran can be abandoned (a recorded run uses evaluate or record-failed-run)")
        fresh.advance(args.hypothesis, HypothesisState.CALIBRATED)
        fresh.record_evaluation(args.hypothesis, no_evidence_record(f"abandoned without a run: {args.reason}"))
    return {"hypothesis_id": args.hypothesis, "state": "TESTED", "status": "NO_EVIDENCE", "p_value": 1.0,
            "reason": args.reason, "evidence_eligible": False,
            "note": "counted as one of the family's m tests with p = 1; it can never pass"}


class _NotReady(Exception):
    def __init__(self, readiness: dict[str, Any]) -> None:
        super().__init__(readiness["reason"])
        self.readiness = readiness


def main(argv: list[str] | None = None) -> int:
    from research.hypothesis_generation import GenerationError
    from research.hypothesis_registry import HypothesisRegistry, RegistryError
    from research.multiple_testing import MultipleTestingError
    from research.strategy_evaluation import EvaluationError, adjudication_readiness, shortlist

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    evaluate = sub.add_parser("evaluate", help="record one verified run's single TEST evaluation")
    evaluate.add_argument("--result", required=True)
    for name in ("adjudicate", "status"):
        sub.add_parser(name).add_argument("--family", required=True)
    failed = sub.add_parser("record-failed-run", help="a recorded run that crashed without a result: p = 1")
    abandon = sub.add_parser("abandon", help="a member that never ran and is no longer wanted: p = 1")
    for p in (failed, abandon):
        p.add_argument("--hypothesis", required=True)
        p.add_argument("--reason", required=True)
    short = sub.add_parser("shortlist", help="rank CANDIDATE ideas (read-only)")
    short.add_argument("--max-correlation", type=float, default=0.8)
    for p in (evaluate, short):
        p.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    try:
        if args.command == "evaluate":
            out = _evaluate(args)
        elif args.command == "adjudicate":
            out = _adjudicate(args)
        elif args.command == "record-failed-run":
            out = _record_failed_run(args)
        elif args.command == "abandon":
            out = _abandon(args)
        elif args.command == "status":
            out = adjudication_readiness(HypothesisRegistry(registry_path=sc.canonical_registry()), args.family)
        else:
            out = shortlist(HypothesisRegistry(registry_path=sc.canonical_registry()),
                            max_correlation=args.max_correlation)
    except _NotReady as exc:
        print(json.dumps({"refused": str(exc), **exc.readiness}, ensure_ascii=False, indent=2))
        return 2
    except (sc.StudyRegistrationError, EvaluationError, GenerationError, RegistryError, MultipleTestingError,
            ValueError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:  # a held registry lock or another I/O failure: transient, nothing written
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    if getattr(args, "output", None):
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
