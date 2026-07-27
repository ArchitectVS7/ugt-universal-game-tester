extends "res://tests/assertions.gd"
## T-006 — the human input front end (`res://scripts/main.gd`).
##
## What this file proves: routing an action through `Main._on_action_input()`
## produces EXACTLY the state that calling the board directly with the same
## action produces — i.e. the input layer adds no rule of its own, which is
## the standing constraint ("all push/collision/win rules live in `board.gd`").
## Every parity case therefore runs the SAME fixture down two paths and
## compares player position, box positions and the PRD state dictionary.
##
## The last six cases cover the WIN STATE, which is the front end's own
## behaviour rather than a parity claim: the board's `all_levels_solved` freeze
## is deliberate and tested elsewhere, and what these pin is that the freeze is
## *visible* — entered exactly once, only on `all_levels_solved` (not on a
## solved level), entered even when the setting move returns false, painted as
## colour and geometry with no text node anywhere, persisting while frozen, and
## cleared by a reload that the board then accepts moves on again.
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
## `[ONE_BOX, NEXT_LEVEL]` + `[3, 3, 3]` is the shortest two-level FINISH:
## step 1 solves level 1, step 2 lazily advances and pushes in level 2, step 3
## solves the last level and sets `all_levels_solved`.
const NEXT_LEVEL := ["######", "#@$ .#", "######"]

## 4x3 · player (1,1) · one crate already standing on its only target at (2,1),
## so the board is `is_solved()` the moment it loads. Used to reach `board.gd`'s
## "last level was already solved at load time" branch, where the move that sets
## `all_levels_solved` RETURNS FALSE.
const PRE_SOLVED := ["####", "#@*#", "####"]

## 7x3 · player (1,1) · crates (2,1) and (4,1) · targets (3,1) and (5,1). One
## RIGHT parks crate 0 on a target while the level as a whole stays unsolved.
const TWO_BOXES := ["#######", "#@$.$.#", "#######"]

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

		var handled: bool = main._on_action_input(direction)
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

		var handled: bool = main._on_action_input(direction)
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
		var handled: bool = main._on_action_input(direction)
		var direct: bool = reference.try_move(direction)
		assert_eq(handled, direct, "step %d (%s): same return" % [step, DIRECTION_NAMES[direction]])
		assert_eq(_snapshot(main.board), _snapshot(reference), "step %d: same state" % step)

	assert_ne(main.board.moves_taken, 0, "the sequence really moved something")
	main.free()


## The key -> action mapping table, in one assertion (T-006 Accept). Read
## through `action_for_key()` — the same function `_unhandled_input()` uses —
## and compared as an Array so this is a single value comparison.
func test_key_to_action_table() -> void:
	var keys := [KEY_UP, KEY_W, KEY_DOWN, KEY_S, KEY_LEFT, KEY_A, KEY_RIGHT, KEY_D, KEY_R]
	assert_eq(
		keys.map(func(key): return Main.action_for_key(key)),
		[0, 0, 1, 1, 2, 2, 3, 3, 4],
		"arrow keys + WASD map to 0=up 1=down 2=left 3=right, and R to 4=reset_level"
	)


## Pressing R mid-level rewinds the level to its start — the PRD's "a player
## can always retry", and the affordance a wedged box makes necessary. Parity
## with the board's own `apply_action()` is asserted the same way as a move.
func test_r_key_reloads_the_level() -> void:
	var main = _main([ROOM])
	var reference = _board([ROOM])
	var start := _snapshot(main.board)

	for direction in [3, 1]:  # push the box right, then step down — real changes
		main._on_action_input(direction)
		reference.apply_action(direction)
	assert_ne(_snapshot(main.board), start, "the setup really changed state")

	var handled: bool = main._on_action_input(Board.ACTION_RELOAD)
	var direct: bool = reference.apply_action(Board.ACTION_RELOAD)
	assert_eq(handled, direct, "reload: handler and apply_action agree on the return")
	assert_eq(_snapshot(main.board), _snapshot(reference), "reload: same state down both paths")
	assert_eq(_snapshot(main.board), start, "reload rewound the level to its start")
	assert_eq(main.board.moves_taken, 0, "reload zeroed moves_taken")
	main.free()


## An unbound key yields the sentinel, and the handler survives being called
## with it (board.gd treats an out-of-range action as a no-op, not an error).
func test_unmapped_key_yields_no_action() -> void:
	assert_eq(Main.action_for_key(KEY_Q), Main.NO_ACTION, "Q is not bound")
	assert_eq(Main.action_for_key(KEY_SPACE), Main.NO_ACTION, "space is not bound")

	var main = _main([ROOM])
	var before := _snapshot(main.board)
	assert_false(main._on_action_input(Main.NO_ACTION), "sentinel is refused")
	assert_eq(_snapshot(main.board), before, "sentinel changed nothing")
	main.free()


