# ATLAS CHECKPOINT — Task 023: Policy manifest v3 and the forex weekend close

## Objective
Activate policy manifest v3, so that open forex positions are closed in the last 30 minutes before the Friday 17:00
New York close (grant GRANT-TASK-023-POLICY-MANIFEST-V3-FOREX, registry v5.106).

Owner messages behind this (2026-10-26/27, quoted verbatim in v5.106):
- "Manifesto v3 hazırla", with the owner's values;
- the order "v3 → kaldıraç → short";
- "Hepsini yap", and "Onay sana kalan işleri tek tek yap hepsini".

Authority is unchanged: live DENIED, production NONE.

## Completed
- **Ratification chain.** The chain is anchored in code and runs one way:
  - the code pins v5.106's sha256 (`V3_RATIFICATION_REGISTRY_SHA256`);
  - v5.106's `policy_manifest_v3_ratification` pins the bytes of governance/policy/ATLAS_POLICY_MANIFEST_v3.json;
  - manifest v3 pins its sealed base, v5.105.
  - EXP-002's parameters are still compared with the sealed v5.85 grant.
- **`core/policy_manifest.py`.**
  - v3 is the active `MANIFEST_PATH`. v2 is kept as `MANIFEST_V2_PATH` and is still verified by its own unchanged
    rules when it is named.
  - The default path is read at call time.
  - `_verify_v3` adds:
    - the forex switches (`market`, `forex_paper_fee_rate`, `forex_weekend_close_minutes`);
    - a `by_market` matcher; an unknown or unreadable market never matches;
    - the ratification check (the code's own path, never the manifest's choice);
    - the PAPER-only invariant.
- **`core/exit_guard.py`.** A new `WEEKEND_CLOSE` rule kind:
  - minutes 1–120 plus an `in_window(now)` check;
  - an unsure check exits, which is risk-reducing;
  - `MAX_LOSS_PCT` is unchanged.
- **`core/market_loop.py`.** `exit_guard_runner` is called once at the start of each cycle, before any decision. A
  failure is logged and the cycle continues. CRYPTO has no runner (None).
- **`core/application.py`.** In FOREX:
  - the exit guard runs in ENFORCE with the single `WEEKEND_CLOSE` rule (30 minutes);
  - it uses only fresh closed-candle marks (the guard's 120 s limit);
  - its SELLs are reduce-only, full-exit SELLs through ExecutionManager.
  - CRYPTO is unchanged: OBSERVE, no rules, not run from the cycle.

## Files changed
- **Commit 1:**
  - governance/current/ATLAS_MILESTONE_REGISTRY_v5.106.json;
  - governance/policy/ATLAS_POLICY_MANIFEST_v3.json.
  - The two belong together: v5.106 pins the manifest's bytes.
- **Commit 2:**
  - the four core modules and `atlas_finance/forex/sessions.py` (`WEEKEND_CLOSE_MINUTES = 30`);
  - `tests/test_task023_policy_manifest_v3.py` (new, 63 tests);
  - packaging maps;
  - this checkpoint.
- **Test changes, disclosed:**
  - `tests/test_phase2_g1_policy_manifest.py` and `tests/test_phase2_g2_exp002_grant.py` get an autouse fixture that
    pins the sealed v2 chain they test.
  - In g1, one assertion changes: the runtime keys are now the v3 set, which still covers every v2 switch.
  - In g2, the real-app test names `MANIFEST_V2_PATH` explicitly, because its helper calls `monkeypatch.undo()`.
    The same check against v3 runs in the new tests, for both markets.

## Tests
- **Task 023:** 63 passed (57, then after the review one test replaced, 6 added and one case added: 57 - 1 + 6 + 1).
- **Manifest tests:** g1, g2 and merged-process: 127 passed, 1 skipped.
- **Mutation check:** 14 real planted bugs, all 14 caught. A fifteenth, badly formed mutant (an unused variable) was
  replaced by a real one, which was caught.
- **Independent read-only review:** 0 BLOCKING / 0 HIGH / 0 MEDIUM / 3 LOW / 4 INFO, before the fixes.
  - **Fixed before commit:**
    - **T023-F1:** the window is now computed from the rule's own minutes, and a FOREX guard that the cycle does not
      run makes `forex_weekend_close_minutes` UNREADABLE, which blocks new risk.
    - **T023-F2:** each mark carries its own candle's open time, so the guard's own age check refuses a stale or
      future-stamped candle.
  - **Kept as known issues:** F3–F7, below.
- **`tests/architecture`:** 102 passed.
- **Full suite (Python 3.13):** 11450 passed, 12 skipped, 0 failed (11387 before + 63 new).

## Current state
- **Branch:** `feature/forex-pivot`, under the standing push approval.

## Known issues / Risks
- **The manifest still says 0.1 %.** The forex commission is not measured yet; that happens on the owner's MT5 demo.
- **Not run on real MT5.** The weekend close has never run against a real MT5 terminal; the unknowns in v5.102
  apply.
- **Holidays are not modelled** in the session window (review T023-F3). Christmas (Fri 2026-12-25) and New Year
  (Fri 2027-01-01) are Friday holidays: the close-out would aim at a closed Friday, and positions would be carried
  through the long weekend. This needs a holiday calendar, or the owner's explicit deferral, before 2026-12-24.
- **Pending marks raise no alarm (T023-F4).** The runner reads the previous cycle's candles. A cycle right after a
  minute rollover can therefore be EXIT_PENDING_PRICE. Missing marks are only logged; nothing escalates (this fails
  toward holding).
- **v2 named explicitly (T023-F5).** Checking a FOREX runtime against v2 on purpose accepts OBSERVE (v2 has no
  market switch); main.py always uses v3.
- **Coverage gap (T023-F6).** No real end-to-end forex exit was run, because `config/instrument_rules_mt5.json`
  only exists after the owner's MT5 run.
- **Scope of the approval (T023-F7).** v5.106 records the owner's words and states its own reading of them. The
  owner's "Hepsini yap" is **not** reused as approval for the leverage and short-selling CRITICAL tasks: each needs
  its own explicit approval.

## Remaining work
1. **Leverage 1:2 (margin accounting)** — CRITICAL.
2. **Short selling** — CRITICAL.
3. **CLAUDE.md update** — owner document.
4. **Owner: MT5 test on Windows.**
5. **Measured commission (manifest change).**
6. **Task 020: crypto removal.**

## Next exact action
Design-to-code for leverage: the forex book schema 3, margin accounting, sizing × 2 and stop-out at 100 %.
