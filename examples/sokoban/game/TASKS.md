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

### T-004 · `try_move` push/collision logic — `status: TODO` · `coder: opus` · `after: T-003`
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

## M2 — Content

### T-005 · Author 3 levels + prove them solvable — `status: TODO` · `coder: sonnet` · `after: T-004`
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

## M3 — Front ends

### T-006 · Human input — `status: TODO` · `coder: sonnet` · `after: T-004`
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

### T-007 · UGT TCP bridge — `status: TODO` · `coder: opus` · `after: T-004`
`ugt_bridge.gd` autoload: `--ugt-bridge` / `UGT_BRIDGE=1` gate, `TCPServer` on
`127.0.0.1:8910` (or `--ugt-port`), newline-delimited JSON per PRD's exact
protocol, one connection at a time. Buffer incoming bytes across `_process()`
polls and split on `\n` — do not assume one socket read equals one message.
**Accept:** a test (or a short committed script) connects, sends `reset` then
one `step`, and gets back the PRD's exact state shape; a single JSON message
written to the socket **split across two separate writes** still parses
correctly; an out-of-range `action_id` is a no-op (state unchanged) rather
than an error or a crash.

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
