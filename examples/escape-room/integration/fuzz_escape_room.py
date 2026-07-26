#!/usr/bin/env python3
"""Tier 2 — robustness. Random-walk the real Tiny Escape Room bridge and assert
invariants after every single step, then prove the run is reproducible.

Run from anywhere:  python3 examples/escape-room/integration/fuzz_escape_room.py

What this does NOT do: re-implement a rule. Every action goes over the real
JSON-lines wire to ../game/src/bridge.js, and every invariant is a statement
about the state the GAME returned, never about what this script thinks should
have happened.

Three checks, all of which must pass for exit 0:

  1. Two independent random walks (seeds 0 and 1), >= 150 steps each, with the
     invariants below asserted after every step.
  2. A negative control: the same invariants run against a deliberately
     corrupted state transition and MUST fire. An invariant suite that has
     never been seen to fail is not evidence of anything (LESSONS O2).
  3. Same-seed determinism: seed 0 replayed twice must produce a byte-identical
     state stream. This game has no RNG, so any divergence would be the
     HARNESS's nondeterminism (dict/set iteration order, uninitialised reuse),
     which is exactly what makes the check worth running here.
"""
from __future__ import annotations

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
GAME = os.path.abspath(os.path.join(HERE, "..", "game"))
sys.path.insert(0, REPO)

from ugt.adapters.subprocess import SubprocessAdapter  # noqa: E402
from ugt.core.invariant_fuzzer import InvariantFuzzer, Invariant  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

STEPS_PER_EPISODE = 160  # T-004 requires >= 150
EPISODES = 1
SEEDS = (0, 1)


def valid_room_ids() -> set[str]:
    """Read the room ids from the GAME's own content, so this can never drift
    from the shipped CSV the way a hardcoded list would."""
    with open(os.path.join(GAME, "content", "rooms.csv"), newline="") as fh:
        return {row["room_id"] for row in csv.DictReader(fh)}


ROOMS = valid_room_ids()


# ── invariants ────────────────────────────────────────────────────────────────
# Signature is the hunter's: (before, action_id, info, after, ctx) -> message or
# "" / None when the property holds.

def moves_never_decrease(before, action_id, info, after, ctx):
    """moves_taken is monotonic non-decreasing."""
    if after["moves_taken"] < before["moves_taken"]:
        return f"moves_taken went backwards: {before['moves_taken']} -> {after['moves_taken']}"
    return ""


def moves_advance_by_at_most_one(before, action_id, info, after, ctx):
    """A single command consumes at most one move."""
    delta = after["moves_taken"] - before["moves_taken"]
    if delta > 1:
        return f"one action advanced moves_taken by {delta} (expected 0 or 1)"
    return ""


def rooms_visited_never_decreases(before, action_id, info, after, ctx):
    """rooms_visited is monotonic non-decreasing."""
    if after["rooms_visited"] < before["rooms_visited"]:
        return (f"rooms_visited went backwards: "
                f"{before['rooms_visited']} -> {after['rooms_visited']}")
    return ""


def current_room_is_real(before, action_id, info, after, ctx):
    """current_room is always a room_id defined in the game's rooms.csv."""
    room = after.get("current_room")
    if room not in ROOMS:
        return f"current_room {room!r} is not one of {sorted(ROOMS)}"
    return ""


def escaped_never_reverts(before, action_id, info, after, ctx):
    """escaped latches: once true it can never go back to false."""
    if before.get("escaped") and not after.get("escaped"):
        return "escaped reverted from True to False"
    return ""


def flags_never_unset(before, action_id, info, after, ctx):
    """A set flag is never cleared — the whole puzzle chain depends on latching."""
    for name, was in (before.get("flags") or {}).items():
        if was and not (after.get("flags") or {}).get(name):
            return f"flag {name!r} reverted from True to False"
    return ""


PREDICATES = [
    moves_never_decrease,
    moves_advance_by_at_most_one,
    rooms_visited_never_decreases,
    current_room_is_real,
    escaped_never_reverts,
    flags_never_unset,
]
INVARIANTS = [Invariant(p.__name__, p, p.__doc__ or "") for p in PREDICATES]


def make_adapter() -> SubprocessAdapter:
    cfg = UgtConfig(os.path.join(HERE, "ugt.config.yaml"))
    return SubprocessAdapter(cfg)


