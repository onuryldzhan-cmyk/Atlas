# ATLAS CHECKPOINT — Task 026: Forex short selling on the 1:2 margin book

## Objective
Let the forex paper book act on bearish decisions with a governed short (grant GRANT-TASK-026-FOREX-SHORT-SELLING,
registry v5.109, which also ratifies policy manifest v5).

Owner approval:
- 2026-10-26: 'Short eklensin';
- 2026-10-27: 'Kaldıraç ve short onaylı', recorded verbatim in v5.108 and v5.109.

Authority is unchanged: live DENIED, production NONE.

## Completed
- **How the side works.**
  - Orders keep the venue side (`action` BUY/SELL) and gain a `position_side` (LONG/SHORT).
  - ExecutionManager derives the side from the durable book; a caller's value is discarded:
    - a held position keeps its own side;
    - a SELL of a pair not held is SHORT when `RiskPolicy.shorts_enabled`;
    - otherwise the side is LONG.
  - LONG: BUY opens, SELL reduces. SHORT: SELL opens, BUY covers. Adds and flips are refused
    (DUPLICATE_OPEN_POSITION).
  - LONG is never serialized, so every crypto payload is byte-identical.
- **Book (`core/execution_portfolio_foundation.py`).**
  - A margin-book position may carry `side: "SHORT"`; absent means LONG, so Task 025 books stay valid.
  - `base_quantity` stays positive, so every exposure figure is the absolute notional.
  - A short's P&L is cost − notional. A cover credits released margin + gross − fee.
  - Sides never mix (POSITION_SIDE_CONFLICT).
  - A cash book refuses a short before any write (SHORT_NOT_PERMITTED_IN_CASH_BOOK).
  - Closed records carry `side`.
  - `mint_position_id` mints `short:<symbol>:<digest>` IDs.
- **RiskEngine.**
  - `RiskPolicy.shorts_enabled` is False by default and requires leverage > 1.
  - A short open passes every new-risk gate a long does; SHORT_NOT_PERMITTED is the refusal while shorts are off.
  - A cover is a reduction judged against the short only; NON_RISK_REDUCING_COVER otherwise.
- **ExecutionManager.** Every "new risk" and "reduction" decision now uses `opens_risk` / `reduces_risk`:
  - the confidence floor (the side is derived before it), the manifest and audit gates, fill bounds and the
    reservation, the position limit, the finalize reservation and settlement checks;
  - realized-P&L booking, the mirror classification, executor dispatch and shadow-book notional;
  - the admission key, risk-state sides and mark-to-market.
- **MarketLoop.** `shorts_enabled` is set from the policy in FOREX.
  - A SELL of a pair not held is new risk: it gets the pre-close, fresh-data and sizing gates.
  - A cover is never held back by those gates.
  - While the regime gate is on, no short is opened (REGIME_GATE_LONG_ONLY).
- **Exit guard.**
  - Shorts are covered with a BUY.
  - MAX_LOSS and the stop-out measure a short's loss as a rising price.
  - The weekend close covers shorts too.
- **Valuation and reports.** Valuation (C1) and EM mark-to-market are side-aware, as are `portfolio_view`,
  `paper_position_report`, `soak_report` (exit fee), `trade_evidence`, `learning_view` and `exp001_report`.
- **Recovery tool (`tools/reconcile_execution_authorities.py`), review F1.** It reads the side from the prepared
  request:
  - a short open needs its reservation;
  - a cover's realized result is booked;
  - the redo evidence of a cover is a BUY on the SHORT side;
  - the post-repair BUY adapter runs only on LONG opens.
- **`risk_check`, review F2.** It derives the side from the book before any new-risk gate, so a forged side never
  slips a short past the manifest or audit block.
- **Policy manifest v5.**
  - It adds `shorts_enabled` (CRYPTO false, FOREX true). The RiskPolicy and the MarketLoop must agree, or the
    switch reads UNREADABLE.
  - The chain is code → v5.109 → v5 → v5.108.
  - v2, v3 and v4 remain verifiable.

