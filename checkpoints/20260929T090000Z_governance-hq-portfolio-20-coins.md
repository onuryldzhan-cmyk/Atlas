# ATLAS CHECKPOINT — governance foundation, HQ, live portfolio, 20-coin universe

**Objective:** owner's master build command, bounded by the owner's choice "Önce yönetişim temeli", then the owner's follow-ups: HQ/dashboard, real-time capital and P/L from real data, 20 coins, and agents improving Atlas.

**Completed (branch `claude/exp001-on-owner-lineage`, registry v5.34–v5.42):**
- v5.34: `atlas_org/`, permissions, a hash-chained proposal lifecycle and Memory with provenance; `/api/proposals|memory|permissions`.
- v5.35: deterministic Atlas Manager, a task lifecycle with permission-checked routing, and `/api/tasks`.
- v5.36: Security Guardian (AST), bound to proposal security reviews.
- v5.37: Command Center brief and deterministic Atlas Chat (`/api/command-center`, `/api/chat`).
- v5.38: `/hq`, a dependency-free Canvas 3D core plus 2D panels. three.js was DEFERRED because the download was denied.
- v5.39: the independent audit and re-audit are closed.
  - F1: owner HMAC signatures; the key lives outside the repo and the web never reads it.
  - F2: path normalisation.
  - F3: evasions.
  - F4: security reviews are bound to evidence and re-verified before the owner signs.
  - F5: disclosed.
  - F6: phrasing.
- v5.40: `/api/portfolio` (the real durable PAPER book valued at real loop prices, with starting capital derived exactly), `/home` (simple) and `/trading` (detail).
- v5.41: trade universe = the symbols with real Binance venue rules (max 20); `--preset owner-20`.
- v5.42: `tools/atlas_self_review.py`, which files improvement tasks from real evidence and never edits.

**Tests:** full suite 5828 passed, 12 skipped, 2 failed. The 2 failures are the accepted B2/D5 (`tools/ci_check_known_accepted_failures.py` PASS).

**Current state:**
- Atlas trades PAPER on the 5 coins that have real rules; live money DENIED.
- 20 coins need the owner's rules refresh (OWNER_TERMINAL_TASKS §6).

**Known issues / risks:**
- api.binance.com is blocked in the cloud environment.
- `ExecutionPortfolioFoundation.mark()` has no runtime caller; the portfolio view values positions itself.
- The owner key is readable by any process running as the owner's OS user.
- A log truncated at its tail is detectable only by comparing against the noted head.
- The web cannot verify owner signatures (Ed25519 needs a new dependency, DEFERRED).
- Cycle time with 20 coins should be re-measured (PERF-001).

**Remaining work (owner decisions):**
- Q2: EXP-001 by 2026-10-12.
- Q6: AI-001 LLM agents.
- Ed25519 dependency.
- `max_positions` with 20 coins (unchanged at 5, risk decision).
- The staged runtime package was not started (backtest evidence v5.33).

**Next exact action:** the owner runs OWNER_TERMINAL_TASKS §6 and §7 and pastes the outputs. Then re-measure cycle telemetry with 20 coins and record PERF-001 for 20.
