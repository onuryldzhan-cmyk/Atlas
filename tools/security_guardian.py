"""Security Guardian: review a git change and optionally record it on a proposal.

  python -m tools.security_guardian --base HEAD~1            # review HEAD~1..working tree
  python -m tools.security_guardian --base main --json
  python -m tools.security_guardian --base HEAD~1 --record P-0001

The analysis itself is atlas_org.security_review (pure). This wrapper only
reads git: the changed paths between ``--base`` and the working tree, their
current text, and the base version of every requirements file. ``--record``
appends a SECURITY review (actor ``security``) whose verdict and checks are
exactly the report's - the proposal log refuses any other combination.
Exit code: 0 PASS, 1 REVIEW_REQUIRED, 2 FAIL, 3 usage/git error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from atlas_org.security_review import SecurityReport, files_digest, review_change

ROOT = Path(__file__).resolve().parents[1]
EXIT = {"PASS": 0, "REVIEW_REQUIRED": 1, "FAIL": 2}
MAX_FILE_BYTES = 2 * 1024 * 1024


def _git(*args: str) -> str:
    # List arguments, no shell: nothing from the change reaches a shell.
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def collect(base: str) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    changed = set(_git("diff", "-z", "--name-only", base, "--").split("\0"))
    changed |= set(_git("ls-files", "-z", "--others", "--exclude-standard").split("\0"))
    changed.discard("")
    files, deps = {}, {}
    for rel in sorted(changed):
        path = ROOT / rel
        text = ""
        if path.is_file() and path.stat().st_size <= MAX_FILE_BYTES:
            text = path.read_text(encoding="utf-8", errors="replace")
        files[rel] = text
        name = Path(rel).name
        if name.startswith("requirements") and name.endswith(".txt") or rel.startswith("requirements/"):
            try:
                old = _git("show", f"{base}:{rel}")
            except subprocess.CalledProcessError:
                old = ""
            deps[rel] = (old, text)
    return files, deps


def read_files(paths: list[str], base: str) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """Current contents of exactly these paths (and the base version of requirement files)."""

    files, deps = {}, {}
    for rel in paths:
        path = ROOT / rel
        text = ""
        if path.is_file() and path.stat().st_size <= MAX_FILE_BYTES:
            text = path.read_text(encoding="utf-8", errors="replace")
        files[rel] = text
        name = Path(rel).name
        if name.startswith("requirements") and name.endswith(".txt") or rel.startswith("requirements/"):
            try:
                old = _git("show", f"{base}:{rel}")
            except subprocess.CalledProcessError:
                old = ""
            deps[rel] = (old, text)
    return files, deps


def reverify(review: dict) -> str | None:
    """Re-run the guardian on the reviewed files; None if the recorded review still holds, else why not."""

    files_reviewed = review.get("files_reviewed")
    if not isinstance(files_reviewed, list) or not review.get("files_digest") or not review.get("base"):
        return "security review has no files_reviewed/files_digest/base to re-verify"
    try:
        files, deps = read_files(files_reviewed, review["base"])
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return f"git error while re-verifying: {exc}"
    if files_digest(files) != review["files_digest"]:
        return "reviewed files changed since the security review: re-run python -m tools.security_guardian --record"
    fresh = review_change(files, deps)
    if fresh.checks() != review.get("checks"):
        return f"security review does not reproduce: recorded {review.get('checks')} vs now {fresh.checks()}"
    return None


def render(report: SecurityReport) -> str:
    data = report.to_dict()
    lines = ["SECURITY REVIEW"]
    lines += [f"{k:<17}{v}" for k, v in data["checks"].items()]
    lines.append(f"{'Overall':<17}{data['overall']}")
    for f in data["findings"]:
        where = f"{f['path']}:{f['line']}" if f["line"] else f["path"]
        lines.append(f"  [{f['level']}] {f['category']} {where} - {f['detail']}")
    lines.append(f"files reviewed: {len(data['files_reviewed'])}")
    lines.append("note: static, heuristic analysis (AST + patterns); REVIEW means a human must look")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--record", metavar="PROPOSAL_ID")
    args = parser.parse_args(argv)
    try:
        files, deps = collect(args.base)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"git error: {exc}", file=sys.stderr)
        return 3
    report = review_change(files, deps)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) if args.json else render(report))
    if args.record:
        from tools import atlas_org_cli
        from atlas_org.proposals import ProposalLogError

        summary = f"security_guardian vs {args.base}: {report.overall()} ({len(report.findings)} findings)"
        try:
            atlas_org_cli.add_proposal_event(
                atlas_org_cli.RECORDS_DIR, proposal_id=args.record, event="REVIEW", actor="security",
                payload={"kind": "SECURITY", "verdict": report.overall(), "summary": summary,
                         "tool": "security_guardian", "base": args.base,
                         "files_reviewed": report.files_reviewed, "files_digest": files_digest(files),
                         "checks": report.checks(), "findings": report.to_dict()["findings"]})
        except ProposalLogError as exc:
            print(f"not recorded: {exc}", file=sys.stderr)
            return 3
        print(f"recorded on {args.record}")
    return EXIT[report.overall()]


if __name__ == "__main__":
    raise SystemExit(main())
