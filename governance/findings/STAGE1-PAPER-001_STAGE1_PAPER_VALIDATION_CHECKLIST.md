# STAGE1-PAPER-001 — Stage 1 (Paper) validation checklist

| Field | Value |
| --- | --- |
| Finding ID | STAGE1-PAPER-001 |
| Title | The twelve-item Stage 1 (Paper) validation checklist, with per-item coverage status and evidence |
| Finding type | `PROMOTION_GATE_DEFINITION_OF_DONE_WITH_COVERAGE_AUDIT` |
| Operating mode | AUDIT MODE |
| Status | `OPEN_GATE_NOT_PASSED_4_OF_12_CARRY_A_GAP` |
| Authorized by | `governance/current/ATLAS_MILESTONE_REGISTRY_v4.40.json`, `GRANT-STAGE1-PAPER-CHECKLIST-PERSISTENCE` and `GRANT-STAGE1-EIGHT-ITEM-READ-ONLY-AUDIT` |
| **Last verified against commit** | **`59b8392` (branch `research/edge-validation`)** — the registry v4.40 commit; the audited source tree is identical to `7772024`, which is the last commit touching anything but governance documents |
| Recorded on | 2026-09-22 |
| Production effect | NONE |
| Live effect | NONE |

---

## 0. What this document is, and the one thing it is not

This is the **authoritative definition of done for Stage 1 (Paper)** of the
promotion ladder. Any future claim that Stage 1 has passed is measured against
the twelve items in §3 and nowhere else. A claim of passage that does not name
this document, at a stated commit, is not a claim this project recognises.

Creating this document does **not** advance the ladder. It writes the target
down; §5 states how far the repository currently is from it.

### 0.1 This is NOT REM-001 Gate 1 — disambiguation

The token **"Gate 1" is already bound** in this repository to something else:
**REM-001 Gate 1**, the specification-remediation gate governed by
`governance/ATLAS_BASELINE_IDENTITY_AND_GATE1_SCOPE_DECISION_v1.0.md`,
`governance/ATLAS_REM001_GATE1_DELIVERABLE1_AUTHORIZATION_v1.0.md` and
`governance/ATLAS_REM001_GATE1_DELIVERABLE8_SUCCESSOR_REDEFINITION_v1.0.md`.
Its state is `gate_1_state = OPEN_NOT_CERTIFIED`, closure authority
`OWNER_ACCEPTANCE_REQUIRED`.

The two gates are unrelated and have unrelated acceptance criteria. **Nothing in
this document closes, certifies, partially certifies or reopens REM-001 Gate 1,
and REM-001 Gate 1 closing would say nothing about the twelve items here.** This
document is named for the ladder stage — Stage 1 (Paper) — precisely so the two
cannot be confused by a future reader.

### 0.2 Provenance of the twelve items, and their relationship to the vision document

The twelve items are the **owner's specification**, recorded here for the first
time. Before this document they existed only in conversation; three independent
searches at `7772024` found no persisted copy anywhere in the repository
(§1.2).

The vision document `docs/vision/03_gercek_para_guvenlik_temelleri.txt` carries
its own, **different and shorter** Paper-stage list at lines 440–500 — "Aşama 3
— Paper doğrulama", with four sub-criteria: long uninterrupted running,
realistic costs, no risk violations, and acceptable divergence between expected
and actual. Those four are **operational run criteria** (what a paper run must
demonstrate once it is running); the twelve here are **capability criteria**
(what must be correct and tested before a run means anything).

**This document does not supersede that list and does not merge with it.** The
relationship between the two is an **open question** deliberately left open:
resolving it would be an owner decision about what Stage 1 means, which no
audit may make on its own. Until it is resolved, a complete Stage 1 case needs
both.

---

## 1. Method, and what would falsify this audit

### 1.1 Method

Four of the twelve items were audited in a prior AUDIT MODE pass (Part 4 of an
earlier task) and are carried here by citation, marked **[prior pass]**. The
other eight were audited read-only in this session under
`GRANT-STAGE1-EIGHT-ITEM-READ-ONLY-AUDIT`.

For the eight, the method was the prior pass's method:

- **Assertions were read, not test names.** A test called
  `test_technical_analyzer_accepts_normalized_candles` is not evidence that the
  technical analyzer is correct; its body (`assertIsNotNone(result)`) is
  evidence that it does not crash. The distinction decides item 1's verdict.
- **Coverage was checked against the runtime closure**, not against the test
  suite's apparent surface area. `packaging/atlas_runtime_closure.json` names
  the 105 modules reachable from the four entry points (`main.py`,
  `web_app.py`, `atlas_service.py`, `atlas_supervisor.py`). A heavily tested
  module outside that set is not Stage 1 evidence. This changed two verdicts
  (items 1 and 5).
- **Absence is evidence and is stated as such.** Where an item has no test, the
  document records what was searched and what came back empty, per the UNKNOWN
  rule. Silence is not an output.

Nothing was implemented, no test was added, modified or weakened, and no
production file was touched. Remediation below is **suggested, not performed**,
per the grant's explicit exclusion.

### 1.2 The absence that justified writing this document

At `7772024`, three independent searches, all negative:

1. `git ls-files` filtered for `stage1|gate1|checklist|paper.?valid|definition.of.done`
   → only the three REM-001 Gate 1 governance files, none containing such a
   checklist.
2. `git grep -il` for partial-fill terminology (English and Turkish) across
   `docs/`, `governance/`, `checkpoints/`, `ATLAS_MASTER_PLAN.md`, `CLAUDE.md`
   → no governance or checkpoint hit; only two vision documents.
3. Direct read of `docs/vision/03_gercek_para_guvenlik_temelleri.txt` lines
   440–500 → the Paper stage carries four sub-criteria, not twelve.

