extends "res://tests/assertions.gd"
## T-003 — level file format + loader (`res://scripts/level.gd`).
##
## Fixtures are arrays of row strings joined with "\n" by `_grid()`. They are
## deliberately NOT triple-quoted literals: GDScript keeps the leading
## indentation tabs of a multi-line string, which would inject tabs into the
## grid and produce phantom UNKNOWN_CHARACTER failures. The array form also
## makes significant trailing spaces visible to a reader.
##
## Every malformed fixture is malformed in exactly ONE way — otherwise the
## "distinct error" tests would really be testing validation ORDER rather than
## detection.

const Level := preload("res://scripts/level.gd")

## 7x5 · 20 walls · 3 targets · 3 boxes · player at (1, 1).
## Covers every legend character except '+' (see VALID_PLAYER_ON_TARGET).
const VALID := ["#######", "#@ $ .#", "#  *  #", "#.$   #", "#######"]

## Player standing on a target: 2 targets, 2 boxes.
const VALID_PLAYER_ON_TARGET := ["#######", "#+$ $.#", "#######"]

## Row 3 is 4 wide against row 1's 5. Otherwise valid (1 player, 1 box, 1 target).
const BAD_ROW_LENGTH := ["#####", "#@$.#", "####"]

## No '@' and no '+'. Otherwise valid (1 box, 1 target).
const BAD_NO_PLAYER := ["#####", "#$. #", "#####"]

## Two '@'. Otherwise valid (1 box, 1 target).
const BAD_TWO_PLAYERS := ["######", "#@$.@#", "######"]

## 2 boxes against 1 target. Otherwise valid.
const BAD_BOX_TARGET_MISMATCH := ["######", "#@$$.#", "######"]

## 'X' is not in the legend. Otherwise valid (1 player, 1 box, 1 target).
const BAD_UNKNOWN_CHAR := ["######", "#@$.X#", "######"]


func _grid(rows: Array) -> String:
	var parts := PackedStringArray()
	for row in rows:
		parts.append(row)
	return "\n".join(parts)


func test_valid_grid_loads_counts() -> void:
	var level := Level.new()
	assert_true(level.load_from_text(_grid(VALID)), "valid fixture should load")
	assert_true(level.is_valid(), "is_valid() after a good load")
	assert_eq(level.error_code, "", "no error code after a good load")
	assert_eq(level.width, 7, "width")
	assert_eq(level.height, 5, "height")
	assert_eq(level.wall_count, 20, "wall count")
	assert_eq(level.target_count, 3, "target count")
	assert_eq(level.boxes_total(), 3, "box count")
	assert_eq(level.player_start, Vector2i(1, 1), "player start")


func test_valid_grid_tiles_and_box_positions() -> void:
	var level := Level.new()
	level.load_from_text(_grid(VALID))

	assert_eq(level.tile_at(0, 0), Level.Tile.WALL, "'#' is a wall")
	assert_eq(level.tile_at(2, 1), Level.Tile.FLOOR, "' ' is floor")
	assert_eq(level.tile_at(5, 1), Level.Tile.TARGET, "'.' is a target")
	# A box is an entity, not a tile: the '*' cell's TILE is a plain target.
	assert_eq(level.tile_at(3, 2), Level.Tile.TARGET, "'*' tile is a target")
	assert_eq(level.tile_at(1, 1), Level.Tile.FLOOR, "'@' tile is floor")
	# Off-grid reads are walls (bounds convenience for board.gd, not a rule).
	assert_eq(level.tile_at(-1, 0), Level.Tile.WALL, "off-grid left is a wall")
	assert_eq(level.tile_at(99, 0), Level.Tile.WALL, "off-grid right is a wall")

	# Row-major scan order, asserted element-wise for a readable failure.
	assert_eq(level.boxes.size(), 3, "boxes size")
	assert_eq(level.boxes[0], Vector2i(3, 1), "first box")
	assert_eq(level.boxes[1], Vector2i(3, 2), "second box")
	assert_eq(level.boxes[2], Vector2i(2, 3), "third box")


func test_player_on_target_counts_as_target() -> void:
	var level := Level.new()
	assert_true(level.load_from_text(_grid(VALID_PLAYER_ON_TARGET)), "'+' fixture should load")
	assert_eq(level.player_start, Vector2i(1, 1), "player start on '+'")
	assert_eq(level.tile_at(1, 1), Level.Tile.TARGET, "'+' tile is a target")
	assert_eq(level.target_count, 2, "'+' counts toward targets")
	assert_eq(level.boxes_total(), 2, "box count")


func test_unequal_row_lengths_is_an_error() -> void:
	var level := Level.new()
	assert_false(level.load_from_text(_grid(BAD_ROW_LENGTH)), "unequal rows must not load")
	assert_false(level.is_valid(), "is_valid() after a failed load")
	assert_eq(level.error_code, Level.ERR_ROW_LENGTH, "error code")
	assert_true(level.error_message.contains("3"), "message names the 1-based offending line")


func test_no_player_start_is_an_error() -> void:
	var level := Level.new()
	assert_false(level.load_from_text(_grid(BAD_NO_PLAYER)), "no player must not load")
	assert_eq(level.error_code, Level.ERR_NO_PLAYER, "error code")
	assert_false(level.error_message.is_empty(), "message is not empty")


