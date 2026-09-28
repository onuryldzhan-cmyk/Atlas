# ATLAS CHECKPOINT — BUY risk-bucket / confidence-ceiling diagnosis (read-only)

## Objective
Explain why nearly every BUY is `risk_level=HIGH` and rejected `CONFIDENCE_BELOW_POLICY`,
while SELLs are MEDIUM with confidence up to 85.4. Read-only: no code, config, threshold or
vote change; nothing pushed or committed.

## Completed
1. Traced where `risk_level` is produced (FACT, cited below).
2. Traced final confidence (AgentFusion) and the separate ConfidenceEngine value that feeds risk.
3. Computed BUY ceilings for three macro scenarios and the SELL case from the real formulas.
4. Point 2 (real bucket distribution from `C:\AtlasState`): **UNKNOWN — requires verification.**
   That directory is on the owner's Windows machine and is not reachable from the cloud
   session that produced this checkpoint. A read-only tabulation script is given below.
   `data/ai_decisions.json` in the repo is July-2026 output of a retired pipeline and is not evidence.

## Findings

### 1. Where risk_level comes from (FACT)
- `ai/core/atlas_brain.py:421-430` — `ConfidenceEngine.calculate(agent_results, reasoning,
  {"level": "MEDIUM"}, expected_agent_count=5)`. The risk input is a hard-coded MEDIUM.
- `ai/core/atlas_brain.py:447-449` — `AdvisoryRiskScorer.calculate(confidence=confidence_result.value)`.
  `volatility` and `market_health` are **never passed** and default to 0.5.
- `ai/core/intelligence/risk_engine.py:173-185` — `score = 0.5(1-c) + 0.3·vol + 0.2·(1-health)`
  = `0.75 − 0.5c` with the defaults. `:227-258` — LOW <0.25, MEDIUM <0.50, HIGH <0.75, else CRITICAL.
- `ai/core/intelligence/decision_builder.py:114-118` — `risk_level = risk.level`.
- `core/market_loop.py:1745-1750` → `core/risk_engine.py:455, 494-496` — that level selects the
  bucket; policy `core/risk_engine.py:147-149`: LOW 0.60 / MEDIUM 0.70 / HIGH 0.80.

Consequences (derived from the above):
- **LOW is unreachable by construction** (needs c > 1.0).
- **MEDIUM iff c > 0.50; HIGH iff 0 < c ≤ 0.50.**
- The Risk agent's volatility regime (`analysis/world_analysis_engine.py:505-533`) **does not reach
  risk_level at all**; it only casts a fusion vote (LOW/NEUTRAL→HOLD 0.50, HIGH→SELL 0.25,
  `:98-101`). "Risk agent LOW, bucket HIGH" is therefore not a contradiction in the code — the two
  are unrelated quantities.

`c` (ConfidenceEngine, `confidence_engine.py:147-159, 216-321`):
`c = 0.50·A + 0.35·R − 0.15·0.20`, where
- `A` = (count of the most common vote action) / 5 — vote **counts**, not scores; denominator is
  the full configured roster (NB-5 guard, `:307-321`), so an excluded agent (sentiment) counts
  against agreement.
- `R` = reasoning-engine confidence (0..1), `reasoning_adapter.py:187-205`.

Hypothesis (a) CONFIRMED in a specific form: HIGH is near-structural for BUYs because a split vote
(BUY,BUY,HOLD,SELL) gives A = 2/5, so c = 0.17 + 0.35R, which is MEDIUM only if **R > 0.943**.

### 3. Final confidence (FACT, `ai/core/intelligence/agent_fusion.py`)
- Weights `:110-132`: technical .40, momentum .20, risk .20, macro .10, sentiment .10.
- Masses `:670-705`: BUY vote adds `score·w`; SELL adds `(1−score)·w`; HOLD adds `0.5·w`.
- `confidence = winning_mass / (total + missing_weight)` `:902-931`; an absent agent is charged its
  full weight (M-2 / NB-4 monotonicity). Percent conversion: `decision_builder.py:94-100` (×100, 2dp).
- Floor `:166-169, 639-657`: ≥3 participants and ≥50% weight coverage, else HOLD 0.0.
- Momentum range `:1090-1139`: 0.5 ±0.20 (trend) ±0.10 (RSI) → max 0.80.

BUY with the recorded votes (tech 0.85, momentum 0.70, risk HOLD 0.50, sentiment excluded):

| Scenario | Final confidence | Ceiling (tech 1.0, mom 0.80) | Vote-count A | risk_level |
|---|---|---|---|---|
| (a) Macro SELL 0.25 (today) | **63.58** | 67.07 | 0.40 | HIGH unless R > 0.943 |
| (b) Macro HOLD 0.50 | **65.75** | 69.14 | 0.40 | HIGH unless R > 0.943 |
| (c) Macro excluded | **61.54** | 65.12 | 0.40 | HIGH unless R > 0.943 |
| (ref) Macro BUY 0.75 | 73.51 | 76.05 | 0.60 | MEDIUM if R > 0.657 |
| (ref) Macro BUY + sentiment BUY 0.75 | — | 87.65 | — | — |

Arithmetic, scenario (a): buy = .85·.40 + .70·.20 = .48; hold = .50·.20 = .10; sell = .75·.10 = .075;
denominator = .655 + .10 (sentiment missing) = .755; .48/.755 = 0.6358.

