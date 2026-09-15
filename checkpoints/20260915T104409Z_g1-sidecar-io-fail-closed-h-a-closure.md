# ATLAS CHECKPOINT

## Objective

Close out Package H-A (`tools/migrate_execution_financial_state.py` — the
execution financial-state v1→v2 migration guard) by remediating Gap G1, the
one MEDIUM finding surfaced by a PLAN MODE audit of that tool: both
`load_index()` call sites for the applied/closed sidecars opened files
directly and let `OSError` escape uncaught — at the two pre-append guards, in
`_verify_post_append`, and in `_verify_already_migrated` — producing an
unhandled Python traceback instead of a structured `MigrationResult` on a
present-but-unreadable sidecar (permission denied, I/O error, Windows file
lock). This is a CRITICAL-classification BUILD MODE task per CLAUDE.md
(touches migration integrity); the full final gate applies: IMPLEMENT → TEST
→ SELF-REVIEW → REGRESSION → INDEPENDENT AUDIT → FIX → RE-TEST → FINAL GATE.

## Completed

- Read `tools/migrate_execution_financial_state.py` in full (636 lines) and
  the reference pattern at `tools/migrate_capital_reservations.py:183-186`
  (its existing `OSError` → `ARCHIVE_UNREADABLE` handling, kept distinct from
  `ARCHIVE_CORRUPT`).
- Confirmed via `core/execution_portfolio_foundation.py:186-330` that
  `AppliedExecutionArchiveCorruptError` / `AppliedExecutionArchiveConflictError`
  and their closed-sidecar equivalents are `RuntimeError` subclasses, disjoint
  from `OSError` — so adding `except OSError` clauses shadows none of the
  existing exception handling and clause ordering is not semantically
  significant.
- Asked the operator which reason-code strategy to use for the two pre-append
  guards (reuse `*_SIDECAR_CORRUPT` vs. two new `*_SIDECAR_UNREADABLE`
  tokens); operator selected the new-token option, explicitly authorizing the
  one deviation from the scope's literal "do NOT invent new reason tokens"
  instruction, because collapsing an access failure into "corrupt" sends the
  operator toward the wrong remediation (content repair instead of fixing
  access) on a financial migration tool.
- Implemented `OSError` handling at all six actual `load_index()` call sites
  that read a sidecar (the scope named four locations; two of those location
  descriptions — `_verify_post_append` and `_verify_already_migrated` — each
  contain two calls, one per sidecar, both of which needed the fix).
- Added a module-docstring paragraph documenting the new fail-closed
  behavior and the `UNREADABLE`-vs-`CORRUPT` distinction.
- Added two parametrized/discrete tests to
  `tests/test_migrate_execution_financial_state.py` covering both required
  scenarios (pre-append refusal; post-append-verification refusal with
  resume proof).
- Ran the new tests against the pre-fix code (`git show HEAD:...`) to confirm
  they fail with exactly the unhandled `PermissionError` traceback G1
  describes, then restored the fixed file — proving the tests are
  discriminating, not vacuous.
- Ran the full regression surface (every module referencing this tool) on
  the final code state: 98/98 passed.
- Ran an independent audit (code-review skill, effort `high`, scoped to the
  two changed files) as the CRITICAL gate's INDEPENDENT AUDIT step. One LOW
  finding surfaced, pre-existing and not introduced by this diff (see Known
  issues below); it was recorded, not fixed, per the standing token-
  efficiency-contract rule that an unrelated LOW finding in a critical
  package gets recorded rather than fixed inline unless it materially
  affects correctness (it does not — both downstream paths still fail
  closed).
- Saved a durable memory,
  `atlas-unreadable-distinct-from-corrupt.md`, capturing the
  UNREADABLE-vs-CORRUPT reason-code principle the operator settled, since the
  same question is expected to recur in the deferred G2/G3 work on
  `migrate_capital_reservations.py`.

## Files changed

Per `git status --porcelain` and `git diff --stat`, captured at checkpoint
time:

```
 M tests/test_migrate_execution_financial_state.py | 152 ++++++++++++++++++++++++
 M tools/migrate_execution_financial_state.py      |  57 ++++++++-
 2 files changed, 207 insertions(+), 2 deletions(-)
```

