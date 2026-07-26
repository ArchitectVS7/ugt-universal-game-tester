# Sokoban Mini (game) — Master Task List

Build the Godot game per `PRD.md` in this folder.

## Orchestrator protocol

1. Check out the first `status: TODO` task whose `after:` are all DONE; set IN-PROGRESS.
2. Plan → 3. Code → 4. Review vs **Accept** → 5. Gate, commit `<ID>: <title>`, set DONE, update this file in the same commit.

**Gate (every task):** first regenerate Godot's import cache — `godot4
--headless --editor --path . --quit` (idempotent; required on a fresh clone
since `.godot/` is not committed) — then run the suite: `godot4 --headless
--path . -s tests/run_tests.gd` — both exit 0. **Until T-002 is DONE the gate
is the first command only** (T-001 builds the project, T-002 builds the
runner). T-008 additionally requires `python3 tools/tcp_smoke_check.py` to
exit 0.

**Format check (optional):** none — omitted (gdformat is optional tooling,
not assumed here).

**Standing constraints:**
- This example requires a local Godot 4.x CLI binary on `PATH`, invoked as
  `godot4` — every task's Gate depends on it. Unlike `dice`/`escape-room`
  there is no zero-dependency fallback; confirm `godot4 --version` works
  before starting T-001. (Homebrew installs the binary as `godot`; if that is
  what you have, symlink it: `ln -s "$(command -v godot)" /usr/local/bin/godot4`.)
- **No third-party addons.** The test runner in T-002 is ~40 lines of
  GDScript, specified in full below. Do not vendor GUT or any other
  framework, and do not fetch anything from the network — see PRD
  "Verification" for why.
- All push/collision/win rules live in `res://scripts/board.gd`'s
  `try_move()`. Neither human input handling nor `ugt_bridge.gd` may contain
  a rule — both only call `try_move()`.
- Level files are plain-text grids under `res://levels/`; no level geometry
  may be hardcoded in `.gd` scripts.
- The bridge's JSON message shape (`reset`/`step`/`close`, response fields)
  must match `PRD.md` exactly.

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---

## M0 — Scaffold + test harness

### T-001 · Godot project scaffold — `status: DONE` · `coder: sonnet` · `after: —`
Create the Godot 4 project: `project.godot`, one main scene, and empty
`res://scripts/`, `res://levels/`, `res://tests/` directories. Do **not**
commit `.godot/` (the machine-specific import cache) — the Gate regenerates
it on every run, including on a fresh clone.
**Accept:** on a fresh clone, `godot4 --headless --editor --path . --quit`
exits 0, and `godot4 --headless --path . --quit` opens and closes the project
with no errors on stderr.

**Delivered (2026-07-25):** Added `project.godot` (Godot 4.4, gl_compatibility
renderer, 640×480 viewport, `main.tscn` as the run scene), the empty
`main.tscn` root `Node2D` wired to a deliberately-empty `scripts/main.gd`
(doc-commented to say push/collision/win rules must live only in the future
`board.gd`), and empty `res://scripts/`, `res://levels/`, `res://tests/`
directories (kept present via `.gitkeep` where Godot itself left them empty).
Added a repo-local `.gitignore` for `.godot/` per the standing constraint —
the machine-specific import cache is never committed since the Gate
regenerates it every run. Scope boundary: no gameplay, no board/rules script,
and no test runner — those are T-002 onward; this task is scaffold-only and
was verified against the two `godot4 --headless` Accept commands, not against
the project's own test suite (which does not exist yet).
Orchestration: graphify=none — no `graphify-out/graph.json` in the repo root (checked); scaffold task is self-contained anyway. · attempts=1/4.

### T-002 · Headless test runner — `status: DONE` · `coder: opus` · `after: T-001`
Write `tests/run_tests.gd`, run as `godot4 --headless --path . -s
tests/run_tests.gd`. Implement **exactly this contract** — it is small on
purpose, and it is the gate every later task is judged by:

- discovers every `res://tests/test_*.gd`, sorted by filename
- for each, instantiates it and calls every method whose name begins with
  `test_`, in declaration order; honours optional `before_each()` /
  `after_each()` on the script
