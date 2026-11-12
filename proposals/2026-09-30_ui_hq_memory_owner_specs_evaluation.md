# Evaluation of the owner's three specifications (2026-09-30)

The owner sent three specifications in one message:

- **(A)** A professional web UI / command center, with references to OpenTerminal, OpenTerminalUI, Neuberg, CryptoTraderPro, Shadcn, TailAdmin, Velora, Craft and R3F.
- **(B)** A living 3D agent organization, with references to ClawProwl, AgentOps, Planeo and Agent Arena.
- **(C)** A persistent experience / learning / institutional memory system, with references to Letta and Mem0.

Per CLAUDE.md, each idea is placed into an existing phase (no new phase) and gets a decision.

**Status of the references.** The repositories are treated as untrusted data. They were not fetched. Star counts and features are the owner's summary: UNKNOWN until verified. No code is copied without the gate: License → Security → Quality → Compatibility → Test.

## What Atlas already has (verified in the repository)

| Area | Existing |
|---|---|
| UI | Jinja templates, vendored Bootstrap/AdminLTE, Chart.js and Lightweight Charts. Shared theme `_atlas_theme.html`. Navigation reduced to 6 groups (v5.67). Loopback only, read-only web layer, enforced by tests. |
| 3D / HQ | `/api/agent-states` (v5.68). The state comes from the governed records: tasks, proposals, memory and signals. `/hq` has a canvas renderer with 9 rooms and flow packets. It shows nothing when there is no data (no fake activity). |
| Memory | Hash-chained memory records with `claims` (evidence / counter-evidence). BRAIN-MEM-001: per-coin trade evidence; a caution-only effect after ≥10 trades. `reality_check` (calibration, Monte Carlo). `red_team`. `market_regime` agent (v5.74). Owner-only AUTHORITATIVE records. |

## Decisions