### 1.3 Working definitions

Several item names do not have one obvious meaning for this repository. Each is
defined **before** it is audited, so the verdict can be argued with rather than
merely believed:

| Item | Working definition used |
| --- | --- |
| Signal correctness | Given market data, the runtime produces a directional signal whose (a) indicator inputs are numerically right, (b) fusion of those inputs is right, and (c) behaviour on missing/malformed evidence is fail-closed. All three are required. |
| Execution correctness | An admitted decision becomes exactly the intended order — right symbol, side, quantity — delegated exactly once, and its terminal status is classified into a closed vocabulary where an unrecognised outcome fails closed rather than being assumed successful. |
| Position-accounting correctness | Cash, committed capital, exposure, fees, realized and unrealized PnL, average entry and position quantity are exact (Decimal, not float) after open, increase, partial close and full close, and survive replay without double-counting. |
| Risk correctness | Policy limits actually reject what they should, the rejection reason is a closed vocabulary, and the risk gate **cannot be bypassed** — not by an alternate execution route, not by mutating an already-approved request, not by concurrency. |
| Database correctness | For each store **on the runtime path**: round-trip fidelity, migration integrity (forward-only, checksum-verified, future-version refused), corruption detected and refused rather than repaired, and concurrent writers serialized without loss. |
| State-survives-restart | Re-instantiating the runtime against the same state directory reproduces financial state exactly, an interrupted transaction still blocks afterwards, and a completed request replays as a duplicate rather than re-executing. |
| Market-data-disconnect handling | Loss or degradation of the market-data feed is detected, and — critically — **cannot produce a trading decision on data that is absent or stale**. |
| Exchange-API-error handling | An error from the exchange or market-data API is classified, never silently swallowed, and an **indeterminate** outcome (timeout, connection loss mid-call) is treated as indeterminate rather than assumed failed. |

---

## 2. Summary table

| # | Item | Status | Gap severity | Finding |
| --- | --- | --- | --- | --- |
| 1 | Signal correctness | **PARTIAL** | HIGH | S-1 |
| 2 | Execution correctness | **COVERED** | — | — |
| 3 | Position-accounting correctness | **COVERED** | — | — |
| 4 | Risk correctness | **COVERED** | — | — |
| 5 | Database correctness | **COVERED** (scoped) | INFORMATIONAL | S-2 |
| 6 | State-survives-restart | **COVERED** | — | — |
| 7 | Market-data-disconnect handling | **PARTIAL** | HIGH | S-3 |
| 8 | Exchange-API-error handling | **PARTIAL** | MEDIUM | S-4 |
| 9 | Reconciliation correctness *[prior pass]* | **COVERED** | — | — |
| 10 | No duplicate orders *[prior pass]* | **COVERED** | — | — |
| 11 | Crash handling *[prior pass]* | **PARTIAL** | MEDIUM | Finding 1 (prior) |
| 12 | Correct partial-fill handling *[prior pass]* | **ABSENT** (safe-by-refusal) | MEDIUM | Finding 2 (prior) |

**8 COVERED / 3 PARTIAL / 1 ABSENT.** No BLOCKING finding.

---

## 3. The twelve items

### Item 1 — Signal correctness — **PARTIAL** (finding S-1, HIGH)

**What is covered, strongly.** The fail-closed third of the definition is among
the best-tested behaviour in the repository. `tests/test_nb1_momentum_rsi_failsafe.py`
(404 lines) proves a `None`, malformed-string or arbitrary-object `rsi` excludes
momentum from fusion rather than raising or fabricating a neutral score
(`:102–103` `assert "momentum" not in signals; assert signals == {}`;
`:115` `assert signals.get("momentum") != {"action": "HOLD", "score": 0.5}`),
resolves through the normal decision path rather than an error fallback
(`:234–243` `decision.action.value == "HOLD"`, `confidence == 0.0`,
`fusion_reason == "INSUFFICIENT_EVIDENCE"`, `"fallback" not in decision.metadata`),
and **never reaches a directional action** (`:286` `assert decision.action.value
not in ("BUY", "SELL")`). `tests/test_nb3_momentum_evidence_gating.py` extends
this to *missing* keys, and `tests/test_nb4_nb5_confidence_availability_correction.py`
holds the NB-4/NB-5 line directly: `:101` `assert reduced.value <= full.value`
(removing evidence cannot raise confidence) and `:218–220`
`assert len(AgentFusion.WEIGHTS) == 5; assert agreement == pytest.approx(0.6);
assert agreement < 1.0` (the denominator is the expected roster, so three
agreeing providers out of a five-agent roster is not unanimity).

**What is not covered at all: the numbers.** The indicator layer that *produces*
`rsi`, `trend`, EMA, MACD and ATR has no numerical assertion anywhere in the
suite. Its only test contact is
`tests/phase6/test_market_loop_integration.py:155` —

```python
def test_technical_analyzer_accepts_normalized_candles(self) -> None:
    ...
    result = analyzer.analyze(normalized)
    self.assertIsNotNone(result)
```

— a smoke test. A repository-wide grep for a numeric indicator assertion
(`rsi ==`, `ema ==`, `adx ==`, `macd ==`, `atr ==` across `tests/`) returned
**only `schema_version`/`policy_version` comparisons** and no indicator value.
There is no golden-vector test: no "given this closed OHLCV series, RSI(14) is
*x*". `core/technical_analyzer.py` (in the closure) and
`analysis/technical_analyzer.py` both implement indicators by hand;
`analysis/technical_analyzer.py:87` `rsi()` is a hand-rolled simple-average RSI
(not Wilder smoothing) whose output no test constrains.

