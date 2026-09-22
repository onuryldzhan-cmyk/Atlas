# ATLAS CHECKPOINT

Successor to `checkpoints/20260917T103347Z_dashboard-multisymbol-expansion.md`,
which is left untouched per the additive convention. That checkpoint closed at
"working tree, uncommitted, two open decisions". This one records what happened
after it: the freshness-hook implementation (Step 1), live verification against
the owner's running instance (Step 2), and the two commits that closed the
work stream (Step 3).

## Objective

Close out the dashboard-expansion work stream by (1) solving the test-results
panel staleness at its actual source rather than relying on someone
remembering to run a script, (2) verifying the new dashboard against a real
running Atlas instance rather than only against fakes and a throwaway preview
server — the explicit "Remaining work" item 3 of the predecessor checkpoint —
and (3) committing the result.

## Completed

### Step 1 — observability artifact freshness hook

**Problem restated from the predecessor:** the dashboard's "Test Sonuçları"
panel reads `reports/observability/test_results.junit.xml` plus its
`.meta.json` provenance sidecar live from disk on every request. Nothing ever
refreshed those files except a manual run of
`tools/generate_test_results_artifact.py`, so the panel sat four commits stale
at 1401 tests. CI cannot close this: it has no access to the operator's local
filesystem, and both files are `.gitignore`d by design (lines 196-197).

**Design — a root `conftest.py` hook, refreshing the artifact from the runs
that already happen.** The hook is 323 lines in `conftest.py` and has four
parts:

1. **`pytest_configure` (`tryfirst`)** decides eligibility and, when eligible,
   points pytest's own `--junitxml` machinery at a temporary file
   (`reports/observability/.test_results.junit.xml.partial`) beside the real
   artifact. `tryfirst` is required, not cosmetic: pytest's junitxml plugin
   reads `config.option.xmlpath` in its *own* `pytest_configure` to decide
   whether to register its `LogXML` reporter, so setting it afterwards would
   silently do nothing. The temp file lives in the artifact's own directory —
   therefore the same filesystem — so promotion is a single atomic
   `os.replace`, never a copy.
2. **`pytest_deselected`** accumulates deselected item counts into the
   config stash, so a run that lost items to a plugin's deselection hook
   after collection cannot publish.
3. **`pytest_sessionfinish` (`trylast`)** promotes the temp file over the real
   artifact or discards it. `trylast` is required so pytest's own
   `LogXML.pytest_sessionfinish` has already finished writing the temp file.
4. **`_publish`** does the `os.replace` and then stamps the provenance sidecar
   by calling `tools/generate_test_results_artifact.py`'s own
   `write_meta_sidecar`, which was **extracted into an importable function**
   by this change rather than duplicated. Both that import and
   `observability.panel_sources` are imported *inside* `_publish`, not at
   module scope, because `conftest.py` is imported for every pytest run in
   this repository and a problem in either module must not be able to break
   collection.

**The risk the design is actually built around** is a narrow run publishing a
misleadingly low count as if it were the whole suite. Two separate gates
address it:

- **Eligibility, decided before the run** (`is_full_suite_invocation`), from
  pytest's *parsed* options — never argv string matching, so `-k x` and
  `-k=x`, `--junitxml` and its `--junit-xml` alias, and every other spelling
  collapse to the same value. It stands the hook down for: an explicit
  caller-supplied `--junitxml` (which includes
  `tools/generate_test_results_artifact.py`'s own subprocess run — the hook
  never fights the script), an xdist worker (only the controller sees the
  whole suite), `--collect-only`, and any of `-k` / `-m` / `--deselect` /
  `--lf` / `--sw`. It publishes only when either no path args were given (so
  pytest fell back to the `testpaths` ini) or the given paths are exactly
  `testpaths`. `--ff` / `--nf` are deliberately *not* disqualifying: they
  reorder the suite but still run all of it.
