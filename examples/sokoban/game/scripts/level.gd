extends RefCounted
## Sokoban level file format + loader.
##
## Parses the PRD's classic-Sokoban ASCII legend into an immutable tile grid
## (wall / floor / target) plus the entities that start on it: one player
## position and N box positions.
##
## STRUCTURAL VALIDATION ONLY — there is deliberately no move, push, collision
## or win logic in this file. Those rules live in exactly one place,
## `res://scripts/board.gd`'s `try_move()` (T-004). `board.gd` will hold the
## mutable run state (player position, box positions, `moves_taken`); this
## script holds only the parsed, never-mutated geometry, which is what makes a
## `reset` a matter of re-applying `player_start` / `boxes`.
##
## Deliberately no `class_name` (no dependency on the editor's global class
## registry) — consumers do:
##     const Level := preload("res://scripts/level.gd")
##
## Errors are RETURNED DATA, never `assert()` / `push_error()` / `push_warning()`:
## a project run must leave stderr clean (T-001's Accept), and returned data is
## the only form the tests can assert on. On any failure the loader leaves NO
## half-parsed state behind — a caller cannot accidentally use a broken level.

enum Tile { FLOOR, WALL, TARGET }

## Distinct, stable error codes. Strings rather than enum ints so a failure
## message reads on its own without a lookup table.
const ERR_EMPTY := "EMPTY_LEVEL"
const ERR_ROW_LENGTH := "UNEQUAL_ROW_LENGTHS"
const ERR_UNKNOWN_CHAR := "UNKNOWN_CHARACTER"
const ERR_NO_PLAYER := "NO_PLAYER_START"
const ERR_MULTIPLE_PLAYERS := "MULTIPLE_PLAYER_STARTS"
const ERR_BOX_TARGET_MISMATCH := "BOX_TARGET_MISMATCH"
const ERR_FILE_NOT_FOUND := "FILE_NOT_FOUND"

## PRD "Core mechanics" legend.
const CHAR_WALL := "#"
const CHAR_FLOOR := " "
const CHAR_TARGET := "."
const CHAR_BOX := "$"
const CHAR_BOX_ON_TARGET := "*"
const CHAR_PLAYER := "@"
const CHAR_PLAYER_ON_TARGET := "+"

## "" means the last load succeeded.
var error_code: String = ""

## Human-readable detail, prefixed with the source name and (where one applies)
## the 1-based line number.
var error_message: String = ""

## File name for `load_from_file`, or "<inline>" for `load_from_text`.
var source_name: String = ""

var width: int = 0
var height: int = 0
var wall_count: int = 0
var target_count: int = 0

## Array of PackedByteArray rows; `grid[y][x]` is a `Tile` value.
var grid: Array = []

var player_start: Vector2i = Vector2i(-1, -1)

## Box start positions as `Vector2i`, appended in row-major scan order
## (top-to-bottom, then left-to-right). The order is deterministic on purpose:
## the PRD's determinism criterion means the same level must always produce the
## same box list, and downstream state serialization must not depend on Godot
## dictionary/iteration order.
var boxes: Array = []


