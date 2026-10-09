"""The pre-registered regime-filter bar is applied verbatim.

P4-CLOSURE-004 (audit F-2; reviews N-1, NF-1..NF-6, NEW-1..NEW-3, R4-1, R4-2):
a period counts only when it is a REGISTERED study that re-verifies against
the canonical hypothesis registry, so the bar-arithmetic tests below build
their results from a real sealed registry. Each hypothesis seals its own exact
window (after the registry's genesis time, exactly the sealed ``days``), its
one run is recorded (``start_study_run``), its result claims exactly that
window and carries its digest, and the arithmetic periods come from a
one-member family so the family completeness rule is met. The arithmetic and
its expected verdicts are unchanged.
"""

from datetime import datetime, timedelta, timezone

import pytest

from research.hypothesis_registry import HypothesisRegistry
from research.lifecycle import HypothesisState
from tests.test_research_hypothesis_registry import make_preregistration
from tools import strategy_compare as sc
from tools.regime_bar_check import FILTER, REFERENCE, verdict

SPEC = sc.study_parameters({REFERENCE: {}, FILTER: {}}, days=30, windows=3, embargo=240, step=15, exp001=True)
BASE = datetime(2100, 1, 1, tzinfo=timezone.utc)  # after the registry's genesis time (today)
PAIR, SOLO, OTHER, SPECS = "FAM-REGIME-PAIR", "FAM-REGIME-SOLO", "FAM-REGIME-OTHER", "FAM-REGIME-SPECS"


def window(slot, days=30, offset_days=0):
    """Sealed window number ``slot``: consecutive, non-overlapping 31-day slots."""
    start = BASE + timedelta(days=31 * slot + offset_days)
    return {"data_start": start.isoformat(), "data_end": (start + timedelta(days=days)).isoformat()}


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(tmp_path))
    (tmp_path / "research").mkdir()
    out = (sc.canonical_registry(), None)
    _register(out, "HYP-0001", PAIR, slot=0)
    _register(out, "HYP-0002", PAIR, slot=1)
    _register(out, "HYP-0003", SPECS, {**SPEC, "windows": 2}, slot=2)
    _register(out, "HYP-0004", SOLO, slot=3)
    _register(out, "HYP-0005", OTHER, slot=4)
    return out


def fresh(reg):
    return HypothesisRegistry(registry_path=reg[0])  # runs are recorded through other instances


def _register(reg, hid, family, spec=SPEC, universe=("BTCUSDT",), slot=0, **window_override):
    fresh(reg).register(make_preregistration(
        hypothesis_id=hid, family_id=family, feature_spec={sc.STUDY_SPEC_KEY: spec}, universe=universe,
        preregistered_at="2026-10-01T00:00:00+00:00", **{**window(slot, spec["days"]), **window_override}))


def study(reg, hid="HYP-0004"):
    """The study block of the hypothesis's one run, recording that run on first use (as main() does)."""
    record = fresh(reg).get(hid)
    bound = {"status": "REGISTERED", "evidence_eligible": True, "hypothesis_id": hid,
             "preregistration_hash": record.preregistration_hash,
             "parameters": record.preregistration.feature_spec[sc.STUDY_SPEC_KEY]}
    if record.state is HypothesisState.REGISTERED:
        return sc.start_study_run(reg[0], bound)
    return {**bound, "run_started_at": sc._run_started_at(record)}


