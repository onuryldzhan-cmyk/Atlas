# ATLAS CHECKPOINT — S-3/M-2 Read-Only Extraction Tool

- **UTC:** 2026-09-24T14:43:06Z
- **Branch:** `research/edge-validation`
- **HEAD at start:** `9e28d4d`
- **HEAD at end:** uncommitted at checkpoint time — three new untracked files (see *Files changed*)
- **Mode:** BUILD
- **Classification:** CRITICAL, per the owner's pinned task-classification rubric. The trigger is not the tool's own blast radius (it touches no risk/execution/capital/security/migration code and adds no runtime import edge) but that the task requires authoring a new governance registry successor record — touching the governance domain is itself a CRITICAL floor. The full gate was applied: IMPLEMENT → TEST → SELF-REVIEW → REGRESSION → INDEPENDENT AUDIT → FIX → RE-TEST → FINAL GATE.

## Objective

Build a read-only extraction/analysis tool that parses
`<ATLAS_LOG_DIRECTORY>/market_loop_telemetry.jsonl` and computes candle-age
(S-3) and cycle-duration (M-2) statistics per runbook step 6 of
`checkpoints/20260924T123057Z_candle-age-durable-telemetry.md`, and produce a
data-backed proposal for the owner's S-3/M-2 threshold decisions.

## Completed

1. **Classification.** CRITICAL per the owner's pinned task-classification
   rubric — see *Classification* above.
2. **Investigation.**
   - Confirmed no prior grant authorizes creating a persistent extraction
     script. Registry v4.45's `GRANT-RUN-EVIDENCE-EXTRACTION` explicitly
     forbade `CREATING_ANY_FILE_UNDER_THIS_GRANT` and was scoped to a
     one-time report ("THE FINAL SESSION REPORT ONLY").
   - `checkpoints/20260924T123057Z_candle-age-durable-telemetry.md`'s
     *Remaining work* explicitly calls for "a separate, future extraction
     task under its own grant."
   - Filesystem search confirmed **no real `market_loop_telemetry.jsonl`
     exists anywhere on this workstation** outside ephemeral pytest tmp
     directories. `ATLAS_LOG_DIRECTORY` has never been set for a real run.
     No real S-3/M-2 evidence currently exists.
3. **Step 0 — governance.** Authored
   `governance/current/ATLAS_MILESTONE_REGISTRY_v4.72.json` as an additive
   successor to v4.71. Built as a verified byte-identical copy of the
   predecessor (round-trip checked) before appending, so the historical
   record is provably unchanged. Adds the
   `s3_m2_extraction_tool_authorization` record with
   `GRANT-S3-M2-EXTRACTION-TOOL`: read-only, BUILD mode for the tool /
   RESEARCH_MODE for output interpretation, explicit fail-closed rules, an
   explicit `this_grant_does_not_authorize` list (no threshold
   implementation/enforcement, no change to `market_loop.py`/`logger.py`/
   `application.py`/the schema, no touch to execution/risk/capital/health
   paths, no commit to `feat/block3-execution-safety`, no network access, no
   new dependency), and the sample-size-honesty binding rule carried forward
   from v4.45's `GRANT-RUN-EVIDENCE-EXTRACTION`.
4. **Implementation — `tools/extract_candle_age_telemetry.py`.** Parses the
   JSONL log fail-closed (skips and counts blank lines, malformed JSON,
   non-object JSON, missing required fields; never raises). Reports
   per-symbol and overall `candle_age_seconds` distributions (count / min /
   max / mean / median / p50 / p90 / p95 / p99) over `MEASURED` records
   only, `candle_age_status` frequency counts, and `cycle_duration_seconds`
   distributions de-duplicated to one value per (run, cycle) via a
   run-boundary-on-cycle-reset heuristic (documented in the module docstring
   as an inference from file order, not a guaranteed identity, since
   schema_version 1 carries no run/instance id). CLI supports `--json` and
   `--log-directory`. Reuses `core.application.resolve_log_directory()` and
   `core.logger.TELEMETRY_LOG_FILE` rather than reimplementing path
   resolution, so the tool and the runtime writer can never disagree about
   where the log lives. Writes no file, makes no network call, writes no
   threshold value anywhere.
5. **Tests — `tests/test_extract_candle_age_telemetry.py`.** Started at 28
   tests covering parsing edge cases (blank lines, malformed JSON,
   non-object JSON, missing fields, mixed `schema_version`, a reason-code
   row instead of a numeric age), S-3/M-2 aggregation, run-boundary
   detection, and CLI/`main()` (unset `ATLAS_LOG_DIRECTORY`, missing file,
   empty file, `ConfiguredDirectoryError`, explicit `--log-directory`
   override).
