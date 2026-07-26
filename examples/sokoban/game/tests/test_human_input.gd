extends "res://tests/assertions.gd"
## T-006 — the human input front end (`res://scripts/main.gd`).
##
## What this file proves: routing a move through `Main._on_direction_input()`
## produces EXACTLY the state that calling `board.try_move()` with the same
## direction produces — i.e. the input layer adds no rule of its own, which is
## the standing constraint ("all push/collision/win rules live in
## `board.gd::try_move()`"). Every parity case therefore runs the SAME fixture
## down two paths and compares player position, box positions and the PRD state
## dictionary.
##
## DELIBERATELY NOT DONE HERE: no `InputEventKey` is synthesized, no
## `Input.parse_input_event()` / `Input.action_press()`, no window resizing and
## no `SceneTree` node adds. Headless Godot's root window is 64x64 and
## synthesized input does not land without resizing it twice — an environment
## quirk, not game logic, and not what T-006 is testing. The handler takes an
## `int` direction precisely so it can be called directly.
##
## Fixtures are SMALL INLINE GRIDS (same discipline as `test_board.gd`), never
## the shipped `res://levels/*.txt`, and are arrays of row strings joined by
## `_grid()` rather than triple-quoted literals — GDScript keeps a multi-line
## string's indentation tabs, which would inject tabs into the grid.
##
## A `Main` is created with `Main.new()` and never added to a tree, so `_ready()`
## never runs and no node is created unless a case explicitly calls
## `build_view()`. `Main` extends `Node2D`, so every case must `free()` what it
## creates (`queue_free()` would never run outside a tree).

const Main := preload("res://scripts/main.gd")
const Board := preload("res://scripts/board.gd")

## 6x6 · player (2,2) · box (3,2) · target (3,3).
## Open room: all four directions are legal, and RIGHT is a real push
## (box (3,2) -> (4,2)), so parity covers a pushing move as well as free ones.
const ROOM := ["######", "#    #", "# @$ #", "#  . #", "#    #", "######"]

## 5x4 · player (1,1) · box (2,1) · wall behind it at (3,1) · target (3,2).
## LEFT and UP are wall-blocked; RIGHT is a wall-behind-the-box blocked push.
## Used so parity is asserted on NO-OPS too, not only on successful moves.
const BLOCKED := ["#####", "#@$##", "#  .#", "#####"]

## 5x3 · player (1,1) · box (2,1) · target (3,1). RIGHT solves it in one move.
const ONE_BOX := ["#####", "#@$.#", "#####"]

## 6x3 · player (1,1) · box (2,1) · target (4,1). Second level of the
## advance fixture — RIGHT pushes the box onto plain floor, not a solve.
const NEXT_LEVEL := ["######", "#@$ .#", "######"]

## Every PRD action id, in order.
const ALL_DIRECTIONS := [0, 1, 2, 3]
const DIRECTION_NAMES := ["up", "down", "left", "right"]


func _grid(rows: Array) -> String:
	var parts := PackedStringArray()
	for row in rows:
		parts.append(row)
	return "\n".join(parts)


## A board holding `fixtures` (an array of row-arrays) as its levels. Asserts
## the fixture itself loaded, so a broken fixture fails loudly rather than
## silently no-op-ing every later assertion.
func _board(fixtures: Array):
	var texts: Array = []
	for rows in fixtures:
		texts.append(_grid(rows))
	var board := Board.new()
	assert_true(board.load_levels_from_texts(texts), "fixture should load")
	return board


## A `Main` driving its own fresh copy of `fixtures`. No `_ready()`, no nodes.
func _main(fixtures: Array):
	var main = Main.new()
	main.board = _board(fixtures)
	return main


## Player position + box positions + the full PRD state dict, as one value.
## Comparing this in a single `assert_eq` catches a divergence in any of them.
func _snapshot(board) -> Array:
	return [board.player, board.boxes.duplicate(), board.get_state()]


## THE T-006 Accept case: the handler called directly with each of the 4
## directions matches `try_move()` with the corresponding direction.
func test_handler_matches_try_move_for_each_direction() -> void:
	for direction in ALL_DIRECTIONS:
		var label: String = DIRECTION_NAMES[direction]
		var main = _main([ROOM])
		var reference = _board([ROOM])

		var handled: bool = main._on_direction_input(direction)
		var direct: bool = reference.try_move(direction)

		assert_eq(handled, direct, "%s: handler and try_move agree on the return" % label)
		assert_true(handled, "%s: is a legal move in this fixture" % label)
		assert_eq(
			_snapshot(main.board),
			_snapshot(reference),
			"%s: player/box positions and state match try_move" % label
		)
		main.free()


## The handler must also match on moves the rules REFUSE — a parity test that
## only ever compares successful moves is half a test.
func test_handler_matches_try_move_on_blocked_moves() -> void:
	# LEFT and UP walk into a wall; RIGHT is a push with a wall behind the box.
	for direction in [0, 2, 3]:
		var label: String = DIRECTION_NAMES[direction]
		var main = _main([BLOCKED])
		var reference = _board([BLOCKED])

		var handled: bool = main._on_direction_input(direction)
		var direct: bool = reference.try_move(direction)

		assert_false(handled, "%s: blocked move is refused" % label)
		assert_eq(handled, direct, "%s: handler and try_move agree on the refusal" % label)
		assert_eq(_snapshot(main.board), _snapshot(reference), "%s: state matches try_move" % label)
		assert_eq(main.board.moves_taken, 0, "%s: a refused move costs nothing" % label)
		main.free()


