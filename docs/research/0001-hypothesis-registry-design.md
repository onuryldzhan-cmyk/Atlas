# RESEARCH-0001: Hypothesis Registry, Leakage-Safe Splits, FDR Control, and the CANDIDATE Lifecycle

## Status

Proposed. Track `research/edge-validation`, Step 1 (infrastructure only).

Amended after Step 1 by the five-check validation package, which adds
**Decision 5** and takes the persisted registry format from version 1 to
version 2. Decisions 1-4 are unchanged; the amendment is additive.

Branched from `feat/block2-architecture-core` (`0942391`). No `main` branch
exists in this repository and there are no remotes; `feat/block3-execution-safety`
is the de-facto trunk but is excluded from this track's base by owner decision,
so that the research subsystem carries no execution-safety commits.

## Context

Atlas can currently *run* strategies but has no mechanism that establishes
whether a strategy has an edge at all. The existing backtest stack
(`backtest/backtest_engine.py`, `backtest/portfolio_backtest.py`) fabricates
its own OHLCV from `random.uniform` / `np.random.normal`, so nothing it has
ever produced is evidence about a real market. Repository-level backtest
result files are therefore treated as UNVERIFIED.

Three failure modes destroy quantitative research, and all three are
*process* failures rather than code failures. They cannot be fixed after the
fact by a better estimator:

1. **Look-ahead / leakage.** A split that lets information from the
   evaluation period reach the fitting period inflates every downstream
   statistic. Random shuffling of a time series is the common form; overlapping
   labels near a split boundary are the subtle form.
2. **Multiple testing.** Testing many strategies and reporting the best one
   guarantees a "significant" result under a true null. At `alpha = 0.05`,
   testing 100 worthless strategies yields roughly 5 apparent discoveries.
3. **HARKing** (Hypothesising After Results are Known) — silently changing the
   hypothesis, the test statistic, the direction, the universe, or the date
   range once results are visible, then reporting as if it had been planned.

This note designs the infrastructure that makes those three failures
*structurally difficult* rather than merely discouraged. It builds no
strategy, tests no hypothesis, and asserts no edge.

## Scope

**In scope for this step:** the hypothesis record schema and its
tamper-evident seal; the purged/embargoed train/calibration/test splitter;
Benjamini-Hochberg FDR control; the strategy lifecycle state machine.

**Explicitly not in this step:** any hypothesis, any feature, any signal, any
strategy, any p-value computation, any data acquisition, any backtest engine,
any connection to `MarketLoop`, `ExecutionManager`, or the paper-trading book.

## Decision 1 — Hypothesis Registry record schema

A hypothesis is registered **before** it is evaluated, and the registration is
sealed by a content hash. The record separates three field groups with
different mutability rules.

### Sealed fields (immutable after registration)

| Field | Type | Purpose |
|---|---|---|
| `hypothesis_id` | `str` | Strict slug, `^HYP-[0-9]{4}$`. Owner-assigned, format-controlled. |
| `title` | `str` | Short human label. |
| `description` | `str` | What is claimed, in plain language. |
| `economic_rationale` | `str` | *Why* this edge should exist — the mechanism, the participant behaviour, the structural friction. Required and non-empty. |
| `author` | `str` | Accountability. |
| `universe` | `tuple[str, ...]` | Symbols, frozen at registration. |
| `timeframe` | `str` | Bar interval, frozen at registration. |
| `data_start` / `data_end` | `str` | The data window sealed at registration. |
| `feature_spec` | `Mapping[str, Any]` | Declarative description of the signal. |
| `entry_rule` / `exit_rule` | `str` | Declarative trade rules. |
| `test_statistic` | `str` | The single pre-committed measurement. |
| `direction` | `str` | `greater` / `less` / `two_sided`. |
| `null_hypothesis` | `str` | Stated explicitly. |
| `alpha` | `float` | Nominal per-hypothesis level, `0 < alpha < 1`. |
| `minimum_effect_size` | `float` | Economically meaningful threshold, `>= 0`. |
| `family_id` | `str` | The multiple-testing family this belongs to. |
| `split_spec` | `SplitSpec` | Purge/embargo parameters, frozen at registration. |
| `preregistered_at` | `str` | UTC ISO-8601. |

### Seal

`preregistration_hash` is SHA-256 over a canonical JSON serialisation of the
sealed fields (sorted keys, no whitespace, UTF-8). It is not itself part of
the hashed payload.

The `economic_rationale` field is deliberately free text supplied by a human
and is therefore *format-uncontrolled*. Consistent with the project's
canonical-identity rule, it is **hashed into the seal rather than being
allowed to widen any identity charset** — `hypothesis_id` keeps its strict
slug format regardless of what the rationale contains.

