"""Read-only: what the AI-001 and rule-based agents actually said, and which agent failed.

python -m tools.agent_report          (last 3 CEO / council / model-validation records + last cycle's non-OK agents)
python -m tools.agent_report --n 10
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlas_org import memory_records
from tools import atlas_org_cli as cli

LOG = Path("governance/records") / cli.MEMORY_LOG
SHOW = {"ceo_ai": "CEO", "model_council": "KONSEY", "model_validation": "MODEL DOĞRULAMA"}


def _body(rec):
    try:
        return json.loads(rec.get("body") or "{}")
    except (TypeError, ValueError):
        return {"metin": rec.get("body")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3)
    args = ap.parse_args(argv)
    if not LOG.exists():
        print(f"hafıza kaydı yok: {LOG}")
        return 0
    recs = sorted(memory_records.replay(cli.read_log(LOG)).values(), key=lambda r: r.get("created_at") or "")
    for author, label in SHOW.items():
        mine = [r for r in recs if r.get("author") == author][-args.n:]
        print(f"\n=== {label}: {len(mine)} kayıt gösteriliyor ===")
        for r in mine:
            print(f"- {r.get('created_at')} {r.get('id') or r.get('record_id')}: {r.get('title')}")
            print(json.dumps(_body(r), ensure_ascii=False, indent=2)[:2500])
    cycles = [r for r in recs if r.get("author") == "executive_assistant" and str(r.get("title", "")).startswith("Ajan döngüsü")]
    if cycles:
        last = cycles[-1]
        bad = [a for a in _body(last).get("agent_cycle", []) if a.get("verdict") != "OK"]
        print(f"\n=== Son ajan döngüsü {last.get('created_at')}: sorunlu ajan {len(bad)} ===")
        for a in bad:
            print(f"- {a.get('name')} ({a.get('unit')}): {a.get('verdict')} - {a.get('summary')} [{a.get('seconds')} sn]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
