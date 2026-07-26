extends Node2D

## Entry point for Sokoban Mini + the HUMAN front end (T-006).
##
## THIS FILE CONTAINS NO GAME RULE. Per the standing constraint in TASKS.md,
## every push / collision / win rule lives in exactly one place —
## `res://scripts/board.gd`. All this script may do is:
##   1. translate a key into a PRD action id (`KEY_ACTIONS` below), and
##   2. hand that id to `board.apply_action()` via the single handler
##      `_on_action_input()`, then re-read `board` to snap the sprites.
## No wall check, no push check, no `moves_taken` arithmetic and no solved
## check may ever appear here. A reviewer can grep this file for `Tile.WALL`,
## `boxes_on_target`, `moves_taken` or `is_solved` and should find no decision
## made on them.
##
## The handler deliberately takes an `int` direction rather than an
## `InputEvent`, so a test drives the exact same code path a keypress does
## without synthesizing input (headless Godot's 64x64 root window swallows
## synthesized events — an environment quirk, not game logic).
##
## Errors are printed as returned data, never `push_error()` / `assert()`:
## a project run must leave stderr clean (T-001's Accept).

const Board := preload("res://scripts/board.gd")
const Level := preload("res://scripts/level.gd")

## Arrow keys + WASD to move, R to retry the level (the PRD's "a player can
## always retry" — without it a wedged box would force a process restart). The
## ids on the right come from `Board.Direction` / `Board.ACTION_RELOAD` — this
## table never invents a number of its own, so it cannot drift from the PRD's
## `0=up, 1=down, 2=left, 3=right, 4=reset_level`.
const KEY_ACTIONS := {
	KEY_UP: Board.Direction.UP,
	KEY_W: Board.Direction.UP,
	KEY_DOWN: Board.Direction.DOWN,
	KEY_S: Board.Direction.DOWN,
	KEY_LEFT: Board.Direction.LEFT,
	KEY_A: Board.Direction.LEFT,
	KEY_RIGHT: Board.Direction.RIGHT,
	KEY_D: Board.Direction.RIGHT,
	KEY_R: Board.ACTION_RELOAD,
}

## Returned for a key that is not bound. Also accepted by
## `_on_action_input()`, where `board.apply_action()` treats it as a no-op.
const NO_ACTION := -1

## Side of one grid cell in pixels. The whole of the "snap sprites" behaviour
## is `cell_to_position()` below.
const CELL_SIZE := 32

const COLOR_FLOOR := Color(0.13, 0.14, 0.17)
const COLOR_WALL := Color(0.33, 0.35, 0.40)
const COLOR_TARGET := Color(0.55, 0.42, 0.16)
const COLOR_BOX := Color(0.78, 0.62, 0.29)
const COLOR_PLAYER := Color(0.40, 0.72, 0.85)

## The rules engine. Public so a test can inject a small inline fixture board
## without going anywhere near `_ready()` or the scene tree.
var board = null

## View nodes. Empty/null until `build_view()` runs, which is what keeps the
## handler usable in a node-free test.
var view_root: Node2D = null
var player_node: ColorRect = null
var box_nodes: Array = []

var _rendered_level_index: int = -1


func _ready() -> void:
	board = Board.new()
	if not board.load_levels_from_paths():
		# Returned data, printed — never push_error(): stderr must stay clean.
		print("Sokoban Mini: could not load levels — %s: %s" % [board.error_code, board.error_message])
		return
	build_view()


## Key -> PRD action id, or `NO_ACTION` when the key is not bound. Both
## `_unhandled_input()` and the mapping test go through this one function, so
## the table can never drift from what the game actually reads.
static func action_for_key(keycode: int) -> int:
	return KEY_ACTIONS.get(keycode, NO_ACTION)


## Grid cell -> pixel position of that cell's sprite. This IS the snapping
## rule: a sprite is only ever placed on an exact cell multiple, never
## interpolated. Pure and node-free so it is testable on its own.
static func cell_to_position(cell: Vector2i) -> Vector2:
	return Vector2(cell.x * CELL_SIZE, cell.y * CELL_SIZE)


