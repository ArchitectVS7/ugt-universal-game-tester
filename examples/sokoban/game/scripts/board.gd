extends RefCounted
## Sokoban rules engine — the ONE place push/collision/win rules live.
##
## Per the standing constraint in TASKS.md, `try_move()` below is the only
## function in the project allowed to decide whether a move happens: neither the
## human input handler (T-006) nor `ugt_bridge.gd` (T-007) may contain a rule,
## they only call `try_move(direction)` and re-read `get_state()`.
##
## Split of responsibilities with `res://scripts/level.gd`:
##  - `level.gd` = immutable parsed geometry (walls / floor / targets, plus the
##    START positions of the player and the boxes). Never mutated.
##  - `board.gd` = the mutable run state (`player`, `boxes`, `moves_taken`,
##    `level_index`, `all_levels_solved`) + the rules that change it. A reset is
##    therefore just "re-copy the start positions out of the parsed level".
##
## Deliberately no `class_name` (no dependency on the editor's global class
## registry) — consumers do:
##     const Board := preload("res://scripts/board.gd")
##
## Errors are RETURNED DATA, never `assert()` / `push_error()` / `push_warning()`:
## a project run must leave stderr clean (T-001's Accept), and returned data is
## the only form the tests can assert on. A failed load leaves NO half-built
## board behind.
##
## NO LEVEL GEOMETRY IS HARDCODED HERE. `DEFAULT_LEVEL_PATHS` is a list of file
## paths, not grids; the grids themselves are plain-text files under
## `res://levels/` (authored in T-005) parsed by `level.gd`.

const Level := preload("res://scripts/level.gd")

## PRD "Core mechanics": `0=up, 1=down, 2=left, 3=right`. The action-id table
## lives HERE rather than in the bridge so that `ugt_bridge.gd` can stay a pure
## pass-through of the wire's `action_id` with zero rule content — including the
## "an out-of-range action_id is a no-op, not an error" behaviour.
enum Direction { UP = 0, DOWN = 1, LEFT = 2, RIGHT = 3 }

## Indexed by `Direction`. Godot's Y axis grows downward, so UP is -1.
const DIRECTION_VECTORS := [Vector2i(0, -1), Vector2i(0, 1), Vector2i(-1, 0), Vector2i(1, 0)]

## Paths only — see the "no level geometry" note above.
const DEFAULT_LEVEL_PATHS := [
	"res://levels/level_01.txt",
	"res://levels/level_02.txt",
	"res://levels/level_03.txt",
]

## Board-specific load failure; every other code comes straight from `level.gd`.
const ERR_NO_LEVELS := "NO_LEVELS"

## "" means the last load succeeded.
var error_code: String = ""

## Human-readable detail; a per-level failure is prefixed with the level index.
var error_message: String = ""

## 0-based index of the level currently being played.
var level_index: int = 0

## Current player cell.
var player: Vector2i = Vector2i(-1, -1)

## Current box cells as `Vector2i`, in the level's row-major start order. The
## order is preserved across pushes (a push mutates the entry in place) so a
## front end can bind one sprite per index and downstream state never depends on
## iteration order.
var boxes: Array = []

## Moves that actually changed a position. NOT reset by a level advance — see
## `try_move()`; only `reset_level()` zeroes it.
var moves_taken: int = 0

## True once the last level has been solved. While set, `try_move()` is frozen.
var all_levels_solved: bool = false

## Parsed `level.gd` instances, in play order.
var _levels: Array = []


## Loads levels from an array of raw grid strings. This is the entry point the
## tests use with small inline fixtures; the game itself uses
## `load_levels_from_paths()`. Returns true on success; on failure returns false,
## sets `error_code`/`error_message` and leaves the board empty.
func load_levels_from_texts(texts: Array) -> bool:
	var loaded: Array = []
	for i in range(texts.size()):
		var level := Level.new()
		if not level.load_from_text(str(texts[i]), "<inline %d>" % i):
			return _fail_level(i, level)
		loaded.append(level)
	return _adopt(loaded)


## Loads levels from files under `res://levels/`. Defaults to the PRD's three
## bundled levels. Same failure contract as `load_levels_from_texts()`.
func load_levels_from_paths(paths: Array = DEFAULT_LEVEL_PATHS) -> bool:
	var loaded: Array = []
	for i in range(paths.size()):
		var level := Level.new()
		if not level.load_from_file(str(paths[i])):
			return _fail_level(i, level)
		loaded.append(level)
	return _adopt(loaded)


