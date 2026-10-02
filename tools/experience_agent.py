"""Experience agent (owner 2026-10-02): Atlas keeps learning from history while it runs.

Every agent cycle it replays ONE more day of Atlas's real decision chain
(tools.backtest_replay, record_signals=True):

  * forward first: when a full day has passed since the newest replayed day,
    that new day is replayed (the experience keeps up with the present);
  * otherwise backward: the day before the oldest replayed day, until
    MAX_DAYS_BACK (years of experience accumulate a day at a time).

Every BUY/SELL decision is appended to <research>/experience/signals.csv
with its after-fee 60/240-minute outcome. The lesson book is then rebuilt
with a walk-forward split: a group is a CANDIDATE lesson only when it is
MEASURED (>= tools.lesson_book.MIN_SAMPLES) in BOTH the older and the newer
half of the experience and its 240-minute direction agrees in both halves.

Authority: research evidence only. It writes a memory record when the
candidate set changes; it never changes a gate, a parameter or an order.
A candidate becomes trading behaviour only through an owner-approved proposal.
"""
from __future__ import annotations

import csv
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

DAY_MS = 24 * 60 * 60_000
MAX_DAYS_BACK = 730
HORIZON_PAD_MIN = 1440  # longest outcome horizon (1 day) after the day ends
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
SLIPPAGE_BPS = 5

Fetcher = Callable[[str, int], list[list]]


def _paths(base: Path) -> tuple[Path, Path]:
    d = base / "experience"
    d.mkdir(parents=True, exist_ok=True)
    return d / "state.json", d / "signals_v2.csv"  # v2: raw moves + 1-day horizon


def _load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(state, dict):
            return state
    except (OSError, ValueError):
        pass
    return {}


def next_day(state: dict[str, Any], now_ms: int) -> tuple[int, str] | None:
    """(day_start_ms, direction) of the next day to replay, or None when nothing is due."""
    today = now_ms - now_ms % DAY_MS
    # a day is complete only when its last decision's 240-minute outcome is in the past
    last_complete = today - DAY_MS if now_ms - today >= HORIZON_PAD_MIN * 60_000 else today - 2 * DAY_MS
    newest, oldest = state.get("newest_day_ms"), state.get("oldest_day_ms")
    if newest is None or oldest is None:
        return last_complete, "first"
    if newest < last_complete:
        return newest + DAY_MS, "forward"
    if (last_complete - oldest) // DAY_MS < MAX_DAYS_BACK:
        return oldest - DAY_MS, "backward"
    return None


def _download(symbol: str, start_ms: int, end_ms: int, fetch: Fetcher) -> list[list]:
    rows: list[list] = []
    cursor = start_ms
    while cursor < end_ms:
        for attempt in range(3):
            try:
                page = fetch(symbol, cursor)
                break
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        if not page:
            break
        rows.extend(r for r in page if int(r[0]) < end_ms)
        cursor = int(page[-1][0]) + 60_000
    return rows


def replay_day(day_ms: int, fetch: Fetcher, symbols=SYMBOLS, replay=None) -> list[dict]:
    """Every BUY/SELL decision Atlas would have made on that UTC day, with outcomes."""
    from tools import backtest_replay as bt

    replay = replay or bt.replay
    start = day_ms - bt.WINDOW * 60_000  # warm-up candles the decision chain needs
    end = day_ms + DAY_MS + HORIZON_PAD_MIN * 60_000
    data = {s: _download(s, start, end, fetch) for s in symbols}
    result = replay(data, step=15, sleeves=True, slippage_bps=SLIPPAGE_BPS, record_signals=True)
    lo = datetime.fromtimestamp(day_ms / 1000, UTC).isoformat()
    hi = datetime.fromtimestamp((day_ms + DAY_MS) / 1000, UTC).isoformat()
    return [s for s in result.signals if lo <= s["time"] < hi]


def _append(path: Path, signals: list[dict]) -> None:
    from decimal import Decimal

    from tools.backtest_replay import SIGNAL_COLUMNS as COLUMNS

    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(COLUMNS)
        for sig in signals:
            w.writerow(["" if sig.get(c) is None else (format(sig[c], "f") if isinstance(sig[c], Decimal) else sig[c])
                        for c in COLUMNS])


