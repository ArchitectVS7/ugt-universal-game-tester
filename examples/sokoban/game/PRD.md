# Sokoban Mini — Game PRD

**One-liner:** A minimal Sokoban clone — four-direction push-crate puzzles, 3
bundled levels, no timer, no scoring beyond move count.

**Why this example exists:** Demonstrate `/tasklist` + `/orchestrate` building
a small Godot game from a PRD.

## Stack

Godot 4.x, 2D, single scene, tile-based grid movement. One canonical move
function behind the front end (mirrors the discipline in the other two
examples):

- **`res://scripts/board.gd`** — loads a level, holds `try_move(direction)`
  (the only place push/collision rules live), tracks solved state.
- **Human input** — the four arrow keys / WASD call `try_move()` directly.
  This is the real, playable game.

## Core mechanics

- 4 actions: `0=up, 1=down, 2=left, 3=right`.
- Grid legend (classic Sokoban ASCII, used for level files): `#` wall, `@`
  player, `$` box, `.` target, `*` box-on-target, `+` player-on-target,
  ` ` floor.
- Moving into a wall: no-op. Moving into a box: box is pushed one cell in the
  same direction *only if* the cell beyond it is floor or an empty target
  (not a wall, not another box) — otherwise the whole move is a no-op
  (classic Sokoban rule).
- Level solved when every box is on a target (`boxes_on_target ==
  boxes_total`).
- `moves_taken` increments only on a move that actually changes player or box
  position; a wall-blocked or box-blocked no-op does not increment it.
- No lose state — a player can always retry; add a `reset_level` action for a
  stuck position. No move limit, no timer.

## Content: 3 bundled levels

`res://levels/level_01.txt`, `level_02.txt`, `level_03.txt` — plain-text
grids in the legend above, increasing in box count (1 → 2 → 3 boxes) and grid
size. Solving a level advances to the next automatically; solving the third
sets `all_levels_solved: true`.

## Game state

`board.gd` exposes a snapshot of exactly this shape:

```json
{
  "level_index": 0,
  "player_x": 3, "player_y": 2,
  "boxes_on_target": 1, "boxes_total": 2,
  "moves_taken": 17,
  "level_solved": false,
  "all_levels_solved": false
}
```

`reset_level` reloads the current level from scratch, keeping `level_index`.

## Verification

Runnable headless with nothing installed but Godot itself:

- **`tests/run_tests.gd`** — a ~40-line GDScript test runner (discovers
  `res://tests/test_*.gd`, runs `test_*` methods, prints PASS/FAIL per case,
  exits non-zero if any failed or if it discovered no tests). Deliberately
  **not** GUT or any other third-party addon: vendoring ~100 files of
  someone else's test framework to check a three-level demo would be a
  heavier dependency than the game. A runner this small is only trustworthy
  with a negative control, so `tools/check_runner_reports_failure.sh` proves
  it can actually fail — a suite that cannot go red is worse than no suite.

## Non-goals

No undo/redo, no level editor, no animation beyond snapping sprite
positions, no sound, no save/load between sessions, more than 3 levels,
diagonal movement, or any scoring beyond `moves_taken`. No third-party Godot
addons.

## Acceptance criteria

- Runs in the Godot editor, and headless by running the project directly
  (`godot4 --headless --path .`) — no exported binary is required for this
  example.
- All 3 levels are solvable (a documented solution move sequence exists for
  each).
- Same level + same move sequence from `reset_level` reproduces identical state
  (the game has no randomness at all, so this should hold trivially — worth
  asserting anyway).
