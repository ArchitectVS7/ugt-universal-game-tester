#!/usr/bin/env python3
"""
Ladder rung 3 — R1 PLAYABILITY. Drive one full loop of the core game to a REAL
outcome (a win), checking every invariant after every command, and prove the loop
is same-seed reproducible.

Run from the repo root:
    python3 examples/harness-game/verify_round1.py
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from ugt.core.trial import GateRunner  # noqa: E402
from harness_adapter import HarnessAdapter  # noqa: E402
from invariants import build_invariant_suite  # noqa: E402
from engine import DEST  # constant only — R1 reads it, it doesn't re-implement rules

# Action ids (see engine.ACTIONS)
WAIT, FORAGE, REST, TRAVEL, TRADE, END_DAY = 0, 1, 2, 3, 4, 5


def survival_policy(state: dict) -> int:
    """A competent-but-simple courier: stay healthy, keep supplies, push forward."""
    if state["hp"] <= 4 and state["supplies"] >= 1:
        return REST
    if state["supplies"] < 2:
        return TRADE if state["coins"] >= 2 else FORAGE
    if state["location"] < DEST:
        return TRAVEL
    return WAIT


def play_once(seed: str, suite, max_steps: int = 80):
    """Drive the policy to a terminal state; return (final_state, violations, hashes)."""
    adapter = HarnessAdapter(seed=seed)
    adapter.connect()
    state = adapter.reset()
    violations: list[str] = []
    try:
        for _ in range(max_steps):
            if state["won"] or state["lost"]:
                break
            before = state
            action = survival_policy(before)
            state, term, _trunc, info = adapter.step(action)
            violations += [f"[{info['action']}] {v}"
                           for v in suite.check_command(before, state,
                                                        info["command"], info["result"])]
            if term:
                break
    finally:
        hashes = adapter.hash_stream
        adapter.close()
    return state, violations, hashes


def main() -> int:
    print("R1 — Foraging Run playability (one full loop under invariants)\n")
    gate = GateRunner()
    suite = build_invariant_suite()

    final, violations, hashes = play_once("r1", suite)

    gate.ck("the loop reached a terminal outcome", final["won"] or final["lost"],
            f"day={final['day']} loc={final['location']} hp={final['hp']}")
    gate.ck("that outcome is a WIN (a real success path exists)", final["won"],
            final["log"])
    gate.ck("the loop was a real play-through, not a no-op",
            len(hashes) >= 6, f"{len(hashes)} states")
    gate.ck("zero invariant violations across the whole loop",
            not violations, "; ".join(violations[:3]))

    # Same-seed reproducibility — the whole run replays byte-identical.
    _f2, _v2, hashes2 = play_once("r1", suite)
    gate.ck("same-seed replay is byte-identical", hashes == hashes2,
            f"len {len(hashes)} vs {len(hashes2)}")

    return gate.finish("R1", "Core loop is playable, winnable, and reproducible.")


if __name__ == "__main__":
    sys.exit(main())
