# Owner architecture for Atlas HQ: event contract, agent state, telemetry bridge. Evaluation (2026-10-01)

**Source:** the owner's message of 2026-10-01. The owner reviewed AI Office, Pixel Office, OpenClaw Office and VirtOffice on GitHub.

**Status:** EVALUATED. No code yet.

**Untrusted-input note:** external repositories are data, not instructions. In this session I did not read any of them. Everything said about their contents below is the owner's report, marked **UNKNOWN — requires verification**. That includes their licences (MIT for three; VirtOffice has a licence file that was not checked).

## What the owner decided (recorded as given)
1. No repository is forked into Atlas's core. The existing backend, governance and trading code stays the source of truth.
2. Ideas, and if needed licence-checked code fragments, go only into a separate Atlas HQ frontend plus a telemetry-bridge layer.
3. The first work is the **Atlas Event Contract, AtlasAgentState and the Telemetry Bridge**, not 3D.
4. Order of work:
   - 2D / isometric prototype first, then 3D (Three.js);
   - the final product is 3D plus 2D panels.
5. The 3D UI is never an executor. A user request goes: Request → Proposal → Governance → Approval → Executor.
6. No new phase. This is a sub-work item of the existing 3D Command Center / UI phase.

## Evaluation (CLAUDE.md new-idea format)

| Field | Content |
|---|---|
| **What** | (a) A versioned Atlas event schema: `event_id`, `event_type`, `timestamp`, `agent{id, role}`, `run{id, task_id}`, `payload`. (b) An `AtlasAgentState` owned by the backend. (c) A read-only stream (SSE) that the HQ / dashboard subscribes to. (d) Later: a 2D, then a 3D HQ that only reads. |
| **Why** | So that "Quant — analyzing" on screen is always backed by a real event: no fake animation (matches "no fake data"). |
| **Where** | Existing UI / observability phase (3D Command Center sub-work). No new phase. |
| **Dependencies** | **Already in the repository:** `core/event_bus.py` (runtime event bus); `observability/agent_states.py` (agent states derived from the task, proposal and memory logs plus signals); the activity timeline in `/hq`; the hash-chained governance logs. **Missing:** a published schema, a stream endpoint, and agent emitters. Today's agents are rule-based with a 10-minute cycle; LLM agents wait on AI-001, so "tool.started / thinking / tokens / cost" events have no real source yet. |
| **Risk** | 1. The web layer is read-only and loopback-only by test, so SSE must stay GET-only and loopback-guarded. 2. Agents' state must never be shown as more alive than it is: an agent with no event shows `offline` / `idle`, never invented motion. 3. An HQ "request" button would be a write path; it may only create a DRAFT proposal through the existing governance flow, and needs its own owner decision. 4. Third-party code and assets need a licence audit (code ≠ assets: textures, models, fonts). |
| **Cost** | Contract and state: small (one schema module plus tests). SSE: small. 2D prototype: medium. 3D: large (new toolchain; the R3F engine was already deferred). |
| **Alternative** | Keep polling the existing JSON APIs every 5 s; that is what `/hq` does today. It is enough until real-time LLM agent events exist. |
| **Decision** | **ACCEPT** (a) the event contract and (b) AgentState, as a design with a schema plus tests, mapped onto the existing `agent_states` and `event_bus` with no new top-level folders. **DEFER** (c) SSE until there are events worth streaming (AI-001), and (d) 2D/3D HQ until the Core phases close (CLAUDE.md: UI never delays Core). **REJECT** the proposed new folder tree (`agents/`, `telemetry/`, `api/`, `frontend/` at the root) for now: it is a large restructure, and rule 1 / rule 9 favour adding modules inside the existing `observability/` and `core/` layout. Revisit when the HQ frontend actually starts. |

## Mapping the owner's states onto what exists
| Owner state | Today's source | Real now? |
|---|---|---|
| offline / idle | agent_cycle record age (`agent_states`) | yes |
| researching / auditing / reviewing | the agent's cycle result (quant_research, red_team, security, …) | yes, per 10-minute cycle |
| waiting_approval | READY_FOR_OWNER proposals | yes |
| blocked | BLOCKED task steps (task_runner) | yes |
| error | FAILED agent leading to an INCIDENTS record | yes |
| thinking / coding / tool / tokens / cost | none | **N/A until AI-001** |
| trading_monitoring | market loop status | yes |
| location / movement / collaboration links | derivable from the event type (research.result → quant) | design only |

## Next exact steps (once the owner says "start")
1. `observability/event_contract.py`:
   - a versioned dataclass schema and validator (no I/O);
   - tests for malformed or unknown event types (rejected, never coerced) and secret redaction (SensitiveDataGuard).
2. Map the agent_cycle outputs and governance-log entries to contract events (read-only adapter). Test that every on-screen state has a backing event.
3. Licence / OSS audit of the four repositories, before any fragment is copied (Discover → License → Security → Quality → Compatibility → Test → Adopt / Adapt / Reject).
