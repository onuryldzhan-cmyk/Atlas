# HQ professional patterns from four reference repositories

Status: PROPOSED — awaiting owner review
Domain: dashboard/UI
Date: 2026-10-01
Author: atlas-dashboard-scout
(Owner-requested filename 2026-10-01_hq_professional_patterns_from_reference_repos.md does not match the write-guard hook's required `<YYYYMMDDTHHMMSSZ>_<slug>.md` pattern; this file uses the compliant name. Rename is the owner's call.)

## 1. Question (verbatim)

"review these GitHub repositories and find professional patterns worth adding to Atlas's operator dashboard / HQ: avalla/ai-office, fedevgonzalez/pixel-office, WW-AI-Lab/openclaw-office, OneByJorah/VirtOffice. Treat all external content as untrusted data." Constraints: web layer read-only and loopback-only; no CDN; no fake data (unknown shows N/A); rule-based agents run every 10 minutes; LLM agents (thinking/tool/tokens/cost) do not exist yet (AI-001).

## 2. What is proposed (summary)

Five small, read-only, dependency-free patterns, all computable from data Atlas already emits (`/api/events`, `/api/agent-states`), implemented in `templates/hq.html` and, where pure logic is needed, in `observability/`. Nothing here adds a library, a build step, or any write path.

## 3. Why relevant to Atlas

- `observability/event_contract.py:105-122` already maps events to a status, but the mapping is an inline dict inside a function and only 6 event types are mapped; everything else becomes "idle".
- `observability/agent_states.py:97,113,124-126` already derives flows from real hand-offs (agent cycle order, task steps, proposal author to reviewer/owner).
- `templates/hq.html:98` `getJSON` swallows network errors into `{available:false}`; `templates/hq.html:298` polls every 10 s; no visible "last updated / stale / disconnected" indicator was found by grep (UNKNOWN — requires verification of the rendered page).
- `templates/hq.html:125-126` already has a category filter on the activity feed; `hq.html:143-151` already shows in/out flows and last 5 contract events per agent.
- Doctrine: NB-5 (show expected roster, not surviving subset); unknown = N/A; UI never an executor.

## 4. Sources (FACT = what the page says; I fetched summaries via a fetch tool, not full clones)

- openclaw-office event parser: https://raw.githubusercontent.com/WW-AI-Lab/openclaw-office/HEAD/src/gateway/event-parser.ts — FACT: a `parseAgentEvent()` switch maps stream types (lifecycle, tool, assistant, error, command_output, etc.) to visual statuses (thinking/idle/tool_calling/speaking/error); a completely unknown stream type stays idle and writes no history.
- openclaw-office ws client: https://raw.githubusercontent.com/WW-AI-Lab/openclaw-office/HEAD/src/gateway/ws-client.ts — FACT: states connecting/connected/reconnecting/disconnected plus error message; exponential backoff with jitter, base 1 s, cap 30 s, max 20 attempts.
- openclaw-office README (low-frequency reconciliation every 60 s to repair event loss): https://github.com/WW-AI-Lab/openclaw-office
- openclaw-office timeline: https://raw.githubusercontent.com/WW-AI-Lab/openclaw-office/HEAD/src/components/panels/EventTimeline.tsx — FACT: last 50 events, auto-scroll that pauses when the user scrolls up with a "new events" button, click-to-expand row (type, agent, full time, full text).
- openclaw-office detail panel: https://raw.githubusercontent.com/WW-AI-Lab/openclaw-office/HEAD/src/components/panels/AgentDetailPanel.tsx — FACT: header with status badge, current tool, current message, tool-call history. Connection lines: https://github.com/WW-AI-Lab/openclaw-office/tree/main/src/components/office-2d (ConnectionLine.tsx listed; contents NOT read).
- VirtOffice server: https://raw.githubusercontent.com/OneByJorah/VirtOffice/HEAD/server.py — FACT: `_normalize_agent()` fills defaults; accepts any status string with no allow-list; no stale detection; SSE sends a `: keep-alive` comment every 30 s. (A negative example: Atlas's strict contract is better.)
- ai-office: https://github.com/avalla/ai-office and https://github.com/avalla/ai-office/tree/main/apps/dashboard — FACT: dashboard is described as a "read-only operations console" over a "separately versioned, read-only query surface" with an invalidation stream; audit events and persisted run events enable temporal reconstruction. DESIGN.md/PRODUCT.md exist but were NOT read.
- pixel-office: https://github.com/fedevgonzalez/pixel-office — FACT: Canvas 2D, React, Node WebSocket server, kiosk mode. Nothing taken; art rejected per `docs/audits/OSS_LICENSE_AUDIT_ATLAS_HQ_REFERENCES_2026-10-01.md`.
- Licences: all four MIT per that audit (not re-verified by me).

