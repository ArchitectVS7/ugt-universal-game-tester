#!/usr/bin/env python3
"""Rung 5 (R3) — robustness: UGT's real InvariantFuzzer against the live bridge.

    python3 examples/escape-room/integration/verify_round3.py

Uniform-random actions with `invariants.py` asserted after every step — the SAME
predicates R1/R2 use, via `InvariantSuite.to_hunter_invariants()`, so the
scripted and random tiers cannot drift on what "correct" means.

Supersedes `fuzz_escape_room.py`, which pre-dated `invariants.py` and carried
its own private copy of six predicates. Its three good ideas are kept and the
duplication is not: the negative control (an invariant never seen to fail is not
evidence — LESSONS O2), the same-seed replay check, and the non-vacuity guard.
Added here: `generic_checks`, the zero-config floor every game gets.

**What a green run here does and does not prove.** Random play cannot solve this
game — a uniform policy almost never advances a 7-link flag chain, and the walk
below reaches only a handful of distinct states. That is a property of the
genre, not a defect, and it is why the tiers are not interchangeable: R3 proves
the game never BREAKS under nonsense input; only R1/R2 (scripted) and the LLM
tier can show it is completable. The rung measures its own reach rather than
implying otherwise.
"""
from __future__ import annotations

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (HERE, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from invariants import PREDICATES, SUITE  # noqa: E402
from ugt.adapters.subprocess import SubprocessAdapter  # noqa: E402
from ugt.core.generic_checks import run_generic_checks  # noqa: E402
from ugt.core.invariant_fuzzer import InvariantFuzzer  # noqa: E402
from ugt.core.trial import GateRunner, first_divergence  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG = os.path.join(HERE, "ugt.config.yaml")
EPISODES = 1
STEPS = 160          # the superseded fuzzer's budget, kept for comparability
SEEDS = (0, 1)
REPLAY_STEPS = 60

# State paths that legitimately only ever grow. Dispositioned, not assumed:
# `moves_taken` counts accepted commands and `rooms_visited` counts distinct
# rooms entered. Neither is a resource a player could farm — there is no
# economy in this game at all. Anything NEW that only grows will trip the
# monotone-growth check and demand its own disposition.
MONOTONE_COUNTERS = ("moves_taken", "rooms_visited")

# Generic-check observations this integration has looked at and accepted, with
# the reason. Observations are informational by design — an integration promotes
# one to a gate failure or dispositions it. Anything NOT listed here fails the
# rung, so a NEW observation can never slip through as "one of the known ones".
DISPOSITIONED = {
    "state-cycle":
        "Expected, and load-bearing. An inapplicable command is documented to "
        "consume NOTHING — not even moves_taken — so any refusal returns an "
        "identical state, and ~35 of 41 actions are inapplicable in a given "
        "room. The repeats are refusals, not a farmable loop: this game has no "
        "economy, no score and no resource, so there is nothing a cycle could "
        "accumulate. R1 asserts the refusal semantics directly.",
    "dead-action":
        "An artifact of random play's reach, NOT unimplemented content. The walk "
        "below never leaves the first two rooms, so the other 30 actions are "
        "merely out of context. R2 is the authority that refutes this: it issues "
        "all 41 declared actions and asserts each one's real effect (take/drop/"
        "re-take, examine, both arms of every use-gate). If R2 ever stops "
        "covering all 41, THAT is the failure — not this observation.",
    "action-coverage":
        "Sampling artifact of a uniform policy over 41 actions in 160 steps. R2 "
        "covers the full action space deterministically.",
}

gate = GateRunner()


def check(ok, label, detail=""):
    """Adapter to GateRunner's (name, ok, detail) order, so call sites read naturally."""
    return gate.ck(label, ok, detail)


def state_stream(cfg, seed: int, steps: int) -> list:
    """Drive a fixed pseudo-random action sequence and record every state."""
    ids = sorted(int(k) for k in cfg.action_mappings)
    rng = random.Random(seed)
    ad = SubprocessAdapter(cfg)
    ad.connect()
    try:
        stream = [ad.reset()]
        for _ in range(steps):
            state, _t, _tr, _i = ad.step(rng.choice(ids))
            stream.append(state)
        return stream
    finally:
        ad.close()


def main() -> int:
    print("Escape Room R3 — invariant fuzzer against the live bridge\n")

    cfg = UgtConfig(CONFIG)
    action_ids = sorted(int(k) for k in cfg.action_mappings)
    names = {int(k): v["name"] for k, v in cfg.action_mappings.items()}
    hunter_invariants = SUITE.to_hunter_invariants()
    print(f"  ({len(hunter_invariants)} invariants, shared with R1/R2)\n")

    # ── 1. random walks ──────────────────────────────────────────────────────
    print("  -- random walks --")
    last_report = None
    for seed in SEEDS:
        ad = SubprocessAdapter(cfg)
        fuzzer = InvariantFuzzer(ad, hunter_invariants, action_ids,
                                 action_names=names, seed=seed)
        report = fuzzer.run(episodes=EPISODES, steps_per_episode=STEPS,
                            log=lambda m: None)
        last_report = report
        try:
            ad.close()
        except Exception:
            pass
        n = len(report.findings)
        check(n == 0, f"seed {seed}: {EPISODES}x{STEPS} random steps, 0 findings",
              "" if n == 0 else "; ".join(f"{f.name}: {f.detail}"
                                          for f in report.findings[:3]))

    # ── 2. the negative control ──────────────────────────────────────────────
    # Every predicate must be capable of firing. One that stays silent here is
    # decoration, and a suite of decorations is a green light wired to nothing.
    print("\n  -- negative control (every invariant MUST be able to fail) --")
    good = {"current_room": "R02", "inventory": ["lantern"],
            "flags": {"has_oil": True, "lantern_lit": False},
            "moves_taken": 5, "rooms_visited": 3, "escaped": False}
    won = {**good, "current_room": "R10", "escaped": True}
    corrupt = {
        "moves_never_decrease":            {**good, "moves_taken": 4},
        "moves_advance_by_at_most_one":    {**good, "moves_taken": 9},
        "rooms_visited_never_decreases":   {**good, "rooms_visited": 2},
        "rooms_visited_within_the_map":    {**good, "rooms_visited": 99},
        "current_room_is_real":            {**good, "current_room": "R99"},
        "a_move_goes_to_an_adjacent_room": {**good, "current_room": "R09",
                                            "moves_taken": 6},
        "inventory_holds_only_real_objects": {**good, "inventory": ["excalibur"],
                                              "moves_taken": 6},
        "inventory_changes_by_at_most_one": {**good, "inventory": ["a", "b", "c"],
                                             "moves_taken": 6},
        "escaped_never_reverts":           {**won, "escaped": False},
        "escaped_is_only_ever_won_in_the_exit_room":
                                           {**good, "escaped": True,
                                            "current_room": "R03", "moves_taken": 6},
        "flags_never_unset":               {**good, "flags": {"has_oil": False,
                                                              "lantern_lit": False}},
        "the_flag_key_set_is_stable":      {**good, "flags": {"has_oil": True}},
        "a_free_action_changes_nothing_at_all": {**good, "current_room": "R03"},
    }
    befores = {"escaped_never_reverts": won}
    silent = [p.__name__ for p in PREDICATES
              if not p(befores.get(p.__name__, good), corrupt[p.__name__], "probe", {})]
    check(not silent, f"all {len(PREDICATES)} invariants fire on a corrupted transition",
          "" if not silent else f"silent (cannot fail): {silent}")

    # ...and must NOT fire on a legitimate one, or every run is noise.
    legit = {**good, "current_room": "R03", "moves_taken": 6, "rooms_visited": 4}
    noisy = [p.__name__ for p in PREDICATES if p(good, legit, "go_east", {})]
    check(not noisy, "no invariant fires on a legitimate transition",
          "" if not noisy else f"false positives: {noisy}")

    # ── 3. generic checks — the zero-config floor ────────────────────────────
    print("\n  -- generic checks --")
    obs = run_generic_checks(last_report.trace, monotone_allowlist=MONOTONE_COUNTERS)
    loud = run_generic_checks(last_report.trace, monotone_allowlist=())
    check(any(o.check == "monotone-growth" for o in loud),
          "the generic-check channel is LIVE (it fires when the allowlist is removed)",
          f"without the allowlist: {sorted({o.check for o in loud})}")

    for o in obs:
        print(f"      [{o.check}] {o.summary}")
    undispositioned = [o for o in obs if o.check not in DISPOSITIONED]
    check(not undispositioned,
          "every generic-check observation is DISPOSITIONED (none new)",
          f"dispositioned: {sorted({o.check for o in obs})}"
          if not undispositioned
          else "NEW, needs a disposition: "
               + "; ".join(f"[{o.check}] {o.summary}" for o in undispositioned))
    # A disposition list that names checks which never fire is stale paperwork —
    # it would silently keep excusing a check long after the reason expired.
    stale = sorted(set(DISPOSITIONED) - {o.check for o in obs})
    check(not stale, "no disposition is stale (each one still describes a live observation)",
          f"listed but never fired: {stale}" if stale else "")

    # ── 4. determinism ───────────────────────────────────────────────────────
    # This game has no RNG, so any divergence here would be the HARNESS's
    # nondeterminism (dict ordering, uninitialised reuse) — which is exactly what
    # makes the check worth running on a game that cannot fail it on its own.
    print("\n  -- determinism --")
    a = state_stream(cfg, 0, REPLAY_STEPS)
    b = state_stream(cfg, 0, REPLAY_STEPS)
    same = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    check(same, "same-seed replay is byte-identical across two separate processes",
          "" if same else f"first divergence at index {first_divergence(a, b)}")
    distinct = len({json.dumps(s, sort_keys=True) for s in a})
    check(distinct > 1, "the determinism proof is NON-VACUOUS (state actually moved)",
          f"{distinct} distinct states over {len(a)} steps")

    c = state_stream(cfg, 1, REPLAY_STEPS)
    check(json.dumps(a, sort_keys=True) != json.dumps(c, sort_keys=True),
          "a DIFFERENT seed produces a different walk (the seed is really wired)",
          f"first divergence at index {first_divergence(a, c)}")

    # ── 5. what the random tier actually reached ─────────────────────────────
    # Reported, never asserted away. The number is the point: it is the clearest
    # illustration in this repo of why a random tier cannot replace a scripted one.
    # Printed as a NOTE, not registered as a finding: `gate.finding()` prints
    # under "bugs/anomalies to fix upstream", and none of this is a bug.
    print("\n  -- reach (reported, not gated, not a finding) --")
    rooms = {s["current_room"] for s in a}
    escaped = any(s["escaped"] for s in a)
    print(f"      Random play reached {distinct} distinct states and {len(rooms)} of 10 "
          f"rooms in {REPLAY_STEPS} steps; escaped={escaped}.")
    print(f"      Expected: a uniform policy almost never advances an 8-link flag chain.")
    print(f"      R3 proves the game does not BREAK under nonsense input. Only R1/R2 and")
    print(f"      the LLM tier can prove it is COMPLETABLE — do not read a green R3 as")
    print(f"      'the game works'.")

    return gate.finish(
        "ROUND 3",
        f"No invariant broke under random pressure across {len(SEEDS)} seeds, every invariant "
        f"was proven able to fail, no undispositioned generic check tripped, and the run "
        f"replays byte-identically while a different seed diverges.")


if __name__ == "__main__":
    sys.exit(main())
