# Final operation plan: reconcile, red-team, trial, certify, freeze (owner, 2026-09-30)

**Status:** accepted as the closing sequence. **No new features** during it.

**When it runs:** it starts only after the open CRITICAL findings are decided: F-1 (M-1), F-3 (daily loss including unrealized), F-4 (paper fills), and S1. Before that, the certification would only confirm known gaps.

## Steps

| # | Step | What it produces | What already exists |
|---|---|---|---|
| 1 | **Full architecture reconciliation** | A call graph from data to lesson; every link marked RUNTIME / TEST / CODE-only | Runtime closure plus import graph (`packaging/`); the architecture tests |
| 2 | **No-bypass audit** | A proof that only RiskEngine and ExecutionManager can cause a financially material action (agent, strategy, PaperTrader, UI, memory, research, LLM: all ✗) | `test_single_execution_authority.py` (this session), `test_intelligence_cannot_import_execution.py`, `test_web_layer_is_read_only.py`, `NEVER_GRANTED_TO_AI` |
| 3 | **Full-system scenarios** | Normal, reject, exchange failure → unknown → reconcile, crash → restart → reconcile, duplicate fill ×3, corrupted state → safe mode | Idempotency, journal and recovery tests (partial); no exchange-failure or unknown-order scenario in PAPER |
| 4 | **Red-team** | Adversarial inputs (NaN / inf / negative, future timestamps, forged events, prompt injection, malicious repos, clock drift, replay). Each case must show fail → contain → audit → safe state. | Loopback / host-header guard, stale and future-candle rejection, Decimal validation (partial) |
| 5 | **Historical digital trial** | Bull / bear / sideways / crash / recovery periods; strict t0 → t1 streaming (no look-ahead); reproducible (dataset + seed + versions) | `tools/backtest_replay.py` drives the real market loop over closed candles; there is no dataset versioning, failure injection or learning loop in the replay |
| 6 | **Learning validation** | Trade #1 → lesson; Trade #2 retrieves it; no lesson from a thin sample or a single dimension (regime, symbol, fees, slippage) | Sample-size lifecycle, look-ahead-free regime tags, contradiction; retrieval into decisions is only the BRAIN-MEM-001 caution |
| 7 | **Certification** | The table per area with IMPLEMENTED / PARTIALLY / NOT / BLOCKED plus evidence. No scores. | First version: `docs/audits/INDEPENDENT_STATUS_AUDIT_MEGA_TASKS_2026-09-30.md` (implementing-session self-audit). **The real one must be independent.** |
| 8 | **Freeze** | Freeze the architecture, dependencies, schemas and authority; set the security and test baselines; package reproducibility; declare a release candidate. After that, change enters only through Proposal → Impact → Sandbox → Tests → Security → Independent review → Owner. | The registry, proposal log and vendored-asset hashes are the base |

## After the freeze

Research, then PAPER long-run trial, then independent audit. On FAIL: fix and repeat. On PASS: small live, and only with the owner's signature. The ladder stays Paper → Shadow → Small Live (CLAUDE.md), so **Shadow comes before Small Live**. `live_authority` stays DENIED until then.

## 3D HQ in the final state

Every item shown must come from a backend event: the agent, the data, the evidence, the reasoning, the risk result, why BUY / SELL / HOLD / ABSTAIN, the order, the fill, the P/L, the lesson, the memory record, the governance event and health. Anything missing is shown as N/A.