The seal exists because the registry is a JSON file on disk. Without it,
`direction` could be flipped from `greater` to `less` after seeing a negative
result, and nothing would record that it happened. With it, any edit to a
sealed field makes the stored hash disagree with the recomputed hash, and the
registry refuses to load the record.

### Mutable state

Only two things may change after registration:

- `state` — advanced solely through the lifecycle machine (Decision 4).
- `evaluations` — an **append-only** list of evaluation records. Nothing is
  ever edited or removed.

### Rationale for pre-registration

Registration must precede evaluation, and the hypothesis is registered with
its test *fully specified*: statistic, direction, threshold, universe, dates,
and split parameters. A hypothesis that needs any sealed field changed is not
an amended hypothesis — it is a **new** hypothesis with a new `hypothesis_id`,
and it enters the multiple-testing family as an additional test. This is the
single most important anti-HARKing property in the design: revision is never
free, it always costs statistical power.

### Minimum effect size

Statistical significance is not the promotion criterion. A hypothesis must
clear `minimum_effect_size` *as well as* the FDR gate, because with enough
observations an economically worthless effect becomes statistically
detectable. Costs, fees, and slippage are why an edge that is real can still
be worthless.

## Decision 2 — Leakage-safe split with purge and embargo

The split is **contiguous and chronological**. Observations are never
shuffled, and no random sampling is used anywhere in the split.

```
|<---- TRAIN ---->|<-gap->|<-- CALIBRATION -->|<-gap->|<---- TEST ---->|
```

### The three segments have different privileges

- **TRAIN** — fit parameters. Unlimited access.
- **CALIBRATION** — select hyperparameters, thresholds, variants; all model
  selection and all searching happens here. Unlimited access. This is the
  deliberately "dirty" segment: it absorbs the optimisation bias so the test
  segment does not have to.
- **TEST** — **single use**. Read once, ever, per hypothesis. Enforced by the
  lifecycle machine, not by convention.

Splitting into three rather than two exists precisely so that the searching
that must happen somewhere is confined to a segment whose contamination does
not matter.

### Purge

If an observation at time *t* carries a label that depends on data through
*t + h* (`label_horizon_bars = h`), then an observation near the end of an
earlier segment "knows" about the beginning of the later segment. Purging
removes, from the **earlier** segment, every observation whose label window
reaches into the later segment — the final *h* bars.

### Embargo

Purging removes direct overlap but not serial correlation. Features built
from trailing windows, and returns with autocorrelation, leak information
across the boundary even when label windows do not overlap. The embargo
removes a further `embargo_pct` of total bars from the **earlier** segment.

### Convention: both purge and embargo remove from the earlier segment

This is a choice between two defensible conventions, and it is made
deliberately. Removing from the earlier segment never shrinks or shifts the
TEST segment, so test-set size and composition depend only on
`test_fraction` — not on the purge and embargo parameters. Had the buffers
been taken from the later segment, tuning `embargo_pct` would silently change
what the test set *is*, which is itself a researcher degree of freedom worth
eliminating.

### Invariants (enforced, fail-closed)

- Strict ordering: every TRAIN index < every CALIBRATION index < every TEST index.
- Segments are pairwise disjoint; no index appears twice.
- Every segment is non-empty after purge and embargo — otherwise raise, never
  return a degenerate split.
- The realised gap at each boundary is at least `purge + embargo` bars.
- Fully deterministic given `(n_observations, fractions, label_horizon_bars, embargo_pct)`.

A split that cannot satisfy these raises rather than returning something
usable-looking. Silent degeneracy in a splitter is indistinguishable from
leakage in the results.

## Decision 3 — Benjamini-Hochberg FDR control

For `m` p-values in one family, sorted `p_(1) <= ... <= p_(m)`, find the
largest `k` with

```
p_(k) <= (k / m) * q
```

and reject `H_(1) ... H_(k)`. Adjusted p-values are computed by the standard
monotone step-up from the largest index down:

```
p_adj_(i) = min( 1, min over j >= i of ( m / j ) * p_(j) )
```

### Why FDR rather than FWER

Bonferroni controls the family-wise error rate — the probability of *any*
false discovery — and at research scale it is so conservative that real edges
are discarded. Controlling the *expected proportion* of false discoveries
among those declared is the appropriate trade for strategy screening, where
tolerating a known fraction of false positives is rational as long as the
fraction is bounded and stated.

### The family definition is the load-bearing part

