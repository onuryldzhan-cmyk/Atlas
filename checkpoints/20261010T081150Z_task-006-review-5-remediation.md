# ATLAS CHECKPOINT — Task 006: review-5 remediation (M-A mark-to-market, L-A/L-B/L-C)

## Objective
Close the open findings of the fifth independent review of Task 006 (commit e7cdba9, PASS 0 BLOCKING/0 HIGH)
per the owner's decision of 2026-10-10 on M-A: "Fix: mark to market".

## Completed
- M-A:
  - `tools/backtest_replay.py` adds `Result.marked_open` (`_mark_to_market`). Each position still open at a
    window's end is valued at the last valid close × (1 − slippage), less the exit fee, and dated at that
    candle's close, inside the window.
  - `tools/strategy_compare.daily_net` and `ev_components` include the marks; `ev.marked_open` counts them.
  - Unchanged: `trades`, `open_trades`, `summarize()`, closed-trade `net_pnl` and the BETTER verdict.
- L-A: a regime test with a noon crash (day 4 stays SIDEWAYS, day 5 is PANIC).
- L-B: resamples without spread widen the bootstrap-t interval on both sides. An unbounded side is recorded as
  null (`StudyEvaluation.ci()`), and the shortlist ranks a null bound last (`_lowest`, `_rank_key`).
- L-C: digest refusal cases for variant/reference `daily_net`, `ev`, a regime label, and deleted `regimes`.
- Review 6 (fresh context) PASS: 0 BLOCKING / 0 HIGH / 0 MEDIUM. Its LOW findings:
  - F1: tests that a mark equals a real sell at the window end in the staged, partial-sell, tranche and
    next-open cases, plus the corrupt-last-close fallback.
  - F2: null ranking tested.
  - F3: recorded in v5.90 as UNKNOWN.
- Registry v5.90 is a successor of v5.89. It adds only `task_006_review_5_remediation_v5_90` and
  `changes_v5_90`.

## Files changed
tools/backtest_replay.py, tools/strategy_compare.py, research/strategy_evaluation.py, tools/strategy_selection.py,
tests/research/test_task006_strategy_selection.py, governance/current/ATLAS_MILESTONE_REGISTRY_v5.90.json, this
checkpoint.

## Architecture decisions
- Mark-to-market happens inside the replay: open positions don't expose their held quantity or partial-sell
  proceeds outside it.
- The OUT_OF_SAMPLE/BETTER check is unchanged. The p-value now includes the marks.

## Tests
- Mutation-checked: removing the marks, same-day lookahead, narrowing the CI, dropping regimes from the
  digest, dropping partial-sell proceeds, and dropping the corrupt-close fallback each fail a new test.
- Full suite before the review-6 LOW fixes: 10349 passed, 12 skipped, 0 failed.
- Re-run after them (2026-10-10): 10353 passed, 12 skipped, 0 failed (exit 0).

## Current state
Task 006 milestone ACTIVE. Every review finding is fixed or recorded.

## Known issues
- **F3:** the owner has not explicitly confirmed approval for changing the shared `tools/backtest_replay.py`
  (UNKNOWN in v5.90). It was derived from the M-A decision.
- Informational, unchanged:
  - the unkeyed result digest (pre-existing);
  - `Template.days` defaults to 30 (conservative);
  - exit code 2 is shared by refusals and transient failures;
  - a non-numeric trailing close now raises when a position is open at the window end (fails closed).
- Pre-existing and unrelated: the clock-resolution flake in `tests/test_apprentice.py`. Proposed fix: freeze
  `atlas_org_cli.now` in that test.

## Risks
Peso-problem residual at 90 days: about 3–14% false positives for rare-loss P/L (owner-accepted, v5.89).

## Remaining work
- Owner: confirm or reverse the `backtest_replay.py` scope addition (F3).
- Owner: decide whether to close the Task 006 milestone (a closure needs a successor registry).

## Next exact action
Report to the owner and ask for the F3 confirmation and the Task 006 closure decision.
