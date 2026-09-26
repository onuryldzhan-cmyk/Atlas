# ATLAS CHECKPOINT — Dashboard package committed; real combined full-suite count

## Objective
Commit the already-built, already-tested AdminLTE dashboard package (Parts L
and M) that had been sitting uncommitted alongside the concurrently-completed
and already-committed PAPER realized-P&L / risk-accounting package (v4.82,
commits 5b670bc + 175f8c2). Write the dashboard package's own governance
successor record (v4.83), close the known-limitations gap the two packages
left on `observability/panel_sources.py`, and measure the real, combined
full-suite result now that both packages coexist in one working tree for the
first time (each had previously only been full-suite-tested in its own
isolated worktree, against different bases).

Classification: STANDARD (a scoped commit + additive governance record +
data-only text update + a test run; no new code paths, no architecture
change). Not CRITICAL: nothing in this task's own diff touches execution,
risk, capital, or migration code — the CRITICAL package it references was
already implemented, tested, audited, and closed under its own v4.82 gate.

## Completed
1. Verified `git status --short` matched exactly the dashboard package's
   uncommitted files, and that `core/execution_manager.py` and
   `core/risk_state_store.py` (the CRITICAL package's files) showed zero
   uncommitted changes — confirming that work was already safely committed
   and untouched by this session.
2. Added two entries to `observability/panel_sources.py`'s
   `KNOWN_LIMITATIONS` (data only, no panel logic changed):
   - `RISK-ACCOUNTING-RECOVERY-REBOOK-GAP-001` (crash-recovery does not
     re-book a recovered trade's realized P&L into risk accounting;
     registry v4.82 MEDIUM-1).
   - `RISK-EQUITY-UNREALIZED-DRAWDOWN-GAP-001` (risk-store equity only
     refreshes on a SELL commit or day rollover; an open position's
     unrealized drawdown is not monitored by the daily-loss/drawdown halts;
     registry v4.82 informational).
   Ran the dashboard's own test file first: 51 passed, unaffected (the
   existing test asserts a subset of ids with `<=`, not an exact set).
3. Committed the dashboard package as `fc04e2f` with exactly the file list
   from the task prompt: `.gitignore`, `core/market_loop.py`,
   `observability/panel_router.py`, `observability/panel_sources.py`,
   `templates/dashboard.html`, `templates/login.html`, `web_app.py`,
   `static/`, `tests/test_dashboard_adminlte_and_integrity_panels.py`, and
   its own checkpoint
   `checkpoints/20260926T105401Z_dashboard-adminlte-integrity-panels.md`.
4. Wrote `governance/current/ATLAS_MILESTONE_REGISTRY_v4.83.json` as an
   additive successor to v4.82: header fields (`schema_version`,
   `supersedes`, `registry_status`) updated, and one new top-level key
   `dashboard_adminlte_visual_redesign_and_content_panels_result` appended.
   Built by a scratch script that inserted the new member as text rather
   than round-tripping the whole document through `json.dump`, so every
   byte of the prior v4.82 history is preserved unchanged (a straight
   JSON-load-then-dump would have reformatted unrelated historical strings
   — e.g. mixed `\uXXXX`-escaped vs. literal-Unicode paths already present
   in the file — which would read as an edit to history, not an addition).
   Diffed against v4.82 to confirm only the 3 header lines and the new
   trailing block changed.
5. Ran the real, non-isolated full suite on this actual tree (both packages
   coexisting): **4600 passed / 1 failed / 0 skipped in 145.09s.**

