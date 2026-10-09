"""The pre-registered regime-filter bar is applied verbatim.

P4-CLOSURE-004 (audit F-2, reviews N-1 / NF-1..NF-6): a period counts only when
it is a REGISTERED study that re-verifies against the hypothesis registry, so
the bar-arithmetic tests below build their results from a real sealed registry.
The candles are dated after the registration (the registry's own genesis time,
not a caller-supplied ``preregistered_at``), each result carries its digest,
and the arithmetic periods come from a one-member family so the family
completeness rule is met. The arithmetic and its expected verdicts are unchanged.
"""

import pytest

from research.hypothesis_registry import HypothesisRegistry
from research.lifecycle import HypothesisState
from tests.test_research_hypothesis_registry import make_preregistration
from tools import strategy_compare as sc
from tools.regime_bar_check import FILTER, REFERENCE, verdict

SPEC = sc.study_parameters({REFERENCE: {}, FILTER: {}}, days=30, windows=3, embargo=240, step=15, exp001=True)
WINDOW = {"universe": ("BTCUSDT",), "data_start": "2099-01-01T00:00:00+00:00",
          "data_end": "2100-12-31T00:00:00+00:00", "preregistered_at": "2026-10-01T00:00:00+00:00"}
FIRST_OPEN = 4_100_000_000_000  # 2099-12-03: inside the sealed window, after the registry's genesis
LATER = FIRST_OPEN + 10 * 86_400_000  # a second, non-overlapping period
PAIR, SOLO, OTHER = "FAM-REGIME-PAIR", "FAM-REGIME-SOLO", "FAM-REGIME-OTHER"


@pytest.fixture
def reg(tmp_path):
    path = tmp_path / "hypotheses.json"
    registry = HypothesisRegistry(registry_path=path)

    def add(hid, family, spec=SPEC, **window):
        registry.register(make_preregistration(hypothesis_id=hid, family_id=family,
                                               feature_spec={sc.STUDY_SPEC_KEY: spec}, **{**WINDOW, **window}))

    add("HYP-0001", PAIR)
    add("HYP-0002", PAIR)
    add("HYP-0003", PAIR, {**SPEC, "windows": 2})
    add("HYP-0004", SOLO)
    add("HYP-0005", OTHER)
    return path, registry


def study(reg, hid="HYP-0004"):
    path, registry = reg
    record = registry.get(hid)
    return {"status": "REGISTERED", "evidence_eligible": True, "hypothesis_id": hid,
            "preregistration_hash": record.preregistration_hash,
            "parameters": record.preregistration.feature_spec[sc.STUDY_SPEC_KEY]}


def result(flt, ref, ds="a", study=None, first_open=FIRST_OPEN):
    rows = lambda xs: [{"net_pnl": n, "max_drawdown": d, "closed_trades": c} for n, d, c in xs]
    out = {"table": {FILTER: rows(flt), REFERENCE: rows(ref)},
           "dataset": {"dataset_sha256": ds,
                       "symbols": {"BTCUSDT": {"first_open": first_open, "last_open": first_open + 60_000 * 1000}}}}
    if study is not None:
        out["study"] = {**study, "result_digest": sc.result_digest(out)}  # as strategy_compare.main seals it
    return out


REF = [(10, 100, 20), (10, 100, 20), (10, 100, 20)]
GOOD = [(20, 90, 12), (20, 90, 12), (5, 90, 12)]


def test_owner_v575_shape_still_needs_a_second_period(reg):
    # v5.75 nets/drawdowns; trade counts were not printed then, 10 per window is assumed here.
    flt = [(-48.14, 150, 10), (301.10, 164, 10), (466.92, 240, 10)]
    ref = [(73.61, 158, 10), (-239.26, 314, 10), (36.09, 262, 10)]
    assert verdict([result(flt, ref, study=study(reg))], reg[0])["verdict"] == "PENDING SECOND PERIOD"


def test_worse_drawdown_in_any_window_fails(reg):
    bad = [(20, 90, 12), (20, 90, 12), (20, 101, 12)]
    assert verdict([result(bad, REF, study=study(reg))], reg[0])["verdict"] == "NOT PROVEN"


def test_too_few_trades_fails(reg):
    few = [(20, 90, 5), (20, 90, 5), (20, 90, 5)]
    assert verdict([result(few, REF, study=study(reg))], reg[0])["verdict"] == "NOT PROVEN"


def test_two_periods_with_different_datasets_clear_the_bar(reg):
    a = result(GOOD, REF, "a", study(reg, "HYP-0001"))
    b = result(GOOD, REF, "b", study(reg, "HYP-0002"), LATER)
    assert verdict([a, b], reg[0])["verdict"] == "BAR CLEARED"
    # The same period supplied twice is not a second period. Before NF-2/NF-3 this read
    # PENDING SECOND PERIOD; it now reads NOT PROVEN (an overlapping, incomplete family) --
    # stricter, never more permissive.
    assert verdict([a, result(GOOD, REF, "a", study(reg, "HYP-0001"))], reg[0])["verdict"] == "NOT PROVEN"


def test_missing_variant_is_not_proven(reg):
    assert verdict([{"table": {REFERENCE: []}, "study": study(reg)}], reg[0])["verdict"] == "NOT PROVEN"


# -- F-2 / N-1: nothing unregistered, unverifiable or retroactive clears the bar --


def test_unregistered_or_exploratory_results_cannot_clear_the_bar(reg):
    for claimed in (None, {"status": "EXPLORATORY", "evidence_eligible": False}, {"status": "REGISTERED"}):
        out = verdict([result(GOOD, REF, "a", claimed), result(GOOD, REF, "b", claimed, LATER)], reg[0])
        assert out["verdict"] == "NOT PROVEN"
        assert "not a verified registered study" in out["periods"][0]["reason"]


