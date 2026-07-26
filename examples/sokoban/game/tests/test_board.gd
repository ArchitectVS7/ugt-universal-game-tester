extends "res://tests/assertions.gd"
## T-004 — `try_move()` push/collision/win rules (`res://scripts/board.gd`).
##
## Fixtures are SMALL INLINE GRIDS defined here, never the shipped
## `res://levels/*.txt` — those are authored in T-005, and a rules test that
## depended on them could not run until then (and would fail for the wrong
## reason when a level is edited).
##
## Fixtures are arrays of row strings joined by `_grid()`, not triple-quoted
## literals: GDScript keeps a multi-line string's indentation tabs, which would
## inject tabs into the grid and produce phantom parse errors. Each fixture is
## annotated with the exact coordinates the tests assert on.
##
## Note every fixture obeys `level.gd`'s `boxes_total == targets_total` rule, so
## a fixture cannot accidentally load "half a level".

const Board := preload("res://scripts/board.gd")
const Level := preload("res://scripts/level.gd")

## 5x3 · player (1,1) · box (2,1) · target (3,1).
## Pushing RIGHT solves it in one move; UP / DOWN / LEFT are all wall-blocked.
const ONE_BOX := ["#####", "#@$.#", "#####"]

## 6x3 · player (1,1) · box (2,1) · target (4,1).
## Pushing RIGHT moves the box onto plain FLOOR (3,1) — a real move that does
## not solve the level.
const PUSH_FLOOR := ["######", "#@$ .#", "######"]

## 5x4 · player (1,1) · box (2,1) · wall at (3,1) · target (3,2).
## Pushing RIGHT is blocked by the wall BEHIND the box.
const PUSH_WALL_BEHIND := ["#####", "#@$##", "#  .#", "#####"]

## 7x4 · player (1,1) · boxes (2,1) and (3,1) · targets (5,1) and (1,2).
## Pushing RIGHT is blocked by the second BOX behind the first.
const PUSH_BOX_BEHIND := ["#######", "#@$$ .#", "#. #  #", "#######"]

## 7x4 · player (1,1) · boxes (2,1) [on target] and (3,2) · targets (2,1), (5,1).
## Starts with 1 of 2 boxes on a target; pushing RIGHT shoves that box OFF its
## target onto floor (3,1).
const BOX_ON_TARGET := ["#######", "#@*  .#", "#  $  #", "#######"]

## 6x5 · player (1,1) · boxes (2,1) and (3,2) · targets (4,1) and (3,3).
## Solved by RIGHT, RIGHT, DOWN (see SOLVE_TWO_SOLUTION) — two boxes, so "the
## LAST box reaching a target is what sets level_solved" is a real assertion.
const SOLVE_TWO := ["######", "#@$ .#", "#  $ #", "#  . #", "######"]
const SOLVE_TWO_SOLUTION := [3, 3, 1]

## 5x5 · player (2,2) · box (3,1) · target (3,3) · open floor around the player,
## so all four directions are free moves. Used to pin the action-id table.
const ROOM := ["#####", "#  $#", "# @ #", "#  .#", "#####"]

## No '@' and no '+' — `level.gd` rejects it. Used to prove a bad level in the
## middle of a list fails the whole load.
const BAD_NO_PLAYER := ["#####", "#$. #", "#####"]


func _grid(rows: Array) -> String:
	var parts := PackedStringArray()
	for row in rows:
		parts.append(row)
	return "\n".join(parts)


## A board holding exactly `rows` as its only level. Asserts the fixture itself
## loaded, so a broken fixture fails loudly instead of silently no-op-ing every
## later assertion in the case.
func _board(rows: Array):
	var board := Board.new()
	assert_true(board.load_levels_from_texts([_grid(rows)]), "fixture should load")
	return board


func _board_of(fixtures: Array):
	var texts: Array = []
	for rows in fixtures:
		texts.append(_grid(rows))
	var board := Board.new()
	assert_true(board.load_levels_from_texts(texts), "fixtures should load")
	return board


