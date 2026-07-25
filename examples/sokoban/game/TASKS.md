# Sokoban Mini (game) — Master Task List

Build the Godot game per `PRD.md` in this folder.

## Orchestrator protocol

1. Check out the first `status: TODO` task whose `after:` are all DONE; set IN-PROGRESS.
2. Plan → 3. Code → 4. Review vs **Accept** → 5. Gate, commit `<ID>: <title>`, set DONE, update this file in the same commit.

**Gate (every task):** first regenerate Godot's import cache — `godot4
--headless --editor --path . --quit` (idempotent; required on a fresh clone
since `.godot/` is not committed) — then run GUT headless, e.g. `godot4
--headless --path . -s addons/gut/gut_cmdln.gd -gdir=res://tests -gexit` —
both exit 0. T-001 below is responsible for getting this two-step command
working; keep the gate minimal until then. T-006 additionally requires
`python tools/tcp_smoke_check.py` (committed alongside the bridge, not a
throwaway) to exit 0.

**Format check (optional):** none — omitted (gdformat is optional tooling,
not assumed here).

**Standing constraints:**
- This example requires a local `godot4` CLI binary (Godot 4.x) on `PATH` —
  every task's Gate depends on it. Unlike `dice`/`escape-room`, there is no
  zero-dependency fallback; confirm `godot4 --version` works before starting
  T-001.
- All push/collision/win rules live in `res://scripts/board.gd`'s
  `try_move()`. Neither human input handling nor `ugt_bridge.gd` may contain
  a rule — both only call `try_move()`.
- Level files are plain-text grids under `res://levels/`; no level geometry
  may be hardcoded in `.gd` scripts.
- The bridge's JSON message shape (`reset`/`step`/`close`, response fields)
  must match `PRD.md` exactly.

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---

## M0 — Scaffold

### T-001 · Godot project scaffold + GUT — `status: TODO` · `coder: sonnet` · `after: —`
Create the Godot 4 project. Vendor the GUT addon by committing
`addons/gut/` directly into the repo (not via the editor's Asset Library,
which needs GUI/network and won't run headless); enable the plugin in
`project.godot`. Do not commit `.godot/` (the machine-specific import
cache) — the Gate's own cache-regeneration step handles it on every run,
including a fresh clone. Add an empty `res://tests/` with one trivial
passing test.
**Accept:** on a completely fresh clone, the two-step Gate command exits 0
(1 test, 0 failures).

### T-002 · Level file format + loader — `status: TODO` · `coder: opus` · `after: T-001`
Parse the ASCII grid legend into a 2D tile grid (walls/floor/targets), player
start position, and box positions.
**Accept:** GUT tests cover: a valid fixture level loads with the right
wall/target/box counts; a malformed level (unequal row lengths, no player
start) raises a clear error.

## M1 — Content

### T-003 · Author 3 levels — `status: TODO` · `coder: sonnet` · `after: T-002`
Write `level_01.txt` (1 box), `level_02.txt` (2 boxes), `level_03.txt` (3
boxes), each with a known solution documented in a comment/fixture.
**Accept:** loader (T-002) accepts all 3 with 0 errors; each has a documented
solvable move sequence.

## M2 — Core mechanics

### T-004 · `try_move` push/collision logic — `status: TODO` · `coder: opus` · `after: T-003`
Implement the single move/push function per PRD: wall blocks, box pushes only
into floor/empty-target, `boxes_on_target`/`level_solved` tracking,
level-advance on solve, `all_levels_solved` after level 3.
**Accept:** GUT tests cover: wall blocks move; box pushes into floor; box
push blocked by wall behind it; box push blocked by another box behind it;
the T-003 documented solution for each level reaches `level_solved: true`;
solving level 3 sets `all_levels_solved: true`.

## M3 — Front ends

### T-005 · Human input — `status: TODO` · `coder: sonnet` · `after: T-004`
Wire arrow keys / WASD to `try_move()`; snap sprite positions on move.
**Accept:** a GUT test simulates each of the 4 key bindings (via a synthetic
`InputEventKey` fed to the input handler, or `Input.action_press` + one
`_process` tick) and asserts the resulting player/box position matches
calling `try_move()` directly with the corresponding direction; running all
3 documented solutions as simulated key sequences reaches `level_solved:
true` for each level.

### T-006 · UGT TCP bridge — `status: TODO` · `coder: opus` · `after: T-004`
`ugt_bridge.gd` autoload: `--ugt-bridge` / `UGT_BRIDGE=1` gate, `TCPServer` on
`127.0.0.1:8910` (or `--ugt-port`), newline-delimited JSON per PRD's exact
protocol, one connection at a time. Buffer incoming bytes across
`_process()` polls and split on `\n` — do not assume one socket read equals
one message. Commit `tools/tcp_smoke_check.py` (a real, repo-tracked Python
script, not a throwaway) that connects, sends the T-003 solutions for all 3
levels as `step` commands, and asserts `all_levels_solved: true`.
**Accept:** `tools/tcp_smoke_check.py` (per the Gate's T-006 addendum) exits
0; an invalid direction mid-solution is a no-op (state unchanged) not an
error; a test that writes a single JSON message to the socket split across
two separate writes still parses correctly on the Godot side.

---

**Deliberately deferred:** undo/redo, level editor, more than 3 levels,
animation, sound — see PRD Non-goals.
