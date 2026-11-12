# ATLAS CHECKPOINT — Shadow S1/S2, sentiment observation, coin filters (2026-10-02)

**Objective:** owner-approved Shadow stage (S1 observe, S2 book fills), sentiment observation, coin filter report.

**Completed (pushed, branch claude/exp001-on-owner-lineage):**
- 3644227 BH false-discovery filter on candidate lessons; 05d2701 confirmed vs suspected overconfidence; e22babb research chart.
- 769b053 tools/sentiment_lessons.py (observe-only). CORRECTION: Fear & Greed sentiment IS live (registry v4.66); the
  earlier "no provider" claim came from a stale agent_fusion comment (comment updated, behaviour unchanged).
- 098caeb S1: digital_twin agent samples live order books; python -m tools.shadow_costs report.
- e78c359 + 8195bf2 S2 (owner approved): ATLAS_FILL_MODEL=BOOK prices PAPER fills at the live book VWAP; no price ->
  REJECTED SHADOW_BOOK_PRICE_UNAVAILABLE, reservation released; mode stays PAPER; needs ATLAS_STATE_DIRECTORY with a
  folder named exactly 'shadow'. Independent audit: 0 BLOCKING/HIGH; 2 MEDIUM + 1 LOW fixed (partial SELL notional,
  hard deadline on the lookup, exact folder name). Default LAST_PRICE unchanged.
- 3fbdec1 tools/universe_filter_report.py (freqtrade-style filters, report only).

**Tests:** full suite 6412 passed, 12 skipped (after 8195bf2).

**Not done / next:** S3 gate criteria (Shadow -> Small Live) need Shadow data first and owner numbers.
UNVERIFIED in this container (network blocked): all live Binance/alternative.me calls; run on the owner machine.
Standing preference: ideas only from high-star GitHub repos.
