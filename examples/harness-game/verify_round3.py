#!/usr/bin/env python3
"""
Ladder rung 5 — R3 EXPLOIT-HUNTER. Random/heuristic walks that assert the SAME
invariants (invariants.py) after every step, across multiple seeded episodes,
plus a same-seed replay-determinism check. This is the robustness tier: it asks
"does the game break?", needs no reward engineering, and treats a failed check as
DATA (a finding), not noise.

Run from the repo root:
    python3 examples/harness-game/verify_round3.py
"""
from __future__ import annotations

import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from ugt.core.trial import GateRunner, first_divergence  # noqa: E402
from ugt.core.exploit_hunter import ExploitHunter  # noqa: E402
from harness_adapter import HarnessAdapter  # noqa: E402
from invariants import build_invariant_suite  # noqa: E402
from engine import ACTIONS  # noqa: E402


def replay_stream(seed: str, actions: list[int]) -> list[str]:
    """Feed a fixed action script to a fresh adapter; return its hash stream."""
    a = HarnessAdapter(seed=seed)
    a.connect()
    a.reset()
    for act in actions:
        a.step(act)
    stream = a.hash_stream
    a.close()
    return stream


def main() -> int:
    print("R3 — Foraging Run exploit-hunter + determinism\n")
    gate = GateRunner()
    suite = build_invariant_suite()

    # ── Exploit-hunter: random walk, invariants after every step ─────────────
    adapter = HarnessAdapter(seed="r3")
    adapter.connect()
    hunter = ExploitHunter(
        adapter,
        invariants=suite.to_hunter_invariants(),
        action_ids=list(ACTIONS.keys()),
        action_names=ACTIONS,
        seed=1234,
    )
    report = hunter.run(episodes=8, steps_per_episode=40)
    adapter.close()

    print()
    gate.ck("hunter completed every episode", report.episodes == 8,
            f"{report.episodes}/8")
    gate.ck("zero invariant violations / crashes across the whole hunt",
            not report.findings,
            f"{len(report.findings)} finding(s): "
            + "; ".join(f.name for f in report.findings[:3]))
    gate.ck("every action was exercised at least once",
            set(report.action_counts) == set(ACTIONS.values()),
            f"missing={sorted(set(ACTIONS.values()) - set(report.action_counts))}")
    for f in report.findings:  # a finding is DATA — surface each one
        gate.finding(f"{f.name}: {f.message} (action={f.action_name}, ep{f.episode} step{f.step})")

    # ── Determinism: a same-seed replay must be byte-identical ───────────────
    rng = random.Random(42)
    script = [rng.choice(list(ACTIONS.keys())) for _ in range(30)]
    a1 = replay_stream("replay", script)
    a2 = replay_stream("replay", script)
    div = first_divergence(a1, a2)
    gate.ck("same-seed replay is byte-identical (no divergence)",
            div is None and len(a1) == len(a2),
            f"first divergence at index {div}")
    b = replay_stream("replay-other", script)
    gate.ck("a different seed diverges (the check can actually fail)", a1 != b)

    return gate.finish("R3", "No invariant broke under random pressure; replay is deterministic.")


if __name__ == "__main__":
    sys.exit(main())
