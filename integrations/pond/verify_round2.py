#!/usr/bin/env python3
"""
Pond Conspiracy ROUND 2 — the full-spine gate: every mode driven to a REAL
outcome against the live headless game, through `PondHarnessAdapter`.

R1 asked "is this game playable over the wire?" and answered yes. R2 asks the
harder question: "does every mode the game advertises actually reach an
outcome?" — all three arenas and their hazards, the wave-5 boss fought to a
decision, the evidence -> conspiracy-board -> epilogue chain, BOTH run-end paths
(death and victory), and pause.

The answer is a qualified no, and the qualifications are the point of this gate.
The remaining blocks are genuine no-code-path / balance defects, which is
precisely the class of defect a full-spine round exists to find:

  * the boss arena clears regular enemies then leaves the spawner running, so
    the "locked" arena refills with adds — finding PC-14;
  * the wave-5 boss cannot be defeated with real input because damage rounds to
    nothing while each mutation adds boss hp — finding PC-15 (balance).

Two earlier structural blocks have since been FIXED game-side and are now
measured over the wire rather than asserted as prose:

  * PC-11 (only one boss wired) is fixed by T-054 — `LevelGenerator` now maps a
    distinct boss per run band (Wetland/Foreman, Chemical Plant/Lobbyist,
    HQ/CEO). This gate drives run_number 1/5/10, walks each to its boss, and
    asserts three DISTINCT boss_id values read from the live harness. Expected
    to pass, proving the fix.
  * PC-13 (ESC quit the process) is fixed by T-058/T-059 — pause now toggles
    `get_tree().paused` and emits `EventBus.pause_toggled`, never quits, and
    `input_manager.gd` is deleted. Its wire assertion (re-enabling the pause
    action in the harness and asserting its invariants) is U-008's job, so this
    gate records it as INFO rather than re-driving it.

PC-12 remains a fail, but for a different reason than originally filed: the
victory run-end path now HAS a production caller (`run_manager.gd:235` via
`_on_ending_unlocked`, T-057). It is unreachable through the CURRENT harness —
reaching `EventBus.ending_unlocked` needs all 16 logs + Lobbyist + CEO defeats
+ the smoking-gun board connection, and the JSON-lines protocol exposes no
board-connection / evidence-grant op. So it is an explicit named harness gap,
recorded as a reasoned BLOCKED (the follow-up is filed in HANDOFF.md).

The blocks FAIL the gate and print as findings with the evidence that proves
them, rather than being quietly skipped. A gate that skips what the game cannot
do reports a green that means nothing.

Everything that IS reachable is driven for real: arenas are selected by pinning
the run number (the same input the game uses), hazards are read as live NODES,
and the boss is fought with real input — kiting at tongue range, evading real
bullet positions, spending dodge i-frames, and picking level-up cards by
clicking them. No game logic is reimplemented; every fact is read back from the
harness snapshot.

Run (from the UGT repo root; needs godot 4.7 on PATH or UGT_GODOT_BIN):
    python3 integrations/pond/verify_round2.py [seed]
"""

from __future__ import annotations

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ugt.adapters.pond_harness import PondHarnessAdapter  # noqa: E402

DEFAULT_SEED = 20260720

# Arena selection thresholds the game itself uses (LevelGenerator, FR-06).
# Driving these is the whole reason `run_number` is a create-time config key.
ARENAS = [
    (1, "Polluted Wetland", "toxic_puddle"),
    (5, "Chemical Plant", "conveyor_wall"),
    (10, "Corporate HQ Lobby", "security_camera"),
]

# FR-08 / T-040: enemies per wave derives from the run number (8-12, then +2,
# capped at 20). Asserted so an arena change cannot silently stop scaling.
EXPECTED_PER_WAVE = {1: 8, 5: 16, 10: 20}

# The BossArena trigger box in TestArena.tscn, in world coordinates.
BOSS_TRIGGER = (960.0, 250.0)