## Calling the handler before a board exists must not crash — `_ready()` bails
## out without a board when the levels fail to load.
func test_handler_is_a_noop_without_a_board() -> void:
	var main = Main.new()
	assert_null(main.board, "no board yet")
	assert_false(main._on_action_input(0), "handler refuses without a board")
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
	assert_true(main._on_action_input(3), "the push happened")
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
		var handled: bool = main._on_action_input(sequence[step])
		var direct: bool = reference.try_move(sequence[step])
		assert_eq(handled, direct, "advance step %d: same return" % step)
		assert_eq(_snapshot(main.board), _snapshot(reference), "advance step %d: same state" % step)

	assert_eq(main.board.level_index, 1, "the handler really crossed into level 1")
	main.free()


## Drives the two-level fixture to its finish and asserts the win state after
## EVERY step. The half that matters most is the middle: solving a level is not
## winning the game, so `level_solved` must not enter the win state.
func test_win_state_is_entered_only_on_all_levels_solved() -> void:
	var main = _main([ONE_BOX, NEXT_LEVEL])
	assert_eq(main.win_state_entries, 0, "no win state before a move")
	assert_false(main.win_state_active, "no win state before a move")

	assert_true(main._on_action_input(3), "step 1: the solving push in level 1")
	var after_first: Dictionary = main.board.get_state()
	assert_true(after_first["level_solved"], "step 1 solved level 1")
	assert_false(after_first["all_levels_solved"], "but there is another level to play")
	assert_eq(main.win_state_entries, 0, "a solved LEVEL is not the win state")
	assert_false(main.win_state_active, "a solved LEVEL is not the win state")

	assert_true(main._on_action_input(3), "step 2: the advance move, applied in level 2")
	assert_eq(main.board.level_index, 1, "step 2 crossed into the last level")
	assert_false(main.board.all_levels_solved, "level 2 is not solved yet")
	assert_eq(main.win_state_entries, 0, "still no win state")
	assert_false(main.win_state_active, "still no win state")

	assert_true(main._on_action_input(3), "step 3: the solving push in the last level")
	assert_true(main.board.all_levels_solved, "the game is finished")
	assert_eq(main.win_state_entries, 1, "the win state was entered")
	assert_true(main.win_state_active, "the win state is showing")
	main.free()


## The frozen board must not keep re-entering the win state. Every refused
## action is checked on a whole-state snapshot as well as on the counter, so a
## board that quietly changed while looking frozen is caught too.
func test_win_state_is_entered_exactly_once() -> void:
	var main = _main([ONE_BOX, NEXT_LEVEL])
	for direction in [3, 3, 3]:
		main._on_action_input(direction)
	assert_true(main.board.all_levels_solved, "the fixture really finished")
	var won := _snapshot(main.board)

	for action in [0, 1, 2, 3, Main.NO_ACTION]:
		assert_false(main._on_action_input(action), "action %d is refused on a won board" % action)
		assert_eq(_snapshot(main.board), won, "action %d changed nothing" % action)
		assert_eq(main.win_state_entries, 1, "action %d did not re-enter the win state" % action)
		assert_true(main.win_state_active, "action %d: the win state persists" % action)
	main.free()


## The PRD's "a player can always retry" has to hold AFTER the game is won. The
## un-freeze is proven by a move being accepted, not by reading a flag — and
## re-solving must count a SECOND entry, which is what makes the "exactly once"
## case above a real edge trigger rather than a value latched at 1.
func test_reload_clears_the_win_state_and_un_freezes_the_board() -> void:
	var main = _main([ONE_BOX, NEXT_LEVEL])
	for direction in [3, 3, 3]:
		main._on_action_input(direction)
	assert_true(main.win_state_active, "the fixture really won")

	assert_true(main._on_action_input(Board.ACTION_RELOAD), "reload is accepted")
	assert_false(main.board.all_levels_solved, "reload cleared the frozen flag")
	assert_false(main.win_state_active, "reload cleared the win state")
	assert_eq(main.win_state_entries, 1, "leaving the win state is not an entry")
	assert_eq(main.board.level_index, 1, "reload retries the LAST level, not the game")

	assert_true(main._on_action_input(3), "the board accepts moves again")
	assert_false(main.win_state_active, "one push is not a win")
	assert_true(main._on_action_input(3), "the re-solving push")
	assert_true(main.board.all_levels_solved, "the last level is solved again")
	assert_eq(main.win_state_entries, 2, "re-winning enters the win state a second time")
	assert_true(main.win_state_active, "and it is showing again")
	main.free()