BH controls FDR only if the family contains **every hypothesis tested**,
including those that failed, were abandoned, or were quietly forgotten.
Applying BH to the survivors reproduces exactly the selection bias it is
meant to correct, and is worse than not applying it at all, because it
produces a number that *looks* corrected.

This is the architectural reason the registry is append-only and never
deletes: **the registry is the only structure that can honestly enumerate a
family.** The correction and the registry are not two features that happen to
sit in the same module — one is unsound without the other.

### Dependence assumption, stated

BH controls FDR under independence or positive regression dependence (PRDS).
Strategy p-values computed on overlapping windows of the same market are
positively correlated, which is generally within PRDS, so BH is applied as
specified. Benjamini-Yekutieli (dividing the threshold by the harmonic number
`H_m`) holds under arbitrary dependence at a real power cost; it is noted as
the fallback and is not implemented in this step.

### This step takes p-values as input

No p-value is *computed* here. `scipy` and `statsmodels` are absent from this
environment, and the correction is a separate concern from the test procedure
that produces the inputs. BH is implemented in pure `numpy`, adding no
dependency.

## Decision 4 — CANDIDATE strategy lifecycle

```
   DRAFT ──seal──> REGISTERED ──> CALIBRATED ──> TESTED ──> CANDIDATE
     │                  │              │            │           │
     │                  v              v            v           v
     └──> WITHDRAWN  REJECTED      REJECTED     REJECTED   PAPER_VALIDATING
                                                                │
                                                        ┌───────┴───────┐
                                                        v               v
                                                    VALIDATED ──>   RETIRED
```

| State | Meaning | Test set readable? |
|---|---|---|
| `DRAFT` | Being written. Not sealed. | No |
| `REGISTERED` | Pre-registration sealed. Train only. | No |
| `CALIBRATED` | Train + calibration complete. | No |
| `TESTED` | The one-shot test evaluation has been consumed. | Consumed |
| `CANDIDATE` | Passed test, cleared BH within its family, cleared minimum effect size. | Consumed |
| `PAPER_VALIDATING` | Forward validation in PAPER mode. | Consumed |
| `VALIDATED` | Survived forward validation. | Consumed |
| `REJECTED` | Failed a gate. Terminal. | — |
| `RETIRED` | Decayed or withdrawn after promotion. Terminal. | — |
| `WITHDRAWN` | Abandoned before sealing. Terminal. | — |

### Transitions are monotone

No transition returns to an earlier state. A `TESTED` hypothesis can never go
back to `CALIBRATED` and be re-tested; a `REJECTED` one is terminal. Without
monotonicity, "test, adjust, test again" is available, and the test segment
degrades into a second calibration segment after the first re-entry.

### `TESTED -> CANDIDATE` is not a per-hypothesis decision

This is the one transition a hypothesis cannot make on its own evidence. It
requires a family-level BH run over every hypothesis in `family_id`,
because whether this result survives correction depends on how many *other*
hypotheses were tested. The state machine encodes that dependency: promotion
takes a family decision as an argument, not just the hypothesis's own p-value.

### No LIVE state exists

The terminal promotion state is `VALIDATED`, which confers **no trading
authority whatsoever**. There is deliberately no `LIVE`, `PRODUCTION`, or
`DEPLOYED` state in this machine — not a guarded one, not an unreachable one.
Per the project contract, live/real-money authority is denied by default, and
the way to keep a state machine from granting it is for the state not to
exist. Any future promotion beyond PAPER requires explicit owner
authorisation and a separate, governed design.

## Decision 5 — The five-check validation protocol

Added by a later package on this track, after Decisions 1–4 were implemented
and the `research/` L4 boundary was settled (ADR-0009). Decisions 1–4 are
unchanged by it; this decision adds a fifth gate in front of promotion and
breaks the persisted format once to carry it.

Decision 1 seals *what* will be tested. It does not seal *how thoroughly*.
A hypothesis could be pre-registered honestly and then validated by whichever
checks happened to come out well — running a Monte Carlo only after the
cost-adjusted result disappoints, or quietly not running it at all. That is
HARKing one level up: not about the hypothesis, but about the validation
protocol applied to it. Decision 5 seals the protocol too.

### The closed set of checks

| Check | Segment scored | Sealed parameters |
|---|---|---|
| `BACKTEST` | TRAIN | `minimum_effect_size` |
| `WALK_FORWARD` | CALIBRATION | `window_count`, `minimum_fraction_passing` |
| `OUT_OF_SAMPLE` | TEST | — (identity is the sealed `split_spec` TEST segment) |
| `COST_ADJUSTED` | TEST | `cost_model_id`, `cost_bps` |
| `MONTE_CARLO` | TEST | `trial_count`, `null_model_id`, `percentile_threshold` |

