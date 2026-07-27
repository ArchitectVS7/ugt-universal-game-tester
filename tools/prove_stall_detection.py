#!/usr/bin/env python3
"""Proof harness for stall detection — the run-level signal AND the design
finding that says what must NOT be built.

    python3 tools/prove_stall_detection.py

There is no pytest in this repo. This file replays action-log traces through the
detector logic and asserts what it does, in both directions: it must fire on a
stalling run and stay silent on a healthy one. It also PINS a negative result —
that a per-target futility BLOCK is wrong for a game whose gates open over
time — because that is the fix everyone reaches for first, and the reason not to
build it is not visible in the code that exists.

Traces here are synthetic, and deliberately labelled as such. They model shapes
recorded in a findings log; they are not recordings. Their job is to prove the
detector's LOGIC, never to justify a threshold — a threshold has to be re-checked
against a real retained trace (which is why report retention landed first).

Re-run after touching the stall window, the ledger, or `display_only_verbs`
handling in `ugt/core/playtester.py`.
"""
from __future__ import annotations

import os
import random
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from ugt.core.trial import GateRunner  # noqa: E402

gate = GateRunner()


def check(ok, label, detail=""):
    return gate.ck(label, ok, detail)


# ── the logic under test, mirrored from playtester.py ────────────────────────
# Mirrored rather than imported because the loop body is a 400-line function with
# a live adapter in it. The invariant that keeps this honest: the rules below are
# small enough to read side by side with the source, and any drift shows up as a
# behaviour change in the live channel check that runs in the same gate sweep.
DISPLAY_ONLY = {"ls", "analyze"}
IGNORE_FIELDS = {"rngCounter", "turn_number"}


def material(entry) -> bool:
    sd = entry.get("state_delta") or {}
    return bool({k: v for k, v in sd.items() if k not in IGNORE_FIELDS})


def stall_signal(log, window=20, floor=0.20):
    """D3: does the RUN advance? Returns the steps at which it fired."""
    fires, recent = [], []
    for e in log:
        recent.append(1 if material(e) else 0)
        if len(recent) > window:
            recent.pop(0)
        if len(recent) == window and sum(recent) / window < floor:
            fires.append(e["step"])
            recent.clear()
    return fires


def adjacency_guard(log, threshold=3):
    """What already ships: N identical picks in a row."""
    fires, streak, last = [], 0, None
    for e in log:
        a = e["action"].strip().lower()
        streak = streak + 1 if a == last else 1
        last = a
        if streak >= threshold:
            fires.append(e["step"])
            streak = 0
    return fires


def dead_targets(log, threshold=3, respect_display_only=True):
    """The ledger's `distinct_dead_targets`: keys tried >= N with zero material
    effect. INFORMATION — never a veto. See `blocking_would_suppress` below."""
    tries, productive = {}, {}
    for e in log:
        action = e["action"].strip()
        verb = action.split(" ", 1)[0].lower()
        if respect_display_only and verb in DISPLAY_ONLY:
            continue
        k = action.lower()
        tries[k] = tries.get(k, 0) + 1
        if material(e):
            productive[k] = productive.get(k, 0) + 1
    return {k for k, n in tries.items() if n >= threshold and productive.get(k, 0) == 0}


def blocking_would_suppress(log, threshold=3):
    """If a dead target were BLOCKED on its Nth futile try, how many blocked keys
    later go on to work? Every one of those is play the guard destroyed."""
    futile, blocked, suppressed = {}, [], 0
    for e in log:
        k = e["action"].strip().lower()
        if k.split(" ", 1)[0] in DISPLAY_ONLY:
            continue
        if material(e):
            futile[k] = 0
            continue
        futile[k] = futile.get(k, 0) + 1
        if futile[k] >= threshold and k not in [b[0] for b in blocked]:
            blocked.append((k, e["step"]))
    for k, step in blocked:
        if any(e["action"].strip().lower() == k and e["step"] > step and material(e) for e in log):
            suppressed += 1
    return len(blocked), suppressed


# ── traces (SYNTHETIC — shapes, not recordings) ──────────────────────────────
def healthy_trace():
    """A run that works: recon interleaved with real progress, including the
    repeated `ls` that legitimately never moves structured state."""
    seq = [("accept m1", 1), ("scan", 1), ("connect 10.0.0.1", 1), ("ls", 0),
           ("analyze", 0), ("exploit weak_password", 1), ("cat /etc/hosts", 1),
           ("ls", 0), ("escalate", 1), ("ls", 0), ("download /f", 1),
           ("connect 10.0.0.2", 1), ("ls", 0), ("exploit weak_password", 1),
           ("cat /b", 1), ("ls", 0), ("progress", 0), ("missions", 0),
           ("scan", 1), ("escalate", 1)]
    return [{"step": i + 1, "action": a,
             "state_delta": {"rngCounter": "+1", **({"xp": "+5"} if ok else {})}}
            for i, (a, ok) in enumerate(seq)]


