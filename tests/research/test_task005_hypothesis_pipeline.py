"""Task 005: hypothesis generation and screening pipeline (registry v5.88 grant, research only).

Covers generation, deduplication ("zaten hafizada"), fast-fail screening on
historical data, registration of one sealed family in the canonical registry,
the multiple-testing hooks, crash/failure recovery, and the end-to-end cycle
generation -> registration -> screening -> one registered run of exactly the
sealed arguments -> verification. Phase 4 rules are re-checked, not assumed.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pytest

from research import hypothesis_generation as hg
from research import screening as scr
from research.hypothesis_registry import HypothesisRegistry
from research.lifecycle import HypothesisState
from research.multiple_testing import benjamini_hochberg
from tools import hypothesis_pipeline as hp
from tools import strategy_compare as sc

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)
HISTORY_START = NOW_MS - 1440 * 60_000  # one day of history ending at the registration
PERIOD_1 = datetime(2100, 1, 1, tzinfo=timezone.utc)
PERIOD_2 = datetime(2100, 2, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(tmp_path))
    (tmp_path / "research").mkdir()


def candles(start_ms, count, volume="10"):
    rows, price = [], Decimal("100")
    for i in range(count):
        opened = start_ms + i * 60_000
        rows.append([opened, str(price), str(price * Decimal("1.001")), str(price * Decimal("0.999")), str(price),
                     volume, opened + 59_999, "0", 3, "4", "400", "0"])
        price *= Decimal("1.0001")
    return rows


def history(universe=("BTCUSDT",)):
    return {s: candles(HISTORY_START, 1440) for s in universe}


def template(**overrides):
    params = dict(name="regime-atr", family_id="FAM-GEN-REGIME-ATR", author="research",
                  universe=("BTCUSDT",), reference=sc.REFERENCE, reference_args=dict(sc.REALISTIC),
                  base_args=dict(sc.REALISTIC), grid={"regime_filter": [True], "atr_stop": ["1.5", 2]},
                  periods=(PERIOD_1.isoformat(),), economic_rationale="Trend regimes with volatility-scaled stops "
                  "cut losses in chop; tested out of sample on sealed future windows.", days=1, windows=3,
                  embargo=0, step=15, exp001=True)
    params.update(overrides)
    return hg.Template(**params)


SPEC = scr.ScreeningSpec(start_ms=HISTORY_START, end_ms=NOW_MS, cutoff_ms=NOW_MS, minimum_trades=5)


def registry():
    return HypothesisRegistry(registry_path=sc.canonical_registry())


def run(tmpl=None, *, trades=lambda c, d: 10, data=None, dry_run=False, clock=None):
    return hg.run_pipeline(tmpl or template(), sc.canonical_registry(), historical=history() if data is None else data,
                           screening=SPEC, quick_trades=trades, now=NOW, dry_run=dry_run, clock=clock)


def statuses(report):
    return [c["status"] for c in report["candidates"]]


# -- generation ----------------------------------------------------------------


def test_the_grid_becomes_deterministic_candidates_with_sealed_arguments():
    cands = hg.generate(template(grid={"regime_filter": [True, False], "atr_stop": ["1.5", 2, "2.0"]}))
    assert len(cands) == 6 and len({c.name for c in cands}) == 4  # "2" and "2.0" are one grid point
    first = cands[0]
    assert first.name == "gen:regime-atr:atr_stop=1.5,regime_filter=true"
    assert first.args == {"atr_stop": "1.5", "next_open_fill": True, "regime_filter": True, "slippage_bps": 5}
    spec = first.spec
    assert spec["variant_args"][first.name] == first.args and spec["variant_args"][sc.REFERENCE] == hg.normalize_args(sc.REALISTIC)
    assert spec == sc.study_parameters({}, days=1, windows=3, embargo=0, step=15, exp001=True,
                                       variant_args={sc.REFERENCE: sc.REALISTIC, first.name: first.args})
    assert [c.name for c in hg.generate(template())] == [c.name for c in hg.generate(template())]


@pytest.mark.parametrize("args", [
    {"no_such_knob": 1}, {"regime_filter": 1}, {"atr_stop": True}, {"atr_stop": "-1"}, {"atr_stop": "nan"},
    {"sell_confirm": 0}, {"min_hold_min": 1.5}, {"risk_per_trade": "0.01"},  # risk needs an ATR stop
    {"atr_stop": 2, "risk_per_trade": "0.2"}, {"atr_stop": "abc"},
])
def test_only_valid_replay_arguments_can_be_sealed(args):
    with pytest.raises(hg.GenerationError):
        hg.normalize_args(args)


@pytest.mark.parametrize("change", [
    {"name": "Not A Slug"}, {"grid": {}}, {"grid": {"atr_stop": []}}, {"grid": {"atr_stop": "2"}},
    {"grid": {"slippage_bps": [1]}},  # a knob that is also a base argument
    {"correction": "HOLM"}, {"periods": ()}, {"days": 0}, {"base_args": {"bogus": 1}},
])
def test_malformed_templates_are_refused(change):
    with pytest.raises(hg.GenerationError):
        template(**change)


@pytest.mark.parametrize("periods", [
    (NOW.isoformat(),),                                      # not after the registration
    ((NOW - timedelta(days=30)).isoformat(),),               # in the past
    ("2100-01-01T00:00:00",),                                 # naive
    ("2100-01-01T00:00:30+00:00",),                           # not a whole minute
    (PERIOD_1.isoformat(), (PERIOD_1 + timedelta(hours=12)).isoformat()),  # overlapping periods
    ("tomorrow",),
])
def test_sealed_windows_must_lie_wholly_after_the_registration(periods):
    with pytest.raises(hg.GenerationError):
        run(template(periods=periods))
    assert not sc.canonical_registry().exists()  # refused before any write


def test_tampered_sealed_arguments_are_refused():
    spec = dict(hg.generate(template())[0].spec)
    spec["variant_args"] = {**spec["variant_args"]}
    name = [n for n in spec["variant_args"] if n != sc.REFERENCE][0]
    spec["variant_args"][name] = {**spec["variant_args"][name], "atr_stop": "9"}
    with pytest.raises(hg.GenerationError, match="digest"):
        hg.sealed_variant_args(spec)
    assert hg.sealed_variant_args({"variants": ["a"]}) is None  # a names-only study


# -- screening -----------------------------------------------------------------


def test_screening_never_reads_data_after_the_registration():
    with pytest.raises(scr.ScreeningError, match="before the registration"):
        scr.ScreeningSpec(start_ms=HISTORY_START, end_ms=NOW_MS + 60_000, cutoff_ms=NOW_MS)
    for bad in ({"start_ms": HISTORY_START + 1}, {"max_zero_volume_fraction": "2"}, {"minimum_trades": -1},
                {"end_ms": HISTORY_START}, {"start_ms": 1.0}):
        with pytest.raises(scr.ScreeningError):
            scr.ScreeningSpec(**{"start_ms": HISTORY_START, "end_ms": NOW_MS, "cutoff_ms": NOW_MS, **bad})
    with pytest.raises(hg.GenerationError, match="cutoff"):
        hg.run_pipeline(template(), sc.canonical_registry(), historical=history(), now=NOW, quick_trades=None,
                        screening=scr.ScreeningSpec(start_ms=HISTORY_START, end_ms=NOW_MS, cutoff_ms=NOW_MS + 60_000))


def _row(i=0):
    return candles(HISTORY_START, 1)[0]


@pytest.mark.parametrize("mangle", [
    lambda r: r[:11], lambda r: [float(r[0]), *r[1:]], lambda r: [*r[:6], r[6] + 1, *r[7:]],
    lambda r: [r[0], "0", *r[2:]], lambda r: [r[0], r[1], r[3], r[2], *r[4:]], lambda r: [*r[:5], "-1", *r[6:]],
    lambda r: [*r[:8], -1, *r[9:]], lambda r: [*r[:9], "NaN", *r[10:]], lambda r: "not a row",
])
def test_candle_integrity_is_checked_in_full(mangle):
    assert scr.validate_candle(_row()) == HISTORY_START
    with pytest.raises(ValueError):
        scr.validate_candle(mangle(_row()))


def test_the_data_stages_fail_fast_in_order():
    good = scr.screen_data(history(), ["BTCUSDT"], SPEC)
    assert [(r.stage, r.verdict.value) for r in good] == [("integrity", "PASS"), ("completeness", "PASS"),
                                                          ("zero_volume", "PASS")]
    broken = history()
    broken["BTCUSDT"][7] = broken["BTCUSDT"][7][:11]
    assert [r.verdict.value for r in scr.screen_data(broken, ["BTCUSDT"], SPEC)] == ["FAIL"]
    gappy = history()
    del gappy["BTCUSDT"][700]
    assert [(r.stage, r.verdict.value) for r in scr.screen_data(gappy, ["BTCUSDT"], SPEC)][-1] == ("completeness", "FAIL")
    idle = {"BTCUSDT": candles(HISTORY_START, 1440, volume="0")}
    assert scr.screen_data(idle, ["BTCUSDT"], SPEC)[-1].stage == "zero_volume"
    assert scr.screen_data(history(("ETHUSDT",)), ["BTCUSDT"], SPEC)[0].verdict is scr.StageVerdict.FAIL


def test_the_trade_count_stage_does_not_pass_without_a_count():
    assert scr.screen_trades(None, SPEC).verdict is scr.StageVerdict.NOT_RUN
    assert scr.screen_trades(4, SPEC).verdict is scr.StageVerdict.FAIL
    assert scr.screen_trades(True, SPEC).verdict is scr.StageVerdict.FAIL
    assert scr.screen_trades(5, SPEC).passed
    data = scr.screen_data(history(), ["BTCUSDT"], SPEC)
    assert scr.passed(data + [scr.screen_trades(5, SPEC)])
    assert not scr.passed(data + [scr.screen_trades(None, SPEC)]) and not scr.passed(data)


# -- the pipeline: registration into the canonical registry ---------------------


def test_survivors_are_registered_as_one_sealed_family_in_the_canonical_registry():
    tmpl = template(periods=(PERIOD_1.isoformat(), PERIOD_2.isoformat()))
    report = run(tmpl)
    assert statuses(report) == ["REGISTERED", "REGISTERED"] and report["evidence_eligible"] is False
    family = registry().family(tmpl.family_id)
    assert len(family) == 4 == report["family_size"]  # 2 survivors x 2 sealed periods
    for record in family:
        pre = record.preregistration
        assert record.state is HypothesisState.REGISTERED
        assert datetime.fromisoformat(pre.data_start) in (PERIOD_1, PERIOD_2)
        assert datetime.fromisoformat(pre.data_end) - datetime.fromisoformat(pre.data_start) == timedelta(days=1)
        gen = pre.feature_spec["generation"]
        assert gen["candidates_generated"] == 2 and gen["multiple_testing"]["family_size"] == 4
        assert gen["idea_fingerprint"] == hg.record_fingerprint(record)
        assert sc.sealed_variants(sc.canonical_registry(), record.hypothesis_id) is not None
    assert [r.hypothesis_id for r in family] == ["HYP-0001", "HYP-0002", "HYP-0003", "HYP-0004"]


def test_an_existing_idea_is_tagged_zaten_hafizada_and_not_registered_again():
    run()
    again = run(template(family_id="FAM-GEN-AGAIN"))
    assert statuses(again) == ["EXISTING", "EXISTING"] and again["family_size"] == 0
    assert "zaten hafizada" in again["candidates"][0]["reason"] and again["candidates"][0]["hypothesis_ids"]
    assert registry().family("FAM-GEN-AGAIN") == () and len(registry().all_records()) == 2


def test_a_duplicate_grid_point_is_registered_once():
    report = run(template(grid={"atr_stop": [2, "2.0"]}))
    assert statuses(report) == ["REGISTERED", "DUPLICATE"] and len(registry().all_records()) == 1


def test_screened_out_candidates_are_not_registered():
    gappy = history()
    del gappy["BTCUSDT"][100]
    report = run(data=gappy)
    assert statuses(report) == ["SCREENED_OUT", "SCREENED_OUT"] and "contiguous" in report["candidates"][0]["reason"]
    assert not sc.canonical_registry().exists()
    few = run(trades=lambda c, d: 1 if "1.5" in c.name else 50)
    assert statuses(few) == ["SCREENED_OUT", "REGISTERED"]
    assert registry().family("FAM-GEN-REGIME-ATR")[0].preregistration.feature_spec["generation"][
        "candidates_screened_out"] == 1


def test_without_a_quick_replay_nothing_passes_screening():
    assert statuses(run(trades=None)) == ["SCREENED_OUT", "SCREENED_OUT"]


# -- failure and crash recovery -------------------------------------------------


def test_a_crashing_candidate_is_failed_and_never_blocks_the_others_or_a_later_run():
    def trades(candidate, data):
        if "1.5" in candidate.name:
            raise RuntimeError("replay blew up")
        return 50

    report = run(trades=trades)
    assert statuses(report) == ["FAILED", "REGISTERED"] and "replay blew up" in report["candidates"][0]["reason"]
    later = run(template(family_id="FAM-GEN-RETRY"))  # the failed idea is not marked: it can be generated again
    assert statuses(later) == ["REGISTERED", "EXISTING"]


class _Calls(list):
    restore = None


def _flaky_register(monkeypatch, fail_on):
    real, calls = HypothesisRegistry.register, _Calls()

    def flaky(self, prereg):
        calls.append(prereg.hypothesis_id)
        if len(calls) == fail_on:
            raise OSError("disk full")
        return real(self, prereg)

    monkeypatch.setattr(HypothesisRegistry, "register", flaky)
    calls.restore = lambda: monkeypatch.setattr(HypothesisRegistry, "register", real)
    return calls


def test_a_registry_write_failure_stops_cleanly_and_reports_what_was_registered(monkeypatch):
    _flaky_register(monkeypatch, fail_on=2)
    report = run()
    assert statuses(report) == ["REGISTERED", "REGISTRATION_FAILED"]
    assert "disk full" in report["registration_failure"] and report["family_size"] == 1
    assert [r.hypothesis_id for r in registry().all_records()] == ["HYP-0001"]
    assert not sc.canonical_registry().with_name("hypotheses.json.lock").exists()  # the lock is released


def test_an_invalid_pre_registration_writes_nothing():
    with pytest.raises(hg.GenerationError, match="invalid pre-registration"):
        run(template(economic_rationale="   "))
    assert not sc.canonical_registry().exists()


def test_an_existing_family_is_never_extended():
    run(template(grid={"atr_stop": [2]}))
    with pytest.raises(hg.GenerationError, match="already exists"):
        run(template(grid={"atr_stop": [3]}))
    assert len(registry().family("FAM-GEN-REGIME-ATR")) == 1


def test_a_dry_run_registers_nothing():
    report = run(dry_run=True)
    assert statuses(report) == ["NOT_REGISTERED", "NOT_REGISTERED"] and report["family_size"] == 2
    assert not sc.canonical_registry().exists()


# -- multiple testing -----------------------------------------------------------


def test_bonferroni_seals_alpha_over_the_whole_family():
    tmpl = template(correction="BONFERRONI", alpha=0.05, periods=(PERIOD_1.isoformat(), PERIOD_2.isoformat()))
    run(tmpl)
    family = registry().family(tmpl.family_id)
    assert {r.preregistration.alpha for r in family} == {0.05 / 4}
    assert {r.preregistration.feature_spec["generation"]["multiple_testing"]["method"] for r in family} == {"BONFERRONI"}


def test_bh_keeps_the_family_alpha_and_records_the_family_size():
    run()
    family = registry().family("FAM-GEN-REGIME-ATR")
    assert {r.preregistration.alpha for r in family} == {0.05}
    assert all(r.preregistration.feature_spec["generation"]["multiple_testing"] ==
               {"method": "BH", "family_size": 2, "q": 0.05, "alpha_per_hypothesis": 0.05} for r in family)


def test_the_correction_hooks_control_error_rates_under_the_null():
    """Monte Carlo under the global null: Bonferroni at alpha/m keeps FWER <= alpha; BH keeps FDR <= q."""
    rng, m, trials, alpha = np.random.default_rng(5), 20, 4000, 0.05
    fwer_bonf = fwer_bh = 0
    for _ in range(trials):
        p = rng.uniform(size=m)
        fwer_bonf += bool((p <= alpha / m).any())
        fwer_bh += benjamini_hochberg(p, q=alpha).n_rejected > 0  # under the global null FDR = FWER
    assert fwer_bonf / trials <= alpha + 0.01 and fwer_bh / trials <= alpha + 0.01
    naive = sum(bool((rng.uniform(size=m) <= alpha).any()) for _ in range(trials)) / trials
    assert naive > 0.5  # without a correction a family of 20 "finds" something most of the time


# -- end to end: generation -> registration -> screening -> one sealed run -> verification --


def test_a_generated_hypothesis_runs_exactly_its_sealed_arguments_once(monkeypatch, tmp_path):
    run(template(grid={"atr_stop": ["1.5"], "regime_filter": [True]}))
    [record] = registry().family("FAM-GEN-REGIME-ATR")
    hid, start = record.hypothesis_id, int(PERIOD_1.timestamp() * 1000)
    seen = []

    def fake_compare(data, windows, step, exp001, variants, **kw):
        seen.append(variants)
        return {"table": {name: [{"net_pnl": "1", "max_drawdown": "1", "closed_trades": 1}] * windows for name in variants},
                "verdicts": {name: "-" for name in variants}}

    monkeypatch.setattr(sc, "compare", fake_compare)
    dataset = tmp_path / "ds.json"
    data = {"BTCUSDT": candles(start, 1440)}
    dataset.write_text(json.dumps({"manifest": sc.dataset_manifest(data), "data": data}), encoding="utf-8")
    out = tmp_path / "out.json"
    argv = ["--dataset", str(dataset), "--symbols", "BTCUSDT", "--json", "--days", "1", "--windows", "3",
            "--embargo", "0", "--step", "15", "--output", str(out),
            "--registry", str(sc.canonical_registry()), "--hypothesis", hid]
    only = argv[:-4] + ["--only", "atr", "--registry", str(sc.canonical_registry()), "--hypothesis", hid]
    assert sc.main(only) == 2 and seen == []  # refused on a fresh hypothesis, which stays unspent
    assert registry().get(hid).state is HypothesisState.REGISTERED
    assert sc.main(argv) == 0
    [variants] = seen
    sealed = sc.sealed_variants(sc.canonical_registry(), hid)
    assert variants == {name: hg.replay_kwargs(args) for name, args in sealed.items()}
    assert variants[[n for n in variants if n != sc.REFERENCE][0]]["atr_stop"] == Decimal("1.5")
    result = json.loads(out.read_text(encoding="utf-8"))
    assert sc.verify_registered_result(result, sc.canonical_registry())["hypothesis_id"] == hid
    assert registry().get(hid).state is HypothesisState.CALIBRATED
    assert sc.main(argv) == 2 and len(seen) == 1  # one run per hypothesis


def test_a_generated_study_cannot_be_run_with_other_arguments(monkeypatch, tmp_path):
    run(template(grid={"atr_stop": ["1.5"]}))
    hid = registry().family("FAM-GEN-REGIME-ATR")[0].hypothesis_id
    raw = json.loads(sc.canonical_registry().read_text(encoding="utf-8"))
    rec = raw["records"][0]["preregistration"]["feature_spec"]["strategy_compare"]
    name = [n for n in rec["variant_args"] if n != sc.REFERENCE][0]
    rec["variant_args"][name]["atr_stop"] = "3"  # a hindsight edit of the sealed arguments
    sc.canonical_registry().write_text(json.dumps(raw), encoding="utf-8")
    replayed = []
    monkeypatch.setattr(sc, "compare", lambda *a, **k: replayed.append(1))
    rc = sc.main(["--symbols", "BTCUSDT", "--json", "--days", "1", "--windows", "3", "--embargo", "0",
                  "--registry", str(sc.canonical_registry()), "--hypothesis", hid])
    assert rc == 2 and replayed == []


# -- the tools entry point --------------------------------------------------------


def _template_file(tmp_path, **overrides):
    raw = dict(name="regime-atr", family_id="FAM-GEN-CLI", author="research", universe=["BTCUSDT"],
               base_args={}, grid={"atr_stop": ["2"]}, periods=[PERIOD_1.isoformat()],
               economic_rationale="Volatility-scaled stops in trend regimes.", days=1, windows=3, embargo=0, step=15)
    raw.update(overrides)
    path = tmp_path / "template.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def _fetch(symbol, start):
    return candles(start, 1000)


def test_the_cli_registers_into_the_canonical_registry_only(tmp_path):
    out = tmp_path / "report.json"
    rc = hp.main(["--template", str(_template_file(tmp_path)), "--history-days", "1", "--minimum-trades", "0",
                  "--output", str(out)], fetch=_fetch, now=NOW)
    report = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 0 and statuses(report) == ["REGISTERED"] and report["registry"] == str(sc.canonical_registry())
    [record] = registry().family("FAM-GEN-CLI")
    args = list(record.preregistration.feature_spec["strategy_compare"]["variant_args"].values())
    assert all(a["slippage_bps"] == 5 and a["next_open_fill"] is True for a in args)  # realistic fills sealed


@pytest.mark.parametrize("overrides", [{"base_args": {"slippage_bps": 0}}, {"reference": "x"},
                                       {"base_args": {"next_open_fill": False}}, {"universe": []}])
def test_the_cli_refuses_templates_without_realistic_fills_or_with_unknown_fields(tmp_path, overrides):
    rc = hp.main(["--template", str(_template_file(tmp_path, **overrides)), "--history-days", "1"],
                 fetch=_fetch, now=NOW)
    assert rc == 2 and not sc.canonical_registry().exists()


def test_the_cli_reports_a_failed_download_and_registers_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    def down(symbol, start):
        raise OSError("network down")

    assert hp.main(["--template", str(_template_file(tmp_path)), "--history-days", "1"], fetch=down, now=NOW) == 2
    assert not sc.canonical_registry().exists()


def test_the_cli_dry_run_registers_nothing(tmp_path):
    rc = hp.main(["--template", str(_template_file(tmp_path)), "--history-days", "1", "--minimum-trades", "0",
                  "--dry-run"], fetch=_fetch, now=NOW)
    assert rc == 0 and not sc.canonical_registry().exists()


# -- independent review of Task 005: F-1 .. F-6 ----------------------------------


def _seed_hypothesis(hid="HYP-0001", family="FAM-SEED"):
    from tests.test_research_hypothesis_registry import make_preregistration

    registry().register(make_preregistration(hypothesis_id=hid, family_id=family,
                                             feature_spec={"strategy_compare": {"variants": ["seed"]}}))


def test_f1_a_concurrent_run_record_is_not_lost_while_the_pipeline_screens():
    _seed_hypothesis()

    def trades(candidate, data):  # meanwhile the daily agent records HYP-0001's run
        registry().advance("HYP-0001", HypothesisState.CALIBRATED)
        return 50

    report = run(template(grid={"atr_stop": [2]}), trades=trades)
    assert statuses(report) == ["REGISTERED"]
    assert registry().get("HYP-0001").state is HypothesisState.CALIBRATED  # not rolled back
    assert [r.hypothesis_id for r in registry().all_records()] == ["HYP-0001", "HYP-0002"]


def test_f1_two_overlapping_pipeline_runs_keep_both_families():
    inner = []

    def trades(candidate, data):  # a second generation run registers while the first one screens
        if not inner:
            inner.append(run(template(grid={"atr_stop": [3]}, family_id="FAM-GEN-OTHER", name="other")))
        return 50

    outer = run(template(grid={"atr_stop": [2]}), trades=trades)
    assert statuses(inner[0]) == ["REGISTERED"] and statuses(outer) == ["REGISTERED"]
    assert len(registry().family("FAM-GEN-OTHER")) == 1 and len(registry().family("FAM-GEN-REGIME-ATR")) == 1
    assert len({r.hypothesis_id for r in registry().all_records()}) == 2  # no id collision


def test_f1_the_same_idea_registered_meanwhile_is_existing_not_duplicated():
    def trades(candidate, data):
        run(template(grid={"atr_stop": [2]}, family_id="FAM-GEN-FIRST"))
        return 50

    report = run(template(grid={"atr_stop": [2]}), trades=trades)
    assert statuses(report) == ["EXISTING"] and len(registry().all_records()) == 1


def test_f1_the_write_lock_is_exclusive_and_fails_closed(monkeypatch):
    import os
    from research import registry_lock as rl

    path = sc.canonical_registry()
    with rl.registry_write_lock(path):
        with pytest.raises(rl.RegistryLockError, match="held by another writer"):
            with rl.registry_write_lock(path, timeout_s=0.1):
                pass
    assert not rl.lock_path(path).exists()
    rl.lock_path(path).write_text("123", encoding="utf-8")
    os.utime(rl.lock_path(path), (0, 0))  # a writer died holding it long ago
    with pytest.raises(rl.RegistryLockError, match="remove it only after checking"):
        with rl.registry_write_lock(path, timeout_s=0.1):
            pass
    assert rl.lock_path(path).exists()  # never broken automatically


def test_f1_a_held_lock_makes_registration_and_a_registered_run_fail_without_writing(monkeypatch, tmp_path):
    from functools import partial
    from research import registry_lock as rl

    run(template(grid={"atr_stop": ["1.5"]}))
    hid = registry().family("FAM-GEN-REGIME-ATR")[0].hypothesis_id
    monkeypatch.setattr(rl, "registry_write_lock", partial(rl.registry_write_lock, timeout_s=0.1))
    rl.lock_path(sc.canonical_registry()).write_text("other writer", encoding="utf-8")
    with pytest.raises(rl.RegistryLockError):
        run(template(grid={"atr_stop": [4]}, family_id="FAM-GEN-LOCKED"))
    assert registry().family("FAM-GEN-LOCKED") == ()
    data = {"BTCUSDT": candles(int(PERIOD_1.timestamp() * 1000), 1440)}
    dataset = tmp_path / "ds.json"
    dataset.write_text(json.dumps({"manifest": sc.dataset_manifest(data), "data": data}), encoding="utf-8")
    out = tmp_path / "out.json"
    rc = sc.main(["--dataset", str(dataset), "--symbols", "BTCUSDT", "--json", "--days", "1", "--windows", "3",
                  "--embargo", "0", "--output", str(out), "--registry", str(sc.canonical_registry()), "--hypothesis", hid])
    assert rc == 2 and json.loads(out.read_text(encoding="utf-8"))["study"]["status"] == "FAILED"  # transient
    assert registry().get(hid).state is HypothesisState.REGISTERED  # unspent: it can run once the lock is gone


@pytest.mark.parametrize("variation", [
    {"name": "renamed"},                                                             # another template name
    {"grid": {"regime_filter": [True]}, "base_args": {**sc.REALISTIC, "atr_stop": 2}},  # knob moved to base_args
    {"step": 16}, {"windows": 2}, {"embargo": 60},                                   # other evaluation settings
])
def test_f2_the_same_idea_under_another_name_or_evaluation_is_existing(variation):
    run(template(grid={"atr_stop": [2], "regime_filter": [True]}))
    again = run(template(family_id="FAM-GEN-AGAIN", **{"grid": {"atr_stop": [2], "regime_filter": [True]}, **variation}))
    assert statuses(again) == ["EXISTING"] and len(registry().all_records()) == 1


def test_f2_a_different_idea_is_not_existing():
    run(template(grid={"atr_stop": [2]}))
    for variation in ({"universe": ("ETHUSDT",)}, {"exp001": False}, {"grid": {"atr_stop": [3]}}):
        tmpl = template(family_id="FAM-GEN-" + str(len(registry().all_records())), **variation)
        data = history(tmpl.universe)
        assert "EXISTING" not in statuses(run(tmpl, data=data))


def test_f3_a_sealed_weaker_reference_is_refused_at_run_and_at_verification(tmp_path, monkeypatch):
    weak = {**sc.REALISTIC, "slippage_bps": 50}
    run(template(grid={"atr_stop": ["1.5"]}, reference_args=weak, base_args=weak))  # fills match: research accepts
    hid = registry().family("FAM-GEN-REGIME-ATR")[0].hypothesis_id
    replayed = []
    monkeypatch.setattr(sc, "compare", lambda *a, **k: replayed.append(1))
    rc = sc.main(["--symbols", "BTCUSDT", "--json", "--days", "1", "--windows", "3", "--embargo", "0",
                  "--registry", str(sc.canonical_registry()), "--hypothesis", hid])
    assert rc == 2 and replayed == [] and registry().get(hid).state is HypothesisState.REGISTERED
    forged = {"study": {"status": "REGISTERED", "hypothesis_id": hid}}
    with pytest.raises(sc.StudyRegistrationError):
        sc.verify_registered_result(forged, sc.canonical_registry())


def test_f4_windows_are_rechecked_against_the_real_clock_before_any_write():
    late = PERIOD_1 + timedelta(minutes=1)  # the real clock has passed the first period's start
    with pytest.raises(hg.GenerationError, match="not after the registration"):
        run(template(grid={"atr_stop": [2]}), clock=lambda: late)
    assert registry().all_records() == ()


def test_f5_re_running_the_same_plan_resumes_a_partly_registered_family(monkeypatch):
    tmpl = template(periods=(PERIOD_1.isoformat(), PERIOD_2.isoformat()))
    calls = _flaky_register(monkeypatch, fail_on=3)
    first = run(tmpl)
    assert "disk full" in first["registration_failure"] and len(registry().family(tmpl.family_id)) == 2
    calls.restore()  # (monkeypatch.undo() would also undo the state-root fixture)
    second = run(tmpl)
    family = registry().family(tmpl.family_id)
    assert statuses(second) == ["REGISTERED", "REGISTERED"] and len(family) == 4 and second["family_size"] == 4
    assert {r.preregistration.feature_spec["generation"]["multiple_testing"]["family_size"] for r in family} == {4}
    assert len({r.preregistration.feature_spec["generation"]["lineage"] for r in family}) == 1
    assert "resumed" in second["candidates"][0]["reason"]
    third = run(tmpl)  # idempotent: nothing new
    assert len(registry().family(tmpl.family_id)) == 4 and statuses(third) == ["REGISTERED", "REGISTERED"]
    assert calls[:3] == ["HYP-0001", "HYP-0002", "HYP-0003"]


def test_f5_an_existing_family_with_another_plan_is_refused():
    run(template(grid={"atr_stop": [2]}))
    with pytest.raises(hg.GenerationError, match="another plan"):
        run(template(grid={"atr_stop": [2], "regime_filter": [True, False]}))


def test_f6_a_seal_valid_record_with_a_wrong_argument_digest_is_refused(monkeypatch):
    from tests.test_research_hypothesis_registry import make_preregistration

    spec = dict(hg.generate(template(grid={"atr_stop": ["1.5"]}))[0].spec)
    spec["variant_args_sha256"] = "0" * 64  # registered (and sealed) as is: the seal is valid, the digest is not
    registry().register(make_preregistration(hypothesis_id="HYP-0001", feature_spec={"strategy_compare": spec},
                                             universe=("BTCUSDT",), data_start=PERIOD_1.isoformat(),
                                             data_end=(PERIOD_1 + timedelta(days=1)).isoformat(),
                                             preregistered_at=NOW.isoformat()))
    with pytest.raises(sc.StudyRegistrationError, match="digest"):
        sc.sealed_variants(sc.canonical_registry(), "HYP-0001")
    replayed = []
    monkeypatch.setattr(sc, "compare", lambda *a, **k: replayed.append(1))
    assert sc.main(["--symbols", "BTCUSDT", "--json", "--days", "1", "--windows", "3", "--embargo", "0",
                    "--registry", str(sc.canonical_registry()), "--hypothesis", "HYP-0001"]) == 2 and replayed == []


# -- second independent review of Task 005: N-1, F-2/F-4/F-5 residuals, N-2 -----


def test_n1_a_template_cannot_give_variants_cheaper_fills_than_the_reference():
    with pytest.raises(hg.GenerationError, match="fill exactly like the reference"):
        template(grid={"slippage_bps": [1]}, base_args={"next_open_fill": True})
    with pytest.raises(hg.GenerationError, match="fill exactly like the reference"):
        template(base_args={**sc.REALISTIC, "slippage_bps": 1})


def test_n1_a_seal_valid_variant_with_cheaper_fills_is_refused_at_run_and_at_verification(monkeypatch):
    from tests.test_research_hypothesis_registry import make_preregistration

    cheap = {"slippage_bps": 1, "next_open_fill": True, "atr_stop": 2}
    spec = hg.study_spec({sc.REFERENCE: sc.REALISTIC, "cheap": cheap}, reference=sc.REFERENCE,
                         days=1, windows=3, embargo=0, step=15, exp001=True)
    registry().register(make_preregistration(hypothesis_id="HYP-0001", feature_spec={"strategy_compare": spec},
                                             universe=("BTCUSDT",), data_start=PERIOD_1.isoformat(),
                                             data_end=(PERIOD_1 + timedelta(days=1)).isoformat(),
                                             preregistered_at=NOW.isoformat()))
    replayed = []
    monkeypatch.setattr(sc, "compare", lambda *a, **k: replayed.append(1))
    assert sc.main(["--symbols", "BTCUSDT", "--json", "--days", "1", "--windows", "3", "--embargo", "0",
                    "--registry", str(sc.canonical_registry()), "--hypothesis", "HYP-0001"]) == 2 and replayed == []
    assert registry().get("HYP-0001").state is HypothesisState.REGISTERED
    with pytest.raises(sc.StudyRegistrationError):
        sc.verify_registered_result({"study": {"status": "REGISTERED", "hypothesis_id": "HYP-0001"}},
                                    sc.canonical_registry())


def test_f2_writing_a_replay_default_out_is_the_same_idea():
    run(template(grid={"atr_stop": [2]}))
    for i, extra in enumerate(({"regime_filter": False}, {"trend_ema_hours": 0}, {"risk_per_trade": "0"},
                               {"cost_gate": "0.0"}, {"cost_gate": "-0"})):
        again = run(template(family_id=f"FAM-GEN-DEFAULT-{i}", grid={"atr_stop": [2]},
                             base_args={**sc.REALISTIC, **extra}))
        assert statuses(again) == ["EXISTING"], extra
    assert len(registry().all_records()) == 1
    assert hg.normalize_args({"regime_filter": False, "atr_stop": "0", "trend_ema_hours": 0}) == {}


def test_f2_the_knob_defaults_are_the_replays_own_defaults():
    import inspect
    from tools import backtest_replay as bt

    signature = inspect.signature(bt.replay)
    for knob, default in hg.KNOB_DEFAULTS.items():
        assert str(signature.parameters[knob].default) == str(default), knob
    assert set(hg.KNOB_DEFAULTS) == set(hg.KNOBS)


def test_f2_a_grid_point_at_a_default_still_gets_a_readable_name():
    names = [c.name for c in hg.generate(template(grid={"regime_filter": [True, False]}))]
    assert names == ["gen:regime-atr:regime_filter=true", "gen:regime-atr:regime_filter=false"]


def test_f4_preregistered_at_is_the_real_registration_time():
    real = NOW + timedelta(minutes=5)
    run(template(grid={"atr_stop": [2]}), clock=lambda: real)
    assert registry().all_records()[0].preregistration.preregistered_at == real.isoformat()


def test_f5_a_resume_follows_the_sealed_plan_without_screening_again(monkeypatch):
    tmpl = template(periods=(PERIOD_1.isoformat(), PERIOD_2.isoformat()))
    calls = _flaky_register(monkeypatch, fail_on=3)
    run(tmpl)
    calls.restore()
    screened = []

    def changed_market(candidate, data):  # a later screening would now drop the second candidate
        screened.append(candidate.name)
        return 0

    report = run(tmpl, trades=changed_market, data={"BTCUSDT": []})  # even unusable data: nothing is re-screened
    family = registry().family(tmpl.family_id)
    assert screened == [] and statuses(report) == ["REGISTERED", "REGISTERED"] and len(family) == 4
    assert len({json.dumps(r.preregistration.feature_spec["generation"]["plan"]) for r in family}) == 1


def test_f5_family_completeness_tells_an_incomplete_generated_family(monkeypatch):
    calls = _flaky_register(monkeypatch, fail_on=2)
    run(template())
    assert hg.family_completeness(registry(), "FAM-GEN-REGIME-ATR") == (1, 2)  # adjudicating now would understate m
    calls.restore()
    run(template())  # resume
    assert hg.family_completeness(registry(), "FAM-GEN-REGIME-ATR") == (2, 2)
    _seed_hypothesis(hid="HYP-0099", family="FAM-MANUAL")
    assert hg.family_completeness(registry(), "FAM-MANUAL") == (1, None)  # not a generated family


def test_new1_spellings_of_a_default_or_of_true_are_not_a_new_idea():
    assert hg.normalize_args({"atr_stop": "-0", "cost_gate": "-0.0"}) == {}
    with pytest.raises(hg.GenerationError, match="exp001"):
        template(exp001=1)


def test_new4_only_the_owner_listed_knobs_can_be_swept():
    assert set(hg.KNOBS) == {"regime_filter", "atr_stop", "risk_per_trade", "trend_ema_hours", "cost_gate",
                             "slippage_bps", "next_open_fill"}
    for knob in ("min_hold_min", "sell_confirm", "staged", "sleeves"):
        with pytest.raises(hg.GenerationError, match="not a replay argument|unknown replay argument"):
            template(grid={knob: [1]})


def test_n2_a_dry_run_takes_no_lock(monkeypatch):
    from research import registry_lock as rl

    rl.lock_path(sc.canonical_registry()).write_text("another writer", encoding="utf-8")
    report = run(dry_run=True)
    assert statuses(report) == ["NOT_REGISTERED", "NOT_REGISTERED"]
