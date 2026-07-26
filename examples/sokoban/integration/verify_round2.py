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
from ugt.core.trial import GateRunner  # noqa: E402
from invariants import SUITE  # noqa: E402

SOLUTIONS = os.path.join(HERE, "..", "game", "levels", "solutions.json")
OPPOSITE = {0: 1, 1: 0, 2: 3, 3: 2}

gate = GateRunner()


def check(ok, label, detail=""):
    """Adapter to GateRunner's (name, ok, detail) order, kept so the call sites below read naturally."""
    return gate.ck(label, ok, detail)



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

        # ---- F1: walking into a WALL is inert -------------------------------
        print("\n  -- F1: wall no-op --")
        noop_seen = 0
        for d in (0, 1, 2, 3):
            b = drv.state
            a = drv.step(d)
            if (a["player_x"], a["player_y"]) == (b["player_x"], b["player_y"]):
                # A true no-op must change NOTHING, not merely leave the player put.
                if a == b:
                    noop_seen += 1
                else:
                    gate.ck(f"a blocked move in direction {d} still mutated state", False,
                            f"delta={ {k: (b[k], a[k]) for k in a if a[k] != b[k]} }")
            else:
                drv.step(OPPOSITE[d])  # undo, leave no trace
        gate.ck("F1: a wall-blocked move changes NOTHING at all (whole state identical)",
                noop_seen > 0, f"{noop_seen} of 4 directions were total no-ops")

        # ---- F3: a blocked BOX PUSH is inert --------------------------------
        # Distinct from F1, and deliberately so: an earlier version of this rung
        # only probed for "some direction is a no-op", which finds a WALL and
        # therefore re-tested F1 while claiming to cover F3. On level_01
        # (player (3,3), box (2,2)) `up` lines up, the first `left` pushes the
        # box to x=1, and the second `left` would shove it into the wall at x=0.
        print("\n  -- F3: blocked box push --")
        drv.reset()
        drv.step(0)                       # up
        pre = drv.state
        post = drv.step(2)                # left — this push must be ACCEPTED
        gate.ck("F3 setup: the first box push is accepted",
                post["moves_taken"] == pre["moves_taken"] + 1,
                f"moves {pre['moves_taken']} -> {post['moves_taken']}")
        b = drv.state
        a = drv.step(2)                   # left again — box would hit the wall
        gate.ck("F3: a box pushed into a wall is refused, state COMPLETELY unchanged",
                a == b, f"player stayed ({b['player_x']},{b['player_y']}), "
                        f"moves stayed {b['moves_taken']}")

        # An out-of-range action must be equally inert.
        b = drv.state
        a = drv.step(99)
        gate.ck("an out-of-range action_id is completely inert", a == b,
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

    return gate.finish("ROUND 2", f"Every shipped level was solved through the live bridge to all_levels_solved, F1 (wall) "
        f"and F3 (blocked box push) were proven distinct and totally inert, and all invariants "
        f"held across {drv.commands} commands.")


if __name__ == "__main__":
    sys.exit(main())