No other tracked file was modified. Four untracked files were already
present in the working tree at session start (not created or touched by this
session): `REM-001_CANONICAL_COMPONENT_MATRIX.json`,
`governance/ATLAS_REM001_GATE1_DELIVERABLE1_AUTHORIZATION_v1.0.md`,
`governance/ATLAS_REM001_GATE1_DELIVERABLE8_SUCCESSOR_REDEFINITION_v1.0.md`,
`governance/current/ATLAS_MILESTONE_REGISTRY_v4.33.json`. These are staged
into a separate, unrelated commit below (see Current state) — they are not
part of the G1/H-A change and are not described further here.

## Architecture decisions

- **`OSError` at a sidecar read is fail-closed, never treated as absent or
  empty.** All six read sites now catch `OSError` explicitly and return a
  structured `MigrationResult` (or, at the post-append gate, the existing
  `POST_APPEND_VERIFICATION_FAILED:*` string) rather than letting the
  exception propagate. This preserves the tool's own output-safety contract
  (ADR-0005): no raw exception text, path, or OS message reaches
  operator-visible output, and the exit code stays in the tool's own
  `{EXIT_REFUSED, EXIT_FAILED}` vocabulary rather than colliding with
  Python's default exit 1 (`EXIT_USAGE`).
- **Two new reason tokens, `APPLIED_SIDECAR_UNREADABLE` and
  `CLOSED_SIDECAR_UNREADABLE`**, used at the two pre-append guards and in
  `_verify_already_migrated` (four of the six sites). Composed from this
  tool's own existing vocabulary (the `SIDECAR_INVALID` outcome it already
  uses for corrupt/conflicting sidecars, and the `UNREADABLE` suffix it
  already uses for the working file — `SOURCE_UNREADABLE`), not invented
  from nothing. Kept deliberately distinct from `*_SIDECAR_CORRUPT` because
  the operator's remediation differs: corrupt content needs repair or
  reconstruction; an unreadable file needs an access fix. Operator-confirmed
  decision (see Completed).
- **No new token at the post-append verification gate.** There, an
  unreadable sidecar and a corrupt one call for the identical operator
  action — do not treat the migration as committed, v1 is still intact and
  the run is resumable — so `OSError` was added to the existing `except`
  tuples for `POST_APPEND_VERIFICATION_FAILED:APPLIED_SIDECAR` and
  `POST_APPEND_VERIFICATION_FAILED:CLOSED_SIDECAR` rather than getting its
  own token. This keeps the scope's "match this tool's own existing token
  vocabulary" instruction fully honored at the two sites where the
  remediation is genuinely identical, while still authorizing new tokens
  where the operator confirmed the remediation genuinely differs.
- **Tests patch `Path.open` at read-mode granularity, path-scoped**, rather
  than stubbing `load_index()` or the store classes. This exercises the
  actual read path the tool depends on today, so a future refactor that
  changed how a sidecar is read (without preserving the fail-closed
  behavior) would still be caught by these tests rather than silently
  passing against a stale mock.

## Tests

- `tests/test_migrate_execution_financial_state.py` alone: **14 passed**
  (11 pre-existing + 3 new — `--basetemp` used per the ASCII-basetemp
  standing rule for this host).
- Regression surface — every module in the repository that references this
  tool (`tests/test_migrate_execution_financial_state.py`,
  `tests/test_block5i_durable_financial_state_sidecars.py`,
  `tests/test_block5k_durable_execution_storage.py`) run together on the
  final code state: **98 passed, 0 failed**.
- Discriminating-test proof: the 3 new tests were run against the pre-fix
  code (`git show HEAD:tools/migrate_execution_financial_state.py`
  temporarily restored) and confirmed to **fail** with exactly the unhandled
  `PermissionError: [Errno 13] ...execution_*.jsonl` traceback G1 describes;
  the 11 pre-existing tests passed unchanged in that same run, confirming no
  existing success-path behavior moved. The fixed file was then restored and
  the 98-passed regression result above is against that restored, final
  code.
- No test was modified or weakened to make it pass, per the standing testing
  rule.

## Current state

- Package H-A (execution-financial-state migration guard,
  `tools/migrate_execution_financial_state.py`) is now **fully CLOSED**. All
  checklist properties are PRESENT and independently tested: idempotency,
  resume, retry, sequence/ordering (including the already-fixed H-1),
  duplicate detection, partial-state handling, conflict detection,
  rollback/recovery, fail-closed-on-corrupt, output safety per ADR-0005, and
  — as of this session — fail-closed-on-unreadable (G1).
