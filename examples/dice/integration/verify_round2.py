#!/usr/bin/env python3
"""Rung 4 (R2) — full spine: every allocation, and BOTH terminal arms.

    python3 examples/dice/integration/verify_round2.py

R1 proved one battle works. R2 proves the whole content surface does:

  * all seven allocation presets actually resolve a round;
  * defense demonstrably beats attack for damage taken (a controlled A/B — the
    same claim the feature map could not make, because it compares two
    different battles);
  * ALL THREE ways a battle can end are reached for real — a knockout to 0, a
    points decision at the round cap, and the (now rare) exact-tie draw;
  * each arm needs a specific seed, which is exactly what a scripted rung can do
    and `ugt verify` cannot.
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

ALL_ATTACK, ALL_DEFENSE, BALANCED = 0, 6, 3
PRESETS = list(range(7))

# D18 (2026-07-26) added a THIRD way for a battle to end, so this rung now
# covers three terminal arms instead of two. The round cap used to draw
# unconditionally; it now decides on Force Strength, and only an exact tie
# draws. The three are genuinely different branches of `evaluateOutcome`:
#
#   KNOCKOUT   a side reaches 0 before the cap        -> decisive
#   POINTS     the cap is reached, FS differs         -> decisive   (NEW)
#   DRAW       the cap is reached, FS exactly equal   -> draw       (now rare)
#
# Per LESSONS.md O10, a gate that returns its old check count after the game
# gained an outcome type has not tested the new outcome — so the count moves.
#
# Every fixture below was re-swept for this change, because all the old ones
# expired: 'stalemate' now knocks out on round 7 instead of drawing, and seed 0
# now runs to the cap instead of knocking out. This rung failing is what caught
# both.
DEFAULT_SEED = "anvil"         # a representative battle (shared with R1)
KNOCKOUT_SEED = "stalemate"    # all-attack: enemy wins by KO on round 7
POINTS_SEED = "deadlock"       # balanced: reaches the cap at 5 v 2, player wins
DRAW_SEED = "siege"            # balanced: reaches the cap at an exact 2 v 2
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

            # ---- terminal arm 1: a knockout --------------------------------
            print("\n  -- terminal arm 1: knockout before the cap --")
            ko = drv.play_out(ALL_ATTACK, KNOCKOUT_SEED)
            gate.ck("a knockout is reachable, and sets a decisive winner",
                    ko["battle_over"] and ko["winner"] in ("player", "enemy")
                    and min(ko["player"]["force_strength"], ko["enemy"]["force_strength"]) == 0,
                    f"seed {KNOCKOUT_SEED!r}: round {ko['round_number']}, winner={ko['winner']!r}, "
                    f"{ko['player']['force_strength']} v {ko['enemy']['force_strength']}")
            gate.ck("the knockout landed BEFORE the cap (a real decision, not a relabelled timeout)",
                    ko["round_number"] < MAX_ROUNDS,
                    f"ended on round {ko['round_number']} of {MAX_ROUNDS}")

            # ---- terminal arm 2: decided on points at the cap (D18) --------
            print("\n  -- terminal arm 2: points decision at the cap (D18) --")
            pts = drv.play_out(BALANCED, POINTS_SEED)
            gate.ck(f"seed {POINTS_SEED!r} runs the full {MAX_ROUNDS} rounds",
                    pts["battle_over"] and pts["round_number"] == MAX_ROUNDS,
                    f"round {pts['round_number']}, "
                    f"{pts['player']['force_strength']} v {pts['enemy']['force_strength']}")
            gate.ck("the cap DECIDED it on Force Strength rather than drawing",
                    pts["winner"] in ("player", "enemy"),
                    f"winner={pts['winner']!r} — under the pre-D18 rule this same battle drew")
            # The arm is only meaningful if nobody died: otherwise it is arm 1
            # wearing a different label, and would pass while testing nothing.
            gate.ck("both sides finished the cap ALIVE — this is a points win, not a knockout",
                    pts["player"]["force_strength"] > 0 and pts["enemy"]["force_strength"] > 0)
            higher = ("player" if pts["player"]["force_strength"] > pts["enemy"]["force_strength"]
                      else "enemy")
            gate.ck("the winner is the side with the HIGHER force strength",
                    pts["winner"] == higher,
                    f"{higher} led {pts['player']['force_strength']} v "
                    f"{pts['enemy']['force_strength']} and won")

            # ---- terminal arm 3: the surviving draw ------------------------
            print("\n  -- terminal arm 3: draw, now an exact tie only --")
            drawn = drv.play_out(BALANCED, DRAW_SEED)
            gate.ck(f"seed {DRAW_SEED!r} ends as a draw at the round cap",
                    drawn["battle_over"] and drawn["winner"] == "draw"
                    and drawn["round_number"] == MAX_ROUNDS,
                    f"round {drawn['round_number']}, "
                    f"{drawn['player']['force_strength']} v {drawn['enemy']['force_strength']}")
            gate.ck("it drew because the two sides are EXACTLY level, both still standing",
                    drawn["player"]["force_strength"] == drawn["enemy"]["force_strength"]
                    and drawn["player"]["force_strength"] > 0,
                    "post-D18 a draw is a tie on points, not simply running out of rounds")

            gate.ck("all THREE terminal arms were reached in this run",
                    ko["winner"] in ("player", "enemy")
                    and pts["winner"] in ("player", "enemy")
                    and drawn["winner"] == "draw",
                    f"knockout ({ko['winner']}) + points ({pts['winner']}) + draw")

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

            # ---- the depth finding, now CLOSED -------------------------------
            gate.finding(
                "CLOSED 2026-07-26 by D18. This rung used to carry an open finding that "
                "the game had no strategic depth: all-attack won 35 of 60 while a balanced "
                "allocation won 1 of 60, so aggression was not a trade-off, just the right "
                "answer. It was correctly filed as a DESIGN question rather than a constant "
                "to tune — two independent reviews then proved it structural (the marginal "
                "gap between an attack die and a defense die is p(1-p)*P(tie) > 0, in which "
                "no balance constant appears, so no retune could ever have fixed it). "
                "Resolved by DEFENSE_BLOCK = 2 plus a round cap that decides on Force "
                "Strength, chosen by simulating six rule variants over 3.15M battles before "
                "any code changed — see LESSONS.md SS D. Best response is now [3,3,3,3,3,2,0] "
                "rather than all-zeros, regret of all-attack 0.000 -> 0.131, and optimal "
                "play picks a genuine mix 61% of the time rather than 7%. Kept here as a "
                "record, not an open item: `game/tools/balance_sweep.mjs` reports these "
                "numbers on demand and now warns if regret ever falls back under 0.02."
            )
        finally:
            ad.close()

    return gate.finish(
        "ROUND 2",
        f"Every allocation resolves, defense measurably beats attack for damage taken, and all "
        f"THREE terminal arms were driven to a real outcome — a knockout, a D18 points decision "
        f"at the cap, and an exact-tie draw — with all invariants holding across "
        f"{drv.commands} rounds.",
    )


if __name__ == "__main__":
    sys.exit(main())
