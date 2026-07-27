extends "res://tests/assertions.gd"
## The committed solutions are the SHORTEST possible — proven by search.
##
## `tests/test_shipped_levels.gd` pins three properties of each sequence in
## `res://levels/solutions.json`: it SOLVES its level, it is UNPADDED
## (`moves_taken == actions.size()`), and it does NOT solve early. None of those
## is minimality — a shorter solution could exist for any level and every one of
## those cases would stay green. This suite closes that gap: it computes the true
## shortest solution per level by breadth-first search and asserts it equals the
## length of the committed sequence.
##
## WHY THIS LIVES IN THE GAME AND NOT IN THE TESTER. Minimality is a claim about
## authored CONTENT, so it is the game's to prove; a solver in the test harness
## would be a second rules engine sitting next to the one it is meant to check.
##
## THE SEARCH DRIVES `board.gd::try_move()` — IT DOES NOT RE-IMPLEMENT IT.
## A hand-rolled push/collision loop in here would be exactly the thing the
## project's standing constraint forbids: rules live in `try_move()` and nowhere
## else, so a search that used its own transition function would be answering a
## question about a copy of the game. Driving the real engine costs ~16 s for
## level_03 (see `SKIP_SLOW_ENV`), which is affordable, so there is no excuse.
##
## NO LEVEL GEOMETRY IS EMBEDDED FOR THE SHIPPED LEVELS — they are read from
## `res://levels/`, same as `test_shipped_levels.gd`. The small inline grids below
## are FIXTURES for the searcher itself: controls with hand-checkable answers, so
## that a searcher which under-reports (or silently reports "unsolvable") is red
## rather than quietly agreeing with whatever `solutions.json` happens to say.

const Board := preload("res://scripts/board.gd")
const Level := preload("res://scripts/level.gd")

const SOLUTIONS_PATH := "res://levels/solutions.json"

## The shipped level names, in play order. Paths are derived, never repeated.
const LEVEL_NAMES := ["level_01", "level_02", "level_03"]

## Search results RECORDED on 2026-07-26. The search below re-derives them on
## every unskipped run, so these can never drift silently — and they are never
## the primary claim. They exist so that the one case allowed to skip its search
## still has something to assert, and so that a change to `solutions.json` has to
## be acknowledged in two places.
const RECORDED_SHORTEST := {"level_01": 6, "level_02": 23, "level_03": 44}

## Set to any non-empty value to skip the one search that is slow enough to
## annoy a gate (level_03: ~7.7e5 states, ~16 s). Opt-OUT, never opt-in: nothing
## in the game's tooling, the tester's ladder or CI sets this. When it is set the
## level_03 case prints a loud SKIP line and falls back to the recorded length,
## so even the skipped path still catches a padded `solutions.json`.
const SKIP_SLOW_ENV := "SOKOBAN_SKIP_SLOW_TESTS"

## `_shortest()`'s length when the level is provably unsolvable (the search
## EXHAUSTED the reachable state space — it was never truncated).
const NO_SOLUTION := -1

## `_state_key()` packs a state into one 64-bit int as
## `box_mask * non_wall_count + player_index`, which is what makes level_03's
## search finish in seconds. It overflows silently past this many non-wall cells,
## and a wrong number from a test whose entire output is a number is the worst
## possible failure — so the capacity is asserted, loudly, before any search runs.
const MAX_NON_WALL_CELLS := 56


func _level_path(name: String) -> String:
	return "res://levels/%s.txt" % name


## Parsed `solutions.json`. A missing or malformed file must fail LOUDLY — never
## silently return `{}`, which would make every comparison below vacuous.
## (Deliberately a local copy of `test_shipped_levels.gd`'s reader rather than a
## shared helper: these two suites assert different things about the same file and
## are meant to be independently readable.)
func _solutions() -> Dictionary:
	var file := FileAccess.open(SOLUTIONS_PATH, FileAccess.READ)
	assert_not_null(file, "%s should exist and be readable" % SOLUTIONS_PATH)
	if file == null:
		return {}
	var text := file.get_as_text()
	file.close()

	var parsed = JSON.parse_string(text)
	assert_eq(typeof(parsed), TYPE_DICTIONARY, "%s should parse to a JSON object" % SOLUTIONS_PATH)
	if typeof(parsed) != TYPE_DICTIONARY:
		return {}
	return parsed


## The action ids for one level, coerced to `int` and validated.
func _actions(solutions: Dictionary, name: String) -> Array:
	assert_true(solutions.has(name), "solutions.json should contain '%s'" % name)
	if not solutions.has(name):
		return []

	var raw = solutions[name]
	assert_eq(typeof(raw), TYPE_ARRAY, "'%s' should be an array" % name)
	if typeof(raw) != TYPE_ARRAY:
		return []
	assert_true(raw.size() > 0, "'%s' solution should not be empty" % name)

	var actions: Array = []
	for i in range(raw.size()):
		var value = raw[i]
		var numeric := typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT
		assert_true(numeric, "'%s'[%d] should be a number, got %s" % [name, i, str(value)])
		if not numeric:
			continue
		var id := int(value)
		assert_eq(float(id), float(value), "'%s'[%d] should be a whole number" % [name, i])
		assert_true(id >= 0 and id <= 3, "'%s'[%d] = %d should be a PRD action id" % [name, i, id])
		actions.append(id)
	return actions