**A second, smaller hole: the directional path.** Every full-path assertion in
the NB tests resolves to `HOLD @ 0.0 / INSUFFICIENT_EVIDENCE`. Directional
`BUY`/`SELL` outcomes are asserted only at the fusion layer with hand-built
signal dicts (`test_nb4_nb5_...:294–296` `result.action == "BUY"`,
`confidence == pytest.approx(0.7674)`), never from market data through
indicators to a decision.

**Note on `core/signal_pipeline.py`:** the 684-line `SignalPipeline`/
`SignalValidator`/`SignalFactory` module has **no test and is not in the
runtime closure** (`grep -c "signal_pipeline" packaging/atlas_runtime_closure.json`
→ `0`). Its only non-archived importer is `strategy/strategy_base.py`, also
outside the closure. It is therefore dead relative to Stage 1 and its absence
of tests is *not* counted against this item.

---

> #### Finding S-1 — Indicator computation has no numerical correctness test
>
> - **Severity:** HIGH
> - **Location:** `core/technical_analyzer.py` (runtime closure);
>   `analysis/technical_analyzer.py:87`; sole test contact
>   `tests/phase6/test_market_loop_integration.py:155`
> - **Evidence:** the only assertion against the indicator layer is
>   `self.assertIsNotNone(result)`. A grep for any numeric indicator
>   assertion across `tests/` returns no indicator value, only schema and
>   policy version comparisons. No golden-vector, no property, no
>   cross-implementation comparison test exists.
> - **Impact:** a wrong indicator is silent. Every downstream guard in the
>   system — fusion, the participation floor, the confidence ladder, the risk
>   engine — operates on `rsi` and `trend` as *given*. An RSI that is
>   systematically wrong (off-by-one window, simple vs. Wilder averaging, an
>   inverted comparison) produces a confident, well-formed, fully-audited,
>   risk-approved and correctly-accounted-for **wrong** trade. Every safety
>   layer in the stack would pass it. In paper this costs nothing but poisons
>   the performance measurement Stage 1 exists to produce — the divergence
>   between expected and actual that the vision document's Paper criteria
>   require would be measuring a broken input.
> - **Reasoning:** the fail-closed behaviour is exhaustively tested because it
>   was the subject of the NB-1/NB-3/NB-4/NB-5 remediations; the numeric
>   behaviour was never the subject of a remediation, so it was never tested.
>   This is a coverage shape that follows the repository's incident history,
>   not its risk surface. It is HIGH and not BLOCKING because it cannot lose
>   real capital at Stage 1 (live authority is DENIED) and cannot corrupt
>   state — it corrupts *conclusions*.
> - **Remediation (suggested, NOT performed):** add golden-vector tests for
>   each indicator the decision path consumes — a fixed closed OHLCV series
>   with independently-derived expected values, asserted to a stated
>   tolerance — plus at least one end-to-end test driving real-shaped market
>   data through the indicator layer to an asserted directional decision, so
>   the `BUY`/`SELL` path is exercised and not only the `HOLD` path. Also
>   record, as a deliberate decision, which RSI convention
>   (`analysis/technical_analyzer.py:87` uses a simple average, not Wilder)
>   is canonical.

---

### Item 2 — Execution correctness — **COVERED**

**Input validation, before any exchange contact.**
`tests/test_exchange_manager_order_validation.py` rejects an empty symbol
(`:98–101`), invalid symbol characters (`:116–118`), an invalid side (`:133–136`)
and an invalid quantity (`:163–166`) — and each assertion ends
`assert exchange.orders == []`, proving the rejection happens *before* the
adapter is reached, not after. The positive case is equally specific
(`:169–190`): `" btcusdt "`, `" buy "`, `0.25` normalizes to exactly

```python
assert exchange.orders == [{"symbol": "BTCUSDT", "side": "BUY", "quantity": 0.25}]
```

— one delegation, normalized, not two and not mutated.

**Terminal-status classification, fail-closed.**
`tests/test_block3_terminal_status_classification.py` (13 tests) asserts that
the success vocabulary is the authority and is disjoint from the failure
vocabulary (`:220–223`), that an **unknown** terminal status fails closed
(`:206`), and — the important one — that a failure or denial arriving *after a
side effect* resolves to `COMMIT_STATUS_UNKNOWN` with
`recovery_required is True`, reservation `INDETERMINATE` and
`execution_halted is True` (`:284–288`, `:300–302`), rather than being
optimistically resolved either way.

**End-to-end through the real runtime path.**
`tests/test_block5c_upstream_sizing_authority.py:727`
`test_real_market_loop_buy_is_sized_and_settles_end_to_end` drives
MarketLoop → sizing → ExecutionManager → `risk_check` → reservation → paper
execution → settlement and asserts exact Decimal outcomes:
`snapshot["cash"] == TOTAL_CAPITAL - notional - fee`,
`notional + fee <= approved`, reservation `COMMITTED`, no orphan reservation,
`execution_halted is False`. `:786` does the same for a SELL exiting a held
position.

**Scope note, not a gap:** only `MARKET` orders exist on this path
(`core/execution_manager.py:2238–2241` defaults `order_type` to `"MARKET"`).
Limit-order lifecycle is therefore correctly untested — there is nothing to
test — but that also means item 12 (partial fills) has no order type that could
produce one, which is consistent with the prior pass's Finding 2.

### Item 3 — Position-accounting correctness — **COVERED**

`tests/test_phase4_execution_position_portfolio_foundation.py` (26 tests) is
exact-arithmetic throughout, in `Decimal`:

- Open: `cash == D("899")`, `committed_capital == D("100")`,
  `gross_exposure == D("100")`, `fees == D("1")`, `equity == D("999")`,
  `realized_net_pnl == D("-1")` (`:85–90`).
- Increase: weighted average entry recomputed, `base_quantity == D("15")`,
  `cost_quote == D("200")`, `version == 2` (`:107–119`).
