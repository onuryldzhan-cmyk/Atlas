# ATLAS CHECKPOINT — C2 resolved: undefined FIN-004.1a-C1/C2/C3 retired, active milestone = REM-001 Gate 1

## Objective
Carry out the owner's C2 decisions of 2026-09-28:
- Option (b): retire the undefined identifiers.
- Set the replacement active milestone to REM-001 Gate 1.
- Re-point every `FIN-004.1a-C3` prerequisite to REM-001 Gate 1.

## Completed
Registry v4.91 (`c2_undefined_milestone_retirement_result`):
- `active_milestone` changed from `FIN-004.1a-C1` to `REM-001/GATE_1_CANONICAL_COMPONENT_MAPPING`.
- `queued_foundation_sequence` lost its two `FIN-004.1a` entries. The remaining order is unchanged, starting at CFG-001.
- In 9 milestones (ARCH-001, CODE-001, OBS-001, TEST-001, PERF-001, REL-001, SEC-001.1, DATA-001, SEC-002), the `FIN-004.1a-C3` prerequisite was replaced by the Gate 1 identifier. Every before/after pair is recorded in the registry.
- C2 is marked RESOLVED. The retirement is explicitly not a claim that any work was completed.

## Files changed
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.91.json`
- This checkpoint.

v4.90 and `governance/ATLAS_ROADMAP_PHASE_0_10_ENUMERATION_v1.0.md` are not edited. That record still says C2 is open, and v4.91 supersedes it on this point.

## Architecture decisions
- Gating is not loosened: each dependent milestone now waits on a defined gate.
- Designating Gate 1 as active is not authorization. REM-001 `implementation_authorized`, `canonical_mapping_execution_authorized` and `source_changes_authorized` remain false.

## Tests
No code was changed. The following were verified:
- A structural diff of v4.90 against v4.91 shows only these changes: the new record block, `schema_version`, `supersedes`, `registry_status`, `active_milestone`, `queued_foundation_sequence`, and the `prerequisites` of exactly the 9 milestones.
- No FIN-004.1a reference remains outside the two record blocks.
- `resolve_current_registry()` resolves v4.91 as head.
- No `.py`, `.yml`, `.html` or `.js` file reads these fields.

## Current state
- Branch `claude/vigilant-maxwell-5vwebp`.
- The freeze is unchanged (PAUSED_PENDING_REM_GATE_1).
- Authority is unchanged: production=NONE, live=DENIED, autonomous_deployment=DENIED.
- CI:
  - `ee50b63` is green (push run 36361322517, PR run 36361325114).
  - `53fc09b` was in progress when last checked.

## Known issues / risks
- The origin of the retired IDs is still UNKNOWN. If a definition surfaces, it is registered as a new milestone by a successor record.
- AMP-001 phase names are UNKNOWN (profile document absent).

## Remaining work
- The owner authorizes, or declines, execution of REM-001 Gate 1 (Canonical Component Mapping). Today it is the active milestone, but not authorized.
- Deferred Improvements:
  - A CLAUDE.md pointer to the roadmap record.
  - A static test for ADR-0011 D1.

## Next exact action
Read the CI results for `53fc09b` and the v4.91 push. Then take the owner's decision on authorizing REM-001 Gate 1 work.
