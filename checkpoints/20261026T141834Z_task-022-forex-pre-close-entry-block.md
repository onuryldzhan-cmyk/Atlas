# ATLAS CHECKPOINT — Task 022: Forex pre-close entry block (+ owner decisions 2026-10-26)

## Objective
The owner answered five decisions one by one on 2026-10-26. This task carries out the parts that need no policy
manifest change, and records the rest for owner-approved follow-up tasks (registry v5.105,
`owner_decisions_v5_105`).

Authority is unchanged: live DENIED, production NONE.

## Completed
- **Archive.** c08897a, the old head of `vigilant-maxwell` (EXP-001 v4.94), was on no GitHub ref.
  - It is now preserved as the GitHub branch `archive/vigilant-maxwell-pre-task017`, verified with
    `git ls-remote`.
  - The session's git proxy refused the tag push four times: the remote hung up, and no relay failure was recorded.
    The local tag still exists, and the owner can push it from their own machine.
  - The bundle was moved out of the repository into the session scratchpad. The repository has no untracked files.
- **Task 022.** In FOREX, no BUY is routed in the last 60 minutes before the Friday 17:00 New York close.
  - The window comes from `atlas_finance.forex.sessions.is_forex_pre_close`.
  - The skip is recorded with reason `PRE_CLOSE_NO_NEW_RISK` and metric `buy_pre_close_skipped`.
  - SELL orders are never held back by it.
  - A check that raises, or answers anything but False, counts as in the window (fail closed).
  - CRYPTO has no such window.

## Files changed
- **Commit 1:** governance/current/ATLAS_MILESTONE_REGISTRY_v5.105.json (a successor).
- **Commit 2:**
  - atlas_finance/forex/sessions.py and `__init__.py`;
  - core/market_loop.py and core/application.py;
  - tests/test_task022_weekend_entry_block.py (new, 20 tests);
  - packaging maps (the closure is unchanged at 146 modules);
  - this checkpoint.

## Architecture decisions
- **The weekend decision is split by governance.** Closing open positions before the weekend needs the exit guard
  in ENFORCE, with a time-based rule kind, invoked from the cycle. The manifest v2 pins `exit_guard_mode` OBSERVE and
  `exit_guard_rules` 0, so this goes into the manifest v3 package together with the forex commission. A v3 draft
  never takes effect until the owner ratifies it in a registry.
- **Leverage and short selling.** Both are accepted by the owner as direction. Both change the risk, capital and
  paper-book cores (CRITICAL), with several architectural choices, so a design comes to the owner before any code.

## Tests
- **Task 022:** 20 passed. The related forex tests and the golden tests pass.
- **Mutation check:** 6 planted bugs, all 6 caught.
- **`tests/architecture`:** 102 passed.
- **Full suite (Python 3.13):** 11387 passed, 12 skipped, 0 failed (11367 before + 20 new).

## Current state
- **Branch:** `feature/forex-pivot`. Task 018, 019 and 021 are pushed (04b1e62); Task 022 is local, and its push
  waits for the owner.
- **Tag:** `archive/vigilant-maxwell-pre-task017` exists locally only. The branch of the same name is on GitHub.

## Known issues / Risks
- **Open positions are still held over the weekend** until manifest v3 is approved.
- **Earlier issues remain:** MT5 is unverified on a real terminal, the HIGH bucket sits below the minimum lot at 1:1,
  the system is long-only, and costs are spread + 0.1 %.

## Remaining work (in order)
1. **Manifest v3 draft:** the forex commission and the weekend-close exit rule, for owner approval.
2. **Leverage design:** for owner approval.
3. **Short-selling design:** for owner approval.
4. **Task 020** (crypto removal), after the MT5 verification on the owner's Windows machine.

## Next exact action
Owner approves the push of Task 022. Then draft the manifest v3 package.