Hypothesis (b) PARTLY TRUE: Macro SELL costs ~2 points versus HOLD. It is not the binding
constraint. With the Risk agent voting HOLD (it can never vote BUY) and sentiment absent, **no BUY
can reach 80 under any macro vote** (max 76.05), and none can reach MEDIUM's 70 unless Macro votes
BUY. Excluding Macro is *worse* than a SELL vote (61.54 < 63.58) because of the M-2 absence charge.

### 4. Why SELL differs (FACT + arithmetic)
Recorded SELL votes: tech 0.40, momentum 0.40, risk 0.25 (HIGH regime), macro 0.25.
sell = .60·.40 + .60·.20 + .75·.20 + .75·.10 = .585; denominator .585 + .10 = .685; **.585/.685 = 85.40**
— reproduces the dashboard value exactly, confirming the model.
Asymmetry sources:
1. A SELL vote's mass is `1 − score`: "weak-looking" 0.25/0.40 scores are 0.75/0.60 conviction.
2. The Risk agent can vote SELL but never BUY; Macro votes SELL in the current yield regime. SELL
   collects all four available agents, BUY at most two.
3. Four SELL votes → A = 0.80 → c = 0.37 + 0.35R → MEDIUM whenever R > 0.371.
4. Note: `core/risk_engine.py:474-481` — a SELL only passes as reduce-only risk reduction; a
   non-reducing SELL is rejected `NON_RISK_REDUCING_SELL` before the bucket check. SELL bucket
   confidence is therefore not the gate in practice.

### 2. Tabulation script (read-only; run locally, not added to the repo)
```python
import json, pathlib, collections, sys
root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\AtlasState")
rows, seen = [], set()
for p in root.rglob("*"):
    if p.suffix not in (".jsonl", ".json") or not p.is_file():
        continue
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError:
        continue
    lines = text.splitlines() if p.suffix == ".jsonl" else [text]
    for line in lines:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        stack = [obj]
        while stack:
            o = stack.pop()
            if isinstance(o, list):
                stack.extend(o); continue
            if not isinstance(o, dict):
                continue
            stack.extend(o.values())
            a, r, s = o.get("action"), o.get("risk") or o.get("risk_level"), o.get("symbol")
            if isinstance(a, str) and isinstance(r, str) and isinstance(s, str):
                key = o.get("request_id") or o.get("decision_id") or (s, a, r, o.get("timestamp"), o.get("confidence"))
                if key in seen:
                    continue
                seen.add(key)
                rows.append((a.upper(), r.upper(), s.upper()))
by_action = collections.Counter((a, r) for a, r, _ in rows)
by_symbol = collections.Counter((s, a, r) for a, r, s in rows)
for a in sorted({a for a, _ in by_action}):
    tot = sum(n for (x, _), n in by_action.items() if x == a)
    print(a, tot, {r: f"{n} ({n/tot:.0%})" for (x, r), n in sorted(by_action.items()) if x == a})
for k, n in sorted(by_symbol.items()):
    print(*k, n)
```
Caveat: audit events are written by ExecutionManager (`core/execution_manager.py:1148-1180`), so
HOLD decisions that never become requests may be absent; the HOLD row will under-count.

## Options (no recommendation beyond the evidence)

| Option | Effect | Invariants touched | Tier |
|---|---|---|---|
| 1. Keep everything | BUYs stay disabled while votes split and sentiment is neutral; behaviour is fail-closed | none | none |
| 2. Lower the HIGH floor (0.80) | Alone insufficient: max reachable BUY is 67.07 (macro SELL); would need ≤0.63 to admit today's BUYs — below the MEDIUM floor, inverting the bucket ladder | capability≠authority (risk authority relaxed on advisory input); RiskEngine policy | CRITICAL |
| 3. Change how Macro enters fusion | Best case (macro HOLD) 65.75 — still below 70 and 80; does not change the bucket (A stays 0.40). Removing macro lowers confidence (M-2) | NB-4 (must not raise confidence on removal), NB-5 roster denominator | COMPLEX–CRITICAL (decision intelligence) |
| 4. Change how risk_level is assigned (e.g. pass real volatility/market_health, or derive from the market_risk regime instead of vote-count agreement) | Addresses the root cause: today risk_level is a function of vote agreement + reasoning, with LOW unreachable and the risk regime ignored. Would make LOW reachable, so 63.58 could clear a LOW 0.60 floor | capability≠authority (advisory layer feeding the execution bucket), NB-4/NB-5 if agreement term changes | CRITICAL (changes which trades are admissible) |
| 5. Accept and surface on dashboard | State that BUYs are structurally blocked in the current regime, showing A, R, c and the max reachable confidence | none (display only) | ROUTINE–STANDARD (UI) |

## Files changed
- This checkpoint only (uncommitted). No source, test, config or threshold change.
- Throwaway calculation script in the session scratchpad (outside the repo); it could not be run
  because the sandbox's shell-approval check was erroring. All numbers above are closed-form and
  hand-computed; the SELL 85.40 reproduction is the consistency check.

## Tests
None run (read-only diagnosis; shell execution unavailable in-session).

## Known issues / Risks
- Point 2 distribution is UNKNOWN until the script is run against `C:\AtlasState`.
- Reasoning confidence R per cycle is not known here; it is recorded in decision metadata
  (`reasoning`), and `risk.score` in metadata gives c exactly as `c = (0.75 − score)/0.5`.
- Technical score ceiling 1.0 is theoretical; the MarketLoop score producer was not audited.

## Remaining work
Owner runs the tabulation script; owner chooses among options 1–5.

## Next exact action
Run the script above against `C:\AtlasState` and paste the output; then decide an option.
