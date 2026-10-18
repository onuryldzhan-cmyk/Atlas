# Task 015 — Paper soak initiation: day-0 execution plan (registry v5.99; criteria additions of Task 016, registry v5.100)

Date: 2026-10-17. Phase 2 INVESTMENT ENGINE. Execution mode PAPER only, live authority DENIED. Nothing in this plan
changes trading behaviour, adds a venue, or moves anything up the Paper → Shadow ladder.

This plan turns the Task 014 soak plan (`docs/operations/TASK014_PAPER_VERIFICATION_2026-10-17.md` §3) into the steps
the owner runs. Where the two differ, the Task 014 document governs the criteria, **except** that the sheet in §1
(lines 5, 6 and 16–19, which the owner extended on 2026-10-17 after Task 014) supersedes the PASS and INCONCLUSIVE
rows of Task 014 §3, and line 19 adds a stop condition to Task 014's list of stop conditions; this document governs the order of steps.

## 0. Who does what

- **The soak runs on the owner's machine.** The agent's cloud environment has no access to Binance (per
  `docs/operations/OWNER_TERMINAL_TASKS.md`), so the agent cannot refresh the venue rules or start the run.
- **The agent's part** is this plan, the pre-registration sheet, the v5.99 and v5.100 records and the read-only report
  script `tools/soak_report.py` with its tests (§1, lines 11 and 16–19).
- **The owner's part** is confirming the agent's definitions of §1 lines 16–19 and the PASS-to-INCONCLUSIVE rule
  before day 0 (§2 step 1), the three day-0 lines of §1 (lines 1, 12 and 14), §2 (run) and the daily routine in §4.
- **FACT vs UNKNOWN.**
  - Commands marked *(verified here)* were dry-run by the agent in a throwaway state directory on Linux.
  - Commands marked *(owner's machine)* need Binance access, a running Atlas or Windows, and are UNKNOWN until the owner
    runs them. The PowerShell syntax is UNKNOWN for the same reason.
- **What the tools write.** No tool in this plan writes trading state (positions, cash, orders or the journals) except
  Atlas itself. The writes outside Atlas are:
  - `tools.bootstrap_financial_state` creates the three financial stores in a fresh state directory (step 3), and
    never overwrites one;
  - `tools/refresh_venue_instrument_rules.py` rewrites `config/instrument_rules.json` (step 5);
  - `python -m tools.incident_report detect` and the agent runner that `tools.start_atlas` starts beside Atlas append
    records under `governance/records/` **in the repository**, which makes the working tree dirty while the soak runs
    (see §2 step 1 and §4);
  - `tools/fetch_historical_market_data.py` (end of run, §7) fetches public 1h bars from Binance (no key, no order
    endpoint) and writes them to the market archive `market_data.sqlite3` in the market archive directory (by default
    `data/market_archive` in the repository, which git ignores); `soak_report` reads that file immutably and creates no
    side file;
  - the agent runner also writes under the state directory's `research/` folder (its heartbeat, usage ledger and
    research files, including `research/shadow/book_costs.csv`). Its `digital_twin` agent runs `tools/shadow_costs.py`
    (Shadow stage S1), which reads Binance's public order-book depth each cycle. It is observe-only: it sends no
    orders and changes nothing Atlas trades on. It does not make this soak a Shadow run.
  - Every other command here only reads and prints.

## 1. Pre-registration sheet

Criteria are fixed here, before day 0, and are not changed after seeing results. The owner approved the proposed
values on 2026-10-17 (Task 015 sign-off). Lines 1, 12 and 14 are filled in by the owner on day 0, in the evidence
record (§3); the run does not start until they have a value.