def state_stream(seed: int, steps: int) -> list:
    """Drive a fixed pseudo-random action sequence and record every state."""
    import random

    cfg = UgtConfig(os.path.join(HERE, "ugt.config.yaml"))
    ids = sorted(int(k) for k in cfg.action_mappings)
    rng = random.Random(seed)
    adapter = make_adapter()
    adapter.connect()
    try:
        stream = [adapter.reset()]
        for _ in range(steps):
            state, _term, _trunc, _info = adapter.step(rng.choice(ids))
            stream.append(state)
        return stream
    finally:
        adapter.close()


def main() -> int:
    checks: list[tuple[bool, str, str]] = []

    def record(ok: bool, label: str, detail: str = "") -> None:
        checks.append((ok, label, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))

    print(f"Tier 2 — exploit hunt against the real bridge ({len(ROOMS)} rooms, "
          f"{len(PREDICATES)} invariants)\n")

    # ── 1. random walks ───────────────────────────────────────────────────────
    print("  -- random walks --")
    cfg = UgtConfig(os.path.join(HERE, "ugt.config.yaml"))
    action_ids = sorted(int(k) for k in cfg.action_mappings)
    names = {int(k): v.get("name", str(k)) if isinstance(v, dict) else str(v)
             for k, v in cfg.action_mappings.items()}

    for seed in SEEDS:
        adapter = make_adapter()
        hunter = InvariantFuzzer(adapter, INVARIANTS, action_ids,
                               action_names=names, seed=seed)
        report = hunter.run(episodes=EPISODES, steps_per_episode=STEPS_PER_EPISODE,
                            log=lambda m: None)
        try:
            adapter.close()
        except Exception:
            pass
        n = len(report.findings)
        record(n == 0, f"seed {seed}: {EPISODES}x{STEPS_PER_EPISODE} random steps, 0 findings",
               "" if n == 0 else f"{n} finding(s): " +
               "; ".join(f"{f.name}: {f.detail}" for f in report.findings[:3]))

    # ── 2. negative control ───────────────────────────────────────────────────
    # Every invariant above must be capable of firing. Feed each a transition it
    # is supposed to reject; a predicate that stays silent here is decoration.
    print("\n  -- negative control (invariants MUST fire) --")
    good = {"moves_taken": 5, "rooms_visited": 3, "current_room": "R02",
            "escaped": True, "flags": {"has_oil": True}}
    corrupt = {
        "moves_never_decrease":          {**good, "moves_taken": 4},
        "moves_advance_by_at_most_one":  {**good, "moves_taken": 9},
        "rooms_visited_never_decreases": {**good, "rooms_visited": 2},
        "current_room_is_real":          {**good, "current_room": "R99"},
        "escaped_never_reverts":         {**good, "escaped": False},
        "flags_never_unset":             {**good, "flags": {"has_oil": False}},
    }
    silent = [p.__name__ for p in PREDICATES
              if not p(good, 0, {}, corrupt[p.__name__], {})]
    record(not silent, f"all {len(PREDICATES)} invariants fire on a corrupted transition",
           "" if not silent else f"silent (cannot fail): {silent}")

    # ...and must NOT fire on a legitimate transition, or every run is noise.
    legit = {**good, "moves_taken": 6, "rooms_visited": 4}
    noisy = [p.__name__ for p in PREDICATES if p(good, 0, {}, legit, {})]
    record(not noisy, "no invariant fires on a legitimate transition",
           "" if not noisy else f"false positives: {noisy}")

    # ── 3. determinism ────────────────────────────────────────────────────────
    print("\n  -- determinism --")
    a = state_stream(0, 60)
    b = state_stream(0, 60)
    same = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    first_div = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
    record(same, "same-seed replay is byte-identical",
           "" if same else f"first divergence at index {first_div}")
    # A determinism claim over a stream that never moved would be vacuous.
    moved = len({json.dumps(s, sort_keys=True) for s in a}) > 1
    record(moved, "the determinism proof is NON-VACUOUS (state actually changed)",
           f"{len({json.dumps(s, sort_keys=True) for s in a})} distinct states over {len(a)} steps")

    passed = sum(1 for ok, _, _ in checks if ok)
    total = len(checks)
    print("\n" + "=" * 70)
    if passed == total:
        print(f"TIER 2 MET — {passed}/{total} checks. No invariant broke under random "
              f"pressure across {len(SEEDS)} seeds, every invariant was proven able to "
              f"fail, and the run replays byte-identically.")
        return 0
    print(f"TIER 2 NOT MET — {passed}/{total} checks.")
    for ok, label, detail in checks:
        if not ok:
            print(f"  FAILED: {label}  {detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
