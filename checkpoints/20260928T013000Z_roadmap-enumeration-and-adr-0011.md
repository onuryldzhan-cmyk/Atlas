# ATLAS CHECKPOINT — Phase 0–10 roadmap enumeration (C1 closed), C2 evidence, ADR-0011

## Objective
This is the owner's option "B + ADR" (2026-09-28). It does three things:
- Records the owner's 0–10 vision as the official roadmap, which closes registry conflict C1.
- Resolves or records C2.
- Writes the owner's AI architecture principles as an ADR.

It is documentation only.

## Completed
- `governance/ATLAS_ROADMAP_PHASE_0_10_ENUMERATION_v1.0.md`:
  - Phases 0–10, verbatim from the owner's §95, with scope drawn from the owner's vision sections.
  - The owner's stated current focus: Phases 2–3.
  - The relationship to the REM-001 gates, the capital ladder, the master plan and AMP-001.
  - An advisory crosswalk labelled INFERENCE.
  - The C2 CONFLICT with three options.
- `docs/adr/0011-ai-independent-deterministic-core.md`:
  - D1: the deterministic core never depends on AI.
  - D2: AI is reached only through a provider-neutral layer, with local Ollama as the intended default.
  - D3: Claude Code is a development tool.
  - D4: AI output is always a proposal.
  - D5: Atlas Coder only through the governed pipeline with two human approvals, a sandbox, and gates that are not the author.
  - Accepted as principle; implementation is not authorized.
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.90.json`, block `roadmap_enumeration_and_ai_independence_adr_result`:
  - C1 RESOLVED.
  - C2 OPEN_EVIDENCE_RECORDED_OWNER_DECISION_REQUIRED.
  - ADR-0011 recorded.
- The clone was unshallowed (`git fetch --unshallow`, read-only) to gather the C2 evidence.

## Files changed
The three files above plus this checkpoint. No source, test or configuration file changed.

## Architecture decisions
- ADR-0011 D1–D5 (principle).
- The 0–10 phase axis is canonical. The other frameworks are kept as separate axes and not superseded.

## Tests
None needed; there is no code change.
- Checked that no test references `docs/adr` content beyond a comment.
- Checked that `observability.panel_sources.resolve_current_registry()` resolves v4.90 as head, with the chain intact.
- Checked that the cited test line ranges in the ADR (`148-153`, `173-179`) match the files.

## Current state
- Branch `claude/vigilant-maxwell-5vwebp`.
- `active_milestone` is still `FIN-004.1a-C1`.
- The freeze is unchanged (PAUSED_PENDING_REM_GATE_1).
- Authority is unchanged: production=NONE, live=DENIED, autonomous_deployment=DENIED.

## Known issues / risks
- C2 is open: FIN-004.1a-C1/C2/C3 are undefined at every revision, and their origin (registries v4.0–v4.17) is UNKNOWN.
- AMP-001 counts phases 0–8 and its profile document is absent from all history. Recorded, not resolved.
- The crosswalk is inference. Reconnect and Supervisor status is UNKNOWN (not verified).
- The CI result for `ee50b63` (the dashboard refusal-label push) has not been read.

## Remaining work
- The owner decides C2: (a) supply the definition, (b) retire the IDs and re-point, or (c) leave open.
- Deferred Improvements:
  - A CLAUDE.md pointer to the enumeration record.
  - A static test enforcing ADR-0011 D1 across all core modules.
- Next roadmap work per the owner's focus (Phases 2–3), and REM-001 Gate 1 when authorized.

## Next exact action
The owner decides C2. Separately, read the CI result for the pushed head.
