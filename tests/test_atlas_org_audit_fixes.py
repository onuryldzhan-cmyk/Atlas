"""Independent audit v5.39 findings F1-F6: each attack from the audit report must now fail."""

from __future__ import annotations

import os
import stat

import pytest

from atlas_org import manager, memory_records, owner_auth, proposals
from atlas_org.proposals import ProposalLogError, next_event, replay, touches_protected
from atlas_org.security_review import CATEGORIES, review_change
from tools import atlas_org_cli as cli

from atlas_org.security_review import files_digest as _files_digest

BIND = {"files_reviewed": [], "files_digest": _files_digest({}), "base": "HEAD"}
AT = "2026-09-29T00:00:00Z"
KEY = b"k" * 32
SEC_PASS = {c: "PASS" for c in CATEGORIES}
FIELDS = {"title": "t", "problem": "p", "motivation": "m", "proposed_changes": "c",
          "affected_components": ["x"], "affected_files": ["core/x.py"], "risk_level": "LOW", "rollback_plan": "r"}


def _ready():
    events = []
    for ev, actor, payload in [
        ("CREATE", "code_engineering", FIELDS), ("SUBMIT", "code_engineering", {}),
        ("RECORD_TESTS", "code_engineering", {"command": "pytest", "passed": 1, "failed": 0}),
        ("REVIEW", "code_review", {"kind": "CODE", "verdict": "PASS", "summary": "ok"}),
        ("REVIEW", "security", {"kind": "SECURITY", "verdict": "PASS", "summary": "ok", "checks": SEC_PASS, "tool": "security_guardian", **BIND, "findings": []}),
        ("MARK_READY", "executive_assistant", {}),
    ]:
        events.append(next_event(events, proposal_id="P-1", event=ev, actor=actor, at=AT, payload=payload))
    return events


# ---------------------------------------------------------------- F1 owner identity

def test_f1_agent_without_key_cannot_write_an_owner_decision():
    with pytest.raises(ProposalLogError, match="owner's key"):
        next_event(_ready(), proposal_id="P-1", event="OWNER_APPROVE", actor="owner", at=AT)


def test_f1_forged_or_moved_signature_is_refused_where_the_key_exists():
    events = _ready()
    forged = {"seq": len(events) + 1, "prev_hash": events[-1]["hash"], "proposal_id": "P-1",
              "event": "OWNER_APPROVE", "actor": "owner", "at": AT, "payload": {}, "owner_sig": "0" * 64}
    forged["hash"] = proposals.event_hash(forged)
    assert replay([*events, forged])["P-1"].owner_decision["verified"] is None  # no key: never "verified"
    with pytest.raises(ProposalLogError, match="does not verify"):
        replay([*events, forged], KEY)
    genuine = next_event(events, proposal_id="P-1", event="OWNER_APPROVE", actor="owner", at=AT, owner_key=KEY)
    assert replay([*events, genuine], KEY)["P-1"].owner_decision["verified"] is True
    moved = {**genuine, "proposal_id": "P-2"}
    moved["hash"] = proposals.event_hash(moved)
    with pytest.raises(ProposalLogError):
        replay([*events, moved], KEY)


def test_f1_unsigned_owner_event_and_signature_on_agent_event_are_refused():
    events = _ready()
    unsigned = {"seq": len(events) + 1, "prev_hash": events[-1]["hash"], "proposal_id": "P-1",
                "event": "OWNER_APPROVE", "actor": "owner", "at": AT, "payload": {}}
    unsigned["hash"] = proposals.event_hash(unsigned)
    with pytest.raises(ProposalLogError, match="without a valid owner signature"):
        replay([*events, unsigned])
    stray = {"seq": len(events) + 1, "prev_hash": events[-1]["hash"], "proposal_id": "P-1",
             "event": "REQUEST_REVISION", "actor": "code_review", "at": AT, "payload": {}, "owner_sig": "a" * 64}
    stray["hash"] = proposals.event_hash(stray)
    with pytest.raises(ProposalLogError, match="non-owner"):
        replay([*events, stray])


def test_f1_mark_applied_needs_a_verified_approval(tmp_path, monkeypatch):
    records = tmp_path / "rec"
    keyfile = tmp_path.parent / f"{tmp_path.name}_owner.key"
    for ev in _ready():
        cli.add_proposal_event(records, proposal_id="P-1", event=ev["event"], actor=ev["actor"],
                               payload=ev["payload"], at=AT)
    keyfile.write_text("b" * 64)
    key = keyfile.read_bytes().strip()
    cli.add_proposal_event(records, proposal_id="P-1", event="OWNER_APPROVE", actor="owner", at=AT, owner_key=key)
    with pytest.raises(ProposalLogError, match="verified"):
        cli.add_proposal_event(records, proposal_id="P-1", event="MARK_APPLIED", actor="deployment_manager", at=AT)
    cli.add_proposal_event(records, proposal_id="P-1", event="MARK_APPLIED", actor="deployment_manager",
                           at=AT, owner_key=key)


def test_f1_owner_key_lives_outside_the_repo_and_is_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_OWNER_KEY_FILE", str(cli.ROOT / "owner.key"))
    with pytest.raises(SystemExit, match="outside the repository"):
        cli.owner_init()
    target = tmp_path.parent / f"{tmp_path.name}_k" / "owner.key"
    monkeypatch.setenv("ATLAS_OWNER_KEY_FILE", str(target))
    assert cli.owner_init() == target
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert len(cli.load_owner_key()) == 64
    with pytest.raises(SystemExit, match="already exists"):
        cli.owner_init()