## Files changed
- Committed in `fc04e2f` (dashboard package, per the task's exact list):
  `.gitignore`, `core/market_loop.py`, `observability/panel_router.py`,
  `observability/panel_sources.py`, `templates/dashboard.html`,
  `templates/login.html`, `web_app.py`,
  `static/vendor/VENDORED_ASSETS.json`,
  `static/vendor/adminlte-4.9.1/{adminlte.min.css,LICENSE,BOOTSTRAP_LICENSE}`,
  `tests/test_dashboard_adminlte_and_integrity_panels.py`,
  `checkpoints/20260926T105401Z_dashboard-adminlte-integrity-panels.md`.
- New, this checkpoint's own commit: `governance/current/ATLAS_MILESTONE_REGISTRY_v4.83.json`,
  this file.
- Not touched: `core/execution_manager.py`, `core/risk_state_store.py`, or
  anything else from the v4.82 CRITICAL package.

## Architecture decisions
- Governance registry successor records are built as an exact byte-preserving
  textual insert (header replace + trailing-block append) rather than a
  parse/reformat round trip, specifically to avoid an unintended
  reformatting diff across unrelated historical entries. This is a tooling
  choice for *this* session's record-writing, not a change to the registry's
  documented schema or convention.
- No dashboard code, panel logic, or execution/risk/capital code was touched
  in this session beyond the two data-only `KNOWN_LIMITATIONS` entries.

## STOP condition encountered — third, unrelated, uncommitted change appeared mid-session
While staging the two files this task's registry/checkpoint work produced,
`git status --short` showed `tools/reconcile_execution_authorities.py` as
modified. This file was **not** listed in the git-status snapshot taken at
the start of this session (which showed only the dashboard package's own
files), and this session never opened or edited it. Its diff implements the
MEDIUM-1 fix (booking a recovered SELL's realized P&L/equity into risk
accounting during crash recovery) and explicitly cites `registry v4.84` in
its own new docstring text — i.e. a concurrent session is actively building
the very fix this task's prompt said to defer ("Do not implement MEDIUM-1's
actual fix ... the fix is a separate task"), in this same working tree,
while this session was running.

This session did **not** touch, stage, revert, or commit that file — it
remains exactly as the concurrent session left it, unstaged, so as not to
destroy in-progress work that is not this session's to judge.
`core/execution_manager.py` and `core/risk_state_store.py` (the v4.82
CRITICAL package's own files) were re-checked and are still clean, so the
already-committed v4.82 package itself is unaffected.

**Consequence for the full-suite number below:** the "real combined tree"
run was executed after this drift appeared, so the measured tree was
actually dashboard + v4.82 + this third, unrelated, in-progress,
uncommitted change — not the clean two-package combination the task asked
to measure. The result reconciled exactly to the expected arithmetic
(4520 + 29 + 51 = 4600) with no unexplained new failures, which is evidence
the drifting file did not change any currently-collected test's outcome,
but it is not proof the combination the task asked for was measured in
isolation from it. **Decision required (owner):** whether this figure is
accepted as the real combined count, or whether it must be re-measured once
the concurrent session's file reaches a committed or reverted state.

## Tests
- `tests/test_dashboard_adminlte_and_integrity_panels.py`: 51 passed (run
  standalone immediately after the `KNOWN_LIMITATIONS` edit, before commit).
- Real, non-isolated full suite on the actual current tree at commit
  `fc04e2f` (both the dashboard package and the concurrently-committed
  v4.82 realized-P&L package present together for the first time; see the
  STOP condition above regarding a third, uncommitted, unrelated file
  present during this specific run):
  **4600 passed / 1 failed / 0 skipped in 145.09s (0:02:25).**
  - Failure: the pre-existing, accepted Group B2
    `tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports`
    (`atlas_finance/market_data/contracts.py` edges only — unchanged by
    this session).
  - No skip this run, unlike either package's prior isolated-worktree run:
    `tests/test_observability_artifact_freshness.py` did not hit its
    fresh-worktree skip condition because this real tree already has an
    `observability` test-results artifact.
  - Reconciliation: v4.81 baseline 4520 passed + 29 (v4.82's new risk-
    accounting tests) + 51 (this package's new dashboard tests) = 4600,
    exactly matching the observed passed count. This is the first time
    both packages' tests have actually run together in one process.

## Current state
- Dashboard package: committed (`fc04e2f`), governance-recorded (v4.83,
  this checkpoint's own commit).
- CRITICAL realized-P&L/equity package: unchanged, already committed
  (`5b670bc` + `175f8c2`, registry v4.82). Confirmed untouched by this
  session (`git status --short` on its two files showed nothing both
  before and after this session's work).
- Authority unchanged: `production_authority=NONE`, `live_authority=DENIED`,
  `autonomous_deployment_authority=DENIED`.
- Live instance verification: NOT_PERFORMED for both packages — requires an
  owner-started run.

## Known issues / risks
- **Unrelated in-progress uncommitted change observed at commit time:**
  `tools/reconcile_execution_authorities.py` is modified in the working tree
  (unstaged, left untouched by this session) — a MEDIUM-1 fix in progress,
  citing `registry v4.84`, evidently by a concurrent session. See the STOP
  condition recorded above. This is not this package's work and was not
  reverted, committed, or otherwise acted on.
- `KNOWN_LIMITATIONS` still contains a stale entry, `DAILY-LOSS-LIMIT-WIRING`,
  which states realized daily P&L is "not accumulated anywhere yet." As of
  `5b670bc` (registry v4.82) that is no longer accurate — realized P&L and
  equity are now wired. This entry was deliberately **not** modified in this
  session because doing so was outside the approved scope (add exactly the
  two named items). **CONFLICT:** Expected — the known-limitations list
  reflects current wiring state; Actual — `DAILY-LOSS-LIMIT-WIRING` predates
  and contradicts the now-committed v4.82 wiring; Evidence —
  `observability/panel_sources.py` KNOWN_LIMITATIONS entry `DAILY-LOSS-LIMIT-WIRING`
  vs. registry v4.82's `paper_realized_pnl_risk_accounting_and_halted_rollover_refusal_result`;
  Impact — the System Integrity panel shows an inaccurate limitation to the
  operator; Decision required (owner) — remove, rewrite, or explicitly
  supersede that entry in a follow-up change.
- All other risks/known-issues from the dashboard package's own checkpoint
  (`checkpoints/20260926T105401Z_dashboard-adminlte-integrity-panels.md`)
  are unchanged and still apply (rollover-refusal audit-event gap,
  4 MiB audit-scan window, static-limitations-list maintenance burden).

## Remaining work
- Owner decision on the stale `DAILY-LOSS-LIMIT-WIRING` entry (see CONFLICT
  above).
- Deferred improvements carried over unimplemented, per the dashboard
  package's own checkpoint: audit rollover refusals (CRITICAL, separate
  package); `templates/register.html`'s unused Tailwind CDN reference;
  optionally vendoring `adminlte.min.css.map`.
- MEDIUM-1's actual fix (crash-recovery re-booking realized P&L) — noted in
  the known-limitations text per this task's instructions, not implemented;
  remains a separate future package.

## Next exact action
Owner reviews `fc04e2f` and the v4.83 registry record; decides whether the
concurrent session's uncommitted `tools/reconcile_execution_authorities.py`
work should proceed, be coordinated with, or be checked before the
4600/1/0 combined figure above is treated as final; decides on the stale
`DAILY-LOSS-LIMIT-WIRING` entry; and prioritizes the deferred items above
against the roadmap.
