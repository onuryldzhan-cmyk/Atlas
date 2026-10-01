# ATLAS CHECKPOINT — 2026-10-02: order observe live, collaboration handoffs, regime checker

## Completed (pushed, branch claude/exp001-on-owner-lineage)
**Regime filter:**
- `tools/regime_bar_check.py` applies the pre-registered bar verbatim.
- SC-* records now also keep drawdown and closed trades per window.

**HQ:**
- The inspector shows each agent's `atlas.event.v1` events from `/api/events`.
- New: a data-age (stale) indicator and the count of records that did not fit the event contract.
- Collaboration lines are drawn only from `collaboration.handoff` events.

**Handoffs (owner approved):**
- Derived only from a real `related_proposal` link: the proposal's author → `red_team` ("inceleme").
- A link to an unknown proposal produces nothing.

**Order state machine stage 1 is live in `main.py`** (`order_lifecycle_observe=True`, observe only). Violations show in `ExecutionManager.status()["order_lifecycle"]` and as a readiness FAIL.

**Reference-repo proposal:** `proposals/20261001T120000Z_dashboard-hq-professional-patterns-from-reference-repos.md` (ideas only, no code copied).

## Tests
- Last full suite: 6250 passed, 12 skipped, 0 failed.
- The intermittent c2 test did not recur in 5 full runs or 40 isolated runs. Its cause is UNKNOWN and it stays on watch.

## Switches (main.py)
| Switch | State |
|---|---|
| F-3 | ON |
| S1 sleeves | ON |
| F-4 5 bp | ON |
| Order observe | ON |
| Live authority | DENIED |

## Next exact action
1. Owner: update the machine and restart (commands on "geldim").
2. After about 1 week of PAPER with observe ON, review the `order_lifecycle` violations. If there are zero, write the stage-3 (enforce) design and get an audit.
3. Regime: run `tools/regime_bar_check.py` on the owner's `strategy_compare_latest.json`.
4. AI-001 (LLM agents) waits on the owner.
