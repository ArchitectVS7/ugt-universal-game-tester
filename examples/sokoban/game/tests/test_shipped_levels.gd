extends "res://tests/assertions.gd"
## T-005 — the three SHIPPED levels + their committed solutions.
##
## Unlike `tests/test_board.gd`, which deliberately uses small inline fixtures so
## the rules engine can be tested without depending on content, this suite reads
## the real files under `res://levels/` and REPLAYS the committed action
## sequences in `res://levels/solutions.json` through `board.gd::try_move()`.
## That is the point of the task: "all 3 levels are solvable (a documented
## solution move sequence exists for each)" is an EXECUTED claim, not a
## hand-traced one. A wrong grid or a wrong action id turns this suite red.
##
## NO LEVEL GEOMETRY IS EMBEDDED HERE — only file paths and structural
## relationships (box count, relative grid size). Levels are plain-text data
## files per the standing constraint; a copy of a grid in a `.gd` file would
## silently stop tracking the file the game actually loads.
##
## `solutions.json` is a flat `{"level_01": [0, 3, ...], ...}` map of PRD action
## ids (`0=up, 1=down, 2=left, 3=right`) with no nesting and no metadata,
## because T-008's TCP smoke check `json.load`s the very same file and replays
## the very same sequences over the real wire. Keep the shape flat.

const Board := preload("res://scripts/board.gd")
const Level := preload("res://scripts/level.gd")

const SOLUTIONS_PATH := "res://levels/solutions.json"

## The shipped level names, in play order. The PATHS themselves are not repeated
## here — `_level_path()` derives them, and `board.gd::DEFAULT_LEVEL_PATHS` is
## asserted against them so a rename cannot pass unnoticed.
const LEVEL_NAMES := ["level_01", "level_02", "level_03"]


func _level_path(name: String) -> String:
	return "res://levels/%s.txt" % name


## Parsed `solutions.json`. A missing or malformed file must fail LOUDLY — never
## silently return `{}`, which would make every replay below vacuously pass on an
## empty action list.
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


## The action ids for one level, coerced to `int`.
##
## The coercion is deliberate and checked: Godot's JSON parser may hand a number
## back as a float, and `try_move(direction: int)` plus its
## `direction >= DIRECTION_VECTORS.size()` bounds check must never be fed one.
## The losslessness assertion means a stray `2.5` in the file is a RED test
## rather than a silent floor to a legal-looking action.
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


func _replay(board, actions: Array) -> void:
	for action in actions:
		board.try_move(action)


## A board holding exactly one shipped level, loaded from its real file.
func _board_for(name: String):
	var board := Board.new()
	assert_true(
		board.load_levels_from_paths([_level_path(name)]),
		"%s should load (%s)" % [name, board.error_message]
	)
	return board


func test_solutions_file_holds_exactly_the_three_shipped_levels() -> void:
	var solutions := _solutions()
	var keys := solutions.keys()
	keys.sort()
	var expected := LEVEL_NAMES.duplicate()
	expected.sort()
	assert_eq(keys, expected, "one solution per shipped level, no more and no fewer")

	# `_actions()` carries the per-entry validation (array, non-empty, whole
	# numbers, ids within 0..3).
	for name in LEVEL_NAMES:
		var actions := _actions(solutions, name)
		assert_true(actions.size() > 0, "%s has a non-empty solution" % name)


## The shipped filenames really are what the game loads by default — a renamed
## or reordered level file must not be able to pass this suite while breaking the
## actual game.
func test_default_level_paths_are_the_shipped_files() -> void:
	var expected: Array = []
	for name in LEVEL_NAMES:
		expected.append(_level_path(name))
	assert_eq(Board.DEFAULT_LEVEL_PATHS, expected, "board.gd ships these three level files")


## Accept: "a test loads each shipped level through T-003's loader (0 errors)".
func test_each_shipped_level_loads_without_error() -> void:
	for name in LEVEL_NAMES:
		var level := Level.new()
		var path := _level_path(name)
		assert_true(level.load_from_file(path), "%s should load (%s)" % [name, level.error_message])
		assert_eq(level.error_code, "", "%s loads with no error code" % name)
		assert_true(level.error_message.is_empty(), "%s loads with no error message" % name)
		assert_true(level.is_valid(), "%s is valid" % name)


