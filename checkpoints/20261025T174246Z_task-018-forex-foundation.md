# ATLAS CHECKPOINT — Task 018: Forex foundation (crypto → forex pivot, step 1)

## Objective
Owner decision of 2026-10-25: Atlas moves from crypto to forex, through MetaTrader 5, and crypto is removed. The
owner's choices were "remove crypto", "MetaTrader 5" and "start implementing now". Task 018 (grant
GRANT-TASK-018-FOREX-FOUNDATION, registry v5.102) builds the forex foundations: instruments, the trading session and a
demo-only MT5 market-data provider. It does not wire them into the runtime yet.

Authority is unchanged: live DENIED, production NONE.

## Completed
- **Inventory.** 30 of the 142 runtime-closure modules depend on crypto inputs:
  - the Binance provider, funding, Fear & Greed and the order book;
  - MarketLoop, the application wiring, MarketFeed and the candle processor;
  - the risk quote currencies and the venue rules.

  The runtime reads market data only through `MarketDataProviderProtocol` (`get_price`, `get_candles` →
  `MarketCandle`), so forex can arrive behind that same contract.
- **`atlas_finance/forex/instruments.py`.** `ForexInstrument` is built from an MT5 `symbol_info` record and carries:
  - pip size (0.0001 for 5-digit quotes, 0.01 for 3-digit);
  - contract size, units, lots rounded down to the volume step, and pip value.

  Only USD-quoted pairs of two fiat currencies are accepted. USD is the account currency, so the existing notional
  arithmetic stays valid. Metals, crypto CFDs, suffixed symbols and non-USD quotes are refused. Default universe:
  EURUSD, GBPUSD, AUDUSD, NZDUSD.
- **`atlas_finance/forex/sessions.py`.** The market is open from Sunday 17:00 to Friday 17:00 New York time. US
  daylight saving is computed without a time-zone database, so it works the same on Windows. `next_forex_open` gives
  the next open.
- **`atlas_finance/market_data/mt5_provider.py`.** `Mt5MarketDataProvider` implements the market-data protocol:
  - **Demo only.** Contest and real accounts are refused.
  - **No credentials.** It attaches to the terminal's own login.
  - **No order path.** No order, position or login function is used, and a test checks the source.
  - **Closed bars only.** It reads from position 1 and drops any bar that has not closed.
  - **UTC timestamps.** Broker server time is converted to UTC with a configured offset, or one measured from a fresh
    tick. The offset is never guessed while the market is closed.
  - **Volume.** Tick volume is labelled `volume_kind = "TICK"`. No quote volume is invented.
  - **Validation.** Malformed bars and quotes are refused.
- **MT5 API checking.** Names and constants were checked against the official MetaTrader5 package (PyPI 5.0.6231,
  MetaQuotes, MIT; sha256-verified wheel, read as text and never executed). The MQL5 documentation was unreachable
  (proxy 403), so the call semantics are recorded as UNKNOWN in v5.102.
- **Registry v5.102.** It records:
  - the owner decision, Task 017 closed, the Task 018 grant;
  - conflicts C-1..C-4 (CLAUDE.md still says crypto; roadmap discipline; the crypto soak is superseded; the
    replace-then-remove order);
  - the plan for Tasks 019 and 020, unknowns, and a branch-state note.

## Files changed
- governance/current/ATLAS_MILESTONE_REGISTRY_v5.102.json (a successor; v5.101 is untouched)
- atlas_finance/forex/__init__.py, instruments.py and sessions.py (new)
- atlas_finance/market_data/mt5_provider.py (new)
- tests/test_task018_forex_foundation.py (new, 65 tests)
- packaging maps, regenerated with the files staged (the runtime closure is unchanged at 142 modules)
- this checkpoint
- **Unchanged:** every runtime module, the policy manifest and all parameters.

## Architecture decisions
- **Replace, then remove.** Each crypto component is removed only after its forex replacement runs. The end state,
  no crypto, is the owner's.
- **Same contract.** Forex comes in behind the existing market-data protocol, so downstream code keeps its contract.
- **Account currency.** Quantities stay in base-currency units. The first universe is USD-quoted only (notional is in
  the account currency).
- **No leverage.** The runtime keeps paying the full notional (1:1), the most conservative setting. Any leverage is
  an owner decision.
- **Session guard.** The weekly session is a guard; the broker's quotes stay the authority. Holidays are not
  modelled.

## Tests
- **Task 018:** 65 passed. A mutation check planted 16 deliberate bugs in a scratch copy, and the tests caught all 16.
- **Full suite on the final branch** (feature/forex-pivot from 6d6b846, Python 3.13): 11322 passed, 12 skipped,
  0 failed (11257 before + 65 new).
- **`tests/architecture`:** 102 passed.
- **Earlier run, wrong base.** The full suite also ran once on the wrong base (feature/time-stop-and-backtest):
  11374 passed, 12 skipped, 0 failed.

## Current state
- **Branch:** `feature/forex-pivot`, created from `claude/exp001-on-owner-lineage` 6d6b846 (owner choice). Commits
  are local; the push waits for the owner.
- **The time-stop sprint** (`feature/time-stop-and-backtest`, 9e47f4c) is unmerged and unregistered, and the owner
  chose to leave it as is.
- **Process issue, recorded honestly:**
  - this session started without checking the branch, so Task 018 was first built on the time-stop branch and then
    moved;
  - a stray `git stash` briefly stashed the work, and it was restored at once with nothing lost.

## Known issues / Risks
- **MT5 behaviour is UNKNOWN until checked on the owner's terminal:**
  - whether position 0 is the forming bar;
  - whether times are server time;
  - the symbol names on the broker.
- **Not checked by any independent review.** No independent read-only review was run for Task 018; the owner did not
  ask for one. The tests and the mutation check are the evidence.
- **CLAUDE.md still says crypto** (C-1): an owner action.
- **Regulation of leveraged forex for the owner is UNKNOWN.**

## Remaining work
- **Task 019 (wiring):**
  - MarketFeed on MT5 and MT5 instrument rules;
  - USD as the quote currency in risk and capital;
  - a spread-based liquidity gate;
  - a session-aware MarketLoop;
  - a forex cost model in paper execution.
- **Task 020:** remove the crypto components and tests.
- **Later:** non-USD pairs, a leverage decision, a forex soak plan.

## Next exact action
The owner checks the provider on a Windows MT5 demo terminal, with `pip install MetaTrader5` and the terminal logged
in:

```
python -c "from atlas_finance.market_data.mt5_provider import Mt5MarketDataProvider as P; p=P(); p.connect(); print(p.server_utc_offset_hours, p.get_price('EURUSD'), p.get_candles('EURUSD','1h',3))"
```

Then the Task 019 grant.
