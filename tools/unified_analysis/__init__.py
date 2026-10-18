"""Unified analysis (Task 017): one crypto research workflow that combines specialist analysis, adversarial review,
independent verification, a risk gate and outcome-based experience.

Advisory only. Nothing here can place an order, size a position, change a gate or a threshold, or reach the
execution path: the output is a classified, evidence-backed report and an append-only prediction record. The
package lives outside the trading runtime closure (ADR-0011 D1): it imports ``core`` read-only, and a model is
reached only through ``tools.ai_gateway`` and only when the caller passes ``ask``.

Workflow (``pipeline.run_analysis``):

  1. market_intelligence  validate closed bars per timeframe (core.market_cycle causal pipeline), provenance,
                          freshness; an unusable primary timeframe ends the run as INSUFFICIENT_EVIDENCE before
                          any specialist or model call
  2. specialists          technical, regime, liquidity/structure, derivatives, sentiment, macro (deterministic) and an
                          optional model narrative; news and on-chain are declared NO_PROVIDER capabilities
  3. verification (in)    every numeric claim is recomputed from the bars; a model finding with an unverifiable or
                          wrong claim is dropped, a wrong deterministic claim fails the run
  4. scenarios            bull / bear / neutral, scored by independent evidence groups, each with invalidation
  5. review               adversarial review: deterministic prosecutor plus an optional model court (prosecutor and
                          lens jurors, Court Skill concepts); a vote count is recorded, never decisive
  6. verification (out)   freshness, look-ahead, consistency, contradiction, required invalidation
  7. decision             SignalFusion over the expected roster (NB-4/NB-5), calibration cap, review penalties,
                          risk gate; a risk rejection has no override path
  8. experience           the prediction is recorded before any outcome exists; settlement uses only bars after the
                          cutoff and appends a separate outcome record

Upstream concepts adopted (no upstream code is copied or imported; see docs/architecture/UNIFIED_ANALYSIS.md):
TauricResearch/TradingAgents (Apache-2.0) and alexyc9381/court-skill (MIT).
"""
