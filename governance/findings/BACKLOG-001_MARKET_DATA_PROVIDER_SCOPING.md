# BACKLOG-001 — Missing macro / sentiment / risk market-data provider

## Greed-side confidence-threshold finding — 2026-09-23, registry v4.68

**This section is additive.** Everything below it, including the
"Sentiment provider IMPLEMENTED" section, is preserved unchanged.

**Authority.** `governance/current/ATLAS_MILESTONE_REGISTRY_v4.68.json`,
`GRANT-GREED-THRESHOLD-FINDING`.

**Finding.** Under current `AgentFusion` weights, the greed-side rule
(`GREED+BULLISH` → SELL, the overextension read; `GREED+BEARISH`/ambiguous →
HOLD) is implemented and tested but never reaches
`ExecutionManager.MIN_CONFIDENCE` (60) in any measured state. Only the FEAR
band currently produces actionable (execution-eligible) decisions. This is a
real, disclosed, accepted-for-now behavior — not a bug — that was previously
only visible as summary observations in registry v4.67; this record states
it plainly so nobody later assumes the greed-side protection is
operationally active when it isn't.

**Evidence (already measured in commit `75c4fce`'s own test suite; nothing
re-derived here).** `tests/test_backlog001_sentiment_wiring_and_fusion.py`:

- `GRID` (lines 463–466): 7 Fear&Greed index values (0, 24, 25, 50, 74, 75,
  100) × 3 trends (BULLISH, BEARISH, NEUTRAL) × 6 RSI classes (20, 32, 38,
  50, 65, 80) = **126 states**.
- `test_sentiment_never_makes_a_trade_it_voted_against_execution_eligible`
  (lines 484–498), parametrized over the full 126-state `GRID`, asserts that
  whenever the fused result is execution-eligible (`action != "HOLD"` and
  `confidence * 100 >= ExecutionManager.MIN_CONFIDENCE`), sentiment's own
  vote agrees with that action **and** `sentiment_evidence["band"] ==
  "FEAR"`. Across all 126 states, no GREED-band or NEUTRAL-band state is
  ever execution-eligible.
- `test_withholding_sentiment_never_raises_confidence_nb4` (lines 469–481),
  parametrized over the same 126-state `GRID`, confirms the companion NB-4
  guard: removing sentiment evidence never raises fused confidence.
- `REAL_PIPELINE_RSI_50` (lines 437–447) / `test_real_pipeline_fusion`: at
  RSI 50, `GREED+BULLISH` fuses to BUY 0.5614 (sentiment dissents SELL) and
  `GREED+BEARISH` fuses to HOLD 0.3623 — both below the 0.60 confidence
  needed for execution eligibility. By contrast `FEAR+BULLISH` fuses to BUY
  0.6491, which clears it.

**Future consideration (PROPOSE-tier, not decided here).** Whether
`AgentFusion`'s weighting should be revisited so the greed-side protection
can become operationally meaningful is named as an open option for a future
owner decision. No recommendation is made, and `GRANT-GREED-THRESHOLD-
FINDING` explicitly does not authorize any weighting or threshold change,
any change to the fear/greed rule logic itself, or any change to
`ExecutionManager.MIN_CONFIDENCE`.

## Sentiment provider IMPLEMENTED — 2026-09-23, registry v4.66 / v4.67

**This section is additive.** Everything below it, including the v4.65
live-investigation section and `Status` through `Reaffirmation — 2026-09-23`,
is preserved unchanged.

**Authority.** `governance/current/ATLAS_MILESTONE_REGISTRY_v4.66.json`,
`GRANT-SENTIMENT-P3-IMPLEMENTATION` (commit `e432c35`). Result recorded in
`governance/current/ATLAS_MILESTONE_REGISTRY_v4.67.json`
(`sentiment_provider_p3_implementation_result`).

**Status of this item.** The **sentiment** slot is **IMPLEMENTED** at commit
`75c4fce`. The **macro** and **market_risk** slots are unchanged: still
`UNAVAILABLE_NO_PROVIDER`, still DEFER.

