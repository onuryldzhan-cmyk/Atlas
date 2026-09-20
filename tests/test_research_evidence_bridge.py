"""Contract tests for the L3 research-to-Evidence-Store bridge (ADR-0009).

The bridge is the only sanctioned route from a five-check verdict into the
Evidence Store. These tests pin the four properties that route exists to
guarantee:

* **The boundary holds.** The bridge imports ``ClaimSource`` from L1 and
  never the L2 store, and the store arrives by constructor injection. A
  static check here mirrors ``tests/test_research_isolation.py``'s guard
  from the other side of the same edge.
* **NB-4 at this boundary.** Removing a recorded check result can never
  raise the confidence written. This is exercised over every subset of the
  five checks, not a chosen few.
* **NB-5 at this boundary.** The denominator is the sealed plan's
  required-check count, never the number of results that happen to exist,
  so a half-run plan cannot be recorded as unanimous.
* **Nothing is invented.** A malformed verdict, a naive timestamp or an
  absent store is refused rather than filled in with a substitute.

Every test points the store at pytest's ``tmp_path``. Nothing here touches
a configured durable root, and no test reads or writes real runtime state.
"""

from __future__ import annotations

import ast
import itertools
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from core.research_evidence_bridge import (
    CLAIM_AGENT_ID,
    CLAIM_KIND,
    SOURCE_KIND,
    ResearchEvidenceBridge,
    ResearchEvidenceBridgeError,
)
from data_layer.contracts import ClaimSource
from data_layer.evidence_store import EvidenceStore
from research.hypothesis_registry import (
    REGISTRY_FORMAT_VERSION,
    CheckName,
    CheckPlan,
    CheckPlanStatus,
    CheckVerdict,
    EvaluationRecord,
    HypothesisRecord,
)
from research.lifecycle import HypothesisState
from tests.test_research_hypothesis_checks import (
    FULL_CHECK_PLAN,
    TEST_SEGMENT_CHECKS,
    full_preregistration,
    make_check,
)


PASS = CheckVerdict.PASS
FAIL = CheckVerdict.FAIL

RUN_ID = "research-run-0001"

#: A distinct, fixed time per check, so that "the latest recorded check" is
#: a determinate value a test can assert rather than a wall-clock read.
CHECK_TIMES = {
    CheckName.BACKTEST: "2026-09-01T00:00:00+00:00",
    CheckName.WALK_FORWARD: "2026-09-02T00:00:00+00:00",
    CheckName.OUT_OF_SAMPLE: "2026-09-03T00:00:00+00:00",
    CheckName.COST_ADJUSTED: "2026-09-03T00:00:00+00:00",
    CheckName.MONTE_CARLO: "2026-09-03T00:00:00+00:00",
}

LATEST_CHECK_TIME = datetime(2026, 9, 3, tzinfo=UTC)

#: ``full_preregistration`` seals this; it is the fallback assertion time
#: for a record carrying no recorded check at all.
PREREGISTERED_AT = datetime(2026, 8, 1, tzinfo=UTC)

ALL_FIVE = tuple(CheckName)

#: Every subset of the five checks. The NB-4 property is a claim about all
#: possible removals of evidence, so it is tested over all of them.
EVERY_SUBSET_OF_CHECKS = [
    subset
    for size in range(len(ALL_FIVE) + 1)
    for subset in itertools.combinations(ALL_FIVE, size)
]

_SEGMENTS: tuple[tuple[str, tuple[CheckName, ...], dict[str, float]], ...] = (
    ("TRAIN", (CheckName.BACKTEST,), {}),
    ("CALIBRATION", (CheckName.WALK_FORWARD,), {}),
    ("TEST", TEST_SEGMENT_CHECKS, {"p_value": 0.01, "effect_size": 0.8}),
)


# --- helpers -------------------------------------------------------------


