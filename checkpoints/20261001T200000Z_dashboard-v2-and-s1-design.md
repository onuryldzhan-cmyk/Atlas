# ATLAS CHECKPOINT — 2026-10-01: Dashboard v2 + S1 step 2 design

## Objective
Owner: "continue the whole roadmap; my tasks come later."

## Completed (all pushed, branch claude/exp001-on-owner-lineage)
- `/postmortem` page: read-only, from `/api/learning`, with a client-side CSV export.
  - Linked from `/trading` and from the Ctrl+K palette.
  - Registered in the loopback guard list.
- `/decisions` now shows the decision trace as numbered steps 1–6.
  - Step 6 states plainly that the execution chain is not shown on this page.
- Ctrl+K navigation palette in the shared sidebar. Navigation only: no fetch, no form.
- S1 step 2 design: `proposals/2026-10-01_s1_step2_risk_bucket_persistence_DESIGN.md`. It recommends option B (a sidecar file; the financial state is untouched). Not implemented.

## Tests
- Full suite 6182 passed after the post-mortem commit.
- Later commits ran the targeted page tests: 41 passed.

## Remaining (in order)
1. **Owner decisions:**
   - S1 design A or B;
   - F-3/F-4 switch-on;
   - regime filter once SC-* records arrive;
   - independent final audit.
2. **Order state machine enforcement inside ExecutionManager.** CRITICAL: write the design first, the same way as S1.
3. **Remove the old top navbars.** Move their sub-links (governance/research) into the pages.
4. **Density modes.** Low priority.
5. **AI-001 (LLM agents)** waits on the owner's API work.

## Next exact action
Write the order-state-machine enforcement design (`core/execution_manager.py`, existing state machine module). Do not code it before approval.
