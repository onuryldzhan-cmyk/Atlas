# Task 014 — Paper environment long-term verification (registry v5.98)

Date: 2026-10-17. Phase 2 INVESTMENT ENGINE. Read-only work plus one paper-lock fix. Execution mode PAPER only, live
authority DENIED. No order path, strategy, risk, sizing or experiment parameter is changed by anything in this document.

This document has three parts:

1. The EXP-002 evaluation.
2. The paper-lock audit.
3. The soak plan (DRAFT — every number in it is an owner decision before the run starts).

## 1. EXP-002 evaluation

### The pre-registered criterion
GRANT-EXP002-PAPER-CONFIDENCE-EXPERIMENT (registry v5.85) and the design record
(`proposals/2026-10-01_sentiment_second_source_and_exp002_DESIGN.md`) fix the criterion in advance:

| Item | Value |
|---|---|
| Admission | MEDIUM-bucket BUYs admitted at a floor of 0.62 (policy 0.70) |
| Cap | at most 30 tagged admissions |
| Window | 2026-10-02T00:00Z .. 2026-10-16T00:00Z |
| Mode | PAPER only, funding sentiment OFF |
| Success measure | after 30 admissions or at window end, net expectancy after fees, "compared with the reference" (the record does not define the reference; see below) |
| Insufficient | fewer than 30 closed trades: INSUFFICIENT, and the floor goes back to policy |

### What can be evaluated here
**Result: UNKNOWN — the evidence is not in this repository.**

- **FACT:** `python -m tools.exp001_report --experiment EXP-002` is the existing read-only report. It attributes each
  closed position to its entry approval by exact identity and applies the 30-trade minimum.
- **FACT:** run in this container (state root `memory_data`), it reports 0 admissions and no closed trades.
- The paper runtime ran on the owner's machine (`Atlas-test`). Its state directory holds the evidence:
  - `execution_closed_positions` (the closed positions);
  - the execution audit events;
  - the experiment ledger;
  - the durable financial state.
- None of these files is tracked in git.

### What happens to EXP-002 now (FACT, from code)
- **Still switched on in code.** `main.py:544-545` still passes `paper_confidence_experiment=True, paper_confidence_experiment_id="EXP-002"`.
- **No admissions after expiry.** The experiment admits a BUY only while `starts_at <= now < ends_at` and fewer than 30
  admissions have been made (`core/risk_engine.py:202`). Since 2026-10-16T00:00Z it admits nothing, and MEDIUM BUYs
  need the policy floor 0.70 again. The existing test
  `tests/test_exp002_paper_confidence_experiment.py::test_below_floor_high_bucket_and_outside_window_keep_default_floors`
  covers this.
- **The manifest still matches.** The policy manifest (`core/policy_manifest.py`) has no expiry rule. The EXP-002
  parameters still match the manifest, so the check stays MATCH and does not block new risk.
- **Clean-up is a separate decision.** Turning the switch off in `main.py` is tidier, but it changes the manifest
  comparison (`paper_confidence_experiment` is a critical switch). So it needs its own governed manifest decision. It
  is not done here.

### How the owner obtains the verdict (read-only, on the machine that ran the paper runtime)
```
python -m tools.exp001_report --experiment EXP-002
```
The report never writes and takes no lock, so it is safe while Atlas runs. It prints, for each group (EXP-002, policy
floor, and unattributed when non-empty):
- trades and wins;
- the win rate with a Wilson 95 % interval, computed on wins after estimated fees;
- gross P&L, the recorded entry fees and the estimated fees;
- estimated net P&L;
- a verdict: INSUFFICIENT below 30 trades, otherwise PROFITABLE, NOT PROFITABLE or inconclusive.

Net expectancy per trade is the group's estimated net P&L divided by its trades.