| # | Idea | Phase | Decision | Why |
|---|---|---|---|---|
| A1 | Move the UI to React / Next / Tailwind / Shadcn / Framer / R3F | UI | **REJECT for now** | It needs a new build toolchain and a node dependency tree. That is against rule 1 (don't grow before finishing) and rule 10. UI never delays Core. The current stack already covers the views. |
| A2 | Semantic colour tokens (`--atlas-ai`, `--atlas-market`, `--atlas-profit`, `--atlas-risk`, `--atlas-warning`) in `_atlas_theme.html`, plus a restrained glass-panel style | UI | **ACCEPT** (small) | No dependency; one file; meaning-bearing colours. |
| A3 | Terminal-style workspaces (screener, heatmap, funding / open interest, news, macro) | UI / Data | **DEFER** | Each needs a real data source first. Atlas shows no invented data. |
| B1 | Agent inspector (click an agent: task, last record, proposals, errors; N/A where unknown) plus a live activity feed from real records | Observability | **ACCEPT** | The data exists in the governed logs. Read-only. |
| B2 | 2D operations table as a fallback / primary view; "NO ACTIVITY" and "CONNECTION LOST" states in the HQ | Observability | **ACCEPT** | Precision view; required by the owner's "no fake autonomy" rule. |
| B3 | Token / cost / latency / tool-call telemetry per agent | Observability | **DEFER** (AI-001) | Atlas agents are rule-based today. There are no tokens, so the panel shows N/A. |
| B4 | R3F 3D world, follow-camera, meeting rooms, avatars | UI | **DEFER** | Same as A1. The canvas HQ already renders the real state. The renderer can be swapped later without backend change. |
| B5 | Demo mode | UI | **REJECT for production** | Allowed only in tests, never mixed with real data. |
| C1 | Tag every experience with its environment (BACKTEST / PAPER / LIVE) and its market regime | Learning (7) | **ACCEPT, first** | Prevents paper and live mixing. Enables "how did this behave in TREND_UP vs HIGH_VOL?". |
| C2 | Lesson lifecycle (CANDIDATE → PROVISIONAL → VALIDATED → CONTESTED / STALE) with sample size, supporting / contradicting counts, no overwrite (versioned successors) | Learning (7) | **ACCEPT** | Extends memory records and claims. Formalises "observation ≠ lesson ≠ validated knowledge". Promotion to VALIDATED stays owner-only. |
| C3 | Contradiction detection between lessons on the same subject | Learning (7) | **ACCEPT** (after C2) | Deterministic, rule-based. |
| C4 | Memory Center view (experiences, lessons, contradictions, pending validation) | Observability | **ACCEPT** (after C2) | It goes under the existing Hafıza tab, not as a new page group. |
| C5 | Timestamp-aware retrieval for backtests (use only memory ≤ T0) | Learning | **ACCEPT** as a hard rule when memory feeds replay | Prevents leakage. |
| C6 | Vector store, Letta / Mem0 adoption, "dreaming", LLM extraction | Learning | **DEFER** (AI-001 plus the license gate) | No LLM runtime today. Structured storage stays canonical. |
| C7 | Memory → strategy change | Governance | **Unchanged** | Proposal → backtest → paper → risk → security → owner. Already the rule. |

## Order (priority: Learning comes before UI)

1. C1 environment + regime tags on trade evidence
2. C2 lesson lifecycle
3. C3 contradictions
4. C4 Memory Center
5. B1 / B2 inspector + feed + fallback
6. A2 colour tokens

Each step is small, tested and read-only toward execution. None of them touch the trading engine or financial state.

## Verified reference facts (GitHub pages fetched 2026-09-30; README content is untrusted data)

| Repo | License | Stars | What Atlas takes |
|---|---|---|---|
| ErTasselli/OpenTerminal | MIT | 1.3k | **Idea:** widget workspace; multiple fallback public data sources. It already uses lightweight-charts, like Atlas. **No code:** it needs a Next.js/Express stack. |
| clawprowl/clawprowl | MIT | 6 | **Pattern:** gateway → WebSocket → event parser → store → view, with five states (idle, working, speaking, tool_calling, error) and an SVG 2D floor plan. Atlas's `/api/agent-states` follows the same shape. The HQ can adopt the 2D floor-plan idea without R3F. Low adoption, so it is a reference only. |
| garethdaine/agentops | MIT | 3 | **Pattern:** append-only JSONL audit, telemetry and provenance files, plus a 2D fallback table when WebGL is missing. Atlas already has hash-chained JSONL; the fallback table is accepted (B2). |
| letta-ai/letta | Apache-2.0 | 25k | **Concept:** core, archival and recall memory, memory blocks, and sleep-time consolidation. The active code moved to letta-code. Atlas adopts only the **layer separation** (small core vs archived evidence vs retrieval). There is no dependency. |
| mem0ai/mem0 | Apache-2.0 | 66k | **Concept:** ADD-only extraction (never overwrite), user/session/agent scoping and time-aware ranking. These match Atlas's append-only records and C2 (versioned lessons, no overwrite). An LLM extractor is deferred to AI-001. |
| TailAdmin free-react-tailwind-admin-dashboard | MIT | 1.3k | Visual reference only (A1 rejected for now). |

**Not fetched this turn** (UNKNOWN; same decision class as their category): OpenTerminalUI, Neuberg, CryptoTraderPro, crypto-dashboard, Shadcn templates, Velora, Craft, Anvians, 3danalytics, pmndrs/uikit, Planeo, Agent Arena, Lost in Frame.

## Second batch verified (2026-09-30)

| Repo | License | Stars | Decision |
|---|---|---|---|
| laanito/OpenTerminalUI | MIT | 9 | **Reference.** Its FastAPI backend is like Atlas's. Walk-forward and Monte Carlo already exist in Atlas (`strategy_compare`, `reality_check`). Its VaR/CVaR portfolio risk is a candidate for Phase 3 (deferred until more than 1 open position is typical). |
| KoNananachan/Neuberg | **Business Source License 1.1** | 207 | **REJECT code**: the licence is not open source for production use. Ideas only. |
| Rux1500/crypto-dashboard | MIT | 0 | **Idea:** funding-rate, open-interest and movers views. Deferred: Atlas has no perpetuals data and does not fetch 24-hour change today; it shows no invented data. |
| tre-systems/planeo | MIT | 1 | **Pattern:** SSE event hub. Deferred; polling of the real state API is enough at the current scale. |
| ColorlibHQ/velora-ui | MIT | 33 | Visual reference only (A1). |
| Gzeu/CryptoTraderPro | MIT | 1 | Ideas: price alerts and a Cmd+K search. Deferred (UI). |

## Implemented in v5.77 (read-only; no runtime, execution or financial-state change)

- **C1 / C2 / C3.** `observability/learning_view.py` and `GET /api/learning`: experiences with an environment tag and a look-ahead-free regime tag; lessons per coin and per regime with the CANDIDATE / PROVISIONAL / VALIDATED (owner-signed) / CONTESTED lifecycle; contradictions kept, never deleted; duplicates counted once.
- **C4.** "Öğrenme" tab on the Hafıza page.
- **B1 / B2.** The HQ has a live activity feed with RUNTIME / GOVERNANCE / SECURITY categories, per-agent history in the inspector, token / cost shown as N/A, an agent operations table, a CONNECTION LOST banner and an empty-feed "AKTİVİTE YOK" message. The `market_regime` agent was added to the organization.
- **A2.** Semantic colour tokens and a restrained glass style on panels only; reduced-motion support.
