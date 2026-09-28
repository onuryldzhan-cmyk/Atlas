# ATLAS CHECKPOINT — ADR-0011 D1 test, CLAUDE.md pointer, RELSUP-001 audit, REM-001 Gate 1 plan

## Objective
The owner replied "Hepsini yap" to three options:
1. Gate 1: read the scope and present a plan.
2. A read-only Reconnect/Supervisor investigation.
3. The two v4.90 Deferred Improvements.

## Completed
- **(3), commit `bd2ee9f`:**
  - `tests/architecture/test_runtime_has_no_ai_provider_dependency.py` enforces ADR-0011 D1 across the runtime closure.
  - CLAUDE.md "Roadmap discipline" now points to the Phase 0–10 enumeration record and ADR-0011.
- **(2):** `governance/findings/RELSUP-001_RECONNECT_AND_SUPERVISOR_STATUS.md`. No BLOCKING or HIGH findings. Two MEDIUM:
  - G-S1: the supervisor does not detect a hung child.
  - G-S3: there is no alert channel.
- **(1):** `governance/ATLAS_REM001_GATE1_COMPLETION_PLAN_v1.0.md`, status PROPOSED:
  - 6 of 9 deliverables are produced.
  - Every remaining step needs an owner decision or an owner-held artifact first.
- Registry v4.92 (`deferred_improvements_relsup_and_gate1_plan_result`).

## Files changed
- `CLAUDE.md`
- `tests/architecture/test_runtime_has_no_ai_provider_dependency.py`
- `governance/findings/RELSUP-001_RECONNECT_AND_SUPERVISOR_STATUS.md`
- `governance/ATLAS_REM001_GATE1_COMPLETION_PLAN_v1.0.md`
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.92.json`
- this checkpoint

## Architecture decisions
- The D1 test uses the checked-in runtime closure. That closure is already pinned to the recomputed one by `test_runtime_closure_matches_inventory`.
- An ADR-0011 D2 provider adapter can enter the D1 test's allowlist only through an explicit owner-approved change.

## Tests
Run with Python 3.13 in `/usr/bin/python3.13` via a scratch venv. The container default is 3.11, which cannot parse the repository's PEP 701 f-strings.
- `tests/architecture`: 48 passed, 1 failed. The failure is the accepted B2 signature, confirmed by `tools/ci_check_known_accepted_failures.py`.
- Injection check: both violation shapes were caught, and the file was restored.
- Reconnect and supervisor tests: 29 passed, 10 skipped (Windows-only).

## Current state
- Branch `claude/vigilant-maxwell-5vwebp`.
- Active milestone: REM-001 Gate 1. It is designated, not authorized.
- The freeze is unchanged.
- Authority is unchanged: production=NONE, live=DENIED, autonomous_deployment=DENIED.

## Known issues / risks
- Gate 1 is blocked on the owner:
  - D1, D2 and D6 need review.
  - The ARCH-001.2.1 schema needs a custody decision; it is not in Git.
  - D7 needs a definition.
  - D9 needs a specification.
- The RELSUP-001 MEDIUM findings are open. Fixing them is new source work under the freeze.
- Windows supervisor signal behaviour is not verified here.

## Remaining work
Owner decisions on:
- Gate 1 steps S1–S4;
- whether to remediate G-S1 and G-S3, and under which authorization.

## Next exact action
Read CI for the pushed head. Then the owner starts Gate 1 S1 (review D1, D2 and D6) and decides S2 (commit the ARCH-001.2.1 schema, or name another baseline).