**What the "policy floor" group contains:** every attributed closed trade whose approval is not tagged EXP-002
(`tools/exp001_report.group_closed`).
- That includes trades admitted under EXP-001 (floor 0.60, window 2026-09-28..2026-10-12).
- It includes every archived trade from any period, so also trades from before the 2026-10-01 slippage switch-on.
- A clean reference would be policy-floor approvals opened inside 2026-10-02..2026-10-16. No existing tool applies
  that filter. Whether to build one is an owner decision.

**INFERENCE, not pre-registered:** the "reference" is taken to be the policy-floor group.
- The design record (`proposals/2026-10-01_sentiment_second_source_and_exp002_DESIGN.md`) says only "compared with
  the reference", and the v5.85 grant does not define it.
- The report prints both groups but makes no comparison itself.
- The owner confirms or names the reference before the comparison is read.

**INFORMATIONAL:** the report's fee comment is out of date, but its figures are still sound.
- `tools/exp001_report.py` says "paper execution currently books zero fees".
- Since registry v5.23 (2026-09-28), `main.py` books `PAPER_FEE_RATE_PER_SIDE = 0.001` per side. Since the owner's
  2026-10-01 switch-on it also applies 5 bps of adverse slippage, inside the fill price.
- The verdict uses gross P&L minus an estimate of 0.1 % per side, which matches the booked fee rate, so the figures are
  still sound.
- Not changed here.

## 2. Paper-lock audit

The chain that keeps the runtime paper-only has five guards. Each was read and probed.

| # | Guard | Where | Behaviour | Existing tests |
|---|---|---|---|---|
| 1 | Fixed mode | `main.py:60` `EXECUTION_MODE = "PAPER"` | not configurable; no environment variable sets the mode | `tests/test_atlas_config.py::test_main_mode_is_paper_and_passes_its_own_validation` |
| 2 | Config validation | `core/atlas_config.py:118-123` `load_config` | refuses any mode but PAPER (`live_authority=DENIED`) and refuses unknown `ATLAS_*` variables | `tests/test_atlas_config.py::test_non_paper_mode_is_refused` and others |
| 3 | Policy manifest | `core/policy_manifest.py:338` `verify` | a manifest that is not PAPER with live disabled is LIVE_REFUSED; any runtime mismatch is BLOCK_NEW_RISK (new BUYs refused) | `tests/test_phase2_g1_policy_manifest.py` |
| 4 | Live authority | `core/execution_manager.py:684` | LIVE needs both mode LIVE and `live_execution_enabled`; `AtlasApplication` never passes that flag (default False), so a LIVE request is LIVE_DISABLED | `tests/test_block3_terminal_status_classification.py`, `tests/test_block6a_venue_rule_freshness.py`, `tests/test_block6b_venue_upper_bounds.py` |
| 5 | No live adapter | `core/execution_manager.py` (LIVE_NOT_IMPLEMENTED) | even with live authority, no adapter is configured, so nothing is dispatched | same |

`tools/check_execution_authority_agreement.py` is not a mode guard. It reports disagreements between the execution
journal and the idempotency store, which makes it a restart-integrity check. It is used as such in the soak plan.

### Finding L-1 (LOW, fixed): the application and its execution manager could report different modes
- **Where:** `core/application.py`, `self.execution_mode = str(execution_mode).upper()`.
- **Before the fix:** the application stored any mode string as given (upper-cased, not stripped), while
  ExecutionManager normalises the mode. A probe showed:
  - `'SHADOW'`: the application reported SHADOW while the manager ran PAPER;
  - `'Live '`: the application reported `'LIVE '` while the manager ran LIVE.
- **Impact:** a misreported mode in status and in the manifest comparison. Execution stayed paper or blocked in every
  case, because the manager maps unknown modes to PAPER and has no live authority.
- **Reachability:** only by building the application directly. `main.py` validates its fixed PAPER with
  `load_config` and passes that constant to the application.
