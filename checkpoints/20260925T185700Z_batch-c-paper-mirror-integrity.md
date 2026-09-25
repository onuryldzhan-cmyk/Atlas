# ATLAS CHECKPOINT

## Objective

Owner brief 2026-09-25, Part C: fix F-4 from
`checkpoints/20260924T195526Z_execution-financial-state-reconciliation-audit.md`.
The fix has three parts:

- re-project the PaperTrader mirror at startup from
  ExecutionPortfolioFoundation;
- make `save()` atomic;
- make `load()` fail loud without halting.

Classification: CRITICAL, because it touches the `ExecutionManager.start()`
path.

## Completed

- **`ccb2e37`**
  - `ExecutionManager._reproject_paper_book()` runs from `start()` whenever
    `durable_ready`. It projects `portfolio_foundation.snapshot()["positions"]`
    through `PaperTrader.reproject_all`. Diverged symbols are logged at
    WARNING. Any exception is logged and contained: it never halts and never
    sets `recovery_required`. It is skipped when the foundation is not ready.
  - `PaperTrader.save()` writes a `.tmp` file, then flush, fsync and
    `os.replace`. This mirrors `FinancialStateStore.save`.
  - `PaperTrader.load()` sets `load_status` to OK, MISSING, CORRUPT or
    UNREADABLE. UNREADABLE (an I/O failure) is kept distinct from CORRUPT
    (bad JSON or the wrong shape). On failure it:
    - moves the bad file aside to `<file>.<status>.<UTC ts>`;
    - logs at ERROR;
    - starts with an empty book, which the startup re-projection then
      rebuilds.

    `load_status` is exposed in `status()`.
- **`e879517`** (self-review follow-up): `reproject_all` saves only when a
  symbol diverged, so a consistent startup neither creates nor rewrites
  `paper_trades.json`.
- Governance: registry v4.76,
  `paper_mirror_integrity_f4_implementation_result`.

## Files changed

- `core/paper_trader.py`
- `core/execution_manager.py` (one call in `start()` and one new contained
  method)
- `tests/test_paper_book_mirror_integrity.py` (new, 16 tests)
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.76.json`

## Architecture decisions

- The mirror stays passive. It has no new readers, and `/api/trades` is
  unchanged.
- ExecutionPortfolioFoundation is only read, through `snapshot()`.
- Re-projection runs only once the foundation is known ready.

## Tests

- New tests: 16 passed. They cover:
  - startup re-projection of a missing symbol;
  - dropping a symbol the authority shows flat;
  - no rewrite and no warning when the book is consistent;
  - no file created on a consistent fresh start;
  - a failing re-projection not halting;
  - no re-projection when the foundation is not ready;
  - a torn file at startup: CORRUPT, preserved byte-exact, rebuilt, no halt;
  - 4 wrong-shape cases, all CORRUPT;
  - UNREADABLE kept distinct from CORRUPT;
  - interrupted save leaving the previous complete file;
  - round-trip with no leftover `.tmp`;
  - divergence reporting.
- Blast radius, run on `ccb2e37`: every tests file that references
  paper_trader, PaperTrader or paper_mirror, plus
  `test_block5j_execution_authority_recovery.py`. 659 passed.
- Full suite at `e879517`, with ASCII basetemp: **3961 passed / 1 failed**.
  - This is the baseline 3945/1 plus the 16 new tests.
  - The failure is the pre-existing Group B2 test
    `tests/architecture/test_forbidden_layer_imports.py`, about edges from
    `atlas_finance/market_data/contracts.py`. It is untouched.

## Current state

F-4 is implemented.

The CRITICAL final gate is **not fully closed**:

- **INDEPENDENT AUDIT was not performed.** This session did a self-review
  only.
- **Live-instance verification** needs the owner to start a real runtime.

## Known issues

An UNREADABLE book whose quarantine rename also fails is not moved aside. If
the re-projection save then succeeds, that file is overwritten. This affects
the mirror only.

## Risks

Low:

- Re-projection is contained, and the mirror has no consumers.
- The one behavior change: a startup with a divergent book now rewrites
  `paper_trades.json`, and logs a WARNING when it does.

## Remaining work

- Run an independent review of `ccb2e37..e879517`.
- On the next owner-started run, check the startup log and
  `paper_trades.json`.

## Next exact action

The owner runs `/code-review` on `ccb2e37..e879517`, or approves a separate
audit.
