# ATLAS CHECKPOINT — Dashboard refusal-label CONFLICT resolved (v4.88 option a)

## Objective
Resolve the v4.88 CONFLICT `conflict_dashboard_refusal_label`. The Risk Accounting panel said rollover refusals are not audited, but since v4.88 C3 they are, as `RISK_ACCOUNTING_DAY_ROLLOVER_REFUSED`. The owner chose option (a): wire the panel to the latest REFUSED event and update the pinned test.

## Completed
- `web_app.py`:
  - The single bounded audit-tail scan (`_latest_rollover` became `_scan_rollover_events`) also tracks the latest REFUSED event of `risk_accounting_state`, and whether a PREPARED event follows it.
  - New `rollover.latest_refusal`: `reason`, the two day labels, `refused_at`, `superseded_by_later_rollover`.
  - `refusal_reason` is set only while the refusal still applies: the day is `BEHIND_TODAY`, the refusal is for today, and it is not superseded.
  - `refusal_reason_source` is one of `AUDIT_LOG`, `AUDIT_LOG_UNAVAILABLE` or `AUDIT_DISABLED_NOT_RECORDED`.
  - A reason that is not 1-64 upper-case ASCII, digit or `_` characters is published as `UNRECOGNIZED_REASON`.
- `templates/dashboard.html`: the "reddetme sebebi" row shows one of:
  - the current reason (badge plus timestamp);
  - "şu an yok" with the latest audited refusal as history;
  - why no source exists.
- Tests: the pinned `NOT_AUDITED_WARNING_LOG_ONLY` test was replaced (owner-authorized), and 25 tests were added.
- Registry v4.89 was written as a successor record. v4.88 was not edited.

## Files changed
- Commit `6d99a5b`: `web_app.py`, `templates/dashboard.html`, `tests/test_dashboard_adminlte_and_integrity_panels.py`.
- Registry commit: `governance/current/ATLAS_MILESTONE_REGISTRY_v4.89.json` and this checkpoint.
- Untouched: `core/`, the audit store, all gates, the loopback guard.

## Architecture decisions
- No import of `core` from `web_app` (L5). The event type is mirrored as a literal, like PREPARED and COMMITTED. A test asserts the literal equals `ExecutionManager`'s constant.
- There is still one scan pass over the 4 MiB tail, not two.
- "Current" versus "history" is derived only from the log order and today's day state. Nothing is inferred.

## Tests
- Environment: Linux, Python 3.11.15, dependencies from `requirements/all.txt` with constraints plus `httpx2==2.7.0`. This is not CI's hash-locked Windows py3.14 set.
- Dashboard file: 64 passed before the change, 88 passed after.
- Mutation: 10 of 10 mutants killed.
- Targeted regression: 493 passed, 12 failed, 1 skipped.
  - All 12 failures are in `tests/architecture`, and the identical 12 fail on the unchanged tree (checked with a stash).
  - Cause: Python 3.11 cannot parse the repository's PEP 701 f-strings. This is environmental.
- Chromium render against a real uvicorn server on loopback: 4 scenarios, no page errors, no dialogs.
- Full suite: NOT_RUN here. The CI result after the push is UNKNOWN until it is read.
- Independent audit: NOT_PERFORMED (STANDARD task).

## Current state
- Branch `claude/vigilant-maxwell-5vwebp`.
- Authority unchanged: production=NONE, live=DENIED, autonomous_deployment=DENIED.

## Known issues / risks
- Unaudited refusals (`JOURNAL_LOCK_UNAVAILABLE`, unreadable stored state) still appear only in the WARNING log.
- A long-persisting refusal can age out of the 4 MiB scan window. The panel reports this via `scan_truncated`.

## Remaining work
- Read the CI run for this push.
- Owner live check on a running instance.
- Pending from the previous session's options: B, the roadmap unification that closes the recorded conflicts C1 (no Phase 0–10 enumeration) and C2 (`FIN-004.1a-C1` has no status object).
- The owner's 2026-09-28 architecture message (local-first AI provider / Ollama, deterministic core independent of AI, Atlas Coder) awaits evaluation in the CLAUDE.md new-idea format. Nothing was implemented.

## Next exact action
Read the CI result for the pushed head. Then take the owner's decision on the AI-provider architecture evaluation and on option B.
