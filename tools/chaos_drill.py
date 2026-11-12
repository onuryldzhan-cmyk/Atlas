"""Failure drill: inject known faults into the real components in a sandbox and check Atlas catches them.

  python -m tools.chaos_drill
  python -m tools.chaos_drill --record     # also write the result to Atlas Memory (OPERATIONS)

Vision §61 / master command §36 ("recovery", "failure injection, sandbox
only"). Every scenario is an existing, reviewed test that builds the real
component in a temporary directory, injects the fault and asserts the
fail-closed or recovery behaviour - so the drill never touches the real
state, the network or live money. Grouped the way an operator thinks about
failures:

  DATA CORRUPTION   corrupt financial / risk / reservation state is refused, never repaired silently
  CRASH RECOVERY    a crash at each step of a PAPER execution (K0-K6) recovers exactly once
  DUPLICATES        a completed request replays as a duplicate after restart
  SUPERVISION       an abnormal exit is restarted, five fast crashes give up
  CONNECTIVITY      the market feed reconnects after a disconnect
  GOVERNANCE LOGS   a truncated or altered proposal log is refused

Exit 0 only if every scenario passes.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCENARIOS: dict[str, list[str]] = {
    "DATA CORRUPTION": [
        "tests/test_block2_risk_service_composition_wiring.py::test_corrupt_financial_state_denies_execution_startup",
        "tests/test_block2_risk_service_composition_wiring.py::test_corrupt_risk_accounting_state_denies_buy",
        "tests/test_block2_risk_service_composition_wiring.py::test_corrupt_reservation_state_denies_buy",
        "tests/test_block3_bootstrap_state_validation.py::test_all_three_corrupt_at_once_reports_invalid_existing_for_each_and_untouched",
        "tests/test_block2c_financial_state_bootstrap.py::test_bootstrap_does_not_replace_corrupt_existing_state",
    ],
    "CRASH RECOVERY": [
        "tests/test_execution_crash_recovery_f1_f6.py::test_k0_crash_before_prepare_leaves_no_journal_entry_and_startup_releases_the_orphan",
        "tests/test_execution_crash_recovery_f1_f6.py::test_k1_crash_after_prepare_recovers_as_a_clean_abort",
        "tests/test_execution_crash_recovery_f1_f6.py::test_k3_to_k5_recover_committed_from_applied_evidence_not_rederivation",
        "tests/test_execution_crash_recovery_f1_f6.py::test_k6_recovers_committed_with_the_genuine_recorded_result",
        "tests/test_execution_crash_recovery_f1_f6.py::test_k2_marker_with_no_sidecar_append_recovers_as_abort",
    ],
    "DUPLICATES": [
        "tests/test_block3_durable_execution_path_ownership.py::test_completed_request_is_still_a_duplicate_after_restart",
        "tests/test_execution_crash_recovery_f1_f6.py::test_k0_then_same_request_retry_executes_once_on_a_fresh_reservation",
    ],
    "SUPERVISION": [
        "tests/test_process_supervisor.py::test_an_abnormal_exit_is_restarted",
        "tests/test_process_supervisor.py::test_five_rapid_crashes_give_up_with_a_non_zero_exit",
        "tests/test_process_supervisor.py::test_a_clean_first_exit_is_never_restarted",
    ],
    "CONNECTIVITY": [
        "tests/test_market_feed_restart_lifecycle.py::test_owned_provider_can_restart_after_disconnect",
    ],
    "GOVERNANCE LOGS": [
        "tests/test_atlas_org_governance.py::test_cli_writes_chain_and_refuses_truncated_log",
        "tests/test_atlas_org_governance.py::test_readers_show_state_and_report_corruption_unavailable",
    ],
}


def run(scenarios: dict[str, list[str]] = SCENARIOS) -> dict:
    import pytest

    nodes = [n for group in scenarios.values() for n in group]
    with tempfile.TemporaryDirectory() as scratch:
        junit = Path(scratch) / "drill.xml"
        code = pytest.main(["-q", "-p", "no:cacheprovider", f"--junitxml={junit}", *nodes],
                           plugins=[])
        outcomes: dict[str, str] = {}
        if junit.exists():
            for case in ElementTree.parse(junit).iter("testcase"):
                classname, name = case.get("classname", ""), case.get("name", "")
                path = classname.replace(".", "/") + ".py"
                status = "FAIL" if case.find("failure") is not None or case.find("error") is not None else (
                    "SKIP" if case.find("skipped") is not None else "PASS")
                key = f"{path}::{name.split('[')[0]}"  # parametrized cases fold into their test
                if outcomes.get(key) != "FAIL":
                    outcomes[key] = "FAIL" if status == "FAIL" else outcomes.get(key, status)
    groups = {}
    for group, members in scenarios.items():
        groups[group] = {m.split("::")[-1]: outcomes.get(m, "NOT RUN") for m in members}
    all_pass = all(v == "PASS" for g in groups.values() for v in g.values())
    return {"all_pass": all_pass, "pytest_exit": int(code), "groups": groups}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", action="store_true", help="write the result to Atlas Memory (OPERATIONS, TEMPORARY)")
    args = parser.parse_args(argv)
    result = run()
    print("\nATLAS HATA TATBİKATI (sandbox, gerçek bileşenler, gerçek durum/para/ağ yok)")
    for group, cases in result["groups"].items():
        ok = sum(1 for v in cases.values() if v == "PASS")
        print(f"  {group:<16} {ok}/{len(cases)} yakalandı")
        for name, status in cases.items():
            if status != "PASS":
                print(f"      {status}: {name}")
    print("SONUÇ:", "TÜM HATALAR YAKALANDI" if result["all_pass"] else "EKSİK VAR - yukarıdaki satırlara bakın")
    if args.record:
        from tools import atlas_org_cli as cli

        existing = {r["record_id"] for r in cli.read_log(cli.RECORDS_DIR / cli.MEMORY_LOG)}
        cli.add_memory_record(cli.RECORDS_DIR, {
            "record_id": f"CD-{len(existing) + 1:04d}", "type": "OPERATIONS", "authority": "TEMPORARY",
            "title": "Hata tatbikatı: " + ("hepsi yakalandı" if result["all_pass"] else "eksik var"),
            "body": json.dumps(result, ensure_ascii=False), "author": "incident_response",
            "source": "tools/chaos_drill.py"})
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