The set is closed. A sixth check is a change to the validation protocol and
belongs in a reviewed change to `CheckName`, not in a free-text field.

`CheckVerdict` has exactly two values, `PASS` and `FAIL`. There is deliberately
no `INCONCLUSIVE` or `SKIPPED`: a third value is somewhere a failing check can
hide, and an absent required check already adjudicates as a failure, so a check
that could not be computed simply is not recorded.

### Three checks, one test read

`OUT_OF_SAMPLE`, `COST_ADJUSTED` and `MONTE_CARLO` all score the TEST segment,
and Decision 4 allows that segment to be read exactly once. They are therefore
not three reads: `OUT_OF_SAMPLE` **is** the single irreversible read,
`COST_ADJUSTED` re-scores that same read under a cost model, and `MONTE_CARLO`
resamples it. All three ride on one `EvaluationRecord`, and the single-use
budget is untouched.

This has a consequence worth stating, because it is a feature rather than an
edge case: `BACKTEST` and `WALK_FORWARD` score segments readable only before
`TESTED`, so consuming the test read first makes them permanently unrecordable
and the hypothesis permanently unpromotable. "Look at the test set, then go back
and do the backtest" is structurally unavailable, not merely discouraged.

### This module adjudicates checks; it does not compute them

A `CheckResult` arrives as plain data — statistic, verdict, the threshold it was
scored against, and a free-form payload. The engines that compute walk-forward
windows, cost models and resampled nulls are a separate, later package. What is
defined here is the contract and the adjudication, not the statistics.

### A sealed threshold is binding, not documentary

Sealing a threshold stops it being *edited* after the fact. On its own it does
not stop the check being *computed* against a different number and a `PASS`
handed in regardless — a plan sealing `minimum_effect_size: 0.5` would accept a
`BACKTEST` PASS decided against `0.0001`, and the sealed number would be
decoration.

So a result must declare the threshold it used, and it must be the one the plan
sealed. `CheckPlan.threshold_for()` is where a compute engine reads its
threshold rather than choosing one. `WALK_FORWARD` binds
`minimum_fraction_passing` for the same reason — "6 of 10 windows cleared,
threshold 0.3" is a pass the plan never authorised if it sealed 0.6. A check
that seals no threshold must declare none, so that a stored number can never be
mistaken for a binding nothing checked.

Residual, recorded rather than closed: the non-threshold sealed parameters
(`cost_model_id`, `null_model_id`, `window_count`, `trial_count`) are sealed but
not bound, because binding them needs fields on `CheckResult` that do not exist
yet. An engine can still seal one cost model and use another.

### Adjudication is conjunctive

Promotion requires **all four** gates: the family-level FDR decision, the
hypothesis's own pre-registered `alpha`, its `minimum_effect_size`, and every
check its sealed plan requires. They are combined with a hard AND. There is no
weighted or blended score, because a weighted score lets a strong p-value buy
its way past a failed cost-adjusted check, and those two quantities are not
exchangeable.

### Ordering: BH first, checks strictly after

Benjamini-Hochberg runs over the p-values of every tested hypothesis in the
family, with no check verdict consulted while it runs, so `m` is the true number
of tests. Check gating is applied afterwards, as a further conjunct on a decision
BH has already made.

The order is not interchangeable. Gating on checks *before* the correction would
drop the hypotheses that failed their checks from the family, shrinking `m` and
making every survivor's threshold easier to clear — reintroducing precisely the
selection bias of Decision 3 by way of the machinery meant to add rigour.

### The two regression guards

**NB-4 analogue — removing evidence never relaxes the verdict.** Adjudication
iterates the sealed *plan* and looks each required check up among the recorded
results. A required check with no result is a `FAIL`, never a skip. Deleting a
recorded result can therefore only move a check from passed to missing; there is
no subset of the evidence whose removal improves the outcome.

**NB-5 analogue — the denominator is the plan.** "How many checks passed" is
always scored against the plan's required-check count, never against however many
results happen to be present. Were it the latter, a hypothesis with two of five
checks recorded and both passing would read as unanimous — the same false full
consensus NB-5 describes for a short agent roster.

`CheckPlanStatus` distinguishes `INCOMPLETE` from `COMPLETE_FAIL`, because "three
checks are still outstanding" and "all five ran and one failed" are different
operational situations. Both are non-promotable; adjudicating while incomplete
resolves per NB-4, as a rejection rather than a hypothesis held open.

### Promotion is reachable only through family adjudication, in process

