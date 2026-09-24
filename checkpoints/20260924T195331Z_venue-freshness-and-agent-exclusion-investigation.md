# ATLAS CHECKPOINT

## Objective

Two independent, read-only observability investigations surfaced during a
real supervised paper run on 24 Eylül, neither previously investigated:

- **Part A** — venue instrument-rule freshness reports STALE
  (`age_seconds=3100420`, ~36 days, vs `maximum_age_seconds=2592000`); find
  whether any safe, already-existing, non-Package-6C mechanism can refresh
  it, and run it if so.
- **Part B** — 3 of 5 intelligence agents (macro, sentiment, risk) report
  `EXCLUDED status=UNAVAILABLE_NO_PROVIDER` in every observed decision cycle;
  classify each as NEVER_IMPLEMENTED / CONFIGURED_BUT_FAILING /
  DISABLED_BY_FLAG / OTHER with evidence, and confirm NB-4/NB-5 protections
  still hold under the 2-of-5-active condition.

Both parts were scoped strictly read-only/investigation-only. No provider
implementation, no Package 6C construction, no touching
`feat/block3-execution-safety`, no confidence-calculation change.

## Completed

Investigation only. No code, test, or config file was changed.

### Part A result — CONFLICT found; no safe closing action available

The task's own premise is **stale/incorrect** and is recorded here as a
CONFLICT:

- **Expected (per brief):** "Package 6C ... is currently BLOCKED pending the
  owner's GOV-DRIFT-002 resolution and lives on `feat/block3-execution-safety`,
  which is off-limits right now."
- **Actual:** `tools/venue_metadata_adapter.py` (Block 6C, the venue metadata
  adapter) was committed at `3265b44` (2026-08-27) and **is already present
  on the current branch** `research/edge-validation`
  (`git branch --contains 3265b44` lists `research/edge-validation`, not just
  `feat/block3-execution-safety`). Its governance disposition is
  `GOV-DRIFT-003` (not `GOV-DRIFT-002` — a related but separate finding),
  status `RECONCILED_BY_VERSIONED_SUCCESSOR_RECORD`, `blocking_effect: CLOSED`,
  resolved in registry v4.28 — 45 registry versions before the current
  v4.73. `GOV-DRIFT-002` itself (a different finding, about REM-001 freeze
  scope vs. the block3 stream generally) was also already `CLOSED`, in
  registry v4.27. Neither finding is open today.
- **Evidence:** `git log --oneline -- tools/venue_metadata_adapter.py` (one
  commit, `3265b44`); `git branch --contains 3265b44`; registry
  `governance/current/ATLAS_MILESTONE_REGISTRY_v4.73.json` lines 1906-1942
  (`GOV-DRIFT-002`, `GOV-DRIFT-003` records); `docs/evidence/
  block6c_venue_metadata_adapter.md` (the package's own freeze evidence,
  22 tests passing, closure-verified outside the runtime import graph).
- **Impact:** the tool is real, safe, and not blocked. But running it
  **cannot actually close the observed staleness**, for two independent
  reasons the tool's own evidence record already names as deliberately
  deferred, separate future steps:
  1. It requires a genuine, current `exchangeInfo` snapshot from the venue.
     No automated fetch mechanism exists anywhere in the repository (6A's
     own docstring: "the only Binance client serves prices and candles, not
     `exchangeInfo`"); obtaining one live would be a new, owner-gated
     network action against a financial venue, not a read-only
     investigation step.
  2. Even with a fresh snapshot, the adapter deliberately **never writes**
     `config/instrument_rules.json` — the file `core/venue_rule_freshness.py`
     actually assesses, and which Package 5D made "the sole,
     process-immutable venue precision authority." It publishes to a
     separate artifact (`instrument_rules.published.json` by default), and
     "wiring a runtime to a published artifact is a separate, explicit
     operator action" that has never been taken (`grep` for
     `instrument_rules.published` found no such file anywhere on disk).
     Overwriting the checked-in authority file itself would be a
     production-financial-config change requiring explicit owner
     authorization under CLAUDE.md's git & approval policy, not something
     this investigation may do on its own initiative.
- **Verified:** `config/instrument_rules.json` is unchanged since commit
  `bd950fd` (2026-08-20), `retrieved_at: "2026-08-19T17:47:48Z"` — consistent
  with the observed `age_seconds=3100420`. No `instrument_rules.published*`
  file exists anywhere in the tree; the adapter has never been run against
  real data in this repository.
- **Conclusion: no safe path exists to close this right now** — not because
  Package 6C is blocked (it is not), but because closing it requires two
  further owner decisions (acquiring a real snapshot; authorizing the
  runtime-authority file to be touched) that are outside a read-only
  investigation's authority. Not blocking in PAPER mode, per the venue
  freshness policy's own `allow_stale_bounded_execution=True` default.