- exposes assert helpers to test scripts: `assert_eq(actual, expected, msg)`,
  `assert_ne`, `assert_true(v, msg)`, `assert_false`, `assert_null`,
  `assert_not_null`. Each records a pass or a failure — an assert must never
  abort the run
- prints one line per case: `PASS <script>::<method>` or
  `FAIL <script>::<method> — <msg>`
- prints a final `N passed, M failed` line
- **exits 0 if and only if M == 0 and N > 0** — a run that discovers zero
  tests exits 1, never 0

Also add `tests/test_sanity.gd` with one trivially passing test, and commit
`tools/check_runner_reports_failure.sh` — a real, repo-tracked script (not a
throwaway) that writes a temporary failing test into `res://tests/`, runs the
runner, asserts it exited **non-zero**, and removes the temp file via a
`trap` so the working tree is left clean whether it passes or fails.
**Accept:** on a fresh clone the two-step Gate exits 0 and prints
`1 passed, 0 failed`; `tools/check_runner_reports_failure.sh` exits 0
(proving the runner can actually fail); `git status --porcelain` is empty
after running it. A runner that cannot report failure is worse than no
runner — this task is not DONE until that negative control passes.

**Delivered (2026-07-25):** `tests/run_tests.gd` (SceneTree script, no
third-party addon, nothing fetched) implements the contract exactly:
filename-sorted discovery of `res://tests/test_*.gd`, `test_*` methods in
declaration order (deduped, never sorted), optional `before_each()` /
`after_each()`, one `PASS <script>::<method>` / `FAIL <script>::<method> — <msg>`
line per case, a final `N passed, M failed`, and exit 0 **iff** `M == 0 and
N > 0` (verified by hand: with `test_sanity.gd` moved aside the runner prints
`0 passed, 0 failed` and exits 1). Assert helpers live in
`tests/assertions.gd` (inherited by path — no `class_name`, and not named
`test_*.gd` so it is never discovered as a suite); they only append to
`failures`, never `assert()`/`push_error()`/`quit()`, so an assertion can
never abort the run. `tests/test_sanity.gd` holds exactly one test with one
assertion, pinning the `1 passed, 0 failed` gate line.
`tools/check_runner_reports_failure.sh` (repo-tracked, mode 755,
cwd-independent, `GODOT` overridable) injects a failing `test_*.gd` and
requires **both** a non-zero exit **and** a matching `FAIL` line — so a crash
or an empty discovery cannot masquerade as a working negative control; an
`EXIT` trap installed before the file is written removes both the `.gd` and
any `.gd.uid` (this repo tracks `.uid` sidecars), leaving `git status
--porcelain` clean on every path. Three environment findings hardened against
on Godot 4.7.1: `OS.set_exit_code()`/`OS.exit_code` do not exist (plain
`quit(code)` does propagate); a test script with a parse error `load()`s as a
non-null GDScript whose `new()` raises a fatal error that **aborted
`_initialize()` and hung the run forever** — now gated on `can_instantiate()`
and reported as a `FAIL <script>::<load>` case, with a 60s `_process()`
watchdog as a last-resort "print red and quit 1" net so the Gate can never
hang; and `==` between unrelated Variant types raises at runtime, so the
helpers compare `typeof()` first (`assert_true`/`assert_false` are
strict-boolean — `1` does not pass). `tests/.gitkeep` removed (the directory
now has real content). Scope boundary: no game logic — no `board.gd`, no
levels, no bridge.
Orchestration: graphify=none — no `graphify-out/graph.json` in the repo root or in `examples/sokoban/game/` (checked); the task is also self-contained (two new files + one shell script · attempts=1/4.

## M1 — Rules engine

### T-003 · Level file format + loader — `status: DONE` · `coder: opus` · `after: T-002`
Parse the ASCII grid legend (PRD "Core mechanics") into a 2D tile grid
(walls/floor/targets), the player start position, and box positions.
Structural validation only — no move logic here.
**Accept:** tests cover a valid inline fixture grid loading with the right
wall/target/box counts, and each of these malformed fixtures raising a clear,
distinct error: unequal row lengths, no player start, two player starts,
`boxes_total != targets_total`.

**Delivered (2026-07-25):** New `scripts/level.gd` (a `RefCounted`, no
`class_name` — consumers `preload` it, same discipline as `tests/assertions.gd`)
parses the PRD legend into `grid` (`Tile.FLOOR/WALL/TARGET` as
`PackedByteArray` rows), `player_start`, `boxes`, plus `width`/`height`/
`wall_count`/`target_count`, and exposes `load_from_text`/`load_from_file`/
`is_valid`/`boxes_total`/`tile_at`. **Kept deliberately separate from
`board.gd`** so the standing constraint stays trivially auditable: `level.gd` is
immutable parsed geometry with zero direction/push/collision/win code, and
T-004's `board.gd::try_move()` remains the only place a rule can live (`tile_at`
returning `WALL` off-grid is a bounds convenience, documented as such, not the
"walls block" rule). Seven distinct, stable string error codes —
`EMPTY_LEVEL`, `UNEQUAL_ROW_LENGTHS`, `UNKNOWN_CHARACTER`, `NO_PLAYER_START`,
`MULTIPLE_PLAYER_STARTS`, `BOX_TARGET_MISMATCH`, `FILE_NOT_FOUND` — returned as
data with a `source:line: detail` message; never `assert()`/`push_error()`
(stderr must stay clean per T-001's Accept, and returned data is the only form
the tests can assert on). A failed load wipes all partially-parsed state, so a
caller cannot half-use a broken level. Parser decisions that matter to T-005:
CRLF/lone-CR normalised and **trailing** blank lines dropped (a file ending in a
newline gains no zero-width row) while **interior** blank lines stay a genuine
row-length error; rows are never `strip_edges()`ed because trailing spaces are
significant floor cells; an out-of-legend character is a loud error, never a
silent floor; `boxes` is appended in row-major order so the box list is
deterministic for the PRD's determinism criterion.
`tests/test_level_loader.gd` adds 14 cases (suite 1 → 15 passed, 0 failed):
counts/tiles/row-major box order on a 7×5 fixture covering every legend
character, `+` counting as a target, all four required malformations, plus
unknown-char, empty/blank-only, no-partial-state-after-failure, CRLF +
trailing-newline equivalence, reload-clears-state, and missing-file. Each
malformed fixture is malformed in **exactly one way** (otherwise the "distinct
error" claim would be testing validation *order*, not detection), and
`test_error_codes_are_distinct` dedupes the four codes to prove they really are
four. Fixtures are `const` arrays of row strings joined by a helper, not
triple-quoted literals — GDScript keeps a multi-line string's indentation tabs,
which would inject tabs into the grid. Verified the new tests are not vacuous by
mutating `wall_count += 1` → `+= 2` in the loader and watching the suite go
`14 passed, 1 failed`, then restoring. Gate green (editor pass exit 0, suite
exit 0), `tools/check_runner_reports_failure.sh` still exits 0, and the two
generated `.uid` sidecars are included (this repo tracks them). `test_sanity.gd`
doc comment corrected — it claimed the Gate pins the line `1 passed, 0 failed`,
which stopped being true the moment a real suite landed; the Gate is exit 0
(`M == 0 and N > 0`). Scope boundary: no `board.gd`, no `try_move`, no level
`.txt` files and no `levels/solutions.json` (T-004/T-005 own those), and
`levels/.gitkeep` left in place.
Orchestration: graphify=none — no `graphify-out/graph.json` in either the git root (`_UGT Universal Game Tester/`) or `examples/sokoban/game/` (both checked); the task is also self-con · attempts=1/4.

### T-004 · `try_move` push/collision logic — `status: DONE` · `coder: opus` · `after: T-003`
Implement the single move/push function per PRD: wall blocks; box pushes only
into floor or empty target; `boxes_on_target`/`level_solved` tracking;
`moves_taken` increments only on a move that actually changes a position;
level-advance on solve; `all_levels_solved` after the third level.
Test against **small inline fixture grids defined in the test file**, not the
shipped levels — those are authored in T-005.
**Accept:** tests cover wall blocks move; box pushes into floor; box push
blocked by a wall behind it; box push blocked by another box behind it; a
no-op move does **not** increment `moves_taken`; a real move does; putting the
last box on a target sets `level_solved: true`.
**Delivered (2026-07-25):** shipped `scripts/board.gd` as the single rules
engine (`try_move()`, `reset_level()`, `boxes_on_target()`/`is_solved()`,
`get_state()` in the PRD's exact shape) built on top of T-003's `level.gd`
parser, with lazy level-advance (a solved level only advances at the start of
the next `try_move()` call, so `level_solved: true` stays observable in the
solving move's own state before the next level's grid replaces it) and
out-of-range/unknown direction ids treated as a silent no-op so the future
wire bridge can pass an `action_id` straight through with zero rule content of
its own. `tests/test_board.gd` adds 21 cases against small inline fixture
grids (wall block, push into floor, push blocked by a wall/box behind it,
no-op vs. real move increment, last-box-on-target solve, level advance +
`moves_taken` surviving it, `all_levels_solved` after the third level, reset
semantics, state-shape/determinism, and bad/empty/missing-level load
failures) — none of the shipped `level_01/02/03.txt` levels exist yet, so
proving those specific levels solvable is explicitly left to T-005, not this
task's gate.
Orchestration: graphify=none — no `graphify-out/graph.json` in the game dir or the git root (both checked); the task is also self-contained (one new script + one new test file against  · attempts=1/4.

## M2 — Content

### T-005 · Author 3 levels + prove them solvable — `status: DONE` · `coder: sonnet` · `after: T-004`
Write `level_01.txt` (1 box), `level_02.txt` (2 boxes), `level_03.txt` (3
boxes), increasing in grid size. For each, commit its solution as a move
sequence in `levels/solutions.json` — a flat map of
`{"level_01": [0,3,3,1, ...], ...}` using the PRD's action ids
(`0=up, 1=down, 2=left, 3=right`).
**Accept:** a test loads each shipped level through T-003's loader (0 errors)
and **replays its `solutions.json` sequence through `try_move()`**, asserting
`level_solved: true` at the end of each, and `all_levels_solved: true` after
the third. This is an executed check, not a hand-traced one — a wrong level
or a wrong solution fails *this* task's gate, not a later task's.
**Delivered (2026-07-25):** shipped `levels/level_01.txt` (7×5, 1 box),
`level_02.txt` (9×7, 2 boxes) and `level_03.txt` (11×8, 3 boxes) — box count
1→2→3 and grid area 35→63→88, both strictly increasing per the PRD — plus
`levels/solutions.json`, a flat `{"level_01": [2,0,2,0,3,3], ...}` map of PRD
action ids with sequences of 6 / 23 / 44 moves (73 total). Every committed
sequence is BFS-**optimal**, contains zero no-op actions, and does not solve
its level before its own final action; the tests pin all three properties, so
a padded or wrong sequence cannot pass. `tests/test_shipped_levels.gd` adds 10
cases (suite 37 → 47 passed, 0 failed): the solutions file parses to exactly
the three shipped keys with whole-number ids in 0..3, `board.gd`'s
`DEFAULT_LEVEL_PATHS` really are these files, each level loads through T-003's
`level.gd` with an empty `error_code`, box count / area grow, **no level
starts already solved** (the anti-vacuity guard — a level authored with `*` on
its only target would otherwise "pass" its replay doing nothing), each level's
committed sequence replayed through `try_move()` ends `level_solved: true`
with `moves_taken == sequence length`, all three concatenated on ONE board end
`all_levels_solved: true` at `level_index: 2` / `moves_taken: 73` (which also
pins T-004's lazy level-advance: the next level's FIRST action is what
triggers the advance and is then applied inside the new level — no filler move
between sequences, exactly what T-008 replays over the wire), and a
reset-then-replay reproduces an identical state dictionary. Unlike
`test_board.gd`, this suite deliberately reads the real `res://levels/` files
by path and embeds **no grid and no action list** of its own — level geometry
stays data-only per the standing constraint, and `solutions.json` stays a flat
`{name: [int, ...]}` map with no nesting or metadata because T-008 `json.load`s
that exact file. Action ids are coerced with `int()` on read (Godot's JSON
parser can return numbers as floats, and `try_move(direction: int)`'s bounds
check must not be fed one) with the coercion asserted lossless, so a stray
`2.5` is a red test rather than a silent floor. Verified the new tests are not
vacuous with three mutations, each reverted byte-identically: flipping
`level_01`'s last action `3`→`0` gave `44 passed, 3 failed`; turning the
level_02 floor cell (4,3) into `#` on the solution path gave `45 passed, 2
failed`; appending one wall-blocked no-op after `level_01`'s win gave `45
passed, 2 failed` — each naming the offending level. Gate green (editor pass
exit 0, suite exit 0, stderr empty), `tools/check_runner_reports_failure.sh`
still exits 0, and `levels/.gitkeep` was removed now that the directory holds
real content. Scope boundary held: no `ugt_bridge.gd`, no human input
handling, no `tools/tcp_smoke_check.py`, and `scripts/board.gd` /
`scripts/level.gd` were not touched — T-006/T-007/T-008 own those.
Orchestration: graphify=none — no `graphify-out/graph.json` in the game dir or the git root (`_UGT Universal Game Tester/`), both checked; the task is also self-contained (3 data files · attempts=1/4.

## M3 — Front ends

### T-006 · Human input — `status: DONE` · `coder: sonnet` · `after: T-004`
Wire arrow keys / WASD to `try_move()`; snap sprite positions on move. Route
key events through a single handler function (e.g.
`Board._on_direction_input(dir)`) so it is callable directly.
**Accept:** a test calls the input handler directly with each of the 4
directions and asserts the resulting player/box positions match calling
`try_move()` with the corresponding direction; a separate one-line assertion
covers the key→direction mapping table. Do **not** synthesize `InputEventKey`
through the `Input` singleton — headless Godot's root window is 64x64 and
synthesized input does not land without resizing it twice. That is an
environment quirk, not game logic, and it is not what this task is testing.

**Delivered (2026-07-25):** Built the human front end in `scripts/main.gd` (the
whole implementation — `board.gd`, `level.gd`, `levels/`, `main.tscn` and
`project.godot` were not touched), plus `tests/test_human_input.gd` (9 cases,
suite 47 → **56 passed, 0 failed**). Three pieces, none of them a rule: a
`KEY_DIRECTIONS` table binding the 4 arrows + WASD to ids taken from
`Board.Direction` (it never spells a number itself, so it cannot drift from the
PRD's `0=up 1=down 2=left 3=right`), read through one pure
`static func direction_for_key(keycode) -> int` returning `NO_DIRECTION` (-1)
for an unbound key; the single handler `_on_direction_input(direction) -> bool`,
which is nothing but `board.try_move(direction)` plus a view re-sync and
returns `try_move()`'s own bool untouched; and `_unhandled_input()`, which only
translates a keycode (physical first so WASD keeps its physical position on a
non-QWERTY layout, `keycode` fallback for the arrows) and delegates. The
handler takes an `int`, not an `InputEvent`, which is exactly what lets a test
drive the real code path — **no `InputEventKey` is synthesized anywhere, no
`Input.parse_input_event`, no window resizing, no `SceneTree` node adds**, per
the task's explicit instruction. The view re-syncs unconditionally, including
when the move returned false, because `board.gd` documents that a false return
can still coincide with its lazy level advance. Sprite snapping is a pure
`static func cell_to_position(cell) -> Vector2` (`cell * CELL_SIZE`, 32px);
`build_view()` draws ColorRects only (no textures, so nothing to import and
nothing to break headless) — a backdrop, a tile per wall, a centred pip per
target, one node per box index-aligned with `board.boxes`, one for the player —
and `_sync_view()` re-places the movable nodes on exactly `cell_to_position()`
with no inset, rebuilding on a level advance. `_sync_view()` early-returns when
no view exists, which is what keeps 8 of the 9 tests node-free; `_ready()` is
the only place a node is created and never runs for a `Main.new()` outside the
tree. A level-load failure `print()`s the returned `error_code`/`error_message`
— never `push_error()`/`assert()`, so T-001's clean-stderr Accept still holds
(re-verified: `godot4 --headless --path . --quit` exits 0 with **0 bytes on
stderr** even though `_ready()` now loads levels and builds the view). Tests
compare the two paths on a `[player, boxes, get_state()]` snapshot — positions
*and* the PRD state dict — over all 4 directions on an open room where RIGHT is
a real push, over three refused moves (wall-into, wall-behind-box push) so
parity is pinned on no-ops too, after **every** step of a 6-move sequence, and
across a lazy level advance; the key table is one `assert_eq` over all 8 keys
via `direction_for_key()`. Verified not vacuous with three mutations, each
reverted byte-identically: pointing `KEY_W` at `DOWN` gave `55 passed, 1
failed`; making the handler return false without calling `try_move()` gave `52
passed, 4 failed`; adding `+ 1` to `cell_to_position`'s x gave `55 passed, 1
failed`. Gate green (editor pass exit 0, suite exit 0),
`tools/check_runner_reports_failure.sh` still exits 0 with a clean tree after.
Scope boundary held: no `ugt_bridge.gd`, no TCP, no
`tools/tcp_smoke_check.py` (T-007/T-008), and no reset key binding, HUD, undo,
animation or sound.
Orchestration: graphify=none — no `graphify-out/graph.json` in the game dir or in the git root `_UGT Universal Game Tester/` (both checked); the task is also self-contained (one script · attempts=1/4.

### T-007 · UGT TCP bridge — `status: DONE` · `coder: opus` · `after: T-004`
`ugt_bridge.gd` autoload: `--ugt-bridge` / `UGT_BRIDGE=1` gate, `TCPServer` on
`127.0.0.1:8910` (or `--ugt-port`), newline-delimited JSON per PRD's exact
protocol, one connection at a time. Buffer incoming bytes across `_process()`
polls and split on `\n` — do not assume one socket read equals one message.
**Accept:** a test (or a short committed script) connects, sends `reset` then
one `step`, and gets back the PRD's exact state shape; a single JSON message
written to the socket **split across two separate writes** still parses
correctly; an out-of-range `action_id` is a no-op (state unchanged) rather
than an error or a crash.

**Delivered (2026-07-26):** Added `scripts/ugt_bridge.gd` (registered as the
`UgtBridge` autoload in `project.godot` — the only edit to that file) plus
`tests/test_ugt_bridge.gd`, 28 cases, suite **56 → 84 passed, 0 failed**.
`board.gd` / `level.gd` / `main.gd` / `main.tscn` / `levels/` / the runner were
not touched. **The bridge contains zero game rules**: it frames bytes, turns a
wire `action_id` into an `int`, calls `board.try_move()`, and hands
`board.get_state()` back verbatim — no direction vector, no wall/push check, no
`boxes_on_target` arithmetic, and **deliberately no range check on
`action_id`** (T-004 documents an unknown direction as a silent no-op precisely
so the wire value passes straight through), with `terminated` READ OUT of
`state["all_levels_solved"]` rather than recomputed. Four layers, each
independently testable: (1) pure statics `bridge_enabled(args, env)` /
`port_from_args(args)` so the gate is asserted without touching `OS` —
`_ready()` reads `get_cmdline_args() + get_cmdline_user_args()` because the
documented launch puts the flag after `--`, and both `--ugt-port=N` and
`--ugt-port N` are accepted with a non-numeric/out-of-range value falling back
to 8910 (`"abc".to_int()` is 0, which would otherwise become a silently wrong
port); (2) a public frame-independent `poll()` (with `_process()` as a
one-liner) so the socket cases run inside the synchronous runner — it accepts
one peer at a time and hangs up on a second, reads available bytes *before*
judging peer status so a write-then-close client still gets served, and keeps
listening when a client vanishes without `close`; (3) `feed_bytes()`, the
buffer that makes "one socket read is not one message" true in both directions
(split message, two-messages-in-one-read, CRLF, 1 MiB runaway-buffer guard);
(4) pure `handle_line()` returning `{response, close}` with the PRD's exact
shapes — `reset` replies `{"state": …}` and nothing else, `step` replies exactly
`state`/`terminated`/`truncated`/`info`, and `close` writes **no reply at all**
because `../integration/PRD.md` defines its right-hand side as "Godot process
exits cleanly", i.e. the client observes EOF. Two traps hardened against:
`_action_id_from()` must never be `int(msg["action_id"])` — GDScript's
`int("up")` is `0`, a legal UP move, so a garbage wire value would *move the
player*; it maps missing/String/null/bool/Array/Dictionary/fractional to `-1`
while passing whole floats (JSON has one number type) and out-of-**range**
integers through untouched. And `JSON.parse_string()` was swapped for
`JSON.new().parse()` because the static helper pushes an engine error on bad
input, which would let a garbage client spray the game's stderr (T-001's Accept
requires it stay clean — re-verified: `godot4 --headless --path . --quit` still
exits 0 with **0 bytes on stderr**, and prints no bridge line at all when the
flag is absent). Malformed JSON / unknown commands answer `{"error": …}` with
**no `state` key**, so an error can never be mistaken for a state response;
blank lines are ignored. `_ensure_board()` prefers the board the human front
end is already playing (`get_tree().current_scene.board`) over a shadow copy —
the "drive the real running game" discipline — and only builds its own when
there is no scene (tests, `-s` runs); `_shutdown()` guards `get_tree().quit()`
behind `is_inside_tree()` so a `close` test cannot kill the test runner. Tests
use no `await`, no signal, no `get_tree()` and add no node to a tree (the
runner is synchronous — an `await` would be scored green while still running);
every pump loop is bounded by a 2 s wall-clock deadline that asserts on expiry
rather than leaning on the runner's 60 s watchdog; sockets bind upward from
**18910, never 8910**, so a stale bridge cannot fail the suite for the wrong
reason; and `after_each()` frees every bridge and disconnects every client so a
failing case cannot leak a listening socket. All three Accept criteria are
pinned twice — at the pure layer and over a **real socket**: `reset`+`step`
returning the PRD's exact 8-key state (asserted as a sorted key SET, not a
subset), one message in **two separate `put_data` calls** with a load-bearing
mid-way assertion that *nothing* has come back yet (proving it buffered rather
than mis-parsed), and `action_id` 42 over the wire leaving the state
byte-identical with no `error`, a still-`STATUS_CONNECTED` peer and a working
next step (no framing desync). Verified not vacuous with three mutations, each
reverted byte-identically (md5-checked): dropping the framing buffer gave
`80 passed, 4 failed`; the naive `int(msg.get("action_id", -1))` coercion gave
`83 passed, 1 failed`; hardcoding `"terminated": false` gave `83 passed, 1
failed`. Also driven live end-to-end (not committed as a script — that is
T-008): `godot4 --headless --path . -- --ugt-bridge --ugt-port=18910` printed
the single stable readiness line `UGT bridge listening on 127.0.0.1:18910`,
then a Python client replayed all three `solutions.json` sequences over the
socket to `all_levels_solved: true` / `terminated: true` at `moves_taken: 73`,
and `{"command":"close"}` exited the process **0 with empty stderr**;
`UGT_BRIDGE=1 godot4 --headless --path .` (no flag) came up on 8910
identically. Gate green (editor pass exit 0, suite exit 0, stderr 0 bytes),
`tools/check_runner_reports_failure.sh` still exits 0 with a clean tree after.
Scope boundary: no `tools/tcp_smoke_check.py`, no UGT-side Python adapter or
ladder scripts (T-008 / the integration side), no reset key binding and no HUD.
Orchestration: graphify=none — no `graphify-out/graph.json` in the game dir (`examples/sokoban/game/`) or the git root (`_UGT Universal Game Tester/`); both checked. · attempts=1/4.

### T-008 · End-to-end wire check (`tools/tcp_smoke_check.py`) — `status: TODO` · `coder: opus` · `after: T-005, T-007`
Commit `tools/tcp_smoke_check.py` — a real, repo-tracked Python script (not a
throwaway) that launches or attaches to the headless bridge, connects over
TCP, replays all three `levels/solutions.json` sequences as `step` commands,
and asserts `all_levels_solved: true`. This is the PRD's acceptance criteria
checked through the real wire — the closest thing in this example to what UGT
itself does.
**Accept:** `python3 tools/tcp_smoke_check.py` exits 0; it exits non-zero with
a readable message (not a traceback) if the bridge is not running; running
`reset` then the same sequence twice reproduces byte-identical state,
satisfying the PRD's determinism criterion.

---

**Deliberately deferred:** undo/redo, level editor, more than 3 levels,
animation, sound — see PRD Non-goals.