## Files changed
- **Commit 1:** registry v5.109 + `governance/policy/ATLAS_POLICY_MANIFEST_v5.json`.
- **Commit 2:**
  - the core and report modules above;
  - `tests/test_task026_forex_short_selling.py` (new);
  - the packaging maps;
  - this checkpoint.
- **Test changes, disclosed:**
  - `tests/test_task023_policy_manifest_v3.py`: the active-manifest path is now v5.
  - `tests/test_phase2_g1_policy_manifest.py`: the runtime keys are now `CRITICAL_SWITCHES_V5`.
- Also changed: `tools/reconcile_execution_authorities.py` (review F1).
  - `tests/test_task025_forex_leverage.py`:
    - the v4 tests name `MANIFEST_V4_PATH`, and the bad-switch checks run against v4 and the active manifest;
    - the "v4 is active" assertion is now "v4 is sealed; v5 is active";
    - one `dataclasses.replace` call also clears `shorts_enabled`, because a 1:1 policy may not allow shorts.

## Tests
- **Task 026:** 49 passed.
- **Mutation check:** 20 planted bugs. The first pass caught 18. The two survivors were killed by added tests: one
  for the finalize reservation and settlement check for a short, one for `risk_check` re-deriving a forged side.
  So 20 of 20 are caught. A further 3 planted bugs in the review fixes are all caught.
- **Independent review:** 0 BLOCKING / 1 HIGH / 1 MEDIUM / 3 LOW / 1 INFO.
  - F1 (HIGH) and F2 (MEDIUM) are fixed, with tests.
  - F6: a stale comment and the not-yet-sealed v5 source text are corrected; v5 and v5.109 were rebuilt.
  - F3, F4 and F5 (LOW) are kept as known issues, below.
  - Re-review: 0 BLOCKING / 0 HIGH / 0 MEDIUM / 3 LOW (deferred) / 1 INFO. 438 targeted tests passed. The INFO (a
    stale "LONG-only" docstring) is fixed.
- **Full suite (Python 3.13):**
  - First run: 11617 passed, 12 skipped, 0 failed.
  - Re-run after the fixes: 11620 passed, 12 skipped, 2 failed. The 2 failures were the packaging maps, whose cited
    line numbers moved with the docstring fix made during the run.
  - After regenerating the maps: `tests/architecture` + Task 026 + golden gave 151 passed.
  - Total: 11622 passed (11573 + 49), 0 failed.

## Known issues / Risks
- **Swap / rollover is not charged.** It is UNKNOWN until read from MT5. Paper results are optimistic by the swap,
  and a short typically pays a different swap than a long.
- **Passive mirrors don't show the side.** The PaperTrader mirror and the legacy PositionController are passive and
  do not show the side.
- **No hedged positions.** There are no both-sides positions on one pair.
- **Review F3 (LOW): the Brain's memory caution is BUY-only.** A SELL that opens a short skips that 0–5 point
  caution. Applying it to every SELL would lower crypto exit confidence, and the Brain does not know whether a SELL
  opens a short. Deferred Improvement.
- **Review F4 (LOW):** the PaperTrader mirror drops `side`, so a mirrored short is shown as a long. It is passive.
- **Review F5 (LOW):** `paper_position_report` attributes only BUY entries, and `lesson_book` leaves shorts out of
  the learning dataset.
- **Carried over:** T023-F4/F5/F6; the December early closes; an existing FOREX schema 2 book needs a
  re-bootstrap with `--leverage 2`.

## Remaining work
1. CLAUDE.md update (owner document).
2. **Owner: the MT5 test on Windows.** Bootstrap the book with `--leverage 2`, then measure the commission, the swap
   and the December hours.
3. A measured commission and swap (manifest change).
4. Task 020: crypto removal.

## Next exact action
CLAUDE.md update proposal for the owner (crypto → forex: market, ladder, authority unchanged).
