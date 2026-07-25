# Sokoban Mini — Game PRD

**One-liner:** A minimal Sokoban clone — four-direction push-crate puzzles, 3
bundled levels, no timer, no scoring beyond move count. Built in Godot to
demonstrate UGT driving an engine UGT has no native adapter for.

**Why this example exists:** Demonstrate `/tasklist` + `/orchestrate` building
a small Godot game from a PRD, then a **hand-written, engine-first UGT
adapter** (the same pattern `examples/harness-game` uses for a Python engine)
driving it over a local TCP socket — because Godot's frame-based main loop
doesn't fit a blocking-stdio subprocess bridge the way Python/Node do.

## Stack

Godot 4.x, 2D, single scene, tile-based grid movement. One canonical move
function, two front ends (mirrors the discipline in the other two examples):

- **`res://scripts/board.gd`** — loads a level, holds `try_move(direction)`
  (the only place push/collision rules live), tracks solved state.
- **Human input** — the four arrow keys / WASD call `try_move()` directly.
  This is the real, playable game.
- **`res://scripts/ugt_bridge.gd`** — an autoload, active only when launched
  with `--ugt-bridge` (or `UGT_BRIDGE=1`), that opens a local `TCPServer`,
  accepts one connection, and maps a numeric `action_id` from a socket
  message to a `try_move(direction)` call. **Never re-implements
  push/collision logic.** `StreamPeerTCP` delivers raw bytes with no
  built-in line framing, so the bridge must buffer incoming bytes across
  `_process()` polls and split on `\n` itself — a message can legitimately
  arrive split across two or more frames.

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
- No lose state — a player can always retry; add a `reset_level` action (or
  the bridge's `reset` command) for a stuck position. No move limit, no
  timer.

## Content: 3 bundled levels

`res://levels/level_01.txt`, `level_02.txt`, `level_03.txt` — plain-text
grids in the legend above, increasing in box count (1 → 2 → 3 boxes) and grid
size. Solving a level advances to the next automatically; solving the third
sets `all_levels_solved: true`.

## UGT hooks required (the game/integration contract)

When launched with the bridge flag, `ugt_bridge.gd` listens on
`127.0.0.1:8910` (configurable via `--ugt-port=N`) for newline-delimited
JSON, same message shape as UGT's subprocess protocol (see
`../integration/PRD.md`):

- `{"command": "reset"}` → reloads the current level from scratch →
  `{"state": {...}}`
- `{"command": "step", "action_id": N}` → one `try_move()` call →
  `{"state": {...}, "terminated": bool, "truncated": bool, "info": {}}`
- `{"command": "close"}` → clean shutdown

State shape:

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

`terminated` mirrors `all_levels_solved`.

## Non-goals

No undo/redo, no level editor, no animation beyond snapping sprite
positions, no sound, no save/load between sessions, more than 3 levels,
diagonal movement, or any scoring beyond `moves_taken`.

## Acceptance criteria

- Runs in the Godot editor and as an exported headless binary (`godot4
  --headless --path . -- --ugt-bridge`).
- All 3 levels are solvable (a documented solution move sequence exists for
  each).
- Same level + same action sequence from `reset` reproduces identical state
  (the game has no randomness at all, so this should hold trivially — worth
  asserting anyway).
