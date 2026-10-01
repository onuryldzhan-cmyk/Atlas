# Independent audit: funding-rate sentiment (design C) and EXP-002, 2026-10-01

**Mode:** AUDIT. **Commits:** `a22cd8e` (EXP-002), `c7def60` (funding sentiment). HEAD is `f9757a9`.
**Tests run:** `pytest tests/test_funding_rate_sentiment.py tests/test_exp002_paper_confidence_experiment.py tests/test_data_source_registry.py` gave **27 passed**.
**Probe:** `AgentFusion().fuse()` with the real weights (technical 0.40, momentum 0.20, risk 0.20, macro and sentiment the remainder). No network calls were made. No repository file was changed except this report.

## Probe results (live-typical votes: technical BUY 0.85, macro SELL 0.25, momentum BUY 0.70)

| risk agent | sentiment | action | confidence | ≥ EXP-002 0.62 | ≥ MEDIUM 0.70 | ≥ HIGH 0.80 |
|---|---|---|---|---|---|---|
| HOLD 0.50 | abstain (today) | BUY | 0.6358 | yes | no | no |
| HOLD 0.50 | funding BUY 0.75 | BUY | **0.7603** | yes | **yes** | no |
| HOLD 0.50 | funding HOLD 0.50 | BUY | 0.6809 | yes | no | no |
| HOLD 0.50 | funding SELL 0.25 | BUY | **0.6575** (rises) | yes | no | no |
| SELL 0.25 | abstain (today) | BUY | 0.5963 | no | no | no |
| SELL 0.25 | funding BUY 0.75 | BUY | **0.7115** | yes | **yes** | no |
| SELL 0.25 | funding HOLD 0.50 | BUY | **0.6358** | **yes** | no | no |
| SELL 0.25 | funding SELL 0.25 | BUY | **0.6154** (rises) | no | no | no |

## Findings

### F-1 HIGH: a non-agreeing funding vote (HOLD or SELL) raises BUY confidence
- **Location:** `analysis/world_analysis_engine.py` (the funding branch of `_sentiment_evidence`), together with `ai/core/intelligence/agent_fusion.py` `fuse()`.
- **Evidence:** see the probe. An absent agent adds its full weight `w` to the denominator (NB-5). A present HOLD vote adds `0.5w`, and a SELL vote at 0.25 adds `0.75w`, to the denominator, while adding nothing to the BUY numerator. So when the funding source turns an abstention into a HOLD or SELL vote, BUY confidence goes **up**:
  - 0.5963 → 0.6358 (HOLD), which crosses the EXP-002 floor of 0.62;
  - 0.5963 → 0.6154 (SELL);
  - 0.6358 → 0.6575 (SELL).
- **Impact:** a contrarian caution signal (for example CROWDED_LONG with an ambiguous or bearish trend gives HOLD) can turn a BUY that was previously refused into an admitted one under EXP-002. This is evidence against the trade raising confidence in the trade, which breaks the spirit of rule 3 ("never raise confidence without evidence").
- **NB-4 strict check:** not violated. Removing the funding vote never raises confidence, because the M-2 monotonicity holds. **NB-5:** not violated. The roster stays at five, and the denominator includes missing weight.
- **Reasoning:** the property is pre-existing in `fuse()`, but until now sentiment abstained in the neutral band. Design C newly converts abstentions into dissenting votes, so this change is the first time the property affects live decisions.
- **Remediation (one of):**
  - (a) Accept a funding-derived vote only when it agrees with the fused action, or only when it is BUY. Otherwise keep abstaining.
  - (b) Fix `fuse()` so that dissenting mass cannot shrink the winner's denominator below the abstention case. This is a governed decision-intelligence change.
  - (c) At minimum, never co-enable funding sentiment with EXP-002 until (a) or (b) is in place.
  
  Add a fusion-level test asserting that "a dissenting vote never raises the winner's confidence vs abstention".

### F-2 MEDIUM: a funding BUY can lift a BUY past the default MEDIUM floor
- **Evidence:** 0.6358 → 0.7603, and 0.5963 → 0.7115.
- **Impact:** this is agreeing evidence, so it is legitimate in principle. However, a single derivatives-positioning metric, `lastFundingRate` (up to 8 h old), alone moves typical cycles from "no trade" to "trade" at the default floors. That materially changes PAPER trading frequency.
- **Remediation:** the owner should switch it on knowingly. Log `reason=FUNDING_RATE_CROWDED` admissions so their outcomes can be evaluated separately from F&G-driven ones.

### F-3 MEDIUM: required tests are missing at the fusion level
- **Location:** `tests/test_funding_rate_sentiment.py`.
- **Evidence:** the design requires these tests: "NB-4 removal test; NB-5 roster test; F&G and funding disagreeing". The tests check vote creation and abstention at the engine level only. No test runs `AgentFusion` to assert that confidence does not rise on removal, or that the roster denominator stays at 5. "Disagreeing" is covered only as "a non-neutral F&G ignores funding".
- **Remediation:** add fusion-level NB-4 and NB-5 tests, plus the F-1 test.

