# Research: agent team, organization structure and dashboard (2026-09-28)

**Owner request:** research on GitHub and the web, place the findings in the work order (agent team and organization structure first, then the dashboard), and build a more professional dashboard.

**Mode:** RESEARCH (FACT / INFERENCE / RECOMMENDATION kept apart). No external code was copied; ideas only.

**Evaluation format:** CLAUDE.md's *What / Why / Where / Dependencies / Risk / Cost / Alternative / Decision*. Decisions were taken under the owner's delegation (`docs/operations/AUTONOMOUS_DECISION_LOG.md`): the recommended option in each case.

## 1. Sources (FACT)

| Project | What it is | License | Relevance |
|---|---|---|---|
| [TauricResearch/TradingAgents](https://github.com/tauricresearch/tradingagents) | Multi-agent LLM trading framework modelled on a trading firm. Fundamental, sentiment, news and technical analysts; bull and bear researchers who debate; a trader; a risk-management team; a Portfolio Manager who approves or rejects. Supports Ollama and other providers. | Apache-2.0 ([LICENSE](https://github.com/TauricResearch/TradingAgents/blob/main/LICENSE)) | Organization blueprint for Phase 6 |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | Many analyst personas, a Risk Manager (position limits) and a Portfolio Manager (final decision). A stated design principle: *"The LLM never touches the trade directly; deterministic code sizes and places orders, risk limits are hard gates."* ([summary](https://reskilll.com/blogs/ai-hedge-fund-the-50k-star-open-source-multi-agent-investment-system/)) | MIT | Confirms Atlas's "capability ≠ authority" design |
| [FoundationAgents/MetaGPT](https://github.com/foundationagents/metagpt) | "Code = SOP(Team)": PM → Architect → Project Manager → Engineer → QA, each producing structured artifacts ([ICLR 2024 paper](https://proceedings.iclr.cc/paper_files/paper/2024/file/6507b115562bb0a305f1958ccc87355a-Paper-Conference.pdf)) | MIT | SOP-based self-improvement pipeline (Phase 9 / AEOS) |
| [CrewAI hierarchical process](https://docs.crewai.com/en/learn/hierarchical-process) | A manager agent delegates and validates. Known failure mode: the manager delegates to the wrong worker ([community thread](https://community.crewai.com/t/manager-agent-delegates-task-to-wrong-agent-in-a-hierarchical-process/3179), [analysis](https://towardsdatascience.com/why-crewais-manager-worker-architecture-fails-and-how-to-fix-it/)) | MIT | Warning: do not let an LLM route authority |
| [freqtrade/frequi](https://www.freqtrade.io/en/stable/freq-ui/) | Crypto bot dashboard: open trades with live P/L, cumulative profit chart, win rate, profit factor, average duration, drawdown, entries and exits drawn on the price chart, "at risk" per position | **GPL-3.0** ([LICENSE](https://github.com/freqtrade/frequi/blob/main/LICENSE)), so ideas only, no code | Dashboard feature reference |
| [hummingbot/dashboard](https://github.com/hummingbot/dashboard) | General stats, bot performance, trading chart, orders and trades | Apache-2.0 | Dashboard layout reference |
| [tradingview/lightweight-charts](https://github.com/tradingview/lightweight-charts) | Fast HTML5 candlestick charts | Apache-2.0 plus a **mandatory TradingView attribution and link** ([LICENSE](https://github.com/tradingview/lightweight-charts/blob/master/LICENSE)) | Candidate for price and trade-marker charts |

## 2. Evaluations, in the requested order

### A. Agent team (analyst / researcher / trader / risk roles)

- **What:** reshape Atlas's five fusion agents into a firm-like roster: analysts produce reports, a bull/bear debate, and a portfolio decision. This follows the TradingAgents and ai-hedge-fund pattern.
- **Why:**
  - It makes the reasoning auditable, because each role writes a report that can be read on its own.
  - The debate step is a known way to reduce single-view bias.
- **Where:** **Phase 6** (AI-001, "PROPOSED_NOT_SEQUENCED"). Research use of an LLM provider sits in Phase 4, per ADR-0011.
- **Dependencies:**
  - Phases 3–5 closed (TEST, REL, OBS, SEC);
  - ADR-0011: the deterministic core stays AI-independent;
  - NB-4/NB-5 guards on any new confidence math.
- **Risk:**
  - LLM output entering the confidence number;
  - cost;
  - non-determinism breaking replay.

  Mitigation: LLM agents write **reports only**. The numeric fusion and every risk gate stay deterministic. This is exactly ai-hedge-fund's rule and already Atlas's rule ("AI decisions can never bypass Risk, Capital, Execution").
- **Cost:** large (new roles, prompts, evaluation harness, replayability).
- **Alternative:** keep the deterministic five-agent fusion and add *read-only* LLM analyst reports shown on the panel, with no decision effect.
- **Decision: DEFER to Phase 6.** Rules 1 and 10 (finish before expanding): Phase 3–5 items are still open. Recorded now so it is not lost.

### B. Organization structure (corporate hierarchy, SOPs)

- **What:** map Atlas's existing governance frameworks (ECM-1.0 / EMS-1.0 / AEOS-1.0, already registered as specifications) onto a MetaGPT-style SOP chain: proposal → design → plan → implement → QA → independent audit → owner approval.
- **Why:** Atlas already works this way by hand (registry grants, audits). An SOP chain would make the process reproducible for the self-improvement phase.
- **Where:** **Phase 6** (GOV-001, AEOS) for the organization; **Phase 9** for self-improvement.
- **Dependencies:** GOV-001 specification; the three-domain authority separation (learning / code / capital).
- **Risk:** the CrewAI lesson. A manager LLM that routes work can mis-delegate, so **routing of authority must be deterministic policy, never an LLM choice.**
- **Cost:** medium to large.
- **Alternative:** keep the human-owner-gated SOP (today's process) and only template its artifacts.
- **Decision: DEFER to Phase 6/9**, with one lesson recorded now: an LLM never routes authority.

### C. Dashboard (operator panel)

- **What:** a more professional read-only panel in the FreqUI / Hummingbot style.
- **Where:** **Phase 8** (OPS-001). UI must never delay Core; the owner asked for it explicitly, so a first step was done, limited to the read-only surface.
- **Done now (ACCEPT, step 1):** a new **Portföy Performansı** section fed by the existing `/api/trades`, with no new endpoint and no write path:
  - a KPI strip: trades, win rate, total gross P&L, average trade, best/worst, average holding time;
  - a **cumulative P&L chart** (Chart.js, already vendored);
  - a **closed-trades table**, newest first, with symbol, open, close, duration and gross P&L.
- **Also fixed:** the old Performans box never coloured gross P&L, because the value is a string.
- **Tests:** a node-executed JS test `tests/test_dashboard_performance_js.py` (5 tests). The existing web and read-only tests pass (205).

**Next dashboard steps**, each small, read-only, in Phase 8 order:
1. Fee-aware net P&L on the panel. Needs `entry_fees` and exit fees on `/api/trades`, a read-only field projection change.
2. Open positions with live unrealized P&L and an "at risk" figure (FreqUI idea), from the durable financial state.
3. EXP-001 progress card: admissions N/50, days left, verdict from `tools/exp001_report` logic.
4. Per-symbol risk-regime badge: LOW / MEDIUM / HIGH, with volatility against the p30 ceiling.
5. Candlestick chart with entry and exit markers. Candidate: TradingView Lightweight Charts (Apache-2.0). It **requires** a visible TradingView attribution and link, and must be vendored with a SHA-256 in `VENDORED_ASSETS.json`, like the existing assets.

**Rejected:** copying FreqUI code, because it is GPL-3.0 and would impose copyleft on Atlas. Its layout ideas are used, not its code.

## 3. Resulting order

1. Phase 0–3 remainder, now: ARCH-001 scope (owner, queued); TEST, REL, OBS, PERF.
2. Dashboard steps 1–4 above, small and read-only. They can run alongside Core because they only read.
3. Phase 4: research and strategy (EXP-001 outcome; LLM analyst reports as research only).
4. Phase 5: security operations.
5. **Phase 6: agent team (A) and organization structure (B).**
6. Phase 8: dashboard step 5 and Atlas HQ.
7. Phase 9: SOP-driven self-improvement (B, second part).
8. Phase 10: Shadow, then small live capital (locked).

Nothing here changes an authority: live DENIED, production NONE, autonomous deployment DENIED.