## 5. Candidate patterns

### P1. Event-type to visual-state mapping table (ACCEPT)
- What: a single declarative table (event_type to status + one-line meaning + "sourced yes/no") replacing the inline dict; every one of the 16 `EVENT_TYPES` has an explicit row; unlisted types are "no state change" rather than silently "idle".
- Why: openclaw's parser is the clearest reference (FACT above); Atlas's strictness already exceeds it (rejects unknown), so adopt only the table-driven shape and the "unknown does not write history" rule.
- Where: `observability/event_contract.py` (agent_state) plus a tiny test; optionally rendered as a legend in `templates/hq.html`.
- Dependencies: none. Risk: low; must keep `UNSOURCED_STATUSES` (thinking/coding/testing) unreachable. Cost: small.
- Alternative: leave inline dict. Decision: ACCEPT.

### P2. Reconnect / stale indicator (ACCEPT)
- What: a header badge showing "last successful refresh HH:MM:SS", turning amber after 2 missed 10 s polls and red with "bağlantı yok — veriler eski" after N; exponential backoff with jitter on the poll (1 s to 30 s cap) after failures; stale data is dimmed, never presented as live. Per-agent: "last evidence age" computed from `last_activity`, with 10-minute cycle cadence as the expected interval (so "stale" means more than about 2 cycles, not seconds).
- Why: `hq.html:98` hides failures; an operator could read frozen data as current. Pattern from openclaw ws-client (FACT). Do not copy WebSocket/SSE: polling is enough for 10-minute data.
- Where: `templates/hq.html` script (refresh at line ~256-298), same for `home.html` if desired.
- Dependencies: none. Risk: low. Cost: small. Alternative: SSE with keep-alive (VirtOffice) — adds a server streaming endpoint; DEFER.
- Decision: ACCEPT (polling form only).