## THE single entry point for a human action — every key press funnels through
## here, and a test calls it directly with an action id.
##
## Returns `board.apply_action()`'s own bool, untouched. The view is re-synced
## unconditionally, including when the move returned false: `board.gd` warns
## that a false return can still coincide with its lazy level advance, so the
## view must always re-read state rather than trust the return value.
func _on_action_input(action: int) -> bool:
	if board == null:
		return false
	var moved: bool = board.apply_action(action)
	_sync_view()
	return moved


func _unhandled_input(event: InputEvent) -> void:
	if not (event is InputEventKey):
		return
	var key_event := event as InputEventKey
	if not key_event.pressed or key_event.echo:
		return
	# Physical keycode first so WASD keeps its physical position on a non-QWERTY
	# layout; the `keycode` fallback is what resolves the arrow keys.
	var action := action_for_key(key_event.physical_keycode)
	if action == NO_ACTION:
		action = action_for_key(key_event.keycode)
	if action == NO_ACTION:
		return
	_on_action_input(action)
	get_viewport().set_input_as_handled()


## (Re)builds the whole view for the level currently in `board`. Safe to call
## repeatedly — the previous view is discarded first.
func build_view() -> void:
	if board == null:
		return
	var level = board.current_level()
	if level == null:
		return

	if view_root != null:
		remove_child(view_root)
		view_root.free()
	view_root = Node2D.new()
	view_root.name = "View"
	add_child(view_root)
	box_nodes = []
	player_node = null

	var viewport_size := Vector2(
		float(ProjectSettings.get_setting("display/window/size/viewport_width", 640)),
		float(ProjectSettings.get_setting("display/window/size/viewport_height", 480))
	)
	var grid_size := Vector2(level.width, level.height) * CELL_SIZE
	view_root.position = ((viewport_size - grid_size) * 0.5).floor()

	# Static geometry: a backdrop, a full tile per wall, a centred pip per target.
	var backdrop := _new_rect(COLOR_FLOOR, grid_size)
	backdrop.position = Vector2.ZERO
	view_root.add_child(backdrop)
	for y in range(level.height):
		for x in range(level.width):
			match level.tile_at(x, y):
				Level.Tile.WALL:
					_add_cell_rect(Vector2i(x, y), COLOR_WALL)
				Level.Tile.TARGET:
					_add_target_pip(Vector2i(x, y))

	# One node per box, index-aligned with `board.boxes` (board.gd guarantees
	# that order is stable across pushes).
	for box in board.boxes:
		box_nodes.append(_add_cell_rect(box, COLOR_BOX))
	player_node = _add_cell_rect(board.player, COLOR_PLAYER)

	_rendered_level_index = board.level_index


## Snaps the movable sprites onto their cells. A no-op when no view exists,
## which is what lets tests drive `_on_action_input()` without a scene tree.
func _sync_view() -> void:
	if view_root == null or board == null:
		return
	if board.level_index != _rendered_level_index or box_nodes.size() != board.boxes.size():
		build_view()
		return
	for i in range(box_nodes.size()):
		box_nodes[i].position = cell_to_position(board.boxes[i])
	if player_node != null:
		player_node.position = cell_to_position(board.player)


## One full-cell ColorRect placed EXACTLY on `cell_to_position(cell)` — no
## inset, no offset. That exactness is what `_sync_view()` reasserts on every
## move, and what the snapping test pins.
func _add_cell_rect(cell: Vector2i, color: Color) -> ColorRect:
	var rect := _new_rect(color, Vector2(CELL_SIZE, CELL_SIZE))
	rect.position = cell_to_position(cell)
	view_root.add_child(rect)
	return rect


## The small centred marker drawn on a target cell. Static decoration only —
## it is never moved, so its centring offset cannot affect the snap rule.
func _add_target_pip(cell: Vector2i) -> ColorRect:
	var pip_size := Vector2(CELL_SIZE, CELL_SIZE) * 0.35
	var rect := _new_rect(COLOR_TARGET, pip_size)
	rect.position = cell_to_position(cell) + (Vector2(CELL_SIZE, CELL_SIZE) - pip_size) * 0.5
	view_root.add_child(rect)
	return rect


## ColorRects only — no textures, so there is nothing for Godot to import and
## nothing to break under `--headless`.
func _new_rect(color: Color, size: Vector2) -> ColorRect:
	var rect := ColorRect.new()
	rect.color = color
	rect.size = size
	rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return rect