func test_fresh_board_starts_at_the_level_start() -> void:
	var board = _board(ONE_BOX)
	assert_eq(board.level_index, 0, "starts on level 0")
	assert_eq(board.player, Vector2i(1, 1), "player at the level's start cell")
	assert_eq(board.boxes.size(), 1, "one box")
	assert_eq(board.boxes[0], Vector2i(2, 1), "box at its start cell")
	assert_eq(board.moves_taken, 0, "no moves yet")
	assert_eq(board.boxes_on_target(), 0, "no box on a target yet")
	assert_false(board.is_solved(), "not solved at the start")
	assert_false(board.all_levels_solved, "not finished at the start")


## Accept: "wall blocks move".
func test_wall_blocks_move() -> void:
	var board = _board(ONE_BOX)
	assert_false(board.try_move(Board.Direction.UP), "wall above blocks the move")
	assert_eq(board.player, Vector2i(1, 1), "player did not move")
	assert_eq(board.moves_taken, 0, "a blocked move does not count")

	assert_false(board.try_move(Board.Direction.LEFT), "wall left blocks the move")
	assert_false(board.try_move(Board.Direction.DOWN), "wall below blocks the move")
	assert_eq(board.player, Vector2i(1, 1), "player still did not move")
	assert_eq(board.moves_taken, 0, "still no moves counted")


## Accept: "box pushes into floor".
func test_push_box_into_floor() -> void:
	var board = _board(PUSH_FLOOR)
	assert_true(board.try_move(Board.Direction.RIGHT), "push into floor succeeds")
	assert_eq(board.player, Vector2i(2, 1), "player took the box's cell")
	assert_eq(board.boxes[0], Vector2i(3, 1), "box advanced one cell")
	assert_eq(board.moves_taken, 1, "a real move counts once")
	assert_eq(board.boxes_on_target(), 0, "floor is not a target")
	assert_false(board.is_solved(), "pushing onto floor does not solve")


## Accept: "box push blocked by a wall behind it".
func test_push_blocked_by_wall_behind() -> void:
	var board = _board(PUSH_WALL_BEHIND)
	assert_false(board.try_move(Board.Direction.RIGHT), "wall behind the box blocks the push")
	assert_eq(board.player, Vector2i(1, 1), "player did not move")
	assert_eq(board.boxes[0], Vector2i(2, 1), "box did not move")
	assert_eq(board.moves_taken, 0, "a blocked push does not count")


## Accept: "box push blocked by another box behind it".
func test_push_blocked_by_box_behind() -> void:
	var board = _board(PUSH_BOX_BEHIND)
	assert_false(board.try_move(Board.Direction.RIGHT), "second box blocks the push")
	assert_eq(board.player, Vector2i(1, 1), "player did not move")
	assert_eq(board.boxes[0], Vector2i(2, 1), "first box did not move")
	assert_eq(board.boxes[1], Vector2i(3, 1), "second box did not move")
	assert_eq(board.moves_taken, 0, "a blocked push does not count")


## Accept: "a no-op move does not increment moves_taken".
func test_noop_move_does_not_increment_moves() -> void:
	var board = _board(ONE_BOX)
	board.try_move(Board.Direction.UP)
	board.try_move(Board.Direction.UP)
	board.try_move(Board.Direction.LEFT)
	assert_eq(board.moves_taken, 0, "three wall-blocked moves count zero")
	assert_eq(board.get_state()["moves_taken"], 0, "and the reported state agrees")


## Accept: "a real move does [increment moves_taken]".
func test_real_move_increments_moves() -> void:
	var board = _board(SOLVE_TWO)
	assert_true(board.try_move(Board.Direction.RIGHT), "push onto floor")
	assert_eq(board.moves_taken, 1, "first real move")
	assert_true(board.try_move(Board.Direction.RIGHT), "push onto the target")
	assert_eq(board.moves_taken, 2, "second real move")
	# One blocked move in between must not disturb the count.
	assert_false(board.try_move(Board.Direction.UP), "wall above")
	assert_eq(board.moves_taken, 2, "blocked move still does not count")


