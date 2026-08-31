# ADR-0006: Historical Market Data Archive with Recorded Provenance

## Status

Accepted. Research / edge validation.

Originally authored as ADR-0005 on `research/edge-validation` (commit
`c86d5ad`, 2026-08-29). Renumbered to ADR-0006 when that branch was
reconciled with `feat/block3-execution-safety`, which had already used
number 0005 for "Operator Financial-State Bootstrap Entry Point and Runbook"
(commit `22f8bba`, 2026-08-13) under the governance-ratified
BLOCK3-EXECUTION-SAFETY stream. The earlier, ratified number keeps 0005; this
record takes the next free number. Content is otherwise unchanged apart from
the module rename recorded below.

## Context

Atlas had no archive of real historical market data. The three files under
`data/` (`historical/BTCUSDT_1h_15d.csv`, `btc_usdt_1h.json`,
`btcusdt_1h.json`) are BTCUSDT/1h only, mutually overlapping, roughly a
thousand bars in union, and carry no record of where they came from or when
they were captured. `backtest_engine.py` and `portfolio_backtest.py` generate
OHLCV with `random`. Neither source can support an evidence-driven research
claim: the first has unverifiable provenance, the second is fabricated.

Any statistical result the `research/` package adjudicates is only as
trustworthy as the data underneath it. That requires an archive where each
bar's origin and capture time is reconstructable, and where re-running
acquisition cannot silently change history.

## Decisions

- **A separate store** (`data_layer/market_data_archive_sqlite.py`,
  `MarketDataSQLiteStorage`; originally `data_layer/market_data_sqlite.py`,
  renamed during the same reconciliation because
  `feat/block3-execution-safety` had independently created a different
  `data_layer/market_data_sqlite.py` — the Package-1 dataset manifest/identity
  backend — under the ratified Block-4 stream). The market-data archive does
  not share a
  database or a lifecycle with `data_layer/sqlite.py`. That backend owns the
  financial ledger (orders, executions, positions) and fails closed on
  integrity problems; a bulk, rebuildable price archive has different
  durability and size characteristics and must not be able to block the
  ledger from opening, or vice versa. The archive defaults to
  `data/market_archive/market_data.sqlite3`, which the existing `*.sqlite3`
  ignore rule keeps out of version control.

- **Provenance is per batch, not per row.** Every bar belongs to exactly one
  `market_data_batches` row recording `source` (`binance_public_klines`),
  `endpoint` (`/api/v3/klines`), `provider_version`, the requested window,
  `fetched_at` (UTC), and a SHA-256 `checksum`. `provenance_for_bar()`
  resolves any single bar back to that record. The checksum is computed over
  a canonical serialization of the batch's *normalized* bars rather than the
  raw HTTP bytes, which is the deliberate trade-off: it can be recomputed
  from the stored rows at any time (`verify_batch()`) and therefore detects
  post-hoc tampering, but it does not attest to the exact wire response.

- **Idempotency by content-addressed identity.** A batch's `batch_id` is
  derived from its request identity plus its checksum, and bars are keyed by
  `(symbol, timeframe, open_time_ms)`. Re-fetching a covered range inserts
  nothing and leaves the original `fetched_at` intact. A batch that
  contributes no new bar is not left behind as orphan provenance.

- **Divergence is reported, never resolved silently.** If a re-fetch
  disagrees with an archived bar, the archived row is kept and the
  difference is returned as a `BarConflict`. Overwriting would destroy the
  provenance chain; dropping the difference would hide a venue restatement.

- **Gaps are reported, never filled.** `coverage()` returns exact bar counts,
  the archived range, and every missing run as a `CoverageGap`. No
  interpolation, forward-fill, or synthetic bar is produced anywhere in this
  path. Missing history stays visibly missing.

- **Unclosed bars are never archived.** The in-progress candle at the head of
  a live request is excluded, so the archive contains only settled bars.

- **The provider change is additive.** `BinancePublicDataProvider.get_candles`
  gains keyword-only `start_time`/`end_time`; the existing positional
  signature and all current callers are unaffected. Rate limiting keeps the
  provider's existing fail-fast behavior: a 429/418 raises immediately
  without retry, and `HistoricalArchiver` stops that symbol, records
  `stop_reason=RATE_LIMITED`, and preserves everything already fetched. The
  CLI exits non-zero so a rate-limited run cannot be mistaken for a complete
  one.

## Consequences

- No existing module imports the archive; `backtest_engine.py`,
  `portfolio_backtest.py`, the three legacy `data/` files, and every backtest
  result JSON are untouched by this package. Connecting the archive to a
  backtest path is deliberately left to a separate, reviewed change.
- Because acquisition is idempotent and resumable from the archive's
  high-water mark, an interrupted or rate-limited run is recovered by
  re-running the same command. `--start` re-attempts a specific reported gap.
- The archive records what the venue served at capture time. A gap in it is
  evidence about Binance's history (early-2017 outages are real and visible),
  not a defect to be smoothed over before analysis.
