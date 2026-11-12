# ATLAS CHECKPOINT — Phase 2–3 closed, CFG-001, regime risk_level, paper fees

**Branch:** `claude/exp001-on-owner-lineage` · **Head:** see `git log` (after 222e0d5 + this checkpoint) · **Registry head:** v5.23

## Objective
- Finish the owner's ordered list:
  - the EXP-001 durable counter;
  - the orphaned panel thread;
  - Phase 2–3 closure;
  - the REM-001 Gate 1 study.
- Then continue along the roadmap: CFG-001, the regime-derived risk_level, the EXP-001 report and the paper fee model.
- The owner then delegated autonomous continuation with the recommended options (see `docs/operations/AUTONOMOUS_DECISION_LOG.md`).

## Completed (registry)

| Registry | What |
|---|---|
| v5.17 | EXP-001 durable admission ledger (max of audit and ledger; written before each admission is granted); bounded shutdown of a hung panel |
| v5.18 | Phase 2–3 **closed** (owner). Feature freeze re-keyed from REM-001 Gate 1 (certification path closed) to "next roadmap phase only" (owner, option A) |
| v5.19 | Owner Windows run: lock exit 76 proven; SELL fix proven live (5/5 EXP-001 trades closed, +17.54 gross) |
| v5.20 | Owner decisions: LOW volatility ceiling = p30 per symbol; CFG-001 exits 1 on bad config; unknown `ATLAS_*` variables refused |
| v5.21 | CFG-001: one-pass startup configuration validation, PAPER-only invariant, `tools/show_config` |
| v5.22 | risk_level derived from the volatility regime (A1 + A2 at p30 + Macro cap, fail-closed to HIGH); EXP-001 admissions sized with HIGH limits (owner: "%10 kalsın") |
| v5.23 | Paper fee 0.1% per side, opted in by main.py only; recovery uses the rate recorded on the approval; admission venue-minimum bound includes the fee |

Tools added:
- `tools/exp001_report` (win rate with 95% range, verdict on net after estimated fees);
- `tools/show_config`;
- progress output for `tools/measure_volatility_ceiling`.

## Files changed (main)
- `core/`: `experiment_ledger.py` (new), `atlas_config.py` (new), `risk_engine.py`, `application.py`, `execution_manager.py`, `market_loop.py`
- `ai/`: `ai/core/intelligence/risk_engine.py`, `ai/core/atlas_brain.py`
- top level: `main.py`, `atlas_service.py`
- `tools/`: `reconcile_execution_authorities.py`, `exp001_report.py` (new), `show_config.py` (new)
- `tests/`: `test_exp001_*`, `test_atlas_config`, `test_regime_risk_level`, `test_paper_fee_model`, `test_exp001_report`, `test_panel_decoupling`
- `docs/operations/`: `RECOVERY_RUNBOOK.md`, `OWNER_TERMINAL_TASKS.md`, `REM001_GATE1_STUDY`, `CFG001_PLAN`, `PAPER_FEE_MODEL_PLAN`, `AUTONOMOUS_DECISION_LOG`

## Architecture decisions
- Runtime opt-ins (EXP-001, the paper fee) are literal at the `main.py` call site. The library defaults stay conservative or historical, so contract tests remain valid.
- The regime is the bucket selector, and missing evidence can never make Atlas less conservative (NB-4).
- `RiskEngine.sizing_bucket` is the single answer shared by the sizer and the engine.

## Tests
- Last full suite: **5532 passed, 12 skipped, 2 failed = B2 + D5 (accepted)** (`ci_check_known_accepted_failures` PASS).
- Since then, one test was added: `test_partial_sell_charges_exit_fee_and_apportions_entry_fees`. `test_paper_fee_model.py` now reports 15 passed.
- Every CRITICAL change had mutation checks and an independent audit; all findings are fixed or recorded.

## Current state
- **Owner machine:**
  - running a build older than v5.22 and v5.23;
  - 0 open positions; cash 10017.54;
  - EXP-001 at 5/50.
- **Owner must pull and restart** to activate v5.21–v5.23 (commands in `OWNER_TERMINAL_TASKS.md`).

## Known issues / risks
- The paper fee rate is the public base rate; the owner's account tier is UNKNOWN.
- EXP-001 sample is 5 trades, insufficient for any verdict.
- The regime rule has no end-to-end test from real candles (the estimator identity is verified from source).
- The decision `risk` key taking precedence over `risk_level` in the market loop is UNKNOWN.
- The memory module reports `trades=0`; it is metadata only, has no decision effect, and is intentionally left alone.

## Remaining work
- **ARCH-001:** its specification is lost (GOV-DRIFT-005), so the owner must decide the scope (queued).
- CODE-001 is blocked on ARCH-001. DEP-001 is not sequenced.
- EXP-001 decision on 2026-10-12 using `tools/exp001_report`.

## Next exact action
Owner:
- pull the new build;
- run `show_config` and `check_execution_authority_agreement`;
- restart the supervisor.

Session: wait for the owner's ARCH-001 scope decision; meanwhile only low-risk verification work.