| # | Item | Value |
|---|---|---|
| 1 | Day 0 start (UTC date and time) | *owner, on day 0* (the time of §2 step 8) |
| 2 | Minimum duration | 21 days |
| 3 | Target closed trades | 100 |
| 4 | Hard cap | day 42 |
| 5 | PASS | ≥ 100 trades, E > 0, bootstrap 95 % lower bound of E > 0, **and** lines 16–18 |
| 6 | INCONCLUSIVE | E > 0 with lower bound ≤ 0; or 30–99 trades with E > 0; or the PASS conditions on E hold but one of lines 16–18 or the archive check is not met |
| 7 | FAIL | ≥ 30 trades and E ≤ 0 |
| 8 | INSUFFICIENT | < 30 trades |
| 9 | Optional minimum E% floor | none |
| 10 | EXP-002 "reference" group | the policy-floor group (owner confirmed 2026-10-17) |
| 11 | How E is computed | (a): `python -m tools.soak_report`, committed with this plan before day 0 |
| 12 | State directory | *owner, on day 0*; fresh and bootstrapped, e.g. `C:\AtlasState-soak` |
| 13 | Starting capital | the bootstrap default; *(verified here)* it creates `cash 10000.0` |
| 14 | Evidence folder (outside the state directory and the repository) | *owner, on day 0*, e.g. `C:\AtlasState-soak-evidence` |
| 15 | Day-28 venue-rule refresh if the run is still going | yes |
| 16 | Benchmark (owner decision 2026-10-17: a PASS must beat the basket) | for every closed trade, the equal-weight basket of the trade universe (the 20 coins in `config/instrument_rules.json`) held over the trade's own `[opened_at, closed_at]`; excess = the trade's gross return − the basket's return. PASS needs a mean excess > 0, its bootstrap 95 % lower bound > 0 **and** its day-block lower bound > 0 (line 17's method applied to the excess). BTC alone is shown, not graded. |
| 17 | Day-block bootstrap (owner decision 2026-10-17) | the bootstrap of line 5 repeated with whole UTC closing days resampled; its lower bound of E must be > 0 |
| 18 | Edge not from a few trades (owner decision 2026-10-17) | E without the 3 best trades must be > 0 |
| 19 | Drawdown stop (owner decision 2026-10-17) | realized net equity falls 10 % or more from its peak: stop (§6) |

Notes on the table:
- **Lines 16–19 (Task 016).** The owner chose the benchmark as a PASS condition, the robustness checks and the 10 %
  threshold on 2026-10-17. The agent chose their exact definitions, which the owner confirms before day 0 (§2 step 1):
  - the basket is the equal-weight mean over the trade universe, each coin's return taken over the trade's own
    window; the comparison is not circular (the same coin over the same window would only measure the costs);
  - **costs do not fully cancel.** Fees are on neither side (the trade side is gross of fees). The trade's gross
    return does contain the 5 bps adverse paper slippage on each fill, about 10 bps a round trip, which the basket's
    raw bar prices do not. The excess is therefore understated by about 0.1 percentage point per trade: a bias against
    a PASS (it covers slippage only; a PASS is evidence, not a safety guarantee), and the bar is stricter than "beat a
    passive basket". How large that is
    compared with the edge being looked for is UNKNOWN. The owner either accepts it at the §2 step 1 confirmation or
    asks for an equal slippage haircut on the basket (a code change, committed before day 0);
  - the benchmark is graded on the day-block bound as well, because trades closed on one day in correlated coins are
    not independent and a trade-level bootstrap alone would pass noise more often than 5 % of the time (the
    review 44's simulation under an assumed common daily shock: 16–29 % trade-level against 6–9 % day-block; nothing
    in the repository reproduces it, and whether real excesses cluster is UNKNOWN);
  - prices are the archived 1h bars, interpolated linearly inside the hour; a missing bar is never guessed, and any
    missing bar makes the benchmark UNAVAILABLE and a PASS impossible;
  - the day-block bootstrap uses the same seed and 10,000 resamples as line 5, resampling UTC closing days;
  - the drawdown is of **realized** net equity (starting capital plus net P&L in closing order); unrealized losses
    are not in it, so the `/api/portfolio` equity and limits card stay part of the daily look. `--capital` must be
    passed if line 13 is not the bootstrap default;
  - **inputs.** The criteria are constants. The report has three input options: `--capital` (only if line 13 is not
    the bootstrap default), `--instrument-rules` and `--market-archive` (not used in the soak: they would change the
    basket or the price source). The report prints them ("inputs in effect") and the evidence record saves the
    full command line of every report. A basket of fewer than 10 coins is refused;
  - **few closing days.** The day-block bound rests on the number of distinct closing days, which the report prints.
    With one closing day it equals E, with a few it is coarse. The verdict is only valid after line 2's minimum
    duration, which the report does not enforce;
  - **strictness.** A single missing hourly bar of any of the 20 coins inside any trade's window makes the benchmark
    UNAVAILABLE and a PASS impossible, deliberately. Before day 0 the owner can fetch recent weeks for the universe
    (`tools/fetch_historical_market_data.py`, §7 step 3 shows the form) and look for gaps, to decide whether a
    gap-tolerant rule is wanted; none exists.
