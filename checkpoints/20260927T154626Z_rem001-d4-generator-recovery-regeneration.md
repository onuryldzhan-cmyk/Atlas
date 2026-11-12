# ATLAS CHECKPOINT — REM-001 D4 generator recovery, D4 regeneration, regression test

## Objective
Give D4 (`packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md`) a validated generator and a real regression test, and regenerate it at the current commit. Also correct ADR-0001 line 24 (`main.py:345` → `main.py:406`).

Out of scope, and untouched:
- D5 and D5's test
- the SQLite ownership question (`data_layer/config.py`, `data_layer/sqlite.py`)
- GOV-DRIFT-005's status
- application code
- `feat/block3-execution-safety`

## Completed
- **Premise CONFLICT raised and resolved.**
  - The brief said the generator was permanently lost.
  - In fact the original `tools/build_rem001_gate1_maps.py` and `tests/architecture/test_rem001_construction_paths.py` both survive in dangling stash commit `59229fd` (`stash@{0}^3`).
  - Owner decision: recover the original and make only the needed edits.
- **Validation at db8bdf3, before trusting any HEAD output.**
  - The unmodified original reproduces the committed D4 byte-for-byte (44268 bytes, sha256 `099e806a…0c46`).
  - The edited tool reproduces all 277 rows and every scope figure. Its only output difference is the two authorization-table lines.
- **Tool edits (text only, no analysis logic changed).**
  - The GOV-DRIFT-005 sentence no longer says "OPEN".
  - A D4-only `regeneration_recorded_by` row names registry v4.93.
- **The test is committed byte-unchanged.**
- **D4 regenerated at `4720125`** from a clean tracked tree: 108 / 384 / 286 / 33 / 121 / 91 / 3 / 0, with 4 entry points. These equal the v4.91 drift check's HEAD figures. The rows reconcile as 181 exact + 72 line-shifted + 33 new = 286, and the 24 closure-exit rows are gone.
- **Discrimination proven four ways:**
  - the stale D4 at HEAD fails;
  - tampering with a D4 count fails;
  - a line shift in `main.py` (scratch copy) fails;
  - a rogue `AtlasApplication()` in `web_app.py` (scratch copy) fails three gates.
- **Independent read-only audit:** 9/9 claims PASS, with 0 BLOCKING, 0 HIGH, 0 MEDIUM, 2 LOW and 3 INFORMATIONAL findings.

## Files changed
- Commit `4110390`:
  - `tools/build_rem001_gate1_maps.py` (recovered and edited)
  - `tests/architecture/test_rem001_construction_paths.py` (recovered, byte-unchanged)
  - `packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md` (regenerated)
  - `docs/adr/0001-canonical-composition-root.md` (line 24)
- Registry commit:
  - `governance/current/ATLAS_MILESTONE_REGISTRY_v4.93.json` (additive; `rem001_d4_generator_recovery_and_regeneration`)
  - this checkpoint
- Not staged: the pre-existing untracked `.claude/agents/atlas-test-runner.md`.

## Architecture decisions
- **Recover rather than rebuild.** The recovered tool has byte-exact provenance against D4. A rebuild would have been a second, weaker copy.
- **The tool's D5 `state` subcommand is carried as dormant code.** It was never run.

## Tests
- `tests/architecture` baseline at `4720125`: 1 failed, 55 passed.
- `tests/architecture` after the change: 1 failed, 60 passed.
- New test file: 5 passed.
- Full `pytest tests`: 1 failed, 5042 passed. This reconciles exactly: 5026 + 11 + 5.
- The only failure in every run is the accepted, pre-existing B2 `test_forbidden_layer_imports`.

## Current state
- D4 is current and regression-protected.
- REM-001 `gate_1_state` is still `OPEN_NOT_CERTIFIED`.
- `59229fd` and `stash@{0}` are intact.

## Known issues / deferred
- **F1 (LOW):** Gate 3 trusts the identity stamp D4 carries about itself. The suggested remediation is to verify that `generated_from_commit` is an ancestor of HEAD and that its tree matches.
- **F2 (LOW):** the v4.93 reference in the tool is hardcoded. Any future regeneration must update it or parameterize it.
- **ADR-0001:**
  - lines 29–30 cite stale `core/application.py` line numbers;
  - line 25's claim should be scoped to the runtime closure.
- **The recovered test is slow:** it runs five closure parses, about 25 s.
- **D5** is still a stale db8bdf3 snapshot with no committed generator test. That is a separate decision.

## Risks
- `59229fd` still lives only in `stash@{0}`. D5's original test also exists only there (`tests/architecture/test_rem001_state_authority_map.py`), so dropping the stash would lose it.

## Remaining work
None in this package. Future owner decisions:
- F1 hardening
- the ADR lines 25 and 29–30 corrections
- D5 regeneration and its test
- the SQLite ownership question

## Next exact action
Owner review of commits `4110390` and the v4.93 registry commit. Nothing is pushed.
