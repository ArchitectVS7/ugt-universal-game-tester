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

import argparse
import json
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


# ── loading a REAL retained trace (O-2) ──────────────────────────────────────
def load_trace(report_path, config_path=None):
    """Read a retained `playtest-report-<UTC>.json` into the trace shape above.

    Why this exists: every threshold in this file was tuned on SYNTHETIC shapes, and the
    file says so — "a threshold has to be re-checked against a real retained trace". Until
    2026-07-27 there was no way to do that, because this harness had no loader and no CLI.
    Retention (L-033) made real traces exist; this makes them usable.

    Returns (rows, meta). `rows` are exactly the dicts the detectors above consume, so a
    real trace and a synthetic one go through identical code — that equivalence is the
    whole point, and it is why no detector below is allowed to special-case a real run.

    NOTE the report is NOT self-describing: it records `state_delta` but not the
    `display_only_verbs` / `ignore_delta_fields` that decide what a *material* delta is.
    Pass --config to read them from the game's `ugt.config.yaml`; otherwise this falls
    back to the module constants and says so, loudly, because silently scoring a trace
    with the wrong materiality rule is exactly the vacuous-metric shape O2 warns about.
    """
    with open(report_path) as fh:
        report = json.load(fh)
    log = report.get("action_log") or []
    rows, forced, empty = [], 0, 0
    for e in log:
        action = (e.get("action") or "").strip()
        if e.get("forced_by_repeat_block"):
            forced += 1
        if not action:
            empty += 1
        rows.append({"step": e.get("step"), "action": action,
                     "state_delta": e.get("state_delta") or {}})
    meta = {
        "path": os.path.basename(report_path),
        "steps": len(rows),
        "forced_by_repeat_block": forced,
        "empty_actions": empty,
        "summary": report.get("summary") or {},
        "config_source": "module defaults (NO --config given)",
    }
    if config_path:
        try:
            sys.path.insert(0, REPO)
            from ugt.utils.config_parser import UgtConfig
            pt = (UgtConfig(config_path).data or {}).get("playtest") or {}
            global DISPLAY_ONLY, IGNORE_FIELDS
            DISPLAY_ONLY = set(pt.get("display_only_verbs") or DISPLAY_ONLY)
            IGNORE_FIELDS = set(pt.get("ignore_delta_fields") or IGNORE_FIELDS)
            meta["config_source"] = os.path.basename(config_path)
        except Exception as e:
            meta["config_source"] = f"FAILED to read {config_path}: {type(e).__name__}"
    return rows, meta


