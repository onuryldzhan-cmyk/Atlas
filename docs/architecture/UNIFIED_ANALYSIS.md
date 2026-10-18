# Unified analysis: TradingAgents + Court Skill concepts in one Atlas workflow (Task 017)

Status: implemented outside the trading runtime, advisory only. Registry v5.101, Phase 4 RESEARCH
(research department, source and evidence system, experiment manager) with its decision-memory part in Phase 7.
`production_authority=NONE`, `live_authority=DENIED`. Nothing in this package can place, size or approve an order,
or change a gate, threshold or parameter.

## 1. What it is

`tools/unified_analysis/` analyses one coin at one cutoff and returns a classified, evidence-backed report:
`BULLISH_SETUP`, `BEARISH_SETUP`, `NEUTRAL_RANGE`, `INSUFFICIENT_EVIDENCE` or `RISK_REJECTED`. Each report comes
with its confidence and the basis for it, its scenarios and their invalidation conditions, objections, verification
checks, risk findings and unresolved questions. Every report is recorded as a prediction before its outcome exists,
and is scored later against the market.

```
python -m tools.unified_analysis analyze --symbol BTCUSDT            # live Binance, no model
python -m tools.unified_analysis analyze --symbol BTCUSDT --ai       # + model narrative and court
python -m tools.unified_analysis replay --symbol BTCUSDT --archive <market_data.sqlite3> --start ... --end ...
python -m tools.unified_analysis settle [--archive <market_data.sqlite3>]
python -m tools.unified_analysis calibration
```

## 2. Workflow

| Step | Module | What happens | Branch |
|---|---|---|---|
| 1 data | `market_intelligence.py` | Binance spot klines for 1h, 4h and 1d (or the market archive, read immutably). They are validated by `core.market_cycle.closed_bars`: closed bars only, no gap, duplicate, stale feed or non-finite close, and consistent OHLC. Funding, Fear & Greed and treasury yields come from `atlas_finance.market_data`. Provenance: one `SourceRef` per input, carrying a SHA-256 of the bars used. | Unusable 1h data ends the run as `INSUFFICIENT_EVIDENCE` with **zero** specialist and model calls. |
| 2 specialists | `specialists.py` | technical, regime, liquidity/structure, derivatives, sentiment, macro (all deterministic), plus an optional model narrative. | No input means ABSTAIN; an exception means FAILED. |
| 3 intake verification | `verification.py` | Every numeric claim is recomputed with `indicators.py`. | A wrong deterministic number fails the run. A wrong or unverifiable model number drops the finding. |
| 4 scenarios | `scenarios.py` | Bull, bear and neutral, each scored by **independent** evidence groups (one data stream counts once), each with invalidation. | A margin below 0.3 means NEUTRAL is primary. |
| 5 review | `review.py` | Deterministic prosecutor, plus an optional model court (prosecutor and three lens jurors). | No directional thesis means the court does not sit. |
| 6 report verification | `verification.py` | No look-ahead, freshness, scenario references, contradiction, invalidation. | Contradiction means `INSUFFICIENT_EVIDENCE`. |
| 7 decision and risk | `decision.py` | `SignalFusion` over the expected roster (NB-4/NB-5), then review penalties, then the calibration cap, then the risk gate. | The risk gate runs last and has no override. |
| 8 experience | `experience.py` | A PREDICTION record goes in first. After the horizon, an OUTCOME record is added that references the prediction's hash. | Before the horizon has closed, the record stays PENDING. |

## 3. Layer contracts

**Specialist** (`specialists.Specialist`). Each specialist has a `name`, a `responsibility`, declared `inputs` and
`analyze(snapshot) -> SpecialistReport`. Each finding carries:

- its `kind`: `OBSERVED_FACT`, `INTERPRETATION`, `HYPOTHESIS` or `PREDICTION`;
- a `stance` and a `strength` in 0..1 (an ordinal weight, not a probability);
- the `SourceRef` ids it cites;
- its numeric `claims`, each a metric, a timeframe and a value;
- an `independence_group`.

A specialist never fetches data. It fails by ABSTAIN with a reason, or by FAILED, which the pipeline catches. Both
count as a *missing* source in fusion (NB-5), never as agreement.