## `board.gd`'s "last level was already solved at load time" branch sets
## `all_levels_solved` and returns FALSE. The win state must still be entered —
## it hangs off the board's flag, never off the handler's return value.
func test_win_state_is_entered_on_a_refused_move_when_the_board_loads_solved() -> void:
	var main = _main([PRE_SOLVED])
	assert_true(main.board.is_solved(), "the fixture ships its crate on the target")
	assert_false(main.board.all_levels_solved, "the flag is not set until a move asks")

	assert_false(main._on_action_input(3), "board.gd refuses that move")
	assert_true(main.board.all_levels_solved, "...and sets the finished flag on the way out")
	assert_true(main.win_state_active, "the win state does not hang off the return value")
	assert_eq(main.win_state_entries, 1, "entered exactly once")
	main.free()


## The win state as a HUMAN sees it — colour and geometry, no text anywhere. All
## three signals are asserted on the winning move, asserted to PERSIST across a
## frozen press (the "does not read as hung" half), and asserted to REVERT on a
## reload.
func test_view_paints_the_win_state_and_reverts_on_reload() -> void:
	var main = _main([ONE_BOX, NEXT_LEVEL])
	main.build_view()

	assert_eq(main.backdrop_node.color, Main.COLOR_FLOOR, "idle backdrop")
	assert_false(main.win_frame_node.visible, "no win frame before the win")
	assert_eq(main.box_nodes[0].color, Main.COLOR_BOX, "idle crate colour")

	# The frame is a real ring around the board, not a zero-size node that would
	# make "visible" a meaningless assertion.
	var inset := Vector2(Main.WIN_FRAME_THICKNESS, Main.WIN_FRAME_THICKNESS)
	assert_eq(main.win_frame_node.position, -inset, "the frame starts outside the grid")
	assert_eq(
		main.win_frame_node.size,
		main.backdrop_node.size + inset * 2.0,
		"the frame is thicker than the board on every side"
	)

	# Step 2 crosses a level boundary, which REBUILDS the view — so every
	# assertion below re-reads `main.<node>` rather than caching a reference.
	for direction in [3, 3, 3]:
		main._on_action_input(direction)
	assert_true(main.board.all_levels_solved, "the fixture really finished")
	assert_eq(main.backdrop_node.color, Main.COLOR_FLOOR_WON, "the won backdrop is painted")
	assert_true(main.win_frame_node.visible, "the win frame is shown")
	assert_eq(main.box_nodes[0].color, Main.COLOR_BOX_ON_TARGET, "the finished crate is marked")

	assert_false(main._on_action_input(3), "the board is frozen")
	assert_eq(main.backdrop_node.color, Main.COLOR_FLOOR_WON, "the won backdrop persists")
	assert_true(main.win_frame_node.visible, "the win frame persists")
	assert_eq(main.box_nodes[0].color, Main.COLOR_BOX_ON_TARGET, "the crate marking persists")

	main._on_action_input(Board.ACTION_RELOAD)
	assert_eq(main.backdrop_node.color, Main.COLOR_FLOOR, "reload reverted the backdrop")
	assert_false(main.win_frame_node.visible, "reload hid the win frame")
	assert_eq(main.box_nodes[0].color, Main.COLOR_BOX, "reload reverted the crate colour")
	main.free()


## A crate standing on a target is marked per-crate, off the board's own render —
## not off the win state. Without this the human cannot see the game's objective
## at all: the full-cell crate rect covers the target pip completely.
func test_crate_colour_marks_a_crate_standing_on_a_target() -> void:
	var main = _main([TWO_BOXES])
	main.build_view()
	assert_eq(main.box_nodes.size(), 2, "the fixture ships two crates")

	assert_true(main._on_action_input(3), "the push happened")
	assert_eq(main.board.boxes[0], Vector2i(3, 1), "crate 0 landed on the target at (3,1)")
	assert_eq(main.box_nodes[1].color, Main.COLOR_BOX, "crate 1 is still on floor")
	assert_eq(main.box_nodes[0].color, Main.COLOR_BOX_ON_TARGET, "crate 0 is marked as done")
	assert_false(main.board.all_levels_solved, "one crate of two is not a win")
	assert_false(main.win_frame_node.visible, "so there is no win frame")
	main.free()