## A board holding exactly one shipped level, loaded from its real file.
func _board_for(name: String):
	var board := Board.new()
	assert_true(
		board.load_levels_from_paths([_level_path(name)]),
		"%s should load (%s)" % [name, board.error_message]
	)
	return board


## A board holding exactly one inline fixture level.
func _board_for_text(text: String):
	var board := Board.new()
	assert_true(board.load_levels_from_texts([text]), "fixture should load (%s)" % board.error_message)
	return board


## `{Vector2i: int}` over every non-wall cell of the level in play, in row-major
## order. Walls can hold neither a box nor the player, so they are not indexed —
## which is what keeps the state key inside 64 bits.
func _non_wall_index(level) -> Dictionary:
	var index := {}
	for y in range(level.height):
		for x in range(level.width):
			if level.tile_at(x, y) != Level.Tile.WALL:
				index[Vector2i(x, y)] = index.size()
	return index


## One state as a single int. The box component is a MASK, so it is independent
## of box order — two states differing only in which box sits where are the same
## position and must be visited once.
func _state_key(index: Dictionary, cell_count: int, player: Vector2i, boxes: Array) -> int:
	var mask := 0
	for box in boxes:
		mask |= 1 << int(index[box])
	return mask * cell_count + int(index[player])


## Breadth-first search for the shortest solution to the single level loaded on
## `board`, using `board.try_move()` as the transition function.
##
## Returns `{"length": int, "states": int, "ok": bool}`:
##  - `length` is the number of moves in a shortest solution, `0` if the level
##    ships solved, or `NO_SOLUTION` when the reachable space was EXHAUSTED with
##    no solved state in it. There is no node or depth cap, so `NO_SOLUTION`
##    always means "provably unsolvable" and never "gave up".
##  - `ok` is false only when the state key cannot represent this level, which is
##    recorded as a failure here rather than returned as an answer.
##
## Two subtleties about driving the real engine, both load-bearing:
##  - `all_levels_solved` is sticky and FREEZES `try_move()`. A previous probe
##    that happened to reach a solved position sets it, so it is cleared before
##    every probe.
##  - a solved state is never expanded (the search returns the moment one is
##    discovered), so `try_move()`'s lazy level-advance branch is unreachable from
##    here and a `false` return unambiguously means "the move was refused". That
##    is what lets `false` be treated as "no edge".
func _shortest(board) -> Dictionary:
	var level = board.current_level()
	assert_not_null(level, "the searcher needs a loaded level")
	if level == null:
		return {"length": NO_SOLUTION, "states": 0, "ok": false}

	var index := _non_wall_index(level)
	var cell_count: int = index.size()
	assert_true(
		cell_count <= MAX_NON_WALL_CELLS,
		(
			"this searcher's integer state key holds at most %d non-wall cells (this level has %d); a bigger level needs a PackedByteArray key"
			% [MAX_NON_WALL_CELLS, cell_count]
		)
	)
	if cell_count > MAX_NON_WALL_CELLS:
		return {"length": NO_SOLUTION, "states": 0, "ok": false}

	var start_player: Vector2i = board.player
	var start_boxes: Array = board.boxes.duplicate()
	if board.is_solved():
		return {"length": 0, "states": 1, "ok": true}

	var seen := {}
	seen[_state_key(index, cell_count, start_player, start_boxes)] = true
	var layer: Array = [[start_player, start_boxes]]
	var states := 1
	var depth := 0

	while not layer.is_empty():
		depth += 1
		var next_layer: Array = []
		for entry in layer:
			for direction in range(4):
				board.player = entry[0]
				# `try_move()` mutates `boxes` in place, so never hand it the
				# array the frontier is holding.
				board.boxes = entry[1].duplicate()
				board.all_levels_solved = false
				if not board.try_move(direction):
					continue
				var player: Vector2i = board.player
				var boxes: Array = board.boxes.duplicate()
				var key := _state_key(index, cell_count, player, boxes)
				if seen.has(key):
					continue
				seen[key] = true
				states += 1
				if board.is_solved():
					return {"length": depth, "states": states, "ok": true}
				next_layer.append([player, boxes])
		layer = next_layer

	return {"length": NO_SOLUTION, "states": states, "ok": true}


## Shortest solution length for an inline fixture, for the controls below.
func _shortest_for_text(text: String) -> int:
	var result := _shortest(_board_for_text(text))
	assert_true(result["ok"], "the fixture search should complete")
	if not result["ok"]:
		return NO_SOLUTION
	return int(result["length"])


func _skip_slow() -> bool:
	return not OS.get_environment(SKIP_SLOW_ENV).is_empty()


# --- Controls for the searcher itself -----------------------------------------
#
# Declared before the shipped-level cases so a broken searcher is reported as a
# broken searcher, above whatever it then says about the content.


