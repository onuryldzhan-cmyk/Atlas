# ATLAS CHECKPOINT

## Objective

Expand the operator dashboard (`/dashboard`, `web_app.py`) beyond its prior
BTCUSDT-only, single-decision view per the owner's 15 Eylül standing decision:
show all 5 symbols' decisions, a per-agent confidence/score breakdown,
execution/health status, and trade/performance history (win rate). Separately,
diagnose and fix the "Test Sonuçları" panel showing a stale hand-entered-looking
figure (1401 passed) instead of the real current count, and confirm the
"Governance (GOV-DRIFT)" panel's freshness.

This work followed a PLAN-MODE research phase (no files modified) whose
findings and proposed approach were written to
`C:\Users\HUAWEİ\.claude\plans\replicated-marinating-crystal.md` and approved
by the owner, followed by three explicit owner decisions on open questions
(trade-history data source, CI auto-regeneration, dashboard tile layout)
collected via AskUserQuestion, followed by CLASSIFY (CRITICAL — the new
trade-history endpoint reads live execution/capital state) and the full
CRITICAL-tier implementation gate.

## Completed

1. **`GET /api/signals`** (new, in `web_app.py`) — exposes all symbols'
   latest `MarketLoop.last_signals` (action/confidence/risk_level plus a
   fixed 5-row per-agent breakdown: technical/macro/sentiment/risk/momentum,
   each `{status: EVALUATED, action, score}` or `{status: EXCLUDED, reason}`).
   Reads `MarketLoop.status()["last_signals"]` (the loop's own lock-protected
   accessor), not the old lower-fidelity `brain.process()` path
   `/api/analysis` uses. Fails closed (503) when no runtime/market_loop is
   attached; never leaks metadata internals (fusion scores, reasoning text,
   memory diagnostics, candle identity) — enforced by an explicit allowlist
   and covered by a leak-marker test.

2. **`GET /api/trades`** (new, in `web_app.py`) — trade/performance history
   and win rate, sourced from the durable financial-truth authority
   (`ExecutionPortfolioFoundation.closed_archive`, a `ClosedPositionArchiveStore`
   of `gross_pnl`-per-closed-position JSONL records) per the owner's explicit
   choice over `PaperTrader.history` or the dead `AtlasMemoryCore`. A win is
   `gross_pnl > 0`; breakeven counts as a loss (documented, not silently
   excluded from the denominator). An empty archive reports
   `available: true` with zero trades (not an error). Every step from
   `load_index()` through building the response is inside one try/except so
   a malformed record or an unsortable `closed_at` fails the *whole* response
   closed (503) rather than silently mismatching aggregate totals against the
   listed trades. I/O failures (`OSError`/`UnicodeDecodeError`) are reported
   under a distinct `CLOSED_ARCHIVE_UNREADABLE` reason, separate from
   `CLOSED_ARCHIVE_CORRUPT` for genuine data-validation failures, per this
   project's established UNREADABLE-vs-CORRUPT convention. Only
   `symbol`/`gross_pnl`/`opened_at`/`closed_at` are published per trade —
   `position_id`, `cost_quote`, `entry_fees`, `average_entry_price`,
   `mark_price`, `version` are never exposed.

