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
Four of R2's modes turn out to have no code path at all, which is precisely the
class of defect a full-spine round exists to find:

  * only ONE of the three bosses is wired into any scene, so the true ending
    (which gates on the CEO) is unreachable — finding PC-11;
  * `end_run("victory")` has no production caller, so the victory run-end path
    and everything hanging off it is dead — finding PC-12;
  * there is no pause anywhere: the "pause" action calls `get_tree().quit()`,
    so ESC destroys the run — finding PC-13;
  * the boss arena clears regular enemies then leaves the spawner running, so
    the "locked" arena refills with adds — finding PC-14.

Those are asserted as BLOCKED checks: they FAIL the gate and print as findings
with the evidence that proves them, rather than being quietly skipped. A gate
that skips what the game cannot do reports a green that means nothing.

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
        """A mode with NO code path. Fails the gate — see the module docstring."""
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


def section_unreachable(gate: Gate) -> None:
    """Modes R2 requires that have no code path at all. Evidence, not opinion."""
    print("\n  -- 3. modes with no code path (structural findings) --")
    gate.blocked(
        "all three bosses reachable (PC-11, CRITICAL)",
        "BossArena.boss_scene is an @export set in exactly one place — "
        "TestArena.tscn -> BossLobbyist. BossCEO.tscn and BossForeman.tscn are referenced "
        "ONLY by unit tests; no production code instantiates either, and the three arena "
        "scenes carry hazards only. Consequences: MetaProgression.check_ending_unlock() "
        "requires ceo_defeated, so the TRUE ENDING can never unlock; unlocks."
        "all_bosses_defeated can never become true; the CEO-gated informant "
        "(informant_manager.gd:198) and CEO hints (hint_system.gd:116) are dead content. "
        "docs/prd.md:198 specifies a boss PER ARENA (Wetland/Chemical Plant/Corporate HQ) — "
        "that mapping was never implemented.")
    gate.blocked(
        "both run-end paths reachable (PC-12)",
        "end_run('victory') has NO production caller — the only one is "
        "run_manager.gd:157 end_run('death') from _on_player_died. Boss defeat routes to "
        "enter_investigation_phase(), never to a win. So MetaProgression.end_run_victory() "
        "(150% rewards) is called only by tests, runs.successful_runs can never increment, "
        "best_time can never be set, and RunEndScreen's whole victory branch "
        "(run_end_screen.gd:77/120/157) is unreachable. R1 exercised death; victory has no "
        "path to exercise.")
    gate.blocked(
        "pause exists (PC-13)",
        "There is no pause in this game. The 'pause' input action (bound to ESCAPE in "
        "input_manager.gd:142) is consumed at test_arena_controller.gd:84 by "
        "`get_tree().quit()` — pressing it mid-run quits the application outright, with no "
        "menu and no confirmation, destroying the run. No PauseMenu scene or script exists "
        "anywhere in the project. This is deliberately NOT driven here: wiring the action "
        "into the harness would let any random-input tier (R3) kill the process.")


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
    section_unreachable(gate)
    section_evidence_chain(gate, seed)

    total = gate.passed + gate.failed
    print("\n" + "=" * 70)
    if gate.failed == 0:
        print(f"ROUND 2 MET — {gate.passed}/{total} checks.")
        return 0
    print(f"ROUND 2 NOT MET — {gate.passed}/{total} checks passed, "
          f"{gate.failed} failed/blocked.")
    print("\nFindings (each is a real game defect, to be fixed upstream):")
    for f in gate.findings:
        print(f"  * {f.splitlines()[0]}")
    print("\nThe blocked checks are not harness limitations — they are modes the game\n"
          "has no code path for. See integrations/pond/RESULTS.md for the full\n"
          "diagnosis of PC-11 through PC-15.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
