# Pond Conspiracy (the-pond) — UGT Integration Plan

**Status: SPIKE MET 13/13 (2026-07-19, same day as evaluation). Next: smoke via a
`PondHarnessAdapter` (BaseAdapter), then R1.** Harness: `the-pond/tests/harness/ugt_harness.gd`
(uncommitted in the game repo). Spike: `spike_pond.py`. Findings + harness lessons: `RESULTS.md` —
note the determinism probe came back IDENTICAL twice (global RNG is seedable today; only PC-1's
tongue-crit RNG island remains), so R3 replay is closer than the plan below assumed.
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
