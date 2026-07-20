# Pond Conspiracy — trial findings log

Commit-traceable record. A failed check is data. Game repo: `~/Dev/Games/the-pond/`.

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