### Part B result — 3 classifications, evidence-backed

| Agent | Classification | Evidence |
| --- | --- | --- |
| **macro** | **NEVER_IMPLEMENTED** | `analysis/world_analysis_engine.py:110-112` unconditionally hardcodes `MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER` for `macro`. `governance/findings/BACKLOG-001_MARKET_DATA_PROVIDER_SCOPING.md` confirms, after searching the full active (non-archived) tree, "no code path anywhere ... can set macro ... to AVAILABLE." Status: DEFER, reaffirmed by the owner in registry v4.56 (`GRANT-BACKLOG001-STATUS-QUO`), unchanged since. This is by-design roadmap deferral, not a regression — there is no git history of macro ever being active. |
| **risk** (the `AgentFusion` "risk" score key / `market_risk` evidence-status field) | **NEVER_IMPLEMENTED** | Same file, `:117-119`, same unconditional hardcode. BACKLOG-001 explicitly rules out `ai/core/intelligence/risk_engine.py`'s `RiskEngine.calculate()` as a candidate: it is a *post-decision* risk classifier fed hardcoded 0.5/0.5 placeholders, and "does not feed `AgentFusion`'s `risk` agent input." No git history of this slot ever being active. Same DEFER status as macro. |
| **sentiment** | **OTHER — implemented, but withholding by design in the current Fear & Greed band; not a defect and not the same failure mode as macro/risk** | `atlas_finance/market_data/fear_greed_provider.py` (real, live, no-auth `alternative.me` Fear & Greed provider) was implemented and wired L2→L3→L4 at commit `75c4fce` (2026-09-23T21:08:41+03:00), one day before the observed run. `core/application.py:666` **unconditionally** constructs `FearGreedProvider()` and injects it into `MarketLoop` — no feature flag, no config gate; `git log` confirms no change to `core/application.py`'s sentiment wiring since. `core/market_loop.py:1929-1932`: `sentiment_input` is `None` (→ `UNAVAILABLE_NO_PROVIDER`) **only** if `self.sentiment_provider is None`, which cannot happen through the normal composition root. The confirmed rule (owner-approved, registry v4.66) deliberately keeps the 25-74 "neutral" Fear & Greed band as `UNAVAILABLE_NO_PROVIDER` — **the identical status code** used for a genuinely absent provider — "not a participant," by design, disambiguated only by `sentiment_evidence.reason`. The live-investigation session (`governance/findings/BACKLOG-001...md`, "Live sentiment-provider investigation — 2026-09-23") fetched the real index that day: value 71, squarely inside the 25-74 withholding band. **UNKNOWN, not assumed:** whether the specific paper run the task brief describes started before or after `75c4fce` landed — no Atlas process is running now (`tasklist` for `python.exe`/`pythonw.exe`: none found), so this could not be checked against a live process. If that run's process predates `75c4fce`, sentiment's exclusion in it is a **stale-process** artifact (the in-memory code lacks the wiring) and would resolve on restart; if it postdates `75c4fce`, the exclusion is the documented, by-design neutral-band withholding, not a gap. Either way it is not a regression and not a missing provider — it is already the owner-approved checkpoint's own known open item ("`evidence_status.py`'s docstring still says 'no data source exists'... imprecise for sentiment's neutral-band case," recorded 2026-09-23, not yet fixed). |

**NB-4/NB-5 confirmation under the current 2-of-5-active condition — CONFIRMED HOLDING, not assumed.**

- `AgentFusion.WEIGHTS` has exactly 5 keys (`technical`, `momentum`, `risk`,
  `macro`, `sentiment`); `AgentFusion.MIN_PARTICIPATING_AGENTS = 3`. With
  macro and risk permanently excluded and sentiment excluded whenever the
  Fear & Greed reading is in the neutral band, only `technical` + `momentum`
  (2 agents) are ever available in that state, which is **below** the
  3-agent floor. `AgentFusion.fuse()` (`ai/core/intelligence/
  agent_fusion.py:639-657`) short-circuits to `action="HOLD"`,
  `confidence=0.0`, `reason="INSUFFICIENT_EVIDENCE"` **before any weighted
  vote runs** — a stronger, more conservative guarantee than the NB-5
  denominator check alone would give, since confidence cannot rise at all in
  this state, let alone incorrectly.
- Directly tested, not inferred: `tests/test_nb4_nb5_confidence_availability_
  correction.py:101` (`reduced.value <= full.value` — NB-4), `:218-220`
  (`len(AgentFusion.WEIGHTS) == 5; agreement == pytest.approx(0.6); agreement
  < 1.0` — NB-5's expected-roster-size denominator, not surviving-agent
  count). `tests/test_backlog001_sentiment_wiring_and_fusion.py`'s
  `test_withholding_sentiment_never_raises_confidence_nb4`, parametrized over
  126 states, confirms the same guard specifically for sentiment's
  withholding case.