- **Line 11: what `tools/soak_report.py` computes.**
  - The owner's formula: E = (sum of net profit after slippage and friction) / (total trades). That is the Task 014
    definition, the mean net P&L per closed trade.
  - Net P&L per trade = `gross_pnl` − recorded `entry_fees` − exit fee. The 5 bps slippage is already inside
    `gross_pnl`, because it is applied to the fill price. The exit fee is `PAPER_FEE_RATE_PER_SIDE` (0.1 %) of the
    exit notional `cost_quote + gross_pnl`, rounded up to 8 decimals, which is what paper execution books on a full
    close.
  - It reads the closed-position archive with the archive's own reader (`ClosedPositionArchiveStore.load_index`, the
    one Atlas uses at startup), so the same line format, sequence, retry and conflict rules apply.
  - E% is the mean of net P&L / `cost_quote`.
  - The lower bound is a one-sided 95 % percentile bootstrap: 10,000 resamples with seed 20261017, then the lower
    5 % quantile of their means.
  - The window: positions opened at or after `--start` (line 1) and closed before `--end`. Positions still open are
    listed and excluded.
  - These numbers are constants in the script, not options, so they cannot be changed per run.
  - An archive it cannot read as Atlas would, a financial state that is not readable JSON of the expected shape, or an
    unusable state directory is refused: it prints a `REFUSED:` line and exits 2, and computes nothing. The financial
    state is not read through Atlas's own loader, so a pending recovery marker in it is not flagged; startup and the
    agreement check catch that. A wrong `--start` or `--end` is a usage
    error, also exit 2, without a `REFUSED:` line.
  - **Limit, and its rule.** The archive keeps only the last leg of a position that was partly sold before its close.
    The script compares the archive's gross P&L with the account's realized gross P&L. When they differ, or there is
    no financial state to compare with, it prints a WARNING and the per-trade figures are incomplete: **a PASS is then
    reported as INCONCLUSIVE.** The rule can only lower a verdict, never raise one. In a fresh state directory the two
    are equal unless a partial sale happened. The check compares gross P&L only: partial legs whose gross sums to
    exactly zero are not detected, and a partial sale of a position still open at the end lowers a PASS although the
    window's trades are complete (conservative). (This rule was added by the agent after the owner's approval, on
    review 42's finding that the WARNING had no pre-registered consequence; the owner confirms or replaces it before
    day 0, §2 step 1.)
- **Line 10.**
  - The "policy floor" group in `tools/exp001_report.py` holds every attributed closed trade not tagged EXP-002,
    including EXP-001 admissions and trades from any period. A filtered reference would need a tool that does not
    exist; building one is a separate owner decision.
  - EXP-002 admits nothing since 2026-10-16 and has no part in this soak; line 10 only fixes how its own result is
    read.
- **Line 12.**
  - Use a sibling of the existing state root, not a folder inside it. `C:\AtlasState` is the owner's existing root
    (`docs/operations/RECOVERY_RUNBOOK.md`), and the runbook's rename-or-restore steps would carry a nested soak
    directory with it.
  - Alternative: the existing state directory can be reused with its starting balances recorded. Then `soak_report`
    still counts only positions opened at or after line 1, but the archive check in the Line 11 note warns whenever
    the older history differs from the archive, and a PASS is then not possible. A fresh directory is therefore the
    plan's choice.

## 2. Day -1 to day 0: commands, in order

Run in PowerShell, in the repository on the owner's machine (`Atlas-test`), with Atlas **stopped**. The venue-rule
refresh (step 5) must be at most 1 day before day 0.

1. **Update the code to the pinned base.** This plan, `tools/soak_report.py` with the Task 016 criteria, and the
   v5.99 and v5.100 records are on the branch once committed.
   - **Pre-condition:** the owner has confirmed, or replaced, (a) the PASS-to-INCONCLUSIVE rule in the §1 line 11
     note and (b) the exact definitions of §1 lines 16–19, including the slippage bias of the benchmark and the day-block
     grading. Both were written by the agent after the owner's approval of the sheet (the owner chose the benchmark, the
     checks and the 10 % threshold; the agent chose their definitions). A replacement is committed before this step;
     the confirmation is saved in the evidence record (§3).
   ```
   git status --short
   ```
   - It must print nothing. If it lists files under `governance/records/` (written by the agents or by
     `incident_report detect`), commit them first, as `docs/operations/OWNER_TERMINAL_TASKS.md` does.
   ```
   git fetch origin claude/exp001-on-owner-lineage
   git diff --name-only HEAD...origin/claude/exp001-on-owner-lineage
   git merge --no-edit origin/claude/exp001-on-owner-lineage
   git merge-base --is-ancestor 90ad404 HEAD; $LASTEXITCODE
   git log --oneline -1 -- tools/soak_report.py
   Select-String -Path tools/soak_report.py -SimpleMatch "DRAWDOWN_STOP_PCT", "MIN_BASKET_COINS"
   git log --oneline -1
   ```
   - Save the `git diff --name-only` output: it is what the merge brings in.
   - If the merge reports a conflict, run `git merge --abort` and stop: the start waits for the owner.
   - The `$LASTEXITCODE` line must print `0` (the Task 014 commit is in the history).
   - The `-- tools/soak_report.py` line must print the Task 016 commit (its message names Task 016), or a later
     commit to the script, and the `Select-String` line must find both names: sheet lines 11 and 16–19 require the
     script with the Task 016 criteria before day 0. A script without them (the Task 015 version) stops the start.
   - Record the last commit.

