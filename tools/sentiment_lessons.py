"""Did the live sentiment vote help? Observe-only (owner 2026-10-02).

The live runtime already uses the Crypto Fear & Greed index as a vote
(registry v4.66: FEAR < 25, GREED >= 75, NEUTRAL abstains). This tool
never touches that vote. It joins the experience agent's replayed decisions
(<state>/research/experience/signals_v3.csv) with the daily index value of
each decision's UTC day and asks, per (action, sentiment band), whether the
240-minute outcome differs - with the same walk-forward halves, independent
(non-overlapping) samples and Benjamini-Hochberg false-discovery filter as
the experience agent's candidate lessons.

    python -m tools.sentiment_lessons            # download history, print the table
    python -m tools.sentiment_lessons --offline  # use the cached history only

Evidence only: a result becomes behaviour only through an owner-approved
proposal. Days without an index value are left out, never filled in.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

HISTORY_URL = "https://api.alternative.me/fng/?limit=0&format=json"
MAX_BODY = 2_000_000

Fetcher = Callable[[], bytes]


def _fetch() -> bytes:
    with urllib.request.urlopen(HISTORY_URL, timeout=20) as response:  # fixed public endpoint, no key
        return response.read(MAX_BODY + 1)


def parse_history(body: bytes) -> dict[str, int]:
    """{YYYY-MM-DD: value}; any malformed entry is dropped, never repaired."""
    if len(body) > MAX_BODY:
        raise ValueError("history body too large")
    data = json.loads(body)
    out: dict[str, int] = {}
    for item in data.get("data") or []:
        try:
            value, ts = int(str(item["value"])), int(str(item["timestamp"]))
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= value <= 100 and ts > 0:
            out[datetime.fromtimestamp(ts, UTC).date().isoformat()] = value
    return out


def load_history(research_dir: Path, fetch: Fetcher | None = _fetch) -> dict[str, int]:
    """Download (when fetch is given) and cache; else read the cache. Missing cache: empty."""
    cache = research_dir / "sentiment" / "fear_greed_history.json"
    if fetch is not None:
        history = parse_history(fetch())
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(history, sort_keys=True), encoding="utf-8")
        return history
    try:
        return {k: int(v) for k, v in json.loads(cache.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        return {}


def evaluate(signals_path: Path, history: dict[str, int], split_iso: str) -> dict[str, Any]:
    from atlas_finance.market_data.fear_greed_provider import classify_fear_greed_band
    from tools import experience_agent as xa

    missing = {"n": 0}

    def key(row: dict) -> tuple | None:
        value = history.get(row["time"][:10])
        if value is None:
            missing["n"] += 1
            return None
        return (row["action"], classify_fear_greed_band(value), "-")

    older, newer, total = xa.stream_groups(signals_path, split_iso, key_fn=key)
    groups = []
    for k in sorted(set(older) | set(newer)):
        a, b = older.get(k, {}), newer.get(k, {})
        groups.append({"action": k[0], "band": k[1], "n_older": a.get("n", 0), "n_newer": b.get("n", 0),
                       "n_eff_older": a.get("n_eff", 0), "n_eff_newer": b.get("n_eff", 0),
                       "avg240_older_pct": a.get("net_240m_avg_pct"), "avg240_newer_pct": b.get("net_240m_avg_pct"),
                       "win240_older": a.get("net_240m_win"), "win240_newer": b.get("net_240m_win")})
    lessons = [{**c, "band": c["regime"]} for c in xa._compare(older, newer)]
    return {"decisions": total, "without_index_value": missing["n"], "split": split_iso,
            "groups": groups, "lessons": lessons}


def main(argv: list[str] | None = None) -> int:
    from core.application import resolve_state_directory

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="use the cached index history only")
    parser.add_argument("--signals", default=None, help="signals CSV (default: the experience agent's file)")
    args = parser.parse_args(argv)
    research = resolve_state_directory() / "research"
    signals = Path(args.signals) if args.signals else research / "experience" / "signals_v3.csv"
    if not signals.exists():
        print(f"no experience file yet: {signals}")
        return 1
    try:
        history = load_history(research, None if args.offline else _fetch)
    except (OSError, ValueError) as exc:
        print(f"index history unavailable ({type(exc).__name__}); try --offline")
        return 1
    if not history:
        print("index history empty; nothing evaluated")
        return 1
    days = sorted(history)
    state = json.loads((research / "experience" / "state.json").read_text(encoding="utf-8")) \
        if (research / "experience" / "state.json").exists() else {}
    if state.get("oldest_day_ms") is None or state.get("newest_day_ms") is None:
        print("experience state missing; run the experience agent first")
        return 1
    mid = (state["oldest_day_ms"] + state["newest_day_ms"] + 86_400_000) // 2
    out = evaluate(signals, history, datetime.fromtimestamp(mid / 1000, UTC).isoformat())
    print(f"decisions {out['decisions']}, without an index value {out['without_index_value']}; "
          f"index days {days[0]} .. {days[-1]}; halves split at {out['split'][:10]}")
    print(f"{'action':6} {'band':8} {'n old/new':>13} {'indep':>11} {'240m avg% old/new':>20} {'win old/new':>13}")
    for g in out["groups"]:
        print(f"{g['action']:6} {g['band']:8} {g['n_older']:>6}/{g['n_newer']:<6} {g['n_eff_older']:>5}/{g['n_eff_newer']:<5} "
              f"{str(g['avg240_older_pct']):>9}/{str(g['avg240_newer_pct']):<10} {str(g['win240_older']):>6}/{g['win240_newer']}")
    print("lessons passing walk-forward + independent samples + FDR:",
          ", ".join(f"{c['action']} {c['band']} (q {c['q_newer']})" for c in out["lessons"]) or "none")
    print("Evidence only. The live sentiment vote is unchanged; any change needs an owner-approved proposal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
