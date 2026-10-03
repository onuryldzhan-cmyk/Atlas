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
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from tools.fdr import bh_qvalues, binom_two_sided_p  # noqa: F401 - re-exported (tests, sentiment_lessons)

DAY_MS = 24 * 60 * 60_000
MAX_DAYS_BACK = 730
HORIZON_PAD_MIN = 1440  # longest outcome horizon (1 day) after the day ends
CORE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
MIN_COVERAGE = 0.95  # a coin without (nearly) every minute of the window is left out of that day


def symbols() -> tuple[str, ...]:
    """Owner 2026-10-02: all coins Atlas watches (config/universe_selection.json), else the core five."""
    try:
        from tools.regime_engine import load_symbols

        return tuple(load_symbols()) or CORE_SYMBOLS
    except (OSError, ValueError, KeyError):
        return CORE_SYMBOLS
SLIPPAGE_BPS = 5
STABLE_RUNS = 14  # a candidate present (same direction) in this many consecutive replayed days is drafted as a proposal
PROPOSAL_PREFIX = "XL-"
FDR_Q = 0.10  # Benjamini-Hochberg false-discovery level for candidate lessons
MIN_EFF = 30  # independent (non-overlapping 240m) outcomes a candidate needs in EACH half (= lesson_book.MIN_SAMPLES)

Fetcher = Callable[[str, int], list[list]]


def _paths(base: Path) -> tuple[Path, Path]:
    d = base / "experience"
    d.mkdir(parents=True, exist_ok=True)
    return d / "state.json", d / "signals_v3.csv"  # v3: 5/10-min horizons + take-profit/stop-loss barriers


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


def replay_day(day_ms: int, fetch: Fetcher, symbols=None, replay=None) -> list[dict]:
    """Every BUY/SELL decision Atlas would have made on that UTC day, with outcomes."""
    from tools import backtest_replay as bt

    replay = replay or bt.replay
    start = day_ms - bt.WINDOW * 60_000  # warm-up candles the decision chain needs
    end = day_ms + DAY_MS + HORIZON_PAD_MIN * 60_000
    symbols = symbols or globals()["symbols"]()
    expected = (end - start) // 60_000
    data = {s: _download(s, start, end, fetch) for s in symbols}
    # The replay keeps only minutes EVERY coin has: one coin missing (listed later, delisted, a gap)
    # would erase the whole day, so such a coin is left out of this day instead.
    data = {s: rows for s, rows in data.items() if len(rows) >= MIN_COVERAGE * expected}
    if not data:
        return []
    # The replay drives MarketLoop without an ExecutionManager on purpose, so its per-decision
    # "execution skipped: manager unavailable" warning is expected noise (same as backtest_replay.main).
    # In the agent process nothing configures logging, so it flooded the owner's console (2026-10-03).
    # Errors still surface; the level is restored afterwards. This runs in the agent process, never in Atlas.
    loop_log = logging.getLogger("AtlasAI.MarketLoop")
    level = loop_log.level
    loop_log.setLevel(logging.ERROR)
    try:
        result = replay(data, step=15, sleeves=True, slippage_bps=SLIPPAGE_BPS, record_signals=True)
    finally:
        loop_log.setLevel(level)
    lo =datetime.fromtimestamp(day_ms / 1000, UTC).isoformat()
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
    return _compare(older, newer)


def _newer_p(b: dict) -> float:
    """Out-of-sample (newer half) win-rate p-value on INDEPENDENT outcomes when known."""
    if b.get("net_240m_win") is None:
        return 1.0
    n = int(b.get("n_eff") or b["n"])
    return binom_two_sided_p(round(b["net_240m_win"] * n), n)


def _compare(older: dict, newer: dict) -> list[dict]:
    """Walk-forward candidates, then a false-discovery filter across EVERY group tested.

    Many (action, regime, band) groups are tested at once; some look consistent by luck.
    Each group's newer-half win rate gets a binomial p-value and all of them a
    Benjamini-Hochberg correction; a candidate must have q <= FDR_Q.
    """
    tested, out = [], []
    for key, a in sorted(older.items()):
        b = newer.get(key)
        if not b or a["verdict"] != "MEASURED" or b["verdict"] != "MEASURED":
            continue
        if a["net_240m_avg_pct"] is None or b["net_240m_avg_pct"] is None:
            continue
        if min(a.get("n_eff", MIN_EFF), b.get("n_eff", MIN_EFF)) < MIN_EFF:
            continue  # overlapping decisions: too few independent outcomes in a half
        tested.append((key, a, b))
    qs = bh_qvalues([_newer_p(b) for _, _, b in tested])
    for (key, a, b), q in zip(tested, qs):
        if (a["net_240m_avg_pct"] > 0) != (b["net_240m_avg_pct"] > 0) or q > FDR_Q:
            continue
        out.append({"action": key[0], "regime": key[1], "confidence": key[2], "n_older": a["n"], "n_newer": b["n"],
                    "avg240_older_pct": a["net_240m_avg_pct"], "avg240_newer_pct": b["net_240m_avg_pct"],
                    "win240_older": a["net_240m_win"], "win240_newer": b["net_240m_win"],
                    "n_eff_older": a.get("n_eff"), "n_eff_newer": b.get("n_eff"),
                    "q_newer": round(q, 4), "tested_groups": len(tested)})
    return out


