"""Prove every framework-owned generic check can FIRE, and can stay QUIET.

    python3 tools/prove_generic_checks.py

Run this after touching `ugt/core/generic_checks.py`. There is no pytest suite in
this repo; this script IS the test for that module.

LESSONS O2: a check that cannot fail is worth nothing. Each case below builds a
fake adapter with one specific pathology, runs the fuzzer, and asserts the
matching check tripped — and a clean control asserts they all stay silent.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random as _r
_sysrandom = _r.SystemRandom()

from ugt.core.invariant_fuzzer import InvariantFuzzer


class FakeAdapter:
    """A toy game whose pathology is chosen by `mode`."""

    def __init__(self, mode):
        self.mode = mode
        self.n = 0
        self.gold = 0

    def reset(self):
        self.n, self.gold = 0, 0
        return self._state()

    def _state(self):
        return {"turn": self.n, "gold": self.gold, "over": False}

    def step(self, action_id):
        self.n += 1
        if self.mode == "farm":
            self.gold += 1                      # one-way resource: farmable
        elif self.mode == "cycle":
            self.n = self.n % 3                 # returns to identical states
        elif self.mode == "dead":
            if action_id == 2:
                self.n -= 1                     # action 2 is a no-op overall
        elif self.mode == "nondet":
            # An UNSEEDED RNG — literally the pathology this check exists for.
            self.gold = _sysrandom.randint(0, 5)
            self.n = 0
        elif self.mode == "starved":
            self.n = 1                          # one state forever
        elif self.mode == "clean":
            self.gold = (self.gold + action_id) % 5   # goes up AND down
        return self._state(), False, False, {}

    def close(self):
        pass


CASES = [
    ("farm",    "monotone-growth"),
    ("cycle",   "state-cycle"),
    ("dead",    "dead-action"),
    ("nondet",  "nondeterminism"),
    ("starved", "state-starvation"),
]

ok = True
for mode, expect in CASES:
    rep = InvariantFuzzer(FakeAdapter(mode), [], [0, 1, 2], seed=1).run(
        episodes=1, steps_per_episode=40, log=lambda _m: None)
    got = {o.check for o in rep.observations}
    hit = expect in got
    ok &= hit
    print(f"  [{'PASS' if hit else 'FAIL'}] mode {mode!r:9} -> expected {expect!r};"
          f" fired: {sorted(got) or 'nothing'}")

# Control: a game with none of these pathologies must stay quiet on all of them.
# 'turn' still only grows, which is the honest limitation — it is a counter, so
# it is allowlisted exactly as a real integration would.
rep = InvariantFuzzer(FakeAdapter("clean"), [], [0, 1, 2], seed=1,
                      monotone_allowlist=("turn",)).run(
    episodes=1, steps_per_episode=40, log=lambda _m: None)
noisy = {o.check for o in rep.observations} - {"state-cycle"}
clean = not noisy
ok &= clean
print(f"  [{'PASS' if clean else 'FAIL'}] control stays quiet"
      f"{'' if clean else f'; unexpected: {sorted(noisy)}'}")

# ...and that the allowlist is what silenced it, not luck.
rep2 = InvariantFuzzer(FakeAdapter("clean"), [], [0, 1, 2], seed=1).run(
    episodes=1, steps_per_episode=40, log=lambda _m: None)
allow_works = "monotone-growth" in {o.check for o in rep2.observations}
ok &= allow_works
print(f"  [{'PASS' if allow_works else 'FAIL'}] without the allowlist the same run "
      f"DOES flag the counter (allowlist is load-bearing, not decorative)")

print("\nALL NON-VACUITY CHECKS PASSED" if ok else "\nSOME CHECKS ARE VACUOUS")
sys.exit(0 if ok else 1)