## A level that ships solved needs zero moves, and must be recognised WITHOUT
## expanding anything — `try_move()` freezes on a solved board, so a searcher
## that tried to expand it would find no edges and wrongly report "unsolvable".
func test_search_returns_zero_for_a_level_that_starts_solved() -> void:
	assert_eq(_shortest_for_text("#####\n#@* #\n#####\n"), 0, "an already-solved level costs 0 moves")


## The smallest non-trivial case: one push, one move. Catches an off-by-one in
## the depth counter, which is otherwise invisible on longer levels.
func test_search_finds_a_one_move_solution() -> void:
	assert_eq(_shortest_for_text("#####\n#@$.#\n#####\n"), 1, "one push solves it")


func test_search_finds_a_two_move_solution() -> void:
	assert_eq(_shortest_for_text("######\n#@$ .#\n######\n"), 2, "two pushes solve it")


## The player starts BESIDE the crate on the wrong axis, so the crate cannot be
## pushed toward its target until the player has walked around it. Witness:
## `down, right, up, up`. A greedy "push toward the target" search gets this
## wrong; a correct BFS does not.
func test_search_counts_the_walk_around_a_crate() -> void:
	var fixture := "#######\n#  .  #\n#     #\n# @$  #\n#     #\n#######\n"
	assert_eq(_shortest_for_text(fixture), 4, "one walk-around plus two pushes")


## Two crates, so the search has to explore an ordering rather than a single
## push chain. Witness: `down, left, up, right, right, up, left, left`.
func test_search_handles_two_crates() -> void:
	var fixture := "######\n#. $ #\n#  @ #\n#.$  #\n######\n"
	assert_eq(_shortest_for_text(fixture), 8, "three pushes plus the walking between them")


## The crate is wall-flush on two sides with the player able to reach neither
## pushing cell, so NO sequence solves this level. The search must EXHAUST the
## space and say so — a searcher that reported `0` (or a length) here would make
## every optimality assertion below meaningless in the same way.
func test_search_reports_an_unsolvable_level_as_unsolvable() -> void:
	var fixture := "#####\n#$ .#\n#@  #\n#####\n"
	assert_eq(_shortest_for_text(fixture), NO_SOLUTION, "an unpushable crate is unsolvable")


# --- The shipped content ------------------------------------------------------


func test_level_01_committed_solution_is_the_shortest() -> void:
	_assert_committed_solution_is_shortest("level_01", false)


func test_level_02_committed_solution_is_the_shortest() -> void:
	_assert_committed_solution_is_shortest("level_02", false)


## The slow one — see `SKIP_SLOW_ENV`.
func test_level_03_committed_solution_is_the_shortest() -> void:
	_assert_committed_solution_is_shortest("level_03", true)


## Asserts the triple equality `search == committed == recorded` for one level.
## `slow` marks the case that `SKIP_SLOW_ENV` may drop the search from; the
## committed-vs-recorded half is asserted either way.
func _assert_committed_solution_is_shortest(name: String, slow: bool) -> void:
	var actions := _actions(_solutions(), name)
	if actions.is_empty():
		return  # `_actions()` already recorded the failure.

	assert_true(RECORDED_SHORTEST.has(name), "a recorded shortest length exists for %s" % name)
	if not RECORDED_SHORTEST.has(name):
		return
	var recorded: int = int(RECORDED_SHORTEST[name])
	assert_eq(actions.size(), recorded, "%s committed sequence is %d moves" % [name, recorded])

	if slow and _skip_slow():
		print(
			(
				"    SKIP %s shortest-solution search — %s is set; asserting the recorded length only"
				% [name, SKIP_SLOW_ENV]
			)
		)
		return

	var started := Time.get_ticks_msec()
	var result := _shortest(_board_for(name))
	var elapsed := Time.get_ticks_msec() - started
	assert_true(result["ok"], "%s search should complete" % name)
	if not result["ok"]:
		return

	var length: int = int(result["length"])
	print(
		(
			"    %s: shortest=%d committed=%d states=%d elapsed=%dms"
			% [name, length, actions.size(), int(result["states"]), elapsed]
		)
	)
	assert_ne(length, NO_SOLUTION, "%s must be solvable at all" % name)
	assert_eq(
		length,
		actions.size(),
		(
			"%s: the committed sequence should be a SHORTEST solution (search found %d moves, committed sequence is %d)"
			% [name, length, actions.size()]
		)
	)


## The recorded lengths above and the committed sequences cannot drift apart in
## silence — cheap, and it is what the skipped level_03 search falls back on.
func test_recorded_shortest_lengths_match_the_committed_solutions() -> void:
	var solutions := _solutions()
	var keys := RECORDED_SHORTEST.keys()
	keys.sort()
	var expected := LEVEL_NAMES.duplicate()
	expected.sort()
	assert_eq(keys, expected, "one recorded shortest length per shipped level")

	var total := 0
	for name in LEVEL_NAMES:
		if not RECORDED_SHORTEST.has(name):
			continue
		var actions := _actions(solutions, name)
		assert_eq(
			actions.size(),
			int(RECORDED_SHORTEST[name]),
			"%s: committed sequence length equals the recorded shortest" % name
		)
		total += actions.size()
	print("    committed reference total: %d moves" % total)