| Specialist | Input | Output | Weight in the live roster |
|---|---|---|---|
| technical | 1h, 4h and 1d bars | EMA20/EMA50 structure, RSI(14), stretched-RSI hypothesis, timeframe alignment | 1.0 |
| regime | 1h, 4h and 1d bars | `core.market_cycle.classify` per timeframe; the anchored regime, bounded the same way in both directions | 1.0 |
| liquidity | 1h bars | 24h traded value, relative volume, ATR %, position in the 24-bar range | 0.5 |
| derivatives | funding | crowded long or short, as weak contrarian context | 0.5 |
| sentiment | Fear & Greed | extremes only, weak contrarian, market-wide | 0.5 |
| macro | US treasury | a 10-year move of 25 bp or more, weak | 0.5 |
| narrative (optional model) | verified findings | at most 4 interpretations or hypotheses. It must cite findings, may never state a fact, and its strength is capped at 0.3 | outside the roster |
| news, on-chain | none | declared `NO_PROVIDER`; reported as gaps, never simulated | n/a |

**Rosters.** The `live` roster is all six deterministic specialists. Atlas holds no point-in-time history of funding,
sentiment or macro data, and using today's value for a past cutoff would be look-ahead. An archive replay therefore
uses the declared `hist` roster: technical, regime and liquidity. The roster is recorded in every report's
`confidence_basis`, and calibration keys are `<roster>:<classification>`, so the two rosters are never pooled.

**Confidence.** Confidence is computed in four steps; each one only ever lowers it:

1. **Fusion bound.** Confidence starts as the `SignalFusion` worst-case agreement bound: each missing source counts
   fully against.
2. **Review penalty.** Then 0.10 is subtracted for each MAJOR objection.
3. **Calibration cap.** Next, the confidence is capped. The cap is the Wilson 95 % lower bound of the measured hit
   rate, or 0.50 while the class is UNCALIBRATED.
4. **Threshold.** Finally, a directional result below 0.20 becomes `INSUFFICIENT_EVIDENCE`.

It is never a probability: `calibrated_probability` stays false.

**Risk gate.** Any of the following rejects the result, whatever the fusion and the jury said:

- a restrictive anchored regime (`UNKNOWN`, `PANIC` or `HIGH_VOL`);
- 24h traded value below 5,000,000 quote units, or unknown;
- 1h ATR above 3 % of price, or unknown;
- any BLOCKING objection.

## 4. Adversarial review: what was taken from Court Skill

The following concepts were adopted:

- **Separate prosecutor and judge roles.** The case file holds only the structured record and never an opinion.
- **Lens jurors.** Each juror runs in its own call and never sees the others: Risk Manager, Statistician and
  Market-Structure Trader, adapted from Court Skill's twelve generic lenses.
- **"Would flip if".** These lines are recorded as unresolved questions.
- **A failed juror is `NO VOTE`.** No vote is ever written in its place.

These were deliberately changed:

- **The vote is never the verdict.** A majority is not verification (task rule). A rejecting majority adds one MINOR
  objection; only *cited* prosecutor charges become MAJOR objections. The deterministic prosecutor always runs, and
  only it can raise a BLOCKING objection (a restrictive regime).
- **Independence is not assumed.** All jurors may run on one model; the record states that they are perspectives,
  not independent samples.
- **Court Skill's runtime is not used.** Its `.court/` files, sub-agent waves and twelve-juror default are not
  imported. The court is three gateway calls plus the prosecutor, bounded by `--max-calls`.

## 5. What was taken from TradingAgents

The following concepts were adopted, with no code copied:

- analyst roles with a report each;
- bull, bear and neutral scenario construction from analyst output;
- separate risk review;
- an append-only decision log, settled after a holding window and scored against a benchmark;
- a decision nobody can read is `REVIEW`, never Hold: Atlas uses ABSTAIN or `INSUFFICIENT_EVIDENCE`;
- one decision per (ticker, date), so a re-run cannot count twice;
- entry priced from information available at the decision.

The following were not adopted, with the reason for each:

| Upstream component | Reason |
|---|---|
| LangGraph / LangChain orchestration, `llm_clients/*` | A second orchestration engine and a second model path. ADR-0011 and `tools/ai_gateway.py` make the gateway the only model path. The dependencies are not installed and are not locked in `requirements/`. |
| `dataflows/*` (yfinance, Alpha Vantage, SEC, FRED, Reddit, StockTwits) | Stock-market vendors. They provide no reliable Binance spot or futures data; Atlas's own providers are used instead. |
| Trader / portfolio-manager agents | They emit trade ratings and positions, which an analysis platform must not do (capability is not authority). |
| `TradingMemoryLog` (markdown), reflection prompts | Replaced by the hash-chained `core.durable_append_log` ledger. Model reflections are not stored as learned knowledge. |
| pandas 3 / stockstats indicators | Replaced by `indicators.py` (stdlib) and `core.market_cycle`, so verification and specialists share one trusted implementation. |

## 6. Provenance

