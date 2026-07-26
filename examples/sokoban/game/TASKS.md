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

### T-001 · Godot project scaffold — `status: TODO` · `coder: sonnet` · `after: —`
Create the Godot 4 project: `project.godot`, one main scene, and empty
`res://scripts/`, `res://levels/`, `res://tests/` directories. Do **not**
commit `.godot/` (the machine-specific import cache) — the Gate regenerates
it on every run, including on a fresh clone.
**Accept:** on a fresh clone, `godot4 --headless --editor --path . --quit`
exits 0, and `godot4 --headless --path . --quit` opens and closes the project
with no errors on stderr.

### T-002 · Headless test runner — `status: TODO` · `coder: opus` · `after: T-001`
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

## M1 — Rules engine

### T-003 · Level file format + loader — `status: TODO` · `coder: opus` · `after: T-002`
Parse the ASCII grid legend (PRD "Core mechanics") into a 2D tile grid
(walls/floor/targets), the player start position, and box positions.
Structural validation only — no move logic here.
**Accept:** tests cover a valid inline fixture grid loading with the right
wall/target/box counts, and each of these malformed fixtures raising a clear,
distinct error: unequal row lengths, no player start, two player starts,
`boxes_total != targets_total`.

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
