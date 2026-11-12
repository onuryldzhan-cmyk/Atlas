"""EXP-002 (owner choice 2026-10-01): MEDIUM only, floor 0.62, 30 admissions, two weeks, PAPER only, OFF in main.py."""

import ast
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

from core.risk_engine import EXP002_PAPER_CONFIDENCE_EXPERIMENT as EXP, PAPER_CONFIDENCE_EXPERIMENTS, RiskBucket
from tests.test_exp001_paper_confidence_experiment import buy, engine, state

INSIDE = EXP.starts_at + timedelta(days=1)


def test_constants_are_pinned_and_stricter_than_exp001():
    assert EXP.experiment_id == "EXP-002" and EXP.minimum_confidence == D("0.62")
    assert EXP.buckets == frozenset({RiskBucket.MEDIUM}) and EXP.max_admissions == 30
    assert (EXP.ends_at - EXP.starts_at) == timedelta(days=14)
    assert EXP.minimum_confidence > PAPER_CONFIDENCE_EXPERIMENTS["EXP-001"].minimum_confidence


def test_medium_at_063_is_admitted_and_tagged_inside_the_window():
    d = engine(now=INSIDE, experiment=EXP).evaluate(buy(bucket="MEDIUM", confidence="0.63"), state())
    assert d.reason_code == "RISK_APPROVED" and d.experiment_id == "EXP-002"


def test_below_floor_high_bucket_and_outside_window_keep_default_floors():
    assert engine(now=INSIDE, experiment=EXP).evaluate(buy(bucket="MEDIUM", confidence="0.61"), state()).reason_code == "CONFIDENCE_BELOW_POLICY"
    assert engine(now=INSIDE, experiment=EXP).evaluate(buy(bucket="HIGH", confidence="0.70"), state()).reason_code == "CONFIDENCE_BELOW_POLICY"
    assert engine(now=EXP.ends_at, experiment=EXP).evaluate(buy(bucket="MEDIUM", confidence="0.63"), state()).reason_code == "CONFIDENCE_BELOW_POLICY"


def test_cap_reverts_to_default():
    assert engine(now=INSIDE, experiment=EXP, prior=30).evaluate(buy(bucket="MEDIUM", confidence="0.63"), state()).reason_code == "CONFIDENCE_BELOW_POLICY"


# Test policy change 2026-10-01: was "main keeps experiments off"; the owner switched on EXP-002
# after the independent audit (funding sentiment stays OFF, audit condition).
def test_main_runs_exp002_only_with_funding_off_and_constants_match_the_call_site():
    import main
    tree = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8"))
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "AtlasApplication")
    kw = {k.arg: k.value for k in call.keywords}
    assert ast.literal_eval(kw["paper_confidence_experiment"]) is True
    assert ast.literal_eval(kw["paper_confidence_experiment_id"]) == "EXP-002"
    assert "funding_sentiment" not in kw
    assert main.PAPER_CONFIDENCE_EXPERIMENT is True and main.PAPER_CONFIDENCE_EXPERIMENT_ID == "EXP-002"


def test_unknown_experiment_id_attaches_nothing(tmp_path):
    from core.application import AtlasApplication
    from tests.test_block5e_fee_settlement_accounting import seed_state

    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"), paper_confidence_experiment=True,
                           paper_confidence_experiment_id="EXP-999")
    assert app.risk_engine.experiment is None
