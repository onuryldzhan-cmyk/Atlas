# ATLAS CHECKPOINT — Task 021: Forex spread cost model

## Objective
This task implements the spread cost model the owner chose on 2026-10-25, inside the existing governance (grant
GRANT-TASK-021-FOREX-SPREAD-COST, registry v5.104). It was chosen over removing crypto first: crypto stays as a
fallback until MT5 is verified on the owner's terminal. Task 020 stays reserved for the crypto removal.

Authority is unchanged: live DENIED, production NONE.

## Completed
- **`Mt5QuoteFillProvider`** (in `atlas_finance/market_data/mt5_provider.py`). In FOREX with
  `ATLAS_FILL_MODEL=BOOK`:
  - a PAPER BUY fills at the MT5 ask and a SELL at the bid, so the real spread is paid on every fill;
  - a quote older than 60 s, one more than 60 s ahead of the clock, or one that cannot be read is no price, and the
    order is rejected (the existing BOOK contract; never the last price);
  - the price is rounded to the tick against Atlas by the existing execution-manager code.
- **`core/application.py`.** BOOK in FOREX is wired to the MT5 quotes, sharing the feed's own demo-only
  connection. BOOK in CRYPTO keeps the Binance order book.
- **`core/atlas_config.py`** (fixes a gap left in Task 019). FOREX needs its own `ATLAS_STATE_DIRECTORY`, with a
  folder named `forex` in its path. With BOOK, it also needs `shadow` (e.g. `C:\AtlasState\forex\shadow`). Forex
  never shares the crypto positions, ledgers or journals.

## Files changed
- **Commit 1:** governance/current/ATLAS_MILESTONE_REGISTRY_v5.104.json (a successor).
- **Commit 2:**
  - the three modules above;
  - `tests/test_task021_forex_spread_fill.py` (new, 17 tests);
  - `tests/test_task019_forex_wiring.py` (Task 019's own tests, updated for the new rules; disclosed in v5.104);
  - packaging maps (the closure is unchanged at 146 modules);
  - this checkpoint.

## Architecture decisions
- **Within the manifest.** The policy manifest v2 allows `paper_fill_model` LAST_PRICE or BOOK, so the spread model
  uses BOOK and needs no governance edit.
- **Commission unchanged.** The 0.1 % per-side fee is pinned by the manifest and stays as the commission. Forex
  costs are therefore spread + 0.1 %, which is still conservative. A lower, configurable commission needs a
  manifest v3, which is an owner decision and was not made here.
- **Top of book only.** MT5 exposes no depth here, so a fill is priced at the top of the book. The assumption that
  these sizes are far below top-of-book liquidity is not a measurement.

## Tests
- **Task 021:** 17 passed. Task 019: 28 passed, with the updated rules.
- **Mutation check:** 10 planted bugs, all 10 caught.
- **`tests/architecture`:** 102 passed.
- **Full suite (Python 3.13):** 11367 passed, 12 skipped, 0 failed (11350 before + 17 new).

## Current state
- **Branch:** `feature/forex-pivot`: Task 018 (4713c07, ad092ad), Task 019 (7c11ecc, ba71ea1), then Task 021.
  Everything is local; the push waits for the owner.

## Known issues / Risks
- **Unverified on real MT5.** Nothing has run against a real MT5 terminal; the unknowns in v5.102 still apply.
- **Costs are higher than the real commission** (spread + 0.1 %), until a manifest v3 is decided.
- **Still open from earlier tasks:** the HIGH bucket below the minimum lot, long-only, and weekend gaps
  (known_issues_v5_103).

## Remaining work
- **Owner:** the push, the MT5 check on Windows, and decisions on manifest v3 (commission), a weekend policy,
  leverage and shorts.
- **Task 020:** remove crypto after the MT5 verification.

## Next exact action
Owner sign-off on the push. Then, on Windows, run Atlas with:

```
set ATLAS_MARKET=FOREX
set ATLAS_FILL_MODEL=BOOK
set ATLAS_STATE_DIRECTORY=C:\AtlasState\forex\shadow
```

Create that directory first; Atlas deliberately does not create it.
