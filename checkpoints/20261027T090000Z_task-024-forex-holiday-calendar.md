# ATLAS CHECKPOINT — Task 024: The forex holiday calendar

## Objective
Never open or carry a forex position into a Christmas or New Year closure (review finding T023-F3). Friday
2026-12-25 and Friday 2027-01-01 are the first ones (grant GRANT-TASK-024-FOREX-HOLIDAY-CALENDAR, registry v5.107).

Owner message 2026-10-27, quoted verbatim in v5.107: 'Önce tatil takvimi' (the holiday calendar before leverage).
That answer approves this task only, not leverage or short selling.

Authority is unchanged: live DENIED, production NONE.

## Completed
- **`atlas_finance/forex/sessions.py`.**
  - `HOLIDAYS = ((12, 25), (1, 1))`.
  - A forex trading day D runs from 17:00 New York time on D-1 to 17:00 on D. A holiday closes that whole session.
  - `is_forex_market_open` is the only function changed. The change can only add closed time; it never opens the
    market.
  - Docstrings for `is_forex_pre_close` and `next_forex_open` updated.
- **Effect on every caller** (no caller code changed):
  - the MARKET_CLOSED gate;
  - the 60-minute pre-close entry block;
  - the 30-minute WEEKEND_CLOSE exit rule, which now acts on Thursday 24 Dec and Thursday 31 Dec 2026;
  - MT5 offset measurement, which refuses during a holiday (fails closed).
- **CRYPTO** is unchanged: these functions are wired only in FOREX.
- **Manifest and ratification:** policy manifest v3 and its v5.106 ratification are unchanged. v5.106's bytes are
  identical to HEAD.

## Files changed
- **Commit 1:** `governance/current/ATLAS_MILESTONE_REGISTRY_v5.107.json`, alone. It closes Task 023 and opens
  Task 024.
- **Commit 2:**
  - `atlas_finance/forex/sessions.py`;
  - `tests/test_task024_forex_holidays.py` (new, 46 tests);
  - `packaging/REM-001_STATE_AUTHORITY_MAP.md`, regenerated with `python -m tools.build_rem001_gate1_maps state
    --write` (a cited line number moved);
  - this checkpoint.
- No existing test was changed.

## Tests
- **Task 024:** 46 passed.
- **Mutation check:** 6 planted bugs on a scratch copy, all 6 caught:
  - holiday check removed;
  - calendar day instead of trading day;
  - New Year dropped;
  - shift sign reversed;
  - shift off by one hour;
  - UTC used instead of New York time.
- **Independent read-only review:** 0 BLOCKING / 0 HIGH / 0 MEDIUM / 2 LOW / 2 INFO.
  - **Fixed before commit:**
    - LOW: stale `next_forex_open` docstring.
    - LOW: missing test cases (Sunday holidays, a non-UTC aware input, 60 minutes before 31 Dec, the FOREX
      application's own gates).
  - **INFO, kept:** declared scope limits; MT5 `connect()` without a configured offset refuses during a holiday as on
    a weekend.
- **Full suite (Python 3.13):**
  - First run: 11495 passed, 12 skipped, 1 failed. The failure was the state authority map: a cited line number had
    moved.
  - After regenerating the map, `tests/architecture` gave 102 passed. Total: 11496 passed (11450 + 46 new),
    12 skipped, 0 failed.
  - An earlier run used `python` (3.11, no numpy) by mistake and gave collection errors unrelated to this change. The
    gate runs on 3.13, as for every earlier task.

## Known issues / Risks
- **Broker early closes are not modelled.** Brokers may close early on 24 and 31 December; the hours are UNKNOWN until
  measured on the owner's MT5 demo. Until then, the Thursday 16:30 close-out may come after a broker's early close. If
  it does, the marks are stale, the exit is EXIT_PENDING_PRICE, and the position is carried through the holiday.
- **No observed-Monday closures.** A Saturday or Sunday holiday adds no Monday closure.
- **Weekday holidays close positions too.** A weekday holiday (e.g. Thursday 2025-12-25) is a closure as well:
  positions are closed before it. This is a disclosed extension of 'Yalnız Cuma kapanışı'.
- Open issues carried from Task 023: T023-F4, F5, F6.

## Remaining work
1. **Leverage 1:2 (margin accounting)** — CRITICAL; needs its own explicit owner approval.
2. **Short selling** — CRITICAL; needs its own explicit approval.
3. **CLAUDE.md update** — owner document.
4. **Owner: MT5 test on Windows**, plus the December early-close hours.
5. **Measured commission (manifest change).**
6. **Task 020: crypto removal.**

## Next exact action
Ask the owner for the explicit leverage approval ("Kaldıraç (1:2) görevini onaylıyorum"), then design-to-code:
- the forex book schema 3;
- margin = notional / 2;
- stop-out at 100 %;
- a new manifest pin for L.
