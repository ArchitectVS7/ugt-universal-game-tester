#!/usr/bin/env python3
"""Rung 3 (R1) — playability: drive level 1 to a real solve, asserting F1-F6.

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
from ugt.core.trial import GateRunner  # noqa: E402

SOLUTIONS = os.path.join(HERE, "..", "game", "levels", "solutions.json")
UP, DOWN, LEFT, RIGHT, RELOAD = 0, 1, 2, 3, 4

gate = GateRunner()


def box_cells(state: dict) -> set:
    """Box positions read straight off the player-facing grid ('$' or '*').

    Reading a render is not re-implementing a rule: the game drew the grid, we
    only look at it — the same thing a human player does.
    """
    return {(x, y) for y, row in enumerate(state["grid"])
            for x, ch in enumerate(row) if ch in "$*"}


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
        gate.ck("fresh reset: level 0, 0 moves",
                s0["level_index"] == 0 and s0["moves_taken"] == 0,
                f"boxes {s0['boxes_on_target']}/{s0['boxes_total']}")

        # ---- F1: walking into a wall is a complete no-op --------------------
        print("\n  -- F1: wall blocks --")
        d, before, after = find_blocked_direction(drv)
        gate.ck("found a wall to walk into", d is not None, f"direction={d}")
        if d is not None:
            gate.ck("F1: a blocked move leaves the player where they were",
                    after["player_x"] == before["player_x"] and after["player_y"] == before["player_y"],
                    f"({before['player_x']},{before['player_y']}) unchanged")
            gate.ck("F1: a blocked move consumes no move",
                    after["moves_taken"] == before["moves_taken"],
                    f"moves_taken stayed {before['moves_taken']}")

        # ---- F4: a box demonstrably reaches a TARGET -------------------------
        # boxes_on_target STRICTLY RISING is the evidence: that transition is
        # impossible unless a box entered a target. An earlier version of this
        # check accepted `>=`, which is true on any player move and therefore
        # could never fail — a vacuous green. (F2, "a box moves at all", is
        # proven separately below from the grid, which the wire now carries.)
        print("\n  -- solve level_01 from the committed solution --")
        drv.reset()
        seq = solutions["level_01"]
        rises = 0
        prev = drv.state
        for a in seq:
            cur = drv.step(a)
            if cur["boxes_on_target"] > prev["boxes_on_target"]:
                rises += 1
            prev = cur
        final = drv.state

        gate.ck("F4: boxes_on_target STRICTLY increased — a box provably moved onto a target",
                rises > 0, f"{rises} increase(s) across {len(seq)} actions")
        gate.ck("F5: every box is on a target at the end",
                final["boxes_on_target"] == final["boxes_total"],
                f"{final['boxes_on_target']}/{final['boxes_total']}")
        gate.ck("F5: the game reports the level solved",
                bool(final["level_solved"]),
                f"level_solved={final['level_solved']} level_index={final['level_index']}")
        gate.ck("no phantom moves: moves_taken never exceeds actions issued",
                final["moves_taken"] <= len(seq),
                f"{final['moves_taken']} moves for {len(seq)} actions")

        # ---- F3: a box pushed into a WALL is a no-op -------------------------
        # A genuine blocked BOX push, not another wall-walk. From the start on
        # level_01 (player (3,3), box (2,2)): `up` lines the player up, the first
        # `left` pushes the box to x=1, and the second `left` would drive it into
        # the wall at x=0 — which the game must refuse outright.
        # The previous version probed for "any direction that is a total no-op"
        # and found `down`, a WALL — i.e. it silently re-tested F1 and never
        # exercised a blocked push at all.
        print("\n  -- F3: blocked box push --")
        drv.reset()
        drv.step(UP)
        before_push = drv.state
        after_push = drv.step(LEFT)
        gate.ck("F3 setup: the first push is ACCEPTED (so the box really is against the wall next)",
                after_push["moves_taken"] == before_push["moves_taken"] + 1
                and (after_push["player_x"], after_push["player_y"])
                != (before_push["player_x"], before_push["player_y"]),
                f"player ({before_push['player_x']},{before_push['player_y']})"
                f" -> ({after_push['player_x']},{after_push['player_y']})")

        # F2 proper, now testable on its own: the accepted push above did not
        # cross a target, yet the grid shows the box in a NEW cell. Before the
        # wire carried the grid this was invisible — an R1 finding on every run
        # until the game added box positions to the state contract.
        gate.ck("F2: the grid shows the box in a new cell after the push, independent of any target",
                box_cells(after_push) != box_cells(before_push)
                and after_push["boxes_on_target"] == before_push["boxes_on_target"],
                f"box cells {sorted(box_cells(before_push))} -> {sorted(box_cells(after_push))}, "
                f"boxes_on_target stayed {after_push['boxes_on_target']}")
        blocked_before = drv.state
        blocked_after = drv.step(LEFT)
        gate.ck("F3: pushing that box into the wall is refused — state is COMPLETELY unchanged",
                blocked_after == blocked_before,
                f"player stayed ({blocked_before['player_x']},{blocked_before['player_y']}), "
                f"moves stayed {blocked_before['moves_taken']}")

        # ---- F6: reload (action 4) rewinds the level -------------------------
        # The box above is now wedged against the wall — exactly the situation
        # the PRD's "a player can always retry" exists for. Prove the machine
        # player has the same way out a human's R key gives.
        print("\n  -- F6: reload rescues a wedged position --")
        start = drv.reset()
        drv.step(UP)
        drv.step(LEFT)
        after_reload = drv.step(RELOAD)
        gate.ck("F6: action 4 returns the exact level-start state",
                after_reload == start,
                f"moves_taken back to {after_reload['moves_taken']}")

        # ---- invariants ------------------------------------------------------
        print("\n  -- invariants --")
        gate.ck(f"all {len(SUITE.predicates)} invariants held across {drv.commands} commands",
                not drv.violations,
                "" if not drv.violations else "; ".join(drv.violations[:3]))

        # A suite that cannot fail proves nothing — show it can.
        bad_before = dict(drv.state)
        bad_after = dict(drv.state)
        bad_after["boxes_on_target"] = bad_after["boxes_total"] + 5
        fired = SUITE.check_command(bad_before, bad_after, "synthetic", {})
        gate.ck("the invariant suite FIRES on a corrupted transition (non-vacuous)",
                bool(fired), f"{len(fired)} violation(s) reported")
    finally:
        ad.close()

    return gate.finish(
        "ROUND 1",
        f"UGT drove level 1 to a real solve through the live Godot bridge; F1 (wall), "
        f"F2 (a box move is visible in the grid on its own), F3 (a blocked BOX push is "
        f"refused), F4 (a box provably reached a target), F5 (solved) and F6 (reload "
        f"rescues a wedge) all hold, and every invariant held after every one of "
        f"{drv.commands} commands.",
    )


if __name__ == "__main__":
    sys.exit(main())