### F-4 LOW: CONFLICT between design and code
- **Expected (design):** "a separate sixth evidence item inside the sentiment vote"; funding votes when it is outside the band.
- **Actual:** funding is consulted **only** when F&G is NEUTRAL. When F&G is FEAR or GREED, funding is ignored entirely.
- **Evidence:** the `if band == NEUTRAL` branch; test `test_fear_or_greed_band_ignores_funding`.
- **Impact:** the code is more conservative than the design. The commit title states this, but the design document was not updated.
- **Decision required:** update the design record (successor note).

### F-5 LOW: funding_rate_provider robustness notes
These do not block switch-on.
- **One bad row blanks the whole batch.** One implausible row (|rate| > 5 %) or an unparsable rate fails the entire batch for every symbol. This is fail-closed, so availability is the only cost.
- **Failure retries are slow.** After a failure, the next fetch happens only after `CACHE_S` (600 s), measured from the last attempt. Stale data (> 1800 s) correctly gives unavailable.
- **No lock.** The provider has no lock. This is benign under the current sequential loop, but **UNKNOWN — requires verification** if symbols are ever evaluated concurrently.
- **Never-raise is verified.** `rate()` wraps everything. `_with_funding` also catches errors and passes a non-dict sentiment through unchanged.
- **Malformed readings are handled.** A malformed reading (not a dict, `available` is not `True`, or a band outside the crowded set) gives an abstention, which is correct.

### F-6 INFORMATIONAL: the CROWDED_SHORT → FEAR mapping
- **Rule:** CROWDED_SHORT maps to FEAR, so FEAR with a BULLISH trend gives BUY (short-squeeze read), and FEAR with an ambiguous trend gives SELL. This mirrors the owner-confirmed F&G rule.
- **Assessment:** the direction is defensible, and the rule is conservative when the trend is ambiguous. Ambiguous gives SELL or HOLD, which F-1 shows is *not* conservative in fusion terms.
- **Threshold:** the 0.03 %/8 h threshold is fixed in advance.

### F-7 INFORMATIONAL: wiring and registry
- **Flag default and wiring:** `funding_sentiment` defaults to False. `main.py` does not pass it, so the provider is never attached. The registry entry has status `INACTIVE (flag OFF until audit + owner)`. `tests/test_data_source_registry.py` passes.

### F-8 LOW: EXP-002 switch-on path and experiment exclusivity
- **Correct:**
  - The experiment is selected by id. An unknown id logs an error and attaches nothing (tested).
  - It is PAPER-only.
  - Its cap is counted per `experiment_id` in both the audit log and `ExperimentAdmissionLedger`, taking the max. EXP-002's 30 is therefore counted separately from EXP-001's 50.
  - Admissions are sized with the HIGH bucket's limits (`EXPERIMENT_SIZING_BUCKET`).
  - It is MEDIUM-only, so HIGH stays at 0.80.
  - The floor of 0.62 is ≥ the global minimum.
- **Notes:**
  - Only one experiment can be attached at a time. EXP-001 was stopped by the owner (v5.71) and must stay off while EXP-002 runs (this is the case today).
  - `main.py` has no `paper_confidence_experiment_id` literal yet, so switching on needs a new keyword argument at the call site.
  - `load_config()` receives the module constant `PAPER_CONFIDENCE_EXPERIMENT`, while the app receives a separate literal `False`. The owner must keep the two consistent.
  - The design's "two literals" description is accurate apart from that.
- **Remediation:** none blocking. When switching on, set both the flag and the id in `main.py` and update the constant, or document why it is not updated.

## Verdicts
- **Funding sentiment (design C):** **APPROVE AFTER FIXES.** Fix F-1, or at minimum restrict funding votes to agreeing or BUY-only, and add the F-3 tests. Do not enable it together with EXP-002 until F-1 is resolved.
- **EXP-002:** **APPROVE switch-on** (PAPER, as designed), **with the funding-sentiment flag kept OFF** for the experiment's duration. Otherwise F-1 contaminates its sample. If both run together, EXP-002 becomes APPROVE AFTER FIXES (F-1).

## Remediation (2026-10-01, same session)
| Finding | Status | Change |
|---|---|---|
| **F-1 (HIGH)** | Mitigated for funding | Funding can only add an agreeing BUY (CROWDED_SHORT with a BULLISH trend). Every other funding reading abstains, so funding never adds a dissenting vote that `fuse()` would turn into more confidence. **The underlying `fuse()` behaviour is pre-existing** and today also affects the macro agent's SELL. It is recorded as a separate CRITICAL design: `proposals/2026-10-01_fusion_dissent_confidence_DESIGN.md`. |
| **F-2 (MEDIUM)** | Open; owner decision | A funding BUY can still lift a typical BUY past MEDIUM 0.70. The owner must switch it on knowingly. |
| **F-3 (MEDIUM)** | Partly fixed | Tests added: funding evidence is only ever a BUY or an abstention; Fear & Greed wins when the two disagree. A fusion-level test is still owed, together with the `fuse()` fix. |
| **F-4 (LOW)** | Fixed | A successor note was added to the design. |
| **F-5 (LOW)** | Deferred | Provider robustness: one bad row blanks every coin; there is no lock. |
| **F-8** | No change | Switching on EXP-002 also needs `paper_confidence_experiment_id="EXP-002"` at the `main.py` call site. |