def stream_groups(path: Path, split_iso: str, key_fn: Callable[[dict], tuple] | None = None) -> tuple[dict, dict, int]:
    """Row-by-row 240m aggregates per (action, regime, band) for rows before / from split_iso.

    The experience file grows to millions of rows (20 coins x 730 days); it is never loaded whole.
    Group fields match tools.lesson_book.build (n, verdict, net_240m_win, net_240m_avg_pct).
    """
    from decimal import Decimal

    from tools import lesson_book as lb

    slip = Decimal(SLIPPAGE_BPS) / Decimal(10000)
    acc: tuple[dict, dict] = ({}, {})
    buckets: tuple[dict, dict] = ({}, {})  # (key, symbol) -> 240-minute buckets with a decision
    total = 0
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            total += 1
            key = key_fn(r) if key_fn else (r["action"], r.get("regime") or "UNKNOWN", lb.band(r["confidence"]))
            if key is None:
                continue
            side = 0 if r["time"] < split_iso else 1
            g = acc[side].setdefault(key, [0, 0, 0, Decimal(0)])  # n, k, wins, sum
            g[0] += 1
            buckets[side].setdefault((key, r.get("symbol", "")), set()).add(_bucket240(r["time"]))
            v = lb._value(r, 240, r["action"], slip, None)
            if v is not None:
                g[1] += 1
                g[2] += (v > 0) == (r["action"] == "BUY")
                g[3] += v
    out = tuple({key: {"n": n, "verdict": "MEASURED" if n >= lb.MIN_SAMPLES else "INSUFFICIENT",
                       "net_240m_win": round(w / k, 3) if k else None,
                       "net_240m_avg_pct": round(float(s / k) * 100, 3) if k else None}
                 for key, (n, k, w, s) in half.items()} for half in acc)
    for side in (0, 1):
        for (key, _symbol), seen in buckets[side].items():
            out[side][key]["n_eff"] = out[side][key].get("n_eff", 0) + _non_overlapping(seen)
    return out[0], out[1], total


def _bucket240(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp()) // (240 * 60)


def _non_overlapping(buckets: set[int]) -> int:
    """Effective sample size (mlfinlab's sample-uniqueness idea, conservative form).

    Decisions 15 minutes apart share most of their 240-minute outcome, so they are not
    independent evidence. Greedily keep buckets at least two apart: kept decisions are
    then >= 240 minutes apart and their outcome windows never overlap.
    """
    kept, last = 0, None
    for b in sorted(buckets):
        if last is None or b - last >= 2:
            kept, last = kept + 1, b
    return kept


def stream_candidates(path: Path, split_iso: str) -> tuple[list[dict], int]:
    """Walk-forward candidates split at a point in time, streamed; also the total decision count."""
    older, newer, total = stream_groups(path, split_iso)
    return _compare(older, newer), total


def _lesson_key(c: dict) -> str:
    sign = "POS" if c["avg240_newer_pct"] > 0 else "NEG"
    return "-".join(str(x).replace("-", "_").replace(" ", "_") for x in (c["action"], c["regime"], c["confidence"], sign))


def update_streaks(previous: dict[str, int], lessons: list[dict]) -> dict[str, int]:
    """Consecutive replayed days each candidate (same direction) has held; a missing day resets it."""
    return {k: previous.get(k, 0) + 1 for k in {_lesson_key(c) for c in lessons}}


def _open_draft_keys(records_dir: Path) -> set[str]:
    from atlas_org import proposals as P
    from tools import atlas_org_cli as cli

    path = records_dir / cli.PROPOSALS_LOG
    if not path.exists():
        return set()
    state = P.replay(cli.read_log(path))
    return {pid.split(".")[0].removeprefix(PROPOSAL_PREFIX) for pid, p in state.items()
            if pid.startswith(PROPOSAL_PREFIX) and p.status not in P.TERMINAL}