### What was built

| Layer | File | Role |
|---|---|---|
| L2 | `atlas_finance/market_data/fear_greed_provider.py` | stdlib-only fetch of `https://api.alternative.me/fng/` (no auth). Strict validation, 1h cache, 5 min retry after failure, 26h freshness ceiling on the value's own timestamp. Fail-closed: never a value on any error. |
| L3 | `core/market_loop.py` | Optional injected provider. Converts a reading into plain values `{provider_status, value, band, reason}`. |
| L3 | `core/application.py` | Composition root constructs `FearGreedProvider` and injects it (owner's in-session scope answer). |
| L4 | `analysis/world_analysis_engine.py` | Applies the confirmed rule to plain values. Imports nothing from L2. |
| test | `conftest.py` | Autouse guard: the provider's default network transport fails closed under pytest. |

### Confirmed rule (both sides owner-confirmed in v4.66)

| Index | Trend (reused from `TechnicalAnalyzer`) | Sentiment |
|---|---|---|
| < 25 | BULLISH | BUY (0.75) |
| < 25 | BEARISH / ambiguous | SELL (0.25) |
| ≥ 75 | BULLISH | SELL (0.25) |
| ≥ 75 | BEARISH / ambiguous | HOLD (0.50) |
| 25–74 | any | `UNAVAILABLE_NO_PROVIDER`, not a participant |
| provider error / stale | any | `UNAVAILABLE_PROVIDER_ERROR`, no value |

"Ambiguous" means anything other than an exact `BULLISH`/`BEARISH` string, or
any trend when technical evidence is not `AVAILABLE`.

### Measured AgentFusion confidence (real implementation)

- **v4.65 baseline reproduced exactly** when fed the fixture's inputs:
  fear+BULLISH BUY 0.4702, fear+BEARISH SELL 0.4702, fear+ambiguous HOLD 0.4444.
- **Caveat:** the fixture's momentum 0.55 cannot come out of the real
  `calculate_momentum()`, which only produces values on a 0.1 grid. Fully
  real pipeline at RSI 50:

| Band | Trend | Participants | Fused |
|---|---|---|---|
| fear | BULLISH | 3 | BUY 0.6491 |
| fear | BEARISH | 3 | SELL 0.3007 |
| fear | NEUTRAL | 3 | BUY 0.3537 (sentiment dissents) |
| greed | BULLISH | 3 | BUY 0.5614 (sentiment dissents) |
| greed | BEARISH | 3 | HOLD 0.3623 |
| greed | NEUTRAL | 3 | BUY 0.3662 |
| neutral | any | 2 | HOLD 0.0 `INSUFFICIENT_EVIDENCE` |

Tested over a 126-state grid:
- Withholding sentiment never raises confidence (NB-4).
- Every fused BUY/SELL at or above execution's `MIN_CONFIDENCE` (60) has
  sentiment voting the same way, in the fear band.
- A sentiment dissent can clear the 3-agent floor but stays below 60.

### Architecture

The pre-wiring read-only simulation, and the post-regeneration
`build_architecture_inventory.py check`, both show 106 modules with zero new
forbidden edges. The only violations are the accepted permanent Group B2 pair.

### Tests

- 435 new tests pass.
- Canonical `scripts/validate_atlas.ps1`: 3660 passed, 1 failed (the accepted permanent Group B2 `test_forbidden_layer_imports`); baseline 3225/1, +435 = exactly the new tests; nothing else newly fails.

### Open items recorded, not acted on

- The neutral band reuses `UNAVAILABLE_NO_PROVIDER`, as the owner specified;
  `sentiment_evidence.reason` disambiguates it. A dedicated status would need
  its own grant.
- Pre-existing: `ReasoningAdapter` reads `market_data.get("fear_greed", 50)`,
  so the advisory reasoning path already scores a fabricated neutral 50. That
  contradicts v4.64's "orphaned" note. The new audit key is named
  `sentiment_evidence` so this change does not activate that path.
- No live instance was run. Real-network behaviour of the running process is
  **UNKNOWN** until the owner starts one.

## Live sentiment-provider investigation — 2026-09-23, registry v4.65

**This section is additive.** Everything below it, including `Status`
through the `Reaffirmation — 2026-09-23` section, is preserved unchanged.
Nothing has been deleted or rewritten.

**Authority.** `governance/current/ATLAS_MILESTONE_REGISTRY_v4.65.json`,
`GRANT-SENTIMENT-LIVE-INVESTIGATION`.

**Relationship to the fear-side/greed-side rule already formalized in
registry v4.64.** That record (`d7_standing_backlog_and_sentiment_rule_formalization_record`,
commit `f7a613c`) formalized the owner's fear-side sentiment rule as
CONFIRMED and a greed-side candidate as PROPOSE, citing only static
in-repository code (`core/technical_analyzer.py`,
`ai/core/intelligence/agent_fusion.py`) and a publicly-documented Fear &
Greed scale convention. It performed no live web/API call, no
architecture-placement simulation, and no AgentFusion confidence
measurement, by its own explicit scope. Nothing in v4.64's rule text is
changed by this section; this section supplies the live-investigation
evidence layer that record's own grant excluded, per the owner's later
six-step task instruction requiring the investigation actually be *run*
rather than assumed. All figures below were independently fetched or
computed in this session — see registry v4.65 for the full record.

### Discover — candidate re-check

**alternative.me Fear & Greed Index** (`https://api.alternative.me/fng/`)
remains the sole live-verified sentiment candidate.

- **Live fetch, this session:** `GET https://api.alternative.me/fng/?limit=1`
  returned `{"value": "71", "value_classification": "Greed", "timestamp":
  "1790121600"}`. The timestamp resolves to `2026-09-23T00:00:00Z`
  (verified via `datetime.fromtimestamp(1790121600, UTC)` in-session) —
  today's daily reading, not a stale or recalled figure.
- **Significance of today's real value:** 71 falls in the standard
  50–74 "Greed" band — neither Extreme Fear (<25, the CONFIRMED rule's
  trigger band) nor Extreme Greed (≥75, the PROPOSE candidate's trigger
  band per v4.64). Today's real reading illustrates that the two
  formalized rules do not yet cover the full 0–100 range; that gap is
  expected and unchanged by this section.
- **License, re-verified live** (`https://alternative.me/crypto/fear-and-greed-index/`,
  fetched with and without the `#api` anchor): free, no authentication,
  will remain free per the page's own statement, commercial use allowed,
  attribution requested ("You must properly acknowledge the source of the
  data and prominently reference it accordingly") but not gated behind any
  registration/agreement mechanism. Restriction: may not use the data to
  impersonate alternative.me or create a confusable service.
- **Treasury Fiscal Data API** — re-checked live: free, no-auth (optional
  key only for higher rate limits), confirmed still viable on
  License/Security grounds, but it is a macro/fiscal data source (federal
  debt, interest, revenue series), not a sentiment signal. It does not
  serve the sentiment agent this rule targets and is not adopted here —
  not a rejection, just out of scope for BACKLOG-001's sentiment slice. It
  remains a live no-auth candidate for a future, separately-scoped macro-
  agent investigation, which this section does not open.
- **Deribit** — re-checked live against its own API Usage Policy
  (`docs.deribit.com/articles/api-usage-policy`): public market data needs
  no auth, but the policy explicitly prohibits aggregating, reselling,
  publishing, forwarding, or otherwise *processing* market/derived data
  without prior written approval, except for personal use. Automated
  ingestion into `AgentFusion`'s evidence pipeline is exactly "processing"
  in that sense. Deribit remains **License-blocked**, re-confirmed live in
  this session rather than carried forward from an unverified prior claim.

### Architecture placement — read-only simulation

Using the real `classify_module()` logic and the real `forbidden_edges`/
`layers` tables loaded live from `packaging/atlas_architecture_map.json`
in-session (identical to `tools/build_architecture_inventory.py`'s own
implementation, no repository file created or modified):

| Candidate path | Layer | Matched pattern |
| --- | --- | --- |
| `atlas_finance/market_data/sentiment_fear_greed_provider.py` | **L2** | `atlas_finance/*` |
| `analysis/providers/sentiment_fear_greed_provider.py` | L4 | `analysis/*` |
| `external_data/sentiment_fear_greed_provider.py` | *(unassigned)* | — |

`L4 -> L2` is a forbidden edge (confirmed live from
`packaging/atlas_architecture_map.json`'s `forbidden_edges`); L3's
`allowed_dependencies` includes L2 and L4. **Conclusion:** a new
sentiment-provider module belongs under `atlas_finance/*` (e.g.
`atlas_finance/market_data/`, the same bucket as the existing
`binance_public_provider.py`), auto-classified L2 with zero
`atlas_architecture_map.json` changes required, and should be wired from
L3 (`core/market_loop.py`, which already assembles `market_data` before it
reaches `analysis/world_analysis_engine.py`) — never imported directly by
`analysis/world_analysis_engine.py` or `ai/core/intelligence/agent_fusion.py`
(both L4), which would create the forbidden `L4 -> L2` edge above. Placing
it directly under `analysis/` forces an L4 label onto what is
definitionally an L2 "external service integration" per the architecture
map's own layer description — not an AST-detected violation by itself, but
the same kind of stale-label risk this repository's governance history
already corrected once (`core/__init__.py`, registry v4.39
`GRANT-ANCESTOR-INIT-RECLASSIFICATION`).

`python tools/build_architecture_inventory.py check`, re-run live in this
session: `OK: runtime closure matches (105 modules)`, `OK: architecture map
assigns every live module a layer (105 modules)`, then `FAIL: forbidden
dependency edges detected:` listing exactly the same 2 Group B2 edges
(B2.1, B2.2) and nothing else — the 105-module closure figure and the
permanently-accepted Group B2 disposition (registry v4.63/`de2de76`) are
still exactly correct today, unchanged.

This placement finding is derived fresh in this session from the real
detector logic and the real current architecture map. It does not adopt or
assume any "P1/P2/P3" label from an earlier, unverified chat conversation —
per the owner's explicit instruction, that prior framing is not treated as
fact.

### AgentFusion fixture — real measured confidence

Executed live in-session via `ai.core.intelligence.agent_fusion.AgentFusion().fuse()`
(standalone scratch script, repository root on `PYTHONPATH`, no test file
added, no Atlas process constructed), following the `signals()`/`fuse()`
helper pattern already established in
`tests/test_block3_package4_confidence_semantics.py`.
`AgentFusion.VERSION='10.0'`, `MIN_PARTICIPATING_AGENTS=3`,
`MIN_WEIGHT_COVERAGE=0.5`, `WEIGHTS={'technical': 0.4, 'momentum': 0.2,
'risk': 0.2, 'macro': 0.1, 'sentiment': 0.1}` — all read live from the
class this session.

| State | Inputs (technical, momentum, sentiment) | Actions | Result |
| --- | --- | --- | --- |
| 0 — today's real ceiling | 0.70, 0.55, *(none)* | BUY, HOLD | **HOLD, confidence 0.0, `INSUFFICIENT_EVIDENCE`** (only 2 of 3 required agents) |
| 1 — FEAR + BULLISH trend → sentiment BUY (confirmed rule) | 0.70, 0.55, 0.75 | BUY, HOLD, BUY | **BUY, confidence 0.4702** |
| 2 — FEAR + BEARISH trend → sentiment SELL (confirmed rule, downward branch) | 0.30, 0.55, 0.25 | SELL, HOLD, SELL | **SELL, confidence 0.4702** |
| 3 — FEAR + NEUTRAL/ambiguous trend → sentiment SELL (confirmed rule, ambiguous branch) | 0.50, 0.55, 0.25 | HOLD, HOLD, SELL | **HOLD, confidence 0.4444** |
| 4 — comparison only, NOT the confirmed rule: sentiment abstains (HOLD) instead | 0.50, 0.55, 0.50 | HOLD, HOLD, HOLD | **HOLD, confidence 0.5385** |

**NB-4-relevant observation (real, measured, not predicted):** State 3 vs.
State 4 shows that forcing sentiment to cast a directional SELL vote under
an ambiguous/NEUTRAL trend reading — the owner's actual confirmed rule —
does not flip the final action away from HOLD in this fixture, and
produces a *lower* measured confidence in that HOLD (0.4444) than if
sentiment had abstained instead (0.5385). This is confidence dilution from
a dissenting vote, not confidence inflation from removed evidence, so it
does not itself risk an NB-4 violation — it is recorded because it is real,
freshly-measured evidence directly bearing on registry v4.64's
`nb4_nb5_risk_flag` discussion, and because it shows the owner's ambiguous-
branch SELL choice is not confidence-inflating in this fixture's
construction.

### What this section does not do

No code was implemented or modified to produce this section. It does not
authorize a sentiment-provider implementation (that remains separately
gated per registry v4.62's
`backlog001_single_provider_investigation_and_conditional_implementation_authorization`),
does not decide the greed-side rule (registry v4.64's PROPOSE status is
unchanged), and does not alter Group B2's permanent closure or D7's
standing-backlog status.

## Status

**SCOPING ONLY. Decision: DEFER.** No implementation is authorized by this
record. It exists to describe the gap and its consequences so the owner can
decide timing later, not to begin work on it.

Authorized by `governance/current/ATLAS_MILESTONE_REGISTRY_v4.42.json`
(`hold_only_disclosure_and_provider_scoping_authorization`), grant
`GRANT-PROVIDER-SCOPING-RECORD`. That grant establishes `BACKLOG-NNN` as a
new code under the existing `governance/findings/` naming convention
(`<CODE>-NNN_<DESCRIPTIVE_NAME>.md`, matching `ARCH-EDGE-001`,
`CI-EVIDENCE-001`, `GOV-REVIEW-001`, `STAGE1-PAPER-001`), since no dedicated
"new-idea evaluation" or backlog directory/convention existed anywhere in
`governance/` or `docs/` before this record. This document follows
CLAUDE.md's own new-idea evaluation format verbatim: What / Why / Where /
Dependencies / Risk / Cost / Alternative / Decision.

## What

Implement at least one real macro, sentiment, or risk market-data provider
and wire it into `WorldAnalysisEngine` so that its corresponding
`evidence_status` field (`macro`, `sentiment`, or `market_risk`) can report
`AVAILABLE` with a genuine, non-fabricated score, instead of being
permanently hardcoded to `UNAVAILABLE_NO_PROVIDER`
(`analysis/world_analysis_engine.py:34-69`).

Any one of the three suffices to raise `AgentFusion`'s
`participating_count` from 2 (technical+momentum, the only combination
reachable today) to 3, clearing `MIN_PARTICIPATING_AGENTS`
(`ai/core/intelligence/agent_fusion.py:166`) for the first time. This scoping
record does not choose which of the three to build first; that choice, and
whether to build one, two, or all three, is left to the owner.

**Candidates found in the active repository (searched before writing this
record, not assumed absent):**

- **No wired, active provider of any kind exists today.** This is not a
  partially-complete integration waiting on a config flag; there is no code
  path anywhere in the currently active (non-archived) tree that can set
  `macro`, `sentiment`, or `market_risk` to `AVAILABLE`.
- `ai/core/atlas_reasoning_engine.py:172-314` contains `_evaluate_macro()`
  and `_evaluate_sentiment()` scoring methods, gated on optional
  `macro_data`/`sentiment_data` parameters. These are the closest thing to a
  partially-built piece: scoring *logic* exists, but nothing in the live
  call path supplies it real data. `ai/core/atlas_brain.py:245` and `:355`
  call `self.reasoning` (a `ReasoningAdapter`) with only `(symbol,
  market_data)`, and `market_data` (built by `WorldAnalysisEngine`) never
  carries a `macro_data`/`sentiment_data` payload. This is a candidate
  integration point for a future provider's output, not evidence that
  provider work is already underway.
- `ai/core/intelligence/risk_engine.py`'s `RiskEngine.calculate()` (called
  at `ai/core/atlas_brain.py:447`) is unrelated: it is a post-decision risk
  *classifier* that derives `decision.risk_level` from `confidence` plus
  hardcoded-default `volatility`/`market_health` placeholders (0.5/0.5). It
  does not feed `AgentFusion`'s `risk` agent input and is not a candidate.
- `ai/core/intelligence/agent_analyzer.py` and `ai/core/atlas_multi_agent.py`
  both reference `macro_score`/`sentiment_score`/`risk_score` with silent
  `0.5` defaults - exactly the pre-Step-2C pattern
  `world_analysis_engine.py`'s own comment says was deliberately abandoned
  (fabricating a neutral score makes missing evidence indistinguishable from
  genuinely observed neutral evidence). Neither module is imported anywhere
  in the live decision path (only referenced in a stale `imports_report.txt`
  audit artifact and in `archive_unused_2026-07-22/` legacy files); both are
  orphaned and not candidates.

## Why

The currently-running observed Stage 1 paper run is structurally HOLD-only
as a direct consequence of this gap (see
`governance/findings/STAGE1-PAPER-001_STAGE1_PAPER_VALIDATION_CHECKLIST.md`
section 8.6). No BUY/SELL decision is reachable, which means the run cannot
produce evidence for anything execution-path-dependent - specifically prior
Finding 1 (crash-recovery, still only simulated) and prior Finding 2
(partial-fill, still absent), both of which require a real trade to occur.
Those two findings, and everything downstream of them in the Paper → Shadow
→ Small Live → Controlled Autonomous → Advanced Autonomous progression that
depends on having actually observed a real trade under the live paper
configuration, stay open indefinitely under the current provider
configuration, independent of how long the observed run continues.

## Where

**Phase 2 (Decision Intelligence / Market-Data Evidence Layer)** of the
existing fixed 0-10 phase roadmap. `analysis/world_analysis_engine.py`'s own
comments already frame this gap in Phase 2 terms ("PHASE 2 / STEP 2C -
EVIDENCE CONTRACT", "Phase 2 Market-Data Evidence Semantics Review"), and
the evidence-status contract this work would extend
(`analysis/evidence_status.py`) is itself a Phase 2 artifact. No new phase is
proposed or needed; this is additional work inside a phase already
underway, per CLAUDE.md's roadmap discipline.

## Dependencies

- A real, licensed, production-grade external data source for whichever of
  macro / sentiment / market-risk is selected (e.g., an economic-calendar or
  macro-indicator feed; a news/social sentiment feed; an independent
  market-wide risk/volatility index). None is currently integrated anywhere
  in this repository, active or archived, at production grade.
- `WorldAnalysisEngine.build_market_data()` would need to accept and forward
  the new score into `evidence_status` and the corresponding `*_score` field
  (`AGENT_SCORE_KEYS` in `ai/core/intelligence/agent_fusion.py:228-242`
  already reserves `macro_score`/`sentiment_score`/`risk_score` as the
  expected field names, so the consumer-side contract already exists and
  would not need to change).
- Whatever new provider client is added would go through CLAUDE.md's
  External code/repos gate (Discover → License → Security → Quality →
  Compatibility → Test → Adopt/Adapt/Reject) if it wraps a third-party
  library or API client, exactly as `atlas_finance/market_data/
  binance_public_provider.py` already does for the existing technical feed.
- Once a provider exists, `AgentFusion.MIN_PARTICIPATING_AGENTS` and
  `MIN_WEIGHT_COVERAGE` (`ai/core/intelligence/agent_fusion.py:166-169`)
  should be re-examined against the new roster - not necessarily changed,
  but re-verified, since their current values were tuned specifically around
  a 2-agent ceiling that would no longer be the ceiling.

## Risk

- **A rushed or low-quality provider is worse than no provider.** The
  current `UNAVAILABLE_NO_PROVIDER` state is an honest, fail-closed
  admission of missing evidence. A provider that silently degrades (rate
  limits, stale cache, a scraper that breaks silently) and is not itself
  gated by its own `evidence_status`/error taxonomy could reintroduce
  exactly the fabricated-neutral-evidence problem Step 2A/2B/2C were built
  to eliminate, or could produce `AVAILABLE` status on genuinely bad data,
  which is a **worse** failure mode than the current, visible, honest gap.
- **New external dependency and attack surface.** Any new data source is a
  new network dependency, a new class of provider error to handle correctly
  (mirroring the existing `MarketData*Error` taxonomy work closed for S-4),
  and a new thing that can be compromised, rate-limited, or silently wrong.
- **Financial-safety parameter risk.** Once a third agent is possible,
  `AgentFusion`'s weighted-voting arithmetic becomes reachable for the first
  time under real conditions rather than being categorically excluded by the
  participation floor. This is the intended purpose of the change, but it
  means the fusion math, weights, and confidence-to-execution gate all
  become live in a way they structurally cannot be today, and should be
  re-reviewed rather than assumed still correct once exercised for real.
- **Cost/vendor risk**, see below.

## Cost

Not estimated in this record. A real cost estimate needs a specific
provider selected (macro vs. sentiment vs. risk, and which vendor/feed for
it), which this scoping record deliberately does not choose. Expect at
minimum: a data-source subscription or API cost (recurring), integration
and error-handling implementation effort comparable to the existing
technical/market-data provider work, and test-authoring effort comparable to
the 21 tests that closed S-4's error-handling gap.

## Alternative

- **Do nothing; stay HOLD-only.** Valid and currently in effect. The
  observed run still produces real value for S-3 (candle-age evidence),
  RSI/trend sanity, and process/supervisor health, as recorded in
  STAGE1-PAPER-001 section 8.6. The cost is that Findings 1 and 2 stay open
  indefinitely and the promotion ladder cannot progress past what a
  HOLD-only run can prove.
- **Lower `MIN_PARTICIPATING_AGENTS` instead of adding a provider.**
  Rejected as an alternative by the existing code's own documented
  reasoning, not newly rejected here: `ai/core/intelligence/agent_fusion.py:
  147-164` explains in detail why a 2-agent floor would let a
  non-independent technical+momentum duplication become confidence-eligible
  for execution, which is a real-money-adjacent safety regression, not a
  scoping trade-off. This record does not propose revisiting that boundary.
- **Synthesize Finding 1/Finding 2 evidence without a real trade** (e.g., a
  forced/injected test trade in the paper environment to exercise
  crash/partial-fill paths directly, bypassing the confidence gate). Not
  evaluated here as accepted or rejected - it is a materially different
  approach to closing Finding 1/Finding 2 that does not require a new
  provider at all, and is named only so it is not lost; it would need its
  own separate scoping and owner decision, and is explicitly out of scope
  for this record.

## Decision

**DEFER.** This record documents the gap and what closing it would require.
It does not authorize building any provider, does not select which of
macro/sentiment/risk to build first, and does not commit to a timeline. The
owner decides if and when to accept this work, per CLAUDE.md's "capability
is never authority" principle and its rule that no new feature is
auto-accepted.

## Reaffirmation — 2026-09-23

**Status quo, no change.** Authorized by
`governance/current/ATLAS_MILESTONE_REGISTRY_v4.56.json`,
`GRANT-BACKLOG001-STATUS-QUO`. The owner reaffirmed this record's DEFER
decision unchanged, citing CLAUDE.md's roadmap discipline: this item stays
deprioritized below still-open RISK/ARCHITECTURE-tier items (Group B2 phase
(ii), GOV-DRIFT-005, incomplete REM-001 Gate 1), the same reasoning applied
to the compute-engine proposal in that same registry record. Nothing in
this document's `What`/`Why`/`Where`/`Dependencies`/`Risk`/`Cost`/
`Alternative` sections above changes as a result.
