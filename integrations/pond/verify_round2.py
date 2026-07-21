#!/usr/bin/env python3
"""
Pond Conspiracy ROUND 2 — the full-spine gate: every mode driven to a REAL
outcome against the live headless game, through `PondHarnessAdapter`.

R1 asked "is this game playable over the wire?" and answered yes. R2 asks the
harder question: "does every mode the game advertises actually reach an
outcome?" — all three arenas and their hazards, the wave-5 boss fought to a
decision, the evidence -> conspiracy-board card flip -> epilogue chain, BOTH
run-end paths (death and victory), and pause.

Section 4 DRIVES the full evidence -> board -> epilogue chain over the wire
(U-007): a real death run's EventBus.evidence_unlocked flips a live DataLogCard
on an instanced ConspiracyBoard (create's with_board flag), read back from the
harness `board` block — the board card flip HANDOFF.md lists as an R2
requirement is now a measured check, not a silently-absent one.

The answer is a qualified no, and the qualifications are the point of this gate.
The remaining blocks are genuine no-code-path / balance defects, which is
precisely the class of defect a full-spine round exists to find:

  * the automated driver did not defeat the wave-5 boss this run — finding PC-15
    (balance). The earlier "damage rounds to nothing while each mutation adds
    boss hp" diagnosis is WITHDRAWN: the-pond T-062
    (test/unit/test_boss_damage_scaling.gd) measured the real mechanism as a
    count-vs-type HP/DPS asymmetry — the inversion is REFUTED for realistic,
    offense-inclusive builds and confirmed only for a degenerate zero-offense
    build — not fractional rounding.

Three earlier structural blocks have since been FIXED game-side and are now
measured over the wire rather than asserted as prose:

  * PC-11 (only one boss wired) is fixed by T-054 — `LevelGenerator` now maps a
    distinct boss per run band (Wetland/Foreman, Chemical Plant/Lobbyist,
    HQ/CEO). This gate drives run_number 1/5/10, walks each to its boss, and
    asserts three DISTINCT boss_id values read from the live harness. Expected
    to pass, proving the fix.
  * PC-13 (ESC quit the process) is fixed by T-058/T-059 — pause now toggles
    `get_tree().paused` and emits `EventBus.pause_toggled`, never quits, and
    `input_manager.gd` is deleted. Its wire assertion is DRIVEN by
    `section_pause` (U-008): the harness re-enables the `pause` action and this
    gate drives the ESC *toggle* only (never the PauseMenu's Quit-to-Menu
    button, which ends the run). The pause TOGGLE round-trips cleanly over the
    wire — `paused` flips true<->false, both `pause_toggled` edges are observed,
    and the run is never destroyed — so PC-13's core (ESC no longer quits) is
    CONFIRMED. But driving it surfaced a NEW finding, PC-17: the pause is
    COSMETIC. `get_tree().paused` flips yet gameplay keeps running (the player
    walks ~50px/15-frames while `paused` reads True) because the arena ROOT is
    `PROCESS_MODE_ALWAYS` (T-058) and every gameplay child inherits it — masked
    by a vacuous game test (`test_pause_menu.gd:109` probes a node not under the
    arena). Invariant 2 (no-state-advance-while-paused) correctly FAILS the gate
    and is filed for a game-side fix.
  * PC-14 (the "locked" boss arena refilled with adds) is fixed by T-061 —
    `trigger_boss()` now calls `BossArena._stop_enemy_spawner()` right after
    `_lock_arena()`, so the one-shot clear is no longer immediately undone by an
    active spawner. This gate holds idle in the locked arena for a short window
    (evade + dodge only, never attacking) and asserts 0 non-boss adds at every
    sample — the wire analogue of T-061's in-suite idle >=5s assertion. Expected
    to pass, proving the fix.

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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ugt.adapters.pond_harness import PondHarnessAdapter  # noqa: E402
import invariants  # noqa: E402  (local module, from integrations/pond/)
# Single source of truth for the stderr whitelist: import R1's, never re-author
# it, so the two rungs cannot drift. Importing verify_round1 is side-effect-free
# — its main() only runs under __main__; the top level just defines constants.
from verify_round1 import STDERR_WHITELIST  # noqa: E402

DEFAULT_SEED = 20260720

# The per-step invariant suite R1 sweeps after every step (integrations/pond/
# invariants.py). R2 drives far more frames, so it needs the same net.
SUITE = invariants.build_suite()

# Populated by step() as the gate drives frames; verdicts read in main().
_VIOLATIONS: list[str] = []
_STEP_NO = 0
# Every adapter constructed this run, so a single central stderr scan sees the
# real SCRIPT ERRORs of every subprocess (this is how PC-8 was caught).
_ADAPTERS: list = []


def _new_adapter():
    """Construct a PondHarnessAdapter and register it for the central stderr
    scan. Its stderr_lines persist on the object and are complete after close()
    (the stderr thread is joined in _kill_process), so the finally-block scan
    reads every runtime SCRIPT ERROR plus teardown noise the whitelist absorbs."""
    ad = PondHarnessAdapter()
    _ADAPTERS.append(ad)
    return ad

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

# The canonical evidence set the ConspiracyBoard spawns one card per (EvidenceIds
# .ALL — the 16 data logs; DATA_LOG_01..16). The board-flip section reads the card
# count back over the wire and asserts the full deck instanced (U-007).
EXPECTED_EVIDENCE_CARDS = 16

# PC-14 (the-pond T-061): after trigger_boss()->_stop_enemy_spawner() the locked
# arena must not refill. Wire analogue of T-061's idle >=5s assertion — sample
# the arena across this window and require 0 non-boss adds at every sample.
PC14_SAMPLES = 6      # 6 * 30 frames / 60fps = ~3s of idle observation
PC14_STRIDE = 30

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
    """Drive `frames` frames of real input and sweep the invariant suite over
    the resulting wire state — R1 parity (verify_round1.py:109), centralized
    here because every driven frame in R2 funnels through this helper. The
    per-step `choose` frames stay un-swept, exactly as R1 does not sweep its
    mutation-pick step. No game rule is reimplemented: `before`/`after` are the
    adapter's own normalized snapshots and `resp` is the raw harness snapshot."""
    global _STEP_NO
    before_raw = ad.last_snapshot or {}
    resp = ad._rpc({"op": "step", "frames": frames, "input": inp})
    ad.last_snapshot = resp
    _STEP_NO += 1
    before = ad._normalize(before_raw) if before_raw else {}
    for msg in SUITE.check_command(before, ad._normalize(resp), "step", resp):
        _VIOLATIONS.append(f"step {_STEP_NO} ({inp}): {msg}")
    return resp


