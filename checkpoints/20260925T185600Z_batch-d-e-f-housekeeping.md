# ATLAS CHECKPOINT

## Objective

Owner brief 2026-09-25, Parts D, E and F: three housekeeping corrections.

- **D (I-4):** a stale comment in `core/application.py`.
- **E (I-5):** a stale Gate-1 precondition reference in v4.74 and the
  crash-recovery checkpoint.
- **F:** a duplicated dead block in `tests/test_web_app_contract.py`.

Classification: TRIVIAL for D and F. ROUTINE for E, because it is an
additive governance record.

## Completed

### D: DONE, `95638b7`

- Comment-only.
- The `_build_services` comment now calls the paper book a passive mirror of
  ExecutionPortfolioFoundation, projected after each commit and once at
  startup, with no execution outcome classified against it.
- "Once at startup" is accurate only together with Part C (`ccb2e37`), which
  landed first.

### E: DONE, `accbb04` (registry v4.75) and `64450ca` (evidence)

- `64450ca` commits the previously untracked
  `checkpoints/20260925T000500Z_state-move-1-verification.md`. It is the
  evidence v4.75 cites.
- v4.75 is an additive successor. It adds only
  `stale_reference_corrections_i4_i5`:
  - **I-5 → CLOSED_ALREADY_SATISFIED.** STATE-MOVE-1 was executed
    2026-09-18, according to ADR-0007 and commit `d323365`.
  - **I-4 → CLOSED_FIXED** (`95638b7`).
- v4.74 and `checkpoints/20260924T203700Z_execution-authority-crash-recovery.md`
  are byte-unchanged.
- Diff against v4.74: 3 header fields changed, 39 lines inserted.
- Residual, recorded in v4.75: with `ATLAS_STATE_DIRECTORY` unset, Atlas
  falls back to `<repo>/memory_data`, which is inside OneDrive. The
  precondition holds per operator environment, not by code default.

### F: DONE, `eb60488`

- Verified dead before removing. Lines 146-285 and 287-425 differ only by
  one trailing blank line (`diff` output: `140d139 <` blank).
- Python rebinding means only the second copy was ever collected.
- The shadowed first copy was removed (141 lines).
- Collected test count for the file: 8 before, 8 after. All pass.

## Files changed

- `core/application.py` (comment only)
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.75.json` (new)
- `checkpoints/20260925T000500Z_state-move-1-verification.md` (newly
  tracked, content unchanged)
- `tests/test_web_app_contract.py` (−141 lines)

## Architecture decisions

None.

## Tests

- `tests/test_web_app_contract.py`: 8 passed.
- The full suite result is recorded in the Part C checkpoint
  (`20260925T185700Z_batch-c-paper-mirror-integrity.md`).

## Current state, known issues, risks

- I-4 and I-5 are closed.
- No new issues or risks.

## Remaining work

None for these parts.

## Next exact action

None.