- Partial close: pro-rata reduction, `base_quantity == D("5")`,
  `cost_quote == D("50")`, average entry **unchanged** at `D("10")`,
  `realized_gross_pnl == D("5")`, `cash == D("954")`, position identity and
  `position_id` preserved (`:146–156`).
- Full close, parametrized over winning/losing/flat: `realized_net_pnl ==
  D(gross) - D("2")`, `cash == D("1000") + D(gross) - D("2")` (`:188–192`).
- Fee-only loss (`:198`), unrealized PnL and equity (`:204–205`).
- Replay is idempotent — no double fee, no double cash (`:210–212`).
- Float input is **rejected**, not coerced (`:76`); non-finite and negative
  values rejected (`:72`); ambiguous amounts are not authoritative evidence
  (`:63`).

Reductions larger than the holding are rejected and leave the book not-ready
(`:173–180`), and a duplicate position identity is rejected (`:122`).

### Item 4 — Risk correctness — **COVERED**

`tests/test_phase3_risk_capital_foundation.py` (28 tests) covers both halves of
the working definition.

**Limits reject, with a closed reason vocabulary:** position and bucket caps →
`REQUEST_EXCEEDS_RISK_LIMIT` (`:72–73`); invalid bucket →
`UNSUPPORTED_RISK_LEVEL`, `approved_allocation == D("0")` (`:90–93`); portfolio
cap → `INSUFFICIENT_ALLOCATABLE_CAPITAL` (`:114`); duplicate open position →
`DUPLICATE_OPEN_POSITION` (`:101`); max positions → `MAX_POSITIONS_REACHED`
(`:139`); daily loss breach blocks entry but **not** a valid reduction
(`:120`, `:123` → `RISK_REDUCTION_APPROVED`); drawdown thresholds parametrized
(`:131–134`); base quantity confused with quote notional →
`QUANTITY_NOTIONAL_MISMATCH` (`:107`); float leakage and `NaN` →
`INVALID_FINANCIAL_INPUT` (`:163–164`); missing or corrupt restored state →
`BLOCK_RECOVERY_REQUIRED` / `RISK_STATE_NOT_READY` (`:147–148`).

**Non-bypassability — the part that matters most:** an execution-seam rejection
cannot reach the legacy capital gate (`:213–214`); an approved amount cannot be
exceeded downstream (`:221–222`); a missing canonical service cannot be
substituted by the legacy gate — `CANONICAL_RISK_SERVICE_REQUIRED` (`:236`); an
alternate paper route cannot bypass canonical admission —
`CANONICAL_RISK_ADMISSION_MISSING` (`:245`); and an approved `request_id`
**cannot authorize a mutated financial request** (`:248–254`). Concurrent
reservations cannot double-spend: `sorted(outcomes) == ["blocked", "reserved"]`
with `reservations.available == D("25")` (`:266–267`).

This satisfies CLAUDE.md's "AI decisions can never bypass Risk, Capital, or
Execution Manager gates" as a tested property, not an architectural intention.

### Item 5 — Database correctness — **COVERED**, scoped (finding S-2, INFORMATIONAL)

**Scope first, because it changes what the numbers mean.** The six persistence
modules actually inside the 105-module runtime closure are:

```
core/audit_event_store.py            core/execution_portfolio_foundation.py
core/capital_reservation.py          core/execution_transaction_journal.py
core/execution_idempotency_store.py  core/risk_state_store.py
data_layer/evidence_store.py
```

All are **atomic JSON / append-only JSONL** stores
(`core/execution_portfolio_foundation.py:142` *"Atomic JSON state store;
missing/corrupt state is never healthy-empty"*, `:237` the JSONL append-only
pattern where `append` is the only write and no line is ever rewritten).
Neither SQLite backend — `data_layer/sqlite.py` nor the market-data
`MarketDataSQLiteStorage` — is in the closure (see S-2).

**The on-path stores are strongly covered.**
`tests/test_block5k_durable_execution_storage.py` (35 tests) asserts that a
terminal result never rewrites prior history (`:177`), that journal transitions
never rewrite prior events (`:209`), that hot-path write cost does not grow with
history (`:229`), that a conflicting durable terminal result is **refused at
write** (`:303`) while an identical duplicate is tolerated (`:358`), that damaged
terminal history, non-deterministic sequence and damaged journal history each
**fail closed** (`:384`, `:416`, `:432`), that committed state cannot be
downgraded by either a write or a log event (`:487`, `:518`), that illegal
journal transitions refuse (`:549`, `:572`, `:591`), and that the legacy
migration converts-verifies-retires (`:778`), is **idempotent and resumable**
(`:811`), leaves the legacy source intact on conflict (`:844`), refuses a
malformed source untouched (`:865`), validates the destination before retiring
the source (`:900`), and **never runs automatically** (`:977`). That is
CLAUDE.md's full migration-safety checklist — idempotency, resume, retry,
sequence, ordering, duplicates, partial state, conflicts, rollback — closed
item by item against the store the paper run actually uses.

**The off-path stores are covered to a higher standard still**, which is worth
recording even though it does not count for Stage 1:
`tests/test_block4_market_data_sqlite_storage.py` (63 tests) covers migration
checksum drift (`:886`), future schema version (`:904`), a garbled database
left **byte-identical** on refusal (`:854`), a dropped table (`:870`), orphan
manifests (`:986`), foreign-key enforcement verified per connection with a
connection that silently ignores FKs being refused (`:1080`, `:1092`),
concurrent writers serialized without loss (`:631`), and property-based
round-trip over generated datasets (`:801`).
`tests/test_phase2_data_layer.py` (22 tests) covers multi-repository
atomicity, rollback, transactional migration failure and WAL for
`data_layer/sqlite.py`.

---