`lifecycle` declares `FAMILY_ADJUDICATED_TRANSITION` as the one transition a
hypothesis cannot make on its own evidence. The registry's general-purpose state
mutator now refuses it: `TESTED -> CANDIDATE` is legal for the state machine but
reachable only through family adjudication, which applies all four gates
together. Left open, a single call routes around the entire conjunctive gate,
and the gate is only ever as strong as the path that reaches it. Every other
transition `advance()` served is unaffected, including `TESTED -> REJECTED`,
which needs no family evidence because it is never a promotion.

The scope of that claim is the in-process API, and the qualifier is not
decorative. `state` is mutable by design and therefore outside the seal, so
hand-editing the stored `state` to `CANDIDATE` still produces a promoted record
on load. That is pre-existing and belongs to the same class as open items 6 and
8: the seal binds the pre-registration, not the whole file. Closing the API
route is still worth doing — it is the route an honest caller can take by
accident — but it is not a claim about a text editor.

### Write path and load path enforce the same rules

Evaluations are deliberately outside the seal — they grow after registration,
so a fixed hash cannot cover them. Every invariant the write path enforces is
therefore re-checked on load: that each recorded check is in the sealed plan,
that no check appears twice, and that each was scored against its sealed
threshold. An invariant enforced on only one path holds until the next restart,
which is not an invariant: appending a passing duplicate after a failing result
would otherwise launder the verdict without disturbing the seal at all.

This does not make evaluations tamper-evident. An in-place edit of a single
stored verdict remains undetectable; closing that needs a chained hash over the
append-only log and is future work.

### Format version 2

The sealed payload now includes `check_plan`, so no version-1 payload can produce
a valid version-2 seal. This is a clean break: `REGISTRY_FORMAT_VERSION` goes
`1 -> 2` with **no version-1 loading path**. An exhaustive search found no
version-1 registry file anywhere — in the repository, in `C:\AtlasState`, or in
checkpoints — and nothing outside the tests constructs a registry, so there is no
data to migrate and a revert loses nothing. `_load` refuses any version it does
not recognise, in both directions, rather than guessing.

## Storage and runtime-state isolation

The registry persists to JSON at a path the caller **must supply explicitly**.
There is no default path and no fallback to the working directory, because a
relative default resolves against the process CWD and would write into the
repository's live runtime state when run from the repository root. Research
code never writes to `memory_data/`, never touches `paper_trades.json`, and
never constructs `AtlasApplication`.

## Open items (not resolved by this step)

1. **There is effectively no market data.** Total holdings are ~1,000 hourly
   BTCUSDT bars (2026-06-07 → 2026-07-19) spread across three overlapping
   files in three different schemas. No ETHUSDT, BNBUSDT, SOLUSDT, or XRPUSDT.
   No second timeframe. The `MarketDataSQLiteStorage` store does not exist on
   disk at all.
2. **The provenance of those files is UNVERIFIED.** No script in the
   repository produced them; there is no manifest, source record, fetch
   timestamp, or checksum. They are not assumed to be genuine exchange history.
3. **No data acquisition path exists.** The Binance providers are live
   request paths, not bulk historical archivers.
4. **Sample size.** ~1,000 bars of one symbol cannot support a three-way
   purged split *and* a multiple-testing family of any useful size. Data
   acquisition is a prerequisite for Step 2 of this track, not an optimisation.
5. **No p-value procedure.** Deferred with the test procedure itself.
6. **Family membership is not sealed.** The per-record seal binds a record's
   contents; nothing binds the *set* of records. Deleting a losing hypothesis
   from the stored file shrinks `m` and relaxes every survivor's BH threshold —
   the Decision 3 bias, reachable one level above where the defence sits.
   Closing it needs a family-level manifest (count plus an ordered digest of
   ids) in the stored payload. Pre-existing; not introduced by Decision 5.
7. **A registry file with no `records` key loads as an empty registry.**
   Truncation is therefore indistinguishable from a legitimately empty
   registry, and duplicate-id detection silently resets. Not promotion-relevant
   — an empty registry promotes nothing — but `{}` and an absent key are
   different facts and should be treated as such. Pre-existing; not introduced
   by Decision 5.
8. **A record's `state` is not sealed.** It is mutable by design — the seal
   covers the pre-registration, and `state` must advance — so a hand-edited
   stored `state` of `CANDIDATE` loads as a promoted hypothesis regardless of
   its p-value or its checks. Decision 5 closes the in-process route to that
   state; it does not and cannot close the text-editor route. The same chained
   hash over the append-only log that would make evaluations tamper-evident is
   what would close this. Pre-existing; not introduced by Decision 5.

Consequence: this infrastructure is correct and testable on synthetic index
arrays, and **no hypothesis can be validly evaluated until item 1 is closed.**