def candidate_lessons(rows: list[dict]) -> list[dict]:
    """Walk-forward: MEASURED and same 240m direction in the older AND the newer half."""
    from tools import lesson_book as lb

    if len(rows) < 2 * lb.MIN_SAMPLES:
        return []
    rows = sorted(rows, key=lambda r: r["time"])
    half = len(rows) // 2
    older = {(g["action"], g["regime"], g["confidence"]): g for g in lb.build(rows[:half])}
    newer = {(g["action"], g["regime"], g["confidence"]): g for g in lb.build(rows[half:])}
    out = []
    for key, a in sorted(older.items()):
        b = newer.get(key)
        if not b or a["verdict"] != "MEASURED" or b["verdict"] != "MEASURED":
            continue
        if a["net_240m_avg_pct"] is None or b["net_240m_avg_pct"] is None:
            continue
        if (a["net_240m_avg_pct"] > 0) != (b["net_240m_avg_pct"] > 0):
            continue
        out.append({"action": key[0], "regime": key[1], "confidence": key[2], "n_older": a["n"], "n_newer": b["n"],
                    "avg240_older_pct": a["net_240m_avg_pct"], "avg240_newer_pct": b["net_240m_avg_pct"],
                    "win240_older": a["net_240m_win"], "win240_newer": b["net_240m_win"]})
    return out


def run(records_dir: Path, research_dir: Path, *, fetch: Fetcher | None = None, now_ms: int | None = None,
        replay=None) -> dict[str, Any]:
    from tools import atlas_org_cli as cli

    state_path, signals_path = _paths(research_dir)
    state = _load_state(state_path)
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    due = next_day(state, now_ms)
    if due is None:
        return {"verdict": "OK", "summary": f"deneyim tamam: {MAX_DAYS_BACK} gün geriye işlendi"}
    day_ms, direction = due
    if fetch is None:
        from tools.measure_volatility_ceiling import fetch_page as fetch
    try:
        signals = replay_day(day_ms, fetch, replay=replay)
    except OSError as exc:  # network: nothing recorded, the same day is retried next cycle
        return {"verdict": "WARN", "summary": f"veri indirilemedi ({type(exc).__name__}); gün tekrar denenecek"}
    _append(signals_path, signals)
    state["newest_day_ms"] = max(day_ms, state.get("newest_day_ms", day_ms))
    state["oldest_day_ms"] = min(day_ms, state.get("oldest_day_ms", day_ms))
    state["days"] = int(state.get("days", 0)) + 1
    with signals_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    lessons = candidate_lessons(rows)
    fingerprint = sorted([c["action"], c["regime"], c["confidence"], c["avg240_newer_pct"] > 0] for c in lessons)  # lists: JSON round-trips them
    changed = fingerprint != state.get("lesson_fingerprint", [])
    state["lesson_fingerprint"] = fingerprint
    state_path.write_text(json.dumps(state), encoding="utf-8")
    day = datetime.fromtimestamp(day_ms / 1000, UTC).date().isoformat()
    summary = f"{day} ({direction}) işlendi: {len(signals)} karar; toplam {state['days']} gün, {len(rows)} karar; aday ders {len(lessons)}"
    if changed:
        existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)} if (records_dir / cli.MEMORY_LOG).exists() else set()
        cli.add_memory_record(records_dir, {
            "record_id": f"XP-{len(existing) + 1:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
            "title": f"Deneyim: {state['days']} gün, {len(rows)} karar, {len(lessons)} aday ders (kural değil)",
            "body": json.dumps({"days": state["days"], "decisions": len(rows), "candidate_lessons": lessons[:40],
                                "method": "walk-forward halves; MEASURED in both; same 240m direction",
                                "caveat": "macro/sentiment excluded offline; overlapping 15-min decisions"},
                               ensure_ascii=False),
            "author": "experiment_manager", "source": "tools/experience_agent.py (backtest_replay + lesson_book)"})
    return {"verdict": "OK", "summary": summary}
