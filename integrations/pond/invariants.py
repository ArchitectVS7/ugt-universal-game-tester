"""
Pond Conspiracy invariants — predicates asserted after EVERY adapter step, in
both the scripted rounds (R1/R2, via InvariantSuite.check_command) and the R3
exploit-hunter (via to_hunter_invariants).

Every predicate reads state BACK from the harness snapshot and compares. None
of them re-implements a game rule: no predicate knows what damage a slime
deals, how fast a dodge is, or when a wave should advance — only that hp must
stay inside its own reported bounds, that a position must be a finite number
inside the arena the scene itself defines, and that the run state machine must
not contradict itself. That distinction is what keeps a UGT invariant from
quietly becoming a second copy of the game (the sim_bridge lesson).

`before`/`after` are the adapter's NORMALIZED flat dicts
(PondHarnessAdapter._normalize); `result` is the RAW harness snapshot for the
step (so predicates can reach `events`, `run.phase`, the enemy list, etc.).

Arena geometry comes from the real scene (combat/scenes/TestArena.tscn): a
1920x1080 Background with four StaticBody2D walls whose inner faces sit at
x=0/1920 and y=0/1080. BOUNDS_SLACK allows for the player's collision radius
and one frame of penetration before the wall pushes back — a real escape (no
collision, drifting forever) blows past it immediately.
"""
from __future__ import annotations

import math

from ugt.core.trial import InvariantSuite

ARENA_MIN_X, ARENA_MAX_X = 0.0, 1920.0
ARENA_MIN_Y, ARENA_MAX_Y = 0.0, 1080.0
BOUNDS_SLACK = 64.0  # collision radius + one frame of wall penetration

# RunManager.RunPhase keys, as the harness stringifies them
# (core/scripts/run_manager.gd: enum RunPhase).
KNOWN_PHASES = {"LOBBY", "COMBAT", "INVESTIGATION", "RUN_END"}

# Phases RunManager holds _is_run_active == true in: start_run() sets COMBAT and
# only end_run() clears the flag, so INVESTIGATION (reached from COMBAT without
# ending the run) is still an active phase.
ACTIVE_PHASES = {"COMBAT", "INVESTIGATION"}
INACTIVE_PHASES = {"LOBBY", "RUN_END"}


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def player_hp_in_bounds(before, after, command, result):
    """Player hp stays within [0, max_hp] its own snapshot reports."""
    hp, max_hp = after.get("player_hp"), after.get("player_max_hp")
    if not _finite(hp) or not _finite(max_hp):
        return f"non-finite hp: hp={hp!r} max_hp={max_hp!r}"
    if max_hp <= 0:
        return f"max_hp is not positive: {max_hp!r}"
    if hp < 0 or hp > max_hp:
        return f"hp out of bounds: {hp} not in [0, {max_hp}]"
    return None


def positions_finite(before, after, command, result):
    """Player and every active enemy have finite (non-NaN/inf) positions."""
    px, py = after.get("player_x"), after.get("player_y")
    if not _finite(px) or not _finite(py):
        return f"non-finite player position: ({px!r}, {py!r})"
    for i, enemy in enumerate(result.get("enemies") or []):
        pos = enemy.get("pos") or []
        if len(pos) != 2 or not all(_finite(c) for c in pos):
            return (f"non-finite enemy[{i}] ({enemy.get('type')!r}) "
                    f"position: {pos!r}")
    return None


def player_inside_arena(before, after, command, result):
    """Player stays inside the arena its own walls enclose (no escape)."""
    if after.get("player_dead"):
        return None  # a freed/dying player reports no meaningful position
    px, py = after.get("player_x"), after.get("player_y")
    if not (_finite(px) and _finite(py)):
        return None  # positions_finite owns that failure; don't double-report
    if not (ARENA_MIN_X - BOUNDS_SLACK <= px <= ARENA_MAX_X + BOUNDS_SLACK):
        return (f"player escaped horizontally: x={px:.1f} outside "
                f"[{ARENA_MIN_X}, {ARENA_MAX_X}] (+/-{BOUNDS_SLACK})")
    if not (ARENA_MIN_Y - BOUNDS_SLACK <= py <= ARENA_MAX_Y + BOUNDS_SLACK):
        return (f"player escaped vertically: y={py:.1f} outside "
                f"[{ARENA_MIN_Y}, {ARENA_MAX_Y}] (+/-{BOUNDS_SLACK})")
    return None