def take_level_up(ad, s: dict, pick_log: list | None = None) -> dict:
    """Pick a card if the level-up screen is up.

    MUST be called in every driving loop. LevelUpUI pauses the whole tree, so a
    driver that ignores it sees the world freeze mid-swing — tongue stuck
    EXTENDING, i-frames never expiring — and will misread that as a game
    soft-lock. (It did, during development of this gate.)

    `pick_log`, when passed, receives one record per card taken:
    `{"mutation": <id>, "events": [...]}` — the events the harness drained
    DURING the choose (which the caller would otherwise discard). This is how a
    driver observes whether a mutation's own effect emits `evidence_unlocked`
    mid-run, instead of inferring it from source. Section 4 uses it so every
    board-card flip is attributed to an event actually seen over the wire.
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
    _, choose_events = ad.choose_mutation(pick, frames=40)
    if pick_log is not None:
        picked = ids[pick] if 0 <= pick < len(ids) else None
        pick_log.append({"mutation": picked, "events": list(choose_events)})
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


def walk_to_boss(ad, max_cycles=140) -> dict:
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


def rewards_settle_before_end(events):
    """PC-6: in the ORDERED event stream, `run_rewards_due` must strictly
    precede `run_ended` (rewards settle before the epilogue is narrated).

    `events` is an ordered sequence of event dicts (or bare signal strings).
    Returns (ok, rewards_idx, ended_idx) using FIRST-seen positions. Pure — no
    game state — so a checked-in negative test can drive it with a synthetic
    out-of-order list. Contract source: run_manager.gd emits rewards before
    narration; evidence_manager.gd / meta_progression.gd consume run_rewards_due.
    """
    rewards_idx = ended_idx = None
    for i, e in enumerate(events):
        sig = e.get("signal") if isinstance(e, dict) else e
        if sig == "run_rewards_due" and rewards_idx is None:
            rewards_idx = i
        elif sig == "run_ended" and ended_idx is None:
            ended_idx = i
    ok = (rewards_idx is not None and ended_idx is not None
          and rewards_idx < ended_idx)
    return ok, rewards_idx, ended_idx


def scan_stderr(lines, whitelist):
    """Real SCRIPT ERROR / Parse Error stderr lines, minus the forked-addon
    teardown noise the whitelist covers. Pure — no game, no wire — so a
    checked-in test (stderr_scan_selftest.py) can drive it with a synthetic
    blob. Logic mirrors verify_round1.py:404-406 exactly so the two rungs
    cannot drift; the whitelist itself is IMPORTED from R1, not re-authored."""
    return [ln for ln in lines
            if ("SCRIPT ERROR" in ln or "Parse Error" in ln)
            and not any(w in ln for w in whitelist)]


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def section_arenas(gate: Gate, seed: int) -> None:
    """All three arenas reached, each with its own hazards live as NODES."""
    print("\n  -- 1. every arena, selected the way the game selects it --")
    for run_number, expect_id, expect_hazard in ARENAS:
        ad = _new_adapter()
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
    ad = _new_adapter()
    try:
        ad.reset(seed=seed, run_number=1)
        s = walk_to_boss(ad)
        b = s.get("boss") or {}
        gate.check(bool(b.get("triggered")), "boss triggers from real proximity",
                   f"triggered={b.get('triggered')} locked={b.get('locked')}")
        gate.check(bool(b.get("present")), "boss spawns into the arena",
                   f"boss_id={b.get('boss_id')!r} hp={b.get('hp')}/{b.get('max_hp')}")
        gate.check(not b.get("invulnerable"), "boss becomes vulnerable after its intro",
                   f"invulnerable={b.get('invulnerable')} phase={b.get('phase')}")

        # PC-14 (BLOCKED in the 8852b19 run; FIXED game-side by the-pond T-061):
        # trigger_boss() now calls BossArena._stop_enemy_spawner() right after
        # _lock_arena(), so the locked arena no longer refills with adds — proven
        # in-suite by test_boss_arena.gd::test_trigger_boss_stops_spawner_no_new_
        # enemies_for_5s. Wire analogue of that idle >=5s assertion: hold in the
        # locked arena WITHOUT attacking (evade + dodge only, so the boss is
        # neither killed nor able to kill us and a spawner leak has a fair chance
        # to fire) and require ZERO non-boss adds at EVERY sample. Passes because
        # the spawner is stopped; fails if the leak regresses. Replaces the old
        # unconditional literal-True arm.
        worst_adds: list = []
        for _ in range(PC14_SAMPLES):
            adds = [e for e in (s.get("enemies") or []) if not e.get("boss_id")]
            if len(adds) > len(worst_adds):
                worst_adds = adds
            if s["player"]["dead"]:
                break
            s = take_level_up(ad, s)
            ex, ey, near = evade_vector(s, s["player"]["pos"])
            dodge = (s["player"].get("dodge_cooldown") or 0) <= 0.0
            s = step(ad, PC14_STRIDE, attack=False,
                     aim=(s.get("boss") or {}).get("pos"),
                     move=[ex, ey] if near else [0.0, 0.0], dodge=dodge)
        secs = PC14_SAMPLES * PC14_STRIDE / 60.0
        gate.check(
            not worst_adds,
            "boss arena stays a clean 1v1 across a post-lock window "
            "(PC-14, fixed by the-pond T-061)",
            (f"{len(worst_adds)} non-boss enem(ies) leaked into the LOCKED arena "
             f"within ~{secs:.0f}s of trigger: "
             f"{sorted({e.get('type') for e in worst_adds})} — the T-061 "
             f"_stop_enemy_spawner() has regressed") if worst_adds else
            (f"0 non-boss adds across {PC14_SAMPLES} samples over ~{secs:.0f}s "
             f"post-lock — trigger_boss()->_stop_enemy_spawner() holds "
             f"(the-pond T-061); was BLOCKED in 8852b19"))

        # Instrumentation (uncounted INFO): log the actual mutation ids owned
        # and the resolved tongue base_damage at fight start, read over the
        # wire, so any UGT-side balance note stays evidence-backed.
        active_ids = (s.get("mutations") or {}).get("active_ids") or []
        base_damage = ((s.get("player") or {}).get("tongue") or {}).get("damage")
        gate.info("boss-fight start state (over the wire)",
                  f"tongue base_damage={base_damage} active_ids={active_ids}")

        outcome, s, lowest, cycles = fight_boss(ad)
        b = s.get("boss") or {}
        max_hp = b.get("max_hp")
        if outcome != "defeated" and max_hp is None:
            gate.check(False, "the boss takes real damage from real input",
                       f"boss snapshot empty/absent after the fight (boss={b!r}, "
                       f"outcome={outcome!r}) — cannot measure damage against a real value")
        else:
            took_damage = outcome == "defeated" or lowest < max_hp
            gate.check(took_damage, "the boss takes real damage from real input",
                       f"outcome={outcome!r}; hp fell to {lowest} of {max_hp} "
                       f"(defeated={outcome == 'defeated'})")
        defeated = s["run"]["stats"].get("bosses_defeated", 0) >= 1
        if not defeated:
            gate.blocked(
                "wave-5 boss DEFEATED (PC-15, balance)",
                f"fight ended '{outcome}' after {cycles} cycles with the boss on "
                f"{b.get('hp')} hp (lowest seen {lowest}); at fight start the driver held "
                f"active_ids={active_ids} with tongue base_damage={base_damage}. The earlier "
                f"'fractional damage rounds to nothing → upgrading makes the fight HARDER' "
                f"diagnosis is WITHDRAWN — refuted by the-pond T-062 "
                f"(test/unit/test_boss_damage_scaling.gd). Measured verdict: mercury_blood "
                f"(damage_modifier 0.5) computes 1*1.5→round→2, i.e. DOUBLE damage "
                f"(mutation_manager.gd:120 → player_controller.gd:214, asserted "
                f"test_combat_emissions.gd:201-202), and mercury_blood is this driver's first "
                f"PREFERRED pick. For a 100-hp boss the inversion is REFUTED for realistic "
                f"(offense-inclusive) play — ttk FALLS ~45% as upgrades are taken "
                f"(ttk@0≈52.4s → ttk@10≈28.8s) — and CONFIRMED only for a degenerate "
                f"zero-offense build (52.4s → 78.6s), which is the only regime where the "
                f"'boss survived with 2-52 hp' observation holds. The true mechanism is a "
                f"count-vs-type asymmetry: boss HP scales with mutation COUNT "
                f"(hp_scale_per_mutation) while player DPS scales only with the "
                f"damage/crit/cooldown SUBSET — NOT fractional rounding (only strong_legs at "
                f"0.1 rounds away). The driver still did not beat the boss this run; the "
                f"pass/fail re-baseline is U-009's, not this gate's.")
        else:
            gate.check(defeated, "wave-5 boss DEFEATED", f"after {cycles} cycles")
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
        ad = _new_adapter()
        try:
            ad.reset(seed=seed, run_number=run_number)
            s = walk_to_boss(ad)
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
    # Its wire assertion is DRIVEN by section_pause() below (U-008) — the pause
    # action is re-enabled in the harness and its three invariants are checked
    # over the wire. This block is a pointer only. Do NOT leave prose that says
    # "there is no pause".
    print("\n  PC-13: pause --")
    gate.info(
        "pause no longer quits the process (PC-13, fixed T-058/T-059)",
        "the 'pause' action toggles get_tree().paused and emits "
        "EventBus.pause_toggled instead of quitting; input_manager.gd was "
        "deleted. The wire assertion is DRIVEN in section_pause() (U-008), "
        "section 3b below: the ESC toggle round-trips and never ends the run "
        "(PC-13 core CONFIRMED), but the paused world keeps running underneath "
        "— NEW finding PC-17 (pause is cosmetic), which correctly fails "
        "invariant 2 there.")


def _pause_toggle_args(events) -> list:
    """The ordered list of pause_toggled arg-values in one step's event stream.
    Read straight off the harness EventBus tap — no game logic. Each element is
    the boolean the game emitted (EventBus.pause_toggled(is_paused))."""
    out = []
    for e in (events or []):
        if e.get("signal") == "pause_toggled":
            args = e.get("args") or []
            out.append(bool(args[0]) if args else None)
    return out


def section_pause(gate: Gate, seed: int) -> None:
    """PC-13 / U-008: the pause action, DRIVEN and asserted over the wire.

    The harness now injects the `pause` action (the ESC toggle only — never a
    click on the PauseMenu's Quit-to-Menu button, which would end the run). This
    section drives real `pause` presses and reads `paused` / `events` / `run` /
    player-pos back from the harness snapshot to assert the invariants the old
    exclusion note anticipated:

      (1) toggling `pause` flips `paused` true — the ON edge, with
          EventBus.pause_toggled(true), and the run NOT destroyed (the safety
          proof that ESC is no longer `get_tree().quit()`);
      (2) NO game state advances while paused — the player must not move even
          when fed a strong move input a live player WOULD act on;
      (3) the pause is DISMISSIBLE — a second ESC edge flips `paused` false again
          (a clean round-trip, which also proves the un-pause path stays live
          while the tree is paused), with EventBus.pause_toggled(false), the run
          still intact.

    Toggle discipline: one toggle per FRESH press edge. `_set_action` only
    presses on a false->true transition, so an OFF toggle needs the pause action
    RELEASED (a step that omits `pause`) between the ON and OFF presses. The
    move-only steps of invariant 2 provide that release naturally; the section
    never sends `pause=True` on two consecutive steps.

    RESULT over the wire: invariants 1 and 3 PASS — the pause TOGGLE round-trips
    true<->false, both pause_toggled edges are seen, and the run is never
    destroyed (PC-13's `get_tree().quit()` is gone). Invariant 2 FAILS and
    surfaces a NEW finding, PC-17: the pause is COSMETIC. `get_tree().paused`
    flips true, yet gameplay keeps running underneath — the player walks ~50px
    per 15 frames while `paused` reads True. Root cause (read from source,
    corroborating the observed movement): `test_arena_controller.gd:47` sets the
    arena ROOT to `PROCESS_MODE_ALWAYS` (T-058's fix for keeping ESC alive), and
    every gameplay node is a child that INHERITS ALWAYS — the player is a scene
    child, and `enemy_spawner.gd:290` parents each enemy under that same root via
    `get_parent().add_child(enemy)` — so `paused` never freezes them. The game's
    own suite masks this: `test_pause_menu.gd:109` probes a node parented under
    the TEST root (pausable), not under the arena, so it never exercises a node
    that inherits the arena's ALWAYS. Filed for a game-side fix (a dedicated
    the-pond task, the PC-13 -> T-058 pattern); until then invariant 2 correctly
    fails this gate.
    """
    print("\n  -- 3b. pause: driven & asserted over the wire (PC-13 / U-008) --")
    ad = _new_adapter()
    try:
        ad.reset(seed=seed, run_number=1)
        s = snap(ad)

        # Baseline: settle a few idle frames and clear any level-up modal so the
        # ESC toggle is asserted against a clean COMBAT state (a pending
        # LevelUpUI itself pauses the tree, and _handle_pause_input's
        # `if get_tree().paused: return` guard would make an ESC a no-op while
        # the level-up owns the pause).
        for _ in range(3):
            s = take_level_up(ad, s)
            s = step(ad, 10)
            if s["player"]["dead"]:
                break
        s = take_level_up(ad, s)
        alive = not s["player"]["dead"]
        run0 = s.get("run") or {}
        gate.check(
            alive and run0.get("phase") == "COMBAT" and bool(run0.get("active"))
            and not s.get("paused"),
            "baseline: a live COMBAT run, not paused, before any ESC toggle",
            f"dead={s['player']['dead']} phase={run0.get('phase')!r} "
            f"active={run0.get('active')} paused={s.get('paused')}")
        if not alive:
            gate.check(False, "pause section reached a live baseline",
                       "player died during the idle baseline — cannot assert the "
                       "pause toggle against a live COMBAT run this seed")
            return

        # --- Invariant 1: clean toggle ON, run not destroyed ----------------------
        s = step(ad, 10, pause=True)          # single fresh press edge -> one toggle
        toggles_on = _pause_toggle_args(s.get("events") or [])
        gate.check(
            s.get("paused") is True,
            "ESC toggles the tree PAUSED (round-trip, half 1)",
            f"paused={s.get('paused')} pause_toggled args this step={toggles_on}")
        gate.check(
            True in toggles_on,
            "EventBus.pause_toggled(true) is emitted on the ESC toggle",
            f"pause_toggled args observed over the wire={toggles_on}")
        run_on = s.get("run") or {}
        run_end_on = s.get("run_end") or {}
        gate.check(
            bool(run_on.get("active")) and run_on.get("phase") == "COMBAT"
            and not run_end_on.get("visible"),
            "ESC does NOT end the run (safety: no longer get_tree().quit())",
            f"run.active={run_on.get('active')} phase={run_on.get('phase')!r} "
            f"run_end.present={run_end_on.get('present')} "
            f"visible={run_end_on.get('visible')}")

        # Snapshot the world at the moment of the pause (the reference the paused
        # window must NOT drift from).
        paused_pos = list(s["player"]["pos"])
        paused_enemy_count = len(s.get("enemies") or [])
        paused_stats = dict((s.get("run") or {}).get("stats") or {})

        # --- Invariant 2: NO state advances while paused (PC-17) ------------------
        # Omit `pause` (releases the action, NO further toggle) and feed a strong
        # move a live player WOULD act on. A real pause must freeze the player.
        # `paused` is asserted to hold True across the whole window, so any drift
        # is movement WHILE PAUSED, not a silent auto-resume.
        still_paused = True
        worst_drift = 0.0
        enemy_delta = 0
        stats_changed = False
        for _ in range(4):
            s = step(ad, 15, move=[1, 0])     # strong move; pause released (no toggle)
            if not s.get("paused"):
                still_paused = False
            worst_drift = max(worst_drift, math.dist(s["player"]["pos"], paused_pos))
            enemy_delta = max(enemy_delta,
                              abs(len(s.get("enemies") or []) - paused_enemy_count))
            if dict((s.get("run") or {}).get("stats") or {}) != paused_stats:
                stats_changed = True
        gate.check(
            still_paused,
            "the pause FLAG holds True across the paused window (no auto-resume)",
            f"paused held True across 4 move-steps={still_paused}")
        # The definitive, NON-vacuous invariant-2 check: the player is fed a
        # strong move and MUST NOT move while paused. This FAILS -> PC-17.
        gate.check(
            worst_drift < 0.5,
            "NO game state advances while paused: the player is frozen "
            "(PC-17 — pause is cosmetic, see section docstring)",
            f"player drifted {worst_drift:.2f}px while paused=True over 4 x15 "
            f"frames of move=[1,0] (a real pause must hold 0). Gameplay is NOT "
            f"frozen: root cause read from source is the arena ROOT's "
            f"PROCESS_MODE_ALWAYS (test_arena_controller.gd:47) inherited by "
            f"every gameplay child (player; enemies via enemy_spawner.gd:290 "
            f"get_parent().add_child). Masked by the vacuous test_pause_menu.gd:"
            f"109 (probe not parented under the arena). "
            f"[context, NOT independent evidence: the sampled window held "
            f"{paused_enemy_count} enemies (max delta {enemy_delta}) and no run "
            f"stats change ({not stats_changed}) — with 0 enemies / no kills "
            f"those cannot corroborate a freeze; the player-drift IS the signal]"
            if worst_drift >= 0.5 else
            f"player held within {worst_drift:.2f}px while paused across 4 x15 "
            f"frames of move=[1,0] — gameplay truly frozen")

        # --- Invariant 3: dismissible; clean toggle OFF, run intact ---------------
        s = step(ad, 10, pause=True)          # fresh press edge -> toggle OFF
        toggles_off = _pause_toggle_args(s.get("events") or [])
        gate.check(
            s.get("paused") is False,
            "a second ESC toggle RESUMES the tree (round-trip, half 2 — the "
            "un-pause path stays live while paused)",
            f"paused={s.get('paused')} pause_toggled args this step={toggles_off}")
        gate.check(
            False in toggles_off,
            "EventBus.pause_toggled(false) is emitted on the dismiss toggle",
            f"pause_toggled args observed over the wire={toggles_off}")
        # After the dismiss the player still responds to input (control restored).
        # NB: because of PC-17 the player also moved WHILE paused, so this proves
        # only that control survives the round-trip, not that pause had frozen it.
        resume_pos = list(s["player"]["pos"])
        s2 = step(ad, 30, move=[1, 0])
        moved = math.dist(s2["player"]["pos"], resume_pos)
        gate.check(
            moved > 2.0 and not s2.get("paused"),
            "control is live after the pause round-trip (player responds to move)",
            f"player moved {moved:.2f}px after the OFF toggle (threshold 2.0), "
            f"paused={s2.get('paused')}")
        run_end2 = s2.get("run_end") or {}
        gate.check(
            bool((s2.get("run") or {}).get("active"))
            and not run_end2.get("visible"),
            "the run survived the full pause round-trip intact (end-to-end safety)",
            f"run.active={(s2.get('run') or {}).get('active')} "
            f"run_end.visible={run_end2.get('visible')}")
    finally:
        ad.close()


def section_evidence_chain(gate: Gate, seed: int) -> None:
    """The advertised chain, DRIVEN over the wire: a real run's evidence unlock ->
    conspiracy-board card flip -> epilogue -> run end.

    A death run fires EventBus.run_rewards_due (strictly before run_ended, PC-6),
    which EvidenceManager turns into EventBus.evidence_unlocked, which the LIVE
    ConspiracyBoard consumes in _on_evidence_unlocked -> DataLogCard.set_discovered
    — the board card flip. The board is instanced over the wire via create's
    with_board flag (U-007); every fact is read back from the harness `board`
    block (real DataLogCard.is_discovered() + MetaProgression's persistent gate)
    and the run-end nodes. No game logic is reimplemented here — the flip is
    produced by the game's own bus, never faked. This closes HANDOFF.md's R2
    "evidence -> conspiracy-board card flip -> epilogue" requirement, which was
    previously only an INFO line.
    """
    print("\n  -- 4. evidence -> conspiracy-board card flip -> epilogue -> run end --")
    ad = _new_adapter()
    try:
        # with_board=True: instance the real ConspiracyBoard so the card flip is
        # observable/driveable. It is hidden (never the input target) so it cannot
        # perturb the combat/level-up input this section drives.
        ad.reset(seed=seed, run_number=1, with_board=True)
        s = snap(ad)

        # Baseline board state, READ over the wire (not assumed): the set of cards
        # already discovered before the run, the board's own counter, and
        # MetaProgression's persistent log count.
        board0 = s.get("board") or {}
        board_present = bool(board0.get("present"))
        base_cards = {c.get("id"): bool(c.get("discovered"))
                      for c in (board0.get("cards") or [])}
        base_discovered = {i for i, d in base_cards.items() if d}
        base_count = board0.get("discovered_count") or 0
        base_logs = (board0.get("unlock_status") or {}).get("logs_collected") or 0
        gate.check(
            board_present and len(base_cards) == EXPECTED_EVIDENCE_CARDS,
            "the live ConspiracyBoard instanced over the wire (U-007, with_board)",
            f"present={board_present} cards={len(base_cards)} "
            f"(expected {EXPECTED_EVIDENCE_CARDS}) "
            f"pre-discovered={sorted(base_discovered)} discovered_count={base_count}")

        saw = {"evidence_unlocked": False, "run_rewards_due": False,
               "run_ended": False, "player_died": False}
        result = None
        event_stream: list = []
        # Every evidence_unlocked id seen this run, tagged with the source that
        # emitted it ("run_reward" = a step's stream, "mutation:<id>" = a
        # level-up card's own effect). Full capture — earlier this loop read
        # only the 14-frame step and dropped the choose + 2-frame events, so a
        # second flip had no observed cause and could only be inferred.
        unlocked: list[tuple[str, str]] = []
        pick_log: list = []           # {"mutation", "events"} per card taken

        def _absorb(events, source):
            """Fold one sub-step's events into the ordered stream + tallies.

            `source` labels where these events came from, so each
            evidence_unlocked (and therefore each board flip) is attributed to
            something ACTUALLY observed over the wire, not read from source."""
            nonlocal result
            for e in events:
                event_stream.append(e)
                sig = e.get("signal")
                if sig in saw:
                    saw[sig] = True
                if sig == "evidence_unlocked":
                    args = e.get("args") or []
                    if args:
                        unlocked.append((args[0], source))
                if sig == "run_ended":
                    args = e.get("args") or []
                    result = args[0] if args else None

        for _ in range(500):
            # A level-up pick can itself emit evidence_unlocked (a mutation's
            # own effect); capture those choose-frame events via pick_log rather
            # than discarding them.
            picks_before = len(pick_log)
            s = take_level_up(ad, s, pick_log=pick_log)
            for rec in pick_log[picks_before:]:
                _absorb(rec["events"], f"mutation:{rec['mutation']}")
            p = s["player"]["pos"]
            add, d = nearest_add(s, p)
            aim = add["pos"] if add else [p[0] + 1, p[1]]
            move = [0, 0]
            if add and d > 110:
                move = [(add["pos"][0] - p[0]) / max(d, 1), (add["pos"][1] - p[1]) / max(d, 1)]
            first = step(ad, 2, attack=True, aim=aim, move=move)
            s = step(ad, 14, attack=False, aim=aim, move=move)
            # Temporal order: choose (above), then the press frames, then the
            # release window — the whole iteration's events, none dropped.
            _absorb(first.get("events") or [], "run_reward")
            _absorb(s.get("events") or [], "run_reward")
            if saw["run_ended"]:
                break

        # Ordered list of just the ids (compat with the readouts below).
        unlocked_ids = [uid for uid, _src in unlocked]

        # Post-run board read (zero-frame state op) — the flip lands synchronously
        # inside end_run, so the final snapshot already reflects it; take a clean
        # read anyway so the comparison is unambiguous.
        post = ad._rpc({"op": "state"})
        board1 = post.get("board") or {}
        post_cards = {c.get("id"): bool(c.get("discovered"))
                      for c in (board1.get("cards") or [])}
        post_discovered = {i for i, d in post_cards.items() if d}
        post_count = board1.get("discovered_count") or 0
        post_us = board1.get("unlock_status") or {}
        post_logs = post_us.get("logs_collected") or 0
        ending_id = board1.get("ending_id")
        newly = post_discovered - base_discovered

        gate.check(saw["player_died"] and saw["run_ended"],
                   "a run reaches a real end over the wire",
                   f"result={result!r} events={ {k: v for k, v in saw.items()} }")
        gate.check(result == "death",
                   "this run ended in death",
                   f"result={result!r}")
        ok_pc6, r_idx, e_idx = rewards_settle_before_end(event_stream)
        gate.check(
            ok_pc6,
            "rewards settle BEFORE the epilogue is narrated (PC-6 ordering)",
            f"run_rewards_due at event #{r_idx} precedes run_ended at #{e_idx}"
            if ok_pc6 else
            f"ORDER VIOLATED / missing: run_rewards_due=#{r_idx} run_ended=#{e_idx} "
            f"(rewards must strictly precede run_ended)")

        # --- THE BOARD CARD FLIP (U-007), driven and measured ---------------------
        # ConspiracyBoard._on_evidence_unlocked is the ONLY path to
        # DataLogCard.set_discovered, so every card that flipped this run must
        # correspond to an evidence_unlocked event we actually observed over the
        # wire. We now capture that event from EVERY sub-step (choose + press +
        # release), so the assertion is FULL attribution — no flip is left to
        # inference. A flip with no observed unlock is itself the finding.
        # `unlocked` carries (id, source): "run_reward" (run_rewards_due ->
        # unlock_next_gated_evidence, in the step stream) or "mutation:<id>" (a
        # level-up card's own effect, captured from its choose frames).
        unlocked_set = {uid for uid, _src in unlocked}
        attribution = {uid: src for uid, src in unlocked}   # last-writer per id
        first_id = unlocked_ids[0] if unlocked_ids else None
        every_flip_seen = bool(newly) and newly <= unlocked_set
        flips_are_discovered = all(post_cards.get(i) is True for i in newly)
        flip_ok = (first_id is not None
                   and every_flip_seen and flips_are_discovered
                   and not (base_discovered & newly))
        gate.check(
            flip_ok,
            "every conspiracy-board flip is caused by an observed evidence unlock "
            "over the wire (U-007; HANDOFF R2 'evidence -> board card flip')",
            (f"cards flipped this run={sorted(newly)}; observed evidence_unlocked "
             f"(id->source)={attribution}; every flip attributed to a wire event="
             f"{every_flip_seen}")
            if first_id else
            (f"NO evidence_unlocked observed anywhere this run "
             f"(board_present={board_present}) — cannot measure a flip"))

        # The board's own counter must track the real flips: its delta equals the
        # number of cards that actually turned discovered, and it advanced (>=1).
        gate.check(
            (post_count - base_count) == len(newly) and post_count > base_count,
            "the board's discovered_count tracks the real card flips",
            f"discovered_count {base_count} -> {post_count} "
            f"(+{post_count - base_count}); cards newly discovered={sorted(newly)} "
            f"(n={len(newly)}); by source={attribution}")

        # The board flip and MetaProgression's PERSISTENT evidence set advance in
        # lockstep, and the ending gate is cited by its current constant.
        gate.check(
            (post_logs - base_logs) == (post_count - base_count)
            and post_logs > base_logs and ending_id == "corporate_conspiracy",
            "flip and persistent evidence advance in lockstep, gated by "
            "CORPORATE_ENDING_ID (the-pond T-060)",
            f"logs_collected {base_logs} -> {post_logs}; board discovered_count "
            f"{base_count} -> {post_count}; ending gate id={ending_id!r}")

        narrative = s.get("narrative") or {}
        run_end = s.get("run_end") or {}
        epilogue = str(narrative.get("epilogue") or "")
        gate.check(bool(epilogue), "NarrativeState produces an epilogue",
                   f"{len(epilogue)} chars: {epilogue[:60]!r}")
        gate.check(bool(run_end.get("visible")),
                   "RunEndScreen is presented with that epilogue",
                   f"present={run_end.get('present')} visible={run_end.get('visible')} "
                   f"scene={run_end.get('scene')!r}")

        # Context (NOT a downgrade of the flip check): the full CORPORATE_ENDING_ID
        # unlock still requires all logs + both bosses + the smoking-gun board link,
        # which a single death run does not complete (that residual is PC-12's wire
        # gap, recorded separately).
        gate.info(
            "full CORPORATE_ENDING_ID still gates on the complete case",
            f"ending_unlocked={post_us.get('ending_unlocked')} needs all "
            f"{post_us.get('logs_needed')} logs + Lobbyist + CEO defeats + the "
            f"data_log_04<->data_log_07 smoking-gun board connection "
            f"(smoking_gun={board1.get('smoking_gun')}) — one death run cannot "
            f"complete it (see PC-12).")
    finally:
        ad.close()


def main() -> int:
    global _VIOLATIONS, _STEP_NO
    _VIOLATIONS, _STEP_NO = [], 0
    _ADAPTERS.clear()
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SEED
    print("=" * 70)
    print(f"POND ROUND 2 — full spine (seed {seed})")
    print("=" * 70)
    gate = Gate()
    try:
        section_arenas(gate, seed)
        section_boss(gate, seed)
        section_unreachable(gate, seed)
        section_pause(gate, seed)
        section_evidence_chain(gate, seed)

        # Invariant sweep verdict — R1 parity (verify_round1.py:390). Every
        # driven step ran the suite (in step()); assert zero violations across
        # the whole spine. A violation here is a real game defect, recorded as
        # a finding, never tuned away.
        print("\n  -- 5. per-step invariants across the full spine --")
        gate.check(
            not _VIOLATIONS,
            "invariant sweep is CLEAN across every driven step (R1 parity)",
            f"0 violations over {_STEP_NO} steps" if not _VIOLATIONS
            else f"{len(_VIOLATIONS)} violations over {_STEP_NO} steps")
        for v in _VIOLATIONS[:10]:
            print(f"    invariant violation — {v}")
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        gate.check(False, "exception-free run",
                   f"{type(exc).__name__}: {exc}")
    finally:
        # Stderr scan — R1 parity (verify_round1.py:404-409), in a finally so it
        # runs even when a section raises. Reads the real subprocess stderr of
        # every adapter this run (how PC-8 was originally caught), filtered
        # through the whitelist IMPORTED from R1 via the shared scan predicate.
        print("\n  -- 6. subprocess stderr (every adapter this run) --")
        all_err = [ln for ad in _ADAPTERS for ln in ad.stderr_lines]
        bad = scan_stderr(all_err, STDERR_WHITELIST)
        gate.check(
            not bad,
            "no SCRIPT ERROR on the game's stderr (R1 parity)",
            f"{len(bad)} error lines" + (f"; first: {bad[0]}" if bad else ""))

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
    print("\nPC-15 is a balance note (count-vs-type HP/DPS asymmetry, the-pond T-062)\n"
          "— the automated driver did not beat the boss this run. PC-12 is a named\n"
          "harness gap: the victory caller now exists (T-057) but no wire op reaches\n"
          "it. PC-17 is a NEW finding surfaced by U-008: the pause is COSMETIC —\n"
          "get_tree().paused flips but gameplay keeps running (the arena root is\n"
          "PROCESS_MODE_ALWAYS and every gameplay child inherits it; masked by the\n"
          "vacuous test_pause_menu.gd:109). The pause TOGGLE itself round-trips and\n"
          "never ends the run (PC-13 core confirmed). PC-11 (three distinct bosses)\n"
          "and PC-14 (locked arena spawner leak, the-pond T-061) are FIXED and now\n"
          "measured/reclassified above. See integrations/pond/RESULTS.md.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
