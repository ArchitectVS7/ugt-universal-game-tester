extends "res://tests/assertions.gd"
## Every shipped level CONTAINS a position a crate can never come back from.
##
## This is the claim `reset_level` (PRD action id 4) rests on, and until now
## nothing tested it: the PRD says a player can always retry because a crate can
## become permanently stuck, while no test asserted that such a place exists in
## the authored content at all. This suite asserts it, per level, off
## `board.gd::render_rows()` — the same grid a human (and a machine player) sees.
##
## WHAT A DEADLOCK-CAPABLE CELL IS. Sokoban's only crate move is a push: the
## player stands opposite the crate and both step one cell along that axis. So a
## crate on a non-target cell can never move again when either of these holds:
##  - CORNER — a wall on one VERTICAL side and a wall on one HORIZONTAL side. It
##    cannot go along the vertical axis (one end is the wall, and pushing toward
##    the open end would need the pusher standing inside that wall), and by the
##    same argument it cannot go along the horizontal axis either.
##  - LANE — walls above AND below (or left AND right), so the crate can only ever
##    slide along that one lane, and no cell of the lane is a target. It can still
##    be pushed, but never onto a target, so the level can no longer be won.
##
## WHAT THIS IS NOT — read this before quoting a green run:
##  - NOT a solver, and no search is introduced here. It is a scan of rendered
##    glyphs: no frontier, no visited set, no move is simulated. (Minimality and
##    solvability by search are `tests/test_solution_optimality.gd`'s job.)
##  - NOT a reachability claim. It says the shipped content CONTAINS cells from
##    which a crate is unrecoverable — which is what justifies `reset_level`
##    existing. It does not say a player can push a crate onto one; proving that
##    would need the searcher, and it is not what the reload button's existence
##    depends on.
##  - NOT an enumeration of every deadlock. Two crates jamming each other in a
##    corridor is a real unrecoverable position this predicate does not count, on
##    purpose. A count of 0 would be a red flag; the counts themselves are not a
##    measure of anything.
##  - It classifies CELLS by geometry, so it is indifferent to what occupies one:
##    the cell under `@` or `$` is judged by its walls and its target-ness, not by
##    its current tenant.
##
## WHY THE PREDICATE LIVES IN THE TESTS AND NOT IN `level.gd` / `board.gd`. It is
## not a rule — nothing in the game consults it, and a public "is this cell dead"
## function sitting in the rules engine would be read as one. Per the standing
## constraint, `try_move()` is the only place a rule may live.
##
## WHY INLINE GRIDS APPEAR HERE when `tests/test_shipped_levels.gd` forbids them:
## same reason `test_solution_optimality.gd` has fixtures. They are CONTROLS for
## the predicate with hand-checkable answers, so a predicate that silently counts
## nothing (or counts every floor cell) is red instead of quietly agreeing with
## whatever the shipped levels happen to look like. No shipped level's geometry is
## copied in — those are read from `res://levels/`.

const Board := preload("res://scripts/board.gd")
const Level := preload("res://scripts/level.gd")

## The shipped level names, in play order. Paths are derived, never repeated.
const LEVEL_NAMES := ["level_01", "level_02", "level_03"]

## `reason` values, so a control can assert WHICH clause fired rather than just
## that something did.
const CORNER := "corner"
const LANE := "lane"


func _level_path(name: String) -> String:
	return "res://levels/%s.txt" % name


## The glyph at a cell of a rendered grid. Off-grid reads come back as a wall, the
## same BOUNDS convenience `level.gd::tile_at()` uses — it removes a bounds check
## from every caller below and is not a game rule.
func _glyph(rows: Array, x: int, y: int) -> String:
	if y < 0 or y >= rows.size():
		return Level.CHAR_WALL
	var row: String = rows[y]
	if x < 0 or x >= row.length():
		return Level.CHAR_WALL
	return row[x]


func _is_wall(rows: Array, x: int, y: int) -> bool:
	return _glyph(rows, x, y) == Level.CHAR_WALL


## Target-ness reads the PRD legend from `level.gd`, never a local copy of it: a
## target may be rendered `.`, or `*` with a crate already home, or `+` with the
## player standing on it. Missing `*` / `+` here is the one way this whole suite
## goes vacuous, which is why two controls below exist to catch it.
func _is_target(rows: Array, x: int, y: int) -> bool:
	var glyph := _glyph(rows, x, y)
	return (
		glyph == Level.CHAR_TARGET
		or glyph == Level.CHAR_BOX_ON_TARGET
		or glyph == Level.CHAR_PLAYER_ON_TARGET
	)


