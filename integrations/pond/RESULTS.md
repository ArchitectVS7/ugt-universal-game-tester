# Pond Conspiracy — trial findings log

Commit-traceable record. A failed check is data. Game repo: `~/Dev/Games/the-pond/`.

## 2026-07-20 — U-007 (fix round 2): PC-16 FIXED upstream — the player is now contained in the arena; R2 invariant sweep CLEAN

The U-007 gate re-run exited 1 on three non-passes: the two by-design blocks (PC-15 balance, PC-12
victory wire gap) and the **invariant sweep** — 140 `player escaped vertically` violations (e.g.
`y=-163.0 outside [0.0, 1080.0] (+/-64.0)`) during the wave-5 boss fight, i.e. **PC-16**, the
containment defect the ported sweep surfaced under U-003. PC-16 is a real GAME bug (not a tester
artifact), so it is fixed upstream (dual validation), the sweep now passes because the game works,
and R2 improves **34/37 → 35/37**.

### Root cause (measured, then confirmed in source)

The escape reproduces over the wire: driving the player straight UP with dodge, its `y` reached the
hundreds-negative — it walked clean through the top wall. Source then explained why:

- `project.godot [layer_names]` = `1 Player · 2 Environment · 3 Enemies · 4 PlayerAttack · 5 Bullets`.
- The `Player` `CharacterBody2D` (`combat/scenes/Player.tscn`) had **`collision_mask = 2`**
  (Environment only).
- The `TestArena.tscn` boundary `Walls` (four `StaticBody2D` with real `CollisionShape2D`, inner
  faces at `x=0/1920`, `y=0/1080`) were authored **without an explicit `collision_layer`**, so they
  sit on the **default layer 1 ("Player")** — NOT Environment. `move_and_slide()` collides only when
  the mover's mask ∩ the body's layer ≠ 0; `player_mask(2) & wall_layer(1) == 0`, so **nothing
  collided with the boundary walls** and the player passed straight out. (Enemies, mask `6`, likewise
  never collided with them — they enter from off-screen spawns, see below.)

R1 never caught it because R1 stays interior; R2's boss fight drives the player up toward the
top-positioned boss (`[960, 100]`) while evading, pressing it through the (non-colliding) top edge.

### The fix (surgical, non-regressing): `combat/scenes/Player.tscn` `collision_mask` 2 → 3

Add layer 1 to the player's mask so the player collides with the boundary walls (which live on
layer 1). The player continues to collide with layer-2 Environment (the ChemicalPlant conveyor
hazards) exactly as before; the only NEW physics body it now hits is the layer-1 boundary walls.
Verified safe: the only layer-1 **physics body** in the driven arenas is those walls — the toxic
puddles are `Area2D` (monitoring, never touched by `move_and_slide`), the security camera is a
`Node2D`, conveyor walls are already layer 2. Nothing else on layer 1 exists to spuriously collide.

**Why NOT the "cleaner" re-layer (walls → Environment layer 2).** The game's own
`scripts/validate_collision_setup.gd` matrix documents the intended design as *both* Player and Enemy
colliding with Environment — so the design-correct home for the walls is layer 2. But enemies
(`enemy_spawner.gd:_get_spawn_position`) spawn on a **600px ring around the arena center (960,540)**,
which overshoots the 540px vertical half-height: the top/bottom arcs land at `y∈[-60,1140]`, i.e.
**outside** the walls. Putting the walls on the shared Environment layer makes enemies collide with
them too and **traps ~29% of spawns outside the arena** — a measured R1 regression to **13/18
(4 kills / 10 needed)**. Fixing that properly needs an enemy-spawn-containment change that would
also break `test/unit/test_enemy_spawner.gd::test_enemies_spawn_at_radius` (asserts spawn distance
≈ `spawn_radius` ± 50) and touches FR-08 difficulty — out of this task's scope and R1-destabilizing.
The player-mask fix contains the player (the observed defect) without that blast radius. Two latent
game-side items are filed for a future the-pond collision-model cleanup (see HANDOFF "Still open"):
(a) boundary walls should live on the Environment layer, not the Player layer; (b) enemy spawns
overshoot the arena and would be trapped once walls collide for enemies; and, separately, (c) the
`BossArena` inner `ArenaWalls` have **no `CollisionShape2D` at all** (only `ColorRect`s) so the
"locked" boss box never physically confines — it does not cause an invariant violation (the outer
walls now hold), but the inner-arena lock is cosmetic. `boss_arena.gd:70-72`'s
`set_deferred("disabled", …)` on the shapeless `StaticBody2D` walls is a no-op regardless.

### Verification (measured, seed 20260720, godot 4.7.1)

- Containment repro: driving into every wall now clamps the player to `y∈[14,1066]`, `x∈[14,1906]`
  (the 28px body against walls at 0/1080/0/1920) — no escape.
