#!/usr/bin/env python3
"""Rung 5 (R3) — robustness: UGT's real InvariantFuzzer against the live page.

    python3 examples/dice/integration/verify_round3.py

Uniform-random allocations with `invariants.py` asserted after every round — the
SAME predicates R1/R2 use, via `InvariantSuite.to_hunter_invariants()`, so the
scripted and random tiers cannot drift on what "correct" means.

Episode shape matters here. A battle is over in at most MAX_ROUNDS rounds, so a
long single episode would spend most of its steps on a concluded, inert battle.
Since the D14 envelope fix the adapter DOES see termination, and the hunter
breaks the episode on it — so this rung runs MANY SHORT EPISODES instead of one
long one, and every step lands on a live battle. The rung measures that rather
than assuming it; before the fix the same nominal budget was ~9% live.
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

from invariants import SUITE  # noqa: E402
from serve_process import adapter_for, served_bundle  # noqa: E402
from ugt.core.invariant_fuzzer import InvariantFuzzer
from ugt.core.generic_checks import run_generic_checks  # noqa: E402
from ugt.core.trial import GateRunner, first_divergence  # noqa: E402

PRESETS = {0: "a6_d0", 1: "a5_d1", 2: "a4_d2", 3: "a3_d3",
           4: "a2_d4", 5: "a1_d5", 6: "a0_d6"}
# Many short episodes, not one long one: the hunter resets on `terminated`, and a
# battle cannot last more than MAX_ROUNDS. EPISODES x STEPS is the nominal budget;
# what matters is how much of it is LIVE, which the rung measures below.
EPISODES = 10
STEPS = 20
# State paths that legitimately only ever grow. Dispositioned, not assumed:
# `round_number` counts resolved rounds and `roll_counter` counts dice consumed
# (the RNG-in-state discipline R3's replay check depends on). Neither is a
# resource a player could farm. Anything NEW that only grows will trip the
# monotone-growth check and demand its own disposition.
MONOTONE_COUNTERS = ("round_number", "roll_counter")
SEEDS = (0, 1)
MAX_ROUNDS = 12

gate = GateRunner()


def main() -> int:
    print("Dice R3 — invariant fuzzer against the live page\n")
    hunter_invariants = SUITE.to_hunter_invariants()
    print(f"  ({len(hunter_invariants)} invariants, shared with R1/R2)\n")

    with served_bundle() as port:
        # ---- random walks --------------------------------------------------
        print("  -- random walks --")
        total = 0
        last_report = None
        for seed in SEEDS:
            ad = adapter_for(port)
            hunter = InvariantFuzzer(ad, hunter_invariants, list(PRESETS),
                                   action_names=PRESETS, seed=seed,
                                   monotone_allowlist=MONOTONE_COUNTERS)
            rep = hunter.run(episodes=EPISODES, steps_per_episode=STEPS, log=lambda m: None)
            try:
                ad.close()
            except Exception:
                pass
            total += EPISODES * STEPS
            last_report = rep
            n = len(rep.findings)
            gate.ck(f"seed {seed}: {EPISODES} episodes x up to {STEPS} allocations, 0 findings",
                    n == 0,
                    "" if n == 0 else "; ".join(f"{f.name}: {f.detail}" for f in rep.findings[:3]))

        # ---- the framework's own generic checks -----------------------------
        # These need no per-game configuration: the fuzzer discovers what to look
        # at from the observed states. They are the floor every game inherits —
        # the answer to "R3 only finds what we tell it to". They are reported,
        # not fatal, so read them rather than trusting the count.
        print("\n  -- framework generic checks (no game knowledge) --")
        obs = last_report.observations
        for ob in obs:
            print(f"     {ob}")
            for line in ob.evidence[:4]:
                print(f"        - {line}")
        if not obs:
            print("     (all quiet)")
        # Non-vacuity: this channel has to be able to SAY something, or its
        # silence proves nothing. `round_number` and `roll_counter` really do
        # only ever increase, so dropping the allowlist must make it speak.
        loud = run_generic_checks(last_report.trace, monotone_allowlist=())
        gate.ck("the generic-check channel is live (it fires when the allowlist is removed)",
                any(o.check == "monotone-growth" for o in loud),
                f"without the allowlist: {sorted({o.check for o in loud})}")
        gate.ck("no UNDISPOSITIONED generic check tripped",
                not obs,
                "" if not obs else "; ".join(o.summary for o in obs))

        # ---- how much of the budget is actually live? -----------------------
        # This is the number the D14 envelope fix was made for. Before it, the
        # adapter never saw `terminated`, the episode never reset, and a 120-step
        # walk spent ~109 steps hammering a battle that had already ended.
        print("\n  -- live coverage --")
        ad = adapter_for(port)
        ad.connect()
        try:
            import random
            rng = random.Random(0)
            live = dead = battles = 0
            for _ in range(EPISODES):
                st = ad.reset()
                for _ in range(STEPS):
                    st, terminated, _tr, _i = ad.step(rng.choice(list(PRESETS)))
                    if st["battle_over"]:
                        dead += 0 if terminated else 1
                        if terminated:
                            battles += 1
                        break
                    live += 1
            budget = EPISODES * STEPS
            pct = round(100 * (live + battles) / budget)
            gate.ck("every episode reached a real terminal battle",
                    battles == EPISODES, f"{battles}/{EPISODES} battles concluded")
            gate.ck("no step was wasted on an already-concluded battle",
                    dead == 0,
                    f"{live + battles} live steps across {battles} full battles "
                    f"({pct}% of the {budget}-step budget; it was ~9% before the D14 fix)")
            # ---- illegal input, through the adapter --------------------------
            print("\n  -- illegal input --")
            ad.reset()
            for _ in range(3):
                ad.step(0)
            before = ad._get_game_state()
            rejected, mutated = 0, []
            for bad in (-1, 7, 999):
                try:
                    ad.step(bad)
                except Exception:
                    rejected += 1
                if ad._get_game_state() != before:
                    mutated.append(bad)
            gate.ck("out-of-range action ids are rejected by the game, not silently absorbed",
                    rejected == 3, f"{rejected}/3 raised")
            gate.ck("...and none of them mutated state", not mutated,
                    "state identical after all three" if not mutated else f"mutated: {mutated}")
            gate.ck("the page is still usable afterwards",
                    ad.step(0)[0]["round_number"] == before["round_number"] + 1)
        finally:
            ad.close()

        # ---- determinism ----------------------------------------------------
        print("\n  -- determinism --")
        def replay(seed_label, actions):
            a = adapter_for(port)
            a.connect()
            try:
                a.page.evaluate(f"window.__RESET__({json.dumps(seed_label)})")
                out = [a.page.evaluate("window.__GET_STATE__()")]
                for act in actions:
                    # __SEND_ACTION__ returns the envelope; compare STATES.
                    out.append(a.page.evaluate(f"window.__SEND_ACTION__({act})")["state"])
                return out
            finally:
                a.close()

        seq = [0, 3, 6, 1, 4, 2, 0, 5, 3, 0]
        s1, s2 = replay("dice-duel", seq), replay("dice-duel", seq)
        div = first_divergence(s1, s2)
        gate.ck("two fresh browsers replay the same seed byte-identically",
                div is None, "" if div is None else f"first divergence at index {div}")
        distinct = len({json.dumps(s, sort_keys=True) for s in s1})
        gate.ck("the determinism proof is NON-VACUOUS (state actually moved)",
                distinct > 1, f"{distinct} distinct states over {len(s1)} steps")
        other = replay(0, seq)
        gate.ck("a different seed diverges (the replay check is actually seed-sensitive)",
                first_divergence(s1, other) is not None)

        # ---- suite non-vacuity ----------------------------------------------
        print("\n  -- non-vacuity of the invariant suite --")
        good = s1[-1]
        bad = {**good, "round_number": good["round_number"] + 5, "winner": "nobody"}
        fired = SUITE.check_command(good, bad, "synthetic", {})
        gate.ck("the shared invariant suite FIRES on a corrupted transition",
                bool(fired), f"{len(fired)} violation(s)")

    return gate.finish(
        "ROUND 3",
        f"UGT's real InvariantFuzzer drove the live page for {total} random allocations across "
        f"{len(SEEDS)} seeds with zero findings, illegal ids were proven rejected without "
        f"corrupting state, replays are byte-identical and seed-sensitive, and the invariant "
        f"suite was shown able to fail.",
    )


if __name__ == "__main__":
    sys.exit(main())
