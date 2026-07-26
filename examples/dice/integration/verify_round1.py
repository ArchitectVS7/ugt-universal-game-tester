#!/usr/bin/env python3
"""Rung 3 (R1) — playability: one full battle to a real terminal outcome.

    python3 examples/dice/integration/verify_round1.py

Drives a whole battle through the adapter, checking `invariants.py` after every
single round, and asserts the three bonus-dice rules individually rather than as
a lump sum — which is only possible because the game's PRD pinned down exactly
when each one fires.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (HERE, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from invariants import SUITE  # noqa: E402
from serve_process import adapter_for, served_bundle  # noqa: E402
from ugt.core.trial import GateRunner  # noqa: E402

ALL_ATTACK, ALL_DEFENSE = 0, 6
DEFAULT_SEED = "dice-duel"

gate = GateRunner()


class Driver:
    """Steps the adapter and runs the invariant suite after every action."""

    def __init__(self, adapter):
        self.ad = adapter
        self.violations: list[str] = []
        self.commands = 0
        self.state: dict = {}

    def seed(self, seed):
        """Start a battle on a chosen seed.

        A scripted rung can do this; the feature map cannot, because
        `engine.reset_command` is ignored for any game exposing __RESET_GAME__.
        """
        self.ad.page.evaluate(f"window.__RESET__({seed!r})")
        self.state = self.ad.page.evaluate("window.__GET_STATE__()")
        return self.state

    def step(self, action):
        before = self.state
        after, _t, _tr, info = self.ad.step(action)
        self.commands += 1
        for v in SUITE.check_command(before, after, f"step({action})", info or {}):
            self.violations.append(f"after step({action}) #{self.commands}: {v}")
        self.state = after
        return after


def main() -> int:
    print("Dice R1 — one full battle over the real page\n")

    with served_bundle() as port:
        ad = adapter_for(port)
        ad.connect()
        drv = Driver(ad)
        try:
            s0 = drv.seed(DEFAULT_SEED)
            gate.ck("fresh battle: round 0, 20 v 20, undecided",
                    s0["round_number"] == 0 and s0["battle_over"] is False
                    and s0["player"]["force_strength"] == 20
                    and s0["enemy"]["force_strength"] == 20)

            # ---- round 1: attack damages -------------------------------------
            print("\n  -- combat --")
            r1 = drv.step(ALL_ATTACK)
            gate.ck("an all-attack round reduces the enemy's force strength",
                    r1["enemy"]["force_strength"] < s0["enemy"]["force_strength"],
                    f"enemy {s0['enemy']['force_strength']} -> {r1['enemy']['force_strength']}")
            gate.ck("no bonus dice in round 1 (tied at 20, both above half, not round 3)",
                    r1["player"]["bonus_dice"] == 0 and r1["enemy"]["bonus_dice"] == 0)

            # ---- round 3: reinforcements, isolated ----------------------------
            print("\n  -- bonus dice, one rule at a time --")
            r2 = drv.step(ALL_ATTACK)
            pre3 = drv.state
            r3 = drv.step(ALL_ATTACK)
            gate.ck("Reinforcements fire on round 3",
                    r3["round_number"] == 3)
            # The side that is BEHIND and still above half can only have the +2,
            # so it isolates Reinforcements from Morale and Dug in.
            behind = "enemy" if pre3["enemy"]["force_strength"] < pre3["player"]["force_strength"] else "player"
            ahead = "player" if behind == "enemy" else "enemy"
            gate.ck(f"the trailing side ({behind}) shows exactly +2 — Reinforcements alone",
                    r3[behind]["bonus_dice"] == 2,
                    f"entering round 3 at {pre3[behind]['force_strength']} "
                    f"(behind, above half) -> bonus_dice={r3[behind]['bonus_dice']}")
            gate.ck(f"the leading side ({ahead}) shows +3 — Reinforcements STACKS with Morale",
                    r3[ahead]["bonus_dice"] == 3,
                    f"2 (reinforcements) + 1 (morale) = {r3[ahead]['bonus_dice']}")

            # ---- round 4: morale alone ---------------------------------------
            pre4 = drv.state
            r4 = drv.step(ALL_ATTACK)
            leader = "player" if pre4["player"]["force_strength"] > pre4["enemy"]["force_strength"] else "enemy"
            gate.ck(f"round 4, {leader} leads and is above half: exactly +1 for Morale",
                    r4[leader]["bonus_dice"] == 1,
                    "Reinforcements is spent, Dug in needs FS <= 10")

            # ---- run the battle out ------------------------------------------
            print("\n  -- to a terminal outcome --")
            dug_in_seen = False
            while not drv.state["battle_over"] and drv.state["round_number"] < 12:
                pre = drv.state
                cur = drv.step(ALL_ATTACK)
                for side in ("player", "enemy"):
                    if pre[side]["force_strength"] <= 10 and cur[side]["bonus_dice"] >= 1:
                        dug_in_seen = True
            final = drv.state
            gate.ck("the battle reached a real terminal state",
                    final["battle_over"] is True and final["winner"] is not None,
                    f"round {final['round_number']}, winner={final['winner']!r}, "
                    f"{final['player']['force_strength']} v {final['enemy']['force_strength']}")
            gate.ck("Dug in was observed (a side at or below half gained a defense die)",
                    dug_in_seen,
                    "the third bonus rule fired during the run-out")
            gate.ck("a concluded battle is inert",
                    drv.step(ALL_ATTACK) == final and drv.step(ALL_DEFENSE) == final,
                    "two further actions changed nothing")

            # ---- invariants ---------------------------------------------------
            print("\n  -- invariants --")
            gate.ck(f"all {len(SUITE.predicates)} invariants held across {drv.commands} rounds",
                    not drv.violations,
                    "" if not drv.violations else "; ".join(drv.violations[:3]))
            corrupt = {**final, "winner": "player", "battle_over": False}
            fired = SUITE.check_command(final, corrupt, "synthetic", {})
            gate.ck("the invariant suite FIRES on a corrupted transition (non-vacuous)",
                    bool(fired), f"{len(fired)} violation(s)")
        finally:
            ad.close()

    return gate.finish(
        "ROUND 1",
        f"UGT drove a complete battle through the real page to a terminal outcome, all three "
        f"bonus-dice rules were observed in isolation, and every invariant held after every "
        f"one of {drv.commands} rounds.",
    )


if __name__ == "__main__":
    sys.exit(main())
