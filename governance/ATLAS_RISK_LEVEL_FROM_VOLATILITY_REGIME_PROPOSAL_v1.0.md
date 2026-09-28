# Proposal — derive decision risk_level from the market-risk volatility regime

| Field | Value |
| --- | --- |
| Status | `PROPOSED` — design only, implementation NOT authorized |
| Tier | CRITICAL (changes which BUY requests the execution RiskEngine can admit) |
| Owner decision recorded | 2026-09-28: direction chosen = "derive risk_level from the volatility regime" |
| Evidence | `checkpoints/20260928T070000Z_buy-risk-bucket-confidence-diagnosis.md` |
| Production / live effect | NONE (`live_authority=DENIED` unchanged) |

## Problem (FACT, from the diagnosis)

- The decision's `risk_level` is produced by `AdvisoryRiskScorer.calculate`
  (`ai/core/intelligence/risk_engine.py:130-215`), called at `ai/core/atlas_brain.py:447-449` with
  only `confidence`. `volatility` and `market_health` are never passed and default to 0.5, so
  `score = 0.75 − 0.5c`.
- `c` is `ConfidenceEngine.value` = `0.5·A + 0.35·R − 0.03`, where `A` is vote-count agreement over
  a 5-agent roster and `R` is reasoning confidence (`confidence_engine.py:147-159, 216-321`).
- Result: **LOW is unreachable**; a split BUY vote (A = 0.40) is HIGH unless R > 0.943. The
  measured volatility regime (`analysis/world_analysis_engine.py:505-533, 672-685`) never reaches
  `risk_level`. Risk and confidence are the same signal counted twice: confidence already has its
  own gate (`core/risk_engine.py:495`), and then selects a stricter bucket for itself.

## Proposed rule

`risk_level` is taken from the market-risk regime, not from confidence:

| Evidence state (`market_data`) | risk_level |
| --- | --- |
| `evidence_status["market_risk"] == "AVAILABLE"` and `market_risk_evidence["regime"] == "LOW"` | `LOW` |
| same, regime `NEUTRAL` | `MEDIUM` |
| same, regime `HIGH` | `HIGH` |
| status not AVAILABLE, evidence missing, or regime not one of the three | `HIGH` (fail-closed) |

**Macro cap (owner decision, 2026-09-28, open question 1 resolved):** the regime-derived level is
then raised to at least `MEDIUM` unless Macro is *available and not voting SELL*:

| Macro state | Effect |
| --- | --- |
| `evidence_status["macro"] == "AVAILABLE"` and vote HOLD or BUY | no cap (LOW stays LOW) |
| Macro vote SELL | LOW → MEDIUM |
| Macro unavailable, malformed, or vote unknown | LOW → MEDIUM |

The last row is required by NB-4: if the cap applied only to an explicit SELL, losing the Macro
evidence would lift the cap and produce a *less* conservative bucket than keeping it. Absence is
therefore treated like SELL. The cap never lowers a level (MEDIUM and HIGH are unaffected).

Only the three values the producer already validates are accepted (the producer rejects a regime
that contradicts its own p20/p80 numbers, `world_analysis_engine.py:644-666`). No new vocabulary.

## What changes

- One assignment site: the value passed as `risk_level` into `DecisionBuilder.create`
  (`atlas_brain.py:447-458`, `decision_builder.py:114-118`).
- `AdvisoryRiskScorer` output is **kept in `decision.metadata["risk"]`** as a diagnostic, so the
  old classification stays auditable; it just stops selecting the bucket.

## What does not change

- `core/risk_engine.py` — policy values (LOW 0.60 / MEDIUM 0.70 / HIGH 0.80), global minimum,
  CRITICAL/UNKNOWN rejection, drawdown, daily-loss, exposure and allocation limits: untouched.
  The execution RiskEngine stays the sole admission authority.
- AgentFusion weights, votes, floor, M-2 absence charge; ConfidenceEngine; the final decision
  confidence. The market-risk *vote* in fusion is unchanged.
- SELL handling (reduce-only path, `core/risk_engine.py:474-481`).

## Expected effect (arithmetic, not a promise)

With today's recorded BUY votes (tech 0.85, momentum 0.70, risk HOLD, macro SELL, sentiment
excluded) the final confidence is 63.58:
- regime LOW, Macro SELL (today) → capped to MEDIUM → 63.58 < 70 → **rejected as today**;
- regime LOW, Macro HOLD/BUY → LOW bucket → passes the confidence gate at 60 (Macro HOLD gives
  65.75, all other limits still apply);
