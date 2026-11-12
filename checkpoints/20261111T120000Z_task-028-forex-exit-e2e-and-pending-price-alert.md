# ATLAS CHECKPOINT — Task 028: Forex exit end-to-end tests, the pending-price alert, a forex-safe report price

## Objective
Close the open Task 023 findings that do not need MT5 (grant GRANT-TASK-028-FOREX-EXIT-E2E-AND-PENDING-PRICE-ALERT,
registry v5.111):
- T023-F6: no end-to-end forex exit run.
- T023-F4: an exit the guard cannot price raises no alarm.
- `paper_position_report` asks the crypto ticker for forex pairs.

Owner messages 2026-11-11 'Hepsini düzelt (Önerilen)' and 'Her adımı profesyonel bitir', quoted verbatim in v5.111.

Authority is unchanged: live DENIED, production NONE.

## Completed
- **T023-F6 (end-to-end tests).** `tests/test_task028_forex_exit_e2e.py` runs the weekend close-out and the stop-out
  through the real FOREX `AtlasApplication`: its own exit runner, ExitGuard, ExecutionManager and the schema 3 margin
  book, with one long (EURUSD) and one short (GBPUSD). It covers:
  - the close-out inside the Friday window, and none outside it;
  - the stop-out at a margin level of 0.857, largest loss first, and none at 1.109;
  - a replayed exit request answered as a duplicate (book unchanged).
- **T023-F4 (pending-price alert).** In `core/application.py`, the FOREX exit runner counts, per symbol, the
  consecutive cycles the guard returns EXIT_PENDING_PRICE.
  - An alert fires when a symbol reaches `PENDING_PRICE_ALERT_CYCLES` (3) cycles in a row, or at once while inside the
    30-minute close-out window. An unsure window check counts as inside.
  - The alert is the MarketLoop metric `exit_pending_price_alerts`, a warning, and an `EXIT_GUARD_PRICE_UNAVAILABLE`
    event.
  - It is observability only. It runs after the guard has submitted its exits, and its own failure is caught and
    logged as an alert failure.
  - Positions the guard cannot price are still held, never sold at a guessed price.
- **Report price.** `tools/paper_position_report.live_price` returns None when `ATLAS_MARKET=FOREX`, so it never asks
  the crypto (Binance) ticker.
- **CRYPTO** is unchanged: no runner, no alert.

## Files changed
- **Commit 1:** registry v5.111.
- **Commit 2:**
  - `core/application.py`;
  - `tools/paper_position_report.py`;
  - `tests/test_task028_forex_exit_e2e.py` (new, 12 tests);
  - the packaging maps (regenerated);
  - this checkpoint.
- No existing test was changed.

## Tests
- **Task 028:** 12 passed.
- **Mutation check:** 9 planted bugs, all 9 caught:
  - no alert;
  - the streak never resets;
  - an unsure window holds the alert;
  - the window is ignored;
  - the alert fires on the first cycle;
  - no metric;
  - forex asks the crypto ticker;
  - the stop-out level is loosened;
  - the alert try/except is removed.
- **Independent review:** 0 BLOCKING / 0 HIGH / 0 MEDIUM / 2 LOW / 4 INFO.
  - LOW-1: an alert failure was reported as a failed exit run. Fixed: its own try/except, with a test.
  - LOW-2: the replay comment overclaimed. Fixed: the comment now says what is tested, and a real replay test was
    added.
  - INFO, kept:
    - the alert is not rate-limited: it repeats every cycle while the condition holds, by design;
    - the tests call the runner directly, not through `run_cycle`;
    - the map generator drops the first character of the first modified path (pre-existing, out of scope).
- **Full suite (Python 3.13):** 11648 passed, 12 skipped, 0 failed, before the two LOW fixes.
- **After the LOW fixes:** `tests/architecture`, the quality ratchet and the forex task tests gave 310 passed.

## Known issues / Risks
- **No notification channel.** The alert is an event and a metric only. The repository has no paging channel, and
  which one the owner wants is UNKNOWN.
- **No forex live price in `paper_position_report`** until MT5 is verified.
- **Map generator bug (pre-existing):** the first character of the first modified path is dropped.
- **Still waiting on the owner's MT5 test:**
  - MT5 verification;
  - the measured commission and swap;
  - the December early-close hours;
  - crypto removal (Task 020).
- **Carried over:** T023-F5 (v2 named explicitly accepts FOREX+OBSERVE; main.py always uses the active manifest).

## Remaining work
1. Owner: the MT5 test on Windows (`proposals/2026-10-27_owner_mt5_windows_test_GUIDE.md`).
2. The measured commission and swap (manifest v6).
3. Task 020: crypto removal.

## Next exact action
Wait for the owner's MT5 results.