2. **Create and point at the soak state directory** (line 12). Do this in **every** console used during the soak.
   ```
   New-Item -ItemType Directory -Force C:\AtlasState-soak
   $env:ATLAS_STATE_DIRECTORY = "C:\AtlasState-soak"
   ```
   - Without the variable, tools fall back to the repository's `memory_data`, which may hold the old EXP-001/EXP-002
     archive.
   - **Only some tools print the root they read:** `bootstrap_financial_state`, `show_config`,
     `check_execution_authority_agreement`, `paper_position_report`, `exp001_report` and `soak_report` do.
     `reality_check` and `performance_report` do not, so a wrong console is silent there. §4 therefore starts every
     daily routine with a command that prints the root.

3. **Bootstrap the durable financial state** *(verified here, Linux paths)*. Startup is fail-closed on missing stores.
   ```
   python -m tools.bootstrap_financial_state --state-directory $env:ATLAS_STATE_DIRECTORY
   python -m tools.bootstrap_financial_state --state-directory $env:ATLAS_STATE_DIRECTORY --verify-only
   ```
   - The first run creates `risk_accounting_state.json`, `capital_reservations.json` and
     `execution_financial_state.json` and ends with `verdict: OK (exit 0)`.
   - The second run reports each store as `VALID_EXISTING` and ends with `verdict: OK (exit 0)`.
   - The tool never overwrites an existing store. A different capital would be `--total-capital`; line 13 uses the
     default.

4. **Check the configuration** *(verified here)*.
   ```
   python -m tools.show_config
   ```
   - Expect `execution_mode: PAPER`, `state_directory:` equal to line 12, `fill_model: LAST_PRICE`, and the last line
     `OK - configuration valid.` Anything else stops the start. `ATLAS_FILL_MODEL` must be unset or LAST_PRICE.
   - **`paper_confidence_experiment: True` is expected and inert.**
     - The only experiments in the code are EXP-001 (window ended 2026-10-12) and EXP-002 (ended 2026-10-16)
       (`PAPER_CONFIDENCE_EXPERIMENTS` in `core/risk_engine.py`).
     - Both admit nothing now, so no experiment is active. That is the "no other experiment is switched on"
       pre-condition of Task 014.

