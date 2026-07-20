# Pond Conspiracy — trial findings log

Commit-traceable record. A failed check is data. Game repo: `~/Dev/Games/the-pond/`.

## 2026-07-20 — R1 MET 18/18 · PC-5 (CRITICAL) + PC-6 found and FIXED upstream

`verify_round1.py`, seed 20260719, one full run loop through `PondHarnessAdapter`:
**18/18 checks, 0 invariant violations over 85 steps, 0 SCRIPT ERRORs**, reproduced twice.
Game gate after both fixes: **1032 passing / 25 failing vs baseline 27 — two BETTER than
baseline, zero regressions.** Ladder re-run end to end: spike 13/13, smoke 8/8, R1 18/18.

Two real game defects were found by this gate and fixed upstream (PC-5 critical, PC-6
medium), plus three harness/driver defects of my own. R1 reached MET only after all five.

⚠️ **MET on the pinned seed, not on every seed.** A second seed (777001) reaches 17/18: the
run plays fine (10 kills, level-up, mutation, death, epilogue) but the stderr check fails on
**74 SCRIPT ERROR lines** from a NEW game finding, PC-8 below. So R1's *playability* claim
holds, and one robustness check is seed-dependent. Do not treat R1 as fully green until PC-8
lands — and do not re-pin the gate to a friendlier seed to make it pass.

### PC-8 (OPEN, MEDIUM — fails R1 on seed 777001): the enemy ObjectPool floods stderr with
### "Trying to return a previously freed instance"

74 SCRIPT ERROR lines in one run, first at step 57, all with the same backtrace:

```
SCRIPT ERROR: Trying to return a previously freed instance.
  at: ObjectPool._pop_available (res://shared/scripts/object_pool.gd:310)
  [1] acquire            (object_pool.gd:129)
  [2] _create_enemy      (enemy_spawner.gd:340)
  [3] _try_spawn_enemy   (enemy_spawner.gd:277)
  [4] _physics_process   (enemy_spawner.gd:185)
```

Not caused by the PC-5 tongue change (different subsystem; the sweep guards
`is_instance_valid` and the trace never enters combat code).

The pool's *logic* is actually correct — `acquire()` pops, checks `is_instance_valid(obj)`,
and retries on a freed entry. The bug is that it lets freed objects accumulate in
`_available` and only validates AFTER popping: reading a freed Object out of an Array is
itself what the engine logs as a SCRIPT ERROR. So every stale entry costs one error line even
though the code recovers.

Why it matters beyond noise:
1. **It defeats error monitoring.** A flood of benign SCRIPT ERRORs is exactly what hides a
   real one — this gate's stderr check exists to catch real ones, and PC-8 drowns it.
2. **`acquire()` retries by RECURSION** (`return acquire(scene)`, object_pool.gd:133). A long
   run of stale entries recurses once per entry; 74 in one run is uncomfortably close to a
   stack risk under a heavier swarm.

Root cause to fix upstream: pooled enemies are being freed without being removed from the
pool's `_available` list. Options: have the pool hold `instance_id`s and resolve via
`instance_from_id()` (which returns null for a dead id without logging), or purge on release/
free so a freed node never sits in the free list. Either way `_pop_available` should stop
being the place a freed instance is first touched.

Everything the playability gate asks for is now reachable through real input: waves spawn,
10 enemies die to real tongue swings, 100 `player_damaged` events land, dodge i-frames
provably negate a touching enemy, a level-up fires and a mutation (`toxic_aura`) is applied
by CLICKING its card, and death drives `player_died` -> `run_ended('death')` ->
`epilogue_generated` -> a visible RunEndScreen reporting "Enemies killed: 10".

Two blockers were found and cleared to get there — one game bug (PC-5) and two harness/driver
defects (the 64x64 input surface, and the i-frame measurement granularity).

## 2026-07-20 — PC-5 (CRITICAL, FIXED upstream): the tongue attack could not hit anything
## closer than ~119px, so the player could never kill an enemy

