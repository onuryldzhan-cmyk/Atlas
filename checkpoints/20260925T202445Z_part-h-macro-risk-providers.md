# ATLAS CHECKPOINT

## Objective

Part H of the 2026-09-25 batch: give the AgentFusion `macro` and `risk`
(`market_risk`) agents real providers. Wire them exactly like sentiment.
Leave AgentFusion, NB-4/NB-5, sentiment, RiskEngine and execution untouched.
The task is CRITICAL tier.

**Status: COMPLETE. The CRITICAL final gate is closed in tests. Live-instance
verification has not been performed; only the owner can start a runtime.**

## Completed

- **Decisions.** The owner answered two questions in session:
  - Neutral zones vote a participating HOLD.
  - The proposed macro rule is accepted.

  Both answers are recorded in registry v4.79, `GRANT-BACKLOG001-MACRO-RISK-IMPLEMENTATION`, commit `6b565bf`.
- **CONFLICT PART-H-BRIEF-STATUS-CODE.** The brief said a failure reports
  UNAVAILABLE_NO_PROVIDER. Sentiment in fact reports
  UNAVAILABLE_PROVIDER_ERROR on failure, so I followed the repository.
- **Implementation** is in commit `5f974ca`:
  - `atlas_finance/market_data/treasury_yield_provider.py` (L2).
  - `core/market_risk_regime.py` (pure, L3).
  - Wiring in `core/market_loop.py`, `core/application.py`,
    `analysis/world_analysis_engine.py` and `conftest.py` (network guard).
  - The packaging inventory was regenerated: 106 → 108 modules.
- **Self-review.** 4 of 4 valid in-memory mutations were caught.
- **Independent audit.** It found 1 MEDIUM, 4 LOW and 3 INFORMATIONAL
  findings, and no BLOCKING or HIGH.
  - Fixed: F-1 (MEDIUM, a spliced or holed CSV could misstate the
    lookback), F-2, F-5 and F-7.
  - Recorded: F-6.
  - Deferred: F-3 and F-4, which are inherited from the Fear & Greed
    provider.
- **Result record:** registry v4.80. A BACKLOG-001 additive section was also
  added.

## Vote rules (for owner review)

- **Macro.** The rule looks at how far the US 10Y Treasury yield moved over
  the last 20 trading days:
  - ≥ +25bp → SELL (0.25).
  - ≤ −25bp → BUY (0.75), or HOLD if the curve is inverted (10Y − 2Y < 0).
  - Anything in between → HOLD (0.50).
  - Live on 2026-09-25 the move was +52bp, so the vote is SELL.
- **Market risk.** Realized volatility is the RMS of 30 one-minute log
  returns. The current window is compared with p20 and p80 of all earlier
  windows in the 200 fetched candles, and needs at least 100 of them.
  - HIGH (> p80) → SELL.
  - NEUTRAL or LOW → HOLD. It never votes BUY.
  - The regime is relative to about the last 3 hours.
  - On noise the base rate is about 22% HIGH.

## Files changed

- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.79.json` (new)
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.80.json` (new)
- `atlas_finance/market_data/treasury_yield_provider.py` (new)
- `core/market_risk_regime.py` (new)
- `core/market_loop.py`
- `core/application.py`
- `analysis/world_analysis_engine.py`
- `conftest.py`
- `packaging/atlas_runtime_closure.json`
- `packaging/atlas_architecture_map.json`
- `tests/test_treasury_yield_provider.py` (new)
- `tests/test_market_risk_regime.py` (new)
- `tests/test_backlog001_macro_risk_wiring_and_fusion.py` (new)
- `governance/findings/BACKLOG-001_MARKET_DATA_PROVIDER_SCOPING.md`
- this checkpoint

## Architecture decisions

- **Placement.** Treasury is an L2 provider, like sentiment. The risk regime
  is a pure L3 calculator next to `technical_analyzer.py`, since it has no
  I/O and no new data source. L4 receives plain values only, and its import
  set is unchanged.
- **Provider state.** The risk provider is stateless: it reads each cycle's
  candles. There is no persistence and no restart semantics.

## Tests

`python -m pytest tests` was run on the final code with an ASCII basetemp:

- **Result: 4488 passed, 1 failed.** The one failure is the accepted Group B2
  `tests/architecture/test_forbidden_layer_imports.py`. Its offending edges
  are unchanged.
- Baseline was 3999/1. There are 489 new tests.

NB-4 and NB-5 are confirmed with 2, 3, 4 and 5 agents, and across 240
real-pipeline roster combinations.

## Current state

- Branch `research/edge-validation`.
- Commits: `6b565bf` (v4.79), `5f974ca` (implementation), and the v4.80 plus
  checkpoint commit that follows.
- No Atlas process was started. Nothing was pushed.

## Known issues / Risks

- **PAPER behavior change (disclosed and accepted).** With sentiment neutral,
  a neutral macro HOLD and a neutral risk HOLD make technical+momentum
  execution-eligible. That happens in 9 of 12 measured states, at confidence
  0.6154–0.6575.
- **Shared data source.** market_risk comes from the same candles as
  technical and momentum.
- **F-3 and F-4.** A synchronous fetch with only a per-socket timeout, and
  redirects are not restricted. Both are shared with the Fear & Greed
  provider.
- **Live verification not performed.**

## Remaining work

- Owner starts a runtime and confirms that macro and market_risk show
  AVAILABLE in decision logs.
- A future package covers F-3 and F-4 for both network providers.
- Part A (F-006 CI) remains with the owner: a private repo,
  `git remote add origin`, and auth.

## Next exact action

Owner: restart the supervised paper run on `5f974ca` or later. Check that
`[AGENT] macro:` and `[AGENT] risk:` lines are no longer `EXCLUDED`.
