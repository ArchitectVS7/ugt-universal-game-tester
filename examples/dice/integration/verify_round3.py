#!/usr/bin/env python3
"""Rung 5 (R3) — robustness: UGT's real ExploitHunter against the live page.

    python3 examples/dice/integration/verify_round3.py

Uniform-random allocations with `invariants.py` asserted after every round — the
SAME predicates R1/R2 use, via `InvariantSuite.to_hunter_invariants()`, so the
scripted and random tiers cannot drift on what "correct" means.

One quirk worth knowing (see the smoke rung's finding): the adapter never
observes termination for this game, so a hunter episode does not stop when the
battle ends — it keeps issuing allocations into a concluded, inert battle. That
is measured here rather than ignored, because it caps how much a random walk of
a given length can actually explore.
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
from ugt.core.exploit_hunter import ExploitHunter  # noqa: E402
from ugt.core.trial import GateRunner, first_divergence  # noqa: E402

PRESETS = {0: "a6_d0", 1: "a5_d1", 2: "a4_d2", 3: "a3_d3",
           4: "a2_d4", 5: "a1_d5", 6: "a0_d6"}
STEPS = 120
SEEDS = (0, 1)
MAX_ROUNDS = 12

gate = GateRunner()


def main() -> int:
    print("Dice R3 — exploit hunter against the live page\n")
    hunter_invariants = SUITE.to_hunter_invariants()
    print(f"  ({len(hunter_invariants)} invariants, shared with R1/R2)\n")

    with served_bundle() as port:
        # ---- random walks --------------------------------------------------
        print("  -- random walks --")
        total = 0
        for seed in SEEDS:
            ad = adapter_for(port)
            hunter = ExploitHunter(ad, hunter_invariants, list(PRESETS),
                                   action_names=PRESETS, seed=seed)
            rep = hunter.run(episodes=1, steps_per_episode=STEPS, log=lambda m: None)
            try:
                ad.close()
            except Exception:
                pass
            total += STEPS
            n = len(rep.findings)
            gate.ck(f"seed {seed}: {STEPS} uniform-random allocations, 0 findings", n == 0,
                    "" if n == 0 else "; ".join(f"{f.name}: {f.detail}" for f in rep.findings[:3]))

        # ---- how much of that walk was actually live? -----------------------
        # A battle is over by round 12 at the latest, and the adapter never
        # reports termination, so most of a 120-step episode lands on a dead
        # battle. Measure it instead of pretending the whole walk explored.
        print("\n  -- how much of a random episode is live --")
        ad = adapter_for(port)
        ad.connect()
        try:
            import random
            rng = random.Random(0)
            ad.reset()
            live = 0
            for _ in range(STEPS):
                st, _t, _tr, _i = ad.step(rng.choice(list(PRESETS)))
                if not st["battle_over"]:
                    live += 1
            pct = round(100 * live / STEPS)
            gate.ck("a random episode does reach a terminal battle",
                    st["battle_over"], f"winner={st['winner']!r}")
            gate.finding(
                f"Only {live} of {STEPS} steps in a random episode ({pct}%) land on a live "
                f"battle — the rest hammer a concluded one, because the adapter never sees "
                f"termination (smoke rung's finding) and the battle is capped at "
                f"{MAX_ROUNDS} rounds. The invariants still cover those steps (a concluded "
                f"battle must stay inert, which is itself worth asserting), but the effective "
                f"exploration budget is ~{pct}% of the nominal step count. Sending "
                f"`terminated` from the hooks would let episodes reset and multiply the "
                f"useful coverage."
            )

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
                    out.append(a.page.evaluate(f"window.__SEND_ACTION__({act})"))
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
        f"UGT's real ExploitHunter drove the live page for {total} random allocations across "
        f"{len(SEEDS)} seeds with zero findings, illegal ids were proven rejected without "
        f"corrupting state, replays are byte-identical and seed-sensitive, and the invariant "
        f"suite was shown able to fail.",
    )


if __name__ == "__main__":
    sys.exit(main())
