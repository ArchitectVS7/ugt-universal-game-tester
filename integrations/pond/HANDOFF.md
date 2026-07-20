# Pond Conspiracy (the-pond) — UGT Integration Plan

**Status: R1 MET 18/18, seed-independent (2026-07-20). Next: R2 full spine.**
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

## OPEN ITEMS (as of 2026-07-20) — nothing here blocks R2

Blocking a later rung:
- **PC-1 — blocks R3 replay.** `tongue_attack.gd` owns a private `RandomNumberGenerator` that
  calls `randomize()` in `_ready()`. Every other combat draw uses the global RNG the harness
  seeds, and the determinism probe was identical twice, so this is the last known unseeded
  island before same-seed replay is real. Fix: seed `_rng` from the global RNG / a
  RunManager-owned seed.

Game-side, not blocking:
- **PC-2 — headless runs write the REAL settings save.** `MetaProgression.save_path` is
  redirected by the harness, but `SaveManager.SAVE_PATH` is a `const` and is not. The
  persistent run counter is already test-polluted past #13500, and run count is a difficulty
  input (T-040), so the shipped curve is fed a polluted number. Fix: make the path
  redirectable and/or add a headless guard; consider resetting the counter.
- **PC-3 (benign)** — BulletUpHell `BuHSpawner._exit_tree` throws 3 "Thread must have been
  started" errors on every headless exit. Whitelisted in the ladder's stderr checks.
- **ObjectPool hardening (follow-up from PC-8, NOT a live bug).** Nothing frees the pool now,
  but the pool is still structurally fragile to an external free: a freed entry in
  `_available` costs one engine SCRIPT ERROR per pop, and `acquire()` retries by RECURSION
  (`return acquire(scene)`, `shared/scripts/object_pool.gd:133`). Holding `instance_id`s and
  resolving via `instance_from_id()` would make it immune. Note `test_object_pool.gd` covers
  this file — keep it green.
- **3 pre-existing `test_object_pool.gd` failures**, part of the repo's ~25-test failing
  baseline and NOT caused by the PC-8 work (verified identical before and after): "Should
  track reuse count", "Reset callback should be called", "Deactivate callback should be
  called". Worth their own look — the last two are suspicious given prewarm now runs
  `on_release`.

Human UAT only (an engine trial cannot sign these off):
- The tongue never visually animates outward — it snaps to full length on frame 1 and wobbles.
  The PC-5 hit-detection fix does not address this.
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
5. **R3 exploit-hunter** — `ExploitHunter` with invariants: hp ∈ [0, max]; no NaN/inf positions;
   player inside arena bounds; bullet count bounded (pool leak detector); run/evidence state machine
   consistent (no dupe unlocks); no `SCRIPT ERROR` on the subprocess stderr; soft-lock detection
   (state hash frozen across varied inputs). Plus same-seed replay — **blocked on PC-1 below**.

**LLM playtest tier: DEFERRED.** Real-time dodging is the wrong granularity for an LLM. A later
macro-layer playtest (mutation build choices + conspiracy-board connections) is plausible via the
same pause-step harness, but is not part of this trial.

## Pre-filed game-side findings (from the evaluation alone)

- **PC-1 (blocker for R3 replay): RNG is globally unseeded.** `randi()/randf()` in
  `enemy_spawner.gd`, `enemy_base.gd`, `boss_ceo.gd`; `_rng.randomize()` in `tongue_attack.gd`.
  No seed plumbing exists anywhere. Deterministic replay needs a RunManager-owned seeded RNG (the
  same fix NEXUS and nexus-dominion took). Beyond seeding, Godot-physics float determinism on one
  machine/binary is expected-but-unproven — R3 falls back to a quantized-state hash if byte-exact
  fails, with the gap documented.
- **PC-2: headless test/tool runs write the REAL meta save.** The probe alone bumped the persistent
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