## Accept: "putting the last box on a target sets level_solved: true".
func test_last_box_on_target_solves_level() -> void:
	var board = _board(SOLVE_TWO)
	for direction in SOLVE_TWO_SOLUTION:
		assert_true(board.try_move(direction), "solution move %d applies" % direction)

	assert_eq(board.boxes_on_target(), board.boxes_total(), "every box is on a target")
	assert_eq(board.boxes_total(), 2, "the fixture really has two boxes")
	assert_true(board.is_solved(), "level is solved")

	var state: Dictionary = board.get_state()
	assert_true(state["level_solved"], "state reports level_solved")
	# The solving move must leave the SOLVED level observable — an eager advance
	# would already be showing the next (or a wrapped) level here.
	assert_eq(state["level_index"], 0, "still reporting the level that was solved")
	assert_eq(state["moves_taken"], 3, "three real moves")


func test_solving_the_second_to_last_box_does_not_solve_the_level() -> void:
	var board = _board(SOLVE_TWO)
	assert_true(board.try_move(Board.Direction.RIGHT), "first push")
	assert_true(board.try_move(Board.Direction.RIGHT), "second push lands box 1 on a target")
	assert_eq(board.boxes_on_target(), 1, "one of two boxes home")
	assert_false(board.is_solved(), "one box home is not solved")
	assert_false(board.get_state()["level_solved"], "state agrees it is unsolved")


func test_pushing_a_box_off_a_target_decrements_boxes_on_target() -> void:
	var board = _board(BOX_ON_TARGET)
	assert_eq(board.boxes_on_target(), 1, "fixture starts with one box on a target")
	assert_true(board.try_move(Board.Direction.RIGHT), "push the on-target box off it")
	assert_eq(board.boxes[0], Vector2i(3, 1), "box moved onto plain floor")
	assert_eq(board.boxes_on_target(), 0, "counter is live, not a sticky high-water mark")
	assert_false(board.is_solved(), "still unsolved")


## Pins the PRD action-id table `0=up, 1=down, 2=left, 3=right` in the one place
## it is allowed to live (T-006's key map and T-007's wire both defer to it).
func test_direction_ids_match_the_prd() -> void:
	assert_eq(Board.Direction.UP, 0, "up is 0")
	assert_eq(Board.Direction.DOWN, 1, "down is 1")
	assert_eq(Board.Direction.LEFT, 2, "left is 2")
	assert_eq(Board.Direction.RIGHT, 3, "right is 3")

	var expected := {0: Vector2i(2, 1), 1: Vector2i(2, 3), 2: Vector2i(1, 2), 3: Vector2i(3, 2)}
	for direction in expected:
		var board = _board(ROOM)
		assert_eq(board.player, Vector2i(2, 2), "room player start")
		assert_true(board.try_move(direction), "direction %d is a free move" % direction)
		assert_eq(board.player, expected[direction], "player cell after direction %d" % direction)
		assert_eq(board.moves_taken, 1, "one move counted")


## Pre-satisfies T-007's Accept: an out-of-range `action_id` is a no-op, never an
## error or a crash — the bridge passes the wire value straight through.
func test_out_of_range_direction_is_a_noop() -> void:
	var board = _board(SOLVE_TWO)
	for direction in [-1, 4, 99]:
		assert_false(board.try_move(direction), "direction %d is rejected" % direction)
	assert_eq(board.player, Vector2i(1, 1), "player unchanged")
	assert_eq(board.boxes[0], Vector2i(2, 1), "boxes unchanged")
	assert_eq(board.moves_taken, 0, "no move counted")