## Does the maximal horizontal run of non-wall cells through (x, y) contain a
## target? A linear walk out to the walls on either side — a SCAN, not a search.
func _row_run_has_target(rows: Array, x: int, y: int) -> bool:
	var left := x
	while not _is_wall(rows, left - 1, y):
		left -= 1
	var right := x
	while not _is_wall(rows, right + 1, y):
		right += 1
	for i in range(left, right + 1):
		if _is_target(rows, i, y):
			return true
	return false


## The vertical twin of `_row_run_has_target()`. Also a scan.
func _column_run_has_target(rows: Array, x: int, y: int) -> bool:
	var top := y
	while not _is_wall(rows, x, top - 1):
		top -= 1
	var bottom := y
	while not _is_wall(rows, x, bottom + 1):
		bottom += 1
	for i in range(top, bottom + 1):
		if _is_target(rows, x, i):
			return true
	return false


## Every deadlock-capable cell of a rendered grid, as
## `[{"cell": Vector2i, "reason": CORNER|LANE}, ...]` in row-major order.
##
## Walls and targets are excluded: a crate cannot occupy a wall, and a crate on a
## target is home rather than stuck.
func _deadlock_cells(rows: Array) -> Array:
	var found: Array = []
	for y in range(rows.size()):
		var row: String = rows[y]
		for x in range(row.length()):
			if _is_wall(rows, x, y) or _is_target(rows, x, y):
				continue
			var up := _is_wall(rows, x, y - 1)
			var down := _is_wall(rows, x, y + 1)
			var left := _is_wall(rows, x - 1, y)
			var right := _is_wall(rows, x + 1, y)
			if (up or down) and (left or right):
				found.append({"cell": Vector2i(x, y), "reason": CORNER})
			elif up and down:
				if not _row_run_has_target(rows, x, y):
					found.append({"cell": Vector2i(x, y), "reason": LANE})
			elif left and right:
				if not _column_run_has_target(rows, x, y):
					found.append({"cell": Vector2i(x, y), "reason": LANE})
	return found


## The cells of `found` carrying one reason, so a control can pin the clause.
func _cells_with_reason(found: Array, reason: String) -> Array:
	var cells: Array = []
	for entry in found:
		if entry["reason"] == reason:
			cells.append(entry["cell"])
	return cells


func _all_cells(found: Array) -> Array:
	var cells: Array = []
	for entry in found:
		cells.append(entry["cell"])
	return cells


# --- Controls for the predicate itself -----------------------------------------
#
# Declared before the shipped-level cases so a broken predicate is reported as a
# broken predicate, above whatever it then says about the content.


## A plain walled room: the four inside corners, and nothing else. The mid-edge
## cells have a wall on ONE side only, so a crate there can still be pushed along
## the wall and off it — a predicate that counted them would call almost every
## floor cell deadly and make the shipped-level cases meaningless.
func test_a_plain_room_reports_exactly_its_four_corners() -> void:
	var rows := ["#####", "#   #", "#   #", "#   #", "#####"]
	var found := _deadlock_cells(rows)
	assert_eq(
		_all_cells(found),
		[Vector2i(1, 1), Vector2i(3, 1), Vector2i(1, 3), Vector2i(3, 3)],
		"the four inside corners, in row-major order"
	)
	assert_eq(_cells_with_reason(found, CORNER).size(), 4, "all four fired the corner clause")
	assert_eq(_cells_with_reason(found, LANE).size(), 0, "no lane in an open room")


## The same room with every corner authored as a target: nothing is reported. A
## crate pushed into a corner that IS a target is home, not stuck — so the target
## exclusion is what keeps this predicate from being a pure wall-geometry count.
func test_a_room_whose_corners_are_targets_reports_nothing() -> void:
	var rows := ["#####", "#. .#", "#   #", "#. .#", "#####"]
	assert_eq(_deadlock_cells(rows), [], "a target corner is a home, not a deadlock")


## A one-tall corridor with no target anywhere in it. The two ends are corners;
## the three cells between them have walls above and below, so a crate there can
## only ever slide left and right along a lane that can never score.
func test_a_targetless_horizontal_corridor_reports_its_lane() -> void:
	var rows := ["#######", "#     #", "#######"]
	var found := _deadlock_cells(rows)
	assert_eq(
		_cells_with_reason(found, LANE),
		[Vector2i(2, 1), Vector2i(3, 1), Vector2i(4, 1)],
		"the three cells that can only slide"
	)
	assert_eq(
		_cells_with_reason(found, CORNER),
		[Vector2i(1, 1), Vector2i(5, 1)],
		"plus the two ends, which are corners"
	)


