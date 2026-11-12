"""T-0001 (2026-10-02): fuse() was split into helpers with NO behaviour change.

A seeded corpus of 4000 inputs (missing agents, unknown names, malformed and
out-of-range scores, NaN, booleans, non-dict entries, both denominator modes)
(plus inf, -0.0, tie values and non-dict inputs, outcomes incl. exceptions) was run through the pre-refactor fuse() and the sha256 of every result was
pinned here. The refactored fuse() must reproduce it exactly.
"""

import hashlib
import json
import random

from ai.core.intelligence.agent_fusion import AgentFusion

PINNED_SHA256 = "a05bd951c73b0adcc49ece019bffc8e8cfa367fc436742c8dd3bd32b521499df"

SPECIALS = [0, 1, 0.0, 1.0, 0.5, 0.6, 0.4, 0.25, 0.75, -0.1, 1.2, -0.0, 1e-9, 1 - 1e-9,
            float("inf"), float("nan"), True, None, "0.7"]


def _corpus():
    rng = random.Random(20261002)
    names = list(AgentFusion.WEIGHTS) + ["unknown_agent"]
    for i in range(4000):
        if i % 97 == 0:
            yield rng.choice([None, [], "s"]), i % 2 == 1  # non-dict input: the exception is part of the contract
            continue
        signals = {}
        for name in rng.sample(names, rng.randint(0, len(names))):
            if rng.random() < 0.05:
                signals[name] = "not-a-dict"
                continue
            score = rng.choice(SPECIALS) if rng.random() < 0.15 else round(rng.random(), rng.choice([2, 3, 6]))
            signals[name] = {"score": score, "action": rng.choice(["BUY", "SELL", "HOLD", "WAIT"])}
        yield signals, i % 2 == 1


def _digest():
    h = hashlib.sha256()
    for signals, full in _corpus():
        fusion = AgentFusion()
        fusion.full_weight_denominator = full
        try:
            r = fusion.fuse(signals)
        except Exception as exc:  # noqa: BLE001 - the outcome, including its type, is what is pinned
            h.update(f"EXC:{type(exc).__name__}".encode())
            continue
        h.update(json.dumps([r.action, repr(r.confidence), sorted(r.scores.items()), r.reason]).encode())
    return h.hexdigest()


def test_fuse_output_is_identical_to_pre_refactor_behaviour():
    assert _digest() == PINNED_SHA256