> #### Finding S-2 — The two most heavily tested database backends are not on the runtime path
>
> - **Severity:** INFORMATIONAL
> - **Location:** `packaging/atlas_runtime_closure.json` (105 modules, entry
>   points `main.py`, `web_app.py`, `atlas_service.py`, `atlas_supervisor.py`)
>   vs. `tests/test_block4_market_data_sqlite_storage.py` (63 tests) and
>   `tests/test_phase2_data_layer.py` (22 tests)
> - **Evidence:** `grep -c "data_layer/sqlite.py" packaging/atlas_runtime_closure.json`
>   → `0`. The `atlas_finance/` entries in the closure are
>   `__init__`, `market_data/{__init__,binance_public_provider,contracts,exceptions,market_feed_service,models,temporal}`
>   — no SQLite storage module. The closure's persistence modules are the seven
>   JSON/JSONL stores listed above.
> - **Impact:** none on correctness. The impact is on *interpretation*: 85 of
>   the suite's database tests describe backends the paper run does not touch.
>   A reader counting database tests to judge Stage 1 readiness would
>   substantially overcount. This finding exists so that count cannot be made
>   innocently.
> - **Reasoning:** both SQLite backends are real, forward-looking work
>   (market-data archival, the relational financial store) that is simply not
>   yet wired into the runtime. That is a roadmap position, not a defect, and
>   CLAUDE.md's rule 10 says finish the roadmap rather than widen it.
> - **Remediation (suggested, NOT performed):** none required for Stage 1.
>   When either backend is wired into the closure, re-audit this item — the
>   evidence is already there and would simply start counting.

---

### Item 6 — State-survives-restart — **COVERED**

Over thirty distinct restart tests exist; they are consistent and specific.

- Financial state reproduces exactly: `restored["cash"] == D("1018")`,
  `realized_gross_pnl == D("20")`, `fees == D("2")`
  (`tests/test_phase4_execution_position_portfolio_foundation.py:253–255`).
- Missing **and** corrupt state both fail closed with
  `diagnostics()["recovery_required"] is True` (`:264`, `:271`) — never a
  healthy-empty book.
- A restart in mid-transition blocks `ready` (`:274`).
- A completed request is **still a duplicate after restart**
  (`tests/test_block3_durable_execution_path_ownership.py:214`), the persisted
  idempotency record is reloaded (`:227`,
  `restarted.execution.stats["persistent_records_loaded"] == 1`), an unresolved
  journal **blocks a restarted runtime** (`:249`), and an interrupted execution
  still blocks after restart (`:278`).
- Journal logical state reconstructs identically after restart
  (`tests/test_block5k_durable_execution_storage.py:455`); an old request
  replays to its completed result rather than re-executing (`:265`).
- Reservations survive (`tests/test_block2_risk_service_composition_wiring.py:513`),
  restart against the same durable state is deterministic (`:495`), settlement
  amounts survive reload (`tests/test_block5e_fee_settlement_accounting.py:471`),
  and every closed lifetime is preserved exactly
  (`tests/test_block5g_closed_position_lifetime_identity.py:499`).
- Re-bootstrapping with a different policy version does not silently succeed
  (`tests/test_block3_bootstrap_policy_consistency.py:127`), nor with smaller
  allocatable capital over encumbered state (`:152`).

**Stated limitation, already owned by item 11:** "restart" throughout means
re-instantiating against the same state directory in-process, not killing and
relaunching an OS process. That is the correct semantic for *state* survival and
is why this item is COVERED; the unclean-termination question is the prior
pass's Finding 1 and is scored there, not double-counted here.

### Item 7 — Market-data-disconnect handling — **PARTIAL** (finding S-3, HIGH)

**Detection is genuinely good.** `tests/test_market_loop_reconnect.py` (406
lines) proves per-symbol staleness reporting with `seconds_since_last_success`
(`:192–194`), that a symbol never fetched reports stale with
`seconds_since_last_success is None` (`:218–220`), that **repeated empty
responses report stale rather than fresh** (`:255–260`) — with
`assert feed.calls == 5, "the fixture must actually have been polled"` to prove
the fixture was real — that empty responses do not refresh an aging timestamp
(`:295–299`), that health recovers after a transient error ages out of the
window rather than latching forever (`:149–152`), and that a backfill gap
exceeding the window is detected, counted and published as an event
(`:363–374`).

The producer-side discipline behind this is explicit and correct
(`core/market_loop.py:464`): freshness is recorded *only once real bars are in
hand*, "never merely because the provider call did not raise", because
otherwise "staleness reporting would render the absence of data as positive
evidence of data (NB-4)".

**Hard disconnect is fail-closed by omission.** An empty candle list returns
`None` before any decision (`core/market_loop.py:455–459`); fewer than 50 closed
candles returns `SKIPPED / INSUFFICIENT_CLOSED_CANDLES` (`:515–530`); a raising
provider is caught (`:829–840`), recorded via `_record_error` and returns
`None`. No decision is produced in any of these cases.

**The gap is the soft case: stale-but-present data.**

---

