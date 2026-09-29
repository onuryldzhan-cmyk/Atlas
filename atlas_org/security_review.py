"""Security Guardian: an auditable security review of a proposed change.

Pure analysis (L1: no I/O) over what the caller already read: the changed
files' new text and the old/new dependency files. Python sources are parsed
with ``ast``, so findings come from real call sites (``subprocess.run(...,
shell=True)``, ``eval``, ``pickle.loads``, ``yaml.load`` without a safe
loader, network imports) rather than from words in comments or strings.
Keyword patterns are used only where the input is text by nature: credential
shapes (same shapes as tests/test_sec001_no_secret_literals.py) and
prompt-injection phrases in documents.

Each category ends PASS, REVIEW or FAIL; the overall verdict is the worst
one (FAIL > REVIEW_REQUIRED > PASS). REVIEW means a human must look; it is
never silently turned into PASS.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from atlas_org.proposals import touches_protected

CATEGORIES = ("DEPENDENCIES", "SECRETS", "FILESYSTEM", "NETWORK", "EXTERNAL_CODE",
              "SUBPROCESS", "PRIVILEGE", "PROMPT_INJECTION")
PASS, REVIEW, FAIL = "PASS", "REVIEW", "FAIL"
_RANK = {PASS: 0, REVIEW: 1, FAIL: 2}
OVERALL = {PASS: "PASS", REVIEW: "REVIEW_REQUIRED", FAIL: "FAIL"}

SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key_block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "assigned_exchange_key": re.compile(
        r"(?i)(api[_-]?key|secret|passphrase)\s*[:=]\s*['\"][A-Za-z0-9]{48,}['\"]"),
}
INJECTION_PATTERNS = re.compile(
    r"(?i)ignore (all |any )?(previous|prior|above) instructions|disregard (the )?(system|previous) prompt|"
    r"you are now (in )?(developer|dan) mode|önceki talimatları (yok say|unut)|"
    r"(approve|merge|deploy) (this|it) without (review|approval)|onay(sız)? olmadan (uygula|deploy)")
NETWORK_MODULES = {"socket", "requests", "httpx", "urllib", "urllib3", "aiohttp", "http", "ftplib",
                   "smtplib", "paramiko", "websocket", "websockets"}
DANGEROUS_CALLS = {"eval", "exec", "compile", "__import__"}
UNSAFE_DESERIALIZE = {("pickle", "load"), ("pickle", "loads"), ("marshal", "loads"), ("dill", "loads")}
SUBPROCESS_FUNCS = {"run", "call", "check_call", "check_output", "Popen", "getoutput", "getstatusoutput"}
DESTRUCTIVE_FS = {("shutil", "rmtree"), ("os", "remove"), ("os", "unlink"), ("os", "rmdir"),
                  ("os", "removedirs"), ("os", "chmod"), ("os", "chown")}
REQ_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-\[\]]+)\s*(==\s*[^\s;#]+)?")


@dataclass
class Finding:
    category: str
    level: str
    path: str
    line: int | None
    detail: str

    def to_dict(self) -> dict:
        return {"category": self.category, "level": self.level, "path": self.path,
                "line": self.line, "detail": self.detail}


@dataclass
class SecurityReport:
    findings: list[Finding] = field(default_factory=list)
    files_reviewed: list[str] = field(default_factory=list)

    def checks(self) -> dict[str, str]:
        out = {c: PASS for c in CATEGORIES}
        for f in self.findings:
            if _RANK[f.level] > _RANK[out[f.category]]:
                out[f.category] = f.level
        return out

    def overall(self) -> str:
        worst = max(self.checks().values(), key=_RANK.__getitem__)
        return OVERALL[worst]

    def to_dict(self) -> dict:
        return {"overall": self.overall(), "checks": self.checks(),
                "files_reviewed": self.files_reviewed, "findings": [f.to_dict() for f in self.findings]}


def _dotted(node: ast.AST) -> tuple[str, ...]:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return tuple(reversed(parts))


def _is_true(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _python(path: str, text: str, report: SecurityReport) -> None:
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        report.findings.append(Finding("EXTERNAL_CODE", REVIEW, path, exc.lineno, "file does not parse"))
        return
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = a.name.split(".")[0]
                if a.name.split(".")[0] in NETWORK_MODULES:
                    report.findings.append(Finding("NETWORK", REVIEW, path, node.lineno, f"imports {a.name}"))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            top = node.module.split(".")[0]
            for a in node.names:
                aliases[a.asname or a.name] = f"{top}.{a.name}"
            if top in NETWORK_MODULES:
                report.findings.append(Finding("NETWORK", REVIEW, path, node.lineno, f"imports from {node.module}"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if not name:
            continue
        head = aliases.get(name[0], name[0])
        full = (*head.split("."), *name[1:])
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        line = node.lineno
        if len(full) == 1 and full[0] in DANGEROUS_CALLS:
            report.findings.append(Finding("EXTERNAL_CODE", FAIL, path, line, f"{full[0]}() executes dynamic code"))
        elif full[:2] in UNSAFE_DESERIALIZE:
            report.findings.append(Finding("EXTERNAL_CODE", FAIL, path, line, f"{'.'.join(full)} deserializes untrusted data"))
        elif full[:2] == ("yaml", "load") and "Loader" not in kw and len(node.args) < 2:
            report.findings.append(Finding("EXTERNAL_CODE", FAIL, path, line, "yaml.load without a safe Loader"))
        elif full[0] == "subprocess" and len(full) > 1 and full[1] in SUBPROCESS_FUNCS:
            level = FAIL if _is_true(kw.get("shell")) or full[1] in ("getoutput", "getstatusoutput") else REVIEW
            report.findings.append(Finding("SUBPROCESS", level, path, line,
                                           f"subprocess.{full[1]}" + (" with shell=True" if level == FAIL else "")))
        elif full[:2] in (("os", "system"), ("os", "popen")) or (full[0] == "os" and len(full) > 1 and full[1].startswith("exec")):
            report.findings.append(Finding("SUBPROCESS", FAIL, path, line, f"{'.'.join(full)} runs a shell command"))
        elif full[:2] in DESTRUCTIVE_FS:
            report.findings.append(Finding("FILESYSTEM", REVIEW, path, line, f"{'.'.join(full)} deletes or re-permissions files"))
        elif full[0] == "pip":
            report.findings.append(Finding("DEPENDENCIES", FAIL, path, line, "installs packages at runtime"))
        for arg in [*node.args, *kw.values()]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and ("../" in arg.value or "..\\" in arg.value):
                report.findings.append(Finding("FILESYSTEM", REVIEW, path, line, "path literal escapes its directory ('..')"))


def _requirements(old: str, new: str) -> dict[str, str | None]:
    def parse(text: str) -> dict[str, str | None]:
        out = {}
        for raw in (text or "").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith(("-", "--")):
                continue
            m = REQ_LINE.match(line)
            if m:
                out[m.group(1).lower()] = (m.group(2) or "").replace(" ", "") or None
        return out
    before, after = parse(old), parse(new)
    return {k: v for k, v in after.items() if before.get(k, "<absent>") != v}


def review_change(files: dict[str, str], dependency_changes: dict[str, tuple[str, str]] | None = None) -> SecurityReport:
    """Review changed files ({path: new text}; deleted files as "") and dependency files ({path: (old, new)})."""

    report = SecurityReport(files_reviewed=sorted(files))
    for path, text in sorted(files.items()):
        norm = path.replace("\\", "/")
        if touches_protected([norm]):
            report.findings.append(Finding("PRIVILEGE", REVIEW, norm, None,
                                           "touches protected governance/permission files: owner decision required"))
        for name, pattern in SECRET_PATTERNS.items():
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                level = REVIEW if norm.startswith("tests/") else FAIL
                report.findings.append(Finding("SECRETS", level, norm, line, f"credential shape: {name}"))
        if norm.endswith(".py"):
            _python(norm, text, report)
        elif norm.endswith((".md", ".txt", ".json", ".yaml", ".yml", ".html")):
            for m in INJECTION_PATTERNS.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                report.findings.append(Finding("PROMPT_INJECTION", REVIEW, norm, line,
                                               f"instruction-like text: {m.group(0)!r}"))
    for path, (old, new) in sorted((dependency_changes or {}).items()):
        for package, pin in _requirements(old, new).items():
            if pin is None:
                report.findings.append(Finding("DEPENDENCIES", FAIL, path, None, f"{package} added or changed without an exact == pin"))
            else:
                report.findings.append(Finding("DEPENDENCIES", REVIEW, path, None,
                                               f"{package}{pin}: new/changed dependency needs license, maintenance and security review"))
    return report