def enemy_hp_in_bounds(before, after, command, result):
    """Every ACTIVE enemy has hp within (0, max_hp] — a 0-hp enemy still in
    the active list is a corpse the spawner failed to reap."""
    for i, enemy in enumerate(result.get("enemies") or []):
        hp, max_hp = enemy.get("hp"), enemy.get("max_hp")
        if hp is None or max_hp is None:
            continue  # the boss exposes a different shape; not a violation
        if not _finite(hp) or not _finite(max_hp):
            return f"non-finite enemy[{i}] hp: {hp!r}/{max_hp!r}"
        if hp <= 0:
            return (f"active enemy[{i}] ({enemy.get('type')!r}) has hp={hp} "
                    f"— dead enemy still in the active list")
        if hp > max_hp:
            return (f"enemy[{i}] ({enemy.get('type')!r}) hp {hp} exceeds its "
                    f"own max {max_hp}")
    return None


def run_phase_known(before, after, command, result):
    """RunManager reports a phase from its own RunPhase enum, never a raw
    index or an unknown string."""
    phase = (result.get("run") or {}).get("phase")
    if phase is None:
        return "run.phase missing from the snapshot"
    if phase not in KNOWN_PHASES:
        return f"unknown run phase {phase!r} (known: {sorted(KNOWN_PHASES)})"
    return None


def run_active_matches_phase(before, after, command, result):
    """The run state machine does not contradict itself: is_run_active() is
    true exactly when the phase is an in-run phase, and false in LOBBY/RUN_END.
    """
    run = result.get("run") or {}
    phase, active = run.get("phase"), run.get("active")
    if phase is None or active is None:
        return None  # run_phase_known owns the missing-field failure
    if phase in INACTIVE_PHASES and active:
        return f"run reports active=True while phase={phase}"
    if phase in ACTIVE_PHASES and not active:
        return f"run reports active=False while phase={phase}"
    return None


def death_is_terminal(before, after, command, result):
    """Death is a one-way door: a player who was dead cannot report alive
    again without an intervening reset (no zombie resurrection mid-run)."""
    if before.get("player_dead") and not after.get("player_dead"):
        return (f"player resurrected mid-run: dead -> alive "
                f"(hp {before.get('player_hp')} -> {after.get('player_hp')})")
    return None


def total_runs_stable(before, after, command, result):
    """The persisted run counter never moves mid-episode. It moved twice per
    run before PC-4 was fixed upstream, and it is a difficulty INPUT (T-040),
    so drift here silently rescales the whole run."""
    was, now = before.get("total_runs"), after.get("total_runs")
    if was and now and was != now:
        return f"total_runs changed mid-episode: {was} -> {now}"
    return None


def bullets_bounded(before, after, command, result):
    """The BulletUpHell pool count stays finite and below a sane ceiling — a
    monotonically climbing count is the pool-leak signature."""
    bullets = after.get("bullets")
    if bullets is None or bullets < 0:
        return None  # -1 == the Spawning autoload was unavailable, not a leak
    if not _finite(bullets):
        return f"non-finite bullet count: {bullets!r}"
    if bullets > BULLET_CEILING:
        return (f"bullet pool count {bullets} exceeds the leak ceiling "
                f"{BULLET_CEILING}")
    return None


BULLET_CEILING = 5000


def level_up_freezes_the_game(before, after, command, result):
    """Whenever the level-up screen is up, the tree is paused — the choice is
    modal for the tester exactly as it is for a player. An unpaused level-up
    means enemies keep hitting a player who cannot move."""
    if after.get("level_up_pending") and not after.get("paused"):
        return ("level-up screen is showing but the tree is NOT paused "
                "(a player would be taking hits while choosing)")
    return None


def mutations_monotonic(before, after, command, result):
    """Applied mutations only ever accumulate within a run — a mutation that
    silently falls off the player is a lost selection."""
    was, now = before.get("mutations_taken"), after.get("mutations_taken")
    if was is not None and now is not None and now < was:
        return f"applied mutation count dropped: {was} -> {now}"
    return None


def evidence_monotonic(before, after, command, result):
    """Collected evidence only accumulates within a run (it decides the
    epilogue tier, so a silent drop rewrites the ending)."""
    was, now = before.get("evidence_count"), after.get("evidence_count")
    if was is not None and now is not None and now < was:
        return f"collected evidence count dropped: {was} -> {now}"
    return None


def build_suite() -> InvariantSuite:
    """The full per-step predicate set for R1/R2/R3."""
    return InvariantSuite([
        player_hp_in_bounds,
        positions_finite,
        player_inside_arena,
        enemy_hp_in_bounds,
        run_phase_known,
        run_active_matches_phase,
        death_is_terminal,
        total_runs_stable,
        bullets_bounded,
        level_up_freezes_the_game,
        mutations_monotonic,
        evidence_monotonic,
    ])