- **R1 MET 18/18** — no regression; `run summary: 101 steps, 10 kills` (enemies unaffected).
- **R2 NOT MET 35/37** — the invariant sweep now **PASS: 0 violations over 1578 steps** (was 140);
  stderr scan clean (0 SCRIPT ERRORs). The 2 remaining non-passes are the unchanged by-design blocks
  **PC-15** (balance — driver did not beat the boss; re-baseline is U-009's) and **PC-12** (victory
  result unobservable over the current wire — filed harness follow-up). These correctly FAIL the gate
  per the standing constraint ("a gate that skips what the game cannot do reports a green that means
  nothing"); they are NOT U-007's to resolve and were not weakened to force a green.
- **the-pond `scripts/gate.sh`: PASS** — GUT suite `Failing Tests = 0` (baseline 2, tolerance ±4);
  the `Player.tscn` mask change broke no game test. (BuHSpawner teardown thread errors are the known
  benign PC-3 noise.)

PC-16 status: **RESOLVED upstream** (the-pond `combat/scenes/Player.tscn`).

## 2026-07-20 — U-007: the evidence → conspiracy-board card flip is now DRIVEN & MEASURED over the wire

`verify_round2.py`'s docstring advertised the "evidence → conspiracy-board → epilogue chain", but
`section_evidence_chain` never touched the board and downgraded evidence to a `gate.info` ("the
conspiracy-board card flip is not driven by this section") — the board card flip HANDOFF.md lists as
an R2 requirement was **silently absent, not measured**. The only real blocker was a **harness gap**:
the JSON-lines harness loaded `TestArena.tscn` alone and exposed no board/conspiracy state, so the
`EventBus.evidence_unlocked` the game already emits on every run end had no board listening and no
read-back. This closes that gap and drives a real flip.

**Reachability (why this is DRIVEN, not BLOCKED):** the flip is reachable through the ordinary
death-run path — no boss kill required. On every run end, `RunManager` emits `run_rewards_due`
before `run_ended` (the same ordering PC-6 asserts); `EvidenceManager._on_run_rewards_due →
unlock_next_gated_evidence()` unlocks the first unresolved log (`data_log_01` on a virgin meta save,
via `EvidenceGraph.next_unresolved`) and emits `EventBus.evidence_unlocked(id)`; a live
`ConspiracyBoard._on_evidence_unlocked` calls `DataLogCard.set_discovered(true)` — the flip.

**Harness extension (game repo, wire-only — in the style of the `boss_id` accessor):**
- `ugt_harness.gd` gained an opt-in `with_board` create flag → `_spawn_board()` instances the real
  `res://conspiracy_board/scenes/ConspiracyBoard.tscn` headless (the same `instantiate()` path the
  T-047 E2E test `test/integration/test_end_to_end_loop.gd` drives, so it is known to boot clean),
  hidden so it is never the input target (`_board_is_active()` no-ops while invisible — no focus
  grab, no click theft of the combat/level-up input). Its `_ready()` still spawns the 16 cards and
  subscribes to `EventBus.evidence_unlocked` **before** the first run-end unlock fires.
- New `_board_state()` (added to `_snapshot()` as `board`, null when not requested — same shape rule
  as `_boss_state`) reads structurally only: each live `DataLogCard`'s `get_data_id()`/
  `is_discovered()`, the board's `discovered_count`, and MetaProgression's persistent ending gate
  (`get_connections`/`has_connection(DATA_LOG_04, DATA_LOG_07)`/`get_unlock_status`) plus
  `CORPORATE_ENDING_ID` (T-060) — so the ending citation uses the current constant, never
  `TRUE_ENDING_ID`. No board logic is reimplemented; the flip is produced by the game's own bus.
- `PondHarnessAdapter.reset(..., with_board=False)` threads the flag into the create request
  (transport only).

**The measured checks (verify_round2.py §4, +4 over baseline, all PASS at seed 20260720):**
1. the live `ConspiracyBoard` instanced over the wire — `present=True cards=16 discovered_count=0`
   (baseline READ, not assumed);
2. **every board card flip is caused by an observed evidence unlock** — the driver now captures the
   `evidence_unlocked` events from EVERY sub-step (the level-up choose frames + the attack press + the
   release window), not just the last step, so each flip is attributed to an event actually seen over
   the wire rather than inferred from source. Two cards flipped `discovered false→true` this run and
   both are explained by an observed unlock: `data_log_01` via the run-reward path (`run_rewards_due →
   unlock_next_gated_evidence`, in the step stream) and `data_log_06` by the `paper_trail` mutation's
   own effect, captured in that card's choose frames (`id→source={data_log_06:'mutation:paper_trail',
   data_log_01:'run_reward'}`). The check asserts `cards_flipped ⊆ observed_unlocks` — a flip with no
   observed cause would itself be the finding;
3. `discovered_count` delta equals the cards that actually flipped and advanced ≥1 (`0→2`, both
   `data_log_01` + `data_log_06` as attributed above);
4. flip and MetaProgression's persistent set advance in lockstep (`logs_collected 0→2`), gated by
   `ending_id='corporate_conspiracy'`.
An INFO records (context, not a downgrade) that the FULL `CORPORATE_ENDING_ID` unlock still needs all
16 logs + Lobbyist + CEO + the `data_log_04↔data_log_07` smoking-gun connection — a single death run
does not complete it (the same PC-12 wire gap, unchanged).

**R2 re-measured NOT MET 34/37** (was 30/33): the denominator widened by exactly the 4 board checks,
all passing. The 3 remaining non-passes are unchanged and pre-existing: **PC-15** (boss not beaten
this run, balance), **PC-12** (victory result unobservable over the current wire), and the invariant
sweep FAIL = **PC-16** (boss arena has no collision walls — 140 `player escaped vertically`
violations, all in the boss fight; verified identical on committed code at 30/33, i.e. **not** caused
by this change). Module + `section_evidence_chain` docstrings updated to describe the driven
evidence → board-flip → epilogue chain. gdlint clean; the file's hand-maintained style is preserved
(the-pond does not enforce `gdformat` — `gate.sh` runs neither gdformat nor gdlint, and the committed
harness itself does not pass `gdformat --check`).

## 2026-07-20 — U-003: R1's two safety nets ported into R2 — invariant sweep surfaced a NEW escape (PC-16)

R2 drove tens of thousands of frames with neither safety net R1 has: no per-step
`invariants.build_suite()` sweep and no `SCRIPT ERROR` stderr scan (PC-8 was originally caught by
exactly that scan). Both are now ported into `verify_round2.py`, following R1's structure so the
two rungs cannot drift:

- **Invariant sweep** — `invariants.build_suite()` is built once at module load and run inside the
  central `step()` helper (the primitive every driven frame in R2 funnels through — the faithful
  analogue of R1 sweeping after every `ep.step()`), reusing the exact predicate set R1/R3 share.
  `main()` asserts zero violations across the whole spine, R1 parity with `verify_round1.py:390`.
- **Stderr scan** — extracted as a pure predicate `scan_stderr(lines, whitelist)` that mirrors
  `verify_round1.py:404-406` line-for-line, run in `main()`'s **`finally`** so it executes even when
  a section raises. The whitelist is **imported** (`from verify_round1 import STDERR_WHITELIST`),
  never re-authored, so the rungs share one source. Every adapter constructed this run is registered
  (`_new_adapter()`), so the single scan reads every subprocess's real stderr.
- **Committed negative test** `integrations/pond/stderr_scan_selftest.py` (5 cases) feeds synthetic
  stderr blobs through the same `scan_stderr` predicate R2 uses: the acceptance-mandated case — a
  real `SCRIPT ERROR: Invalid call…` line MUST be flagged — plus a `Parse Error`, a whitelisted
  teardown line that must NOT be flagged (proving the imported whitelist suppresses forked-addon
  noise), clean/warning lines, and a mixed blob isolating the one real error. Passes 5/5, no game.

**R2 re-measured NOT MET 30/33** (seed 20260720, godot 4.7.1); prior baseline was **29/31**. The
denominator widened by exactly the two ported checks: **stderr scan PASSED** (0 error lines) and
**invariant sweep FAILED**. `main()` now wraps the sections in try/except/finally (R1 parity), so a
mid-section raise records a failed `exception-free run` check rather than aborting the tally.

### PC-16 (new, REAL — surfaced by the ported invariant sweep): the boss arena does not contain the player

The sweep reported **201 `player escaped vertically` violations over 2329 driven steps**, all during
the wave-5 boss fight (aim = the boss at `[960, 100]`): the player repeatedly reached **y = -71 to
-127**, e.g. `step 223: y=-121.4 outside [0.0, 1080.0] (+/-64.0)`. This is a real containment
failure, not a tester artifact — the player is outside **both** the outer TestArena top wall
(world y=0) **and** the boss arena's own top wall (world y=-50):

- `BossArena.tscn` is placed at world `(960, 250)` in `TestArena.tscn`; its `ArenaWalls` children
  (`TopWall` local y=-300 → world y=-50, plus Bottom/Left/Right) are `StaticBody2D` nodes whose only
  child is a `ColorRect` — **none has a `CollisionShape2D`**, so the walls are purely decorative and
  cannot stop the player.
- `boss_arena.gd:70-72`'s lock step iterates `arena_walls.get_children()` and calls
  `set_deferred("disabled", false)` on each `StaticBody2D` — but `StaticBody2D` has no `disabled`
  property and there is no collision shape to enable regardless, so "locking" the arena adds no
  collision either. (The scene facts above are source-read context; the **observed** wire evidence is
  the 201 out-of-bounds player positions during the boss fight.)

Consequence: the "locked" boss arena visually frames the fight but does not physically bound it — a
player kiting the top-positioned boss drifts off the top of the play area. Filed for upstream fix in
the game (give the boss walls real `CollisionShape2D` geometry, or clamp the player to the boss
arena rect on lock). This is precisely the previously-invisible defect the ported sweep exists to
catch: the pre-port R2 had no invariant sweep and never noticed the player leaving the arena.

## 2026-07-20 — U-002: PC-6 ordering check made real (was vacuous); two overclaiming labels narrowed

`verify_round2.py:section_evidence_chain` asserted the PC-6 ordering contract (rewards settle
before the epilogue is narrated) with a check that could never fail on ordering: it tested a bare
boolean (`saw["run_rewards_due"]` fired *at some point*) while its detail string claimed
"observed ahead of run_ended" — an ordering never measured. **Reintroducing PC-6 would still have
passed it.** Rewritten to measure positional order from the already-collected ordered `events`
stream:

- New pure predicate `rewards_settle_before_end(events)` records the FIRST-seen index of
  `run_rewards_due` and `run_ended` in the ordered stream and asserts the former strictly
  precedes the latter. Pure (no game state), so it is driven by a **committed** negative test,
  `integrations/pond/pc6_ordering_selftest.py` (4 cases incl. the acceptance-mandated one: an
  out-of-order `[run_ended, run_rewards_due]` stream must FAIL; also missing-`run_rewards_due`
  must FAIL, i.e. never vacuously green). Self-test passes 4/4.
- The section now accumulates `event_stream` across all step batches and feeds it to the
  predicate. Live wire re-run (seed 20260720, godot 4.7.1) prints real evidence:
  **`run_rewards_due at event #66 precedes run_ended at #68`** — positional indices, not two
  booleans. Contract still live and verified this session: `core/scripts/run_manager.gd:116`
  emits `run_rewards_due` before `:119` `run_ended`; `metagame/scripts/evidence_manager.gd:227`
  and `metagame/scripts/meta_progression.gd:160` both `.connect()` to `run_rewards_due` (NOT
  `run_ended`) for exactly this ordering (their own comments cite the contract).
- Two overclaiming labels narrowed to match observed evidence only: the death check's label
  changed from "the only reachable run result is 'death'" (doubly wrong — victory is reachable
  per T-057, and one run cannot prove "only") to **"this run ended in death"**; and
  `section_boss`'s boss-damage check dropped its `lowest < (b.get("max_hp") or 100)` fallback —
  an empty boss snapshot now **fails loudly** ("cannot measure damage against a real value")
  instead of silently comparing against the literal 100. Live re-run read the real value:
  **"hp fell to 17 of 80"** (foreman max_hp 80, not 100).

**Denominator unchanged: still 29/31, 2 blocked** (PC-12 harness gap, PC-15 balance). No checks
were added or removed — one vacuous PC-6 check was replaced by one real one, and the boss-damage
check remains a single check per run; the difference is that both now carry real over-the-wire
evidence rather than a claim the code did not measure.

## 2026-07-20 — U-001: PC-11 CLOSED, PC-13 reclassified, PC-12 re-scoped (R2 `section_unreachable` now measures over the wire)

`verify_round2.py:section_unreachable` previously took no adapter and executed no game code —
three unconditional `gate.blocked()` calls carrying prose (PC-11/PC-12/PC-13). All three
underlying defects are now fixed game-side, so the section was rewritten to drive real game
code over the wire. Re-run (seed 20260720, `UGT_GODOT_BIN=/opt/homebrew/bin/godot`):
**R2 NOT MET 29/31, 2 blocked (PC-12 harness gap, PC-15 balance).**

- **PC-11 (CRITICAL) — CLOSED. Fixed game-side by T-054, verified over the wire.**
  `LevelGenerator.BOSS_SCENES` now maps a distinct boss per run band and
  `TestArenaController._assign_boss_for_run` assigns it onto `BossArena.boss_scene`. The gate
  drives `run_number` 1/5/10, walks each into the BossArena trigger, and reads `boss_id` from
  the live harness `_boss_state()`: **run 1 → `foreman` (80 hp), run 5 → `lobbyist` (100 hp),
  run 10 → `ceo` (150 hp) — three distinct ids.** Guarded so a boss that never triggers fails
  as *boss-not-reached* (a distinct message) rather than masquerading as a same-id mismatch. The
  old finding ("BossArena.boss_scene set in exactly one place → CEO ending unreachable") is
  RESOLVED.
- **PC-13 — reclassified (fixed by T-058/T-059).** Pause is now a real, non-destructive mode:
  the `pause` action toggles `get_tree().paused` and emits `EventBus.pause_toggled` instead of
  `get_tree().quit()`, and `input_manager.gd` was deleted by the-pond T-059. `section_unreachable` records this as
  INFO; the actual wire assertion (re-enable the pause action in the harness, assert tree paused
  / `pause_toggled` emitted / run not destroyed) is **U-008's** job. No more "there is no pause"
  prose.
- **PC-12 — re-scoped from "no production caller" (REFUTED) to a named harness gap.** The caller
  now exists — `run_manager.gd:235` calls `end_run("victory")` inside `_on_ending_unlocked`
  (connected `:65`, T-057). But a `"victory"` run RESULT cannot be OBSERVED over the current
  wire: reaching `EventBus.ending_unlocked` needs all 16 logs + Lobbyist + CEO defeats + the
  smoking-gun board connection (`meta_progression.gd check_ending_unlock`), and the JSON-lines
  harness exposes only `create/step/choose/state/quit` — no board-connection / evidence-grant
  op. Kept as a reasoned `gate.blocked` naming that gap; follow-up harness extension filed under
  HANDOFF.md "Still open". Do NOT re-assert "no production caller".

Denominator disclosure: old **21/26** (5 failed: PC-11, PC-12, PC-13, PC-14, PC-15) → new
**29/31** (2 blocked: PC-12, PC-15). The denominator widens because PC-11 became 7 real checks
(3 boss-reached + 3 boss-id + 1 distinctness summary) and PC-12 stays 1, while PC-13 left the
tally entirely (INFO increments no counter): `section_unreachable` went 3 counted blocks → 8
counted (7 pass + 1 block), net +5 to the total. PC-14 happened to PASS this run (no adds in the
locked arena at the sampled frame — it is the conditional check in `section_boss`, not a
`section_unreachable` change). R2 remains honestly **NOT MET** on PC-12 (wire gap) and PC-15
(balance).

**Follow-up (2026-07-20, U-005):** the PC-14 arm is no longer the single-frame `if adds / else
gate.check(True)` conditional described above — it is now a real persisted-window measurement
(`gate.check(not worst_adds, ...)` over `PC14_SAMPLES` idle samples, 0 non-boss adds required at
every sample; see the PC-14 section below). This is a **category change only** — the arm is still
exactly 1 check, so the denominator is count-neutral (no widen/narrow). The 29/31 numbers above are
a dated run record and are unchanged; U-009 re-baselines the full R2 score.

## 2026-07-20 — R1 MET 18/18 · PC-5 (CRITICAL) + PC-6 found and FIXED upstream

`verify_round1.py`, seed 20260719, one full run loop through `PondHarnessAdapter`:
**18/18 checks, 0 invariant violations over 85 steps, 0 SCRIPT ERRORs**, reproduced twice.
Game gate after both fixes: **1032 passing / 25 failing vs baseline 27 — two BETTER than
baseline, zero regressions.** Ladder re-run end to end: spike 13/13, smoke 8/8, R1 18/18.

Two real game defects were found by this gate and fixed upstream (PC-5 critical, PC-6
medium), plus three harness/driver defects of my own. R1 reached MET only after all five.

**Seed-independent as of the PC-8 fix:** 18/18 on seeds 20260719, 777001, 424242 and 90210.
(Before PC-8, seed 777001 gave 17/18 — the run played fine but the stderr check tripped on 74
SCRIPT ERROR lines. The gate was deliberately not re-pinned to a friendlier seed.)

### PC-8 (MEDIUM, FIXED upstream — was failing R1 on seed 777001): the boss arena freed the
### entire dormant enemy pool, then every later spawn popped a freed instance

74 SCRIPT ERROR lines in one run, first at step 57, all with the same backtrace:

```
SCRIPT ERROR: Trying to return a previously freed instance.
  at: ObjectPool._pop_available (res://shared/scripts/object_pool.gd:310)
  [1] acquire            (object_pool.gd:129)
  [2] _create_enemy      (enemy_spawner.gd:340)
  [3] _try_spawn_enemy   (enemy_spawner.gd:277)
  [4] _physics_process   (enemy_spawner.gd:185)
```

Not caused by the PC-5 tongue change (different subsystem; the trace never enters combat code).

**Root cause.** `BossArena._clear_regular_enemies()` frees every non-boss node in
`group("enemies")` — but that group is NOT the set of live combatants. COMBAT-014 pre-warms
~50 DORMANT pooled instances per enemy type into the same group. Triggering the boss therefore
`queue_free()`d the **entire pool in one frame** (measured: 122 objects at frame 1686), while
`ObjectPool._available` still held every one of them. Each later spawn popped a corpse.

Two things made this hard to see, and both cost me a wrong fix:
1. The boss is triggered by **proximity**, not only by reaching wave 5 — the player wandered
   into the BossArena trigger at **wave 2**. I first checked the wave, saw 2 vs boss_wave 5,
   and wrongly concluded the boss path was not involved.
2. My first fix skipped enemies with `is_active == false` — which skipped nothing, because
   `EnemyBase.is_active` defaults to **true** and `prewarm()` never ran the release-side hook,
   so a pre-warmed enemy that had never been in play still looked live. The error count barely
   moved (74 → 72), which is what exposed the bad assumption.

Only instrumenting found it: a `tree_exiting` hook printing the physics frame showed all 122
leaving the tree in a single frame. (The stack was useless — `queue_free` is deferred, so the
caller is long gone by then.) Same lesson as PC-5: instrument the boundary, don't reason about it.

**Fixes (both upstream):**
- `ObjectPool.prewarm()` now runs the same `on_release` hook a returned object gets, so a
  pre-warmed instance is dormant in the *game's* eyes (`is_active == false`), not merely
  hidden at engine level. This is the real defect: prewarm and release produced different
  states for objects that are supposed to be interchangeable.
- `BossArena._clear_regular_enemies()` skips dormant instances and RELEASES live pooled ones
  via the new `EnemySpawner.despawn_enemy()` (removes from play without firing
  `died`/`enemy_killed`, which would have inflated the kill count and fed the level-up
  trigger) instead of freeing them.

Result: 0 error lines, and R1 is 18/18 on all four seeds tried.

**Still worth doing (not done here):** the pool remains fragile to an external free — a freed
entry in `_available` costs one engine error per pop, and `acquire()` retries by RECURSION
(`return acquire(scene)`, object_pool.gd:133). Holding `instance_id`s and resolving via
`instance_from_id()` would make it structurally immune. Filed as a hardening follow-up, not a
live bug now that nothing frees the pool.

**Separately open:** `test_object_pool.gd` has 3 failures that PRE-DATE all of this work
("Should track reuse count", "Reset callback should be called", "Deactivate callback should be
called") — verified identical before and after the PC-8 change. They are part of the repo's
~25-test failing baseline and deserve their own look.

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

---

## Open-items round — 2026-07-20 (the-pond `a1fb390`)

Cleared everything the R1 round left open, before starting R2. No new UGT-side code: this
round was entirely upstream game fixes plus their regression tests, re-validated by re-running
the ladder against the live game.

**Ladder re-run after the fixes: spike 13/13 · smoke 8/8 · R1 18/18 — unchanged, all green.**
**Game gate: PASS, ratcheted 27 → 21 failing** (was 25 before this round; 2 of the 3 open
test failures fixed, plus the third which turned out to be a real product bug).

### PC-1 CLOSED — tongue crit RNG now derives from the global seed

`tongue_attack.gd` called `_rng.randomize()` in `_ready()`. It now does `_rng.seed = randi()`,
drawing from the global stream the harness seeds at `create`. Shipping behaviour is unchanged
(Godot randomizes the global RNG at startup); replay behaviour is now defined.

Two tests added upstream (`test_tongue_attack.gd`): same global seed → same crit seed, and
different global seed → different crit seed. The second is the anti-vacuity guard — a hardcoded
constant seed would pass the first test while making every run's crits identical. **The
reproducibility test was confirmed to FAIL against the old `randomize()` code** before being
accepted, per the "kill vacuous greens" rule.

*(First attempt at that confirmation was itself vacuous: BSD `sed` treats `\t` in a pattern as
a literal `t`, so the revert silently no-op'd and the test "passed" against code I thought I
had reverted. The printed grep of the supposedly-reverted line is what caught it. Verify the
patch applied, not just that the command exited 0 — the same lesson that bit the baseline
instrumentation below.)*

**R3 same-seed replay is now unblocked.**

### PC-2 CLOSED — headless runs no longer touch the real save files

Worse than filed. The finding was "headless runs write the real meta save"; the truth was that
a full suite run also **deleted** `user://meta_progression.save` (test_main_menu `_delete_save`
on every test) and **overwrote** `user://savegame.json` (three save suites cleaning hardcoded
paths). A developer running `gate.sh` was destroying their own player progression, and
`runs.total_runs` is a difficulty input (T-040) and arena selector (T-042).

Fix upstream: new `core/scripts/save_paths.gd` redirects any *default* `user://` path to a
`headless_` sibling under the headless display driver. `SaveManager`'s three paths became
instance vars (consts kept as the documented shipping locations); it and `MetaProgression`
redirect only a path still at its default, **so the UGT harness's explicit pre-`_ready()`
`MetaProgression.save_path` override still wins** — verified by the spike's save-hygiene check
still reporting `user://ugt_harness_meta.save`.

Note `OS.has_feature("headless")` is NOT the right probe — it reports *false* under
`--headless` (it means a headless export template). `DisplayServer.get_name() == "headless"` is
the signal that tracks the flag; verified empirically on Godot 4.7.1.

**Verified, not assumed:** both real save files are byte-identical by md5 before and after a
full 988-test suite run, and again after `gate.sh`.

### ObjectPool hardening CLOSED

`_available`/`_active` now store instance IDs instead of references, so an entry freed behind
the pool's back resolves to null via `instance_from_id()` rather than going dangling — the
exact PC-8 failure mode (BossArena freed the whole dormant pool; every later pop cost an engine
SCRIPT ERROR, 74 in one run). Discarding dead entries is now a loop rather than recursion;
`acquire()` used to add one stack frame per dead entry, so a 500-deep pool meant a 500-deep
stack at the moment the game was already in trouble. Two tests reproduce the external-free
scenario directly.

### The 3 `test_object_pool.gd` failures — all three were real, none were "just old"

Filed as "pre-existing, not mine". Two were broken tests; the third was a product bug.

- **"Reset callback" / "Deactivate callback" could never pass.** A GDScript lambda captures
  locals **by value**, so `var called := false; object_pool.on_release = func(o): called = true`
  mutates the lambda's private copy and the assertion reads the untouched original. The tests
  now record into an Array (captured by reference). The HANDOFF called these "suspicious given
  prewarm now runs on_release" — that hunch was wrong; the pool was innocent both before and
  after PC-8.
- **"Should track reuse count" was a genuine product bug in `ObjectPool`.** `reuse_count`
  incremented on *every* pool hit, so `prewarm(N)` followed by N acquires reported N reuses
  against N creations — while every object had been used exactly once. The statistic exists to
  show pooling is working (COMBAT-014); reporting reuse for an object on its first life makes
  it useless for that. A reuse now means an object acquired again *after a release*, tracked by
  a `_returned` id set. **The test was right and the code was wrong** — worth stating, because
  the tempting move was to relax the assertion to 2.

### A fourth broken test found while verifying (not on the open list)

`test_main_menu.test_new_run_persists_and_increments_menu_run_count` called
`RunManager.start_run()` twice back-to-back and asserted the counter rose by one. `start_run()`
has a deliberate re-entry guard (the combat scene's `_ready()` calls it again after
SceneRouter's swap), so the second call emits nothing at all. It only ever passed on
accumulated cross-file state in full-suite order — **run alone it failed at HEAD too**. It now
ends the run before starting the next, as a player must, and passes both alone and in suite.

This surfaced as an apparent regression from the PC-2 work. Chasing it produced the round's
sharpest process lesson (below).

### Still open

- **The tongue/spawner/particles/shake failure cluster (21 tests).** Untouched by this round
  and present at every commit checked. The interesting ones are combat-critical and adjacent to
  PC-5: `test_hit_detection_at_3_tile_range` ("should hit enemy at exactly 3-tile range (144px)"
  — fails), `test_tongue_settles_at_max_range` (settles at **11–28px**, expects 144),
  `test_overshoot_extends_effective_range`. PC-5 fixed *close* range; these say **max** range
  may still be broken, which would line up with the human-UAT note that the tongue never
  visually animates outward. Worth a PC-9 investigation before R2 leans on tongue reach.
  Part of the cluster is also **flaky** — `test_attack_emits_signal_on_hit` fails
  intermittently at HEAD (3 vs 4 failures across two identical isolated runs).
- **Human UAT** — tongue extend animation, colorblind modes (ND U-110 precedent).
- **PC-3** — benign BulletUpHell teardown noise, whitelisted.

### Process lessons from this round

- **Diff failing test NAMES against a baseline, never counts — and normalize the values.**
  Two tests fixed and one exposed nets out to "24 → 24", which reads as "no effect". Only a
  name-and-message diff showed 2 fixed, 1 new. Several messages differ only in a float or a
  Vector2 that jitters run to run, so they must be normalized before comparing or they all look
  like regressions.
- **Verify your instrumentation applied.** The first baseline comparison ran a `str.replace`
  against a worktree whose source text had since changed. The patch silently didn't apply, the
  debug print never fired, and the absence of output looked like real evidence about the game.
  Two wrong conclusions came out of it before an `assert` on the patch target caught it. Same
  class as the BSD `sed` failure above — a no-op edit and a successful edit look identical
  unless you check.
- **Compare against the right baseline.** The first comparison used the commit *before* the
  PC-5/PC-6 work rather than HEAD, which attributed pre-existing failures to this round.
- **"Pre-existing" is a hypothesis, not a verdict.** All three "pre-existing" pool failures
  were real and fixable, and one was a product bug hiding behind two broken tests. The label
  was doing the work of an investigation.

---

## PC-9 investigation — 2026-07-20 (four explore agents + independent verification)

**PC-9 as I filed it is REFUTED. Max-range tongue hit detection is not broken.** Recording the
correction prominently, per the D-C1/D-C2 precedent: a wrong finding left standing in a findings
log is worse than no finding.

### What I got wrong, and why

I filed PC-9 off two symptoms: `test_hit_detection_at_3_tile_range` failing, and
`test_tongue_settles_at_max_range` measuring 11–28px where 144 was expected. I read "the tongue
never reaches its stated range" and connected it to the UAT note about the tongue not animating.

The 11–28px is the **retract tail**. Simulating the production easing (`FRAME_DELTA = 0.016`,
`extend_duration = 0.15`, `retract_snap = 2.5`) reproduces my measurements to two decimals:

| frame | phase | length |
|---|---|---|
| 1 | EXTEND | **165.60** (clamped to max×1.15) |
| 2–9 | EXTEND | 153.13 · 127.54 · 151.60 · 143.29 · 142.69 · 144.93 · 143.75 · 143.93 |
| 10 | EXTEND | **144.00** — hard-set, then → RETRACTING |
| 11–14 | RETRACT | 93.12 · 54.91 · **28.08** · **11.20** |

`test_tongue_settles_at_max_range` does `_simulate_attack(1)` + `_process_frames(12)` = 13
frames, landing on 28.08; my two observed readings were **28.07 and 11.19** — frames 13 and 14.
The ±1 frame is the engine driving `_physics_process` on the in-tree player *in addition to* the
test's manual calls. Likewise `test_overshoot_is_configurable` expects the 172.8 peak but
`_simulate_attack(1)` consumes extend frame 1 before the sampling loop opens, so it samples
frame 2 = 153.13 — matching my observed 152–153.

The tongue reaches and exceeds 144px on **every** extend frame. Hit detection uses
`current_length` in both the tip area and the PC-5 shaft sweep, and `current_length` is 127–166px
throughout EXTENDING. Max-range hits are the case that works *most* reliably.

**Lesson:** I treated a test's measurement as a measurement of the game. It was a measurement of
the game *at a frame the test chose badly*. Before believing a number that contradicts the spec,
reproduce it from the production math — that took one short script and would have prevented the
bad finding.

### Why the "0 hits" tests fail — harness, with a known-good reference in the repo

`test/unit/test_tongue_damage.gd:13-19` already documents the cause in its own header: the GUT
cmdln runner does not advance the PhysicsServer on manual `_physics_process()` calls. So:

- The PC-5 shaft sweep is correctly gated behind `Engine.is_in_physics_frame()`
  (`tongue_attack.gd:391`) — a space-state query outside a physics step is illegal — and returns
  `[]` every time in these tests.
- The tip `Area2D` path calls `get_overlapping_bodies()` right after moving the area
  (`tongue_attack.gd:345,352`); overlap lists are refreshed by the server during a step, so with
  no step the list is stale.

Several of these tests *also* carry the by-value lambda-capture bug (the same defect fixed in
`test_object_pool.gd` this round), so they were doubly unpassable. `test_tongue_damage.gd`
passes because it does the three things the others don't: awaits real `physics_frame`s, calls
`player.set_physics_process(false)` to stop the double-drive, and records into an object rather
than a captured bool.

### PC-10 (new, REAL — but a design decision)

The tongue reaches **165.6px on frame 1** (16ms) and then wobbles down to settle. It never
travels outward. That is precisely the human-UAT observation, now with a mechanism.

Caveat that keeps this out of "just fix it": the implementation **matches the GUIDE's own
pseudocode** (`lerp(0, effective_range, ease_out_elastic(progress))`,
`GUIDE/02-combat-system/tongue-attack.md:59-61`), and "ease-out" genuinely means fast-start. But
it contradicts the same GUIDE's prose ("extends over `extend_duration` 0.15s") and the art
checklist's "4–6 frames, tongue extends". This is the tongue feel decision already parked at
the-pond `TASKS.md:342` — it wants a playtest, not a unilateral easing swap by the test harness
author.

### Design-intent conflicts found (for the record, not for UGT to resolve)

- **Range: 144px (GUIDE ×5 docs) vs 120px (PRD FR-01, `docs/prd.md:134`).**
- **Cooldown: 0.3s (GUIDE) vs 0.4s (PRD FR-01).**
- **Shape: elastic point-whip along one ray (GUIDE) vs a 180° arc (PRD FR-01).** If the arc were
  authoritative, hit detection should be a cone — worth knowing against the PC-5 sweep.
- The GUIDE's claim "The PRD specifies 3-tile range" is **not supported** by the current
  `docs/prd.md` (which says 120px); the 3-tile figure traces to PRD-v0.2.
- The GUIDE calls overshoot "purely visual, not gameplay-affecting" while sizing the hitbox to
  `current_length`, which includes the overshoot. Unresolved in the docs.

All three numeric conflicts are already logged as deferred at the-pond `TASKS.md:342`.

### The rest of the 21-test cluster — four distinct causes, not one

Verified directly in the source, not just reported:

- **Enemy spawner (3 tests) — TEST bug.** `test_enemy_spawner.gd:39` adds the spawner to the
  tree *before* assigning `base_spawn_interval` at `:43-47`, but `_ready()` snapshots
  `current_spawn_interval = base_spawn_interval` (`enemy_spawner.gd:148`) and never re-derives
  it. Tests advance 0.6–1.6s against a captured 2.0s interval → 0 spawns.
  `test_player_target_found` is a downstream symptom of the same thing, not a separate defect
  (the group lookup itself works fine under GUT).
- **Particle manager (1 test) — TEST bug.** Cleanup keys off `CPUParticles2D.emitting`, which
  the *engine* flips after `lifetime`. 120 synthetic `_process()` calls inside one real frame
  advance zero engine time.
- **Screen shake (2 tests) — GENUINE PRODUCT BUG, verified.** `_shake_duration` is written at
  `screen_shake.gd:154` and `:188` and **never read anywhere**; trauma decays at a fixed
  `trauma_decay_rate = 1.5`/s, so a requested duration is ignored entirely and full decay always
  takes 0.67s. The tests encode the intended contract; the code doesn't implement it.
- **Hit stop (2 tests) — one GENUINE PRODUCT BUG, verified, plus one contract disagreement.**
  `hit_stop.gd:87-88` discards the passed delta when `Engine.time_scale == 0` and hardcodes
  `0.016`, so a large frame delta cannot unfreeze — a real robustness bug on frame skips.
  Separately, `trigger_hit_stop(-1.0)` is the API's "use default" sentinel while the test expects
  rejection; code is self-consistent, so this is a spec question.

No shared root cause with the tongue cluster; no shared helper, base class or autoload links
them. One global worth watching: `Engine.time_scale` leaking at 0.0 if a hit-stop test aborts
before `after_each` would stall `await`-based tests suite-wide.

### UGT-side notes for R2 (from the implementation read)

- The harness snapshots at the **top** of a physics frame and it is an autoload, so it runs
  before the arena's nodes: `{"op":"step","frames":N}` reports tongue state after **N−1** tongue
  updates. Worth accounting for in any R2 assertion that reads `current_length`.
- `_set_action` presses only on transitions, so holding `attack:true` across steps fires exactly
  **one** swing. R2 must toggle attack off/on to swing repeatedly.
- `HitStop` drives `Engine.time_scale` to 0.0 on hit, which stretches a swing across more
  physics frames — any fixed-frame-count sampling of tongue state will land differently once
  hits start landing.

---

## Cluster remediation — 2026-07-20 (the-pond `d83d932`)

**The game's suite is now fully green: 1063/1063, gate PASS.** Baseline this session was
25 failing; it went 25 → 21 → 2 → 0. Ladder re-run against the live game after every stage:
spike 13/13 · smoke 8/8 · R1 18/18, unchanged throughout. Real save files byte-identical by
md5 across every gate run (PC-2 holding).

The headline: **"21 pre-existing failures" was not one problem.** It was ~11 structurally
unpassable tests *hiding six genuine product bugs*. Every one of those bugs was invisible
precisely because the test that would have caught it could never run.

### Product bugs found and fixed (6)

- **`screen_shake`: the `duration` argument did nothing.** `_shake_duration` was written in two
  places and read in none, so trauma always decayed at the fixed `trauma_decay_rate` and every
  shake lasted 0.67s regardless of what the caller asked for — including the `hit_duration` /
  `kill_duration` presets. Decay rate is now derived from the requested duration, captured at
  `shake()` time (recomputing per frame from live trauma is exponential decay: it approaches
  zero without reaching it, so `is_shaking()` would never go false).
- **`particle_manager`: every new particle system was `add_child()`ed twice**
  (`_create_particle_system` already parents it), raising an engine error per spawn. This, not
  the lifetime logic, is what actually broke the three particle-limit tests.
- **The Pollution Immune synergy did nothing in the real game.** Bonuses were applied with
  `if key in current_stats`, but the shipped `pollution_immune.tres` declares
  `bonus_effects = {"hp": 1}` while the stat is `max_hp`. Key never matched, bonus silently
  dropped. A synergy the player earns by stacking three mutations had zero effect.
- **`hit_stop` discarded the delta it was handed** when `time_scale == 0`, hardcoding 0.016, so
  a large frame skip could not unfreeze. Verified empirically that Godot 4.7.1 really does
  report delta as exactly 0.0 at `time_scale 0` — so an estimate IS needed there; it is now a
  floor (`maxf(0.016, delta)`), not a replacement.
- **`enemy_spawner` tests were VACUOUSLY GREEN.** The spawner never spawned (see below), so
  "should not exceed max_enemies" was passing against zero enemies. Fixing the setup made five
  tests fail — all of them the PC-8 trap again: `group("enemies")` includes the ~125 dormant
  pooled instances, so the tests counted 125 "enemies" for a wave of 3, and the "707px spawn
  radius" was the distance from the spawner to a pooled instance parked at the origin.
- **`gate.sh` could not pass a green suite.** GUT omits the `Failing Tests` line entirely when
  nothing fails, and the gate treated an unparseable count as "GUT crashed" — so the quality
  gate failed at the exact moment the last test was fixed. It now falls back to the
  `Passing Tests` line. Nobody could have found this without first getting to zero.

### Test-harness defects fixed (no behaviour change)

- **Manual `_physics_process()` does not step the PhysicsServer.** Every tongue hit assertion
  was structurally incapable of passing. Now driven through real physics frames, per
  `test_tongue_damage.gd`.
- **Lambda by-value capture**, again — several tests recorded hits into a captured bool/int that
  the lambda copies. Third file this session with this defect (after `test_object_pool.gd`).
- **Frame-count errors** — the settle test sampled 3 frames past the end of extend; the overshoot
  test opened its sampling loop after the peak frame was already consumed.
- **Engine double-drive** — tests called `_physics_process` manually while the engine did too, so
  results depended on how many engine ticks happened to land. Critically, the disable must
  happen BEFORE the awaited frame in `before_each`: `is_action_just_pressed` survives until a
  real frame consumes it, so a leaked press starts a swing early. This is what made the elastic
  file pass test-by-test but fail in file order.
- **`@export` set after `add_child()`** — `enemy_spawner._ready()` snapshots `base_spawn_interval`,
  so configuring it post-`add_child` did nothing and the spawner sat at the 2.0s default while
  tests advanced 0.6–1.6s.
- **A test asserting the opposite of the API contract** — `trigger_hit_stop(-1.0)` was expected to
  refuse, but `-1.0` is that function's DEFAULT PARAMETER, i.e. the "unspecified" sentinel every
  no-argument call uses. Making the old assertion pass would have broken hit-stop entirely.

### Flakes, root-caused rather than retried

- `_orbit_angle` is seeded **randomly**, so an orbiting enemy is legitimately crossing the circle
  toward its slot on early frames. Two tests assumed the slot matched the spawn position and
  read 0.30 / 0.38 / 0.89 on three consecutive runs.
- A **5% crit flake** appeared only once real hits started landing: `crit_chance` defaults to
  0.05, so ~1 run in 20 resolved 2 damage against a `base_damage` 1 assertion.
- `test_separation_when_close` deterministically reached 14.907px against a `> 15.0` bound in its
  10-frame window. Separation worked; the window was too small.

### Lessons

- **A vacuous green is worse than a red.** The spawner suite reported success for a spawner that
  never spawned; `max_enemies` enforcement was "verified" against zero enemies. Fixing the setup
  turned 3 failures into 5 before it turned into 0 — going temporarily *more* red was the signal
  that real assertions had started running.
- **Fixing tests finds product bugs.** Six real defects were sitting behind unpassable tests. The
  instinct to treat a long-standing failure list as cosmetic debt would have shipped every one.
- **The last test is the hardest.** Reaching zero exposed a gate that had never executed its own
  green path. Any "N failures tolerated" ratchet has this blind spot.

---

## R2 — full spine, 2026-07-20 (the-pond `8852b19`)

**ROUND 2 NOT MET — 21/26 checks.** Five blocked, and the blocks are the result:
four of the six modes R2 requires have **no code path at all**, and the fifth (defeating the
boss) could not be achieved under competent automated play. Script:
`integrations/pond/verify_round2.py`. Ladder below R2 unaffected: spike 13/13 · smoke 8/8 ·
R1 18/18, game gate 1063/1063, real saves byte-identical throughout.

R2 exists to ask "does every mode reach a real outcome?", and a gate that quietly skipped what
the game cannot do would report a meaningless green. So unreachable modes FAIL with their
evidence attached.

### What passed (21)

- **All three arenas, selected the way the game selects them.** `create` now takes a
  `run_number` config key; runs 1 / 5 / 10 load Polluted Wetland / Chemical Plant / Corporate
  HQ Lobby, each with its own hazard type live as real nodes (3 puddles, 2 conveyor walls, 2
  security cameras), and per-wave enemy counts scale 8 / 16 / 20 exactly per FR-08.
- **The boss is reached by real proximity, spawns, and becomes vulnerable after its intro**, and
  takes real damage from real input (100 → 38 hp in the gate run).
- **The run-end spine**: `player_died` → `run_rewards_due` → `run_ended` → epilogue →
  RunEndScreen presented, with rewards settled before narration (the PC-6 ordering, still holding).

### PC-11 (CRITICAL) — two of three bosses are unreachable, and the true ending with them

`BossArena.boss_scene` is an `@export` set in exactly ONE place: `TestArena.tscn` →
`BossLobbyist`. `BossCEO.tscn` and `BossForeman.tscn` are referenced **only by unit tests** —
no production code instantiates either, and the three arena scenes carry hazards only.

The consequences are not cosmetic:
- `MetaProgression.check_ending_unlock()` requires `ceo_defeated`, so the **TRUE ENDING can
  never unlock** — the game's headline narrative payoff.
- `unlocks.all_bosses_defeated` can never become true.
- The CEO-gated informant (`informant_manager.gd:198`) and CEO hints (`hint_system.gd:116`) are
  dead content.
- `docs/prd.md:198` specifies a boss **per arena** (Wetland → The Foreman, Chemical Plant → The
  Inspector, Corporate HQ → The Executive). That mapping was never implemented.

Both bosses are fully built — scripts, bullet patterns, their own unit tests — and simply never
wired. This is the exact wire-only class UGT exists for: every in-process test passes.

### PC-12 — the victory run-end path has no caller

`end_run("victory")` is never called by production code. The only production caller is
`run_manager.gd:157` `end_run("death")` from `_on_player_died`. Boss defeat routes to
`enter_investigation_phase()`, never to a win. So `MetaProgression.end_run_victory()` (150%
rewards) is called only by tests, `runs.successful_runs` can never increment, `best_time` can
never be set, and `RunEndScreen`'s entire victory branch (`run_end_screen.gd:77/120/157`) is
unreachable. R1 exercised death because death is the only ending that exists.

### PC-13 — ~~there is no pause; ESC quits the game outright~~ **RESOLVED — the-pond T-058 + T-059 (2026-07-20)**

**Resolved.** Pause is now a real, non-destructive mode. The `pause` action is bound in
`project.godot:78–82` (`physical_keycode: 4194305`, ESC) and consumed by
`combat/scenes/test_arena_controller.gd::_handle_pause_input` (`:122`, reached from `_process:110`),
which flips `get_tree().paused` and emits `EventBus.pause_toggled` via `_set_paused` (`:138–141`) —
pausing only during `RunPhase.COMBAT` (`:126`), never stacking on an existing pause (`:128`), never
destroying the run. `SceneRouter._on_pause_toggled` (`core/scripts/scene_router.gd:185`, connected
`:110`) presents/dismisses `metagame/scenes/PauseMenu.tscn` off that signal. `get_tree().quit()` is
gone from `combat/`.

The previously-cited `input_manager.gd:142` binding was **deleted by the-pond T-059** (not merely
unwired). It was an orphaned parallel input registry never registered in `project.godot`'s autoload
and never part of the real input map; `core/scripts/input_manager.gd` and `test/unit/test_input.gd`
are gone from `git ls-files`. Mis-citing that orphan as the live pause binding is the exact defect
the-pond `TASKS.md:397` (T-059's note) calls out — its green `test_default_bindings_exist` is what
let the earlier review cite `input_manager.gd:142` when the real binding was always `project.godot:78–82`.

**Was:** the original PC-13 claimed the `pause` action was bound at `input_manager.gd:142` and
consumed at `test_arena_controller.gd:84` by `get_tree().quit()` — terminating the application with
no menu and no confirmation, destroying the run, with no PauseMenu scene anywhere. That code path no
longer exists.

The harness deliberately does not drive the pause action from the generic input path (wiring it into
R3's random-input tier could pause/stall the process). The live wire assertion — re-enable the pause
action in the harness and assert `get_tree().paused` / `pause_toggled` emitted / run not destroyed —
is **U-008's** job.

### PC-14 — ~~the "locked" boss arena refills with adds~~ **FIXED — the-pond T-061 (2026-07-20, U-005)**

**Resolved.** `BossArena.trigger_boss()` now calls `_stop_enemy_spawner()` right after
`_lock_arena()` (the-pond `combat/scripts/boss_arena.gd:57`, T-061), which resolves the sibling
`EnemySpawner` via `_find_enemy_spawner()` and calls its `stop_spawning()`. The proximity-trigger
path (`_on_player_entered → trigger_boss`) previously never halted the spawner — that was the
actual defect — so the one-shot `_clear_regular_enemies()` was immediately undone. It is verified
in-suite by `test/unit/test_boss_arena.gd::test_trigger_boss_stops_spawner_no_new_enemies_for_5s`,
which drives the exact proximity-trigger path and asserts zero spawns across ~301 simulated 60 Hz
frames (>5s) after lock.

This is now a **passing wire measurement** in `verify_round2.py`: after the boss triggers, the gate
holds idle in the locked arena for a short window (`PC14_SAMPLES` × `PC14_STRIDE` = ~3s, evade +
dodge only, never attacking so the boss is neither killed nor able to kill the player and a spawner
leak has a fair chance to fire) and asserts **0 non-boss adds at every sample**. It passes because
the spawner is stopped and would fail if the T-061 fix regressed. Replaces the old vacuous
`gate.check(True, "boss arena is a clean 1v1", ...)` conditional arm.

**Was (BLOCKED in the 8852b19 run):** `_clear_regular_enemies()` emptied the arena on trigger but
nothing stopped `EnemySpawner` — it was only paused for INVESTIGATION (`test_arena_controller.gd:113`),
so the arena refilled within seconds. The gate observed 3 regular enemies (Polluted Tadpole, Toxic
Minnow) inside the locked arena during the boss fight.

### PC-15 (balance) — ~~the wave-5 boss could not be defeated (fractional damage rounds to nothing)~~ **DIAGNOSIS WITHDRAWN — the-pond T-062 verdict adopted (2026-07-20, U-004)**

**Correction.** The fractional-rounding mechanism and the "taking upgrades makes the fight
HARDER" headline are **REFUTED**. **the-pond T-062 (`test/unit/test_boss_damage_scaling.gd`,
DONE) is now the authoritative measurement**, driving the real wired paths (Player.tscn +
MutationManager consuming `EventBus.mutation_selected`, PlayerController writing
`tongue.base_damage`, `BossBase.apply_difficulty_scaling`). Its measured verdict:

- `mercury_blood` (`damage_modifier = 0.5`) computes `1 * 1.5 = 1.5 → round → 2` — i.e.
  **DOUBLE** damage, not "rounds to nothing" (`mutation_manager.gd:120` →
  `player_controller.gd:214`, asserted by `test_combat_emissions.gd:201-202`). It is the
  **first** entry in this driver's own `PREFERRED` list (`verify_round2.py`), so realistic
  driving takes it first.
- For a canonical 100-HP boss, time-to-kill **FALLS ~45%** as upgrades are taken
  (`ttk@0 ≈ 52.4s → ttk@10 ≈ 28.8s`): the inversion is **REFUTED for realistic
  (offense-inclusive) play** (T-062 `test_realistic_build_refutes_inversion`).
- The inversion is **CONFIRMED only for a degenerate zero-offense build**
  (`52.4s → 78.6s`, T-062 `test_utility_only_build_confirms_asymmetry`), which bounds where the
  original "boss survived with 2–52 hp" observation is real.
- The true mechanism is a **count-vs-type asymmetry**: boss HP scales with mutation *count*
  (`hp_scale_per_mutation`), while player DPS scales only with the damage/crit/cooldown *subset*
  — **not** fractional rounding (only `strong_legs` at 0.1 rounds away, per T-062
  `test_rounding_facts_are_the_supported_ones`).

`verify_round2.py`'s PC-15 block now logs the actual `active_ids` and resolved tongue
`base_damage` at boss-fight start (uncounted `gate.info`, read over the wire) so any UGT-side
balance note stays evidence-backed. **Denominator UNCHANGED by this correction:** no
`gate.check` was added or removed — the instrumentation is a `gate.info`, so the tally stays as
last recorded (U-003: **30/33**, still `NOT MET`, 2 blocked = PC-12 harness gap + PC-15
balance). The automated driver still did not defeat the boss this run; flipping PC-15's
pass/fail status is **U-009**'s re-baseline, not this task's.

Original record below, kept for the method trail:

> **~~the wave-5 boss could not be defeated~~**
>
> Across **4 seeds and ~20 driver configurations** the Lobbyist survived with **2–52 hp**
> remaining; the player died every time. Best single result: 2 hp. The driver kites at tongue
> range, evades real bullet positions, spends dodge i-frames on cooldown, culls adds, and takes
> level-up cards.
>
> ~~The arithmetic is the finding:~~
> - ~~tongue `base_damage` is **1** against **100** boss hp — ~100 landed hits at ~1.8 swings/sec;~~
> - ~~one boss bullet costs the player **10** of 100 hp, so ~10 mistakes is death;~~
> - ~~**mutations cannot close the gap.** `damage_modifier` is fractional (Mercury Blood +0.5,
>   Strong Legs +0.1) against an **int** base of 1, so `round()` sends almost every damage
>   mutation to no change at all — only Mercury Blood reaches 2;~~
> - ~~meanwhile `hp_scale_per_mutation` adds a full **+5% boss hp per mutation taken**.~~
>
> ~~So taking mutations makes the fight strictly HARDER: measured 100 hp unscaled vs **130 hp**
> after six mutations that produced `damage 1.1` → still 1. That inverts the roguelike loop — the
> optimal play is to refuse upgrades.~~ This is a balance signal, not a proof of impossibility: a
> skilled human may well win. But an agent that plays the mechanics correctly should not need 20
> configurations to fail.

### Two findings I filed and then REFUTED — both were my own instrument

Recording these because the false versions were persuasive:

- **"The boss fight soft-locks."** The world froze mid-swing: tongue stuck EXTENDING, i-frames
  never expiring, dodge cooldown not ticking, boss and player hp static for 300 cycles while
  physics frames advanced. It was a **pending level-up**: `LevelUpUI` pauses the whole tree, and
  my fight loop never picked a card. Any driving loop must check `level_up.pending` every
  iteration.
- **"The level-up pool is broken — it re-offers taken mutations and never surfaces Mercury
  Blood."** The same triple really was returned three times running, with the trigger's own
  `_taken_ids` showing the pick had registered. The cause was `choose` advancing only 8 frames
  while `LevelUpUI._animate_out()` is a **0.3s tween (18 frames)** during which the cards stay
  clickable — so the driver returned mid-fade and clicked again. With 40 frames, offers are
  fresh every time and mutations accumulate correctly.

The second one leaves a real but minor game-side note: cards remain clickable throughout the
fade-out, and each extra click re-emits `EventBus.mutation_selected`, which increments
`BossArena._active_mutation_count` and inflates boss hp for a mutation the player never gained.
A double-clicking human hits this.

### Lesson

Three times this session a "game bug" was my own instrument (PC-9's retract tail, the soft-lock,
the level-up pool). The tell is the same each time: the anomaly is at the boundary I built, not
in the code I'm accusing. Reproduce the number from the production math or instrument the
boundary before filing — and note that the two refuted findings here cost far less to check than
they would have cost the game team to chase.
