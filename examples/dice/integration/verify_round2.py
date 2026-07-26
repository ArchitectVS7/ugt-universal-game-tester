#!/usr/bin/env python3
"""Rung 4 (R2) — full spine: every allocation, and BOTH terminal arms.

    python3 examples/dice/integration/verify_round2.py

R1 proved one battle works. R2 proves the whole content surface does:

  * all seven allocation presets actually resolve a round;
  * defense demonstrably beats attack for damage taken (a controlled A/B — the
    same claim the feature map could not make, because it compares two
    different battles);
  * BOTH ways a battle can end are reached for real — the round-12 draw, and a
    knockout to 0 force strength;
  * the knockout arm needs a specific seed, which is exactly what a scripted
    rung can do and `ugt verify` cannot.
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
PRESETS = list(range(7))
DEFAULT_SEED = "dice-duel"
KNOCKOUT_SEED = 0          # verified reachable in the spike; see README
MAX_ROUNDS = 12

gate = GateRunner()


class Driver:
    def __init__(self, adapter):
        self.ad = adapter
        self.violations: list[str] = []
        self.commands = 0
        self.state: dict = {}

    def seed(self, seed):
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

    def play_out(self, action, seed):
        self.seed(seed)
        while not self.state["battle_over"] and self.state["round_number"] < MAX_ROUNDS:
            self.step(action)
        return self.state


def main() -> int:
    print("Dice R2 — full content spine\n")

    with served_bundle() as port:
        ad = adapter_for(port)
        ad.connect()
        drv = Driver(ad)
        try:
            # ---- every allocation resolves --------------------------------
            print("  -- all 7 allocations --")
            drv.seed(DEFAULT_SEED)
            dead = []
            for p in PRESETS:
                before = drv.state
                after = drv.step(p)
                if after["round_number"] != before["round_number"] + 1:
                    dead.append(p)
            gate.ck("all 7 allocation presets resolve a round", not dead,
                    "0..6 each advanced the round" if not dead else f"inert presets: {dead}")

            # ---- defense really defends (controlled A/B) -------------------
            # Same seed, same round indices, only the allocation differs. This is
            # the comparison a feature-map assertion structurally cannot make: it
            # sees one action list's before/after, never two battles side by side.
            print("\n  -- defense vs attack, same seed, same rounds --")
            def damage_over(action, rounds=4):
                drv.seed(DEFAULT_SEED)
                start = drv.state["player"]["force_strength"]
                for _ in range(rounds):
                    drv.step(action)
                return start - drv.state["player"]["force_strength"]

            atk_loss, def_loss = damage_over(ALL_ATTACK), damage_over(ALL_DEFENSE)
            gate.ck("all-defense takes strictly less damage than all-attack over the same 4 rounds",
                    def_loss < atk_loss,
                    f"all-attack lost {atk_loss} FS, all-defense lost {def_loss} FS")

            # ---- terminal arm 1: the round cap -----------------------------
            print("\n  -- terminal arm 1: round-12 draw --")
            drawn = drv.play_out(ALL_ATTACK, DEFAULT_SEED)
            gate.ck("the default seed ends as a draw at the round cap",
                    drawn["battle_over"] and drawn["winner"] == "draw"
                    and drawn["round_number"] == MAX_ROUNDS,
                    f"round {drawn['round_number']}, "
                    f"{drawn['player']['force_strength']} v {drawn['enemy']['force_strength']}")
            gate.ck("it really was the cap, not a knockout — both sides still standing",
                    drawn["player"]["force_strength"] > 0 and drawn["enemy"]["force_strength"] > 0)

            # ---- terminal arm 2: a knockout --------------------------------
            print("\n  -- terminal arm 2: knockout --")
            ko = drv.play_out(ALL_ATTACK, KNOCKOUT_SEED)
            gate.ck("a knockout is reachable, and sets a decisive winner",
                    ko["battle_over"] and ko["winner"] in ("player", "enemy")
                    and min(ko["player"]["force_strength"], ko["enemy"]["force_strength"]) == 0,
                    f"seed {KNOCKOUT_SEED}: round {ko['round_number']}, winner={ko['winner']!r}, "
                    f"{ko['player']['force_strength']} v {ko['enemy']['force_strength']}")
            gate.ck("the knockout landed BEFORE the cap (it is a real decision, not a relabelled draw)",
                    ko["round_number"] < MAX_ROUNDS,
                    f"ended on round {ko['round_number']} of {MAX_ROUNDS}")
            gate.ck("both terminal arms were reached in this run",
                    drawn["winner"] == "draw" and ko["winner"] in ("player", "enemy"),
                    f"draw + {ko['winner']}")

            # ---- concluded battles stay concluded ---------------------------
            print("\n  -- after the end --")
            frozen = drv.state
            gate.ck("a concluded battle ignores every allocation",
                    all(drv.step(p) == frozen for p in PRESETS),
                    "tried all 7 presets on a finished battle; nothing moved")

            # ---- invariants --------------------------------------------------
            print("\n  -- invariants --")
            gate.ck(f"all {len(SUITE.predicates)} invariants held across {drv.commands} rounds",
                    not drv.violations,
                    "" if not drv.violations else "; ".join(drv.violations[:3]))
            corrupt = {**frozen, "player": {**frozen["player"], "force_strength": 25}}
            fired = SUITE.check_command(frozen, corrupt, "synthetic", {})
            gate.ck("the invariant suite FIRES on a corrupted transition (non-vacuous)",
                    bool(fired), f"{len(fired)} violation(s)")

            # ---- the balance observation, recorded as a finding ---------------
            gate.finding(
                f"The round cap decides most matches. Playing pure all-attack — the most "
                f"aggressive line available — the shipped seed still ends "
                f"{drawn['player']['force_strength']} v {drawn['enemy']['force_strength']} as a "
                f"DRAW at round {MAX_ROUNDS}, and an earlier sweep found only 2 of 12 seeds "
                f"produce a knockout that way. A knockout is reachable (seed "
                f"{KNOCKOUT_SEED}, round {ko['round_number']}) but is the exception. Either "
                f"MAX_ROUNDS is too tight or damage is too low for a 12-round game; both are "
                f"single exported constants in engine.js."
            )
        finally:
            ad.close()

    return gate.finish(
        "ROUND 2",
        f"Every allocation resolves, defense measurably beats attack for damage taken, and "
        f"BOTH terminal arms were driven to a real outcome — the round-12 draw and a genuine "
        f"knockout — with all invariants holding across {drv.commands} rounds.",
    )


if __name__ == "__main__":
    sys.exit(main())