- **Publishability, re-checked after the run** (`is_publishable_result`),
  because `-x` / `--maxfail` only *might* truncate and whether they actually
  did is not knowable up front. A session stopped early
  (`session.shouldstop` / `shouldfail`), any deselected items, or an exit
  status outside `{0, 1}` blocks publication. Exit status 1 **is**
  publishable — a red suite is exactly what the panel should show — while 2
  (interrupted), 3 (internal error), 4 (usage error) and 5 (no tests
  collected) are not a trustworthy picture of the suite.

**Failure isolation is total and deliberate.** Every hook body is wrapped in
`try/except Exception: pass`, and the temp file is removed in a `finally`. The
reasoning is recorded in the code: a stale artifact is a cosmetic dashboard
problem, whereas an exception raised from `pytest_sessionfinish` is an
INTERNALERROR that would report a green suite as failed. The stash write also
deliberately happens *before* `config.option.xmlpath` is redirected, so a
failure in between can never leave a temp file that `sessionfinish` has no
record of and therefore never cleans up.

**`is_full_suite_invocation` and `is_publishable_result` take plain values
rather than a `Config`** specifically so the decision is exhaustively testable
without constructing a pytest session, and so every input is visible in one
signature.

**Tests: `tests/test_observability_artifact_freshness.py`, 428 lines, 30
collected tests** (16 test functions, parametrization expanding them to 30 —
confirmed this session by `pytest --collect-only -q` on that file, which
reported `30 tests collected`). They cover the eligibility matrix option by
option, the publishability gate (early stop, deselection, each exit status),
the atomic-promotion path, the temp-file cleanup, and three end-to-end cases
that run a real nested pytest session: a full-suite run refreshes the
artifact, a narrow run does not create it, and a narrow run leaves an existing
artifact untouched.

**CI:** `.github/workflows/atlas_ci_cd.yml` gained 34 lines in the same
commit, continuing the wiring described in the predecessor checkpoint.

### Step 2 — live verification against the owner's running instance

This closed "Remaining work" item 3 of the predecessor checkpoint, which
recorded that the dashboard had been exercised only against fakes and a
throwaway preview server, and that the behaviour of a real instance was
`UNKNOWN — requires verification`.

Verified this session against the live process (read-only; the instance was
not started, stopped, restarted or otherwise touched):

- **Process topology:** three `python.exe` processes, all created
  `17.09.2026 13:41:14` local (+03) — a WindowsApps launcher shim
  (PID 21472), the real supervisor `atlas_supervisor.py` (PID 22428), and the
  merged child `atlas_service.py` (PID 12064) launched with the repository
  root as its CWD. This matches the intended post-`9fadd67`/`2d7ab52`
  topology: one supervisor with OS-level restart authority over one merged
  Core+Dashboard process.
- **`GET http://127.0.0.1:8000/api/health` → HTTP 200:**
  `healthy: true`, `running: true`, `execution_halted: false`,
  `execution_recovery_required: false`, `supervised: true`,
  `supervisor_epoch: 19d116dfab8044328419465697dae908`,
  `supervisor_restart_count: 0`, `runtime_state: RUNNING`, `error_count: 0`,
  `market_data_stale: true`, `market_data_stale_reason: null`,
  `market_loop_thread_alive: true`.
- **What that establishes:** the execution surface is healthy and, critically,
  `execution_recovery_required: false` — there is no unresolved transaction
  journal entry, so the durable execution state is currently in a clean,
  movable condition. The dashboard's Execution/Sağlık panel is fed entirely
  from these fields, all of which are present and well-formed on a real
  instance.
- **`market_data_stale: true` with `market_data_stale_reason: null`** is worth
  an operator's attention: the loop thread is alive and the runtime reports
  healthy, but market data is flagged stale with no reason string attached.
  Not investigated further — recorded here as an observation, not a diagnosis.