- regime NEUTRAL → MEDIUM → 63.58 < 70 → rejected as today;
- regime HIGH or unavailable → HIGH → rejected as today.

So BUYs open **only** in a measured low-volatility regime. Note that the LOW bucket is also the
**most permissive** sizing bucket (`core/risk_engine.py:147-149`: max allocation 0.40 and exposure
ceiling 0.60, versus HIGH 0.10 / 0.20). The change therefore lowers the confidence bar *and*
raises the permitted position size at the same time.

## Safety analysis

| Invariant | Assessment |
| --- | --- |
| NB-4 (removing evidence must not make Atlas less conservative) | Satisfied by construction: missing/unavailable/malformed regime → HIGH, the strictest executable bucket. Losing volatility evidence can only tighten. Must be pinned by tests. |
| NB-5 (roster denominator) | Not touched: fusion and ConfidenceEngine unchanged. |
| Capability ≠ authority | The volatility provider still has no execution authority; it informs a classification that the canonical RiskEngine enforces. The change removes a self-referential loop (confidence choosing its own bar) rather than adding an authority. |
| Less conservative somewhere? | **Yes, deliberately:** in a LOW regime the confidence bar falls from 80 to 60 and the allowed allocation rises from 0.10 to 0.40. This is the owner-chosen intent and is the reason the tier is CRITICAL. |
| Stale regime | RESOLVED (FACT): the regime is recomputed every cycle from that cycle's own closed candles, with no cache (`core/market_loop.py:2094-2152`); a candle gap or malformed series yields `available=False` (`core/market_risk_regime.py:41-46`) → HIGH under this rule. A stale LOW cannot outlive fresh candles; candle freshness is already enforced upstream. |
| Regime is relative, not absolute | **NEW FINDING (FACT):** LOW means below the 20th percentile of the trailing ~3 hours (200 one-minute candles), not low in absolute terms (`core/market_risk_regime.py:32-39`). Being percentile-based, it occurs in roughly 20% of cycles regardless of how volatile the market is overall; a moderate move after a very calm three hours can read LOW. Under this rule that would open the most permissive bucket. See open question 4. |

## Test plan (required before implementation is accepted)

1. Each regime maps to its bucket; every non-AVAILABLE status, missing evidence, `None`, empty,
   lower-case, unknown string, non-string regime → HIGH.
2. NB-4: for every input, removing the market-risk evidence *or the Macro evidence* never yields
   a lower bucket; Macro SELL, unavailable and malformed all cap LOW to MEDIUM.
3. Confidence and fusion outputs byte-identical before/after for a fixed input grid (proves only
   `risk_level` moved).
4. End-to-end through `RiskEngine.evaluate`: LOW-regime BUY at 63.58 admitted with LOW limits;
   NEUTRAL/HIGH/unavailable BUY at 63.58 rejected `CONFIDENCE_BELOW_POLICY`.
5. SELL path unchanged.
6. Staleness case once the freshness rule is confirmed.
7. Full suite: only the accepted B2 failure.
8. CRITICAL final gate: self-review, regression, independent audit, fix, re-test.

## Open questions for the owner

1. ~~Should a Macro SELL cap the bucket at MEDIUM?~~ **RESOLVED 2026-09-28: yes**, extended to
   Macro absence for NB-4 — see "Macro cap". Consequence: today's BUYs stay rejected under the
   current rising-yield regime; BUYs open only in LOW volatility with Macro HOLD or BUY.
2. ~~Dashboard display.~~ RESOLVED 2026-09-28: show **only the new** regime-derived level; the
   legacy advisory level remains in `decision.metadata["risk"]` for audit only.
