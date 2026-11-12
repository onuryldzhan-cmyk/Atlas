# Independent Audit — Fusion Dissent Fix (F-1 follow-up), 2026-10-02

Mode: AUDIT. Scope: `AgentFusion.full_weight_denominator` (ai/core/intelligence/agent_fusion.py), its wiring through core/application.py → core/brain.py, the replay variant `fusion_fix` (tools/backtest_replay.py, tools/strategy_compare.py), and tests/test_fusion_dissent_confidence.py, plus the existing fusion tests.
Repository files changed by this audit: this report only. Nothing was committed.

## Verdict: APPROVE switch-on (effect size noted, see F-A). No BLOCKING/HIGH/MEDIUM findings.

## What the change does (verified by reading the code)
With the flag ON, `fuse()` uses `denominator = total_configured_weight` (sum of WEIGHTS = 1.0) instead of `total + missing_weight`. Action selection (`quantized_mass` → `max`), the score-range guard, and the MIN_PARTICIPATING_AGENTS=3 / MIN_WEIGHT_COVERAGE=0.50 floor are unchanged. `confidence = round(winning_mass / round(denominator, MASS_PRECISION), 4)`.

## Checks
1. **Dissent vs abstention (flag ON).** Property probe over the real `fuse()`: 1.5M random rosters (4–5 agents; actions BUY/SELL/HOLD; scores {0,.1,.25,.4,.5,.6,.75,.9,1}), 3.48M dissent-vs-abstain pairs where the winner is the same. **0 cases where a dissenting/neutral vote gave the winner higher confidence than abstention**, outside the floor. 15,706 apparent cases were all the floor: removing the voter dropped participation/coverage below the minimum so the abstain case returned HOLD 0.0 `INSUFFICIENT_EVIDENCE` (fail-closed, intended). An exhaustive 5-agent grid (40.0M pairs) gave the same pattern: ON had 179,352 cases, all at most 0.2 and explained by the floor. OFF had 37,881,661 dissent>abstain cases. That confirms F-1 for today's behaviour.
2. **NB-4 / NB-5 (ON).** 200k random rosters × every single removal: **0 cases where removing a voter raised confidence**. The denominator is the full configured roster (constant 1.0) whatever agents are present, so NB-5 holds by construction. Confidence stayed in [0,1] every time (0 out-of-bounds). The numerator is ≤ Σw because every factor is in [0,1] (enforced by the range guard).
3. **Winner flip.** The flag does not touch selection. Across the 200k probe, ON and OFF chose a different action **0 times**, and ON confidence was greater than OFF **0 times**, since `total + missing ≤ W`. A dissent vote can still flip the winner to the dissent's side (with or without the flag). That is sound: it is a different action backed by more mass, not a confidence gain for the old winner.
4. **Quantization.** `total_configured_weight` is passed through `round(·, MASS_PRECISION)` on the same line as the OFF denominator, so both paths are quantized the same way. The numerator is the same `quantized_mass` that selects the action. Bounds: [0,1] was verified in the probe. MIN_WEIGHT_COVERAGE runs before this code, so the two do not interact.
5. **Per-instance / reachability.** The flag is a class attribute defaulting to False, and the code only ever assigns it on an instance. After setting an instance to True, `AgentFusion.full_weight_denominator` and a fresh instance were both still False (verified). The only production constructor is `ai/core/atlas_brain.py:248`, which runs eagerly inside `AtlasBrain.__init__ → initialize_modules`. `core/brain.py:load_intelligence` (the lazy path, called from `start()`) applies the flag right after construction. `core/application.py:749` sets the brain attribute right after constructing the brain, before `start()`. Re-load after `shutdown()` re-applies it. **main.py does not pass `fusion_full_weight_denominator`, so the flag is OFF in production today.** No other path constructs AgentFusion.
6. **Existing tests.** 1358 passed (tests/test_fusion_dissent_confidence.py + all 19 test files that reference AgentFusion). The existing tests run with the default OFF and still pin today's behaviour. `test_default_is_off_and_today_unchanged` pins the default explicitly.
7. **Effect size (technical BUY .85, momentum BUY .70, sentiment abstain):**

| macro / risk | OFF (today) | ON (fix) |
|---|---|---|
| macro SELL .25, risk HOLD .5 | BUY 0.6358 (clears EXP-002 0.62) | BUY 0.4800 (clears none) |
| macro SELL .25, risk SELL .25 | BUY 0.5963 | BUY 0.4800 |
| macro abstain, risk HOLD .5 | BUY 0.6154 | BUY 0.4800 |
| macro abstain, risk SELL .25 | BUY 0.5783 | BUY 0.4800 |
| macro SELL .25, risk abstain | BUY 0.5614 | BUY 0.4800 |

The first row shows F-1 directly: OFF, macro's SELL *raises* BUY from 0.6154 to 0.6358 and pushes it over the EXP-002 floor. ON, every row is 0.48, the agreeing weighted mass (.4·.85 + .2·.70).
8. **Replay variant.** `run_replay(fusion_fix=True)` wraps `brain_factory` and sets the flag on each replay brain's own `agents` instance. `strategy_compare.py` adds the variant as `{**REALISTIC, "fusion_fix": True}`. This is covered by `test_replay_research_variant_sets_the_flag_only_on_its_own_brains` (passing).

## Findings
- **F-A (INFORMATIONAL) — switch-on makes the typical live pattern ineligible.** Location: agent_fusion.py, the `denominator` line in `fuse()`. Evidence: the table above. Impact: with the flag ON, BUY confidence can reach EXP-002 0.62 only when the agreeing weighted mass is ≥ 0.62, for example technical+momentum at high scores plus risk/macro agreeing. Expect far fewer admissions. This is the intended conservative direction (Safety before profit), not a defect. Remediation: the owner should expect the trade count to fall, and should compare with the `fusion_fix` replay variant before the switch-on.
- **F-B (INFORMATIONAL) — floor interaction.** When abstention would trip MIN_PARTICIPATING_AGENTS/MIN_WEIGHT_COVERAGE, a dissent vote still yields more than abstention, because abstention gives 0.0 HOLD. This is the fail-closed floor and not an F-1 recurrence. No remediation needed. Tests could pin it explicitly.
- **F-C (INFORMATIONAL) — `scores` stays a share of the available evidence only, so it no longer sums to the reported confidence when ON.** It is display-only and has no decision authority. Downstream readers should not read `scores[action]` as confidence.

## Reproduction
Probe scripts (scratch, not in the repo): random dissent/NB-4/bounds/flip probe; exhaustive 5-agent dissent grid; floor-classified dissent probe; effect table. Test command: `/usr/bin/python3.13 -m pytest -q -p no:cacheprovider tests/test_fusion_dissent_confidence.py <19 AgentFusion test files>` → 1358 passed.