- **Fix:**
  - the application strips the mode and upper-cases it, exactly as the manager does;
  - a mode other than PAPER or LIVE is refused at construction (`ValueError`);
  - LIVE stays constructible for tests and remains without authority or adapter.
  - Side effect for direct construction only: a padded "paper" (spaces around it) now counts as PAPER everywhere, so it also
    attaches the paper confidence experiment and the BOOK fill provider when those are configured. `main.py` is
    unaffected.
- **Tests:** `tests/test_task014_paper_locks.py` (9 cases):
  - unknown modes, including PAPER_SIMULATION, None and the empty string, are refused. The refusal happens before the
    state-directory lock is taken, and a correct start in the same directory still succeeds;
  - padded and mixed-case modes agree between the application and its manager;
  - live authority stays False.
- **Mutation check:** removing the refusal, the strip, or adding SHADOW to the allowed set is caught by the tests.

No other gap was found.

## 3. Soak plan (DRAFT — for owner approval before the run)

### Purpose
Verify over a long paper run that the paper runtime stays reliable and fail-closed, and measure its net expectancy
after fees. No parameter is tuned during the run. The criteria below are fixed before the run starts and are not
changed after seeing results.

### Pre-conditions (all checked and recorded before day 0)
- The commit under test is pinned; the run's evidence names it.
- `/api/readiness` is ready (HTTP 200).
- `python -m tools.show_config` shows `execution_mode: PAPER`.
- `python -m tools.check_execution_authority_agreement` reports no disagreement.
- The policy manifest check is MATCH.
- **State directory.** `ATLAS_STATE_DIRECTORY` is set to the same value in every console used during the soak, and
  `python -m tools.show_config` shows that `state_directory`. Tools fall back to `memory_data` without it, and each
  tool prints the root it read.
  - A fresh directory must first be created with `tools/bootstrap_financial_state.py`, with a recorded starting
    capital. Startup is fail-closed on missing stores.
- A fresh, dedicated paper state directory is used for the soak, or the existing one with its starting balances
  recorded. Only positions opened at or after day 0 and closed before the end count. Positions still open at the end
  are listed separately and excluded.
- EXP-002 is inactive (its window has ended). No other experiment is switched on.
- **Fill model LAST_PRICE.** `python -m tools.show_config` shows `fill_model: LAST_PRICE`, and `ATLAS_FILL_MODEL` is
  unset or LAST_PRICE.
  - BOOK is the repository's Shadow stage S2 (`core/atlas_config.py`; `main.py` comment "Shadow stage S2"). It fills
    from order-book VWAP without the 5 bps slippage.
  - The policy manifest accepts both values, so the MATCH pre-condition alone would not catch BOOK.
  - A soak on BOOK is not this plan.
- **Venue rules fresh for the whole run.**
  - Rules older than 30 days are STALE (`core/venue_rule_freshness.py` `DEFAULT_MAXIMUM_RULE_AGE_SECONDS`), and a
    STALE status fails readiness.
  - The tracked `config/instrument_rules.json` was retrieved 2026-09-29T13:14:05Z, so it goes stale on 2026-10-29.
  - Rules are fixed for the process lifetime, so a refresh needs a restart.
  - The rules file also defines the traded coins (`main.py` `trade_universe`).
  - **Day-0 refresh.** At most 1 day before day 0, with Atlas stopped, refresh the rules for the existing coin list:
    `python tools/refresh_venue_instrument_rules.py --symbols-file config/universe_selection.json`
    (`docs/operations/OWNER_TERMINAL_TASKS.md` §6a).
    - Do not re-run `tools.select_universe`, so the coin list stays frozen.
    - Commit the refreshed `config/instrument_rules.json`. That commit is the pinned commit under test. A day-28
      refresh is committed the same way, and the evidence names both commits.
    - Record the `retrieved_at` and the coin list.
  - **Retries.** A refresh that fails for a transient reason (network or HTTP error) may be retried within the same
    window. Only a refusal because a coin is not TRADING counts as refused below.
  - **If the day-0 refresh is refused.** The tool refuses the whole refresh, and changes nothing, if any coin is not
    TRADING. The soak does not start until the owner decides on the coin list; that is a new decision, outside this
    plan.
  - **Day-28 refresh.** If the run has not ended by day 28, there is one pre-registered refresh-and-restart that day,
    with the same command. It counts as a drill.
    - The coin list cannot change at that refresh, because the tool either refreshes every listed coin or refuses.
    - If it is refused, the run ends before the day-0 rules reach 30 days old (their `retrieved_at` plus 30 days, which
      is day 29 or 30). The verdict is then computed on the trades closed by that end.