func test_two_player_starts_is_an_error() -> void:
	var level := Level.new()
	assert_false(level.load_from_text(_grid(BAD_TWO_PLAYERS)), "two players must not load")
	assert_eq(level.error_code, Level.ERR_MULTIPLE_PLAYERS, "error code")
	assert_false(level.error_message.is_empty(), "message is not empty")


func test_box_target_count_mismatch_is_an_error() -> void:
	var level := Level.new()
	assert_false(level.load_from_text(_grid(BAD_BOX_TARGET_MISMATCH)), "mismatch must not load")
	assert_eq(level.error_code, Level.ERR_BOX_TARGET_MISMATCH, "error code")
	assert_true(level.error_message.contains("2"), "message names the box count")
	assert_true(level.error_message.contains("1"), "message names the target count")


## The Accept clause "clear, DISTINCT error" made executable: four different
## malformations must not collapse onto one another (or onto "").
func test_error_codes_are_distinct() -> void:
	var fixtures := [BAD_ROW_LENGTH, BAD_NO_PLAYER, BAD_TWO_PLAYERS, BAD_BOX_TARGET_MISMATCH]
	var codes: Array = []
	for fixture in fixtures:
		var level := Level.new()
		assert_false(level.load_from_text(_grid(fixture)), "malformed fixture must not load")
		assert_false(level.error_code.is_empty(), "a failed load always sets an error code")
		assert_false(level.error_message.is_empty(), "a failed load always sets a message")
		if not codes.has(level.error_code):
			codes.append(level.error_code)
	assert_eq(codes.size(), 4, "four malformations give four distinct codes")


func test_failed_load_leaves_no_partial_state() -> void:
	var level := Level.new()
	level.load_from_text(_grid(BAD_TWO_PLAYERS))
	assert_eq(level.boxes_total(), 0, "no boxes survive a failed load")
	assert_eq(level.width, 0, "width reset")
	assert_eq(level.height, 0, "height reset")
	assert_eq(level.grid.size(), 0, "grid reset")
	assert_eq(level.player_start, Vector2i(-1, -1), "player start reset")


func test_unknown_character_is_an_error() -> void:
	var level := Level.new()
	assert_false(level.load_from_text(_grid(BAD_UNKNOWN_CHAR)), "unknown char must not load")
	assert_eq(level.error_code, Level.ERR_UNKNOWN_CHAR, "error code")
	assert_true(level.error_message.contains("X"), "message names the offending character")


func test_empty_text_is_an_error() -> void:
	var empty := Level.new()
	assert_false(empty.load_from_text(""), "empty text must not load")
	assert_eq(empty.error_code, Level.ERR_EMPTY, "error code for empty text")

	var blank := Level.new()
	assert_false(blank.load_from_text("\n\n"), "blank lines only must not load")
	assert_eq(blank.error_code, Level.ERR_EMPTY, "error code for blank-only text")


## Without this, a level file saved on another platform (or with a trailing
## newline, which most editors add) would fail with a confusing
## UNEQUAL_ROW_LENGTHS in T-005.
func test_crlf_and_trailing_newline_load_identically() -> void:
	var lf := Level.new()
	lf.load_from_text(_grid(VALID))

	var crlf := Level.new()
	var crlf_text := _grid(VALID).replace("\n", "\r\n")
	assert_true(crlf.load_from_text(crlf_text), "CRLF text should load")
	assert_eq(crlf.width, lf.width, "CRLF width")
	assert_eq(crlf.height, lf.height, "CRLF height")
	assert_eq(crlf.wall_count, lf.wall_count, "CRLF wall count")
	assert_eq(crlf.target_count, lf.target_count, "CRLF target count")
	assert_eq(crlf.boxes_total(), lf.boxes_total(), "CRLF box count")

	var trailing := Level.new()
	assert_true(trailing.load_from_text(_grid(VALID) + "\n"), "trailing newline should load")
	assert_eq(trailing.height, lf.height, "trailing newline adds no row")
	assert_eq(trailing.boxes_total(), lf.boxes_total(), "trailing newline box count")


func test_reload_clears_previous_state() -> void:
	var level := Level.new()
	assert_true(level.load_from_text(_grid(VALID)), "first load")
	assert_true(level.load_from_text(_grid(VALID_PLAYER_ON_TARGET)), "second load")
	assert_eq(level.width, 7, "second load width")
	assert_eq(level.height, 3, "second load height")
	assert_eq(level.boxes_total(), 2, "no boxes leak from the first load")
	assert_eq(level.target_count, 2, "no targets leak from the first load")
	assert_eq(level.player_start, Vector2i(1, 1), "second load player start")


func test_load_from_file_missing_path_is_an_error() -> void:
	var level := Level.new()
	assert_false(
		level.load_from_file("res://levels/does_not_exist.txt"), "missing file must not load"
	)
	assert_eq(level.error_code, Level.ERR_FILE_NOT_FOUND, "error code")
	assert_false(level.error_message.is_empty(), "message is not empty")
	assert_false(level.is_valid(), "is_valid() after a missing file")