3. ~~Staleness bound for the regime.~~ RESOLVED: no separate bound needed (see Safety analysis).
4. ~~Is a relative 3-hour LOW enough?~~ **RESOLVED 2026-09-28: no — "like a real trader", all
   three of the following, phased:**

   **Phase A (this proposal's scope, risk_level rule).** LOW is granted only if all hold; any
   failure or missing input → MEDIUM (never LOW), preserving NB-4:
   - A1. Relative: the existing 3-hour regime is LOW.
   - A2. Absolute: current realized volatility is below a fixed ceiling. The ceiling value is
     **UNKNOWN — requires measurement** from recorded history (`C:\AtlasState`) and owner approval;
     it must not be guessed.
   - A3. **DEFERRED 2026-09-28 (owner):** not part of Phase A; Phase A = A1 + A2 + Macro cap.
     Original text retained below for the later phase.
     Multi-timeframe: a longer window (candidate: 24 hours) is not HIGH.
     **Possible CONFLICT:** MarketLoop fetches 200 one-minute candles (~3h); a 24h view needs more
     or coarser candles from the same exchange. Registry v4.79 recorded a "no new data source"
     decision for this provider — whether a different interval from the same source is allowed
     is an owner decision (Decision Required).
   - Macro cap (above) still applies after A1–A3.

   **Phase B (separate CRITICAL proposal, not in this scope).** Volatility-scaled position sizing:
   allocation shrinks as realized volatility rises (constant-risk sizing) instead of the fixed
   0.40/0.25/0.10 bucket percentages. This touches `core/position_sizing.py` and the RiskEngine
   bucket policy and needs its own proposal, grant and final gate.

## Implementation map (read-only survey, 2026-09-28 — nothing implemented)

Prepared so that, once authorized, the change is small and its blast radius is known in advance.

**Code touch points (Phase A):**

| # | File:line | Change |
| --- | --- | --- |
| 1 | `ai/core/intelligence/risk_engine.py` | Add one pure function next to `AdvisoryRiskScorer`, e.g. `regime_risk_result(market_data, volatility_ceiling) -> RiskResult`: A1 regime → level, A2 ceiling guard, Macro cap, every failure path → HIGH. Stdlib only; returns the existing `RiskResult`/`RiskCategory` types so `Decision`'s type contract (NBF-5/NBF-7) holds unchanged. |
| 2 | `ai/core/atlas_brain.py:447-458` | Keep the existing `self.risk.calculate(...)` call (advisory). Pass the new regime `RiskResult` to `builder.create` as `risk`. `market_data` is already in scope there. |
| 3 | `ai/core/atlas_brain.py:487-499` (metadata update) | Add the advisory result as `metadata["advisory_risk"]` so the legacy classification stays auditable. `metadata["risk"]` then holds the regime result (written by `decision_builder.py:161-163`). |
| 4 | Ceiling constant | A named constant pinned in code and in the grant record; value **UNKNOWN until measured** (see open question 4). No config file, no environment variable — changing it must require a governed change. |

**Not touched:** `core/risk_engine.py` (policy, gate), `ai/core/intelligence/decision_builder.py`,
`ai/core/intelligence/agent_fusion.py`, `ai/core/intelligence/confidence/confidence_engine.py`,
`analysis/world_analysis_engine.py`, `core/market_loop.py`, `core/position_sizing.py`.

**Dashboard (owner decision: new level only):** no change needed. `web_app.py:78-128` publishes
the decision's `risk_level`, and `templates/dashboard.html:569` renders it; the new level flows
through automatically. The advisory level stays out of the panel by design.

**Existing tests — expected impact:**
- Call `AdvisoryRiskScorer` directly and assert its behaviour; unaffected because the scorer is
  kept unchanged: `test_nb4_nb5_confidence_availability_correction.py`,
  `test_block3_package4_confidence_semantics.py`, `test_nbf5_decision_risk_level_type_contract.py`,
  `test_nb2_fusion_audit_metadata.py`, `test_block2c_deferred_backlog_guards.py`,
  `test_phase2_market_data_evidence_semantics.py` (item 19 asserts the scorer never reads market
  data — still true, the new function is separate), `test_decision_confidence_normalization.py`.
- Type-contract tests `test_nbf5_*`, `test_nbf6_*`, `test_nbf7_*`: must keep passing unmodified;
  they are the guard that the new producer emits a canonical type.
- End-to-end brain tests (e.g. `test_atlas_brain_phase5_shadow.py`, `test_merged_process_composition.py`):
  UNKNOWN — requires verification whether any asserts a specific `risk_level` for a given input.
  If one does, it encodes the old behaviour and is reported to the owner, never silently edited.

**New tests:** the Test plan above, plus a golden check that `decision.confidence`, `action` and
`metadata["fusion"]` are identical before and after for a fixed input grid.

## Authorization required

Implementation needs an explicit owner grant recorded in a new milestone-registry successor record.
This document authorizes nothing.
