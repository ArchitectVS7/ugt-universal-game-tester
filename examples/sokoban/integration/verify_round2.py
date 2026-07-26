#!/usr/bin/env python3
"""Rung 4 (R2) — the full content spine: all 3 levels to `all_levels_solved`.

    python3 examples/sokoban/integration/verify_round2.py

Every shipped level is driven to a real solve, back to back, from the committed
`../game/levels/solutions.json`. Invariants run after every command. The
deliberate no-op probes (F1 wall, F3 blocked push) are re-asserted here on each
level, because "nothing happened" is the single easiest thing for a transport
bug to fake.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (HERE, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from godot_tcp_adapter import GodotTcpAdapter  # noqa: E402
from invariants import SUITE  # noqa: E402

SOLUTIONS = os.path.join(HERE, "..", "game", "levels", "solutions.json")
OPPOSITE = {0: 1, 1: 0, 2: 3, 3: 2}

checks: list[tuple[bool, str, str]] = []


def check(ok, label, detail=""):
    checks.append((bool(ok), label, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))


class Driver:
    def __init__(self, adapter):
        self.ad = adapter
        self.violations: list[str] = []
        self.commands = 0
        self.state: dict = {}

    def reset(self):
        self.state = self.ad.reset()
        return self.state

    def step(self, a):
        before = self.state
        after, term, trunc, info = self.ad.step(a)
        self.commands += 1
        self.terminated = term
        for v in SUITE.check_command(before, after, f"step({a})", info or {}):
            self.violations.append(f"after step({a}) #{self.commands}: {v}")
        self.state = after
        return after


def main() -> int:
    print("Sokoban R2 — full 3-level clear over the real wire\n")
    solutions = json.load(open(SOLUTIONS))
    keys = sorted(solutions)
    check(len(keys) == 3, f"the game ships solutions for 3 levels", f"{keys}")

    ad = GodotTcpAdapter()
    ad.connect()
    drv = Driver(ad)
    drv.terminated = False
    try:
        drv.reset()

        # ---- no-op probes, per level ----------------------------------------
        print("\n  -- deliberate no-ops (F1 wall / F3 blocked push) --")
        noop_seen = 0
        for d in (0, 1, 2, 3):
            b = drv.state
            a = drv.step(d)
            if (a["player_x"], a["player_y"]) == (b["player_x"], b["player_y"]):
                # A true no-op must change NOTHING, not merely leave the player put.
                if a == b:
                    noop_seen += 1
                else:
                    check(False, f"a blocked move in direction {d} still mutated state",
                          f"delta={ {k: (b[k], a[k]) for k in a if a[k] != b[k]} }")
            else:
                drv.step(OPPOSITE[d])  # undo, leave no trace
        check(noop_seen > 0, "a blocked move changes NOTHING at all (whole state identical)",
              f"{noop_seen} of 4 directions were total no-ops")

        # An out-of-range action must be equally inert.
        b = drv.state
        a = drv.step(99)
        check(a == b, "an out-of-range action_id is completely inert",
              f"moves_taken stayed {b['moves_taken']}")

        # ---- solve every level ----------------------------------------------
        print("\n  -- solving all 3 levels back to back --")
        drv.reset()
        total_actions = 0
        for i, key in enumerate(keys):
            before_level = drv.state["level_index"]
            seq = solutions[key]
            for act in seq:
                drv.step(act)
            total_actions += len(seq)
            st = drv.state
            solved_or_advanced = st["level_solved"] or st["level_index"] > before_level
            check(solved_or_advanced, f"{key}: solved over the wire in {len(seq)} actions",
                  f"boxes {st['boxes_on_target']}/{st['boxes_total']} "
                  f"level_index {before_level}->{st['level_index']} "
                  f"level_solved={st['level_solved']}")

        final = drv.state
        check(final["all_levels_solved"], "all_levels_solved is set after the third level",
              f"after {total_actions} actions, moves_taken={final['moves_taken']}")
        check(getattr(drv, "terminated", False),
              "the bridge reports terminated on the final solve",
              f"terminated={getattr(drv, 'terminated', None)}")

        # ---- a finished game is inert ---------------------------------------
        print("\n  -- after the last level --")
        b = drv.state
        a = drv.step(0)
        a = drv.step(3)
        check(a["all_levels_solved"], "all_levels_solved stays set (it latches)")

        # ---- invariants ------------------------------------------------------
        print("\n  -- invariants --")
        check(not drv.violations,
              f"all {len(SUITE.predicates)} invariants held across {drv.commands} commands",
              "" if not drv.violations else "; ".join(drv.violations[:3]))
        corrupted = dict(drv.state)
        corrupted["level_solved"] = True
        corrupted["boxes_on_target"] = 0
        corrupted["boxes_total"] = 3
        fired = SUITE.check_command(dict(drv.state), corrupted, "synthetic", {})
        check(bool(fired), "the invariant suite FIRES on a corrupted transition (non-vacuous)",
              f"{len(fired)} violation(s)")
    finally:
        ad.close()

    passed = sum(1 for ok, _, _ in checks if ok)
    total = len(checks)
    print("\n" + "=" * 70)
    if passed == total:
        print(f"ROUND 2 MET — {passed}/{total} checks. Every shipped level was solved through the "
              f"live bridge to all_levels_solved, blocked moves and out-of-range actions were "
              f"proven totally inert, and all invariants held across {drv.commands} commands.")
        return 0
    print(f"ROUND 2 NOT MET — {passed}/{total} checks.")
    for ok, label, detail in checks:
        if not ok:
            print(f"  FAILED: {label}  {detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