R1 requires "kill >= 1 enemy through the real input path". That gate was unreachable:
**melee was non-functional**. Measured, not inferred — a full R1-shaped run (seed 20260719,
chase + mash attack, 90 steps to death):

| observed | value |
|---|---|
| `tongue_attack_started` (input reached the swing) | 24 |
| `tongue_hit` (swing connected) | **0** |
| `enemy_killed` | **0** |
| `player_damaged` | 100 (hp 100 -> 0) |
| enemies within 10px of the player | up to 8, continuously |

The input path is fine. The swing starts. It just never touches anything.

### Root cause: tip-only hit detection + an elastic ease that reaches full range on frame 1

`combat/scripts/tongue_attack.gd::_check_hits()` positions a **12px-radius** `HitArea` at
the tongue TIP (`hit_area.position = player.aim_direction * current_length`) and tests only
that circle. `_check_hits()` is called only from `_update_extending()`, i.e. for the
`extend_duration = 0.15s` window = **9 physics frames**. Frame-by-frame sample of one real
swing (`max_range` 144, enemy sitting at 92.7 -> 82.0px throughout):

```
f0  len=  0.00      f3  len=131.41      f6  len=143.72
f1  len=165.60  <-- f4  len=151.55      f7  len=144.63
f2  len=146.06      f5  len=141.90      f8  len=143.66   hits=0 for all
```

The tip goes 0 -> 165.6 in ONE frame and then only jitters around 144. The swing therefore
samples a thin annulus at roughly **131–166px** and nothing else. With a 12px radius, every
enemy inside **~119px is unhittable** — about 83% of the tongue's own 144px range is a dead
zone, and part of the ring that *does* hit sits OUTSIDE `max_range`.

Because the enemies are melee chasers that close to ~1px and swarm, they spend essentially
the whole fight inside the dead zone. Hence 0 kills, and hence no level-up (LevelUpTrigger
needs 10 `enemy_killed`), no mutation pick, no evidence, no non-default epilogue.

**A hypothesis I checked and REFUTED:** that `_ease_out_elastic` was miswritten. It is not —
it tracks the standard `easeOutElastic` to within ~1% at every sample (0.111 -> 1.365 vs
1.318, and identical from t=0.222 on). Instantly reaching full extension is what an elastic
ease-out *does*. The defect is the **combination** with a tip-only hitbox, not the curve.
Do not "fix" the easing.

**Fix direction (game-side, needs an owner decision):** hit-test the whole tongue — the
segment from the player to the tip — instead of a circle at the tip. That also matches what
the player SEES: `_update_tongue_visual()` draws a line from the player to the tip, so a
tongue visibly passing through an adjacent enemy currently deals no damage.

**FIXED upstream** (owner-approved) in `combat/scripts/tongue_attack.gd`: `_check_hits()` now
sweeps a capsule from the player to the tip — radius read off the HitArea's own
`CircleShape2D` so the scene keeps owning the thickness — instead of testing a circle at the
tip. Effective reach went from a ~131-166px ring to a contiguous 0-144px. Immediately after:
**8 swings -> 8 hits -> 8 kills** (was 24 -> 0 -> 0), and R1 now lands 10 kills in 52 steps.
Game gate re-run: **PASS, 27 failing vs baseline 27** — no regression.

Still open for human UAT: the tongue also never visually animates outward (it snaps to full
length on frame 1 and wobbles), which the hit-detection fix does not address.

### PC-6 (MEDIUM, FIXED upstream): a run's own evidence reward could never appear in that
### run's epilogue

Root cause traced. **Two autoloads subscribe to the same `EventBus.run_ended`, and they run
in connection order:**

- `NarrativeState._on_run_ended()` (`core/scripts/narrative_state.gd:262`) computes the
  epilogue **synchronously** from `_collected_evidence` and emits `epilogue_generated`.
- `EvidenceManager._on_run_ended()` (`metagame/scripts/evidence_manager.gd:253`) calls
  `unlock_next_gated_evidence()` — the T-045 rule that "each completed run reveals the next
  gated card" — which emits `EventBus.evidence_unlocked`.