5. **Refresh the venue rules for the frozen coin list** *(owner's machine; needs Binance)*. Do not run
   `tools.select_universe`.
   ```
   python tools/refresh_venue_instrument_rules.py --symbols-file config/universe_selection.json
   git diff --stat config/instrument_rules.json
   ```
   - The tool refreshes every listed coin or refuses the whole refresh and changes nothing.
   - A refusal because a coin is not TRADING **stops the soak from starting**: the coin list is then a new decision
     for the owner.
   - A transient failure (network or HTTP error) may be retried.
   - Rules older than 30 days turn STALE, and a STALE status fails readiness.

6. **Commit and push the refreshed rules. This commit is the pinned commit under test.**
   ```
   git add config/instrument_rules.json
   git commit -m "Paper soak: venue rules refreshed for day 0"
   git push origin HEAD:claude/exp001-on-owner-lineage
   git rev-parse HEAD
   ```
   If the push is rejected because the branch moved, do not merge again here: push to a branch of its own with
   `git push origin HEAD:refs/heads/paper-soak-pinned` and record that the pinned commit lives there.

7. **Confirm the state agrees, and take the clean-tree evidence** *(verified here)*.
   ```
   python -m tools.check_execution_authority_agreement --state-dir $env:ATLAS_STATE_DIRECTORY
   git status --short
   ```
   - Expect `startup readiness: ready=True reason=CLEAN` and `OK - Atlas will pass the agreement check on this state.`
   - `git status --short` must print nothing. Save this now: it can only be clean before step 8.

8. **Start Atlas, supervised, with the agents.** Note the UTC time: it is line 1.
   ```
   python -m tools.start_atlas
   ```
   - This is the only launch used for the whole soak.
   - It runs `tools.start_atlas` → `atlas_supervisor` → the Atlas child, plus the agent runner.
   - `.\atlas.ps1 -Action Run` starts the child without the supervisor and is not used.
   - Leave this console open. Ctrl+C in it stops the whole stack.
   - **Read the startup lines in this console and copy the policy-manifest line into the evidence record.**
     - Expected: `Policy manifest MATCH (registry ..., proposal ..., owner approval ...)`.
     - If instead a CRITICAL line `Policy manifest <STATUS>: ... - BLOCK_NEW_RISK` appears, **stop**: new BUYs are
       refused while readiness stays 200, so the soak would yield nothing.
     - The Atlas child logs this line to its standard output at INFO level (`main.py`), and neither `tools.start_atlas`
       nor `atlas_supervisor` redirects the child's output, so it should appear in this console. Only the owner's run
       confirms it.

9. **Check readiness and status within 10 minutes, from a second console** (with the variable set).
   ```
   curl.exe -s -i http://127.0.0.1:8000/api/readiness
   curl.exe -s http://127.0.0.1:8000/api/status
   ```
   *(owner's machine)*. `http://127.0.0.1:8000/system` shows the same in a browser.
   - Expect HTTP 200 and `"ready":true` (the JSON is compact: no space after the colon).
   - The checks are `runtime`, `market_loop`, `market_data`, `execution` and `venue_rules`. Others appear only when
     they fail or are UNKNOWN.
   - A not-ready result in the first minutes, while the first cycles run, is read again after 5 minutes before it is
     treated as a failure.
   - Save both responses.

## 3. Day-0 evidence record (saved to the evidence folder, line 14)

Save these as dated text files, as early as possible after step 9 (trades may already have happened by then):
- sheet lines 1, 12 and 14 with their values, and this plan's commit (the rest of the sheet is fixed in §1);
- the owner's confirmation (or the committed replacement) of the PASS-to-INCONCLUSIVE rule and of §1 lines 16–19
  (§2 step 1);
- the `git diff --name-only` from step 1, the pinned commit hash (step 6) and the empty `git status --short` from
  step 7;
- the `show_config` output (step 4);
- the bootstrap output with the starting cash (step 3);
- the `instrument_rules.json` `retrieved_at` and its coin list;
- the startup `Policy manifest MATCH` line (step 8);
- the first readiness and status responses (step 9).

## 4. Daily routine (about 5 minutes; same console setup)

All of these only read and print. The tools were checked in the repository, `soak_report` also on archives written by
Atlas's own archive store and portfolio code; none was run here against a live runtime. Start with the first command:
it prints the state root, and the saved outputs are valid only if that root equals line 12. Replace `<line 1>` with
the day-0 start, e.g. `2026-10-18T09:30:00Z`.
```
python -m tools.paper_position_report --no-price
python -m tools.soak_report --start <line 1>
python -m tools.reality_check --json
python -m tools.performance_report
curl.exe -s -i http://127.0.0.1:8000/api/readiness
curl.exe -s http://127.0.0.1:8000/api/status
curl.exe -s http://127.0.0.1:8000/api/portfolio
```
- Save each day's outputs to the evidence folder as `day-NN-*.txt`, and optionally a screenshot of `/system`.
- **`soak_report` during the run is interim.** Its verdict line says so. The final verdict is computed once, at the
  end of the run (§7). Looking at interim figures does not change any criterion in §1.
- **`soak_report` exit codes:** 0 normal, 2 refused or a usage error, **3 a STOP CONDITION (realized drawdown of
  10 % or more, §6)**. Any other code (a crash) is reported to the owner as it stands. The command line of every
  report, with its output, goes into the evidence folder. During the run the benchmark line reads UNAVAILABLE until the bars are fetched at the end (§7);
  that is expected and only means no PASS can show yet. The drawdown, E, the lower bounds and the best-trades check
  need no market data.
- **A `soak_report` REFUSED (exit 2) or WARNING while Atlas runs is read again once, a minute later, before it is
  treated as real.** Atlas appends a closed position to the archive just before it saves the account, so a read in
  that moment can see one without the other. A REFUSED that stays is durable-state corruption (§6); a WARNING that
  stays is recorded.
- **`/api/readiness`, `/api/status` and `/api/portfolio` are saved every day.** Readiness shows only pass/fail
  checks. `/api/status` carries the counts the Task 014 criteria need:
  - the feed's `degradations`, `recoveries`, `last_degraded_at` and `last_recovered_at` (the Task 013 counters, which
    reset when the process restarts, so the daily file and the drill snapshots are the history);
  - the contract rejections by reason (`decision_contract`, present only after a first rejection).
  - `/api/portfolio` carries the `limits` card (daily limit, realized loss today, percentage used).
- `python -m tools.performance_report` exits with an error ("no closed-position archive") until the first trade
  closes. That is expected in the first days.
- A feed found DEGRADED with `last_degraded_at` more than 30 minutes before the check and no later
  `last_recovered_at` is a reliability FAIL (Task 014 §3).
- Every `DECISION_CONTRACT_REJECTED` reason in `/api/status` is reviewed (Task 014 §3).
- Any failing or UNKNOWN readiness check is investigated the same day. `python -m tools.incident_report detect`
  records it as an incident (append-only, in the repository's `governance/records/`).
- **Daily stop-event check** *(owner's machine)*:
  ```
  Select-String -Path $env:ATLAS_STATE_DIRECTORY\audit\atlas_audit_events.jsonl -Pattern "DAILY_LOSS_LIMIT_BREACHED|LIVE_DISABLED|LIVE_EXECUTION_BLOCKED|BLOCK_NEW_RISK"
  ```
  - No match is expected. The file appears with the first audit event.
  - `DAILY_LOSS_LIMIT_BREACHED` is the RiskEngine's daily-loss rejection code. It is written only when a BUY reaches
    the RiskEngine and is refused, so a day with no attempted BUY leaves no trace even past the limit; the `limits`
    card in `/api/portfolio` shows the loss itself.
  - `BLOCK_NEW_RISK` marks a BUY refused because of a policy-manifest mismatch or unhealthy audit persistence (code
    reading of `core/execution_manager.py`; the agent has not run this path against a live runtime).
  - Whether the two LIVE events are written to the audit file is UNKNOWN, so also watch the Atlas console for
    `LIVE execution requested but disabled`.
  - **Detection lag.** The RiskEngine enforces the daily-loss limit at once, by refusing new BUYs. This check, which
    decides whether the soak stops, runs once a day, so a stop can come up to a day after the event.
- **Records.** Commit `governance/records/` now and then, as `OWNER_TERMINAL_TASKS.md` does, so the tree stays clean
  for the day-28 steps.

## 5. Calendar (day numbers count from the line 1 start)

| Day | What |
|---|---|
| 0 | steps 1–9, evidence record |
| 1–2 | daily routine only |
| 3 | restart drill A |
| 7 | drill B: the same as A. It runs on day 7 whether or not a position is open. If none is open, it is recorded as a drill without an open position, and one more drill B runs on the first later day with an open position, no later than day 13. If no position is open on any day up to day 13, the open-position drill is recorded as UNMET; the soak continues, and the UNMET is reported with the verdict |
| 10 | drill C |
| 14 | drill D |
| 21 | earliest end, if 100 closed trades have been reached |
| 28 | if the run has not ended: the day-28 refresh and restart below; it counts as a drill |
| 42 | hard cap |

### Drills A, B, C, D

**Before the drill**, save, and note the UTC time (the "before" time):
```
curl.exe -s http://127.0.0.1:8000/api/portfolio
curl.exe -s http://127.0.0.1:8000/api/status
curl.exe -s -i http://127.0.0.1:8000/api/readiness
python -m tools.paper_position_report --no-price
```
- `/api/portfolio` is the runtime's own view of cash and positions. `paper_position_report` reads the durable file.
  `--no-price` skips the live price lookup, which makes a public network call.
- `/api/status` is saved because the restart resets its feed and contract counters.
- `/api/portfolio` rounds money to 0.01; the durable file has full precision.

**The drill:**
- **A and B:** Ctrl+C in the `tools.start_atlas` console. When the stack has stopped, save the durable state as it
  was left (the "after exit" read):
  ```
  python -m tools.paper_position_report --no-price
  Copy-Item $env:ATLAS_STATE_DIRECTORY\execution_financial_state.json <evidence folder>\day-NN-after-exit-financial-state.json
  ```
  Then `python -m tools.start_atlas`.
- **C:** end the python process whose command line runs `atlas_service.py` (not `atlas_supervisor` or
  `tools.start_atlas`; a virtual-environment launcher may show two). Note the UTC time of the kill. The supervisor
  restarts it after a 5-second backoff, so there is no window for an "after exit" read: run the two commands above
  at once after the restart instead, and treat any journal commit after the kill time as explained below.
- **D:** at time T0 turn the network off. At T0 + 1 min press Ctrl+C in the `tools.start_atlas` console, then take the
  "after exit" read as in A. At T0 + 2 min run `python -m tools.start_atlas` (still offline; Atlas is not ready, which
  is expected). At T0 + 5 min turn the network back on. The "ready within 10 minutes" clock below starts at T0 + 5
  (this plan's reading of Task 014, which says only "a restart during a feed outage").
  - **UNKNOWN:** how the Atlas child behaves when started with no network has not been tested. If it exits at
    startup, the supervisor retries with growing backoff and may give up.
  - If the console shows the supervisor has given up, record it, run `python -m tools.start_atlas` again with the
    network on, and record the drill's readiness criterion as not met. Whether that stops the soak is the owner's
    decision; it is not one of the pre-registered stop conditions in §6.

**After the restart**, once readiness answers, save the first `/api/portfolio` and the startup `Policy manifest` line,
then:
1. **Recovery matches the durable state (Task 014 §3).** Compare the "after exit" read with the first `/api/portfolio`
   after the restart, before any new commit:
   - the same open positions, with the same quantity and cost;
   - the same cash, to the cent;
   - the same realized net P&L: `realized_gross_pnl` − `fees` in the saved financial-state file, to the cent.
   - Any difference must be a fill the journal shows committed after the "after exit" read (for drill C, after the
     kill); item 3 lists those. An unexplained difference is a FAIL.
2. **Agreement check:** `python -m tools.check_execution_authority_agreement --state-dir $env:ATLAS_STATE_DIRECTORY`
   expects `ready=True reason=CLEAN`. For drill C, run it right after the restart.
3. **No duplicate order, and the commits since a time** *(owner's machine; tested here on a synthetic journal)*. Copy
   the block exactly as below, starting at column 0, and replace the time on the last line with the "after exit" read
   time (drill C: the kill time), in UTC with the trailing `Z`.

```
@'
import collections, datetime, json, os, sys
since = datetime.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
path = os.path.join(os.environ["ATLAS_STATE_DIRECTORY"], "execution_transaction_journal.jsonl")
counts = collections.Counter()
later = []
with open(path, encoding="utf-8") as handle:
    for line in handle:
        if line.strip():
            event = json.loads(line)
            if event.get("state") == "COMMITTED":
                counts[event["request_id"]] += 1
                stamp = (event.get("entry") or {}).get("updated_at")
                if stamp and datetime.datetime.fromisoformat(stamp) > since:
                    later.append((stamp, event["request_id"]))
duplicates = sorted(request for request, count in counts.items() if count > 1)
print(f"COMMITTED request_ids: {len(counts)}; committed more than once: {duplicates or 'none'}")
print(f"committed after {sys.argv[1]}: {sorted(later) or 'none'}")
'@ | python - 2026-10-21T09:00:00Z
```

   - Expect `committed more than once: none`. The journal is an append log with one event per transition, so a
     request_id appears several times by design; only more than one COMMITTED counts.
   - The second line lists the fills that may explain a difference in item 1. A COMMITTED event carries its time in
     `entry.updated_at`; a PREPARED event carries only `prepared_at`.
4. **Readiness** is ready again within 10 minutes (proposed in Task 014).
5. **Open positions are still managed and their exits still route (Task 014 §3).**
   - Every position in the "after exit" read is in the first `/api/portfolio` after the restart (item 1).
   - At each later daily routine, each such position is either still listed by `paper_position_report` or has a row in
     the closed-position archive with `closed_at` after the restart. `soak_report` prints only counts; to see the row,
     search the archive for the position id from the "after exit" read:
     `Select-String -Path $env:ATLAS_STATE_DIRECTORY\execution_closed_positions.jsonl -SimpleMatch "<position_id>"`.
   - A position that is neither listed nor archived is a FAIL.
   - An exit is observable only when one happens. If a position held across the drill is still open at the end of the
     run, the exit-routing check for that drill is recorded as NOT EXERCISED, not as a PASS.

Any loss, duplication or unrecovered state is a FAIL: stop the soak and follow `docs/operations/RECOVERY_RUNBOOK.md`.

### Day 28 (if the run has not ended)

1. Take the "before the drill" snapshots, then stop with Ctrl+C and take the "after exit" read. Atlas must be stopped
   for the refresh.
2. Make the tree clean: commit `governance/records/` if it is dirty.
3. **Do not pull new code into the running soak.** Fetch and look first:
   ```
   git fetch origin claude/exp001-on-owner-lineage
   git diff --name-only HEAD...origin/claude/exp001-on-owner-lineage
   ```
   - Save the output; it lists, in full, every path the branch changed since the pinned lineage. Merge
     (`git merge --no-edit origin/claude/exp001-on-owner-lineage`) only if every listed path is under
     `governance/records/`, `docs/` or `checkpoints/`. Not the rest of `governance/`: the runtime reads
     `governance/policy/` and a registry under `governance/current/` (`core/policy_manifest.py`).
   - If the merge reports a conflict, run `git merge --abort` and treat it as "do not merge".
   - Otherwise do not merge. The refresh is committed on the pinned lineage and, in step 6, pushed with
     `git push origin HEAD:refs/heads/paper-soak-pinned`.
4. Run step 5. Then:
   - **Refresh succeeded:** run step 6 (a second pinned commit; the evidence now names both commits, the new
     `retrieved_at` and the coin list), then steps 7, 8 and 9, then the "after the restart" checks above.
   - **Refresh refused:** do not stop the run. Run steps 7, 8 and 9 on the **old** rules, then the "after the restart"
     checks. The run continues until the day before the day-0 rules turn 30 days old (their `retrieved_at` plus
     30 days), and then ends with the end-of-run procedure (§7). The verdict uses the trades closed by then.

## 6. Stop conditions

Stop with Ctrl+C in the `tools.start_atlas` console and do not restart until the owner decides. Where each is seen:

| Condition | Where it is seen |
|---|---|
| execution halt, or a required recovery | readiness check `execution` fails; `/system` engine row |
| policy manifest mismatch | the startup line (`BLOCK_NEW_RISK`, CRITICAL), checked at every start and restart, including every drill; a refused BUY shows `BLOCK_NEW_RISK` in the daily audit-file search |
| any `LIVE_DISABLED` / `LIVE_EXECUTION_BLOCKED` event | the daily audit-file search and the console (§4) |
| durable-state corruption | startup refuses (fail-closed), the agreement check at drills, readiness `execution`, a `soak_report` REFUSED that stays on a second read (§4) |
| daily loss beyond the RiskEngine limit (`max_daily_loss_pct = 0.05`) | `DAILY_LOSS_LIMIT_BREACHED` in the audit file; the `/api/portfolio` limits card (both daily, see §4 on the lag) |
| realized drawdown of 10 % or more from the equity peak (§1 line 19) | `soak_report` prints `STOP CONDITION` and exits 3, at the daily run (unrealized losses are in `/api/portfolio`, not in this figure) |
| refused venue-rule refresh at step 5 | the soak does not start (a refusal on day 28 does not stop the run; see above) |

## 7. End of run

1. **Before stopping,** save the final `/api/readiness`, `/api/status`, `/api/portfolio`, `performance_report` and
   `reality_check` outputs: the web server stops with Atlas.
2. Stop with Ctrl+C. Note the UTC time: it is the end.
3. Fetch the benchmark bars for the whole run (public data, no key; the owner's machine, with Binance access). Wait
   until the hour in which the last trade closed has ended (an hourly bar is archived only once closed). Run
   the report once; with the bars missing it prints the exact command, a `python tools/fetch_historical_market_data.py
   --symbols ... --start ... --end ...` line covering the trade universe, BTCUSDT and the trades' span. Run that line,
   then the report again. If it says the archive has an unfinished write-ahead log, let the fetch finish and run it
   again.
4. Compute E, E%, the lower bounds, the benchmark excess and the drawdown (§1 lines 11 and 16–19):
   ```
   python -m tools.soak_report --start <line 1> --end <end>
   ```
   It counts positions opened at or after line 1 and closed before the end, and lists the positions still open, which
   are excluded. With Atlas stopped the archive and the account cannot be caught mid-write, so a WARNING here stands:
   it is reported with the verdict, and a PASS is already reported as INCONCLUSIVE (§1, line 11 note).
5. State the verdict against §1 lines 5–9 and 16–19, using only the pre-registered rules. Also report the drills:
   any FAIL, UNMET or NOT EXERCISED item. A report that shows PASS and also `STOP CONDITION` (exit 3) is read as a
   run that hit its drawdown stop: both are reported, and the run ended at the stop, not by its plan.
6. Report to the owner. The soak result is evidence only. It moves nothing up the Paper → Shadow → Small Live ladder;
   that is a separate governed decision.

## 8. What this plan does not do

- It does not start the run, change any trading code or parameter, or switch anything off. `main.py` still has
  EXP-002 switched on, which is inert after its window; turning it off changes the manifest comparison and is its own
  decision.
- It adds no scheduler, sampler or drill harness. `tools/soak_report.py` only reads and prints.
- It changes no number in §1 after day 0.