func test_level_advances_after_a_solve() -> void:
	var board = _board_of([ONE_BOX, PUSH_FLOOR])
	assert_eq(board.level_count(), 2, "two levels loaded")

	assert_true(board.try_move(Board.Direction.RIGHT), "solve level 0 in one push")
	assert_eq(board.level_index, 0, "the solving move still reports level 0")
	assert_true(board.get_state()["level_solved"], "level 0 solved")
	assert_false(board.all_levels_solved, "but the game is not over")

	# The advance happens at the START of the next move, and that same move is
	# then applied in the new level (no filler move needed).
	assert_true(board.try_move(Board.Direction.RIGHT), "next move runs in level 1")
	assert_eq(board.level_index, 1, "now on level 1")
	assert_eq(board.player, Vector2i(2, 1), "level 1 player moved by the same action")
	assert_eq(board.boxes[0], Vector2i(3, 1), "level 1 box was pushed")
	assert_false(board.get_state()["level_solved"], "level 1 is not solved")


## Design decision pinned: `moves_taken` counts the whole session and is NOT
## zeroed by a level advance (only `reset_level()` zeroes it). The integration's
## R3 invariant is "moves_taken never decreases", and one connection drives all
## three levels back to back.
func test_moves_taken_survives_a_level_advance() -> void:
	var board = _board_of([ONE_BOX, PUSH_FLOOR])
	assert_true(board.try_move(Board.Direction.RIGHT), "solve level 0")
	assert_eq(board.moves_taken, 1, "one move so far")
	assert_true(board.try_move(Board.Direction.RIGHT), "first move of level 1")
	assert_eq(board.moves_taken, 2, "counter carried across the advance")


func test_all_levels_solved_after_the_last_level() -> void:
	var board = _board_of([ONE_BOX, ONE_BOX])
	assert_true(board.try_move(Board.Direction.RIGHT), "solve level 0")
	assert_false(board.all_levels_solved, "one of two levels done")
	assert_true(board.try_move(Board.Direction.RIGHT), "advance and solve level 1")
	assert_eq(board.level_index, 1, "on the last level")
	assert_true(board.is_solved(), "last level solved")
	assert_true(board.all_levels_solved, "all levels solved")
	assert_true(board.get_state()["all_levels_solved"], "state agrees")

	# Frozen: further moves change nothing at all (the bridge reports this as
	# `terminated`).
	var before: Dictionary = board.get_state()
	for direction in [0, 1, 2, 3]:
		assert_false(board.try_move(direction), "direction %d after the end" % direction)
	assert_eq(board.get_state(), before, "state is unchanged after the end")


func test_reset_level_restores_the_current_level() -> void:
	var board = _board(SOLVE_TWO)
	assert_true(board.try_move(Board.Direction.RIGHT), "push")
	assert_true(board.try_move(Board.Direction.RIGHT), "push again")
	assert_ne(board.player, Vector2i(1, 1), "board really moved before the reset")

	board.reset_level()
	assert_eq(board.player, Vector2i(1, 1), "player back at the start")
	assert_eq(board.boxes[0], Vector2i(2, 1), "first box back at the start")
	assert_eq(board.boxes[1], Vector2i(3, 2), "second box back at the start")
	assert_eq(board.moves_taken, 0, "move counter cleared")
	assert_eq(board.level_index, 0, "still the same level")


## A reset retries the level being played — it does not restart the game — and
## it un-freezes a finished board.
func test_reset_keeps_the_level_index_and_unfreezes() -> void:
	var board = _board_of([ONE_BOX, SOLVE_TWO])
	assert_true(board.try_move(Board.Direction.RIGHT), "solve level 0")
	assert_true(board.try_move(Board.Direction.RIGHT), "advance into level 1")
	assert_eq(board.level_index, 1, "on level 1")

	board.reset_level()
	assert_eq(board.level_index, 1, "reset stays on level 1")
	assert_eq(board.player, Vector2i(1, 1), "level 1 player back at its start")
	assert_eq(board.moves_taken, 0, "move counter cleared")

	var finished = _board(ONE_BOX)
	assert_true(finished.try_move(Board.Direction.RIGHT), "solve the only level")
	assert_true(finished.all_levels_solved, "board is finished")
	finished.reset_level()
	assert_false(finished.all_levels_solved, "reset un-freezes the board")
	assert_true(finished.try_move(Board.Direction.RIGHT), "and moves work again")