NarrativeState is connected first, so the epilogue is generated **before** the run's evidence
reward exists. Observed in R1: the epilogue was the NO_EVIDENCE sentinel while
`NarrativeState._collected_evidence` read back `["data_log_01"]` one instant later, and the
RunEndScreen printed "No new evidence recovered this run." for a run that had just earned a
card. The same ordering is why `run_ended`'s own stats carry `evidence_collected: []`.

Net effect for a player: **the card you just earned is never mentioned in the ending you just
got** — it can only ever show up one run late. Every run reads as the "no evidence" ending
until the arc has already moved on.

`replay_run_evidence()` exists and is documented as the rehydration path, but nothing in
production code calls it.

Candidate fixes (owner's call — each has ripple):
- **(A) grant before narrating** — unlock the run's gated evidence before `run_ended` is
  emitted. Safest for the existing T-047 assertions, but couples the end-of-run order.
- **(B) defer the epilogue** — `call_deferred` the `get_run_epilogue()`/emit in
  `_on_run_ended` so all `run_ended` consumers settle first. One line, but T-047 asserts
  `epilogue_generated` synchronously after `end_run()` and would need an `await`.
- **(C) split the signal** — a `run_ending` pre-phase for reward granting, then `run_ended`
  for narration. Cleanest ordering contract, keeps the ADR-003 bus decoupling, biggest diff.

### PC-7 (open, LOW): run duration is wall-clock, not game time

`run_stats["run_start_time"]` uses `Time.get_ticks_msec()`. A 45s (game-time) headless run
reported `time_survived: 2.45` / "Survived: 0:02" because headless runs faster than realtime.
Harmless in normal play (wall clock == game time there) but it makes the stat untestable and
would misreport on any frame-rate stall.

### Harness defect (UGT-side): headless boots a 64x64 input surface, so NO click can ever land

The synthesized card click was pushed at the card's own `get_global_rect()` centre —
(700, 540) — and picked **nothing** (`gui_get_hovered_control() == null`), so the level-up
screen never dismissed and the paused tree stalled every downstream check. Cause:
`--headless` boots the root window at **64x64** while Control layout uses the project's
1920x1080 viewport, so every UI element sits far outside the input surface. Layout coordinates
and input coordinates silently disagree.

Fix: the harness sets `root.size` from
`ProjectSettings display/window/size/viewport_{width,height}`. It must be set **twice** —
once in `_initialize()` and again in `create`, because an autoload applies persisted display
settings on its own `_ready()` (after `_initialize`) and stomped the first resize back to
64x64. The first fix attempt looked like a no-op for exactly that reason.

**Generalises to any Godot GUI-driving integration:** a headless harness that clicks UI must
assert the viewport size, and should read back `gui_get_hovered_control()` to prove the click
picked the control it aimed at rather than trusting `ok: true`. A `choose` that "succeeded"
while hitting nothing is a vacuous green.

### Driver defect (UGT-side): the i-frame check could not observe i-frames

The first R1 reported "0 dodge saves" — which reads like a game bug and is not.
`dodge_iframe_duration` is 0.3s = 18 frames, but a step was 30 frames, so invulnerability
always began AND ended inside a single step and was never true at two consecutive snapshot
boundaries. The check could not have passed no matter how well the game behaved.

Fix: the dodge probe temporarily drops `frames_per_step` to 6 so a step fits inside the
window, and reads the enemy distance from **before** the step (the dodge hurls the player
500px/s away, so the enemy that was touching us is gone by the end). Suspect your own
invariant first — this is the third time on this integration that a red check was the
harness, not the game.

### Adapter change made here (UGT-side, not a game defect)

`attack`/`dodge` macros now **mash** (4 frames on / 6 off across the step) instead of pressing
once. The game consumes both with `is_action_just_pressed()` and buffers nothing, while one
tongue cycle costs 0.55s and a dodge 0.8s — both longer than a 0.5s step — so a single press
per step phase-locks into the cooldown and is dropped. Mashing is also what a real player
does. (This was my first hypothesis for the zero kills; it was necessary but NOT sufficient —
kills stayed at 0 until PC-5 was found. Recorded so the next reader does not re-derive it.)

### Harness extensions added for R1 (game repo, wire-only)

- `{"op":"choose","index":i,"frames":N}` — picks a level-up mutation card by synthesizing a
  real LEFT-CLICK at the card's own laid-out rect centre and pushing it through the viewport's
  GUI routing. `MutationCard` accepts **only** `InputEventMouseButton` on `gui_input` (no
  keyboard/`ui_accept` path), so this is the one real input path; the harness never calls
  `MutationManager.add_mutation()` or emits `EventBus.mutation_selected` directly.
- Snapshot now carries `paused`, `level_up` (pending + the cards on screen), `mutations`
  (what the player's own MutationManager applied), `narrative` (evidence, epilogue, and the
  game's own `EPILOGUE_NO_EVIDENCE` template so a driver can recognise the sentinel without
  hardcoding its prose), `run_end` (the RunEndScreen overlay's own label text **and
  visibility**), and `player.tongue` (swing state + `attack_started`/`tongue_hit` counters).
- Taps added for `NarrativeState.epilogue_generated` / `narrative_branch_changed` and for
  TongueAttack's node-local `attack_started` / `tongue_hit` — none of these reach EventBus,
  so the original tap could not see them. The tongue tap is what made PC-5 diagnosable.

**Careless read to avoid:** `RunEndScreen._true_ending_label` carries "◆ TRUE ENDING ◆" as
static scene text and is merely hidden when no ending unlocked. Reading `.text` alone reports
a true ending on every run — the harness now exposes `true_ending_visible` too. That was my
own bad invariant, not a game bug.

## 2026-07-19 — SMOKE (8/8 MET ×3) + finding PC-4 found & FIXED upstream

**Smoke:** `smoke_pond_adapter.py` 8/8, three consecutive byte-identical runs, plus a spike
re-run 13/13 — all through the new `PondHarnessAdapter` (`ugt/adapters/pond_harness.py`,
transport-only: 14 discrete input macros over held named actions + structural aim targets;
attack/dodge choreograph press→release edges because the game reads them with
`is_action_just_pressed()`). Adapter-level same-seed determinism holds: two scripted 6-step
episodes → identical raw-snapshot fingerprints. Game-side gate (`scripts/gate.sh`) re-run
after the PC-4 fix: PASS (26 failing vs baseline 27 ±4 — one better, no regression).

### PC-4 (FIXED upstream): every run start double-fires — run counter +2, and a duplicate
### arena under the harness

`RunManager.start_run()` had no re-entry guard. Real-game flow: the menu's New Run calls
`start_run()` (state_changed LOBBY→COMBAT → MetaProgression +1), SceneRouter swaps to
TestArena, whose `_ready()` calls `start_run()` AGAIN (+1) — **every played run counted
twice in the persisted `total_runs`, doubling the run-count difficulty ramp (T-040/FR-08)
and the menu's runs-played stat (FR-03)**. The very first feasibility probe's back-to-back
"Run started: #12864 / #12865" was this bug, visible from day one. Under the harness it was
worse: `current_scene` is null under `-s`, so SceneRouter's already-current guard missed and
its deferred swap instantiated a SECOND TestArena on the first stepped frame (duplicate
player + spawner silently inflating enemy pressure in every episode — smoke check 5's
fingerprint dropped from 2 enemies to 1 at frame 181 once fixed). Two fixes:

- **Game** (`core/scripts/run_manager.gd`): re-entry guard in `start_run()` (`if
  _is_run_active: return`); direct-boot F5 still starts normally. Gate PASS.
- **Harness** (`tests/harness/ugt_harness.gd`): register the arena as `current_scene` on
  `tree_entered` — before `_ready()` emits — mirroring the engine's normal scene boot, so
  SceneRouter's guard sees it exactly as in the shipped game.

The smoke now pins the fix: check 2 asserts `total_runs` stays 1 across the first stepped
frame (where run #2 used to appear).

### Transport lesson (UGT-side): never select() on a buffered pipe object

The first smoke re-run flaked: `create` timed out after 120s while the godot log proved the
harness had answered instantly (and answered the later `quit` too). Classic starvation:
`readline()` on the buffered stdout object can slurp several coalesced lines into Python's
internal buffer; the kernel pipe goes empty; `select()` then blocks forever on data that is
already buffered. Timing-dependent — three earlier full runs passed. Fixed in both the
adapter and the spike helper with a dedicated reader thread + queue (EOF as sentinel). If a
harness response "never arrives", check the game's own log (user://logs/godot.log) before
suspecting the game.

## 2026-07-19 — Feasibility probe + SPIKE (13/13 MET)

**Spike:** `spike_pond.py` 13/13 against the new game-side harness
(`the-pond/tests/harness/ugt_harness.gd`, uncommitted in the game repo at time of writing).
Real input injection kills real enemies: the informational attack probe produced a live
`enemy_killed` EventBus event by aiming `aim_target_override` at the nearest active enemy and
cycling `attack` presses. Pause discipline, exact-frame stepping (60 == 60), save hygiene,
dodge i-frames (FR-01), and clean shutdown all hold.

**Determinism probe (informational, 2× now): IDENTICAL end states** across two fresh
processes with the same seed + same scripted input (player pos/hp, enemy list, bullets, wave).
The harness seeds the GLOBAL RNG at `create`, which covers `enemy_spawner`/`enemy_base`/
`boss_ceo` (they use global `randi()/randf()`) — so R3 same-seed replay looks feasible
already; the remaining unseeded island is PC-1.

### Findings (game-side)

- **PC-1 (open, R3-relevant): tongue crit RNG is unseedable.** `tongue_attack.gd` owns a
  private `RandomNumberGenerator` that calls `randomize()` in `_ready()`; every other random
  draw in combat uses the global RNG (seedable — the harness does). Crit rolls will diverge
  same-seed replays once hits land. Fix upstream: seed `_rng` from the global RNG or a
  RunManager-owned seed.
- **PC-2 (open): headless runs write the REAL meta save, and run count is a difficulty
  input.** The 2026-07-19 feasibility probe alone pushed `user://meta_progression.save`
  `total_runs` to #12866 (T-040 scales difficulty by run count, so the shipped curve input is
  test-polluted). `MetaProgression.save_path` is redirectable (the harness and T-047 both do);
  `SaveManager.SAVE_PATH` is a **const** and is NOT — settings saves from headless runs still
  hit the real `user://savegame.json`. Fix upstream: make SaveManager's path redirectable
  and/or add a headless/test guard; consider resetting the polluted run counter.
- **PC-3 (open, benign): BulletUpHell `BuHSpawner._exit_tree` throws 3 "Thread must have been
  started" errors on every headless exit** (BuHSpawner.gd:140–144) plus ObjectDB leak
  warnings. Teardown-only noise in the forked addon; whitelisted in the spike's stderr check.

### Harness lessons (UGT-side, for the next Godot integration)

- At `_initialize()` time absolute `/root/...` NodePaths do NOT resolve (tree not registered);
  autoloads must be looked up as direct children of root. This silently null'd the save
  redirect + EventBus tap on the first spike run (2 FAILs) — the exact "suspect your own
  invariant first" class.
- The enemy "group" is mostly dormant pool: COMBAT-014 pre-warms ~50 invisible pooled
  instances per type into `group("enemies")`. Active set = spawner `_active_enemies` ∪
  visible group members (covers the non-pooled boss).
- Autoload `_ready()` fires on the first main-loop iteration, AFTER the MainLoop script's
  `_initialize()` — that's the window where save-path redirects must land.
- Arena selection derives from the persisted run number, so with a virgin meta state every
  `create` picks the same arena. R2's all-3-arenas gate will need to drive run count (or the
  selection input) explicitly.