def report_real_trace(rows, meta) -> int:
    """Score a real trace and say plainly where it DIVERGES from the synthetic model.

    This is a report, not a gate. A real run is evidence, not a specification — it cannot
    "fail". What it CAN do is show that the synthetic trace no longer models the failure
    being designed against, which is a much more useful thing to learn early.
    """
    print(f"Replaying a REAL retained trace: {meta['path']}\n")
    print(f"  steps                     : {meta['steps']}")
    print(f"  materiality rule from     : {meta['config_source']}")
    print(f"    display_only_verbs      : {sorted(DISPLAY_ONLY)}")
    print(f"    ignore_delta_fields     : {sorted(IGNORE_FIELDS)}")
    print(f"  forced by repeat-block    : {meta['forced_by_repeat_block']}")
    print(f"  empty/no-op action rows   : {meta['empty_actions']}")

    fires = stall_signal(rows)
    adj = adjacency_guard(rows)
    dead = dead_targets(rows)
    blocked_n, suppressed = blocking_would_suppress(rows)
    mat = sum(1 for e in rows if material(e))
    futile_fraction = 1 - (mat / len(rows)) if rows else 0.0

    print("\n  -- detector output on the REAL trace --")
    print(f"  stall_signal fires        : {len(fires)}" + (f" (first at step {fires[0]})" if fires else ""))
    print(f"  adjacency_guard fires     : {len(adj)}")
    print(f"  distinct dead targets     : {len(dead)}  {sorted(dead)[:6]}")
    print(f"  futile step fraction      : {futile_fraction:.3f}")
    print(f"  if dead targets were BLOCKED: {blocked_n} blocked, "
          f"{suppressed} of them later WORK ({(suppressed / blocked_n * 100) if blocked_n else 0:.0f}% "
          f"would be play the guard destroyed)")

    # ── non-vacuity: the mirrored logic must reproduce the run's own numbers ──
    # These detectors are MIRRORED from playtester.py, not imported. If the mirror has
    # drifted, every number above is fiction. The report carries what the live loop
    # actually computed, so cross-check against it and say so either way.
    print("\n  -- cross-check: mirrored logic vs what the live run recorded --")
    s = meta["summary"] or {}
    pairs = [("stall_signal_steps", len(fires)), ("distinct_dead_targets", len(dead)),
             ("futile_step_fraction", round(futile_fraction, 3))]
    drift = []
    for key, mine in pairs:
        theirs = s.get(key)
        if theirs is None:
            print(f"  ?  {key}: not in this report — cannot cross-check")
            continue
        same = (abs(theirs - mine) < 0.002) if isinstance(mine, float) else (theirs == mine)
        print(f"  {'OK' if same else 'DRIFT'} {key}: replay={mine}  live={theirs}")
        if not same:
            drift.append(key)
    if drift:
        print(f"  ** The mirror has DRIFTED from playtester.py on {drift}. Fix the mirror before "
              f"trusting anything above — this file says the mirror is kept honest by exactly this. **")
    else:
        print("  => the mirror reproduces the live numbers, so the replay is measuring the real thing.")

    print("\n  -- divergence from the synthetic model this file proves against --")
    diverged = []
    if len(adj) == 0 and meta["forced_by_repeat_block"] > 0:
        diverged.append(
            f"adjacency_guard replays as 0 fires, but the live run recorded "
            f"{meta['forced_by_repeat_block']} repeat-blocks. Both are true and the gap is the point: "
            "**the retained trace is a POST-GUARD artifact.** The forced `wait` the guard injects is "
            "recorded as a step, so the run of identical picks is already broken in the log and can "
            "never re-trip the guard on replay. Consequence: this trace CANNOT be used to tune any "
            "guard that ACTS during a run — only report-only metrics replay faithfully. Note this also "
            "means the synthetic trace's 0-fires assertion and this 0 are different zeros: there, no "
            "guard ran; here, one already did.")
    if meta["empty_actions"] > 0:
        diverged.append(
            f"{meta['empty_actions']} rows have an empty action (the injected `wait`), which the "
            "synthetic trace has none of — so the oscillate-block-oscillate shape this run actually "
            "died of is not modelled at all. Worse, an empty action is being counted as a dead TARGET "
            "(see the list above), which is a metric artifact, not a finding about the game.")
    distinct = len({e["action"] for e in rows if e["action"]})
    if distinct < 40:
        diverged.append(
            f"only {distinct} distinct actions across {meta['steps']} steps; the synthetic dead-target "
            "pool alone is ~38, so the diversity assumption does not hold either.")
    if diverged:
        for i, d in enumerate(diverged, 1):
            print(f"  {i}. {d}")
        print("\n  => Thresholds tuned on the synthetic trace should NOT be carried onto this shape "
              "without re-deriving them here. That is the finding, and it is why this loader exists.")
    else:
        print("  none — the synthetic model still describes this run's failure shape.")
    print("\n(Reported, not gated: a real run is evidence, not a specification.)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Stall-detection proof, and real-trace replay")
    ap.add_argument("--trace", help="a retained playtest-report-<UTC>.json to replay")
    ap.add_argument("--config", help="that game's ugt.config.yaml, for the materiality rule")
    args = ap.parse_args()
    if args.trace:
        rows, meta = load_trace(args.trace, args.config)
        if not rows:
            print(f"[FAIL] {args.trace} has no action_log entries — nothing to replay.")
            return 1
        return report_real_trace(rows, meta)

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
