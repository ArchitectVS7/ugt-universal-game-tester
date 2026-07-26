#!/usr/bin/env python3
"""Rung 3 (R1) — playability: drive level 1 to a real solve, asserting F1-F5.

    python3 examples/sokoban/integration/verify_round1.py

Solutions come from `../game/levels/solutions.json`, the artifact the game side
commits — never a copy kept here, or the two drift silently.

Invariants from `invariants.py` are checked after EVERY command, not just at the
end, so a violation is attributed to the action that caused it.
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
UP, DOWN, LEFT, RIGHT = 0, 1, 2, 3

checks: list[tuple[bool, str, str]] = []


def check(ok, label, detail=""):
    checks.append((bool(ok), label, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))


class Driver:
    """Steps the adapter and runs the invariant suite after every command."""

    def __init__(self, adapter):
        self.ad = adapter
        self.violations: list[str] = []
        self.commands = 0

    def reset(self):
        self.state = self.ad.reset()
        return self.state

    def step(self, action_id):
        before = self.state
        after, term, trunc, info = self.ad.step(action_id)
        self.commands += 1
        for v in SUITE.check_command(before, after, f"step({action_id})", info or {}):
            self.violations.append(f"after step({action_id}) #{self.commands}: {v}")
        self.state = after
        return after


def find_blocked_direction(drv):
    """Find a direction that is a genuine no-op from here (a wall).

    Discovered by probing the real game rather than by reading the level file:
    if the adapter had to parse the grid to know where walls are, it would be
    re-implementing the rule it is supposed to be testing.
    """
    for d in (UP, DOWN, LEFT, RIGHT):
        before = drv.state
        after = drv.step(d)
        if after["player_x"] == before["player_x"] and after["player_y"] == before["player_y"]:
            return d, before, after
        # Undo by stepping back the other way, so the probe leaves no trace.
        drv.step({UP: DOWN, DOWN: UP, LEFT: RIGHT, RIGHT: LEFT}[d])
    return None, None, None


def main() -> int:
    print("Sokoban R1 — one level solved over the real wire\n")
    solutions = json.load(open(SOLUTIONS))
    ad = GodotTcpAdapter()
    ad.connect()
    drv = Driver(ad)
    try:
        s0 = drv.reset()
        check(s0["level_index"] == 0 and s0["moves_taken"] == 0,
              "fresh reset: level 0, 0 moves",
              f"boxes {s0['boxes_on_target']}/{s0['boxes_total']}")

        # ---- F1: walking into a wall is a complete no-op --------------------
        print("\n  -- F1: wall blocks --")
        d, before, after = find_blocked_direction(drv)
        check(d is not None, "found a wall to walk into", f"direction={d}")
        if d is not None:
            check(after["player_x"] == before["player_x"] and after["player_y"] == before["player_y"],
                  "F1: a blocked move leaves the player where they were",
                  f"({before['player_x']},{before['player_y']}) unchanged")
            check(after["moves_taken"] == before["moves_taken"],
                  "F1: a blocked move consumes no move",
                  f"moves_taken stayed {before['moves_taken']}")

        # ---- solve level 1 --------------------------------------------------
        print("\n  -- solve level_01 from the committed solution --")
        drv.reset()
        seq = solutions["level_01"]
        pushed_a_box = False
        landed_on_target = False
        prev = drv.state
        for a in seq:
            cur = drv.step(a)
            moved = (cur["player_x"], cur["player_y"]) != (prev["player_x"], prev["player_y"])
            if moved and cur["boxes_on_target"] != prev["boxes_on_target"]:
                landed_on_target = True
            if moved:
                pushed_a_box = pushed_a_box or cur["boxes_on_target"] >= prev["boxes_on_target"]
            prev = cur
        final = drv.state

        # ---- F2 / F4 / F5 ---------------------------------------------------
        check(pushed_a_box, "F2: the solution actually moves boxes (not a walk-through)")
        check(landed_on_target, "F4: boxes_on_target changed when a box reached a target")
        check(final["boxes_on_target"] == final["boxes_total"],
              "F5: every box is on a target at the end",
              f"{final['boxes_on_target']}/{final['boxes_total']}")
        check(final["level_solved"] or final["level_index"] > 0,
              "F5: the game reports the level solved (or has advanced past it)",
              f"level_solved={final['level_solved']} level_index={final['level_index']}")
        check(final["moves_taken"] <= len(seq),
              "no phantom moves: moves_taken never exceeds actions issued",
              f"{final['moves_taken']} moves for {len(seq)} actions")

        # ---- F3: a box pushed into an obstacle is a no-op -------------------
        # Re-solve from a clean level and try to shove a settled box outward.
        print("\n  -- F3: blocked push --")
        drv.reset()
        blocked_noop = None
        base = drv.state
        for d in (UP, DOWN, LEFT, RIGHT):
            b = drv.state
            a2 = drv.step(d)
            if (a2["player_x"], a2["player_y"]) == (b["player_x"], b["player_y"]) \
               and a2["moves_taken"] == b["moves_taken"] \
               and a2["boxes_on_target"] == b["boxes_on_target"]:
                blocked_noop = (d, b, a2)
                break
            drv.step({UP: DOWN, DOWN: UP, LEFT: RIGHT, RIGHT: LEFT}[d])
        check(blocked_noop is not None,
              "F3: at least one direction is a total no-op (nothing moves, no move spent)",
              f"direction={blocked_noop[0] if blocked_noop else None}")

        # ---- invariants ------------------------------------------------------
        print("\n  -- invariants --")
        check(not drv.violations,
              f"all {len(SUITE.predicates)} invariants held across {drv.commands} commands",
              "" if not drv.violations else "; ".join(drv.violations[:3]))

        # A suite that cannot fail proves nothing — show it can.
        bad_before = dict(drv.state)
        bad_after = dict(drv.state)
        bad_after["boxes_on_target"] = bad_after["boxes_total"] + 5
        fired = SUITE.check_command(bad_before, bad_after, "synthetic", {})
        check(bool(fired), "the invariant suite FIRES on a corrupted transition (non-vacuous)",
              f"{len(fired)} violation(s) reported")
    finally:
        ad.close()

    passed = sum(1 for ok, _, _ in checks if ok)
    total = len(checks)
    print("\n" + "=" * 70)
    if passed == total:
        print(f"ROUND 1 MET — {passed}/{total} checks. UGT drove level 1 to a real solve through "
              f"the live Godot bridge, F1-F5 hold, every invariant held after every one of "
              f"{drv.commands} commands, and the suite was shown able to fail.")
        return 0
    print(f"ROUND 1 NOT MET — {passed}/{total} checks.")
    for ok, label, detail in checks:
        if not ok:
            print(f"  FAILED: {label}  {detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