- **Supervised launch.** Every start and restart in the soak uses `python -m tools.start_atlas`. It runs Atlas under
  `atlas_supervisor`'s restart policy, the launch named in `docs/operations/OWNER_TERMINAL_TASKS.md`.
  `.\atlas.ps1 -Action Run` starts `atlas_service.py` without the supervisor and is not used.
  - The process tree is `tools.start_atlas` → `atlas_supervisor` → the Atlas child (`atlas_service.py`), plus the
    agents.
  - Ctrl+C in the `tools.start_atlas` console stops the whole stack.

### Duration and sample (proposed; owner decision)

| Item | Proposed value | Reason |
|---|---|---|
| Minimum duration | 21 calendar days | covers three weekly cycles, including weekends |
| Target sample | 100 closed paper trades | at n = 100, a 95 % Wilson interval on a win rate near 50 % is about ±10 percentage points |
| End | the later of day 21 and 100 closed trades, capped at day 42 | |
| Below 30 closed trades at day 42 | INSUFFICIENT: no expectancy conclusion | same minimum as EXP-002 and `tools/exp001_report.py` |
| 30 to 99 closed trades at day 42 | expectancy reported, marked as below target | |

How many trades the runtime makes per day is UNKNOWN, because the EXP-002 evidence was not available here. The trade
target may therefore decide the length, not the 21 days.

### Expectancy criteria (proposed; owner decision)
- **Net P&L per trade:**
  - Take each closed position's `gross_pnl` from the durable closed-position archive. The 5 bps slippage is already
    inside it, because it is applied to the fill price.
  - Subtract the recorded `entry_fees`.
  - Subtract an estimated exit fee of 0.1 % of the exit notional, computed as `cost_quote + gross_pnl`, the formula
    `tools/exp001_report.estimated_fees` uses. The closed record's `base_quantity` is 0 after the close, so price ×
    quantity would give 0. The archive does not store exit fees (see
    `tools/exp001_report.py`), and 0.1 % matches the booked `PAPER_FEE_RATE_PER_SIDE`.
  - Nothing else is subtracted.
- **Expectancy E:** the mean net P&L per closed trade.
- **E%:** the mean of the per-trade ratios net P&L / `cost_quote`. This is the figure an owner floor in "% per trade"
  refers to.
- **Lower bound:** the one-sided 95 % lower confidence bound of E is a percentile bootstrap. Draw 10,000 resamples of
  the per-trade net P&L with replacement, using a recorded random seed, and take the 5th percentile of their means.

| Verdict | Condition |
|---|---|
| PASS (positive edge evidence) | at least 100 trades, E > 0, and the one-sided 95 % lower confidence bound of E > 0 |
| INCONCLUSIVE | E > 0 but the lower bound ≤ 0; or 30–99 trades with E > 0; or, when the owner set a floor, the PASS conditions hold but E% is below the floor |
| FAIL (no edge) | at least 30 trades and E ≤ 0 |
| INSUFFICIENT | fewer than 30 trades |

- **Floor:** the owner may add a "minimum EV threshold" above zero, for example a required net E of at least 0.05 %
  per trade. It is in addition to the lower-bound condition, never instead of it. Any such number is the owner's
  choice before the run, not derived here.
- **How E is computed.** No existing tool applies the day-0 filter or computes E%, the recorded-entry-fee net or the
  seeded bootstrap.
  - Before day 0, the owner either approves a small read-only script, fixed and committed with the plan, or chooses
    an existing report's figures instead.
  - That choice is part of the pre-registration and is not made after seeing the data.
