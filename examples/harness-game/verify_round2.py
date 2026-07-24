#!/usr/bin/env python3
"""
Ladder rung 4 — R2 FULL SPINE. Every action and every terminal outcome driven to
a REAL result under the same invariants: a win path, a loss path, and coverage of
all six actions. The denominator is disclosed honestly — no vacuous passes.

Run from the repo root:
    python3 examples/harness-game/verify_round2.py
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
from engine import ACTIONS  # noqa: E402
from verify_round1 import survival_policy  # reuse the winning policy  # noqa: E402

WAIT, FORAGE, REST, TRAVEL, TRADE, END_DAY = 0, 1, 2, 3, 4, 5


def drive(seed, suite, choose, exercised, max_steps=120):
    """Run `choose(state)->action_id` to terminal; collect violations + coverage."""
    adapter = HarnessAdapter(seed=seed)
    adapter.connect()
    state = adapter.reset()
    violations = []
    try:
        for _ in range(max_steps):
            if state["won"] or state["lost"]:
                break
            before = state
            action = choose(before)
            state, term, _t, info = adapter.step(action)
            exercised.add(info["action"])
            violations += [f"[{info['action']}] {v}"
                           for v in suite.check_command(before, state,
                                                        info["command"], info["result"])]
            if term:
                break
    finally:
        adapter.close()
    return state, violations


def main() -> int:
    print("R2 — Foraging Run full spine (every action + every outcome)\n")
    gate = GateRunner()
    suite = build_invariant_suite()
    exercised: set[str] = set()
    all_violations: list[str] = []

    # ── 1. WIN path ──────────────────────────────────────────────────────────
    win_state, v = drive("r2-win", suite, survival_policy, exercised)
    all_violations += v
    gate.ck("win path reaches a real WIN", win_state["won"], win_state["log"])

    # ── 2. LOSS path — do nothing but burn days until it ends badly ───────────
    loss_state, v = drive("r2-loss", suite, lambda s: END_DAY, exercised)
    all_violations += v
    gate.ck("loss path reaches a real LOSS", loss_state["lost"], loss_state["log"])

    # ── 3. Coverage — a fixed script that exercises the remaining actions ─────
    coverage_script = [WAIT, FORAGE, TRADE, REST, TRAVEL, END_DAY]
    idx = {"i": 0}

    def scripted(_state):
        a = coverage_script[min(idx["i"], len(coverage_script) - 1)]
        idx["i"] += 1
        return a

    _cov_state, v = drive("r2-cover", suite, scripted, exercised, max_steps=len(coverage_script))
    all_violations += v

    every = {ACTIONS[i] for i in ACTIONS}
    gate.ck("every action was exercised to a real outcome", exercised == every,
            f"missing={sorted(every - exercised)}")

    # ── 4. Invariants held across the entire spine ───────────────────────────
    gate.ck("zero invariant violations across all spine runs",
            not all_violations, "; ".join(all_violations[:3]))

    return gate.finish("R2", "Both outcomes reachable; every action exercised under invariants.")


if __name__ == "__main__":
    sys.exit(main())