## Parity has to hold over a sequence, not just the first move — and it is
## checked after EVERY step, not only at the end.
func test_handler_sequence_matches_try_move_sequence() -> void:
	var sequence := [0, 3, 3, 1, 2, 1]
	var main = _main([ROOM])
	var reference = _board([ROOM])

	for step in range(sequence.size()):
		var direction: int = sequence[step]
		var handled: bool = main._on_direction_input(direction)
		var direct: bool = reference.try_move(direction)
		assert_eq(handled, direct, "step %d (%s): same return" % [step, DIRECTION_NAMES[direction]])
		assert_eq(_snapshot(main.board), _snapshot(reference), "step %d: same state" % step)

	assert_ne(main.board.moves_taken, 0, "the sequence really moved something")
	main.free()


## The key -> direction mapping table, in one assertion (T-006 Accept). Read
## through `direction_for_key()` — the same function `_unhandled_input()` uses —
## and compared as an Array so this is a single value comparison.
func test_key_to_direction_table() -> void:
	var keys := [KEY_UP, KEY_W, KEY_DOWN, KEY_S, KEY_LEFT, KEY_A, KEY_RIGHT, KEY_D]
	assert_eq(
		keys.map(func(key): return Main.direction_for_key(key)),
		[0, 0, 1, 1, 2, 2, 3, 3],
		"arrow keys + WASD map to the PRD action ids 0=up 1=down 2=left 3=right"
	)


## An unbound key yields the sentinel, and the handler survives being called
## with it (board.gd treats an out-of-range direction as a no-op, not an error).
func test_unmapped_key_yields_no_direction() -> void:
	assert_eq(Main.direction_for_key(KEY_Q), Main.NO_DIRECTION, "Q is not bound")
	assert_eq(Main.direction_for_key(KEY_SPACE), Main.NO_DIRECTION, "space is not bound")

	var main = _main([ROOM])
	var before := _snapshot(main.board)
	assert_false(main._on_direction_input(Main.NO_DIRECTION), "sentinel is refused")
	assert_eq(_snapshot(main.board), before, "sentinel changed nothing")
	main.free()


## Calling the handler before a board exists must not crash — `_ready()` bails
## out without a board when the levels fail to load.
func test_handler_is_a_noop_without_a_board() -> void:
	var main = Main.new()
	assert_null(main.board, "no board yet")
	assert_false(main._on_direction_input(0), "handler refuses without a board")
	main.free()


## The sprite-snapping rule itself, with no nodes involved: a cell always maps
## to an exact multiple of CELL_SIZE.
func test_cell_to_position_snaps_to_the_grid() -> void:
	assert_eq(Main.cell_to_position(Vector2i(0, 0)), Vector2(0, 0), "origin cell")
	assert_eq(
		Main.cell_to_position(Vector2i(3, 2)),
		Vector2(3 * Main.CELL_SIZE, 2 * Main.CELL_SIZE),
		"a cell maps to an exact CELL_SIZE multiple"
	)


## The one case that touches nodes: after a handler move the player and box
## sprites sit exactly on their new cells.
func test_view_snaps_sprites_on_move() -> void:
	var main = _main([ROOM])
	main.build_view()
	assert_not_null(main.player_node, "view built a player sprite")
	assert_eq(main.box_nodes.size(), main.board.boxes.size(), "one sprite per box")

	# RIGHT is a push in ROOM: player (2,2) -> (3,2), box (3,2) -> (4,2), so
	# BOTH a player sprite and a box sprite have to be re-snapped.
	assert_true(main._on_direction_input(3), "the push happened")
	assert_eq(main.board.player, Vector2i(3, 2), "player advanced")
	assert_eq(main.board.boxes[0], Vector2i(4, 2), "box was pushed")

	assert_eq(
		main.player_node.position, Main.cell_to_position(main.board.player), "player sprite snapped"
	)
	for i in range(main.box_nodes.size()):
		assert_eq(
			main.box_nodes[i].position,
			Main.cell_to_position(main.board.boxes[i]),
			"box %d sprite snapped" % i
		)
	main.free()


## A level advance driven through the handler must match the same sequence
## driven through `try_move()` — the handler must neither swallow nor duplicate
## `board.gd`'s lazy advance.
func test_handler_drives_a_level_advance() -> void:
	var sequence := [3, 3]  # solves ONE_BOX, then the advance move lands in NEXT_LEVEL
	var main = _main([ONE_BOX, NEXT_LEVEL])
	var reference = _board([ONE_BOX, NEXT_LEVEL])

	for step in range(sequence.size()):
		var handled: bool = main._on_direction_input(sequence[step])
		var direct: bool = reference.try_move(sequence[step])
		assert_eq(handled, direct, "advance step %d: same return" % step)
		assert_eq(_snapshot(main.board), _snapshot(reference), "advance step %d: same state" % step)

	assert_eq(main.board.level_index, 1, "the handler really crossed into level 1")
	main.free()