def result(flt, ref, ds="a", study=None, reg=None, first_open=None):
    """A result whose dataset manifest is exactly its hypothesis's sealed window (as main() produces)."""
    rows = lambda xs: [{"net_pnl": n, "max_drawdown": d, "closed_trades": c} for n, d, c in xs]
    symbols = {"BTCUSDT": {"first_open": 0, "last_open": 0, "rows": 0}}
    known = {r.hypothesis_id for r in fresh(reg).all_records()} if reg is not None else set()
    if study is not None and study.get("hypothesis_id") in known:
        record = fresh(reg).get(study["hypothesis_id"])
        start = int(datetime.fromisoformat(record.preregistration.data_start).timestamp() * 1000)
        end = int(datetime.fromisoformat(record.preregistration.data_end).timestamp() * 1000)
        start = start if first_open is None else first_open
        symbols = {sym: {"first_open": start, "last_open": end - 60_000, "rows": (end - start) // 60_000}
                   for sym in record.preregistration.universe}
    out = {"table": {FILTER: rows(flt), REFERENCE: rows(ref)}, "dataset": {"dataset_sha256": ds, "symbols": symbols}}
    if study is not None:
        out["study"] = dict(study)  # as strategy_compare.main seals it
        out["study"]["result_digest"] = sc.result_digest(out)
    return out


def period(reg, hid, flt, ref, ds, **kw):
    return result(flt, ref, ds, study(reg, hid), reg, **kw)


REF = [(10, 100, 20), (10, 100, 20), (10, 100, 20)]
GOOD = [(20, 90, 12), (20, 90, 12), (5, 90, 12)]


def test_owner_v575_shape_still_needs_a_second_period(reg):
    # v5.75 nets/drawdowns; trade counts were not printed then, 10 per window is assumed here.
    flt = [(-48.14, 150, 10), (301.10, 164, 10), (466.92, 240, 10)]
    ref = [(73.61, 158, 10), (-239.26, 314, 10), (36.09, 262, 10)]
    assert verdict([period(reg, "HYP-0004", flt, ref, "a")], reg[0])["verdict"] == "PENDING SECOND PERIOD"


def test_worse_drawdown_in_any_window_fails(reg):
    bad = [(20, 90, 12), (20, 90, 12), (20, 101, 12)]
    assert verdict([period(reg, "HYP-0004", bad, REF, "a")], reg[0])["verdict"] == "NOT PROVEN"


def test_too_few_trades_fails(reg):
    few = [(20, 90, 5), (20, 90, 5), (20, 90, 5)]
    assert verdict([period(reg, "HYP-0004", few, REF, "a")], reg[0])["verdict"] == "NOT PROVEN"


def test_two_periods_with_different_datasets_clear_the_bar(reg):
    a, b = period(reg, "HYP-0001", GOOD, REF, "a"), period(reg, "HYP-0002", GOOD, REF, "b")
    assert verdict([a, b], reg[0])["verdict"] == "BAR CLEARED"
    # The same period supplied twice is not a second period. Before NF-2/NF-3 this read
    # PENDING SECOND PERIOD; it now reads NOT PROVEN (an overlapping, incomplete family) --
    # stricter, never more permissive.
    assert verdict([a, period(reg, "HYP-0001", GOOD, REF, "a")], reg[0])["verdict"] == "NOT PROVEN"


def test_missing_variant_is_not_proven(reg):
    assert verdict([{"table": {REFERENCE: []}, "study": study(reg)}], reg[0])["verdict"] == "NOT PROVEN"


# -- F-2 / N-1: nothing unregistered, unverifiable or retroactive clears the bar --


def test_unregistered_or_exploratory_results_cannot_clear_the_bar(reg):
    for claimed in (None, {"status": "EXPLORATORY", "evidence_eligible": False}, {"status": "REGISTERED"}):
        out = verdict([result(GOOD, REF, "a", claimed), result(GOOD, REF, "b", claimed)], reg[0])
        assert out["verdict"] == "NOT PROVEN"
        assert "not a verified registered study" in out["periods"][0]["reason"]


def test_self_declared_registration_is_not_trusted(reg):
    forged = {**study(reg, "HYP-0001"), "preregistration_hash": "a" * 64}
    unknown = {**study(reg, "HYP-0001"), "hypothesis_id": "HYP-9999"}
    for claimed in (forged, unknown):
        assert verdict([result(GOOD, REF, "a", claimed, reg), period(reg, "HYP-0002", GOOD, REF, "b")],
                       reg[0])["verdict"] == "NOT PROVEN"
    good = [period(reg, "HYP-0001", GOOD, REF, "a"), period(reg, "HYP-0002", GOOD, REF, "b")]
    assert verdict(good, reg[0])["verdict"] == "BAR CLEARED"
    assert verdict(good)["verdict"] == "NOT PROVEN"  # no registry, nothing verifiable


def test_data_from_before_the_registration_cannot_clear_the_bar(reg):
    seen_earlier = 1_700_000_040_000  # 2023-11-14: long before the registry recorded the registration
    out = verdict([period(reg, "HYP-0004", GOOD, REF, "a", first_open=seen_earlier)], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "before" in out["periods"][0]["reason"]


def test_nf1_a_backdated_preregistered_at_does_not_make_old_data_eligible(reg):
    fresh(reg).register(make_preregistration(  # the caller claims 2023; the registry records today
        hypothesis_id="HYP-0006", family_id="FAM-REGIME-BACKDATED", feature_spec={sc.STUDY_SPEC_KEY: SPEC},
        universe=("BTCUSDT",), data_start="2023-11-01T00:00:00+00:00", data_end="2023-12-01T00:00:00+00:00",
        preregistered_at="2023-11-01T00:00:00+00:00"))
    out = verdict([period(reg, "HYP-0006", GOOD, REF, "a")], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "before the registration" in out["periods"][0]["reason"]


def test_periods_must_share_one_sealed_specification(reg):
    two_windows = period(reg, "HYP-0003", [(20, 90, 20)] * 2, [(10, 100, 20)] * 2, "b")
    out = verdict([period(reg, "HYP-0001", GOOD, REF, "a"), two_windows], reg[0])
    assert all(p["ok"] for p in out["periods"])  # each period verifies on its own
    assert out["verdict"] == "NOT PROVEN" and "different sealed study specifications" in out["note"]


# -- NF-2 / NEW-1: bar item 3 means non-overlapping periods, not just different hashes --


def test_nf2_overlapping_periods_with_different_hashes_do_not_clear_the_bar(reg):
    _register(reg, "HYP-0040", "FAM-REGIME-OVERLAP", slot=5)
    _register(reg, "HYP-0041", "FAM-REGIME-OVERLAP", slot=5, **window(5, offset_days=15))  # half the same dates
    out = verdict([period(reg, "HYP-0040", GOOD, REF, "a"), period(reg, "HYP-0041", GOOD, REF, "b")], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "overlap" in out["note"]


def test_new1_two_universes_over_the_same_dates_are_one_period(reg):
    _register(reg, "HYP-0010", "FAM-REGIME-UNIVERSE", slot=6)
    _register(reg, "HYP-0011", "FAM-REGIME-UNIVERSE", universe=("ETHUSDT",), slot=6)
    out = verdict([period(reg, "HYP-0010", GOOD, REF, "a"), period(reg, "HYP-0011", GOOD, REF, "b")], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "overlap" in out["note"]
    _register(reg, "HYP-0012", "FAM-REGIME-UNIVERSE-B", slot=7)
    _register(reg, "HYP-0013", "FAM-REGIME-UNIVERSE-B", universe=("ETHUSDT",), slot=8)
    later = [period(reg, "HYP-0012", GOOD, REF, "a"), period(reg, "HYP-0013", GOOD, REF, "b")]
    assert verdict(later, reg[0])["verdict"] == "BAR CLEARED"  # disjoint dates do clear


# -- NF-3 / NEW-2: no best-of-N selection across hypotheses, specifications, runs or families --


def test_nf3_every_family_member_must_be_supplied(reg):
    out = verdict([period(reg, "HYP-0001", GOOD, REF, "a")], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "every registered hypothesis" in out["note"]


def test_nf3_periods_from_different_families_do_not_combine(reg):
    out = verdict([period(reg, "HYP-0004", GOOD, REF, "a"), period(reg, "HYP-0005", GOOD, REF, "b")], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "different hypothesis families" in out["note"]


def test_new2a_varying_the_specification_inside_a_family_is_not_a_way_out(reg):
    _register(reg, "HYP-0020", "FAM-REGIME-MIXED", slot=9)
    _register(reg, "HYP-0021", "FAM-REGIME-MIXED", slot=10)
    _register(reg, "HYP-0022", "FAM-REGIME-MIXED", {**SPEC, "step": 16}, slot=11)  # the losing variant, left out
    out = verdict([period(reg, "HYP-0020", GOOD, REF, "a"), period(reg, "HYP-0021", GOOD, REF, "b")], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "HYP-0022" in out["note"]


def test_new2b_a_hypothesis_hosts_exactly_one_recorded_run(reg):
    first = study(reg)  # records the run
    with pytest.raises(sc.StudyRegistrationError, match="CALIBRATED"):
        sc.start_study_run(reg[0], {k: v for k, v in first.items() if k != "run_started_at"})
    with pytest.raises(sc.StudyRegistrationError, match="once"):
        sc.bind_study(reg[0], "HYP-0004", SPEC)
    # A second "run" claiming another start time is not the recorded run.
    rerun = result(GOOD, REF, "a", {**first, "run_started_at": "2099-12-01T00:00:00+00:00"}, reg)
    out = verdict([rerun], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "one recorded run" in out["periods"][0]["reason"]
    assert verdict([result(GOOD, REF, "a", first, reg)], reg[0])["verdict"] == "PENDING SECOND PERIOD"


def test_new2b_a_hypothesis_without_a_recorded_run_has_no_registered_result(reg):
    unrun = {k: v for k, v in study(reg, "HYP-0005").items() if k != "run_started_at"}
    _register(reg, "HYP-0030", "FAM-REGIME-UNRUN", slot=12)
    record = fresh(reg).get("HYP-0030")
    never_started = {**unrun, "hypothesis_id": "HYP-0030", "preregistration_hash": record.preregistration_hash,
                     "run_started_at": record.state_chain[0].recorded_at}
    assert verdict([result(GOOD, REF, "a", never_started, reg)], reg[0])["verdict"] == "NOT PROVEN"


# -- NF-4 / NEW-3: a study block cannot be copied, relabelled, nor its numbers edited --


def test_nf4_a_copied_study_block_or_edited_numbers_are_refused(reg):
    sealed = period(reg, "HYP-0004", REF, REF, "a")  # the real run: the filter did not win
    copied = result(GOOD, REF, "a", None, reg)
    copied["dataset"], copied["study"] = sealed["dataset"], sealed["study"]
    edited = period(reg, "HYP-0004", REF, REF, "a")
    edited["table"][FILTER][0]["net_pnl"] = 999
    for forged in (copied, edited):
        out = verdict([forged], reg[0])
        assert out["verdict"] == "NOT PROVEN" and "altered or relabelled" in out["periods"][0]["reason"]


def test_new3_relabelling_a_run_to_a_sibling_hypothesis_is_refused(reg):
    _register(reg, "HYP-0050", "FAM-REGIME-TWINS", slot=13)
    _register(reg, "HYP-0051", "FAM-REGIME-TWINS", slot=13)  # same window: only the label differs
    a, b = study(reg, "HYP-0050"), study(reg, "HYP-0051")
    run = result(REF, REF, "a", a, reg)  # HYP-0050's real (losing) run
    relabelled = {**run, "study": {**run["study"], "hypothesis_id": "HYP-0051",
                                   "preregistration_hash": b["preregistration_hash"],
                                   "run_started_at": b["run_started_at"]}}
    out = verdict([relabelled], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "altered or relabelled" in out["periods"][0]["reason"]


def test_a_table_that_is_not_the_sealed_shape_is_refused(reg):
    out = verdict([period(reg, "HYP-0004", GOOD + [(20, 90, 12)], REF + [(10, 100, 20)], "a")], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "shape" in out["periods"][0]["reason"]


# -- R4-1: a result must claim exactly its sealed window, not a chosen slice of it --


@pytest.mark.parametrize("mangle", [
    lambda s: s.update(first_open=s["first_open"] + 86_400_000, rows=s["rows"] - 1440),  # a later slice
    lambda s: s.update(last_open=s["last_open"] - 86_400_000, rows=s["rows"] - 1440),    # an earlier slice
    lambda s: s.update(rows=s["rows"] - 300),                                             # candles deleted
])
def test_r4_1_a_slice_or_a_gappy_dataset_is_not_the_sealed_window(reg, mangle):
    run = period(reg, "HYP-0004", GOOD, REF, "a")
    mangle(run["dataset"]["symbols"]["BTCUSDT"])
    run["study"]["result_digest"] = sc.result_digest(run)  # even re-sealed consistently
    out = verdict([run], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "not exactly" in out["periods"][0]["reason"]


# -- R4-2: one canonical registry --


def test_r4_2_a_registry_outside_the_canonical_path_does_not_verify(reg, tmp_path):
    good = [period(reg, "HYP-0001", GOOD, REF, "a"), period(reg, "HYP-0002", GOOD, REF, "b")]
    copy = tmp_path / "elsewhere.json"
    copy.write_bytes(reg[0].read_bytes())
    out = verdict(good, copy)
    assert out["verdict"] == "NOT PROVEN" and "canonical" in out["periods"][0]["reason"]


# -- NF-6: a terminal hypothesis's results are not evidence --


def test_nf6_results_of_a_terminal_hypothesis_do_not_count(reg):
    run = period(reg, "HYP-0004", GOOD, REF, "a")
    fresh(reg).advance("HYP-0004", HypothesisState.REJECTED)
    out = verdict([run], reg[0])
    assert out["verdict"] == "NOT PROVEN" and "REJECTED" in out["periods"][0]["reason"]


# -- NF-7: malformed input is refused, never raised --


@pytest.mark.parametrize("mangle", [
    lambda r: r.update(dataset=["not", "a", "dict"]),
    lambda r: r["dataset"]["symbols"]["BTCUSDT"].update(first_open="2099"),
    lambda r: r.update(study={**r["study"], "parameters": None}),
])
def test_nf7_malformed_results_are_refused_not_raised(reg, mangle):
    run = period(reg, "HYP-0004", GOOD, REF, "a")
    mangle(run)
    assert verdict([run], reg[0])["verdict"] == "NOT PROVEN"