## PRD content rule: "increasing in box count (1 -> 2 -> 3 boxes) and grid size".
## Asserted as a RELATIONSHIP (strictly growing area) rather than literal
## dimensions, so this stays metadata about the files and not a second copy of
## their geometry.
func test_shipped_levels_grow_in_boxes_and_size() -> void:
	var previous_area := 0
	for i in range(LEVEL_NAMES.size()):
		var name: String = LEVEL_NAMES[i]
		var level := Level.new()
		assert_true(level.load_from_file(_level_path(name)), "%s should load" % name)
		assert_eq(level.boxes_total(), i + 1, "%s has %d box(es)" % [name, i + 1])
		var area := level.width * level.height
		assert_true(area > previous_area, "%s (area %d) is bigger than the previous" % [name, area])
		previous_area = area


## Anti-vacuity guard for the replays below: a level shipped already solved (a
## box authored as `*` on its only target) would "pass" its replay without the
## solution doing anything at all.
func test_no_shipped_level_starts_solved() -> void:
	for name in LEVEL_NAMES:
		var board = _board_for(name)
		assert_true(board.boxes_on_target() < board.boxes_total(), "%s starts unsolved" % name)
		assert_false(board.is_solved(), "%s is not solved at its start" % name)
		assert_false(board.get_state()["level_solved"], "%s state agrees" % name)


## Accept (level_01): replay the committed sequence through `try_move()` and
## assert `level_solved: true` at the end.
##
## The final action is applied separately so the test also proves the sequence is
## not padded past the win, and `moves_taken == actions.size()` proves every
## committed action is an EFFECTIVE move (no no-op filler).
func test_level_01_solution_solves_it() -> void:
	_assert_solution_solves("level_01")


func test_level_02_solution_solves_it() -> void:
	_assert_solution_solves("level_02")


func test_level_03_solution_solves_it() -> void:
	_assert_solution_solves("level_03")


func _assert_solution_solves(name: String) -> void:
	var actions := _actions(_solutions(), name)
	if actions.is_empty():
		return  # `_actions()` already recorded the failure.

	var board = _board_for(name)
	for i in range(actions.size() - 1):
		board.try_move(actions[i])
	assert_false(board.is_solved(), "%s is not solved before its final action" % name)

	assert_true(board.try_move(actions[actions.size() - 1]), "%s final action applies" % name)

	var state: Dictionary = board.get_state()
	assert_true(state["level_solved"], "%s reports level_solved after its solution" % name)
	assert_eq(state["boxes_on_target"], state["boxes_total"], "%s has every box home" % name)
	assert_eq(state["moves_taken"], actions.size(), "%s solution contains no no-op moves" % name)


## Accept: "`all_levels_solved: true` after the third".
##
## Drives ONE board through the default (shipped) level list with the three
## solutions concatenated and NO filler moves between them — which also pins
## `board.gd`'s lazy level-advance contract that T-008 replays over the wire: the
## first action of the next level's sequence is what triggers the advance, and is
## then applied inside the new level.
func test_all_three_shipped_levels_solved_on_one_board() -> void:
	var solutions := _solutions()
	var board := Board.new()
	assert_true(board.load_levels_from_paths(), "the shipped levels load (%s)" % board.error_message)
	assert_eq(board.level_count(), LEVEL_NAMES.size(), "three levels loaded")

	var total := 0
	for name in LEVEL_NAMES:
		var actions := _actions(solutions, name)
		total += actions.size()
		_replay(board, actions)

	var state: Dictionary = board.get_state()
	assert_true(state["all_levels_solved"], "every shipped level is solved")
	assert_true(state["level_solved"], "the last level is solved")
	assert_eq(state["level_index"], LEVEL_NAMES.size() - 1, "finished on the last level")
	assert_eq(state["moves_taken"], total, "every action across all three levels was a real move")


## The PRD's determinism criterion against real shipped content: same level +
## same action sequence from a `reset` reproduces identical state. (T-008 repeats
## this over the TCP wire.)
func test_reset_and_replay_reproduces_identical_state() -> void:
	var actions := _actions(_solutions(), "level_01")
	var board = _board_for("level_01")

	_replay(board, actions)
	var first: Dictionary = board.get_state()
	assert_true(first["level_solved"], "solved before the reset")

	board.reset_level()
	assert_eq(board.moves_taken, 0, "reset cleared the move counter")
	assert_false(board.is_solved(), "reset restored the unsolved start position")

	_replay(board, actions)
	assert_eq(board.get_state(), first, "replaying the same actions reproduces identical state")
