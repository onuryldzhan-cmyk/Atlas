# ATLAS CHECKPOINT — 2026-10-02T15:00Z — learning: experience agent, lesson book, options A/B/C

## Objective
Owner: Atlas should keep learning from experience (replayed history + live paper trades) and
find ways to earn more with fewer, better trades. Research only; no trading behaviour changes.

## Completed (this segment)
- Refactors T-0001 fuse, T-0002 scheduler._execute_task, T-0003 _execute_paper_buy: golden/differential
  tests, independent audits (0 mismatches). T-0013 _execute_decision (1237 lines) DEFERRED by owner.
- CEO AI: 2.5 h spacing, reads evidence only (ignores own briefs + routine records).
- tools: task_status, agent_report (read-only).
- backtest_replay: per-trade entry confidence/regime, --trades-out, --signals-out (every BUY/SELL with
  60m/240m/1d after-fee net and raw move ret_*).
- lesson_book (read-only): action x regime x 5-pt confidence band; SELL judged on raw move (fixed fee bias);
  --fee-bps re-prices BUY (7 = BNB discount); 1-day column.
- experience_agent (unit experiment_manager, in AGENTS): one UTC day replayed per cycle (forward first,
  then backward to 730 days), appends <research>/experience/signals_v2.csv, walk-forward candidate lessons,
  XP-* memory record only when the candidate set changes; network failure = WARN, day retried.
- meta_filter (read-only): learn kept groups on older 70%, judge on newer 30%.

## Files changed
tools/{agent_cycle,backtest_replay,lesson_book,experience_agent,meta_filter,agent_report,task_status}.py,
ai/core/intelligence/agent_fusion.py, atlas_os/scheduling/scheduler.py, core/execution_manager.py,
observability/{agent_states,organization}.py, templates/research.html, tests (golden/characterization + new tools),
tests/test_code001_quality_ratchet.py (baseline tightened), packaging/REM-001 maps (line numbers).

## Architecture decisions
- Learning writes evidence only; candidates need walk-forward agreement; owner approval before any rule.
- Offline replay excludes macro/sentiment -> confidence lower than live; lessons are about signal quality.

## Tests
Last full run: 6354 passed, 12 skipped (before meta_filter commit; meta_filter subset 136 passed).

## Current state (owner machine — NOT yet pulled)
Owner last pulled cc9015a. Needs: git pull, restart with `python -m tools.start_atlas`.
EXP-002: 4/30 admissions; 25 trades in 60-70 band, win after fees 44%, calibration gap -0.18.

## Evidence so far (30-day replay, 5 coins, 11970 decisions)
BUY loses ~ round-trip cost at 1h/4h; confidence 50-65 not predictive; only TREND_UP near/above 0 at 4h.

## Known issues / risks
- Overlapping 15-min signals: effective n << n. market_regime agent ~330 s (network) once.
- Intermittent test test_c2_failure_after_booking... (unknown cause, not weakened).

## Remaining work
1. Owner: pull + restart; later run lesson_book/meta_filter on experience/signals_v2.csv.
2. After weeks of experience: review candidate lessons -> proposals (owner).
3. Option D (adaptive retraining) and E (funding carry) DEFERRED.
4. EXP-002 ends 2026-10-16 -> exp001_report --experiment EXP-002 -> owner decision.

## Next exact action
Remind owner to pull/restart; then read `python -m tools.agent_report --n 1` for the first XP/experience
cycle results.