3. **`templates/dashboard.html`** rewritten: the old single-symbol decision
   tile is folded into a 5-symbol grid (per owner's explicit layout choice)
   fed by `/api/signals`, rendering every symbol the API actually returns
   (a hardcoded 5-symbol list is only the placeholder fallback for
   not-yet-processed symbols — it never limits which live symbols are
   shown, so an operator-reconfigured symbol set is never silently dropped).
   Added an Execution/Sağlık Durumu panel wired to existing `/api/health`
   fields (`execution_halted`, `execution_recovery_required`, `supervised`,
   `supervisor_epoch`, `supervisor_restart_count`, `market_data_stale`,
   `market_loop_thread_alive`) with correct true/false color polarity per
   field. Added a Performans (Win Rate) panel consuming `/api/trades`. The
   price/system-status tiles and the 200-line-capped trade log were kept.

4. **Test-results panel staleness (item D)** — root-caused: the panel code
   itself (`observability/panel_sources.py::read_test_results_panel`) was
   already live-reading `reports/observability/test_results.junit.xml` +
   `.meta.json` from disk on every request, not hardcoded. The artifact
   itself was stale (last generated manually at commit `45496d8`, showing
   1401 tests, while HEAD had moved to `dac9b72`). Fixed in two parts:
   (a) manually regenerated the artifact against current HEAD
   (`tools/generate_test_results_artifact.py`), now stamped at commit
   `dac9b72f1a57d30f4e79ad4ebb195ad7a4e3f401` with `2781 passed / 0 failed`
   and `commit_alignment: MATCH`; (b) per owner's explicit "yes, wire it into
   CI" decision, `.github/workflows/atlas_ci_cd.yml`'s test step now runs
   through the generator script (with explicit `$LASTEXITCODE` checking, since
   PowerShell does not fail a step on a nonzero external-command exit code by
   itself) and the two artifact files are uploaded as a downloadable CI
   artifact (`actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`
   `# v7.0.1`, SHA verified live against the GitHub API this session, not
   guessed). **Important caveat surfaced and documented in the workflow
   file itself**: `reports/observability/test_results.{junit.xml,meta.json}`
   are `.gitignore`d (lines 196-197), so nothing here is ever committed back
   to the repo — the CI upload makes the artifact auditable per-run, but does
   **not** by itself keep an operator's locally-running dashboard fresh. That
   still requires either a local periodic re-run of the generator script, or
   a separate future decision to un-ignore and commit these files (which
   needs `contents: write`, not granted in this workflow).

5. **Governance panel** — confirmed already live (`read_governance_panel()`
   resolves `governance/current/`'s head via the `supersedes` chain on every
   request; current head confirmed `ATLAS_MILESTONE_REGISTRY_v4.33.json`).
   No fix needed or made.

6. **Independent audit** (CRITICAL-gate step, run via the `code-review` skill
   at high effort across 3 agent-run finder angles — line-by-line, removed-
   behavior, cross-file tracer — since no git remote/upstream exists in this
   checkout for the skill's usual diff-range detection, so `git diff HEAD` on
   the three changed files plus the new test file was used as the review
   scope instead). Found and fixed 5 real issues before this checkpoint (see
   Architecture decisions and Known issues — all reported via ReportFindings
   with `outcome: fixed`):
   - a malformed trade record was silently excluded from aggregate totals
     but still listed in `recent_trades` (inconsistent, partially-fabricated
     figures) — fixed by moving all post-`load_index()` processing inside
     one try/except, so any such record now fails the whole response closed;
   - the `sorted()` call building `recent_trades` ran outside that
     try/except and could raise an uncaught `TypeError` on a non-comparable
     `closed_at` — fixed by the same restructuring;
   - a bare I/O failure reading the closed-position archive was reported
     under the same `CLOSED_ARCHIVE_CORRUPT` code as genuine data corruption
     — fixed with a distinct `CLOSED_ARCHIVE_UNREADABLE` reason;
   - the 5-symbol grid's symbol list was hardcoded and could silently drop
     a live signal if the operator's configured symbol set ever diverges
     from `MarketLoop.DEFAULT_SYMBOLS` — fixed by always rendering the union
     of the fallback placeholder list and whatever symbols `/api/signals`
     actually returns;
   - `updateSignalsGrid()`'s render step was not covered by the same
     try/catch as its fetch step (unlike the old `updateTerminal()`, which
     wrapped its entire body) — fixed by wrapping the whole function.

## Files changed

Per `git status --porcelain` and `git diff --stat` run at checkpoint time
(current branch `research/edge-validation`, HEAD `dac9b72f1a57d30f4e79ad4ebb195ad7a4e3f401`):

- Modified: `.github/workflows/atlas_ci_cd.yml` (+37/-6 lines)
- Modified: `templates/dashboard.html` (rewritten; +163/-48 net per diff stat)
- Modified: `web_app.py` (+440 lines net; two new routes, four new module-level
  constants, four new helper functions)
- New (untracked, not yet committed): `tests/test_web_app_signals_and_trades.py`
  (16 tests)
- Not modified by this session, listed here only because `git status` shows
  them as pre-existing untracked state from before this session started:
  `REM-001_CANONICAL_COMPONENT_MATRIX.json`,
  `checkpoints/20260915T163048Z_execution-authority-log-migration.md`,
  `governance/ATLAS_REM001_GATE1_DELIVERABLE1_AUTHORIZATION_v1.0.md`,
  `governance/ATLAS_REM001_GATE1_DELIVERABLE8_SUCCESSOR_REDEFINITION_v1.0.md`,
  `governance/current/ATLAS_MILESTONE_REGISTRY_v4.33.json`,
  `memory_data_backup_20260915/`, `paper_trades.json.legacy_backup_20260915`.
- `reports/observability/test_results.junit.xml` and
  `reports/observability/test_results.meta.json` were regenerated on disk
  twice this session (final state: 2781 passed, commit `dac9b72f...`,
  `MATCH`) but are `.gitignore`d and so do not appear in `git status`.
- No commit was made this session — all changes above are in the working tree.

## Architecture decisions

1. **New runtime-backed endpoints live in `web_app.py`, not
   `observability/panel_router.py`.** The existing `observability` router is
   deliberately file-based only (no runtime injection — "nothing is read
   here, only when a request arrives", per its own docstring) and has no
   mechanism to reach `application.state.atlas_runtime`. `/api/signals` and
   `/api/trades` need the live `market_loop`/`portfolio_foundation`
   attributes, so they follow the existing `/api/health`/`/api/analysis`
   pattern in `web_app.py` instead.
2. **`_resolve_attr(runtime, name)` added as a generalization of the
   existing `_resolve_brain`**, rather than adding two more bespoke
   resolvers — mirrors the existing `runtime.X` / `runtime.application.X`
   fallback exactly. Confirmed via cross-file trace this session that
   `AtlasApplication.market_loop` and `.portfolio_foundation` are plain
   `__init__`-assigned instance attributes (no property, no side effects).
3. **`/api/trades` reads `ExecutionPortfolioFoundation.closed_archive.load_index()`
   directly on every request**, not the foundation's private
   `_closed_by_position_id` (hydrated only at construction time) and not
   through `MarketLoop` — this matches the existing repository convention
   (see prior-session memory: financial state must come from the durable
   authorities directly, never through MarketLoop) and means trade history
   reflects the archive's true current contents even if
   `portfolio_foundation.ready` is `False` for an unrelated reason (a
   deliberate choice: history readability is orthogonal to live-trading
   readiness).
4. **Least-exposure allowlisting extended, not abandoned**, for the two new
   endpoints: `PUBLIC_SIGNAL_KEYS`, `PUBLIC_AGENT_KEYS`, `PUBLIC_TRADE_KEYS`
   follow the exact pattern already established by `PUBLIC_ANALYSIS_KEYS` /
   `PUBLIC_DECISION_KEYS` — publish only what the dashboard consumes, never
   the full internal shape, even where the fuller shape would technically be
   safe.
5. **CI wiring is deliberately narrower than "commit the artifact back"** —
   only what the owner's answered option described (add the junitxml/meta.json
   generation step). Auto-committing the regenerated files needs
   `contents: write` and a branch-commit policy that was never discussed;
   that is flagged as an open follow-on decision, not silently implemented
   and not silently skipped.
6. **`actions/upload-artifact` pinned by commit SHA** (matching this
   workflow's existing convention for every other action), verified live
   against `https://api.github.com/repos/actions/upload-artifact/git/refs/tags/v7.0.1`
   this session rather than guessed.

## Tests

All commands run this session, exact results:

- `python -m pytest tests/test_web_app_signals_and_trades.py -q --basetemp=C:/atlas_pytest_tmp`
  → initially `14 passed`; after the audit fixes added 2 more discriminating
  tests (I/O-vs-corrupt distinction, fail-closed-on-one-bad-record) →
  **`16 passed`** in the file's final state (verified in the combined run
  below).
- `python -m pytest tests/test_web_app_signals_and_trades.py tests/test_web_app_contract.py tests/test_web_app_runtime_response_safety.py tests/test_observability_panel.py tests/test_block2c_observability_contract.py -q --basetemp=C:/atlas_pytest_tmp`
  → **`69 passed`**, run twice (once before the audit fixes at `53+14=67`... —
  correction: the first combined run, before the two audit-added tests
  existed, was `14+53=67`... verified actual output was not re-checked
  numerically at that intermediate point; the authoritative final combined
  run after all fixes showed **`69 passed, 0 failed`**, matching
  `16 (this session's new file) + 53 (pre-existing web_app/observability
  suites, unchanged)`.
- `python tools/generate_test_results_artifact.py --basetemp C:/atlas_pytest_tmp`
  (the full `tests/` suite, run twice — once mid-session, once as the final
  post-audit-fix run): final run → **`2781 passed, 0 failed`**, exit code 0,
  stamped at commit `dac9b72f1a57d30f4e79ad4ebb195ad7a4e3f401` (current HEAD
  — `commit_alignment` will report `MATCH`). `2781 = 2765` (owner-reported
  real baseline before this session) `+ 16` (this session's new test file).
- Frontend verified in the Claude Code built-in browser pane against a
  throwaway local server (`fastapi`/`uvicorn`, a fake runtime object — no
  `AtlasApplication`, no real `state_directory`, nothing under
  `memory_data/` touched) both before and after the audit fixes: all 5
  panels render, agent EVALUATED/EXCLUDED rows are legible, `/api/health`
  boolean polarity coloring is correct after the fix, and after the final
  fix pass the live test-results panel (reading the real, just-regenerated
  repository artifact through the throwaway server) showed
  `2779 passed / 0 failed / 2779 total` / `commit: MATCH` — confirmed
  visually, not just via the JSON test assertions. No console errors
  (`read_console_messages(onlyErrors=true)` → none).
- `python -m py_compile web_app.py` → `COMPILE_OK`, run twice (once after
  the initial implementation, once after the audit fixes).
- `.github/workflows/atlas_ci_cd.yml` YAML-validated with
  `python -c "import yaml; yaml.safe_load(...)"` → `YAML_OK`, run twice (once
  per edit to that file).

## Current state

- All three modified files (`web_app.py`, `templates/dashboard.html`,
  `.github/workflows/atlas_ci_cd.yml`) and the new test file are in the
  working tree, **uncommitted**.
- `reports/observability/test_results.junit.xml` / `.meta.json` on disk
  reflect the final post-audit-fix suite run (`2781 passed`, HEAD commit,
  `MATCH`) but are gitignored and will not appear in any commit.
- The dashboard has not been exercised against a real, running
  `AtlasApplication`/`atlas_service.py` process this session — only against
  fakes and the throwaway preview server. Whether Atlas is currently running
  on the owner's machine, and if so what its live `/api/signals`/`/api/trades`
  responses actually look like against real market/execution state, is
  **UNKNOWN — requires verification** (out of scope to start/stop/touch the
  running process per the original PLAN-MODE brief's explicit
  out-of-scope list, which this implementation phase continued to respect).
- `portfolio_foundation.ready` on any real running instance —
  **UNKNOWN — requires verification**; the last recorded evidence (from
  `checkpoints/20260915T163048Z_execution-authority-log-migration.md`) was
  that `memory_data/execution_financial_state.json` did not exist, meaning
  `/api/trades` would currently report `available: true` with `total_trades: 0`
  in practice (an empty/missing archive is a legitimate, non-error empty
  state per this endpoint's design) rather than an error — but this was not
  re-verified against the current real filesystem state this session.

## Known issues

- None outstanding from the independent audit — all 5 findings from the
  `code-review` skill run were fixed and re-tested this session (see
  Completed item 6). No CONFIRMED or PLAUSIBLE finding was left unresolved.
- The `code-review` skill's usual `git diff origin/HEAD...` / `@{upstream}`
  diff-detection failed outright (no remote configured in this checkout,
  confirmed via `git remote -v` returning nothing) and had to be worked
  around by manually generating `git diff HEAD` for the 3 changed files.
  This is an environment/tooling gap, not a defect in this change, but a
  future session running `/code-review` or `security-review` in this exact
  checkout will hit the same failure unless a remote is configured.
- `tests/test_web_app_contract.py` was found (not modified) to contain a
  pre-existing, unrelated defect: the entire block of `FakeBrain`/`FakeRuntime`
  classes and 4 test functions (lines ~146-285) is duplicated verbatim later
  in the same file (~287-426) — dead, redundant code, not a functional bug
  (Python redefinition just shadows the earlier copy with an identical body).
  Out of scope for this task per CLAUDE.md's "report as Deferred Improvement,
  never implement on the spot" rule — flagged here, not fixed.

## Risks

- **CI workflow change is uncommitted.** `.github/workflows/atlas_ci_cd.yml`
  was edited and YAML-validated locally but has never actually run inside
  GitHub Actions (no push/PR has triggered it this session) — the
  `$LASTEXITCODE` failure-propagation logic and the `actions/upload-artifact`
  step are validated by direct code reading and YAML parsing, not by an
  actual CI run. Recommend the first real CI run after this lands be watched
  closely.
- **The CI change does not solve the operational staleness problem it was
  meant to address**, per the `.gitignore` discovery in Completed item 4 —
  this is a real, not-yet-closed gap between the owner's stated goal ("so
  the panel never goes stale again") and what was actually approved/wired.
  Flagged explicitly for owner decision, not silently resolved either way.
- **`/api/trades`'s empty-archive behavior was chosen deliberately** (per
  owner's approved option "ClosedPositionArchiveStore ... with a graceful
  'insufficient data' empty state") but has not been visually verified
  against a genuinely empty real archive — only against a fake empty index
  in a unit test. The rendered panel text for zero trades
  (`toplam işlem: 0`, `win rate: n/a`) was confirmed via one of the 16 new
  tests' JSON assertions, not via a browser screenshot of that specific
  state.

## Remaining work

1. Commit these changes (currently untouched per this session's scope — no
   commit was requested).
2. Owner decision needed: how (if at all) to actually keep the *live,
   locally-running* dashboard's test-results panel fresh, given
   `reports/observability/test_results.*` is gitignored and CI cannot reach
   an operator's local filesystem. Candidate options not yet decided: a local
   scheduled task re-running `tools/generate_test_results_artifact.py`
   periodically on the operator's machine, or un-gitignoring + committing
   these files via a CI step with `contents: write` (a bigger decision, not
   part of what was approved this session).
3. Verify against a real running `AtlasApplication`/`atlas_service.py`
   process (when the owner next runs one) that `/api/signals` and
   `/api/trades` behave as designed against genuine live market/execution
   state, not just fakes — in particular confirm `portfolio_foundation.ready`
   and whether the closed-position archive is currently empty or populated.
4. First real GitHub Actions run of the modified `atlas_ci_cd.yml` should be
   watched to confirm the new test step and artifact upload behave as
   designed.
5. Deferred, out of scope: the duplicated dead code block in
   `tests/test_web_app_contract.py` (Known issues).

## Next exact action

Report this checkpoint's summary to the owner (objective met: all 4
owner-approved dashboard additions implemented and tested; both stale-panel
root causes found and fixed; independent audit findings fixed and re-tested;
2781/2781 full suite passing) and surface the two flagged open decisions
(CI-vs-local staleness gap; whether/when to commit) for explicit owner
direction before any commit or further action is taken.