def make_record(
    *,
    present: tuple[CheckName, ...] = ALL_FIVE,
    verdicts: dict[CheckName, CheckVerdict] | None = None,
    universe: tuple[str, ...] | None = None,
    plan: CheckPlan | None = None,
    hypothesis_id: str = "HYP-0001",
) -> HypothesisRecord:
    """A hypothesis record carrying exactly ``present`` recorded checks.

    Built directly rather than through ``HypothesisRegistry`` because the
    registry's lifecycle is not what is under test here, and because
    "three of five checks recorded" is a state the write path reaches only
    part way through a run.
    """
    verdicts = verdicts or {}
    overrides: dict[str, Any] = {"check_plan": plan or FULL_CHECK_PLAN}
    if universe is not None:
        overrides["universe"] = universe
    preregistration = full_preregistration(hypothesis_id, **overrides)

    evaluations = []
    for segment, names, extra in _SEGMENTS:
        checks = tuple(
            replace(
                make_check(name, verdicts.get(name, PASS)),
                recorded_at=CHECK_TIMES[name],
            )
            for name in names
            if name in present
        )
        if not checks:
            continue
        evaluations.append(
            EvaluationRecord(
                segment=segment,
                statistic_value=0.8,
                checks=checks,
                recorded_at=CHECK_TIMES[names[0]],
                **extra,
            )
        )

    return HypothesisRecord(
        preregistration=preregistration,
        preregistration_hash=preregistration.seal_hash(),
        state=HypothesisState.TESTED,
        evaluations=tuple(evaluations),
    )


class RecordingStore:
    """A stand-in store that captures the call instead of persisting it.

    Deliberately not a ``Mock``: the bridge's contract is the exact keyword
    set ``record_claim`` is called with, and a permissive mock would accept
    a misspelled one.
    """

    def __init__(self, claim_id: str = "claim-0001") -> None:
        self.claim_id = claim_id
        self.calls: list[dict[str, Any]] = []

    def record_claim(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return self.claim_id

    @property
    def last(self) -> dict[str, Any]:
        assert self.calls, "the bridge recorded nothing"
        return self.calls[-1]


class ExplodingStore:
    def record_claim(self, **kwargs: Any) -> str:
        raise RuntimeError("disk is gone")


@dataclass(frozen=True)
class FakeVerdict:
    """A hand-built adjudication, for verdict shapes the real one forbids."""

    required_check_count: Any = 5
    passed_check_count: Any = 5
    recorded_check_count: Any = 5
    missing_checks: Any = ()
    failed_checks: Any = ()
    status: Any = CheckPlanStatus.COMPLETE_PASS


class FakeRecord:
    def __init__(self, verdict: Any, record: HypothesisRecord | None = None):
        self._verdict = verdict
        self._record = record or make_record()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._record, name)

    def adjudicate_checks(self) -> Any:
        return self._verdict


@pytest.fixture()
def store():
    return RecordingStore()


@pytest.fixture()
def bridge(store):
    return ResearchEvidenceBridge(store, run_id=RUN_ID)


@pytest.fixture()
def real_store(tmp_path):
    instance = EvidenceStore(tmp_path / "evidence_store.sqlite3")
    instance.open()
    yield instance
    instance.close()


# --- the boundary --------------------------------------------------------


def test_the_bridge_never_imports_the_store_it_writes_to():
    """L3 may call the L2 store, but only through the injected instance.

    ADR-0009's whole point is that the type travels by L1 and the store
    travels by injection. An import of ``data_layer.evidence_store`` here
    would make the bridge depend on the infrastructure it is meant to hold
    at arm's length, and would do it invisibly to the architecture gate,
    which resolves only direct dotted imports.
    """
    source = Path("core/research_evidence_bridge.py").read_text(
        encoding="utf-8"
    )
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(
                f"{node.module}.{alias.name}" for alias in node.names
            )

    assert "data_layer.evidence_store" not in imported
    assert not any(
        name.startswith("data_layer.evidence_store") for name in imported
    )
    assert "data_layer.contracts.ClaimSource" in imported


def test_the_store_is_injected_and_held_as_given(store):
    assert ResearchEvidenceBridge(store, run_id=RUN_ID).evidence_store is store


def test_a_missing_store_is_refused_at_construction():
    """A bridge with no store has no degraded mode; it has a bug.

    AtlasBrain tolerates an absent store because its recording is
    incidental to a decision it must not disturb. Recording is the whole of
    this object's job, so an absent store is refused where the composition
    root can still see it.
    """
    with pytest.raises(ResearchEvidenceBridgeError, match="evidence_store"):
        ResearchEvidenceBridge(None, run_id=RUN_ID)


@pytest.mark.parametrize("run_id", ["", "   ", None, 7])
def test_a_claim_needs_a_run_id(store, run_id):
    with pytest.raises(ResearchEvidenceBridgeError, match="run_id"):
        ResearchEvidenceBridge(store, run_id=run_id)


def test_a_claim_needs_an_agent_id(store):
    with pytest.raises(ResearchEvidenceBridgeError, match="agent_id"):
        ResearchEvidenceBridge(store, run_id=RUN_ID, agent_id="  ")


# --- the claim the bridge builds ----------------------------------------