6. **Independent audit.** Delegated to a fresh subagent with no prior
   context, run in AUDIT MODE against CLAUDE.md's format. Findings:
   - **HIGH** — `aggregate_candle_age` used `candle_age_status` directly as
     a `dict`/`Counter` key with no type guard (unlike `symbol`, which was
     already guarded). A malformed line with a list/dict `candle_age_status`
     value raised an unhandled `TypeError`, crashing the tool with zero
     output — worse than the documented worst case. This also produced a
     **Section B governance CONFLICT**: the v4.72 grant's own
     `fail_closed_rules` text ("never raise an unhandled exception... skip
     plus a counted note") did not match the code as written.
   - **MEDIUM** — no exclusion counters existed for records dropped from
     the M-2 pipeline due to an invalid `cycle` or `cycle_duration_seconds`
     field, and only a weak, indirect equivalent existed for S-3.
   - **LOW** — test-coverage gap tied to the HIGH finding (no test used a
     non-hashable `candle_age_status`).
   - **INFORMATIONAL** — `median` and `p50` use different statistical
     conventions (mean-of-two-middle vs. nearest-rank), undocumented.
7. **Fixes.** All four applied:
   - Guarded `candle_age_status` the same way `symbol` already was: any
     non-`str` value is coerced to `"UNKNOWN_STATUS_TYPE"` before use as a
     dict key. This closes both the HIGH finding and the Section B
     CONFLICT — the code now matches the grant's own fail-closed text.
   - Added `measured_status_excluded_invalid_age_count` to the S-3 report,
     and `excluded_records_invalid_cycle_field` /
     `excluded_records_invalid_duration_field` to the M-2 report.
     `cycle_duration_series`'s return signature grew from a 2-tuple to a
     3-tuple to carry the new count; all three call sites in the test file
     were updated accordingly.
   - Added a one-line code comment noting `median` vs `p50` can differ on
     an even-sized sample.
   - Added 7 new tests covering the fixes (35 total in the file, up from
     28).
8. **Ran the real tool against the real environment.** With
   `ATLAS_LOG_DIRECTORY` unset (its actual current state), confirmed the
   honest zero-record outcome (`log_path: null`, `log_file_found: false`,
   every count zero) — matching the filesystem investigation in step 2.
9. **Regression.** Ran `tests/architecture/` plus
   `tests/test_market_loop_candle_age_telemetry.py`: **103 passed, 1 failed**
   — the failure confirmed identical to the known pre-existing Group B2
   forbidden-edge violation. The new tool's imports of
   `core.application`/`core.logger`/`core.market_loop` introduced no new
   forbidden-edge violations.
10. **Full suite RE-TEST**, at final code state (after all fixes):
    **3906 passed, 1 failed.** Reconciled: the prior baseline
    (`checkpoints/20260924T123057Z_candle-age-durable-telemetry.md`) was
    3871 passed / 1 failed; this run adds exactly the 35 new tests
    (3871 + 35 = 3906) with no other movement. The single failure is the
    same pre-existing Group B2 test.
11. **Final diff review.** `git status --short` shows exactly three new
    untracked files and nothing else — no existing file was modified.

## Files changed

All three are new, untracked, additive-only — no existing file was
modified (confirmed by `git status --short` and `git diff --stat` at
checkpoint time):

- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.72.json` — new governance
  successor record (see *Completed* item 3).
- `tools/extract_candle_age_telemetry.py` — the new tool.
- `tests/test_extract_candle_age_telemetry.py` — its test suite (35 tests).

## Architecture decisions

- **Reuse, not reimplementation, of path resolution.** The tool imports
  `core.application.resolve_log_directory()` and
  `core.logger.TELEMETRY_LOG_FILE` rather than duplicating the directory/
  filename logic, so the tool and the runtime writer can never disagree
  about where the log lives (same pattern as
  `tools/inspect_research_market_data_coverage.py` reusing
  `resolve_market_archive_directory()`).
- **Run-boundary detection is an inference, not an identity.** M-2
  de-duplication groups `cycle_duration_seconds` by (run, cycle), where a
  "run" is inferred from the file-order cycle sequence going backwards.
  This cannot distinguish two consecutive process runs that both never
  advance past cycle 1, because schema_version 1 carries no run/instance
  id (a known *Deferred improvement* from
  `checkpoints/20260924T123057Z_candle-age-durable-telemetry.md`). Declared
  explicitly in the tool's own docstring rather than silently assumed.
- **Governance record built as a verified copy, not hand-authored from
  scratch.** `ATLAS_MILESTONE_REGISTRY_v4.72.json` was produced by copying
  v4.71 byte-for-byte (verified via a round-trip check before this session's
  edits) and then appending the new record plus three top-level meta-field
  edits (`schema_version`, `supersedes`, `registry_status`) — never editing
  historical content in place, per CLAUDE.md's governance additive-only
  rule.

## Tests

- **New file:** 35 passed (28 initially, +7 from the audit-driven fixes),
  stable.
- **Affected-file regression** (`tests/architecture/` +
  `tests/test_market_loop_candle_age_telemetry.py`): 103 passed, 1 failed —
  the pre-existing Group B2 violation, confirmed unchanged.
- **Full suite RE-TEST** (final code state):
  **3906 passed, 1 failed** — reconciled against the prior 3871-passed
  baseline plus exactly the 35 new tests; no other movement. The one
  failure is `tests/architecture/test_forbidden_layer_imports.py`,
  reporting the same two pre-existing forbidden edges from
  `atlas_finance/market_data/contracts.py` documented in every prior
  checkpoint since registry v4.40/v4.41.
- **Live-tool run against the real environment:** confirmed zero records
  (see *Completed* item 8) — this is real-environment output, not a test.

## Current state

- S-3 and M-2 remain **OPEN**. This package adds tooling only and decides
  no threshold. It found that **zero real telemetry data currently exists**
  — `ATLAS_LOG_DIRECTORY` has never been set for a real run on this
  workstation, so no data-backed S-3/M-2 proposal is possible today.
- Authority unchanged: `production_authority=NONE`,
  `live_authority=DENIED`, `autonomous_deployment_authority=DENIED`.
- No Atlas process was started, stopped, or contacted. No real state root
  or real log root was written.

## Known issues

- **Run-boundary ambiguity for consecutive short runs.** Two consecutive
  process runs that both never advance past cycle 1 cannot be told apart
  by the M-2 de-duplication logic. Not a defect given the current schema —
  documented in the tool's docstring, not worked around.
- **`median` vs `p50` convention difference.** They can differ on an
  even-sized sample (mean-of-two-middle vs. nearest-rank). INFORMATIONAL
  per the independent audit; documented via a code comment, not unified
  further since both are individually correct and standard.
- **Mid-session tooling note (not a deliverable defect).** Bash commands
  that parsed or executed these three newly-created files were initially
  refused by the session's own safety classifier as "Instruction
  Poisoning" — a reasonable heuristic given the files' self-authorization-
  style governance language (`"authorized": true`, `GRANT-*` grant IDs),
  which is this repository's own established governance-documentation
  convention but is indistinguishable in isolation from a real
  prompt-injection attempt. Resolved once the user added a Bash permission
  rule. Recorded here so a future session hitting the same block on these
  exact paths recognizes it as expected, not a new problem.

## Risks

- None new. The tool is read-only, fully offline, adds no runtime import
  edge into `core/market_loop.py`'s closure, and writes no threshold value
  anywhere.
- The only standing risk is the pre-existing one already carried by
  `checkpoints/20260924T123057Z_candle-age-durable-telemetry.md`: a real
  paper run started without `ATLAS_LOG_DIRECTORY` set collects nothing,
  silently apart from the "disabled" startup line.

## Remaining work

- **Owner-scheduled, observed paper run** with `ATLAS_LOG_DIRECTORY` set,
  per the runbook in
  `checkpoints/20260924T123057Z_candle-age-durable-telemetry.md` (create a
  log directory outside OneDrive, `setx ATLAS_LOG_DIRECTORY`, start Atlas,
  confirm the "Durable telemetry log: ..." startup line).
- **Run `tools/extract_candle_age_telemetry.py --json`** against the
  resulting real log to get an actual data-backed S-3/M-2 proposal. Today's
  run against the real (unconfigured) environment found zero records, so
  no data-backed threshold proposal is possible yet — only the tooling to
  produce one once real data exists.
- **The S-3 and M-2 threshold value decisions themselves**, which remain
  the owner's alone (registry v4.41: no threshold value may be written into
  any file before the owner decides).

## Next exact action

Owner schedules the observed paper run. Once it produces real telemetry,
run `tools/extract_candle_age_telemetry.py --json` (optionally
`--log-directory <path>` to point at a specific log) against the resulting
file and bring the output back for the S-3/M-2 threshold decision — still
the owner's decision alone, never to be written into any file by an agent
per registry v4.41.