- **Context only:** `python -m tools.performance_report` gives related figures by coin, holding time and hour. They
  are not the same figures: it covers the whole archive, uses estimated entry fees and has no day-0 filter.
- **Not graded:** the soak result is evidence for later decisions. It moves nothing up the Paper → Shadow ladder.

### Reliability criteria (from Tasks 010, 012 and 013)
- **Readiness.** `/api/readiness` is checked at least once a day and after every restart. Any failing or UNKNOWN check
  is investigated. The checks are `runtime`, `market_loop`, `market_data`, `execution`, `venue_rules`, and, when they
  appear, `position_risk_buckets`, `held_position_prices`, `order_lifecycle`, `decision_contract` and `market_feed`.
  `python -m tools.incident_report detect` records it as an incident (append-only).
- **Feed.** A DEGRADED feed must recover on its own (Task 010). A feed found DEGRADED, with `last_degraded_at` more
  than 30 minutes before the check and no later `last_recovered_at`, is a FAIL of the reliability criteria (proposed
  threshold).
  - It is checked only at the daily sample and after restarts.
  - A DEGRADED spell that starts and ends between two checks shows only as a raised degradation count. Its length is
    not measured.
- **Contract rejections.** Every DECISION_CONTRACT_REJECTED reason is reviewed (Task 012). A sustained
  DECISION_STALE or DECISION_FROM_FUTURE points to a clock problem.
- **Not persisted.** The Task 013 counters reset when the process restarts, so the daily /system snapshot is the
  record.
- **Paper locks.** The policy manifest stays MATCH and the mode stays PAPER throughout. Any LIVE_DISABLED or
  LIVE_EXECUTION_BLOCKED event is a FAIL.

### Restart resilience (proposed drill schedule)
**Drills.** Three controlled restarts and one unclean stop:

| Day | Drill |
|---|---|
| 3 | a controlled stop (Ctrl+C in the `tools.start_atlas` console), then `python -m tools.start_atlas` |
| 7 | the same, during an open position |
| 10 | an unclean stop of the Atlas child only: end the python process or processes whose command line runs `atlas_service.py` (a virtual-environment launcher may show two) (not `atlas_supervisor` or `tools.start_atlas`), so the supervisor restarts it |
| 14 | a restart during a feed outage (network disabled for 5 minutes), started with `python -m tools.start_atlas` |

**After each drill, verify:**
- cash, positions and realized P&L in the durable financial state, read after the old process has exited, equal what
  the restarted runtime recovers at startup, before any new commit. A fill that commits between taking a snapshot and
  stopping the process is reconciled through the transaction journal's commits; it is not a loss;
- `tools/check_execution_authority_agreement` reports no disagreement;
- no order is duplicated: in the transaction journal no `request_id` reaches COMMITTED more than once. The journal is
  an append log with one event per transition, so a request_id appears there several times by design.
- readiness is ready again within 10 minutes (proposed);
- open positions are still managed, and their exits still route.

**Outcome.** Any loss, duplication or unrecovered state is a FAIL. It stops the soak for diagnosis, using the
recovery runbook in `docs/operations/RECOVERY_RUNBOOK.md`.

### Stop conditions during the run
The run stops at once, with no restart until the owner decides, on any of these:
- an execution halt or a recovery that is required;
- a policy manifest mismatch;
- any live-path event;
- durable-state corruption;
- a daily loss beyond the existing RiskEngine limit (`max_daily_loss_pct = 0.05`).

### Outputs
- A daily snapshot: readiness, /system rows and `performance_report`.
- The drill records.
- The final `performance_report` and expectancy figures against the pre-registered criteria.
- A closing checkpoint.

### Out of scope
- Live trading, Shadow mode, or a step up the ladder.
- Changes to strategy, risk, sizing or experiments.
- New tooling. A daily sampler or an automated drill harness would each be a new owner decision.