def test_a_fully_passing_plan_records_full_confidence(bridge, store):
    claim_id = bridge.record_verdict(make_record())

    assert claim_id == store.claim_id
    call = store.last
    assert call["confidence"] == Decimal(1)
    assert call["claim_kind"] == CLAIM_KIND
    assert call["subject_scope"] == "SYMBOL"
    assert call["subject_symbol"] == "BTCUSDT"
    assert call["agent_id"] == CLAIM_AGENT_ID
    assert call["agent_version"] == str(REGISTRY_FORMAT_VERSION)
    assert call["run_id"] == RUN_ID
    assert call["payload"]["check_plan_status"] == "COMPLETE_PASS"
    assert call["payload"]["passed_check_count"] == 5
    assert call["payload"]["required_check_count"] == 5
    assert call["reason_codes"] == ["COMPLETE_PASS"]


def test_confidence_is_decimal_never_float(bridge, store):
    """The store refuses a float outright; this pins why it never sees one."""
    bridge.record_verdict(make_record())
    assert isinstance(store.last["confidence"], Decimal)


def test_the_source_carries_the_seal_of_what_was_adjudicated(bridge, store):
    record = make_record()
    bridge.record_verdict(record)

    (source,) = store.last["sources"]
    assert isinstance(source, ClaimSource)
    assert source.source_kind == SOURCE_KIND
    assert source.source_uri == "hypothesis-registry://HYP-0001"
    assert source.source_digest == record.preregistration_hash
    assert source.retrieved_at == LATEST_CHECK_TIME


def test_a_failed_check_is_named_in_the_reason_codes(bridge, store):
    bridge.record_verdict(
        make_record(verdicts={CheckName.COST_ADJUSTED: FAIL})
    )

    call = store.last
    assert call["confidence"] == Decimal(4) / Decimal(5)
    assert call["payload"]["check_plan_status"] == "COMPLETE_FAIL"
    assert call["payload"]["failed_checks"] == ["COST_ADJUSTED"]
    assert "FAILED_COST_ADJUSTED" in call["reason_codes"]


def test_a_partly_run_plan_is_recorded_as_incomplete(bridge, store):
    """Four of five gates evaluated is INCOMPLETE, not a near-pass."""
    bridge.record_verdict(
        make_record(present=tuple(ALL_FIVE[:4]))
    )

    call = store.last
    assert call["payload"]["check_plan_status"] == "INCOMPLETE"
    assert call["payload"]["missing_checks"] == ["MONTE_CARLO"]
    assert "MISSING_MONTE_CARLO" in call["reason_codes"]
    assert call["confidence"] == Decimal(4) / Decimal(5)


def test_a_multi_symbol_universe_is_not_filed_against_one_symbol(
    bridge, store
):
    bridge.record_verdict(make_record(universe=("BTCUSDT", "ETHUSDT")))

    call = store.last
    assert call["subject_scope"] == "MARKET"
    assert call["subject_symbol"] is None
    assert call["payload"]["universe"] == ["BTCUSDT", "ETHUSDT"]


def test_the_assertion_time_is_the_verdicts_own_not_the_wall_clock(
    bridge, store
):
    bridge.record_verdict(make_record())
    assert store.last["asserted_at"] == LATEST_CHECK_TIME


def test_a_record_with_no_recorded_check_falls_back_to_the_seal_time(
    bridge, store
):
    bridge.record_verdict(make_record(present=()))

    call = store.last
    assert call["asserted_at"] == PREREGISTERED_AT
    assert call["confidence"] == Decimal(0)
    assert call["payload"]["check_plan_status"] == "INCOMPLETE"


# --- NB-5: the denominator ----------------------------------------------


def test_the_denominator_is_the_sealed_plan_not_the_results_present(
    bridge, store
):
    """Two of five recorded, both passing, must not read as unanimous.

    This is the NB-5 failure in its exact shape: were the denominator
    ``recorded_check_count``, this claim would be written at confidence
    1.0 on 40% of the evidence.
    """
    bridge.record_verdict(
        make_record(present=(CheckName.BACKTEST, CheckName.WALK_FORWARD))
    )

    call = store.last
    assert call["payload"]["recorded_check_count"] == 2
    assert call["payload"]["required_check_count"] == 5
    assert call["confidence"] == Decimal(2) / Decimal(5)
    assert call["confidence"] < Decimal(1)


def test_a_smaller_plan_keeps_its_own_denominator(bridge, store):
    plan = CheckPlan(required_checks=(CheckName.OUT_OF_SAMPLE,))
    bridge.record_verdict(
        make_record(present=(CheckName.OUT_OF_SAMPLE,), plan=plan)
    )

    assert store.last["payload"]["required_check_count"] == 1
    assert store.last["confidence"] == Decimal(1)