## Parses `text`. Returns true on success; on failure returns false and sets
## `error_code` / `error_message`. Safe to call repeatedly on one instance.
func load_from_text(text: String, source: String = "<inline>") -> bool:
	_clear()
	source_name = source

	var rows := _split_rows(text)
	if rows.is_empty():
		return _fail(ERR_EMPTY, 0, "level is empty")

	width = rows[0].length()
	height = rows.size()
	if width == 0:
		return _fail(ERR_EMPTY, 1, "first row is empty")

	var players: Array = []

	for y in range(height):
		var row: String = rows[y]
		if row.length() != width:
			return _fail(
				ERR_ROW_LENGTH,
				y + 1,
				"row length %d does not match row 1 length %d" % [row.length(), width]
			)

		var tiles := PackedByteArray()
		tiles.resize(width)

		for x in range(width):
			var ch := row[x]
			match ch:
				CHAR_WALL:
					tiles[x] = Tile.WALL
					wall_count += 1
				CHAR_FLOOR:
					tiles[x] = Tile.FLOOR
				CHAR_TARGET:
					tiles[x] = Tile.TARGET
					target_count += 1
				CHAR_BOX:
					tiles[x] = Tile.FLOOR
					boxes.append(Vector2i(x, y))
				CHAR_BOX_ON_TARGET:
					tiles[x] = Tile.TARGET
					target_count += 1
					boxes.append(Vector2i(x, y))
				CHAR_PLAYER:
					tiles[x] = Tile.FLOOR
					players.append(Vector2i(x, y))
				CHAR_PLAYER_ON_TARGET:
					tiles[x] = Tile.TARGET
					target_count += 1
					players.append(Vector2i(x, y))
				_:
					# A typo in a level file must be loud, never a silent floor.
					return _fail(
						ERR_UNKNOWN_CHAR, y + 1, "unknown character '%s' at (%d, %d)" % [ch, x, y]
					)

		grid.append(tiles)

	if players.is_empty():
		return _fail(ERR_NO_PLAYER, 0, "no player start (expected one '@' or '+')")
	if players.size() > 1:
		return _fail(
			ERR_MULTIPLE_PLAYERS,
			0,
			(
				"%d player starts (expected exactly one); first two at %s and %s"
				% [players.size(), str(players[0]), str(players[1])]
			)
		)
	player_start = players[0]

	if boxes.size() != target_count:
		return _fail(
			ERR_BOX_TARGET_MISMATCH,
			0,
			"boxes_total %d != targets_total %d" % [boxes.size(), target_count]
		)

	return true


## Reads `path` and parses it. A missing/unreadable file is `ERR_FILE_NOT_FOUND`,
## not a crash — T-005 and T-007 both load levels by path.
func load_from_file(path: String) -> bool:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		_clear()
		source_name = path.get_file()
		return _fail(ERR_FILE_NOT_FOUND, 0, "could not open '%s'" % path)
	var text := file.get_as_text()
	file.close()
	return load_from_text(text, path.get_file())


func is_valid() -> bool:
	return error_code.is_empty() and height > 0


func boxes_total() -> int:
	return boxes.size()


## Tile at a cell. Off-grid reads return `WALL` so callers do not need their own
## bounds checks — this is a BOUNDS convenience, not a game rule (the "a wall
## blocks a move" rule itself lives only in `board.gd::try_move()`).
func tile_at(x: int, y: int) -> int:
	if y < 0 or y >= height or x < 0 or x >= width:
		return Tile.WALL
	var row: PackedByteArray = grid[y]
	return row[x]


## Normalises line endings and drops TRAILING blank lines only.
##
## - CRLF / lone CR are normalised so a level file authored on another platform
##   does not fail with a confusing UNEQUAL_ROW_LENGTHS.
## - A file that ends with a newline must not gain a zero-width final row.
## - Interior blank lines are KEPT: an interior blank line is a genuine
##   unequal-row-length error, not something to paper over.
## - Rows are never `strip_edges()`ed: trailing spaces are significant floor
##   cells, and stripping them would silently reshape a level.
func _split_rows(text: String) -> PackedStringArray:
	var normalised := text.replace("\r\n", "\n").replace("\r", "\n")
	var rows := normalised.split("\n")
	while rows.size() > 0 and rows[rows.size() - 1].is_empty():
		rows.remove_at(rows.size() - 1)
	return rows


func _clear() -> void:
	error_code = ""
	error_message = ""
	source_name = ""
	width = 0
	height = 0
	wall_count = 0
	target_count = 0
	grid = []
	boxes = []
	player_start = Vector2i(-1, -1)


## Records the failure and wipes any partially-parsed geometry. Always false, so
## callers can `return _fail(...)`.
func _fail(code: String, line_no: int, detail: String) -> bool:
	var source := source_name
	_clear()
	source_name = source
	error_code = code
	if line_no > 0:
		error_message = "%s:%d: %s" % [source_name, line_no, detail]
	else:
		error_message = "%s: %s" % [source_name, detail]
	return false
