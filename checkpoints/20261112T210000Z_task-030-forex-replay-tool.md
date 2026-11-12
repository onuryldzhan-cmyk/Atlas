# ATLAS CHECKPOINT — Task 030: Forex replay and strategy comparison tool (comparison not yet run)

## Objective
Give the owner an exploratory comparison of the strategy variants on real forex prices (grant
GRANT-TASK-030-FOREX-REPLAY-EXPLORATORY, registry v5.113).

Owner 2026-11-12: 'Kodları gözden geçir stratejileri karşılaştır ve kalan adımları tamamla'; asked how, the owner chose
'Forex verisiyle test (Önerilen)' (quoted verbatim in v5.113).

Authority is unchanged: live DENIED, production NONE.

## Completed
- **`tools/forex_replay.py` (new, research only).** It replays the real decision chain (MarketLoop, AtlasBrain,
  RiskEngine) over forex 1-minute history with the runtime's forex rules:
  - the brain sees BID candles; a buy fills at the next minute's ASK open, a sell at the next minute's BID open;
  - the session: no new risk in the last 60 minutes, close-out 30 minutes before a close;
  - the margin book at 1:2: margin, spendable cash, stop-out at a margin level of 100 %, largest loss first;
  - shorts: a SELL of a pair not held opens a short, a BUY covers it;
  - the risk policy `main.py` runs: open losses count in the daily-loss limit, capital sleeves, marked equity;
  - the stop-out and the close-out are checked on every replayed minute.
- **13 variants** (`VARIANTS`): the reference, long only, long only without leverage, minimum hold, exit confirmation,
  trend filter, ATR stop, ATR stop with 1 % risk, cost gate, fusion fix, and three cost assumptions (spread x3,
  commission 0.35 bps a side, the runtime's present crypto fee).
- **Never evidence.** Every result carries `EXPLORATORY` and `evidence_eligible: false`; no verdict is given.
- **History loader** for Dukascopy day files (BID and ASK), cached outside the repository. The tool refuses a cache or
  output path inside the repository, never caches a partial day, and reports weekdays without data.
- **Registry v5.113** closes Task 029 as CLOSED_CONDITIONAL_PASS (T029-F1 stays open) and grants Task 030.

## NOT completed
- **The comparison itself has not been run.** The data server (datafeed.dukascopy.com) answered a short burst of
  requests and then refused this container's address ("Too Many Requests"; connections reset). Only two days of
  EURUSD were downloaded, which is not enough for a comparison. No result exists, so none is reported.

## Files changed
- **Commit 1:** registry v5.113.
- **Commit 2:** `tools/forex_replay.py` (new), `tests/test_task030_forex_replay.py` (new, 37 tests), the packaging
  maps (regenerated), this checkpoint.
- No existing code or test was changed. No market data and no result file is committed.

## Tests
- **Task 030:** 37 passed.
- **Mutation check:** 38 planted bugs, all 38 caught (two needed an added test).
- **Independent audit of the first version:** 0 BLOCKING / 1 HIGH / 2 MEDIUM / 8 LOW / 4 INFO.
  - T030-F1 HIGH (risk gates looser than the runtime's): fixed, see above.
  - T030-F2 MEDIUM (close-out could be missed): fixed, protective exits run every minute.
  - T030-F3 MEDIUM (drawdown of closed trades only): fixed, it is the marked equity's.
  - LOW: F4, F5, F6, F8, F10, F11 fixed; F9 fixed in part.
  - Accepted and disclosed in the docstring and in v5.113: F7 (sizing price against fill price), F9 (60-row "hourly"
    bars), and a spendable-cash cap that cannot bind under this policy (no test reaches it).
  - **The fixes were verified by tests and mutation only. They have not been re-audited.**
- **Full suite (Python 3.13):** 11702 passed, 12 skipped, 1 expected failure (T029-F1), 0 failed.
- **One real-data smoke run** (EURUSD, 7-8 September 2026, real brain): 179 decisions, 134 entry signals, 0 trades (24
  refused CONFIDENCE_BELOW_POLICY, 110 below the execution gate). Run on the first version; two days prove nothing.

## Known issues / Risks
- **T029-F1 (HIGH, open, owner decision):** equity at or below zero still halts the runtime with positions open.
- **Data source.** Dukascopy rate-limits hard, and its licence for anything but personal research is UNKNOWN. The
  owner's MetaTrader 5 history would be a better source once MT5 is verified.
- **Commission and swap are UNKNOWN**; the cost variants are assumptions.
- The replay is a model of the runtime's rules, not the runtime. Its known differences are listed in the docstring.

## Remaining work
1. Run the comparison once history is available (retry Dukascopy slowly, or use the owner's MT5 export).
2. Re-audit the Task 030 fixes; then close Task 030.
3. Owner: decide T029-F1.
4. Owner: the MT5 test on Windows (`proposals/2026-10-27_owner_mt5_windows_test_GUIDE.md`); then commission and swap
   (manifest v6) and crypto removal (Task 020).

## Next exact action
Retry the download at a slow pace into a cache outside the repository, then:
`python3.13 -m tools.forex_replay --cache <dir> --first 2026-08-03 --last 2026-10-30 --windows 3 --jobs 4`
