#!/usr/bin/env python3
"""
Pond Conspiracy ROUND 1 — the playability gate: one full run loop driven through
`PondHarnessAdapter` against the REAL headless game, with the invariant suite
asserted after EVERY step.

R1 answers "is this game playable over the wire?" — every beat of the core loop
reached through real input, never an API:

  * waves spawn and the agent KILLS enemies with the real tongue attack —
    confirmed by `enemy_killed` on the EventBus tap, not by reading internals;
  * the player takes real contact/bullet damage (`player_damaged`) and survives
    a dodge window: no damage event ever lands on a step the player spent
    invulnerable, and that window is provoked deliberately (not waited for);
  * 10 kills trigger a level-up, and a mutation is picked by CLICKING a card —
    MutationCard accepts only InputEventMouseButton, so the harness synthesizes
    that click; the pick is confirmed by the player's own MutationManager
    reporting the mutation applied;
  * the run ends by death -> `player_died` -> `run_ended` -> NarrativeState
    generates an epilogue -> the RunEndScreen overlay is presented with it
    (the T-047 spine, but wire-driven end to end);
  * per-step invariants (integrations/pond/invariants.py): hp in [0, max], no
    NaN/inf positions, player inside the arena its own walls define, run state
    machine self-consistent, level-up freezes the game, no SCRIPT ERROR on the
    subprocess stderr.

The epilogue TIER check is deliberately "correct for this run", not "non-default":
NarrativeState picks NO_EVIDENCE unless evidence was collected, and evidence comes
from defeating a wave-5 boss — that is R2's job. Asserting a non-default epilogue
here would only be satisfiable by smuggling in a boss kill, so R1 instead asserts
the epilogue MATCHES the evidence actually collected (sentinel iff none). See
RESULTS.md finding PC-6 for the ordering bug this check exists to pin.

No game logic is reimplemented; every fact is read back from the harness snapshot.
A failed check is DATA — it prints as a FINDING and fails the gate, to be fixed
upstream in the game, never tolerated here.

Run (from the UGT repo root; needs godot 4.7 on PATH or UGT_GODOT_BIN):
    python3 integrations/pond/verify_round1.py [seed]

Exit 0 + "ROUND 1 MET — N/N" means the gate passed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import invariants  # noqa: E402  (local module, from integrations/pond/)

from ugt.adapters.pond_harness import PondHarnessAdapter  # noqa: E402
from ugt.core.trial import GateRunner  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/pond/ugt.config.yaml"
DEFAULT_SEED = 20260719

# Action ids (must match ugt.config.yaml / PondHarnessAdapter).
A_IDLE, A_ATTACK, A_DODGE, A_CHASE, A_KITE = 0, 9, 10, 11, 12

FIGHT_CAP = 400      # steps allowed to reach a level-up (10 kills)
DIE_CAP = 200        # steps allowed to then die
KILLS_PER_LEVEL = 10  # LevelUpTrigger.kills_per_level_up (game-side default)

# PC-3: BulletUpHell teardown noise in the forked addon, plus the engine's exit
# leak warnings. Whitelisted so real SCRIPT ERRORs still fail the gate.
STDERR_WHITELIST = (
    "Thread must have been started",
    "BuHSpawner.gd",
    "GDScript backtrace",
    "[0] _exit_tree",
    "at: wait_to_finish",
    "ObjectDB instances were leaked",
    "resources still in use",
    "at: cleanup",
    "at: clear",
    "WARNING",
)


class Episode:
    """One R1 run: drives the adapter and records everything observed."""

    def __init__(self, adapter, suite, gate):
        self.ad = adapter
        self.suite = suite
        self.gate = gate
        self.violations: list[str] = []
        self.events: list[dict] = []          # every EventBus signal, in order
        self.kills = 0
        self.damage_events = 0
        self.level_ups = 0
        self.steps = 0
        self.dodge_saves = 0                  # invulnerable steps with a hostile adjacent
        self.damage_while_invulnerable = 0    # must stay 0 — i-frames are absolute
        self.chosen: list = []                # mutation ids the game applied
        self.offered: list = []               # cards the level-up screen showed
        self.state = None

    def step(self, action_id: int):
        before = self.state
        after, term, trunc, info = self.ad.step(action_id)
        self.steps += 1
        self.state = after

        raw = self.ad.last_snapshot or {}
        for msg in self.suite.check_command(before, after, "step", raw):
            self.violations.append(
                f"step {self.steps} ({info.get('actionName')}): {msg}")

        step_events = info.get("events") or []
        self.events.extend(step_events)
        for e in step_events:
            sig = e.get("signal")
            if sig == "enemy_killed":
                self.kills += 1
            elif sig == "player_damaged":
                self.damage_events += 1

        # i-frame accounting. A step the player entered AND left invulnerable
        # was spent entirely inside the dodge window, so a player_damaged event
        # on it would mean i-frames do not actually protect.
        fully_invulnerable = bool(before and before.get("player_invulnerable")
                                  and after.get("player_invulnerable"))
        took_damage = any(e.get("signal") == "player_damaged"
                          for e in step_events)
        if fully_invulnerable:
            if took_damage:
                self.damage_while_invulnerable += 1
            elif before and before.get("enemy_count", 0) > 0 and \
                    before.get("nearest_enemy_dist", 1e9) <= CONTACT_RANGE:
                # Distance is read from BEFORE: the dodge itself hurls the
                # player away at 500px/s, so by the end of the step the enemy
                # that was touching us is no longer adjacent. What we are
                # claiming is "an enemy was on top of us, we spent the whole
                # step invulnerable, and we took no damage".
                self.dodge_saves += 1

        return after, term, trunc, info


# Distance at which a touching enemy deals contact damage. Derived from the
# enemy/player collision radii in the real scenes (EnemyBasic CircleShape2D
# radius 12 + the player's 28x28 hurtbox), NOT from a game rule — it is only
# used to say "an enemy was close enough to hurt us and didn't".
CONTACT_RANGE = 32.0


def main() -> int:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SEED
    cfg = UgtConfig(CONFIG_PATH)
    ad = PondHarnessAdapter(cfg)
    suite = invariants.build_suite()
    gate = GateRunner()
    ck, finding = gate.ck, gate.finding

    print(f"Pond Conspiracy Round 1 — one full run loop (seed {seed})\n")
    ep = Episode(ad, suite, gate)

    try:
        # ── 1. the run starts ────────────────────────────────────────────────
        print("  -- 1. run starts --")
        ad.connect()
        ep.state = ad.reset(seed=seed)
        st = ep.state
        ck("reset() -> live run in COMBAT, full hp, virgin meta",
           st["run_active"] == 1 and st["player_hp"] == st["player_max_hp"] > 0
           and st["player_dead"] == 0 and st["total_runs"] == 1
           and (ad.last_snapshot or {}).get("run", {}).get("phase") == "COMBAT",
           f"arena={ad.arena_id!r} hp={st['player_hp']}/{st['player_max_hp']} "
           f"phase={(ad.last_snapshot or {}).get('run', {}).get('phase')}")

        # ── 2. fight: waves spawn, kill until a level-up is offered ──────────
        print("\n  -- 2. combat: waves, kills, damage, level-up --")
        saw_enemies = False
        while ep.steps < FIGHT_CAP:
            if ad.level_up_pending():
                break
            st = ep.state
            if st["enemy_count"] > 0:
                saw_enemies = True
            # Play like a player: close the distance, swing in range, and dodge
            # out when hurt with something on top of us.
            if st["enemy_count"] == 0:
                action = A_IDLE
            elif st["player_hp"] < st["player_max_hp"] * 0.5 \
                    and st["nearest_enemy_dist"] <= CONTACT_RANGE:
                action = A_DODGE
            elif st["nearest_enemy_dist"] <= 130:
                action = A_ATTACK
            else:
                action = A_CHASE
            _, term, _, _ = ep.step(action)
            if term:
                break

        ck("enemy waves spawn and become reachable", saw_enemies,
           f"max seen enemy_count>0 within {ep.steps} steps")

        ck("agent kills enemies through the real input path (enemy_killed)",
           ep.kills > 0,
           f"{ep.kills} enemy_killed events in {ep.steps} steps "
           f"(tongue swings connect)")

        ck("player takes real damage (player_damaged)", ep.damage_events > 0,
           f"{ep.damage_events} player_damaged events, "
           f"hp={ep.state['player_hp']}/{ep.state['player_max_hp']}")

        # ── 3. level-up + mutation pick through the real UI ──────────────────
        # Resolved BEFORE the dodge probe: the fight loop above exits the moment
        # a level-up is pending, and while that screen is up the tree is paused,
        # so any dodge probe run first would step a frozen game and measure
        # nothing.
        print("\n  -- 3. level-up + mutation selection (real click) --")
        while ep.steps < FIGHT_CAP and not ad.level_up_pending() \
                and not ep.state["player_dead"]:
            st = ep.state
            action = A_ATTACK if st["nearest_enemy_dist"] <= 130 else A_CHASE
            _, term, _, _ = ep.step(action)
            if term:
                break

        level_up_offered = ad.level_up_pending()
        ep.offered = ad.level_up_options()
        ck(f"{KILLS_PER_LEVEL} kills trigger a level-up with cards on screen",
           level_up_offered and len(ep.offered) > 0,
           f"pending={level_up_offered} cards={[o.get('name') for o in ep.offered]} "
           f"after {ep.kills} kills")

        if level_up_offered:
            ck("the level-up screen freezes the game (paused while choosing)",
               ep.state["paused"] == 1 or
               (ad.last_snapshot or {}).get("paused") is True,
               f"paused={(ad.last_snapshot or {}).get('paused')}")

            before_ids = list(((ad.last_snapshot or {}).get("mutations") or {})
                              .get("active_ids") or [])
            after_state, choose_events = ad.choose_mutation(0)
            ep.state = after_state
            ep.events.extend(choose_events)
            ep.level_ups += 1
            after_ids = list(((ad.last_snapshot or {}).get("mutations") or {})
                             .get("active_ids") or [])
            ep.chosen = after_ids
            gained = [m for m in after_ids if m not in before_ids]

            ck("clicking a card APPLIES the mutation to the player",
               len(gained) == 1,
               f"MutationManager active_ids {before_ids} -> {after_ids}")

            ck("mutation_selected reached the bus and the screen dismissed",
               any(e.get("signal") == "mutation_selected"
                   for e in choose_events)
               and not ad.level_up_pending()
               and after_state["paused"] == 0,
               f"pending={ad.level_up_pending()} paused={after_state['paused']} "
               f"signals={[e.get('signal') for e in choose_events]}")
        else:
            finding(f"no level-up within {FIGHT_CAP} steps "
                    f"({ep.kills} kills, need {KILLS_PER_LEVEL})")
            ck("the level-up screen freezes the game (paused while choosing)",
               False, "not reached — no level-up offered")
            ck("clicking a card APPLIES the mutation to the player",
               False, "not reached — no level-up offered")
            ck("mutation_selected reached the bus and the screen dismissed",
               False, "not reached — no level-up offered")

        # ── 4. dodge i-frames ────────────────────────────────────────────────
        print("\n  -- 4. dodge i-frames --")
        # Provoke the window rather than hoping for it: close on the pack and
        # dodge, repeatedly, so invulnerability overlaps a real threat.
        #
        # Step FINER than the i-frame window for this probe. dodge_iframe_duration
        # is 0.3s = 18 frames, so with the normal 30-frame step invulnerability
        # always begins and ends INSIDE one step and is never observable at both
        # snapshot boundaries — the check would read 0 saves no matter how well
        # the game behaves. At 6 frames per step a dodge spans ~3 steps, so a
        # step can be entirely within the window.
        normal_frames = ad.frames_per_step
        ad.frames_per_step = 6
        probe_steps = 0
        while ep.dodge_saves == 0 and probe_steps < 80 \
                and not ep.state["player_dead"]:
            if ad.level_up_pending():
                ep.state, more = ad.choose_mutation(0)
                ep.events.extend(more)
                ep.level_ups += 1
                continue
            near = ep.state["nearest_enemy_dist"] <= CONTACT_RANGE
            _, term, _, _ = ep.step(A_DODGE if near else A_CHASE)
            probe_steps += 1
            if term:
                break
        ad.frames_per_step = normal_frames

        ck("dodge i-frames engage and negate contact while a hostile is on top",
           ep.dodge_saves > 0,
           f"{ep.dodge_saves} fully-invulnerable steps with an enemy within "
           f"{CONTACT_RANGE:.0f}px and zero damage (probe steps={probe_steps})")

        ck("no damage EVER lands while the player is invulnerable",
           ep.damage_while_invulnerable == 0,
           f"{ep.damage_while_invulnerable} player_damaged events during "
           f"i-frames")
        if ep.damage_while_invulnerable:
            finding("dodge i-frames do not actually protect: player_damaged "
                    "fired on a step spent entirely invulnerable")

        # ── 5. death closes the run-end spine ───────────────────────────────
        print("\n  -- 5. death -> run_ended -> epilogue -> RunEndScreen --")
        died = ep.state["player_dead"] == 1
        die_steps = 0
        while not died and die_steps < DIE_CAP:
            # A level-up freezes the tree; clear it or the game can never
            # advance to the death we are waiting for.
            if ad.level_up_pending():
                ep.state, more = ad.choose_mutation(0)
                ep.events.extend(more)
                ep.level_ups += 1
                continue
            # Stop defending: walk into the swarm and stand there.
            action = A_CHASE if ep.state["nearest_enemy_dist"] > CONTACT_RANGE \
                else A_IDLE
            _, term, _, _ = ep.step(action)
            die_steps += 1
            if term or ep.state["player_dead"]:
                died = True
                break

        sigs = [e.get("signal") for e in ep.events]
        raw = ad.last_snapshot or {}
        run = raw.get("run") or {}
        narrative = raw.get("narrative") or {}
        run_end = raw.get("run_end") or {}

        ck("player dies and the run terminates in RUN_END",
           died and run.get("phase") == "RUN_END" and run.get("active") is False,
           f"dead={died} phase={run.get('phase')} active={run.get('active')} "
           f"(after {die_steps} extra steps)")

        ck("death fires player_died then run_ended('death')",
           "player_died" in sigs and "run_ended" in sigs
           and narrative.get("last_result") == "death",
           f"player_died={'player_died' in sigs} run_ended={'run_ended' in sigs} "
           f"result={narrative.get('last_result')!r}")

        epilogue = narrative.get("epilogue") or ""
        ck("NarrativeState generates an epilogue (epilogue_generated)",
           "epilogue_generated" in sigs and bool(epilogue.strip()),
           f"{len(epilogue)} chars: {epilogue[:70]!r}")

        # The epilogue must be CORRECT for what this run achieved: the
        # NO_EVIDENCE sentinel exactly when no evidence was collected. The
        # sentinel is recognised from the game's OWN template constant (its
        # static fragments), never a hardcoded copy of the prose.
        template = narrative.get("no_evidence_template") or ""
        fragments = [f.strip() for f in _static_fragments(template) if len(f.strip()) > 12]
        is_sentinel = bool(fragments) and all(f in epilogue for f in fragments)
        evidence = narrative.get("evidence") or []
        expected_sentinel = len(evidence) == 0
        ck("epilogue tier matches the evidence actually collected",
           is_sentinel == expected_sentinel,
           f"evidence={evidence} sentinel={is_sentinel} "
           f"expected_sentinel={expected_sentinel}")
        if is_sentinel != expected_sentinel:
            finding(
                f"epilogue tier disagrees with NarrativeState evidence "
                f"{evidence}: the run generated "
                f"{'the NO_EVIDENCE sentinel' if is_sentinel else 'an evidence tier'}"
                f" — see PC-6 (epilogue is computed synchronously in "
                f"_on_run_ended, before late evidence registers)")

        ck("RunEndScreen overlay is presented, visible, and shows the epilogue",
           run_end.get("present") is True and run_end.get("visible") is True
           and (run_end.get("epilogue_text") or "").strip() == epilogue.strip(),
           f"present={run_end.get('present')} visible={run_end.get('visible')} "
           f"scene={run_end.get('scene')!r} "
           f"epilogue_matches={(run_end.get('epilogue_text') or '').strip() == epilogue.strip()}")

        ck("RunEndScreen reports the run's real outcome and stats",
           "Defeated" in (run_end.get("stats_text") or "")
           and run_end.get("true_ending_visible") is False,
           f"stats={(run_end.get('stats_text') or '')[:60]!r} "
           f"true_ending_visible={run_end.get('true_ending_visible')}")

        # ── 6. invariants across every step ─────────────────────────────────
        print("\n  -- 6. per-step invariants --")
        ck("invariant sweep is CLEAN across every step of the run",
           not ep.violations,
           "0 violations over %d steps" % ep.steps if not ep.violations
           else f"{len(ep.violations)} violations")
        for v in ep.violations[:10]:
            finding(f"invariant violation — {v}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        gate.ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        # ── 7. stderr is clean ──────────────────────────────────────────────
        print("\n  -- 7. subprocess stderr --")
        bad = [ln for ln in ad.stderr_lines
               if ("SCRIPT ERROR" in ln or "Parse Error" in ln)
               and not any(w in ln for w in STDERR_WHITELIST)]
        gate.ck("no SCRIPT ERROR on the game's stderr", not bad,
                f"{len(bad)} error lines"
                + (f"; first: {bad[0]}" if bad else ""))
        ad.close()

    print(f"\n  run summary: {ep.steps} steps, {ep.kills} kills, "
          f"{ep.damage_events} damage events, {ep.level_ups} level-up(s) "
          f"{[o.get('name') for o in ep.offered]} -> {ep.chosen}, "
          f"{ep.dodge_saves} dodge saves")

    return gate.finish(
        "ROUND 1",
        "The game is playable over the wire: waves spawn, real input kills "
        "enemies, damage and dodge i-frames behave, a level-up is picked by "
        "clicking a real card, and death closes the run-end spine through to "
        "the RunEndScreen. Ready for R2.")


def _static_fragments(template: str) -> list:
    """Split a Godot String.format template into its literal parts, dropping
    the {placeholders}. Lets a driver recognise the game's own epilogue text
    without copying its prose into this file."""
    parts, buf, depth = [], [], 0
    for ch in template:
        if ch == "{":
            depth += 1
            if depth == 1 and buf:
                parts.append("".join(buf))
                buf = []
        elif ch == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


if __name__ == "__main__":
    sys.exit(main())