## THE move function. `direction` is a `Direction` / PRD action id.
##
## Returns true only when the move actually changed a position (and therefore
## incremented `moves_taken`). Rules applied, in order:
##  1. an unknown direction is a no-op (not an error) — this is what lets the
##     bridge pass a wire `action_id` straight through;
##  2. once every level is solved the board is frozen until `reset_level()`;
##  3. LAZY LEVEL ADVANCE: a solved level advances at the START of the next
##     move, and that same move is then applied in the new level (see below);
##  4. moving into a wall is a no-op;
##  5. moving into a box pushes it one cell in the same direction ONLY IF the
##     cell beyond it is floor or an empty target — a wall or a second box
##     behind it makes the WHOLE move a no-op (classic Sokoban);
##  6. otherwise the player moves and `moves_taken` increments.
##
## Why the advance is lazy rather than immediate at the end of the solving move:
## the solving move must leave `level_solved: true` observable in `get_state()`,
## which an immediate advance would destroy (state would already show the next
## level, unsolved). Applying the pending move in the new level rather than
## consuming it is what lets a caller concatenate per-level solution sequences
## (T-005 / T-008) and replay them without inserting a filler move.
##
## NOTE FOR CALLERS: because of (3), a `false` return can coincide with a level
## transition (e.g. the first move in the new level is wall-blocked). Always
## re-read `get_state()` after a call, never only when this returns true.
func try_move(direction: int) -> bool:
	if _levels.is_empty():
		return false
	if direction < 0 or direction >= DIRECTION_VECTORS.size():
		return false
	if all_levels_solved:
		return false

	if is_solved():
		if level_index + 1 < _levels.size():
			_start_level(level_index + 1)
		else:
			# Only reachable for a board whose LAST level was already solved at
			# load time (the solving move itself sets the flag below).
			all_levels_solved = true
			return false

	var step: Vector2i = DIRECTION_VECTORS[direction]
	var target: Vector2i = player + step
	if _tile(target) == Level.Tile.WALL:
		return false

	var box_index := _box_index_at(target)
	if box_index >= 0:
		var beyond: Vector2i = target + step
		if _tile(beyond) == Level.Tile.WALL:
			return false
		if _box_index_at(beyond) >= 0:
			return false
		boxes[box_index] = beyond

	player = target
	moves_taken += 1

	if is_solved() and level_index == _levels.size() - 1:
		all_levels_solved = true
	return true


## Reloads the current level from scratch (PRD's `reset` command). Keeps
## `level_index` — a reset retries the level being played, it does not restart
## the game — and clears `moves_taken` and the frozen `all_levels_solved` state.
func reset_level() -> void:
	if _levels.is_empty():
		return
	_start_level(level_index)
	moves_taken = 0
	all_levels_solved = false


## Boxes currently standing on a target cell. Computed live, never a sticky flag.
func boxes_on_target() -> int:
	var level = current_level()
	if level == null:
		return 0
	var count := 0
	for box in boxes:
		if level.tile_at(box.x, box.y) == Level.Tile.TARGET:
			count += 1
	return count


func boxes_total() -> int:
	var level = current_level()
	return 0 if level == null else level.boxes_total()


## PRD: "Level solved when every box is on a target".
func is_solved() -> bool:
	if _levels.is_empty():
		return false
	return boxes_on_target() == boxes_total()


func level_count() -> int:
	return _levels.size()


## The parsed geometry currently in play, or null when nothing is loaded.
func current_level():
	if level_index < 0 or level_index >= _levels.size():
		return null
	return _levels[level_index]


## The PRD's exact state shape (UGT hooks section). `ugt_bridge.gd` JSON-encodes
## this dictionary untouched — do not add, rename or reorder keys without
## changing the PRD.
func get_state() -> Dictionary:
	return {
		"level_index": level_index,
		"player_x": player.x,
		"player_y": player.y,
		"boxes_on_target": boxes_on_target(),
		"boxes_total": boxes_total(),
		"moves_taken": moves_taken,
		"level_solved": is_solved(),
		"all_levels_solved": all_levels_solved,
	}


## Copies the start positions out of a parsed level. The `Level` is never
## mutated, which is what makes a reset cheap and exact.
func _start_level(index: int) -> void:
	level_index = index
	var level = _levels[index]
	player = level.player_start
	boxes = level.boxes.duplicate()


## Index into `boxes` of the box occupying `cell`, or -1. A linear scan is the
## right shape here: the PRD's levels hold 1–3 boxes.
func _box_index_at(cell: Vector2i) -> int:
	for i in range(boxes.size()):
		if boxes[i] == cell:
			return i
	return -1


## Tile under `cell`. Off-grid reads come back as `WALL` from `level.gd`, which
## is a BOUNDS convenience — the rule "a wall blocks the move" is the caller's,
## in `try_move()` above.
func _tile(cell: Vector2i) -> int:
	var level = current_level()
	if level == null:
		return Level.Tile.WALL
	return level.tile_at(cell.x, cell.y)


func _adopt(loaded: Array) -> bool:
	_clear()
	if loaded.is_empty():
		error_code = ERR_NO_LEVELS
		error_message = "no levels supplied"
		return false
	_levels = loaded
	_start_level(0)
	return true


## Records a per-level load failure and wipes the board. Always false, so
## callers can `return _fail_level(...)`.
func _fail_level(index: int, level) -> bool:
	var code: String = level.error_code
	var detail: String = level.error_message
	_clear()
	error_code = code
	error_message = "level %d: %s" % [index, detail]
	return false


func _clear() -> void:
	error_code = ""
	error_message = ""
	_levels = []
	level_index = 0
	player = Vector2i(-1, -1)
	boxes = []
	moves_taken = 0
	all_levels_solved = false