# --- NB-4: removing evidence ---------------------------------------------


@pytest.mark.parametrize("present", EVERY_SUBSET_OF_CHECKS)
def test_removing_evidence_never_raises_the_recorded_confidence(
    bridge, store, present
):
    """Confidence is monotone non-increasing under any removal of results.

    The full plan is the ceiling; every subset of it is recorded at a
    confidence no higher, and exactly the passing fraction of the sealed
    plan. A subset can only lose a numerator, never shrink a denominator.
    """
    bridge.record_verdict(make_record())
    full_confidence = store.last["confidence"]

    bridge.record_verdict(make_record(present=present))
    subset_confidence = store.last["confidence"]

    assert subset_confidence <= full_confidence
    assert subset_confidence == Decimal(len(present)) / Decimal(5)


def test_dropping_one_result_from_a_passing_plan_lowers_confidence(
    bridge, store
):
    bridge.record_verdict(make_record())
    before = store.last["confidence"]

    bridge.record_verdict(make_record(present=tuple(ALL_FIVE[:-1])))
    after = store.last["confidence"]

    assert after < before
    assert store.last["payload"]["check_plan_status"] == "INCOMPLETE"


# --- malformed input is refused, never filled in -------------------------


def test_an_object_carrying_no_verdict_is_refused(bridge):
    class NotARecord:
        hypothesis_id = "HYP-0001"
        preregistration = full_preregistration()

    with pytest.raises(
        ResearchEvidenceBridgeError, match="adjudicate_checks"
    ):
        bridge.record_verdict(NotARecord())


def test_a_record_without_a_preregistration_is_refused(bridge):
    class NoPrereg:
        hypothesis_id = "HYP-0001"
        preregistration = None

    with pytest.raises(
        ResearchEvidenceBridgeError, match="no preregistration"
    ):
        bridge.record_verdict(NoPrereg())


def test_a_verdict_of_none_is_refused(bridge):
    with pytest.raises(ResearchEvidenceBridgeError, match="no check adjud"):
        bridge.record_verdict(FakeRecord(None))


@pytest.mark.parametrize(
    "field_name",
    [
        "required_check_count",
        "passed_check_count",
        "recorded_check_count",
        "missing_checks",
        "failed_checks",
        "status",
    ],
)
def test_a_verdict_missing_any_field_is_refused(bridge, field_name):
    class Partial:
        pass

    verdict = Partial()
    for name, value in FakeVerdict().__dict__.items():
        if name != field_name:
            setattr(verdict, name, value)

    with pytest.raises(ResearchEvidenceBridgeError, match=field_name):
        bridge.record_verdict(FakeRecord(verdict))


@pytest.mark.parametrize(
    "verdict",
    [
        FakeVerdict(required_check_count=0, passed_check_count=0),
        FakeVerdict(required_check_count=-1, passed_check_count=0),
        FakeVerdict(required_check_count="five"),
        FakeVerdict(passed_check_count=None),
        FakeVerdict(passed_check_count=6),
        FakeVerdict(passed_check_count=-1),
        FakeVerdict(recorded_check_count=-1),
        FakeVerdict(missing_checks="MONTE_CARLO"),
        FakeVerdict(failed_checks=None),
        FakeVerdict(status="   "),
    ],
)
def test_a_malformed_verdict_is_refused_rather_than_defaulted(
    bridge, store, verdict
):
    with pytest.raises(ResearchEvidenceBridgeError):
        bridge.record_verdict(FakeRecord(verdict))
    assert store.calls == []


def test_a_verdict_that_hides_a_shortfall_is_refused(bridge, store):
    """Counts that do not add up to the plan are a silent NB-4 breach.

    Two passed and nothing reported missing or failed, against a plan of
    five, would be written at confidence 0.4 with no record that three
    gates are unaccounted for. The bridge refuses the whole claim instead.
    """
    with pytest.raises(
        ResearchEvidenceBridgeError, match="does not account for"
    ):
        bridge.record_verdict(
            FakeRecord(
                FakeVerdict(
                    required_check_count=5,
                    passed_check_count=2,
                    recorded_check_count=2,
                    missing_checks=(),
                    failed_checks=(),
                    status=CheckPlanStatus.INCOMPLETE,
                )
            )
        )
    assert store.calls == []