> #### Finding S-3 — Market-data staleness is reported but does not gate decisions, and the only max-age gate is shadow-only
>
> - **Severity:** HIGH
> - **Location:** `core/market_loop.py:2046` and `:2064–2080`;
>   `core/execution_manager.py:517–521`;
>   `tests/test_atlas_brain_phase5_shadow.py:77`;
>   `tests/test_market_loop_reconnect.py:204–206`, `:223`, `:263`
> - **Evidence:** three independent strands.
>   1. `core/market_loop.py:2046` states in the source itself:
>      *"market_data_stale is reported only - it never affects healthy"*, and
>      the tests assert exactly that — `health_result["market_data_stale"] is
>      True` together with `health_result["healthy"] is True` (`:204–206`), and
>      again at `:223` and `:263`.
>   2. The execution-side freshness gate
>      (`core/execution_manager.py:517–521`) keys on **venue rule** freshness,
>      not market-data age; `grep -niE "stale|freshness" core/execution_manager.py`
>      returns venue-rule references only.
>   3. A real max-age gate *does* exist — `FreshnessPolicy` in
>      `core/decision_intelligence`, tested at
>      `tests/test_atlas_brain_phase5_shadow.py:286`
>      (`test_stale_ingestion_timestamp_is_rejected_by_freshness_gate`),
>      `:333` (strict-greater-than boundary), `:367` and `:391` (missing and
>      malformed timestamps fail safe) — but it is **shadow-only by tested
>      design**: `:77` `test_phase5_shadow_does_not_alter_execution_relevant_fields`
>      asserts `_execution_relevant_fields(baseline_decision) ==
>      _execution_relevant_fields(shadow_decision)`. The gate that would catch
>      stale data is proven unable to change the decision that executes.
>      `analysis/evidence_status.py:9–16` confirms the two evidence vocabularies
>      are deliberately kept architecturally independent.
>   4. No age bound exists on the baseline path: `grep -niE
>      "max_age|too_old|STALE_DATA" core/candle_processor.py core/market_loop.py`
>      returns nothing. `processing_cutoff` is the cycle clock used to exclude
>      the in-progress candle (`core/candle_processor.py:26–28`, `:173–176`),
>      not an age rejection.
> - **Impact:** a provider that returns **old but well-formed closed candles**
>   — a stalled upstream cache, a delisted or halted symbol still serving its
>   last bars, a degraded endpoint — produces a full, confident, risk-approved
>   trading decision on data of unbounded age, while `health()` reports
>   `healthy: True`. The staleness flag is raised beside the decision, not in
>   front of it. Over a long unattended paper run — precisely what the vision
>   document's Paper criteria require — this is the most plausible way for the
>   run to silently stop measuring reality.
> - **Reasoning:** HIGH rather than BLOCKING for two reasons. Real capital is
>   not at risk (live authority DENIED), and the *hard* disconnect case is
>   genuinely closed, so the failure needs a specific shape — a provider that
>   succeeds while serving stale data — rather than any failure. It is not
>   MEDIUM because it defeats the purpose of the stage: Stage 1 exists to
>   produce a trustworthy divergence measurement, and this silently invalidates
>   it while reporting health.
> - **Remediation (suggested, NOT performed):** gate the decision on candle age
>   in the baseline path — reject a closed-candle batch whose newest bar is
>   older than a configured multiple of the interval, returning a
>   `SKIPPED / STALE_MARKET_DATA` outcome in the same shape as the existing
>   `INSUFFICIENT_CLOSED_CANDLES` refusal, rather than promoting the shadow
>   `FreshnessPolicy` (which would change Phase-5's tested shadow-only
>   contract and is a separate architectural decision). Separately decide, and
>   record, whether `market_data_stale` should influence `healthy` — the
>   current separation is deliberate and documented, so changing it is an owner
>   decision, not a bug fix.

---

### Item 8 — Exchange-API-error handling — **PARTIAL** (finding S-4, MEDIUM)

**The order-placement boundary is well covered, including the hard case.**
`tests/test_exchange_manager_adapter_fail_closed.py` parametrizes adapter
exceptions (`:101–119`) and asserts the classification that matters most:

| Exception | Status | Reason |
| --- | --- | --- |
| `TimeoutError` | `PENDING_RECONCILIATION` | `EXCHANGE_OUTCOME_UNKNOWN` |
| `ConnectionError` | `PENDING_RECONCILIATION` | `EXCHANGE_OUTCOME_UNKNOWN` |
| `RuntimeError` | `ERROR` | `EXCHANGE_ADAPTER_ERROR` |

A timeout is treated as **indeterminate, not failed** — the single most
important distinction in this item, and the one that prevents a phantom
duplicate order later. Each case asserts `exchange.call_count == 1` (no blind
retry) and `allowed is False`. An invalid adapter response fails closed
(`:165–194`), and genuine rejection and success dictionaries are preserved
verbatim rather than reshaped (`:197–223`, `:226–252`).

**The market-data API boundary is where the gap is.** At Stage 1 this is the
boundary that is actually live: live order placement is DENIED, so the real
network surface of a paper run is the Binance public market-data API.

---

