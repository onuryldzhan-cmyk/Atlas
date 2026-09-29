"""Incident management: detect, open, update and resolve incidents in Atlas Memory.

  python -m tools.incident_report detect              # ask the running Atlas; open an incident if not ready
  python -m tools.incident_report open --what "..." --severity HIGH --services market_data
  python -m tools.incident_report update --id INC-0001 --status CONTAINED --note "..."
  python -m tools.incident_report resolve --id INC-0001 --root-cause "..." --actions "..." --prevention "..."
  python -m tools.incident_report list

Vision §38 (detect -> classify -> contain -> diagnose -> recover -> review ->
document). Each change is a new immutable memory record that supersedes the
previous version of the same incident, so the whole history stays readable.
A resolved incident must say why it happened, what was done and what
prevents it next time (atlas_org.memory_records enforces this). detect reads
only GET /api/readiness on loopback and never acts on the runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from typing import Any

from atlas_org import memory_records
from tools import atlas_org_cli as cli

DEFAULT_URL = "http://127.0.0.1:8000/api/readiness"
SEVERITY_BY_CHECK = {"execution": "HIGH", "runtime": "HIGH", "market_loop": "HIGH", "market_data": "MEDIUM",
                     "venue_rules": "MEDIUM"}
ORDER = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def _records() -> dict[str, dict[str, Any]]:
    return memory_records.replay(cli.read_log(cli.RECORDS_DIR / cli.MEMORY_LOG))


def current_incidents(records: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """incident id -> its current (not superseded) record."""

    records = _records() if records is None else records
    out = {}
    for r in records.values():
        if r["type"] == "INCIDENTS" and r["superseded_by"] is None:
            out[r["id"].split(".")[0]] = r
    return out


def _write(incident_id: str, version: int, incident: dict[str, Any], title: str, supersedes: str | None,
           author: str, source: str) -> str:
    rid = f"{incident_id}.{version}"
    fields = {"record_id": rid, "type": "INCIDENTS", "authority": "TEMPORARY", "title": title,
              "body": json.dumps(incident, ensure_ascii=False), "author": author, "source": source, "incident": incident}
    if supersedes:
        fields["supersedes"] = supersedes
    cli.add_memory_record(cli.RECORDS_DIR, fields)
    return rid


def open_incident(what: str, severity: str, services: list[str], author: str = "incident_response",
                  source: str = "tools/incident_report.py open", evidence: Any = None) -> str:
    existing = {rid.split(".")[0] for rid in _records() if rid.startswith("INC-")}
    incident_id = f"INC-{len(existing) + 1:04d}"
    incident = {"what": what, "detected_at": cli.now(), "severity": severity, "services": services,
                "status": "OPEN", "evidence": evidence}
    return _write(incident_id, 1, incident, f"{incident_id}: {what}", None, author, source)


def change(incident_id: str, status: str, author: str, **extra: Any) -> str:
    current = current_incidents().get(incident_id)
    if current is None:
        raise SystemExit(f"refused: no incident {incident_id}")
    version = int(current["id"].split(".")[1]) + 1
    incident = {**current["incident"], **{k: v for k, v in extra.items() if v}, "status": status,
                "updated_at": cli.now()}
    return _write(incident_id, version, incident, f"{incident_id}: {incident['what']} ({status})", current["id"],
                  author, f"tools/incident_report.py {status.lower()}")


def detect(url: str = DEFAULT_URL, fetch=None) -> dict[str, Any]:
    def default_fetch(u: str) -> dict:
        try:
            with urllib.request.urlopen(u, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:  # 503 carries the readiness body
            return json.loads(err.read().decode("utf-8"))

    try:
        readiness = (fetch or default_fetch)(url)
    except Exception as exc:
        readiness = {"ready": False, "checks": [{"check": "runtime", "ok": False, "state": "UNKNOWN",
                                                 "detail": f"Atlas web not reachable: {type(exc).__name__}"}]}
    failing = [c for c in readiness.get("checks", []) if not c.get("ok")]
    if readiness.get("ready") and not failing:
        return {"opened": None, "ready": True}
    what = "Atlas hazır değil: " + ", ".join(sorted(c["check"] for c in failing))
    for inc_id, record in current_incidents().items():
        if record["incident"]["status"] != "RESOLVED" and record["incident"]["what"] == what:
            return {"opened": None, "ready": False, "already_open": inc_id}
    severity = max((SEVERITY_BY_CHECK.get(c["check"], "MEDIUM") for c in failing), key=ORDER.index)
    rid = open_incident(what, severity, sorted({c["check"] for c in failing}), author="incident_response",
                        source=f"tools/incident_report.py detect ({url})", evidence=failing)
    return {"opened": rid, "ready": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect"); d.add_argument("--url", default=DEFAULT_URL)
    o = sub.add_parser("open")
    o.add_argument("--what", required=True); o.add_argument("--severity", required=True, choices=ORDER)
    o.add_argument("--services", required=True, help="comma separated")
    u = sub.add_parser("update")
    u.add_argument("--id", required=True); u.add_argument("--status", required=True, choices=("OPEN", "CONTAINED"))
    u.add_argument("--note", default="")
    r = sub.add_parser("resolve")
    r.add_argument("--id", required=True); r.add_argument("--root-cause", required=True)
    r.add_argument("--actions", required=True); r.add_argument("--prevention", required=True)
    sub.add_parser("list")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "detect":
            print(json.dumps(detect(args.url), ensure_ascii=False))
        elif args.cmd == "open":
            print(open_incident(args.what, args.severity, [s.strip() for s in args.services.split(",") if s.strip()]))
        elif args.cmd == "update":
            print(change(args.id, args.status, "incident_response", note=args.note))
        elif args.cmd == "resolve":
            print(change(args.id, "RESOLVED", "incident_response", root_cause=args.root_cause,
                         actions=args.actions, prevention=args.prevention))
        else:
            for inc_id, rec in sorted(current_incidents().items()):
                i = rec["incident"]
                print(f"{inc_id}  {i['status']:<9} {i['severity']:<8} {i['what']}")
    except memory_records.MemoryLogError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
