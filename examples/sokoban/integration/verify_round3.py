#!/usr/bin/env python3
"""Rung 5 (R3) — robustness: UGT's real ExploitHunter against the live bridge.

    python3 examples/sokoban/integration/verify_round3.py

Uniform-random walks over the 4 real actions plus deliberately illegal ids, with
`invariants.py` asserted after every step — the SAME predicates R1/R2 use, via
`InvariantSuite.to_hunter_invariants()`, so the scripted and random tiers cannot
disagree about what correct means.

Sokoban has no RNG, so the same-seed replay check is not about the game: it
proves the ADAPTER AND BRIDGE add no nondeterminism of their own (socket
buffering, message reordering, reused state).
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
from ugt.core.exploit_hunter import ExploitHunter  # noqa: E402

ACTIONS = {0: "up", 1: "down", 2: "left", 3: "right"}
STEPS = 120          # PRD asks for >= 100
SEEDS = (0, 1)

checks: list[tuple[bool, str, str]] = []


def check(ok, label, detail=""):
    checks.append((bool(ok), label, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))


def replay(seq, port_hint=None):
    """Run a fixed action sequence from a fresh reset; return every state."""
    ad = GodotTcpAdapter()
    ad.connect()
    try:
        out = [ad.reset()]
        for a in seq:
            st, _t, _tr, _i = ad.step(a)
            out.append(st)
        return out
    finally:
        ad.close()


def main() -> int:
    print("Sokoban R3 — exploit hunter against the live bridge\n")
    hunter_invariants = SUITE.to_hunter_invariants()
    print(f"  ({len(hunter_invariants)} invariants, shared with R1/R2)\n")

    # ---- random walks --------------------------------------------------------
    print("  -- random walks --")
    total_steps = 0
    for seed in SEEDS:
        ad = GodotTcpAdapter()
        hunter = ExploitHunter(ad, hunter_invariants, list(ACTIONS),
                               action_names=ACTIONS, seed=seed)
        rep = hunter.run(episodes=1, steps_per_episode=STEPS, log=lambda m: None)
        try:
            ad.close()
        except Exception:
            pass
        total_steps += STEPS
        n = len(rep.findings)
        check(n == 0, f"seed {seed}: {STEPS} uniform-random steps, 0 findings",
              "" if n == 0 else "; ".join(f"{f.name}: {f.detail}" for f in rep.findings[:3]))

    # ---- illegal / malformed actions ----------------------------------------
    print("\n  -- illegal action ids --")
    ad = GodotTcpAdapter()
    ad.connect()
    try:
        base = ad.reset()
        inert = True
        details = []
        for bad in (-1, 4, 99, 10**9):
            before = ad._read_state()
            after, _t, _tr, _i = ad.step(bad)
            if after != before:
                inert = False
                details.append(f"action_id={bad} mutated state")
        check(inert, "every illegal action_id is completely inert (state-identical)",
              "; ".join(details) if details else "-1, 4, 99, 1e9 all no-ops")
        check(ad.reset()["moves_taken"] == 0, "the bridge is still healthy after abuse")
    finally:
        ad.close()

    # ---- determinism ---------------------------------------------------------
    print("\n  -- determinism (adapter/bridge add no nondeterminism) --")
    seq = [0, 2, 2, 0, 3, 1, 2, 0, 0, 3, 1, 1, 2, 3, 0]
    a = replay(seq)
    b = replay(seq)
    same = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    check(same, "two fresh processes replay the same actions byte-identically",
          "" if same else f"first divergence at index "
                          f"{next(i for i,(x,y) in enumerate(zip(a,b)) if x!=y)}")
    distinct = len({json.dumps(s, sort_keys=True) for s in a})
    check(distinct > 1, "the determinism proof is NON-VACUOUS (state actually moved)",
          f"{distinct} distinct states over {len(a)} steps")

    # ---- the suite must be able to fail --------------------------------------
    print("\n  -- non-vacuity of the invariant suite --")
    good = a[-1]
    bad = dict(good)
    bad["moves_taken"] = -1
    bad["boxes_on_target"] = bad["boxes_total"] + 3
    fired = SUITE.check_command(good, bad, "synthetic", {})
    check(bool(fired), "the shared invariant suite FIRES on a corrupted transition",
          f"{len(fired)} violation(s): {fired[:2]}")

    passed = sum(1 for ok, _, _ in checks if ok)
    total = len(checks)
    print("\n" + "=" * 70)
    if passed == total:
        print(f"ROUND 3 MET — {passed}/{total} checks. UGT's real ExploitHunter drove the live "
              f"Godot bridge for {total_steps} random steps across {len(SEEDS)} seeds with zero "
              f"findings, every illegal action id was proven state-inert, two fresh processes "
              f"replay byte-identically, and the invariant suite was shown able to fail.")
        return 0
    print(f"ROUND 3 NOT MET — {passed}/{total} checks.")
    for ok, label, detail in checks:
        if not ok:
            print(f"  FAILED: {label}  {detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