def test_f1_owner_memory_records_are_signed():
    rec = memory_records.next_record([], owner_key=KEY, record_id="M-1", type="DECISION", authority="AUTHORITATIVE",
                                     title="t", body="b", author="owner", source="s", at=AT)
    assert memory_records.replay([rec], KEY)["M-1"]["owner_verified"] is True
    assert memory_records.replay([rec])["M-1"]["owner_verified"] is None
    with pytest.raises(ProposalLogError):
        memory_records.next_record([], record_id="M-1", type="DECISION", authority="AUTHORITATIVE",
                                   title="t", body="b", author="owner", source="s", at=AT)


def test_f1_signing_rejects_short_keys():
    with pytest.raises(owner_auth.OwnerSignatureError):
        owner_auth.sign(b"short", {"a": 1})


# ---------------------------------------------------------------- F2 protected paths

@pytest.mark.parametrize("path", ["/CLAUDE.md", "claude.md", "././CLAUDE.md", "docs/../CLAUDE.md", "Governance/x",
                                  "/home/user/Atlas/governance/r.json", "atlas_org",
                                  "C:\\Users\\x\\SOURCE_REPOSITORY\\governance\\x.json", "../outside.py"])
def test_f2_protected_path_spellings(path):
    assert touches_protected([path])
    with pytest.raises(ProposalLogError, match="protected"):
        next_event([], proposal_id="P-1", event="CREATE", actor="a", at=AT, payload={**FIELDS, "affected_files": [path]})


@pytest.mark.parametrize("path", ["CLAUDE.md.bak", "core/x.py", "docs/governance_notes.md", "/srv/app/core/a.py"])
def test_f2_no_false_protection(path):
    assert not touches_protected([path])


# ---------------------------------------------------------------- F3 security evasions

@pytest.mark.parametrize("source", [
    "import subprocess\ngetattr(subprocess,'run')('x',shell=True)\n",
    "import builtins\nbuiltins.eval('1')\n",
    "__builtins__['eval']('1')\n",
    "from os import *\nsystem('x')\n",
    "import pty\npty.spawn('sh')\n",
    "import os\nos.spawnl(0, 'x')\n",
])
def test_f3_evasions_fail(source):
    assert review_change({"x.py": source}).overall() == "FAIL"


def test_f3_dynamic_import_needs_review():
    assert review_change({"x.py": "import importlib\nimportlib.import_module('os').system('x')\n"}).overall() != "PASS"


# ---------------------------------------------------------------- F6 manager phrasing

@pytest.mark.parametrize("text", ["go live with the strategy", "backtest then go live on binance",
                                  "canlıya geç ve strateji çalıştır", "add a fix to AGENTS.md",
                                  "fix atlas_org/permissions.py", "improve the kill switch so it can be disabled",
                                  "add stop-loss removal", "CANLI İŞLEM başlat", "RİSK LİMİTİNİ ARTIR"])
def test_f6_owner_only_requests_are_refused(text):
    assert manager.classify(text).category == "REQUIRES_OWNER"


# ---------------------------------------------------------------- re-audit residuals

@pytest.mark.parametrize("source, expected", [
    ("o=__import__; o('os').system('x')\n", "FAIL"),
    ("import sys\nsys.modules['os'].system('x')\n", "REVIEW_REQUIRED"),
    ("import os\nvars(os)['system']('x')\n", "REVIEW_REQUIRED"),
    ("import asyncio\nasyncio.create_subprocess_shell('x')\n", "FAIL"),
    ("import runpy\nrunpy.run_path('x')\n", "FAIL"),
    ("import code\ncode.interact()\n", "FAIL"),
])
def test_reaudit_f3_residuals(source, expected):
    assert review_change({"x.py": source}).overall() == expected


@pytest.mark.parametrize("path", ["CLAUDE.md.", "CLAUDE.md::$DATA", "CLAUDE.md\x00", "atlas_org​/x.py",
                                  "~/Atlas/CLAUDE.md"])
def test_reaudit_f2_path_aliases(path):
    assert touches_protected([path])


@pytest.mark.parametrize("text", ["use real funds", "sermayeyi artır", "give code agent write access"])
def test_reaudit_f6_capital_and_access(text):
    assert manager.classify(text).category == "REQUIRES_OWNER"


def test_new1_web_layer_never_reads_the_owner_key():
    from pathlib import Path

    source = Path("observability/governance_records.py").read_text(encoding="utf-8")
    assert "owner.key" not in source and "ATLAS_OWNER_KEY_FILE" not in source
    from observability import command_center as cc

    brief = cc.compose(health={}, account=None, tasks={}, memory={}, proposals={
        "available": True, "awaiting_owner": [], "proposals": [{"id": "P-0001", "title": "t", "status": "APPROVED",
                                                               "risk_level": "LOW", "author": "a",
                                                               "owner_decision": {"verified": None}}]})
    assert "doğrulanamaz" in cc.answer("öneri P-0001", brief)["answer"]


def test_utf8_bom_source_parses_and_is_still_scanned():
    # web_app.py starts with a BOM; it is valid Python and must be scanned, not reported as unparseable
    clean = review_change({"x.py": "﻿x = 1\n"})
    assert clean.overall() == "PASS" and not clean.findings
    risky = review_change({"x.py": "﻿import subprocess\nsubprocess.run('x', shell=True)\n"})
    assert risky.overall() == "FAIL"