**Note on `supervisor_epoch` — the discrepancy item.** The mechanism is
confirmed by reading the code: `atlas_supervisor.py:99-100, 305-311` generates
one epoch per *supervisor* run and injects it (plus the restart count) into a
full copy of `os.environ` handed to each child, and
`core/application.py:185-215` reads it back through
`_read_supervisor_epoch()`, which returns `None` unless the value matches
`\A[0-9a-f]{32}\Z`. The consequence is that the epoch identifies the
supervisor generation and stays **constant across child restarts**, while only
`supervisor_restart_count` increments — so an operator reading the dashboard's
`supervisor_epoch` row as a per-process identity will be misled after any
restart. The live instance is consistent with this (epoch set,
`restart_count: 0`, i.e. no restart has occurred yet).

**However:** the exact discrepancy observed during the original Step 2 session
was not reconstructible from repository artifacts in this session — there is
no `logs/` directory, no epoch value recorded in any committed file, and no
saved plan document for that session. The paragraph above is derived from
reading the code and the live payload now, **not** from the original
observation. The specific original finding is therefore recorded as
**UNKNOWN — requires owner confirmation**, and this checkpoint should be
amended additively once the owner supplies it. It is deliberately not
guessed at.

### Step 3 — the two commits

Both authored `Thu Sep 17 13:53 +0300`, on branch `research/edge-validation`,
on top of `dac9b72`:

- **`6e87e81` — `feat(web): expand operator dashboard to 5 symbols, agents,
  health and trades`.** 3 files, +1057/-45: `web_app.py` (+440),
  `templates/dashboard.html` (+211/-45 rewritten), and the new
  `tests/test_web_app_signals_and_trades.py` (451 lines, 16 tests). This is
  the predecessor checkpoint's items 1-3 and 6 as committed.
- **`da0e227` — `feat(observability): refresh test-results artifact from
  full-suite runs`.** 4 files, +832/-13: the new root `conftest.py` (323),
  the new `tests/test_observability_artifact_freshness.py` (428),
  `tools/generate_test_results_artifact.py` (+60/-13, the `write_meta_sidecar`
  extraction), and `.github/workflows/atlas_ci_cd.yml` (+34). This is Step 1
  as committed.

Both commit messages are written in the repository's established style: the
problem first, then why the chosen mechanism is the right one, then what was
deliberately *not* done and why.

## Files changed

This checkpoint session itself changed **no** repository files other than
adding this checkpoint file. The file changes it records are the ones inside
commits `6e87e81` and `da0e227`, listed above.

Untracked state present before and after, not created by this work:
`REM-001_CANONICAL_COMPONENT_MATRIX.json`,
`checkpoints/20260915T163048Z_execution-authority-log-migration.md`,
`checkpoints/20260917T103347Z_dashboard-multisymbol-expansion.md`,
`governance/ATLAS_REM001_GATE1_DELIVERABLE1_AUTHORIZATION_v1.0.md`,
`governance/ATLAS_REM001_GATE1_DELIVERABLE8_SUCCESSOR_REDEFINITION_v1.0.md`,
`governance/current/ATLAS_MILESTONE_REGISTRY_v4.33.json`,
`memory_data_backup_20260915/`, `paper_trades.json.legacy_backup_20260915`.

## Architecture decisions

1. **Artifact freshness is solved at the point of staleness — the test run —
   not in CI and not by a scheduled job.** CI cannot write to the operator's
   filesystem and the artifact is gitignored, so neither could have closed the
   gap. Every full-suite run the operator already performs now refreshes the
   panel as a side effect.
2. **The XML comes from pytest's own `--junitxml` machinery, redirected**,
   rather than from a reimplementation of pytest's report format. The hook
   therefore produces byte-identical output to what the manual script
   produces, because it is the same code path.
3. **`write_meta_sidecar` was extracted and imported, not duplicated.** One
   provenance format, one writer, two callers.
4. **Two-phase gating (eligibility before, publishability after)** rather than
   a single pessimistic check, because `-x`/`--maxfail` truncation is
   genuinely not knowable before the run, and pessimism there would have
   disabled refresh for the common case.