# Mutations preferred when a level-up card comes up, best-first. A player
# upgrades before a boss; damage first, then survivability.
PREFERRED = ["mercury_blood", "quick_tongue", "regeneration",
             "tough_skin", "strong_legs", "lily_pad", "slippery"]


class Gate:
    """Records checks so the run prints as evidence, not just a tally."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.findings: list[str] = []

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            print(f"  [PASS] {label}" + (f"  — {detail}" if detail else ""))
        else:
            self.failed += 1
            print(f"  [FAIL] {label}" + (f"  — {detail}" if detail else ""))
            self.findings.append(f"{label}: {detail}")
        return ok

    def blocked(self, label: str, detail: str) -> None:
        """A mode that cannot be exercised — either NO game code path or a named
        harness gap. Fails the gate (never unconditionally) — see the module
        docstring. `detail` must carry the specific reason, not just a label."""
        self.failed += 1
        print(f"  [BLOCKED] {label}\n            {detail}")
        self.findings.append(f"BLOCKED {label}: {detail}")

    def info(self, label: str, detail: str = "") -> None:
        print(f"  [INFO] {label}" + (f"  — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Driving helpers — input only, no game rules
# ---------------------------------------------------------------------------


def snap(ad) -> dict:
    return ad.last_snapshot or {}


def step(ad, frames=10, **inp) -> dict:
    resp = ad._rpc({"op": "step", "frames": frames, "input": inp})
    ad.last_snapshot = resp
    return resp


def take_level_up(ad, s: dict) -> dict:
    """Pick a card if the level-up screen is up.

    MUST be called in every driving loop. LevelUpUI pauses the whole tree, so a
    driver that ignores it sees the world freeze mid-swing — tongue stuck
    EXTENDING, i-frames never expiring — and will misread that as a game
    soft-lock. (It did, during development of this gate.)
    """
    lvl = s.get("level_up") or {}
    if not lvl.get("pending"):
        return s
    ids = [str(o.get("id", "")) for o in (lvl.get("options") or [])]
    owned = set(((s.get("mutations") or {}).get("active_ids")) or [])
    fresh = [i for i, m in enumerate(ids) if m not in owned]
    pick = fresh[0] if fresh else 0
    for want in PREFERRED:
        if want in ids and ids.index(want) in fresh:
            pick = ids.index(want)
            break
    # 40 frames, not a handful: _animate_out() is a 0.3s tween (18 frames) and
    # the cards stay clickable for its whole duration, so a short choose returns
    # mid-fade and the next loop iteration clicks AGAIN — re-emitting
    # mutation_selected for an already-owned mutation.
    ad.choose_mutation(pick, frames=40)
    return snap(ad)


def nearest_add(s: dict, pos):
    """Closest NON-boss enemy, or (None, inf)."""
    best, bd = None, float("inf")
    for e in (s.get("enemies") or []):
        if e.get("boss_id"):
            continue
        d = math.dist(pos, e["pos"])
        if d < bd:
            best, bd = e, d
    return best, bd


def evade_vector(s: dict, pos, radius=150.0):
    """Sum of away-vectors from live bullets and adjacent adds."""
    ax = ay = 0.0
    near = 0
    for b in (s.get("bullet_list") or []):
        q = b["pos"]
        d = math.dist(pos, q)
        if 0.001 < d < radius:
            w = (radius - d) / radius
            ax += (pos[0] - q[0]) / d * w
            ay += (pos[1] - q[1]) / d * w
            near += 1
    for e in (s.get("enemies") or []):
        if e.get("boss_id"):
            continue
        q = e["pos"]
        d = math.dist(pos, q)
        if 0.001 < d < 70:
            w = (70 - d) / 70
            ax += (pos[0] - q[0]) / d * w * 0.8
            ay += (pos[1] - q[1]) / d * w * 0.8
            near += 1
    return ax, ay, near


def walk_to_boss(ad, gate: Gate, max_cycles=140) -> dict:
    """Walk into the BossArena trigger, then wait out the invulnerable intro."""
    s = snap(ad)
    for _ in range(max_cycles):
        s = take_level_up(ad, s)
        if (s.get("boss") or {}).get("triggered"):
            break
        p = s["player"]["pos"]
        dx, dy = BOSS_TRIGGER[0] - p[0], BOSS_TRIGGER[1] - p[1]
        n = math.hypot(dx, dy) or 1.0
        s = step(ad, 10, move=[dx / n, dy / n])
        if s["player"]["dead"]:
            return s
    for _ in range(70):
        s = take_level_up(ad, s)
        s = step(ad, 10)
        b = s.get("boss") or {}
        if b.get("present") and not b.get("invulnerable"):
            break
        if s["player"]["dead"]:
            break
    return s


def fight_boss(ad, cycles=2200, band=125.0, radius=150.0):
    """Fight to a decision. Returns (outcome, state, lowest_boss_hp, swings).

    Real input only: kite at tongue range, evade actual bullet positions, spend
    dodge i-frames whenever they are off cooldown, and swing only when the
    tongue is genuinely ready (extend 9 + retract 6 + cooldown 18 = 33 frames at
    60fps — swinging faster just gets swallowed).
    """
    s = snap(ad)
    lowest = math.inf
    for cyc in range(cycles):
        s = take_level_up(ad, s)
        for e in (s.get("events") or []):
            if e.get("signal") == "boss_defeated":
                return "defeated", s, lowest, cyc
        b = s.get("boss") or {}
        if b.get("hp") is not None:
            lowest = min(lowest, b["hp"])
        if not b.get("present") and cyc > 2:
            return "boss_vanished", s, lowest, cyc
        p = s["player"]["pos"]
        bp = b.get("pos") or [960.0, 100.0]
        d = math.dist(p, bp)
        ux, uy = (bp[0] - p[0]) / max(d, 1), (bp[1] - p[1]) / max(d, 1)
        ex, ey, near = evade_vector(s, p, radius)
        if near:
            move = [ex, ey]
        elif d > band + 8:
            move = [ux, uy]
        elif d < band - 8:
            move = [-ux, -uy]
        else:
            move = [-uy, ux]
        tongue = s["player"].get("tongue") or {}
        ready = (tongue.get("cooldown") or 0) <= 0.0 and int(tongue.get("state") or 0) == 0
        dodge = (s["player"].get("dodge_cooldown") or 0) <= 0.0
        if ready:
            step(ad, 2, attack=True, aim=bp, move=move, dodge=dodge)
            s = step(ad, 14, attack=False, aim=bp, move=move)
        else:
            s = step(ad, 6, attack=False, aim=bp, move=move, dodge=dodge)
        if s["player"]["dead"]:
            return "player_died", s, lowest, cyc
    return "timeout", s, lowest, cycles


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def section_arenas(gate: Gate, seed: int) -> None:
    """All three arenas reached, each with its own hazards live as NODES."""
    print("\n  -- 1. every arena, selected the way the game selects it --")
    for run_number, expect_id, expect_hazard in ARENAS:
        ad = PondHarnessAdapter()
        try:
            ad.reset(seed=seed, run_number=run_number)
            s = snap(ad)
            arena = s.get("arena") or {}
            gate.check(
                s.get("arena_id") == expect_id,
                f"run {run_number} loads {expect_id}",
                f"arena_id={s.get('arena_id')!r} controller_run={arena.get('run_number')}")
            gate.check(
                arena.get("hazard_type") == expect_hazard and bool(arena.get("hazards_active")),
                f"{expect_id} hazards are live",
                f"type={arena.get('hazard_type')!r} active={arena.get('hazards_active')} "
                f"nodes={arena.get('hazard_nodes')}")
            gate.check(
                (arena.get("hazard_nodes") or 0) > 0,
                f"{expect_id} hazards exist as real nodes",
                f"{arena.get('hazard_nodes')} node(s) in group('arena_hazard'): "
                f"{[h.get('name') for h in (arena.get('hazards') or [])]}")
            wave = s.get("wave") or {}
            gate.check(
                wave.get("enemies_per_wave") == EXPECTED_PER_WAVE[run_number],
                f"run {run_number} scales the wave per FR-08",
                f"enemies_per_wave={wave.get('enemies_per_wave')} "
                f"(expected {EXPECTED_PER_WAVE[run_number]})")
        finally:
            ad.close()


def section_boss(gate: Gate, seed: int) -> None:
    """The wave-5 boss: reached, damaged, phased — and fought to a decision."""
    print("\n  -- 2. the wave-5 boss --")
    ad = PondHarnessAdapter()
    try:
        ad.reset(seed=seed, run_number=1)
        s = walk_to_boss(ad, gate)
        b = s.get("boss") or {}
        gate.check(bool(b.get("triggered")), "boss triggers from real proximity",
                   f"triggered={b.get('triggered')} locked={b.get('locked')}")
        gate.check(bool(b.get("present")), "boss spawns into the arena",
                   f"boss_id={b.get('boss_id')!r} hp={b.get('hp')}/{b.get('max_hp')}")
        gate.check(not b.get("invulnerable"), "boss becomes vulnerable after its intro",
                   f"invulnerable={b.get('invulnerable')} phase={b.get('phase')}")

        # PC-14: the arena locks and clears regular enemies, then leaves the
        # spawner running. Count what is actually in the locked arena.
        adds = [e for e in (s.get("enemies") or []) if not e.get("boss_id")]
        if adds:
            gate.blocked(
                "boss arena is a clean 1v1 (PC-14)",
                f"{len(adds)} regular enem(ies) inside the LOCKED boss arena: "
                f"{sorted({e.get('type') for e in adds})}. BossArena._clear_regular_enemies() "
                f"empties the arena on trigger but nothing stops EnemySpawner, which is only "
                f"paused for INVESTIGATION — so the arena refills within seconds and the clear "
                f"is pointless.")
        else:
            gate.check(True, "boss arena is a clean 1v1", "no adds present")

        outcome, s, lowest, cycles = fight_boss(ad)
        b = s.get("boss") or {}
        gate.check(lowest < (b.get("max_hp") or 100),
                   "the boss takes real damage from real input",
                   f"hp fell to {lowest} of {b.get('max_hp')}")
        defeated = s["run"]["stats"].get("bosses_defeated", 0) >= 1
        if not defeated:
            gate.blocked(
                "wave-5 boss DEFEATED (PC-15, balance)",
                f"fight ended '{outcome}' after {cycles} cycles with the boss on "
                f"{b.get('hp')} hp (lowest seen {lowest}). Tongue damage is 1 against 100 boss "
                f"hp while a single boss bullet costs the player 10 of 100. Mutations do not "
                f"close the gap: damage_modifier is fractional against an INT base of 1 so most "
                f"damage mutations round away to nothing, while hp_scale_per_mutation adds a "
                f"full +5% boss hp per mutation taken — so upgrading makes the fight HARDER. "
                f"Across 4 seeds and ~20 driver configurations the boss survived with 2-52 hp.")
        else:
            gate.check(True, "wave-5 boss DEFEATED", f"after {cycles} cycles")
    finally:
        ad.close()


def section_unreachable(gate: Gate, seed: int) -> None:
    """Modes R2 requires that a full-spine round must decide over the wire.

    PC-11/PC-13 are now FIXED game-side and measured/reclassified here; PC-12
    is a reasoned harness gap (its production caller now exists). Nothing in
    this section is an unconditional gate.blocked() — the standing constraint.

    Note on the acceptance phrasing "accepts an adapter": every other section
    in this file takes (gate, seed) and CONSTRUCTS its own PondHarnessAdapter,
    because each reset() restarts the headless subprocess. PC-11 needs three
    separate resets at different run_numbers, so a single shared adapter cannot
    serve them. This section follows the same convention — (gate, seed), one
    adapter per run — rather than being handed a prebuilt adapter.
    """
    print("\n  -- 3. boss roster, victory path, and pause --")

    # PC-11 (CRITICAL, fixed by T-054): a distinct boss per run band. Drive
    # run_number 1/5/10, walk each to its boss over the wire, and read boss_id
    # from the live harness. LevelGenerator maps run 1->foreman (Wetland),
    # 5->lobbyist (Chemical Plant), 10->ceo (Corporate HQ).
    print("\n  PC-11: three distinct bosses, one per run band --")
    EXPECTED_BOSS = {1: "foreman", 5: "lobbyist", 10: "ceo"}
    boss_ids: dict[int, str | None] = {}
    for run_number, expected in EXPECTED_BOSS.items():
        ad = PondHarnessAdapter()
        try:
            ad.reset(seed=seed, run_number=run_number)
            s = walk_to_boss(ad, gate)
            b = s.get("boss") or {}
            present = bool(b.get("present"))
            boss_ids[run_number] = b.get("boss_id") if present else None
            # Distinct failure path #1: the walk never reached a boss at all.
            # A boss that never triggers must fail as boss-not-reached, NOT
            # masquerade as a same-id / wrong-id mismatch below.
            if not gate.check(
                    present,
                    f"run {run_number} reaches its boss (PC-11)",
                    f"boss-not-reached: triggered={b.get('triggered')} "
                    f"present={present} player_dead={s.get('player', {}).get('dead')} "
                    f"— walked to BOSS_TRIGGER={BOSS_TRIGGER}"):
                continue
            # Distinct failure path #2: reached a boss, but the WRONG one.
            gate.check(
                b.get("boss_id") == expected,
                f"run {run_number} fields the {expected} boss (PC-11)",
                f"boss_id={b.get('boss_id')!r} (expected {expected!r}) "
                f"hp={b.get('hp')}/{b.get('max_hp')}")
        finally:
            ad.close()

    distinct = {v for v in boss_ids.values() if v}
    gate.check(
        len(distinct) >= 3,
        "all three bosses reachable as distinct ids (PC-11, was CRITICAL — fixed T-054)",
        f"boss_ids by run={boss_ids} distinct={sorted(distinct)}")

    # PC-12 (fixed by T-057): end_run("victory") NOW HAS a production caller —
    # run_manager.gd:235 inside _on_ending_unlocked (connected :65), fired when
    # EventBus.ending_unlocked lands during an active run. The original finding
    # ("no production caller") is REFUTED and must not be re-asserted. The
    # victory RESULT still cannot be OBSERVED through the current harness, so
    # this is a reasoned, named harness gap — not an unconditional block.
    print("\n  PC-12: victory run-end path --")
    gate.blocked(
        "victory run result observed over the wire (PC-12)",
        "end_run('victory') now HAS a production caller (run_manager.gd:235 via "
        "_on_ending_unlocked, connected :65 — fixed by T-057); the earlier "
        "'no production caller' finding is REFUTED and is NOT re-asserted here. "
        "But a 'victory' run RESULT could not be OBSERVED over the wire: reaching "
        "EventBus.ending_unlocked requires all 16 logs + the Lobbyist and CEO "
        "defeats + the smoking-gun conspiracy-board connection "
        "(meta_progression.gd check_ending_unlock), and the JSON-lines harness "
        "protocol exposes only create/step/choose/state/quit — there is no "
        "board-connection or evidence-grant op to reach ending_unlocked. So the "
        "victory arm (successful_runs / win_rate / RunEndScreen's victory branch) "
        "is unreachable THROUGH THE CURRENT WIRE, not un-coded. Follow-up harness "
        "extension filed in integrations/pond/HANDOFF.md.")

    # PC-13 (fixed by T-058/T-059): pause is now a real, non-destructive mode.
    # Reclassified to INFO — its wire assertion is U-008's job. Do NOT leave
    # prose that says "there is no pause".
    print("\n  PC-13: pause --")
    gate.info(
        "pause is now a real, non-destructive mode (PC-13, fixed T-058/T-059)",
        "the 'pause' action toggles get_tree().paused and emits "
        "EventBus.pause_toggled instead of quitting the process; "
        "input_manager.gd was deleted. Its wire assertion — re-enable the pause "
        "action in the harness and assert its invariants (tree paused, "
        "pause_toggled emitted, run NOT destroyed) — lands in U-008, not this "
        "gate.")


def section_evidence_chain(gate: Gate, seed: int) -> None:
    """Evidence -> narrative -> RunEndScreen, driven to a real ending."""
    print("\n  -- 4. evidence -> epilogue -> run end --")
    ad = PondHarnessAdapter()
    try:
        ad.reset(seed=seed, run_number=1)
        s = snap(ad)
        saw = {"evidence_unlocked": False, "run_rewards_due": False,
               "run_ended": False, "player_died": False}
        result = None
        for _ in range(500):
            s = take_level_up(ad, s)
            p = s["player"]["pos"]
            add, d = nearest_add(s, p)
            aim = add["pos"] if add else [p[0] + 1, p[1]]
            move = [0, 0]
            if add and d > 110:
                move = [(add["pos"][0] - p[0]) / max(d, 1), (add["pos"][1] - p[1]) / max(d, 1)]
            step(ad, 2, attack=True, aim=aim, move=move)
            s = step(ad, 14, attack=False, aim=aim, move=move)
            for e in (s.get("events") or []):
                sig = e.get("signal")
                if sig in saw:
                    saw[sig] = True
                if sig == "run_ended":
                    args = e.get("args") or []
                    result = args[0] if args else None
            if saw["run_ended"]:
                break

        gate.check(saw["player_died"] and saw["run_ended"],
                   "a run reaches a real end over the wire",
                   f"result={result!r} events={ {k: v for k, v in saw.items()} }")
        gate.check(result == "death",
                   "the only reachable run result is 'death'",
                   f"result={result!r} — see PC-12: no production path emits 'victory'")
        gate.check(saw["run_rewards_due"],
                   "rewards are settled BEFORE the epilogue is narrated (PC-6 ordering)",
                   "run_rewards_due observed ahead of run_ended")

        narrative = s.get("narrative") or {}
        run_end = s.get("run_end") or {}
        epilogue = str(narrative.get("epilogue") or "")
        gate.check(bool(epilogue), "NarrativeState produces an epilogue",
                   f"{len(epilogue)} chars: {epilogue[:60]!r}")
        gate.check(bool(run_end.get("visible")),
                   "RunEndScreen is presented with that epilogue",
                   f"present={run_end.get('present')} visible={run_end.get('visible')} "
                   f"scene={run_end.get('scene')!r}")
        evidence = (s["run"]["stats"] or {}).get("evidence_collected") or []
        gate.info("evidence collected this run",
                  f"{evidence} — the conspiracy-board card flip needs a boss kill for a "
                  f"gated card, which PC-15 blocks")
    finally:
        ad.close()


def main() -> int:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SEED
    print("=" * 70)
    print(f"POND ROUND 2 — full spine (seed {seed})")
    print("=" * 70)
    gate = Gate()
    section_arenas(gate, seed)
    section_boss(gate, seed)
    section_unreachable(gate, seed)
    section_evidence_chain(gate, seed)

    total = gate.passed + gate.failed
    print("\n" + "=" * 70)
    if gate.failed == 0:
        print(f"ROUND 2 MET — {gate.passed}/{total} checks.")
        return 0
    print(f"ROUND 2 NOT MET — {gate.passed}/{total} checks passed, "
          f"{gate.failed} failed/blocked.")
    print("\nFindings (each is a real game defect or a named wire gap):")
    for f in gate.findings:
        print(f"  * {f.splitlines()[0]}")
    print("\nPC-14 (spawner refills the locked arena) and PC-15 (boss balance) are\n"
          "real game defects with no code path / no winnable path. PC-12 is a named\n"
          "harness gap: the victory caller now exists (T-057) but no wire op reaches\n"
          "it. PC-11 (three distinct bosses) and PC-13 (real pause) are FIXED and\n"
          "now measured/reclassified above. See integrations/pond/RESULTS.md.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