| Project | URL | Commit inspected | License | Use |
|---|---|---|---|---|
| TradingAgents | https://github.com/TauricResearch/TradingAgents | `e8f5503e9b86d5c2710b0c76b1f686703968c9df` (2026-10-16) | Apache-2.0 | concepts only; no file, function or prompt copied; nothing imported or executed |
| court-skill | https://github.com/alexyc9381/court-skill | `2abd32db25783720faf2589b456de944534f611d` (2026-10-03) | MIT | concepts only; juror lenses rewritten for crypto; nothing imported or executed |

Both repositories were cloned into a session scratch directory and read; neither was installed or run. No local
modification of upstream code exists, because none is vendored.

## 7. Storage layers

| Layer | Where | Mutability |
|---|---|---|
| Raw observations | Binance or the market archive (`market_data.sqlite3`); referenced by SHA-256 digest | not copied |
| Immutable audit evidence | `<state>/research/unified_analysis/experience.jsonl`, PREDICTION records | append-only, hash-chained, fsync'd |
| Validated experience | the same ledger, OUTCOME records referencing the prediction hash | append-only; one per prediction |
| Analytical report | `<state>/research/unified_analysis/reports/<id>.json` | a readable copy; the ledger is authoritative |
| Long-term knowledge | the governed memory log (`atlas_org`) by owner decision | not written automatically (deferred) |

The model calls' usage ledger is `<state>/research/ai_usage.json`, shared with the other gateway agents.

## 8. Failure modes

| Failure | Behaviour |
|---|---|
| Binance or archive unavailable | Timeframe `FETCH_FAILED` with its reason. If the 1h timeframe is affected: `INSUFFICIENT_EVIDENCE`, no model call. |
| Gap, duplicate, stale bar, NaN or inconsistent OHLC | That timeframe is UNUSABLE with its reason; nothing is interpolated. |
| Context provider down, malformed, stale or after the cutoff | Its specialist ABSTAINs; it is a missing source in fusion and a MINOR objection. |
| Specialist raises or returns garbage | FAILED; missing source; recorded as a non-blocking check. |
| Specialist states a wrong number | Blocking verification failure; `INSUFFICIENT_EVIDENCE`. |
| Model unavailable, refusing, over budget or malformed | Narrative ABSTAIN, court ABSTAINED; the deterministic result stands. |
| Model invents a number, a fact or a citation | The finding or charge is dropped and recorded; the result cannot move. |
| Strong bull and strong bear evidence | `INSUFFICIENT_EVIDENCE` (contradiction). |
| Ledger edited, reordered or torn | HALT (exit 3); nothing is appended. |
| Re-run of a recorded analysis | Identical: no-op. Different: refused (exit 4); the first one stands. |

## 9. Cost and latency

- **Deterministic run.** Zero model calls. Measured in the test suite: the pipeline runs in milliseconds on 900
  synthetic bars. A live run adds three kline requests plus three context requests to public endpoints.
- **`--ai` run.** At most `--max-calls` model calls (default 5: 1 narrative, 1 prosecutor, 3 jurors), each through
  `tools.ai_gateway.ask` at the gateway's default model and effort. The gateway's duplicate cache and its per-agent
  runaway ceiling (12 calls per rolling 5 hours for `unified_analysis`) bound it, which means at most about two
  `--ai` analyses per window. The cost is the gateway's measured `cost_usd` on the API backend; on the subscription
  backend Atlas cannot see the spend (UNKNOWN). Each report records its calls, cost and per-stage latency in
  `metrics`.

## 10. Limitations (UNKNOWN until measured)

- **Uncalibrated defaults.** Every threshold and weight is an uncalibrated default: specialist strengths, roster
  weights, the 0.3 scenario margin, the 0.10 penalty, the 0.50 cap, the 5M liquidity floor and the 3 % ATR ceiling.
  No predictive skill is claimed. Calibration needs at least 30 settled, non-overlapping predictions per class, with
  both walk-forward halves above a 0.5 hit rate.
- **Cost model.** The round-trip cost charged before a direction counts is 0.3 % (0.1 % fee and 5 bps slippage per
  side). That is Atlas's estimate, not a measured figure.
- **Missing data.** News and on-chain data are absent. Funding, sentiment and macro data have no history, so archive
  replays use the reduced `hist` roster.
- **Court independence.** Model jurors are not statistically independent. The court's usefulness has not been
  measured.
- **Benchmark.** The benchmark is BTCUSDT alone; analyses of BTC itself have zero excess by construction.
- **Not wired anywhere else.** The package is not scheduled in `tools/agent_cycle.py`, not shown on the dashboard
  and not written into the governed memory log (owner decisions, deferred).