> #### Finding S-4 — The market-data API error taxonomy is implemented but untested end-to-end, and collapses to one generic path in the loop
>
> - **Severity:** MEDIUM
> - **Location:** `atlas_finance/market_data/binance_public_provider.py`
>   (retry/backoff and status handling around lines 600–760);
>   `atlas_finance/market_data/exceptions.py`;
>   `core/market_loop.py:829–840`;
>   `tests/test_binance_public_provider_time_window.py`
> - **Evidence:** the implementation is genuinely thorough — HTTP `418` and
>   `429` raise `MarketDataRateLimitError` carrying `Retry-After`, timeouts
>   raise `MarketDataTimeoutError`, connection failures raise
>   `MarketDataConnectionError`, other request failures raise
>   `MarketDataRequestError`, unparseable bodies raise
>   `MarketDataResponseError`, and rate-limit errors deliberately bypass the
>   retry loop rather than hammering a limited endpoint. **None of that is
>   tested.** The provider's only test file,
>   `tests/test_binance_public_provider_time_window.py` (8 tests), covers
>   time-window parameter mapping; its three `pytest.raises` calls (`:109`,
>   `:113`, `:119`) are argument-validation errors raised before any HTTP call.
>   The whole-suite search for the taxonomy
>   (`git grep -l "MarketDataRateLimitError\|MarketDataTimeoutError\|MarketDataConnectionError\|MarketDataResponseError" tests/`)
>   returns two files, and the only rate-limit usage is a **fixture raising it
>   by hand** in `tests/test_historical_archive.py:73` — testing the archiver's
>   reaction, not the provider's detection. No test exercises a 429, a
>   `Retry-After`, a timeout, or the backoff path.
>   On the consumer side, `core/market_loop.py` catches no
>   `MarketData*Error` by type (`grep -nE "except .*Error" core/market_loop.py`
>   → `CandleContractError`, `ValueError`, `IndexError`, `TypeError` only);
>   every provider error lands in the broad `except Exception` at `:829`. That
>   handler is never reached from a raising provider in any test —
>   `tests/test_market_loop_reconnect.py:132` calls `loop._record_error(...)`
>   **directly**, bypassing the path it stands in for.
> - **Impact:** the behaviour is fail-closed (no decision is produced, an error
>   is recorded, health flips for the window), so the risk is not a bad trade —
>   it is undiagnosable operations and unverified retry conduct. Sustained rate
>   limiting is indistinguishable in the logs from a schema change or a DNS
>   failure; and because the backoff path has never executed under test, a
>   regression that turned rate-limit handling into a tight retry loop would be
>   caught by nothing, and could get the account's IP banned (`418`) during a
>   long paper run.
> - **Reasoning:** MEDIUM, not HIGH, because the outcome is conservative in
>   every branch — the generic handler produces the same safe refusal the
>   typed handlers would — and because correctness of the *implementation* was
>   verified by reading it, not merely assumed. It is not LOW because the only
>   live network dependency of a Stage 1 paper run has no error-path test at
>   all, and because the gap is invisible from test counts: the provider looks
>   tested.
> - **Remediation (suggested, NOT performed):** test the provider against a
>   stubbed HTTP session — 429 with and without `Retry-After`, 418, a timeout,
>   a connection reset, a malformed body — asserting the exception type, that
>   rate-limit errors do not retry, and that backoff is bounded. Then add one
>   consumer-side test raising a `MarketData*Error` **through**
>   `process_symbol`, asserting the loop records the error, returns `None`, and
>   produces no decision — so the broad handler is exercised on the real path
>   rather than simulated. Consider distinguishing rate-limit from other errors
>   in the recorded error phase for operator diagnosability; that is a
>   behaviour change and needs its own authorization.

---

### Item 9 — Reconciliation correctness — **COVERED** *[prior pass]*

Carried from the prior AUDIT MODE pass (Part 4), which classified it **strongly
covered** with real evidence. Re-verification was limited to checking that the
supporting files still exist and still carry reconciliation assertions at
`59b8392`: `tests/test_exchange_manager_outcome_reconciliation.py`,
`tests/test_block5j_execution_authority_recovery.py` (including
`test_i_safe_reconciliation_still_repairs_its_one_permitted_case:697` and
`test_j_reconciliation_against_conflicting_authority_still_refuses:724` in
`tests/test_block5k_durable_execution_storage.py`). Nothing looked stale; per
the token-efficiency contract the prior finding is not re-derived.

### Item 10 — No duplicate orders — **COVERED** *[prior pass]*

Carried from the prior pass, which classified it **strongly covered**. Spot
re-verification at `59b8392` found the supporting surface intact and
consistent: `tests/test_exchange_manager_idempotency.py`,
`tests/test_exchange_manager_concurrent_idempotency.py`,
`tests/test_exchange_manager_idempotency_persistence.py`, plus the restart-side
assertions cited under item 6 (`test_completed_request_is_still_a_duplicate_after_restart`,
`test_restart_loads_the_persisted_idempotency_record`) and the concurrency
assertion under item 4 (`sorted(outcomes) == ["blocked", "reserved"]`). Item 8's
`PENDING_RECONCILIATION` classification of an indeterminate outcome is the
upstream half of this property and is independently evidenced there.

### Item 11 — Crash handling — **PARTIAL** *[prior pass]* (prior Finding 1, MEDIUM)

Carried from the prior pass unchanged. **Prior Finding 1:** every crash path in
the suite is *simulated* — via `monkeypatch` or pre-seeded on-disk state — and
no test ever terminates a real process uncleanly mid-transaction.

This session's independent reading is consistent with that finding and did not
soften it. The simulated coverage is extensive and genuinely valuable —
`tests/test_block5k_durable_execution_storage.py` has
`test_h_crash_between_journal_and_idempotency_still_fails_closed:611`,
`test_h_crash_before_the_journal_prepare_leaves_no_entry:652`,
`test_h_crash_after_the_journal_prepare_halts_for_recovery:671`, and
`tests/test_block5h_capital_reservation_archive.py:422` covers a working-file
save failure after an archive append then restart. But the `subprocess` usage in
`tests/test_block5j_execution_authority_recovery.py:251` runs an **operator
reconciliation CLI**, not a killed runtime — confirming rather than
contradicting the prior finding. Remediation remains suggested and unperformed,
and is explicitly outside this task's authorization.

### Item 12 — Correct partial-fill handling — **ABSENT**, safe-by-refusal *[prior pass]* (prior Finding 2, MEDIUM)

Carried from the prior pass unchanged: partial fills are **refused outright,
not handled** — acceptable for paper, a real gap before testnet.

One corroborating detail found in this session's item 2 work, which supports
rather than revises the prior classification: the execution path issues only
`MARKET` orders (`core/execution_manager.py:2238–2241`), so at Stage 1 there is
no order type that would routinely produce a partial fill. That is why refusal
is a coherent Stage 1 posture and why the severity stays MEDIUM rather than
rising. It is also why the gap becomes real the moment order types widen or a
testnet venue with genuine partial fills is introduced. Remediation remains
suggested and unperformed.

---

## 4. NB-4 / NB-5 guard status