5. **Silent, total failure isolation in every hook**, accepting a stale
   artifact as the failure mode, because the alternative failure mode — an
   INTERNALERROR from `pytest_sessionfinish` — would misreport a green suite
   as failed. This is an explicit trade recorded in the code comments.
6. **Decision functions take plain values, not `Config`**, for exhaustive
   testability without a pytest session.

## Tests

- `python -m pytest tests/test_observability_artifact_freshness.py
  --collect-only -q --basetemp=C:/atlas_pytest_tmp` → **`30 tests collected`**
  (run this session; collection only, no execution).
- The full-suite figures recorded in the predecessor checkpoint
  (**2781 passed, 0 failed**, exit code 0) predate commit `da0e227`, and
  therefore predate the 30 freshness tests. The current full-suite count has
  **not** been re-measured as of this checkpoint.
- Per-file and combined suite results for the dashboard work are recorded in
  the predecessor checkpoint and are not restated here.

## Current state

- Branch `research/edge-validation`, HEAD **`da0e227`**. The work stream's
  code is committed; the working tree is otherwise clean apart from the
  pre-existing untracked files listed above.
- **Atlas is running** (since 13:41:14 local), supervised, healthy, with
  execution neither halted nor in recovery.
- `reports/observability/test_results.meta.json` on disk is stamped at commit
  **`dac9b72`**, generated `2026-09-17T10:50:27Z` — i.e. it was produced by
  the last manual script run just *before* the two commits landed. Since HEAD
  is now `da0e227`, the panel's `commit_alignment` will currently report a
  **mismatch** until the next full-suite run refreshes it — which, by the
  design of the new hook, now happens automatically.

## Known issues

- The original Step 2 `supervisor_epoch` observation is **UNKNOWN — requires
  owner confirmation** (see Step 2 above). Recorded, not guessed.
- The artifact/HEAD commit mismatch described under Current state is expected
  and self-correcting on the next full-suite run; it is noted so that nobody
  re-diagnoses it as a regression.
- `market_data_stale: true` with a `null` reason on the live instance —
  observed, not investigated.
- Carried forward, unchanged from the predecessor checkpoint: the CI workflow
  has still never actually executed inside GitHub Actions; the duplicated dead
  code block in `tests/test_web_app_contract.py` (~lines 146-285 repeated at
  ~287-426) remains a deferred improvement; and `/code-review` in this
  checkout still has no git remote to derive a diff range from.

## Risks

- **The freshness hook writes to the artifact on every eligible full-suite
  run.** That is the intent, but it means any full-suite run from any branch
  or working-tree state now restamps what the operator's dashboard displays.
  The provenance sidecar (commit hash plus `commit_alignment`) is what keeps
  that honest, so the panel's commit row is load-bearing and must not be
  dropped from the UI.
- **CI workflow remains unvalidated by an actual run** (carried forward).
- Nothing in this work stream touched execution, risk, capital or migration
  paths; the two new endpoints are read-only and allowlisted.

## Remaining work

1. Owner decision still open from the predecessor checkpoint: how (if at all)
   to keep a *long-running* operator dashboard fresh between full-suite runs.
   The hook substantially narrows this — the panel now self-refreshes whenever
   the suite is run — but an operator who does not run the suite for a week
   still sees a week-old count.
2. First real GitHub Actions run of the modified `atlas_ci_cd.yml` should be
   watched.
3. Amend this checkpoint additively once the owner supplies the original
   `supervisor_epoch` discrepancy detail.
4. Deferred improvement: the duplicated dead code block in
   `tests/test_web_app_contract.py`.

## Next exact action

Nothing in this work stream is blocked and nothing is left half-done: the
dashboard expansion, the freshness hook, live verification and both commits
are complete. The next action is the separately-scoped **STATE-MOVE-1** work
(relocating `memory_data/` out of the OneDrive-synced tree), whose Phase A is
code-only and independent of this stream.
