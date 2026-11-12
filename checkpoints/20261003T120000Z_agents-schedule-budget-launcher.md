# ATLAS CHECKPOINT — Agents: own clocks, build on previous work, whole-window budget, guarded launcher (2026-10-03)

**Objective (owner, 2026-10-03):**
1. Tie the AI budget to the whole 5-hour plan window, with each agent using what its work needs.
2. Give each agent its own timing.
3. No busywork: no trivial or repeated questions. Longer prompts are fine when useful.
4. Agents build on their previous work.
5. Agents start together with Atlas.
6. Protect the system against crashes.

**Completed (branch claude/exp001-on-owner-lineage):**
- **c92b56c — per-agent schedule:**
  - `tools/agent_cycle.SCHEDULE`: each agent has its own interval and inputs (archive / audit / memory / proposals / tasks, compared by size + mtime).
  - `run_scheduled()` runs only the agents that are due. A failed, warned or `pending` run is retried even without new input.
  - An unreadable schedule, or a clock that went back, makes an agent due rather than silent.
  - A tick is recorded only when a log changed or something failed, plus an hourly heartbeat. The dashboard's `RECENT_CYCLE_S` is 2 h, so live agents stay IDLE.
  - Skipped agents appear in the AC record together with their last result.
  - **Busywork removed:**
    - `market_regime` wrote an MR record every cycle (which also triggered the CEO); it now records only on change.
    - `atlas_self_review` wrote "0 tasks filed" every cycle; it now records only a new task or a new refusal.
  - The council reviews up to 3 waiting proposals per run.
- **546391d — build on previous work:**
  - CEO: sees its previous brief; records that are NEW since it are marked; it returns `followups` (resolved / changed / still open, plus the next sharper step) and new priorities only from NEW evidence. The record stores `builds_on`.
  - Council: sees the owner's earlier decisions and how often its own verdict matched them.
  - Performance report: has `since_last_report` (new trades, net change, verdict and win rate before vs now).
- **e697f1d — fix of my own T-0016 golden test:**
  - The test read machine-local governance records and an untracked test-results artifact, so it failed in a clean worktree and would fail on the owner's machine.
  - It is now hermetic and was regenerated on the pre-refactor `web_app.py` (4469419).
  - It passes there, on the current code, in a clean worktree, and with extra local records / a broken artifact. All 4 mutations are still caught.
- **70e4ba4 — budget:**
  - The owner rule "whole 5-hour window, as needed" supersedes "60 %, split by task size". The old rule text is kept as a superseded record, with the reason, in the code and in `docs/operations/AI001_CLAUDE_API_SETUP.md`.
  - Subscription backend: the plan's own limit is the budget. `ATLAS_AI_WINDOW_CALLS`, if the owner sets it, is used in full (unset = no Atlas ceiling, unreadable = 0).
  - Still bounded by: the allowlist (ceo_ai, model_council); never paying twice for the same question within 24 h (question hash in the ledger; old 3-field entries stay readable); a runaway ceiling of 12 calls per agent per 5 h.
  - Anthropic (support article 11145838, read 2026-10-03): Pro/Max limits are shared by Claude and Claude Code. This is written in the doc together with how to keep a reserve.
- **3e853db — agents started with Atlas in their own guarded process:**
  - Command: `python -m tools.start_atlas`.
  - The agents run as a separate, lower-priority process: Windows BELOW_NORMAL with its own process group; POSIX its own session with nice 10.
  - Restart: 5 restarts with backoff from 30 s to 10 min (Atlas's own `RestartPolicy`), then given up; Atlas keeps running.
  - Hang watchdog: no heartbeat for 45 min → the process is killed.
  - Stop: polite first (Ctrl+Break / SIGTERM), then kill after 20 s. Record locks now hold their writer's PID, and the locks of a killed PID are released.
  - Single runner via `core.instance_lock`: no stale lock after a crash; a second runner exits with code 3.
  - Parent-death detection through stdin, read with `os.read`. The real-process test caught CPython aborting at shutdown (exit -6) with the buffered reader.
  - Patterns, with stars verified 2026-10-03: supervisord startretries/startsecs (Supervisor/supervisor, 9.1k); Kubernetes CrashLoopBackOff + liveness probe (kubernetes/kubernetes, 128k).

**Tests:**
- New: test_agent_schedule (11), test_agents_build_on_previous_work (4), test_agent_runner (7), test_start_atlas (10, replacing the thread tests; reason written in the file).
- test_ai_gateway: the three tests pinning the 60 % rule were replaced; the failure tests now ask a distinct question per case (reason written in the file).
- Full suite on a clean worktree: at 70e4ba4 6458 passed, 13 skipped, 0 failed; at 3e853db 6473 passed, 13 skipped, 0 failed.

**Architecture decisions:**
- The runtime stays AI-free. `main.py` does not start the agents; `tools.start_atlas` starts Atlas and the agents as siblings.
- Agents stay advisory; nothing here trades, deploys, approves or changes a gate.

**Current state:** all five commits pushed. Independent read-only audit of c92b56c..3e853db: RUNNING (result recorded in the next update of this file).

**Known issues / residual risks:**
- A kill that lands inside the milliseconds of a record append could leave a truncated last line. `read_log` then fails closed and the line has to be repaired by hand.
- A power loss can leave a PID-less stale record lock, which still has to be removed manually (existing message).
- Windows signal and priority behaviour: UNKNOWN — requires verification on the owner's machine. It is modelled on `atlas_supervisor` (CREATE_NEW_PROCESS_GROUP + CTRL_BREAK_EVENT), whose Windows tests skip here.

**Remaining work:**
- S3 criteria (needs Shadow data).
- EXP-002 report after 2026-10-16.
- Proposal for the owner (not implemented): progressive strategy research (each daily comparison tests a new horizon). It needs a compute and runtime measurement on the owner's machine first.

**Next exact action:** the owner pulls the branch and starts with `python -m tools.start_atlas`.