def test_a_naive_check_timestamp_is_refused(bridge, store):
    """A timestamp with no offset is not silently read as UTC."""
    record = make_record()
    naive = replace(
        record.evaluations[0].checks[0], recorded_at="2026-09-01T00:00:00"
    )
    broken = replace(record.evaluations[0], checks=(naive,))
    record = replace(record, evaluations=(broken,) + record.evaluations[1:])

    with pytest.raises(ResearchEvidenceBridgeError, match="timezone"):
        bridge.record_verdict(record)
    assert store.calls == []


def test_an_empty_universe_is_refused(bridge, store):
    """A claim needs a subject; the bridge does not choose one for it."""

    class EmptyUniverse:
        universe = ()
        preregistered_at = "2026-08-01T00:00:00+00:00"

    class NoSubject:
        hypothesis_id = "HYP-0001"
        preregistration = EmptyUniverse()

        def adjudicate_checks(self) -> Any:
            return FakeVerdict()

    with pytest.raises(ResearchEvidenceBridgeError, match="universe"):
        bridge.record_verdict(NoSubject())
    assert store.calls == []


def test_a_store_failure_is_raised_not_swallowed():
    """Nothing downstream depends on this write, so it is not absorbed."""
    bridge = ResearchEvidenceBridge(ExplodingStore(), run_id=RUN_ID)
    with pytest.raises(RuntimeError, match="disk is gone"):
        bridge.record_verdict(make_record())


# --- integration: a real verdict through a real store --------------------


def test_a_real_verdict_reaches_the_real_store(real_store):
    """Real record -> real ClaimSource -> real record_claim, read back."""
    record = make_record(verdicts={CheckName.MONTE_CARLO: FAIL})
    bridge = ResearchEvidenceBridge(real_store, run_id=RUN_ID)

    claim_id = bridge.record_verdict(record)

    stored = real_store.get(claim_id)
    assert stored is not None
    assert stored.agent_id == CLAIM_AGENT_ID
    assert stored.agent_version == str(REGISTRY_FORMAT_VERSION)
    assert stored.claim_kind == CLAIM_KIND
    assert stored.subject_scope == "SYMBOL"
    assert stored.subject_symbol == "BTCUSDT"
    assert stored.run_id == RUN_ID
    assert stored.confidence == Decimal(4) / Decimal(5)
    assert stored.asserted_at_utc == "2026-09-03T00:00:00Z"
    assert stored.payload["hypothesis_id"] == "HYP-0001"
    assert stored.payload["family_id"] == "FAM-REVERSAL-2026Q3"
    assert stored.payload["state"] == "TESTED"
    assert stored.payload["failed_checks"] == ["MONTE_CARLO"]
    assert stored.payload["required_check_count"] == 5
    assert stored.payload["check_plan_status"] == "COMPLETE_FAIL"
    assert "FAILED_MONTE_CARLO" in stored.reason_codes

    (source,) = real_store.sources_for(claim_id)
    assert source.source_kind == SOURCE_KIND
    assert source.source_uri == "hypothesis-registry://HYP-0001"
    assert source.source_digest == record.preregistration_hash
    assert source.retrieved_at == LATEST_CHECK_TIME

    assert real_store.health()["claims_written"] == 1


def test_recording_the_same_verdict_twice_is_idempotent(real_store):
    """The second submission collides in the database rather than doubling."""
    record = make_record()
    bridge = ResearchEvidenceBridge(real_store, run_id=RUN_ID)

    first = bridge.record_verdict(record)
    second = bridge.record_verdict(record)

    assert first == second
    health = real_store.health()
    assert health["claim_count"] == 1
    assert health["claims_written"] == 1
    assert health["claims_deduplicated"] == 1


def test_two_bridges_over_the_same_verdict_agree_on_the_claim_id(real_store):
    """Idempotency does not depend on reusing one bridge instance."""
    record = make_record()

    first = ResearchEvidenceBridge(
        real_store, run_id="run-a"
    ).record_verdict(record)
    second = ResearchEvidenceBridge(
        real_store, run_id="run-b"
    ).record_verdict(record)

    assert first == second
    assert real_store.health()["claim_count"] == 1


def test_a_changed_verdict_is_a_new_claim_not_an_overwrite(real_store):
    """Evidence added later is recorded beside the earlier reading."""
    bridge = ResearchEvidenceBridge(real_store, run_id=RUN_ID)

    partial = bridge.record_verdict(
        make_record(present=(CheckName.BACKTEST,))
    )
    complete = bridge.record_verdict(make_record())

    assert partial != complete
    assert real_store.get(partial).confidence == Decimal(1) / Decimal(5)
    assert real_store.get(complete).confidence == Decimal(1)
    assert real_store.health()["claim_count"] == 2
