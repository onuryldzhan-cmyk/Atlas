# ATLAS CHECKPOINT — Task 009: Market Regime Identification & Cycle Tracking

## Objective
Implement Task 009 under GRANT-TASK-009-MARKET-REGIME-CYCLE-TRACKING (registry v5.93):
- a lookahead-free regime classification;
- hysteresis;
- a multi-timeframe anchor;
- an immutable strategy permissibility matrix with a regime scale in [0, 1];
- REGIME_UNKNOWN fail-closed for new entries while exits are preserved.

The brief's red-team vectors are A (lookahead), B (flapping) and C (silent misclassification).

## Completed
- **CONFLICTs C-1..C-9** were reported and decided by the owner in session on 2026-10-10:
  - v5.93 was absent and Task 008 was still active.
  - The brief's "governance ZERO modifications" rule contradicted its own v5.93 deliverable.
  - intelligence/regime is a legacy module excluded from the runtime.
  - The draft regime filter is not proven.
  - The runtime has no strategy archetypes.
  - MarketLoop held only about 4 hours of 1-minute candles.
  - "Madde" is UNKNOWN.
  - The intelligence/ import boundary.
  - The evidence-bar mismatch (C-9).
- **Owner decisions:**
  - Draft v5.93: close Task 008, confirm the 5xx deviation, grant Task 009.
  - Build the gate, default OFF.
  - One shared classifier.
  - Closed-bar buffers, observe only.
  - After review 17: a separate regime feed.
  - After review 18: **observation OFF for now**, which reverses the observe-only answer.
- **Registry v5.93** (committed on its own): Task 008 CLOSED; Task 009 defined, granted and ACTIVE. It also records the CONFLICTs, the UNKNOWNs and reviews 15–19.
- **core/market_cycle.py (new):**
  - the shared classifier, moved unchanged from tools/regime_engine. The only behaviour change: NaN, inf, non-numeric and bool closes are now UNKNOWN.
  - the causal closed-bar pipeline (`closed_bars`, `assert_causal`).
  - `RegimeTracker` hysteresis: restrictive and refused regimes are entered immediately; other changes need confirm 2 and dwell 3; a contradicted state decays to TRANSITION.
  - the 4H/1D anchor and the immutable `PERMISSIBILITY` matrix with `permission()`.
  - `MarketCycleTracker`: a per-symbol observer with warm start, causal replay of missed bars, fault separation, cutoff regression and an overlap guard.
  - `DRAFT_EVIDENCE_GATE`.
- **tools/regime_engine.py:** re-exports the classifier, so replay and research use the same function.
- **core/market_loop.py:** optional, default-OFF regime support.
  - `regime_observation` or an enabled `regime_gate` requires a dedicated `regime_feed`, never the 1m feed.
  - Observe-only fetches inside `run_cycle` are deferred until every symbol is routed.
  - The gate can only turn a BUY into SKIPPED or shrink its proposed size. A SELL is never touched.
- **core/application.py:** unchanged from HEAD. The runtime neither observes regimes nor gates.

## Files changed
- **Task 009 commit:**
  - core/market_cycle.py (new), core/market_loop.py, tools/regime_engine.py
  - tests/intelligence/__init__.py (new), tests/intelligence/test_task009_regime_tracking.py (new, 97 tests)
  - the five regenerated packaging artifacts: atlas_runtime_closure.json, atlas_architecture_map.json, REM-001_IMPORT_GRAPH.json, REM-001_RUNTIME_CONSTRUCTION_PATHS.md and REM-001_STATE_AUTHORITY_MAP.md
  - this checkpoint
- **Separate commit:** governance/current/ATLAS_MILESTONE_REGISTRY_v5.93.json.

## Architecture decisions
- **Location:** the shared classifier lives in `core/`, because `intelligence/**` is excluded from the runtime distribution.
- **Gate default:** OFF. Switching it on needs three things:
  - evidence measured on the runtime rule: clock-aligned closed bars with a 720-bar history. Per C-9, the draft's replay bar does not validate any runtime configuration.
  - the governed policy manifest.
  - an owner decision.
- **Observation:** OFF in the runtime. Switching it on needs its own design (a background worker that never blocks trading, plus a stored evidence record) and owner approval.

## Tests
- Full suite: 10577 passed, 12 skipped, 0 failed. That is the 10,480 baseline plus the 97 Task 009 tests.
- Architecture and block4 tests: green.
- Every review fix was mutation-checked; each removed fix makes its test fail.

## Reviews (fresh context, red team, threshold 0 BLOCKING / 0 HIGH / 0 MEDIUM)
- **Review 15 — FAIL.** Findings: the architecture artifacts, fault separation, F3, untested guards, and F5–F8.
- **Review 16 — FAIL.** Findings: the replay alignment (M1), the I/O ordering, and test gaps.
- **Review 17 — FAIL.** Findings: the shared feed latch (F1), the cross-symbol delay (F2), the replay history (F3), and test gaps.
- **Review 18 — FAIL.** M1: observation I/O on the worker thread. The owner turned runtime observation OFF; test gaps were also fixed.
- **Review 19 — PASS (0/0/0).**
  - A differential run against HEAD was identical.
  - Its LOW findings, F1 (wording) and F2 (four test gaps), were fixed before commit.

## Current state
Task 009 is implemented and verified, and its milestone is ACTIVE; closing it is the owner's decision. Paper runtime behaviour is unchanged.

## Known issues / limitations (all recorded in v5.93)
- The permissibility scales and hysteresis defaults are uncalibrated.
- Provider behaviour for 1h/4h/1d against live Binance is UNKNOWN.
- If observation were enabled on the worker thread, it would lengthen cycles (review 18 M1).
- Gate side: if `observe()` ever raised, the gate would read the previous snapshot. This is unreachable today, but must be made fail-closed before the gate is enabled.
- Deferred (pre-existing, outside scope):
  - MarketFeedService's DEGRADED latch: `_require_running` blocks the recovery path, so three consecutive 1m failures halt the 1m path until restart.
  - the `ore/` path-truncation bug in tools/build_architecture_inventory.py.
  - the clock flake in tests/test_apprentice.py.

## Risks
None to the current runtime: application.py is unchanged, and the gate and observation are both OFF.

## Remaining work
- The owner closes Task 009.
- Later, under owner decisions:
  - a background regime observer with stored evidence;
  - a runtime-rule evidence measurement (C-9);
  - a fix for the MarketFeedService latch.

## Next exact action
Report to the owner.