CLAUDE.md requires decision-intelligence work to guard NB-4 (removing evidence
must not raise confidence) and NB-5 (confidence must use the **expected** roster
size as denominator). Both are explicitly and directly tested —
`tests/test_nb4_nb5_confidence_availability_correction.py:101`
(`reduced.value <= full.value`), `:135–143` (risk bucket cannot relax when
evidence is lost), `:164–173` (the availability ladder is not uniformly
unanimous: `1.0 / 0.6 / 0.4 / 0.2`), `:196–200` (removing a dissenter does not
raise agreement via the denominator), `:218–220` (three genuine providers under
a five-agent configured roster yields `0.6`, not `1.0`). The producer-side
discipline at `core/market_loop.py:464` cites NB-4 by name for the same reason.
**No NB-4/NB-5 regression was observed.**

---

## 5. Top-level verdict

**Stage 1 (Paper) CANNOT currently be claimed passed. It CAN be run as an
observed first paper run.** These are different statements and the difference is
the point of this section.

**Why it can be run.** The properties that protect *state and capital* are in
good order and are evidenced, not asserted: risk limits reject and cannot be
bypassed (item 4), position accounting is exact-Decimal and replay-idempotent
(item 3), execution classifies unknown and indeterminate outcomes fail-closed
rather than optimistically (item 2), the durable stores refuse conflicting and
damaged history instead of repairing it (item 5), restart reproduces financial
state exactly and an interrupted transaction still blocks afterwards (item 6),
and duplicate orders are prevented across concurrency and restart (item 10).
Live authority is DENIED and `production_authority` is `NONE`. A supervised
paper run risks no capital and would generate exactly the operational evidence
Stage 1 needs.

**Why it cannot be claimed passed.** Four items carry a gap, and three of them
are in the same place: **the quality of the inputs, and of the conclusions drawn
from them, is not established.**

- Item 1 (HIGH): no test constrains any indicator's numeric output. Every
  downstream guard trusts `rsi` and `trend` as given.
- Item 7 (HIGH): stale-but-present market data produces a full decision while
  health reports `True`; the only max-age gate is proven shadow-only.
- Item 8 (MEDIUM): the one live network dependency of a paper run has no
  error-path test.
- Items 11 and 12 (MEDIUM each): crash handling is simulated, never real;
  partial fills are refused, not handled.

Taken together, items 1, 7 and 8 mean the system could complete a long, clean,
risk-compliant paper run and produce a performance number that is **wrong for
reasons no test would surface** — a mis-computed indicator, or hours of
decisions on stale bars, reported as healthy throughout. Stage 1's entire
purpose is to produce a trustworthy measurement. A gate cannot be declared
passed by a measurement whose inputs are unverified.

**No BLOCKING finding exists.** Nothing here can lose real capital or corrupt
durable state at Stage 1. The gaps corrupt *conclusions*, which is why the
honest verdict is "run it, observe it, and fix items 1 and 7 before treating
any number it produces as evidence" rather than either "blocked" or "ready".

### 5.1 Recommended order before the first real run

Stated as a recommendation only; none of it is authorized by registry v4.40 and
none of it was performed.

1. **Item 1** — indicator golden-vector tests. Highest value per unit of work:
   small, self-contained, no architectural decision, and it underwrites every
   other number the run produces.
2. **Item 7** — a candle-age refusal on the baseline path, shaped like the
   existing `INSUFFICIENT_CLOSED_CANDLES` refusal. Needs one owner decision
   (the age threshold) and must not disturb Phase-5's shadow-only contract.
3. **Item 8** — provider error-path tests plus one consumer-side test through
   `process_symbol`. Test-only; no behaviour change.
4. **Items 11 and 12** — leave until after the first observed run. Item 11's
   real-kill test is a test-infrastructure project, and item 12's gap does not
   bite until order types widen or a testnet venue is introduced. Both are
   genuine prerequisites for the *next* ladder stages, not this one.

---

## 6. Staleness

This checklist is a measurement of a moving repository and **will drift**, in
the same way the design document's Open Items drifted. It is valid **only** for
the tree at **`59b8392`** (source tree identical to `7772024`).

Re-verify this document when any of the following change: the contents of
`packaging/atlas_runtime_closure.json` (several verdicts turn on closure
membership); `core/technical_analyzer.py`, `analysis/technical_analyzer.py` or
`ai/core/intelligence/agent_fusion.py` (item 1); `core/market_loop.py` or
`core/candle_processor.py` (items 7 and 8);
`atlas_finance/market_data/binance_public_provider.py` (item 8);
`core/execution_manager.py` (items 2, 8, 12); or any file under `tests/` cited
above.

A status in §2 that has not been re-derived at the current HEAD is a historical
claim, not a current one. **Per CLAUDE.md's UNKNOWN rule, an item whose evidence
has not been re-verified at the commit under discussion is UNKNOWN, not
COVERED.**

---

## 7. Authority and boundaries

- **Authorized by** registry v4.40,
  `stage1_paper_validation_checklist_persistence_authorization`.
- **This document fixes nothing.** Every remediation above is suggested and was
  not performed; registry v4.40 explicitly excludes fixing prior Finding 1,
  prior Finding 2, or any gap found in this audit. Remediation is separately
  authorized work.
- **Nothing else was touched.** This audit was read-only. No source file, no
  test, no other governance record and no other findings record was modified.
  ARCH-EDGE-001, CI-EVIDENCE-001 and GOV-REVIEW-001 are unchanged.
- **Authority state is unchanged:** `production_authority=NONE`,
  `live_authority=DENIED`, `autonomous_deployment_authority=DENIED`. This
  document is not a promotion, an approval, or an independent correctness
  review of the code it audits.
- **Superseding this document** follows CLAUDE.md's Governance rule: add a new
  versioned successor record and state why it changed. Do not edit this record
  in place to make a later claim fit.