def draft_proposals(records_dir: Path, lessons: list[dict], streaks: dict[str, int]) -> list[str]:
    """Owner 2026-10-02 option 3: a lesson stable for STABLE_RUNS days becomes a proposal DRAFT (CREATE only).

    Nothing is applied: the owner reviews, approves or rejects it through the normal proposal flow.
    """
    from tools import atlas_org_cli as cli

    ready = [c for c in lessons if streaks.get(_lesson_key(c), 0) >= STABLE_RUNS]
    if not ready:
        return []
    open_keys = _open_draft_keys(records_dir)
    filed = []
    for c in ready:
        key = _lesson_key(c)
        if key in open_keys:
            continue
        direction = "kazandırdı" if c["avg240_newer_pct"] > 0 else "kaybettirdi"
        pid = f"{PROPOSAL_PREFIX}{key}.1"
        cli.add_proposal_event(records_dir, proposal_id=pid, event="CREATE", actor="experiment_manager", payload={
            "title": f"Deneyim dersi: {c['action']} / {c['regime']} / güven {c['confidence']} 4 saatte tutarlı biçimde {direction}",
            "problem": f"{streaks[key]} ardışık günde iki yarıda da ölçüldü (n {c['n_older']}/{c['n_newer']}); "
                       f"4s ortalama %{c['avg240_older_pct']} / %{c['avg240_newer_pct']}.",
            "motivation": "Geçmişin tekrar oynatılmasından çıkan, iki zaman yarısında da aynı yönü gösteren ders.",
            "proposed_changes": "Adım 1 (çalışma zamanı değişikliği yok): sahip dersi inceler; gerekirse ayrı bir "
                                "öneriyle eşik veya kova değişikliği tasarlanır, test ve denetimden geçer.",
            "affected_components": ["tools/experience_agent.py (kanıt)", "değişiklik yok (adım 1)"],
            "risk_level": "HIGH",
            "rollback_plan": "Adım 1 hiçbir şeyi değiştirmez; öneri reddedilerek kapatılır.",
            "claims": [{"claim": f"{c['action']} kararları bu rejim ve güven bandında 4 saatte tutarlı biçimde {direction}.",
                        "evidence": f"walk-forward iki yarı: n {c['n_older']}/{c['n_newer']}, "
                                    f"kazanma {c['win240_older']}/{c['win240_newer']}",
                        "counter_evidence": "makro/duygu verisi çevrimdışı yok; 15 dakikalık kararlar örtüşür "
                                            "(bağımsız değil); geçmiş başarı geleceği garanti etmez."}],
        })
        filed.append(pid)
    return filed


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
    daily = state.get("daily") if isinstance(state.get("daily"), dict) else {}
    daily[datetime.fromtimestamp(day_ms / 1000, UTC).date().isoformat()] = len(signals)  # read by the research chart
    state["daily"] = dict(sorted(daily.items())[-(MAX_DAYS_BACK + 30):])
    mid_ms = (state["oldest_day_ms"] + state["newest_day_ms"] + DAY_MS) // 2  # time midpoint of the experience
    lessons, n_rows = stream_candidates(signals_path, datetime.fromtimestamp(mid_ms / 1000, UTC).isoformat())
    fingerprint = sorted([c["action"], c["regime"], c["confidence"], c["avg240_newer_pct"] > 0] for c in lessons)  # lists: JSON round-trips them
    changed = fingerprint != state.get("lesson_fingerprint", [])
    state["lesson_fingerprint"] = fingerprint
    state["decisions"] = n_rows  # read by observability/experience_view.py (the panel never parses the CSV)
    state["candidate_lessons"] = lessons[:40]
    state["lesson_streaks"] = update_streaks(state.get("lesson_streaks", {}), lessons)
    state["updated_at"] = datetime.fromtimestamp(now_ms / 1000, UTC).isoformat()
    state_path.write_text(json.dumps(state), encoding="utf-8")
    day = datetime.fromtimestamp(day_ms / 1000, UTC).date().isoformat()
    summary = f"{day} ({direction}) işlendi: {len(signals)} karar; toplam {state['days']} gün, {n_rows} karar; aday ders {len(lessons)}"
    if changed:
        existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)} if (records_dir / cli.MEMORY_LOG).exists() else set()
        cli.add_memory_record(records_dir, {
            "record_id": f"XP-{len(existing) + 1:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
            "title": f"Deneyim: {state['days']} gün, {n_rows} karar, {len(lessons)} aday ders (kural değil)",
            "body": json.dumps({"days": state["days"], "decisions": n_rows, "candidate_lessons": lessons[:40],
                                "method": "walk-forward halves; MEASURED in both; same 240m direction",
                                "caveat": "macro/sentiment excluded offline; overlapping 15-min decisions"},
                               ensure_ascii=False),
            "author": "experiment_manager", "source": "tools/experience_agent.py (backtest_replay + lesson_book)"})
    drafted = draft_proposals(records_dir, lessons, state["lesson_streaks"])
    if drafted:
        summary += f"; öneri taslağı (sahip onayı gerekir): {', '.join(drafted)}"
    return {"verdict": "OK", "summary": summary}