def diffuse_stall_trace(n=600, seed=7):
    """The documented diffuse shape: one verb re-run dozens of times, plus many
    DIFFERENT dead targets each tried 1-3x, never 3 identical in a row."""
    rng = random.Random(seed)
    dead = ([f"connect 10.{i}.0.{j}" for i in range(4) for j in range(5)]
            + [f"cat /classified/f{i}.txt" for i in range(12)]
            + [f"talk npc{i}" for i in range(6)])
    good = ["scan", "exploit weak_password", "cat /etc/hosts", "escalate"]
    log = []
    while len(log) < n:
        r = rng.random()
        action, ok = ("progress", False) if r < 0.30 else (
            (rng.choice(dead), False) if r < 0.80 else (rng.choice(good), True))
        if len(log) >= 2 and log[-1]["action"] == action == log[-2]["action"]:
            action, ok = rng.choice(dead), False
        log.append({"step": len(log) + 1, "action": action,
                    "state_delta": {"rngCounter": "+1", **({"xp": "+5"} if ok else {})}})
    return log


def story_gated_trace(n=400, seed=3):
    """Targets that refuse now and become playable after an unlock beat — how a
    story-gated game actually behaves."""
    rng = random.Random(seed)
    gated = [f"connect 10.9.0.{i}" for i in range(6)]
    unlock_at = {t: rng.randint(60, 320) for t in gated}
    unlocked, log = set(), []
    for step in range(1, n + 1):
        for t, u in unlock_at.items():
            if step == u:
                unlocked.add(t)
        a = rng.choice(gated + ["scan", "progress", "ls"])
        ok = a in unlocked or a == "scan"
        log.append({"step": step, "action": a,
                    "state_delta": {"rngCounter": "+1", **({"xp": "+5"} if ok else {})}})
    return log


def main() -> int:
    print("Proving stall detection — and pinning the fix that must NOT be built\n")
    healthy, stall, gated = healthy_trace(), diffuse_stall_trace(), story_gated_trace()

    # ── the run-level signal, both directions ───────────────────────────────
    print("  -- D3 run-level stall signal --")
    fires_h = stall_signal(healthy)
    check(len(fires_h) == 0, "stays SILENT on a healthy run (no false positive)",
          f"{len(fires_h)} fires over {len(healthy)} steps")
    fires_s = stall_signal(stall)
    check(len(fires_s) > 0, "FIRES on a diffuse stall", f"{len(fires_s)} fires, first at step {fires_s[0]}")
    check(fires_s and fires_s[0] <= 40, "fires EARLY enough to be actionable",
          f"first fire at step {fires_s[0]} of {len(stall)}")

    # Mutation: neutralise the floor and the signal must go silent.
    check(len(stall_signal(stall, floor=0.0)) == 0,
          "MUTATION: floor=0 silences it (the threshold is what does the work)")

    # ── the adjacency guard's blind spot, reproduced ────────────────────────
    print("\n  -- why the existing guard was not enough --")
    adj = adjacency_guard(stall)
    check(len(adj) == 0, "the ADJACENCY guard fires 0x on the diffuse stall",
          "this is the documented blind spot; if this ever goes non-zero the "
          "trace stopped modelling the failure and the proof below is vacuous")
    check(len(stall_signal(stall)) > len(adj),
          "the run-level signal catches what adjacency cannot")

    # ── display-only handling is load-bearing, not a nicety ─────────────────
    print("\n  -- display-only verbs --")
    with_rule = dead_targets(healthy, respect_display_only=True)
    without_rule = dead_targets(healthy, respect_display_only=False)
    check(len(with_rule) == 0, "healthy run has NO dead targets when display-only is respected",
          f"{sorted(with_rule)}")
    check("ls" in without_rule,
          "MUTATION: drop the rule and legitimate recon is wrongly called dead",
          f"'ls' flagged after {sum(1 for e in healthy if e['action'] == 'ls')} honest listings")

    # ── the pinned NEGATIVE result ──────────────────────────────────────────
    print("\n  -- why futility must INFORM and never BLOCK --")
    found = dead_targets(stall)
    check(len(found) > 0, "dead targets ARE identifiable on a stalling run",
          f"{len(found)} distinct targets tried >=3x with zero effect")
    blocked, suppressed = blocking_would_suppress(gated)
    check(suppressed > 0,
          "on a STORY-GATED run, blocking those targets destroys real play",
          f"{suppressed} of {blocked} blocks would suppress a target that later works")
    check(suppressed >= blocked * 0.5,
          "and it is the common case, not an edge case — so no threshold rescues it",
          f"{suppressed}/{blocked} = {suppressed / blocked:.0%} of blocks are wrong")
    print("     => `distinct_dead_targets` is REPORTED, never enforced. If a future "
          "change\n        turns it into a veto, the two checks above are what should stop it.")

    return gate.finish(
        "STALL DETECTION PROOF",
        "The run-level signal fires on a diffuse stall and stays silent on a healthy "
        "run; the adjacency guard's blind spot is reproduced; display-only handling is "
        "shown load-bearing; and blocking dead targets is shown to destroy legitimate "
        "play on a story-gated game, which is why the metric only ever reports.")


if __name__ == "__main__":
    sys.exit(main())