def test_self_declared_registration_is_not_trusted(reg):
    forged = {**study(reg, "HYP-0001"), "preregistration_hash": "a" * 64}
    unknown = {**study(reg, "HYP-0001"), "hypothesis_id": "HYP-9999"}
    for claimed in (forged, unknown):
        assert verdict([result(GOOD, REF, "a", claimed), result(GOOD, REF, "b", study(reg, "HYP-0002"), LATER)],
                       reg[0])["verdict"] == "NOT PROVEN"
    good = [result(GOOD, REF, "a", study(reg, "HYP-0001")), result(GOOD, REF, "b", study(reg, "HYP-0002"), LATER)]
    assert verdict(good, reg[0])["verdict"] == "BAR CLEARED"
    assert verdict(good)["verdict"] == "NOT PROVEN"  # no registry, nothing verifiable


def test_data_from_before_the_registration_cannot_clear_the_bar(reg):
    seen_earlier = 1_700_000_000_000  # 2023-11-14: long before the registry recorded the registration
    out = verdict([result(GOOD, REF, "a", study(reg), seen_earlier)], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "before" in out["periods"][0]["reason"]


def test_nf1_a_backdated_preregistered_at_does_not_make_old_data_eligible(reg):
    path, registry = reg
    registry.register(make_preregistration(  # the caller claims 2023; the registry records today
        hypothesis_id="HYP-0006", family_id="FAM-REGIME-BACKDATED", feature_spec={sc.STUDY_SPEC_KEY: SPEC},
        universe=("BTCUSDT",), data_start="2023-11-01T00:00:00+00:00", data_end="2023-12-31T00:00:00+00:00",
        preregistered_at="2023-11-01T00:00:00+00:00"))
    out = verdict([result(GOOD, REF, "a", study(reg, "HYP-0006"), 1_700_000_000_000)], path)
    assert out["verdict"] == "NOT PROVEN" and "before the registration" in out["periods"][0]["reason"]


def test_periods_must_share_one_sealed_specification(reg):
    two_windows = result([(20, 90, 20)] * 2, [(10, 100, 20)] * 2, "b", study(reg, "HYP-0003"), LATER)
    out = verdict([result(GOOD, REF, "a", study(reg, "HYP-0001")), two_windows], reg[0])
    assert all(p["ok"] for p in out["periods"])  # each period verifies on its own
    assert out["verdict"] == "NOT PROVEN" and "different sealed study specifications" in out["note"]


# -- NF-2: bar item 3 means non-overlapping periods, not just different hashes --


def test_nf2_overlapping_periods_with_different_hashes_do_not_clear_the_bar(reg):
    a = result(GOOD, REF, "a", study(reg, "HYP-0001"))
    b = result(GOOD, REF, "b", study(reg, "HYP-0002"), FIRST_OPEN + 60_000 * 500)  # half the same candles
    out = verdict([a, b], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "overlap" in out["note"]


# -- NF-3: no best-of-N selection across hypotheses or families --


def test_nf3_every_family_member_with_the_specification_must_be_supplied(reg):
    out = verdict([result(GOOD, REF, "a", study(reg, "HYP-0001"))], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "every registered hypothesis" in out["note"]


def test_nf3_periods_from_different_families_do_not_combine(reg):
    out = verdict([result(GOOD, REF, "a", study(reg, "HYP-0004")),
                   result(GOOD, REF, "b", study(reg, "HYP-0005"), LATER)], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "different hypothesis families" in out["note"]


# -- NF-4: a study block cannot be copied onto other numbers, nor numbers edited after the run --


def test_nf4_a_copied_study_block_or_edited_numbers_are_refused(reg):
    sealed = result(REF, REF, "a", study(reg))  # the real run: the filter did not win
    copied = result(GOOD, REF, "a")
    copied["study"] = sealed["study"]
    edited = result(REF, REF, "a", study(reg))
    edited["table"][FILTER][0]["net_pnl"] = 999
    for forged in (copied, edited):
        out = verdict([forged], reg[0])
        assert out["verdict"] == "NOT PROVEN" and "altered or relabelled" in out["periods"][0]["reason"]


def test_a_table_that_is_not_the_sealed_shape_is_refused(reg):
    out = verdict([result(GOOD + [(20, 90, 12)], REF + [(10, 100, 20)], "a", study(reg))], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "shape" in out["periods"][0]["reason"]


# -- NF-6: a terminal hypothesis's results are not evidence --


def test_nf6_results_of_a_terminal_hypothesis_do_not_count(reg):
    path, registry = reg
    period = result(GOOD, REF, "a", study(reg))
    registry.advance("HYP-0004", HypothesisState.REJECTED)
    out = verdict([period], path)
    assert out["verdict"] == "NOT PROVEN" and "REJECTED" in out["periods"][0]["reason"]


# -- NF-7: malformed input is refused, never raised --


@pytest.mark.parametrize("mangle", [
    lambda r: r.update(dataset=["not", "a", "dict"]),
    lambda r: r["dataset"]["symbols"]["BTCUSDT"].update(first_open="2099"),
    lambda r: r.update(study={**r["study"], "parameters": None}),
])
def test_nf7_malformed_results_are_refused_not_raised(reg, mangle):
    period = result(GOOD, REF, "a", study(reg))
    mangle(period)
    assert verdict([period], reg[0])["verdict"] == "NOT PROVEN"
