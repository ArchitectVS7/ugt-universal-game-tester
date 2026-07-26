#!/usr/bin/env python3
"""Proof harness for `ugt/core/seeding.py` — this file IS its test suite.

    python3 tools/prove_seeding.py

There is no pytest in this repo, and a module whose entire job is to refuse bad
configurations is worthless unless the refusals have been SEEN to fire. So every
guard is exercised in both directions: it must reject what it claims to reject,
and it must accept what it claims to accept.

Modelled on `tools/prove_generic_checks.py`, which plays the same role for the
generic-check floor. Re-run after touching either file.
"""
from __future__ import annotations

import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from ugt.core import seeding  # noqa: E402
from ugt.core.trial import GateRunner  # noqa: E402

gate = GateRunner()


def check(ok, label, detail=""):
    return gate.ck(label, ok, detail)


def raises(fn, *a, **kw):
    """(did_it_raise, message)"""
    try:
        fn(*a, **kw)
        return False, ""
    except seeding.SeedingError as e:
        return True, str(e)


class FakeAdapter:
    """A game whose determinism is whatever the test says it is.

    `mode` drives what the state stream looks like:
      "seeded"        - state depends on the seed, and replays for the same seed
      "ignores_seed"  - accepts a seed and ignores it (the JS silent-drop bug)
      "random"        - different every reset, seed or not
      "deterministic" - identical every reset
      "inert"         - never changes state at all (probe cannot prove anything)
    """

    def __init__(self, mode):
        self.mode = mode
        self._seed = None
        self._tick = 0
        self._run = 0

    def reset(self):
        self._seed = None
        self._tick = 0
        self._run += 1
        return self._state()

    def reset_seeded(self, seed):
        if self.mode == "unseedable":
            raise NotImplementedError("FakeAdapter cannot seed")
        self._seed = seed
        self._tick = 0
        self._run += 1
        return self._state()

    def _state(self):
        if self.mode == "inert":
            return {"x": 0}
        if self.mode == "random":
            return {"x": self._tick, "run": self._run}
        if self.mode == "ignores_seed":
            return {"x": self._tick}
        if self.mode == "deterministic":
            return {"x": self._tick}
        return {"x": self._tick, "seed": self._seed}   # "seeded"

    def step(self, _action):
        self._tick += 1
        return self._state(), False, False, {}


def main() -> int:
    print("Proving ugt/core/seeding.py — every guard, both directions\n")

    # ── resolve(): the config contract ───────────────────────────────────────
    print("  -- resolve() --")
    ok, msg = raises(seeding.resolve, {})
    check(ok, "no declaration and no seeds is REFUSED (the ambiguous case)",
          msg.splitlines()[0] if ok else "accepted silently")

    mode, seeds = seeding.resolve({"episode_seeds": ["a", "b"]})
    check(mode == seeding.PER_EPISODE and seeds == ["a", "b"],
          "a declared seed list infers per_episode (unambiguous, backward compatible)",
          f"mode={mode}")

    mode, seeds = seeding.resolve({"seeding": "deterministic"})
    check(mode == seeding.DETERMINISTIC and seeds == [],
          "an explicit deterministic declaration needs no seeds")

    ok, _ = raises(seeding.resolve, {"seeding": "sometimes"})
    check(ok, "an unknown mode is REFUSED")

    ok, _ = raises(seeding.resolve, {"seeding": "per_episode", "episode_seeds": ["only"]})
    check(ok, "per_episode with a single seed is REFUSED (rotation needs >= 2)")

    ok, _ = raises(seeding.resolve, {"seeding": "deterministic", "episode_seeds": ["a", "b"]})
    check(ok, "deterministic WITH seeds is REFUSED (one of them is a lie)")

    mode, _ = seeding.resolve({"seeding": "uncontrolled"})
    check(mode == seeding.UNCONTROLLED, "uncontrolled resolves cleanly")

    # ── probe(): the declaration vs the live game ────────────────────────────
    print("\n  -- probe(): per_episode --")
    proof = seeding.probe(FakeAdapter("seeded"), seeding.PER_EPISODE, ["s1", "s2"])
    check("PROVEN" in proof, "a genuinely seeded game PASSES", proof)

    ok, msg = raises(seeding.probe, FakeAdapter("ignores_seed"),
                     seeding.PER_EPISODE, ["s1", "s2"])
    check(ok, "a game that SILENTLY IGNORES the seed is caught",
          "this is the browser-dice bug: accepts the arg, returns normal state")

    ok, msg = raises(seeding.probe, FakeAdapter("random"),
                     seeding.PER_EPISODE, ["s1", "s2"])
    check(ok, "a game that never reproduces a seed is caught",
          "passes 'two seeds differ' but a seed names nothing")

    print("\n  -- probe(): deterministic --")
    proof = seeding.probe(FakeAdapter("deterministic"), seeding.DETERMINISTIC, [])
    check("PROVEN" in proof, "a genuinely deterministic game PASSES", proof)

    ok, _ = raises(seeding.probe, FakeAdapter("random"), seeding.DETERMINISTIC, [])
    check(ok, "a game declared deterministic that ISN'T is caught")

    ok, msg = raises(seeding.probe, FakeAdapter("inert"), seeding.DETERMINISTIC, [])
    check(ok, "a probe that never moves the state is REFUSED as vacuous",
          "'identical' proves nothing if nothing happened (LESSONS O2)")

    print("\n  -- probe(): uncontrolled --")
    proof = seeding.probe(FakeAdapter("random"), seeding.UNCONTROLLED, [])
    check("uncontrolled" in proof, "a genuinely unseedable random game PASSES", proof)

    ok, _ = raises(seeding.probe, FakeAdapter("deterministic"), seeding.UNCONTROLLED, [])
    check(ok, "a game declared uncontrolled that actually REPLAYS is caught",
          "its episodes are replays being counted as samples")

    # ── sample_note(): the sentence that stops a bad denominator ─────────────
    print("\n  -- sample_note() --")
    note = seeding.sample_note(seeding.DETERMINISTIC, 8, 0)
    check("sample size is 1" in note,
          "a deterministic run says its effective sample size is 1", note)
    note = seeding.sample_note(seeding.PER_EPISODE, 8, 1)
    check("same scenario repeated" in note,
          "8 episodes on 1 seed is called out even in per_episode mode", note)
    note = seeding.sample_note(seeding.PER_EPISODE, 8, 8)
    check("independent samples" in note, "8 episodes on 8 seeds reads as samples", note)

    return gate.finish(
        "SEEDING PROOF",
        "Every guard rejects what it claims to reject and accepts what it claims to "
        "accept, including the two silent-failure shapes (seed ignored, seed "
        "unreproducible) and the vacuous-probe case.")


if __name__ == "__main__":
    sys.exit(main())
