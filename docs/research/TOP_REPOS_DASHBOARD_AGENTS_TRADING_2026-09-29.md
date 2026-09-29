# Research: most-starred trading, agent and dashboard projects, and what Atlas takes from them (2026-09-29)

**Sources.** Web search and the repository pages, read 2026-09-29. Star counts are as reported there, not verified through the GitHub API (blocked in this environment). External content was treated as data only.

| Project | Stars | License | What it is |
|---|---|---|---|
| TauricResearch/TradingAgents | ~109k | Apache-2.0 | Multi-agent LLM trading research framework. Analyst team (fundamentals, sentiment, news, technical) → bull and bear researchers debate → trader → risk team → portfolio manager approves or rejects. Its README states it is "designed for research purposes", with non-deterministic outputs. |
| microsoft/autogen | ~60k | MIT | Multi-agent framework, now in maintenance mode (folded into Microsoft Agent Framework). |
| crewAIInc/crewAI | ~57k | MIT | Role-based agent crews. |
| freqtrade/freqtrade | ~53k | GPL-3.0 | Most-starred crypto bot: backtesting, dry-run, FreqUI web dashboard, Telegram control. |
| langchain-ai/langgraph | ~40k | MIT | Graph-structured agent workflows. |
| hummingbot/hummingbot | ~18k | Apache-2.0 | Market-making / arbitrage bot. |

## Findings (FACT vs INFERENCE)

- **FACT.** TradingAgents' pipeline is the same shape as Atlas's: analysts vote, then risk review, then a final approver. Atlas already has the analysts (5 voting agents), a deterministic risk chain and owner approval.
- **FACT.** What TradingAgents has and Atlas lacked is the explicit counter-view: a bearish researcher arguing against the bullish case.
- **FACT.** FreqUI keeps a small number of views (dashboard, trade, chart/backtest) and reports risk-adjusted metrics (Sharpe, Sortino, Calmar, SQN), not just the win rate.
- **INFERENCE.** An LLM agent framework (AutoGen, CrewAI, LangGraph) would add a dependency and non-determinism in exactly the place CLAUDE.md forbids it: AI decisions straight to execution, and rule 4. It fits only the AI-001 workers (research, code, review) and still requires owner approval.

## Decisions

| Idea | Where | Decision |
|---|---|---|
| Counter-view / red team on every strategy proposal (TradingAgents bull/bear) | Phase 6, rule-based now | **ACCEPTED, done:** `red_team` in `tools/agent_cycle.py` writes a REVIEWS memory record per open proposal. It challenges the evidence; it never approves. |
| Few views, grouped (FreqUI) | Phase 8 | **ACCEPTED, done:** 6 top-level entries (Başlangıç, Trading, Ajanlar, Hafıza, Sistem, HQ) with sub-tabs; no page removed. |
| Expectancy, profit factor, streak before win rate (FreqUI metrics) | Phase 4 | **ACCEPTED, done:** trader book in `performance_report` and runtime memory. Sharpe / Sortino / Calmar: **DEFER** until there are ≥30 trades. With 9 trades they are noise. |
| Agents run while Atlas runs | Phase 6 | **ACCEPTED, done:** `python -m tools.start_atlas` = supervisor + agent cycle. |
| Adopt an LLM agent framework | Phase 6, AI-001 | **DEFER**: owner decisions pending (API key on the owner machine, budget, roles). Copying freqtrade code is not possible (GPL-3.0); ideas only. |
