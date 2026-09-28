# ATLAS CHECKPOINT — EXP-001 live run, audit-fork incident, runtime hardening

Branch: `claude/exp001-on-owner-lineage` (PR #2), head `f23d0bd`.
Supervisor fixes also on `claude/supervisor-2-fixes` (PR #3, base `wip/supervisor-2`).
Authority unchanged: production_authority=NONE, live_authority=DENIED,
autonomous_deployment_authority=DENIED. PAPER only.

## Objective
Finish the owner-requested items from the previous checkpoint (SELL
reason code, supervisor WIP audit + fixes, merge), run the combined build
on the owner machine, and handle whatever the live run surfaced.

## Completed
- SELL of an unheld symbol: `NO_POSITION_TO_SELL` in ExecutionManager +
  MarketLoop HOLD routing (9f16c96, registry v5.04). Audit M1 (symbol
  key normalization) fixed.
- Supervisor WIP (8585d12) audited; MEDIUM1 bounded shutdown heartbeat,
  MEDIUM2 hangs never reset the restart budget, LOW5 periodic unreadable
  re-warn, portable heartbeat-path test (ce22922, 3077065, e1f5630, e5f6905).
  PR #3 opened; merged into the EXP-001 line (c0580ba, b637b00).
- INCIDENT: owner ran two Atlas processes on one state root
  (C:\AtlasState) at 13:44 local; the audit chain forked (lines 343-344).
  Atlas refused to start (correct fail-closed). Diagnosed with
  `tools/diagnose_audit_chain_fork.py` (0d31c0d): one break, all hashes
  valid.
- Prevention before repair (owner decision): exclusive OS instance lock on
  the state root (exit 76 ALREADY_RUNNING) + `AuditChainIntegrityError`
  exit 75 INTEGRITY_HALT, neither restarted by the supervisor (b11aaa4,
  registry v5.05). Audit HIGH (exit 3 = Windows abort()) fixed by moving
  codes to 75/76.
- Repair (owner-approved and owner-executed): `tools/quarantine_audit_fork.py`
  (9ab2067) moved lines 343-344 byte-for-byte to a quarantine file;
  379 -> 377 lines; Atlas restarted cleanly (registry v5.06, 3e9d28f).
- Dashboard showed the policy floor (HIGH >= 80, "execute edilmez") for BUYs
  EXP-001 admitted at >= 60: `/api/execution-gates` now publishes the
  experiment floor and the cards use it (bc03482).
- Read-only `tools/paper_position_report.py` (51e092d); attribution bug
  (approval written ms after the fill) fixed (f23d0bd).

## Files changed (this session, beyond the previous checkpoint)
core/execution_manager.py, core/market_loop.py, core/audit_event_store.py,
main.py, atlas_supervisor.py, web_app.py, templates/dashboard.html,
tools/diagnose_audit_chain_fork.py, tools/quarantine_audit_fork.py,
tools/paper_position_report.py, packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md
(regenerated with the repo tool; D5 untouched), registries v5.04-v5.06, tests:
test_sell_without_position_routing.py, test_single_instance_and_integrity_exit.py,
test_quarantine_audit_fork.py, test_paper_position_report.py,
test_dashboard_execution_gates.py (extended), test_main_process_heartbeat.py,
test_process_supervisor.py, test_block5b_single_sizing_authority.py (pinned
reason change, owner-approved v5.04).

## Architecture decisions
- One Atlas per state root, enforced by an OS lock in `AtlasProcess.start()`.
- Unfixable exits (75 integrity, 76 already running) are never restarted.
- Audit repair = quarantine (move, never edit/rehash), dry run first.
- Dashboard reads the enforced floor from RiskEngine, never recomputes policy.

## Tests
Full suite last run: 5349 passed, 12 skipped, 2 failed = B2 + D5 only
(`tools/ci_check_known_accepted_failures.py` PASS). PR #2 and PR #3 CI green
on their last reported heads; PR #2 CI for f23d0bd not yet observed.

## Current state (owner machine, 14:20 local)
Atlas-test worktree at 51e092d, Atlas stopped cleanly. EXP-001 admissions 5/50.
Open paper positions (all HIGH bucket): BNB, BTC, ETH, SOL, XRP — all five
under EXP-001 (BNB's attribution corrected by f23d0bd; verify on next report).
Cost 4094.20, unrealized +1.82 at 14:2x. Cash 5905.80. New BUYs blocked by
DUPLICATE_OPEN_POSITION until SELLs close positions.

## Known issues
- Instance lock lives in `AtlasProcess` only; tools constructing
  `AtlasApplication` directly bypass it (e.g. tools/phase6a8_1_decision_execution_trace.py). DEFERRED, needs owner approval (architecture).
- Only the audit-chain failure maps to exit 75; other state-integrity
  failures still exit 1 and are restarted up to budget. UNKNOWN which should.
- Windows msvcrt lock behaviour verified only via mocks + Windows CI.
- SELL fix not yet exercised live (no SELL signal since deployment).
- Owner repo `.git/worktrees/atlas_baseline_*` prune "Permission denied" noise (harmless).

## Risks
- Running Atlas from two folders on the same C:\AtlasState — now blocked by
  the lock, but only for the main/supervisor path.
- All five slots full under EXP-001; experiment outcome now depends on exits.

## Remaining work
1. Owner: run Atlas at >= f23d0bd, keep the window untouched (Ctrl+C = stop),
   check panel EXP-001 line, watch the first SELL (`treated as HOLD` for unheld,
   exits for held).
2. Owner decisions: move lock into AtlasApplication; classify other integrity
   failures; risk_level proposal + ceiling measurement; FIN-004.1a comparison;
   G-S3; PR #2/#3 merge.
3. ADR draft for the Intelligence Layer / Atlas Coder vision (owner item A,
   doc only, DEFER implementation to Phase 9).

## Next exact action
Write the ADR draft (owner option A) under docs/adr/ as PROPOSED, no code.