## The same corridor with the two ends authored as targets: NOTHING is reported.
## The ends are excluded as targets, and the three middle cells now sit in a lane
## that does contain a target, so a crate there is still winnable. This is the
## control for the run WALK — a predicate that only looked at the cell itself
## would call all three a lane deadlock.
func test_a_horizontal_corridor_with_a_target_in_its_lane_reports_nothing() -> void:
	var rows := ["#######", "#.   .#", "#######"]
	assert_eq(_deadlock_cells(rows), [], "a lane containing a target can still be won")


## The vertical branch of the lane clause is not dead code.
func test_a_targetless_vertical_corridor_reports_its_lane() -> void:
	var rows := ["###", "# #", "# #", "# #", "###"]
	var found := _deadlock_cells(rows)
	assert_eq(
		_cells_with_reason(found, LANE), [Vector2i(1, 2)], "the one cell that can only slide"
	)
	assert_eq(
		_cells_with_reason(found, CORNER),
		[Vector2i(1, 1), Vector2i(1, 3)],
		"plus the two ends, which are corners"
	)


func test_a_vertical_corridor_with_a_target_in_its_lane_reports_nothing() -> void:
	var rows := ["###", "#.#", "# #", "#.#", "###"]
	assert_eq(_deadlock_cells(rows), [], "a vertical lane containing a target can still be won")


## Degenerate inputs: a solid block of wall has nowhere for a crate to be, and an
## empty render (`render_rows()` returns `[]` when no level is loaded) must not
## crash the scan or invent a cell.
func test_degenerate_grids_report_nothing() -> void:
	assert_eq(_deadlock_cells(["###", "###", "###"]), [], "all wall, no cells")
	assert_eq(_deadlock_cells([]), [], "an empty render has no cells")


## The predicate against the shape `render_rows()` actually emits, not just
## hand-typed strings — a crate authored home in a corner renders as `*`, and that
## cell must not be counted even though its walls say corner. The neighbouring
## non-target corners still are, so this is not a vacuous "reports nothing".
func test_a_crate_home_in_a_corner_is_not_counted_through_the_real_render() -> void:
	var board := Board.new()
	assert_true(
		board.load_levels_from_texts(["#####\n#*  #\n#  @#\n#####\n"]),
		"the fixture should load (%s)" % board.error_message
	)
	var rows: Array = board.render_rows()
	assert_eq(_glyph(rows, 1, 1), Level.CHAR_BOX_ON_TARGET, "the render really emits '*' there")

	var cells := _all_cells(_deadlock_cells(rows))
	assert_false(cells.has(Vector2i(1, 1)), "a crate already home is not stuck")
	assert_true(cells.size() > 0, "the other corners of the same room still count")


# --- The shipped content ------------------------------------------------------


## The claim `reset_level` rests on: each shipped level contains at least one cell
## a crate could never be recovered from, so "a player can always retry" is a
## response to something real.
##
## Asserted as `>= 1`, never as the observed counts (4 / 8 / 8 on 2026-07-26) —
## an exact count would be a second copy of the level geometry, which is exactly
## what `tests/test_shipped_levels.gd`'s standing note forbids. The counts are
## recorded in the harness notes, not asserted here.
func test_every_shipped_level_has_a_deadlock_capable_cell() -> void:
	for name in LEVEL_NAMES:
		var board := Board.new()
		assert_true(
			board.load_levels_from_paths([_level_path(name)]),
			"%s should load (%s)" % [name, board.error_message]
		)
		var rows: Array = board.render_rows()
		assert_true(rows.size() > 0, "%s renders a non-empty grid" % name)

		var found := _deadlock_cells(rows)
		assert_true(
			found.size() > 0,
			(
				"%s should contain at least one deadlock-capable cell, so reset_level has something to rescue"
				% name
			)
		)
		# Anti-garbage: every reported cell must be a real, non-wall cell of the
		# grid that was scanned.
		for entry in found:
			var cell: Vector2i = entry["cell"]
			assert_true(
				cell.y >= 0 and cell.y < rows.size(),
				"%s: reported cell %s is inside the grid" % [name, str(cell)]
			)
			assert_false(
				_is_wall(rows, cell.x, cell.y),
				"%s: reported cell %s is not a wall" % [name, str(cell)]
			)