## The PRD's "UGT hooks" state block, made executable: `ugt_bridge.gd` (T-007)
## JSON-encodes this dictionary untouched, so a renamed or extra key is a wire
## break.
func test_get_state_matches_the_prd_shape() -> void:
	var board = _board(PUSH_FLOOR)
	var state: Dictionary = board.get_state()

	var keys := state.keys()
	keys.sort()
	var expected := [
		"all_levels_solved",
		"boxes_on_target",
		"boxes_total",
		"level_index",
		"level_solved",
		"moves_taken",
		"player_x",
		"player_y",
	]
	assert_eq(keys, expected, "exactly the PRD's keys, no more and no fewer")

	var int_keys := [
		"level_index",
		"player_x",
		"player_y",
		"boxes_on_target",
		"boxes_total",
		"moves_taken",
	]
	for key in int_keys:
		assert_eq(typeof(state[key]), TYPE_INT, "%s is an int" % key)
	for key in ["level_solved", "all_levels_solved"]:
		assert_eq(typeof(state[key]), TYPE_BOOL, "%s is a bool" % key)

	assert_eq(state["level_index"], 0, "level_index")
	assert_eq(state["player_x"], 1, "player_x")
	assert_eq(state["player_y"], 1, "player_y")
	assert_eq(state["boxes_total"], 1, "boxes_total")


## The PRD's determinism criterion at the rules layer: same level + same actions
## from a reset reproduces identical state.
func test_same_actions_after_reset_reproduce_identical_state() -> void:
	var board = _board(SOLVE_TWO)
	for direction in SOLVE_TWO_SOLUTION:
		board.try_move(direction)
	var first: Dictionary = board.get_state()

	board.reset_level()
	for direction in SOLVE_TWO_SOLUTION:
		board.try_move(direction)
	assert_eq(board.get_state(), first, "replay reproduces identical state")


func test_a_bad_level_fails_the_whole_load() -> void:
	var board := Board.new()
	var texts := [_grid(ONE_BOX), _grid(BAD_NO_PLAYER)]
	assert_false(board.load_levels_from_texts(texts), "one bad level fails the load")
	assert_eq(board.error_code, Level.ERR_NO_PLAYER, "the loader's own error code is propagated")
	assert_true(board.error_message.contains("1"), "message names the offending level index")

	# No half-built board: the good level must not survive either.
	assert_eq(board.level_count(), 0, "no levels loaded")
	assert_eq(board.boxes.size(), 0, "no boxes")
	assert_eq(board.boxes_total(), 0, "no box total")
	assert_false(board.is_solved(), "an empty board is never solved")
	assert_false(board.try_move(Board.Direction.RIGHT), "moves do nothing on an empty board")


func test_empty_level_list_is_an_error() -> void:
	var board := Board.new()
	assert_false(board.load_levels_from_texts([]), "a board with no levels is an error")
	assert_eq(board.error_code, Board.ERR_NO_LEVELS, "error code")
	assert_false(board.error_message.is_empty(), "message is not empty")


## `load_levels_from_paths` is what the game and the bridge use. Asserting the
## MISSING-file path keeps this test independent of T-005's level files.
func test_missing_level_file_is_an_error() -> void:
	var board := Board.new()
	assert_false(
		board.load_levels_from_paths(["res://levels/does_not_exist.txt"]), "missing file fails"
	)
	assert_eq(board.error_code, Level.ERR_FILE_NOT_FOUND, "error code")
	assert_eq(board.level_count(), 0, "nothing loaded")