- **These tests were not re-run this session; citing already-established
  evidence per the token-efficiency contract.** Verified first that nothing
  they depend on changed since: `git log --oneline -- ai/core/intelligence/
  agent_fusion.py analysis/world_analysis_engine.py tests/
  test_nb4_nb5_confidence_availability_correction.py tests/
  test_backlog001_sentiment_wiring_and_fusion.py` shows the last change to
  either production file was `2fe05a0` (2026-09-23, comment-wording only,
  confirmed non-functional in that commit's own checkpoint), and the two
  test files are unchanged since `75c4fce`/`2fe05a0` respectively. The most
  recent full-suite artifact (checkpoint `20260924T194521Z`, generated
  2026-09-24T14:42:16Z at commit `9e28d4d`) reports `3906 passed / 1 failed`
  (the pre-existing, accepted Group B2 architecture test) — no NB-4/NB-5
  test is among the failures.
- **No NB-4/NB-5 regression observed.**

## Files changed

- Added: this checkpoint file only.

## Architecture decisions

None. No production code was touched.

## Tests

No tests were run this session. Existing NB-4/NB-5 and sentiment-wiring test
evidence was cited from the most recent full-suite artifact (3906 passed / 1
failed at commit `9e28d4d`, re-affirmed unchanged through HEAD `f5e7250` per
checkpoint `20260924T194521Z`) after confirming via `git log` that none of
the files that evidence depends on changed since.

## Current state

Branch `research/edge-validation`, HEAD `f5e7250`. Working tree clean except
this checkpoint file. No Atlas process is running (`tasklist` checked for
`python.exe`/`pythonw.exe`: none found).

## Known issues

- Carried forward, unchanged: `analysis/evidence_status.py`'s
  `UNAVAILABLE_NO_PROVIDER` docstring ("No production-grade data source
  exists for this field yet.") remains accurate for macro/risk but imprecise
  for sentiment's neutral-band withholding case. A dedicated status/reason
  distinction would need its own grant scoped to that file (already recorded
  in the 2026-09-23 checkpoint; not reopened or widened here).
- Carried forward, unchanged: the greed-side `AgentFusion` weighting
  question (sentiment's GREED-band votes never clear `MIN_CONFIDENCE`) is an
  open PROPOSE-tier item for a future owner decision; not touched here.
- New: whether the specific paper run that produced the task brief's
  observation predates or postdates commit `75c4fce` is UNKNOWN — no running
  process could be queried. This determines whether sentiment's exclusion in
  that specific historical observation was a stale-process artifact or
  by-design neutral-band withholding; either way it does not change any
  classification above going forward from current HEAD.

## Risks

None introduced. No code, test, or production config was changed.

## Remaining work / Recommended next scoped task for the owner

1. **Correct the stale premise** wherever it originated (an out-of-session
   note or prior briefing) that Package 6C is "blocked pending GOV-DRIFT-002"
   — it has been closed and unblocked since registry v4.28. This checkpoint
   is the correction record.
2. **Venue-rule freshness (Part A):** two separate owner decisions are
   needed before this can close, neither performed here: (a) whether/how to
   obtain a current, verified `exchangeInfo` snapshot (manual operator pull,
   or scope a new authenticated HTTP transport behind `ExchangeInfoSnapshot`
   as its own reviewed package — 6C's evidence record already names this as
   the remaining seam); and (b) whether/how to wire the runtime to consume a
   6C-published artifact instead of (or in addition to) the checked-in
   `config/instrument_rules.json` authority file. Until both are decided,
   staleness will only grow; it remains non-blocking in PAPER mode.
3. **Agent exclusion (Part B):** the real, actionable future package,
   already scoped and DEFERRED at the owner's own prior decision, is
   BACKLOG-001's still-open item: implement macro and/or risk
   (market-risk) providers, which is the only way to raise
   `participating_count` durably above the 2-agent ceiling (sentiment alone
   cannot, since it withholds in the neutral band roughly half the time by
   the Fear & Greed index's own historical distribution). This is a
   separately-sized package per BACKLOG-001's own Cost/Risk/Alternative
   sections and is not started, decided, or recommended for a timeline here.
4. Optional, low-cost, non-blocking: fix `analysis/evidence_status.py`'s
   docstring imprecision for sentiment (known issue above) under its own
   small grant, so `UNAVAILABLE_NO_PROVIDER` reads correctly for all three
   consumers.

## Next exact action

Await owner decision on items 2 and 3 above. No action is queued or
authorized by this checkpoint.
