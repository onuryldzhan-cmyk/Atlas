"""SEC-001.1 baseline (registry v5.28): no secret literal in runtime code or config.

CLAUDE.md: "Never put secrets (API keys, DB passwords) in prompts or code."
Scans every runtime-closure module plus config/ and the entry points for
well-known credential shapes. Test files are out of scope (they carry
deliberate fake secrets to prove redaction works).
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS = {
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key_block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    # a 64-char exchange-style key assigned to something named key/secret
    "assigned_exchange_key": re.compile(
        r"(?i)(api[_-]?key|secret|passphrase)\s*[:=]\s*['\"][A-Za-z0-9]{48,}['\"]"),
}


def _files():
    modules = json.loads((ROOT / "packaging/atlas_runtime_closure.json").read_text(encoding="utf-8"))["modules"]
    paths = {ROOT / m for m in modules}
    paths |= {p for p in (ROOT / "config").rglob("*") if p.is_file()}
    paths |= {ROOT / name for name in ("main.py", "atlas_service.py", "atlas_supervisor.py", "web_app.py", ".env.example")}
    return sorted(p for p in paths if p.exists())


def test_no_secret_literals_in_runtime_or_config():
    hits = []
    for path in _files():
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                hits.append(f"{path.relative_to(ROOT)}: {name}")
    assert hits == []


def test_patterns_catch_known_shapes():
    samples = {
        "aws_access_key": "AKIAABCDEFGHIJKLMNOP",
        "private_key_block": "-----BEGIN RSA PRIVATE KEY-----",
        "github_token": "ghp_" + "a" * 36,
        "openai_style_key": "sk-" + "b" * 40,
        "assigned_exchange_key": 'api_key = "' + "c" * 64 + '"',
    }
    for name, sample in samples.items():
        assert PATTERNS[name].search(sample), name
