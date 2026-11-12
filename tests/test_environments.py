"""Environment boundaries (task 17): config matches the code; nothing but PRODUCTION may touch real money, and it is denied."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = json.loads((ROOT / "config" / "environments.json").read_text(encoding="utf-8"))


def test_only_production_has_real_money_and_it_is_denied():
    real = [k for k, v in ENV["environments"].items() if v["real_money"] or v["may_submit_orders"]]
    assert real == ["PRODUCTION"]
    assert "DENIED" in ENV["environments"]["PRODUCTION"]["entry"]


def test_current_environment_matches_main_py():
    main = (ROOT / "main.py").read_text(encoding="utf-8-sig")
    assert re.search(r'^EXECUTION_MODE = "PAPER"$', main, re.M)
    assert ENV["current"] == "PAPER"


def test_release_gate_has_shadow_before_release_and_owner_last():
    gate = ENV["release_gate"]
    assert gate.index("PAPER") < gate.index("SHADOW") < gate.index("RELEASE")
    assert gate[-2:] == ["OWNER_APPROVAL", "RELEASE"]
