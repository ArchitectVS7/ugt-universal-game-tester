# Pond Conspiracy (the-pond) — UGT Integration Plan

**Status: R2 NOT MET — 35/37 (2026-07-20, after U-001…U-007 + the-pond M7). Two remaining
non-passes, both by-design blocks that correctly fail the gate and are NOT in U-007's scope:
PC-15 (balance — driver did not beat the boss this run; re-baseline is U-009's) and PC-12
(victory run RESULT unobservable over the current wire — filed harness follow-up below). The
formerly-blocked modes PC-11/PC-13/PC-14 are FIXED + measured; the board card flip is DRIVEN
(U-007); and PC-16 (player escaped the arena during the boss fight) is FIXED upstream — the R2
invariant sweep is now CLEAN (0 violations / 1578 steps). Next rung: U-008 (harness pause) →
U-009 (R2 re-baseline) → R3 exploit-hunter.**

Prior status line (kept for history): R2 NOT MET — 21/26 (2026-07-20). Five blocked: four modes
the game had NO code path for, plus a boss the automated driver did not beat (PC-15 balance note,
see the-pond T-062).
R1 MET 18/18 seed-independent; all R1-round open items CLOSED; game suite fully green
1063/1063. PC-1 is fixed, so R3 same-seed replay is no longer blocked.

**R2 headline findings** (full diagnosis in RESULTS.md "R2 — full spine"):
- **PC-11 CRITICAL** — `BossArena.boss_scene` is set in ONE place (TestArena -> BossLobbyist).
  BossCEO/BossForeman are referenced only by unit tests, so the **TRUE ENDING can never
  unlock** (`check_ending_unlock` requires `ceo_defeated`), `all_bosses_defeated` is
  unreachable, and the CEO-gated informant + hints are dead. `docs/prd.md:198` specifies a boss
  per arena; that mapping was never implemented.
- **PC-12** — `end_run("victory")` has no production caller. Victory, 150% rewards,
  `successful_runs`, `best_time` and RunEndScreen's victory branch are all unreachable. Death
  is the only ending that exists.
- **PC-13** — there is no pause. The `pause` action calls `get_tree().quit()`: ESC destroys the
  run with no confirmation. (Not driven from the harness on purpose — it would let R3's random
  input kill the process.)
- **PC-14** — the "locked" boss arena clears regular enemies then leaves the spawner running,
  so it refills within seconds.
- **PC-15 balance** — the automated driver did not defeat the wave-5 boss (it survived with
  2-52 hp across 4 seeds and ~20 driver configurations). The earlier "fractional damage rounds
  to nothing → taking upgrades makes the fight harder" diagnosis is **WITHDRAWN**; the-pond
  T-062 (`test/unit/test_boss_damage_scaling.gd`, DONE) is the authoritative measurement. Its
  verdict: `mercury_blood` computes `1*1.5→round→2` (double damage, `player_controller.gd:214`),
  and for a 100-hp boss the inversion is **REFUTED for realistic (offense-inclusive) builds**
  (ttk@0≈52.4s → ttk@10≈28.8s, ~45% faster) and **confirmed only for a degenerate zero-offense
  build** (52.4s → 78.6s). The real mechanism is a **count-vs-type asymmetry** — boss HP scales
  with mutation *count* (`hp_scale_per_mutation`) while player DPS scales only with the
  damage/crit/cooldown *subset* — not fractional rounding (only `strong_legs` at 0.1 rounds
  away). Pass/fail re-baseline is U-009's.
Spike 13/13, smoke 8/8×3. `verify_round1.py` drives one full run loop: waves -> 10 real tongue
kills -> damage -> provoked dodge i-frames -> level-up -> mutation applied by a real CLICK ->
death -> `run_ended` -> epilogue -> visible RunEndScreen, with 0 invariant violations over 85
steps and 0 SCRIPT ERRORs. Verified on seeds 20260719, 777001, 424242 and 90210 — 18/18 on all
four, so the gate is no longer seed-fragile.

**Three game defects found by R1 and FIXED upstream this round:**
- **PC-5 (CRITICAL):** the tongue's tip-only hitbox left everything inside ~119px unhittable,
  so the player could never kill anything (24 swings, 0 hits, 0 kills). `_check_hits()` now
  sweeps a capsule from the player to the tip, unioned with the original tip area (which still
  owns the overshoot reach COMBAT-004 specifies). 8 swings -> 8 kills after.
- **PC-6:** `NarrativeState` computed the epilogue off `EventBus.run_ended` while
  `EvidenceManager` granted the run's evidence off the same signal, NarrativeState first — so a
  run's own reward could never appear in its own ending. Added `EventBus.run_rewards_due`,
  emitted by `RunManager.end_run()` immediately before `run_ended`; EvidenceManager listens
  there now. RunManager also settles its own state *before* emitting, so a consumer can no
  longer strand it mid-`end_run`.
- **PC-8:** `BossArena._clear_regular_enemies()` freed every non-boss node in
  `group("enemies")` — which includes the ~122 DORMANT pre-warmed pool instances, so
  triggering the boss destroyed the whole pool and every later spawn popped a freed instance
  (74 SCRIPT ERRORs). Root cause was `ObjectPool.prewarm()` never running the release-side
  hook, so a pre-warmed enemy kept `is_active == true` and looked live to any group scan.
  Fixed in both places, plus `EnemySpawner.despawn_enemy()` to remove an enemy from play
  without firing `died`/`enemy_killed`. The boss triggers by PROXIMITY, not only at wave 5 —
  which is why this bit at wave 2 and misled the first diagnosis.

Game gate after all three: **1032 passing / 25 failing vs baseline 27 — two better than
baseline, zero regressions.** PC-4 (run-start double-fire) was fixed the previous round. Determinism probe IDENTICAL twice (global RNG seedable today; only PC-1's
tongue-crit RNG island remains), so R3 replay is closer than the plan below assumed.

Harness: `the-pond/tests/harness/ugt_harness.gd` (now also `choose` + level-up/narrative/
run-end/tongue state); adapter: `ugt/adapters/pond_harness.py` (+ `ugt.config.yaml`, 14
input-macro actions, `choose_mutation`); invariants: `integrations/pond/invariants.py`;
scripts: `spike_pond.py`, `smoke_pond_adapter.py`, `verify_round1.py`. Findings + lessons:
`RESULTS.md`.

## OPEN ITEMS — updated 2026-07-20 after the open-items round (the-pond `a1fb390`)

**All four items the R1 round left open are CLOSED.** Ladder re-run after the fixes: spike
13/13 · smoke 8/8 · R1 18/18, unchanged. Game gate PASS, **ratcheted 27 → 21 failing**. Full
write-up in `RESULTS.md` ("Open-items round").

- **PC-1 CLOSED** — `tongue_attack.gd` now seeds `_rng` from the global RNG (`_rng.seed =
  randi()`) instead of `randomize()`. **R3 same-seed replay is unblocked.** Covered by two new
  upstream tests, incl. an anti-vacuity guard; the reproducibility test was confirmed to fail
  against the old code.
- **PC-2 CLOSED** — new `core/scripts/save_paths.gd` redirects default `user://` paths to a
  `headless_` sibling under the headless display driver. Worse than filed: a suite run was also
  *deleting* the real meta save and *overwriting* the real `savegame.json`, so `gate.sh` was
  destroying real player progression. Verified by md5: both real save files are byte-identical
  after a full suite run. The harness's explicit `MetaProgression.save_path` override still
  wins (only *default* paths get redirected).
- **ObjectPool hardening CLOSED** — `_available`/`_active` hold instance IDs; a freed entry
  resolves to null instead of dangling, and dead entries are discarded in a loop rather than by
  recursion. Two tests reproduce the external-free scenario.
- **The 3 `test_object_pool.gd` failures CLOSED — all three were real.** Two tests could never
  pass (a GDScript lambda captures locals **by value**, so the recorded bool never reached the
  assertion). The third, "Should track reuse count", was a genuine **product bug**:
  `reuse_count` counted every pool hit, so `prewarm(N)` + N acquires reported N reuses while
  each object had lived once. The test was right; the code was wrong. The HANDOFF's hunch that
  prewarm/`on_release` was implicated was wrong — the pool was innocent there.
- Also fixed: `test_main_menu`'s run-count test called `start_run()` twice back-to-back, which
  the deliberate re-entry guard makes a no-op. It passed only on cross-file suite state and
  failed when run alone **at HEAD too**.

**Cluster remediation DONE (the-pond `d83d932`): the game suite is FULLY GREEN, 1063/1063,
gate PASS** (was 25 failing at session start: 25 → 21 → 2 → 0). The "21 pre-existing failures"
turned out to be ~11 unpassable tests hiding **six real product bugs** — screen-shake `duration`
ignored entirely, particle systems double-parented, the Pollution Immune synergy silently doing
nothing, hit-stop discarding its delta, spawner tests vacuously green (asserting `max_enemies`
against zero enemies), and `gate.sh` unable to pass a green suite at all. Details in RESULTS.md
("Cluster remediation").

### Still open

- **PC-16 — RESOLVED upstream (the-pond `combat/scenes/Player.tscn`), but two related latent
  game-side items are filed for a future collision-model cleanup (NOT this task).** PC-16 (player
  escaped the arena vertically during the boss fight) was fixed by setting the Player
  `CharacterBody2D` `collision_mask` 2 → 3 so it collides with the boundary walls (which sit on the
  default physics layer 1). That is the surgical, R1-safe fix. The deeper items a game task should
  address: **(a)** the `TestArena.tscn` boundary `Walls` live on layer 1 ("Player") instead of layer 2
  ("Environment") — the game's own `scripts/validate_collision_setup.gd` matrix intends walls to be
  Environment and BOTH player and enemies to collide with them; **(b)** `enemy_spawner.gd`'s 600px
  spawn ring overshoots the 540px vertical half-height, so top/bottom spawns land OUTSIDE the arena
  (`y∈[-60,1140]`) and would be trapped the moment walls collide for enemies (moving walls to layer 2
  without fixing this regressed R1 to 13/18); **(c)** the `BossArena` inner `ArenaWalls` have no
  `CollisionShape2D` at all (only `ColorRect`s), so the "locked" boss box never physically confines —
  cosmetic only, and `boss_arena.gd:70-72`'s `set_deferred("disabled", …)` on those shapeless
  `StaticBody2D`s is a no-op. See RESULTS.md "U-007 (fix round 2): PC-16 FIXED" for the full analysis.
- **Harness gap (follow-up filed by U-001): no wire op reaches `EventBus.ending_unlocked`, so a
  `"victory"` run result cannot be OBSERVED over the wire.** The JSON-lines harness protocol
  (`tests/harness/ugt_harness.gd`) exposes only `create/step/choose/state/quit`. Reaching
  `ending_unlocked` (and thus `run_manager.gd:235`'s `end_run("victory")`, T-057) requires all 16
  data logs + the Lobbyist and CEO boss defeats + the smoking-gun conspiracy-board connection
  (`meta_progression.gd check_ending_unlock`) — none of which have an affordance in the harness. To
  let a future R2 observe a real `"victory"` run result and MetaProgression's victory arm
  (`successful_runs` / `win_rate` moving), the harness needs a new op to grant evidence / make a
  board connection (or otherwise drive `ending_unlocked`). Until then PC-12 is a reasoned
  `gate.blocked` in `verify_round2.py` naming exactly this gap (NOT "no production caller" — that is
  refuted, the caller now exists). Boss-defeat driving is separately blocked by PC-15 balance.
- **PC-9 — REFUTED as filed. I was wrong; max-range hit detection works.** (Tests since fixed
  and green.) See RESULTS.md
  "PC-9 investigation" for the full correction. The 11–28px I read as "the tongue never reaches
  144" is the **retract tail**: the tongue reaches 165.6px on extend frame 1 and is hard-set to
  exactly 144.0 on frame 10, then snaps back. `test_tongue_settles_at_max_range` advances 13
  frames and samples mid-retract. Reproduced the observed values to 2dp from the production
  easing (frame 13 = 28.08, frame 14 = 11.20 vs my measured 28.07/11.19), so this is settled,
  not argued. The ±1 frame is the engine double-driving `_physics_process` on the in-tree player.
- **PC-10 (real, but a DESIGN decision — do not fix unilaterally): the tongue reaches full
  extension in ONE frame.** `_ease_out_elastic` puts the tongue at 165.6px (max+overshoot,
  clamped) after 16ms, then wobbles 153 → 127 → 152 → 143 → settle. It never travels outward.
  This is exactly the human-UAT note ("snaps to full length on frame 1 and wobbles"), now with
  a mechanism. Note the implementation **matches the GUIDE's pseudocode** (`ease_out_elastic`),
  and "ease-out" legitimately means fast-start — but it contradicts the GUIDE's own prose
  ("extends over `extend_duration` 0.15s", 4–6 animation frames in the art checklist). This is
  the feel decision already parked at the-pond `TASKS.md:342`; it wants a playtest, not a guess.
- **PC-3 (benign)** — BulletUpHell `BuHSpawner._exit_tree` throws 3 "Thread must have been
  started" errors on every headless exit. Whitelisted in the ladder's stderr checks.

Human UAT only (an engine trial cannot sign these off):
- The tongue never visually animates outward — it snaps to full length on frame 1 and wobbles.
  The PC-5 hit-detection fix does not address this; see PC-9, they may share a root cause.
- Colorblind modes and visual polish generally (the ND U-110 precedent).
Game repo: `/Users/vs7/Dev/Games/the-pond/` · Godot 4.7.1 (`/opt/homebrew/bin/godot`) · GDScript ·
real-time top-down bullet-hell roguelike ("Pond Conspiracy", v0.1.0).

This would be **game #7** and the **first real-time / first Godot** integration. The portfolio survey
rated Godot titles "Hard"; the 2026-07-19 feasibility probe (below) downgrades this one to **Medium**:
the game's own dev process already runs fully headless, and the hooks UGT needs mostly exist.

## Feasibility evidence (probe run 2026-07-19, scratchpad `ugt_pond_probe.gd`)

A `SceneTree` script run via `godot --headless --path . -s <script>` against the real project:

- All 13 autoloads boot headless (EventBus, RunManager, MetaProgression, EvidenceManager, SceneRouter, …).
- The real `combat/scenes/TestArena.tscn` instantiates; the real Player node is found.
- `Input.action_press("move_right")` moved the player 80px over 60 physics frames — **named-action
  input injection works headless**. ALL game input is named actions (`move_*`, `attack`, `dodge`,
  `pause`) — no raw-mouse-only paths.
- `player_controller.gd` already ships `aim_target_override` — a hook explicitly built for
  "gamepad/AI-driven aim … deterministic tests where the OS cursor cannot be warped".
- `RunManager.is_run_active()` and friends give structured state; JSON.stringify works.
- The game's own gate (`scripts/gate.sh`) runs headless import + full GUT suite; the T-047 E2E test
  (`test/integration/test_end_to_end_loop.gd`) drives the whole boss→evidence→board→epilogue spine
  against live autoloads headlessly. Headless is this game's native test mode, not an exotic ask.

## Architecture: DDD-pattern JSON-lines subprocess harness

Same shape as `ugt/adapters/ddd_harness.py` / `nexus_dominion_harness.py` — engine-first trial,
constructed directly by ladder scripts (no `engine.type` registration needed).

**Game side** (new, wire-only — lives in the-pond repo, e.g. `tests/harness/ugt_harness.gd`):
a `SceneTree` script speaking one JSON request/response per line over stdin/stdout:

- `{"op":"create","arena":"TestArena","seed":…}` → loads the REAL scene, redirects
  `MetaProgression.save_path` to a scratch save (see finding PC-2), pins meta state (run count is a
  difficulty input per T-040 — it must be an explicit config key, the DDD exact-config-key lesson).
- `{"op":"step","frames":N,"input":{"move":[dx,dy],"attack":bool,"dodge":bool,"aim":[x,y]}}` →
  unpause, apply `Input.action_press/release` + `aim_target_override`, advance exactly N physics
  frames, re-pause, return a state snapshot.
- State snapshot = structural reads only: player pos/hp/i-frames/dodge-cooldown, enemies
  (pos/hp/type), active bullet count, wave/boss state, RunManager stats, plus **all EventBus signals
  drained since the last step** (player_damaged, enemy_killed, level_up, evidence_unlocked,
  run_ended, …). The EventBus tap is the killer feature: every module's real event stream, zero
  game-logic duplication.
- `{"op":"choose","mutation":i}` (level-up picks), `{"op":"state"}`, `{"op":"quit"}`.

Pause discipline: `get_tree().paused = true` between commands; harness node
`PROCESS_MODE_ALWAYS`. A step is exactly N physics frames — wall clock is irrelevant, so headless
max-FPS drift can't desync anything.

**UGT side** (new `ugt/adapters/pond_harness.py`, `PondHarnessAdapter`): transport only, NO game
logic. Discrete action ids = macro inputs ("move N ×10 frames", "move NE + attack", "dodge toward
nearest bullet-free sector" is NOT allowed — that's game logic; instead "dodge + move dir" macros,
aim always at nearest enemy via structural read of the harness's own enemy list). Unmapped ids raise
`NotImplementedError` per repo convention.

## Trial ladder

1. **Spike** (`spike_pond.py`) — raw protocol round-trip: create → 20 steps of held input → state
   deltas sane → quit clean. The probe already proves ~80% of this.
2. **Smoke** (`smoke_pond_adapter.py`) — same path through `BaseAdapter`, 5 random steps.
3. **R1 playability** — one full run loop through the adapter: waves spawn, kill ≥1 enemy (real
   tongue-attack via injected input, not any API), take damage, trigger a level-up + pick a
   mutation, die → `run_ended` → non-default epilogue reaches RunEndScreen state. Invariants
   asserted every step.
4. **R2 full spine** — every mode to a real outcome: all 3 arenas (ChemicalPlant / CorporateHQ /
   PollutedWetland) + their hazards, wave-5 boss reached and DEFEATED for each of the 3 bosses
   (Lobbyist/CEO/Foreman), dodge i-frames actually negate a hit, evidence → conspiracy-board card
   flip → epilogue chain (the T-047 spine, but wire-driven), both run-end paths (death, victory),
   pause. Colorblind modes + visual polish are OUT of scope — flag for human UAT (the ND U-110
   precedent).
   - **Board card flip — DRIVEN & MEASURED (U-007, no longer a silent gap).** The harness gained
     an opt-in `with_board` create flag (`ugt_harness.gd::_spawn_board` + `_board_state()`, in the
     style of the `boss_id` accessor) that instances the real `ConspiracyBoard` headless (the same
     `instantiate()` path the T-047 E2E test uses) and reads back each live `DataLogCard`'s own
     `is_discovered()`, the board's `discovered_count`, and MetaProgression's persistent ending gate
     (`get_unlock_status`/`has_connection`, `CORPORATE_ENDING_ID`). `verify_round2.py` §4 now drives
     a real death run whose `EventBus.evidence_unlocked` flips `data_log_01` undiscovered→discovered
     on the live board — asserted as a `false→true` transition, a `discovered_count` delta that
     matches the cards actually flipped, and lockstep with `logs_collected`. The old `gate.info`
     "not driven by this section" note is gone. The FULL `CORPORATE_ENDING_ID` unlock (all 16 logs +
     Lobbyist + CEO + the `data_log_04↔data_log_07` smoking-gun board connection) still can't be
     reached over the current wire — that residual is the same PC-12 harness gap (no evidence-grant /
     board-connection op), tracked below, not a board-flip gap.
5. **R3 exploit-hunter** — `ExploitHunter` with invariants: hp ∈ [0, max]; no NaN/inf positions;
   player inside arena bounds; bullet count bounded (pool leak detector); run/evidence state machine
   consistent (no dupe unlocks); no `SCRIPT ERROR` on the subprocess stderr; soft-lock detection
   (state hash frozen across varied inputs). Plus same-seed replay — **PC-1 is now fixed, so
   this is unblocked**; the pre-filed note below is kept as the original diagnosis.

**LLM playtest tier: DEFERRED.** Real-time dodging is the wrong granularity for an LLM. A later
macro-layer playtest (mutation build choices + conspiracy-board connections) is plausible via the
same pause-step harness, but is not part of this trial.

## Pre-filed game-side findings (from the evaluation alone)

- **PC-1 (FIXED 2026-07-20 — original diagnosis kept for the record): RNG is globally unseeded.** `randi()/randf()` in
  `enemy_spawner.gd`, `enemy_base.gd`, `boss_ceo.gd`; `_rng.randomize()` in `tongue_attack.gd`.
  No seed plumbing exists anywhere. Deterministic replay needs a RunManager-owned seeded RNG (the
  same fix NEXUS and nexus-dominion took). Beyond seeding, Godot-physics float determinism on one
  machine/binary is expected-but-unproven — R3 falls back to a quantized-state hash if byte-exact
  fails, with the gap documented.
- **PC-2 (FIXED 2026-07-20 — original diagnosis kept for the record): headless test/tool runs write the REAL meta save.** The probe alone bumped the persistent
  run counter to #12865 — and run count drives difficulty scaling (T-040), so thousands of test
  runs have already polluted the shipped difficulty curve input. T-047 redirects `save_path`; the
  arena boot path doesn't. Harness must redirect; game should consider a `--test-save` guard.
- **PC-3 (noise): BulletUpHell `BuHSpawner._exit_tree` throws 3 "Thread must have been started"
  errors on every headless exit** (BuHSpawner.gd:140-144). Benign teardown bug in the forked addon.
- Known upstream: ~21 legacy test files fail to LOAD headless under Godot 4.7 (documented in
  `gate.sh`, ratcheted). Don't let harness stderr-scanning confuse their noise with new errors.

## Effort estimate

Game-side harness (~300–400 lines GDScript) is the long pole; adapter + spike/smoke ≈ 1 session,
R1 ≈ 1, R2 ≈ 1–2, R3 ≈ 1–2 (includes the PC-1 seeding fix upstream). Total **3–5 sessions**,
vs. same-day for nexus-dominion — the real-time/pause-step machinery and the seeding work are the
delta. Timing is good: the run loop was just wired (T-047/T-051 landed 2026-07-19) and the game is
pre-feature-freeze, so findings land while the code is hot.

## Next step

Write `tests/harness/ugt_harness.gd` in the-pond (create/step/state/quit ops only), then
`spike_pond.py` here. Nothing else until the spike round-trips.
