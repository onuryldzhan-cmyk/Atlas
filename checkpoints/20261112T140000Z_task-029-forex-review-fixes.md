# ATLAS CHECKPOINT — Task 029: Forex branch review and its fixes

## Objective
Review the whole forex branch across tasks, and fix what the review finds (grant GRANT-TASK-029-FOREX-REVIEW-FIXES,
registry v5.112).

Owner message 2026-11-12: 'Kodları gözden geçir stratejileri karşılaştır ve kalan adımları tamamla'. Asked what the
remaining steps cover, the owner chose 'MT5'siz olanlar (Önerilen)' (quoted verbatim in v5.112).

Authority is unchanged: live DENIED, production NONE.

## Completed
- **Review (AUDIT MODE).** The production diff of `feature/forex-pivot` since Task 018 (33 files, about 1950 added
  lines) was read across tasks. Three findings, recorded in v5.112 as `forex_branch_review_2026_11_12`.
- **R-1 (HIGH), fixed in part.** With negative cash in the margin book, every later exit failed in finalization and
  the runtime halted with the positions open.
  - `set_reserved_capital` now accepts a reservation that does not grow in a leveraged book, so exits settle.
  - A growing reservation and every new-risk order are still refused. The cash book (leverage 1) is unchanged.
  - **This holds only while the book's equity is positive.** Equity at or below zero is the open finding T029-F1.
- **R-2 (HIGH), fixed.** ExecutionManager remembers a clean refusal under the request id, so one transient refusal
  disabled that position's exit for good.
  - After a REJECTED answer the exit guard retries under `<id>:retry:<minute>`.
  - The first indeterminate answer (neither REJECTED nor an execution, or a raised submission) pins the id it was
    given to. That exit is never sent under another id again.
  - The FOREX runner raises `EXIT_GUARD_EXIT_NOT_EXECUTED` (metric `exit_not_executed_alerts`): at once, then once
    every 60 cycles while the failure lasts.
- **R-3 (LOW), fixed.** Outside the close-out window the pending-price alert repeats once every 60 cycles, not every
  cycle. Inside the window it still fires every cycle.
- **CRYPTO** is unchanged.

## Files changed
- **Commit 1:** registry v5.112.
- **Commit 2:**
  - `core/execution_portfolio_foundation.py` (`set_reserved_capital`);
  - `core/exit_guard.py` (retry id, pinned id);
  - `core/application.py` (alerts);
  - `tests/test_task029_review_fixes.py` (new: 15 passing tests and 1 strict expected-failure test);
  - the packaging maps (regenerated);
  - this checkpoint.
- No existing test was changed.

## Tests
- **Task 029:** 15 passed, 1 expected failure (T029-F1, strict).
- **Mutation check:** 10 planted bugs on the first version (all caught) and 8 on the audit fixes. Of those 8, the
  first pass caught 7; the survivor (the not-executed streak never resets) was killed by an added test.
- **Independent audit of the first version:** 0 BLOCKING / 1 HIGH / 3 MEDIUM / 2 LOW / 1 INFO.
  - T029-F2 MEDIUM (an indeterminate answer was retried under a new id after one REJECTED): fixed, the id is pinned.
  - T029-F3 MEDIUM (test gaps): fixed, tests added.
  - T029-F4 MEDIUM (v5.112 overclaimed): fixed before commit. The audit also showed that the BOOK fill model's
    stale-quote refusal is not cached, so it was removed from R-2's evidence.
  - T029-F5 LOW (alert every cycle): fixed. The retry still writes one idempotency record per minute per position
    while a refusal lasts (accepted).
  - T029-F6 LOW (one alert failing could cost the other): fixed.
  - **T029-F1 HIGH: OPEN.** See Known issues.
- **Full suite (Python 3.13):** 11664 passed, 12 skipped, 1 expected failure (T029-F1), 0 failed. The streak-reset test was added after that run; the Task 029 file then gave 15 passed, 1 expected failure.

## Known issues / Risks
- **T029-F1 (HIGH, open, owner decision required).** When a close leaves the book's equity at or below zero, risk
  accounting refuses the figures (`DURABLE_FIGURES_NOT_ACCOUNTABLE`), the runtime halts, and the other positions stay
  open.
  - Reproduced on the real application: a 1000 GBPUSD short opened at 1.30 and priced at 13.0.
  - The halt is fail-closed: no new risk is taken. At leverage 2 it needs an adverse move of about half the price
    past the 100 % stop-out. PAPER only.
  - It is not fixed here because every risk-state record requires positive equity (`RestoredRiskState`, `RiskState`,
    the day rollover). How a non-positive equity is accounted is a financial-state decision for the owner.
  - It predates Task 029.
- **A double close after an indeterminate answer** is blocked by the pinned id and by the durable book. The audit
  noted that ExecutionManager discards the caller's `reduce_only` and re-derives it from the book.
- **Still waiting on the owner's MT5 test:** MT5 verification, the measured commission and swap, the December
  early-close hours, crypto removal (Task 020).

## Remaining work
1. Owner: decide how equity at or below zero is accounted (T029-F1).
2. Task 030: the forex strategy comparison (its own record, v5.113).
3. Owner: the MT5 test on Windows (`proposals/2026-10-27_owner_mt5_windows_test_GUIDE.md`).

## Next exact action
Task 030: finish `tools/forex_replay.py`, its tests and its registry record, then run the comparison on the
downloaded history.