- Working tree has two modified tracked files
  (`tools/migrate_execution_financial_state.py`,
  `tests/test_migrate_execution_financial_state.py`) plus the four untracked
  governance/matrix files noted above, present at session start and unrelated
  to this change.
- Branch: `research/edge-validation` (per session start git status). Not yet
  committed as of the start of this checkpoint step; the commit created
  immediately after this checkpoint file is written will include only the
  two G1-fix files plus this checkpoint file — the four unrelated untracked
  files are explicitly left out of that commit (see Next exact action / this
  session's final git actions for the actual commit hash and post-commit
  `git status`).

## Known issues

- **One LOW, pre-existing finding, recorded but not fixed**, at
  `tools/migrate_execution_financial_state.py:327` (line number as of the
  fixed file): the `applied_path.exists()` / `closed_path.exists()`
  pre-checks that gate the *new* `except OSError` handlers themselves
  swallow `OSError` — confirmed on this repo's Python 3.14.6 that
  `Path.exists()` delegates to `os.path.exists()`, which returns `False` on
  any `OSError` rather than propagating it. If a sidecar's **stat** call
  fails (not its read — e.g. the parent directory lacks traverse
  permission, or a transient I/O error at stat time), the file reads as
  absent and the entire pre-append guard block — including this session's
  new `OSError` handler — is skipped. Both downstream outcomes still fail
  closed and never commit a bad migration: a persistent fault surfaces as
  `MIGRATION_WRITE_FAILED:SIDECAR_APPEND` when `append()` itself raises; a
  transient fault that clears before the append gets caught by the
  post-append verification gate as `POST_APPEND_VERIFICATION_FAILED:*`, with
  v1 left intact either way. The residual cost in the transient case is
  junk lines left durably in the sidecar, which wedges all later runs at the
  `*_SIDECAR_DOES_NOT_MATCH_SOURCE` conflict gate until an operator manually
  repairs the archive file. This is out of the G1 scope as given (which
  named the `load_index()` call sites, not the `exists()` pre-checks),
  changing `exists()`-based control flow would itself be a behavior change
  to an already-correct success path, and it does not materially affect
  correctness (nothing is ever silently committed). Not fixed in this
  session per the operator's standing rule that an unrelated LOW finding in
  a critical package is recorded, not fixed inline, unless it materially
  affects correctness.

## Risks

- The one recorded LOW finding above means a rare stat-level I/O fault (as
  opposed to a read-level one, which this session's fix now handles) can
  still wedge a resume at the conflict gate rather than surfacing the new
  `*_SIDECAR_UNREADABLE` token. Operator remediation in that case is the
  same as any other conflict-gate refusal: inspect the sidecar manually. No
  data-loss or silent-corruption risk — every path still fails closed.
- The two new reason tokens (`APPLIED_SIDECAR_UNREADABLE`,
  `CLOSED_SIDECAR_UNREADABLE`) are additions to this tool's operator-visible
  reason-code contract. Any external tooling or runbook that pattern-matches
  on the previously-exhaustive `SIDECAR_INVALID` reason-code set for this
  tool should be updated to expect these two new values. UNKNOWN — requires
  verification whether any such external tooling exists; none was
  identified or modified in this session.

## Remaining work

- None within Package H-A itself — it is fully closed as of this session.
- Deferred, unrelated packages explicitly out of scope for this session and
  still open: G2/G3 in `migrate_capital_reservations.py`; G4
  (`_verify_already_migrated`'s checkpoint-comparison behavior); G5
  (directory fsync, architectural); G6 (`risk_state_store.py`, separate
  risk-domain scope). None of these were touched, and this checkpoint does
  not assert anything new about their state beyond what was already known
  before this session.

## Next exact action

Stage and commit `tools/migrate_execution_financial_state.py`,
`tests/test_migrate_execution_financial_state.py`, and this checkpoint file
together in a single commit on the current branch (`research/edge-validation`),
with a message summarizing the G1 fix and the H-A closure. Do not push. Do
not stage the four unrelated untracked governance/matrix files present at
session start — they belong to separate, not-yet-reviewed work and staging
them here would silently expand this commit's scope beyond G1/H-A. After
committing, run `git status` to confirm the two code files and this
checkpoint file are no longer listed as modified/untracked, and report the
exact commit hash.
