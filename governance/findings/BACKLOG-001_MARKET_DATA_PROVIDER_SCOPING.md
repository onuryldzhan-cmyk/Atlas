# BACKLOG-001 — Missing macro / sentiment / risk market-data provider

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