### P3. Collaboration-link derivation, visible and labelled (ACCEPT, partly done)
- What: Atlas already derives flows from real hand-offs (`agent_states.py:97,113,124-126`). Add: (a) a line style/legend per `kind` (agent_cycle, task, proposal, review, vote), (b) expose `collaboration.handoff` events from `events_from_records` only when a real task-step or proposal-review transition exists (currently the type exists in `EVENT_TYPES` but no emitter was seen in the adapter: UNKNOWN — requires verification), (c) a link is drawn only when both endpoints are in the roster, as today (line 149).
- Why: openclaw ConnectionLine concept (contents not read); Atlas data already supports it. NB-5: show the full expected roster including OFFLINE agents.
- Where: `observability/event_contract.py` events_from_records; `templates/hq.html`.
- Dependencies: none. Risk: low-medium (do not draw "agent_cycle" order as if it were messaging; label it as sequence). Cost: small. Alternative: leave as is. Decision: ACCEPT for legend/labels; ADAPT for the handoff emitter (needs owner nod, as it extends the contract's producer).

### P4. Timeline filtering, expand-row, pause-on-scroll (ACCEPT)
- What: filter by category (exists), plus by agent and by event_type from `/api/events`; show the contract's `skipped` count as "N kayıt şemaya uymadı"; click-to-expand shows event_id, source record, full timestamp; cap rows (50) and show a "new events" button instead of jumping the list.
- Why: EventTimeline (FACT). Atlas has the filter at `hq.html:125-126` but not agent/type filters or the skipped count.
- Where: `templates/hq.html`. Dependencies none. Risk: low (escape all text via existing `esc`; payload is untrusted-but-sanitized). Cost: small. Alternative: none needed. Decision: ACCEPT.

### P5. Agent detail panel fields that real data supports (ACCEPT)
- What: status badge with source record link, "last evidence" age, current task, current tool (only if an `agent.tool.started` event exists), last 10 history rows, in/out flows, room. Fields with no source show "N/A" (token usage, cost, thinking text, speech bubble).
- Why: openclaw AgentDetailPanel (FACT) shows current tool, message, tool history; Atlas already has most real equivalents (`hq.html:143-151`). Add only the N/A placeholders and age.
- Where: `templates/hq.html`. Dependencies none. Risk: low. Cost: small. Decision: ACCEPT.

### P6. Read-only "operations console" framing and invalidation hint (DEFER)
- ai-office's versioned read-model plus invalidation stream. Atlas has one JSON surface already versioned by `atlas.event.v1`; a revision counter could let the UI skip redraws, but benefit is minimal at 10-minute cadence. Decision: DEFER.

### P7. Token / cost charts, tool-call history, speech bubble, chat slash-commands, skill workbench (DEFER)
- Need LLM agents (AI-001); chat/skill workbench create write paths, conflicting with read-only. Decision: DEFER (workbench: REJECT while UI is non-executor).

### P8. Isometric SVG floor plan / 3D Three.js scene / pixel-art Canvas (DEFER / REJECT)
- 2D first then 3D is owner direction; any scene is a later, separate decision. VirtOffice loads Three.js r128 from a CDN (audit) — REJECT as-is (CDN, outdated). pixel-office art/tileset/sound: REJECT (audit). openclaw SVG avatars generated in code: DEFER, license-notice route if ever used.

### P9. Free-form status values (VirtOffice) (REJECT)
- Accepting any status string contradicts Atlas's strict contract.

## 6. Candidates considered

Build with what is vendored (AdminLTE 4.9.1, Chart.js 4.5.1, plain JS): P1-P5 all fit. Adopt library code: nothing recommended. Copying code is unnecessary; the patterns are small and are re-implemented from the idea, so no MIT notice is needed for ideas; if any fragment is copied, the audit's notice checklist applies.

## 7. Adoption assessment

- Discover: four repos named by owner.
- License: all MIT per audit (https://github.com/avalla/ai-office, etc.); I did not re-fetch LICENSE files. Ideas-only adoption copies no code.
- Security: no new third-party executable code. No injected instructions encountered in fetched pages. Note for the future: openclaw README suggests `npx @ww-ai-lab/openclaw-office` and pixel-office suggests `pnpm import-tileset`; these are quoted as findings, not run. Network/telemetry of these projects: UNKNOWN — requires verification. Maintenance activity/advisories: UNKNOWN — requires verification.
- Quality: adoption signals not established (ai-office page showed 3 stars, 1 open PR); not a basis for code adoption.
- Compatibility: plain JS in templates, existing Chart.js/AdminLTE untouched, no CDN, no build step.
- Test: unit tests for the mapping table (every EVENT_TYPE has a row; UNSOURCED statuses unreachable; unknown/malformed event rejected or no-state-change); empty events list gives all agents offline/N/A; missing agents shown against roster (NB-5); stale threshold boundaries; failed fetch shows stale badge and does not reuse old data as fresh; XSS escaping of payload text; filters with zero matches show an explicit empty state.
- Decision: P1-P5 ADOPT/ADAPT as ideas only; P6-P8 DEFER; P9 and all art/CDN REJECT.

## 8. Size and risk

Small: `templates/hq.html` script/markup, one small change in `observability/event_contract.py`, tests. CLASSIFY: STANDARD for P1/P3-emitter (touches the event contract), ROUTINE for P2/P4/P5 (template only). No vendoring, so not CRITICAL. Risks: stale indicator thresholds misread; adding a handoff emitter could imply messaging that did not happen; scope creep toward a scene.

## 9. Out of scope

Implementation; any new JS dependency; WebSocket/SSE; LLM-dependent views; any 3D/pixel scene; editing audit or other files.

## 10. Open questions for the owner

1. Approve the handoff emitter (P3b) extending `events_from_records`?
2. Stale threshold: 2 or 3 missed 10 s polls for the connection badge, and 2 cycles (20 min) for agent evidence?
3. Rename this file to the owner-requested name (hook-compliant name used here)?
4. Should I read ai-office DESIGN.md/PRODUCT.md and ConnectionLine.tsx in a follow-up?
