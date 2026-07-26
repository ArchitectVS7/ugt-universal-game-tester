# Sokoban Mini (integration) — Master Task List

Build the UGT-side adapter and trial ladder per `PRD.md` in this folder,
against `../game`.

## Orchestrator protocol

1. Check out the first `status: TODO` task whose `after:` are all DONE; set IN-PROGRESS.
2. Plan → 3. Code → 4. Review vs **Accept** → 5. Gate, commit `<ID>: <title>`, set DONE, update this file in the same commit.

**Gate (every task):** `python -m py_compile *.py` and the ladder script(s)
introduced so far all exit 0.

**Standing constraints:**
- This example requires a local Godot 4.x CLI binary on `PATH`, invoked as
  `godot4`, same as `../game` — confirm `godot4 --version` works before
  starting T-001. (Homebrew installs it as `godot`; if that is what you have,
  symlink it: `ln -s "$(command -v godot)" /usr/local/bin/godot4`.)
- No push/collision/win logic here — every rule lives in
  `../game/scripts/board.gd`. This folder only transports state and actions.
- `GodotTcpAdapter` is constructed directly by each ladder script, per
  `examples/harness-game`'s precedent — it is not dispatched by
  `ugt/core/env.py` (its `ugt.config.yaml` declares `engine.type: custom`).
- **Every ladder script owns the bridge's lifecycle** — it spawns
  `godot4 --headless --path ../game -- --ugt-bridge --ugt-port=<port>` itself,
  waits for the port to accept a connection, and tears the process down on
  exit (including on failure). Attaching to an already-running bridge is a
  fallback for interactive debugging, not the normal path. This mirrors
  `examples/harness-game`, whose adapter spawns `harness.py` rather than
  requiring a human to start it, and it is what `PRD.md` specifies for
  `connect()`. No ladder script may require a manual pre-step: a rung that
  only passes when someone started a server by hand cannot run unattended,
  and a rung that silently passes because it attached to a *stale* bridge
  from an earlier build is worse — verify the PID you spawned is the one
  listening (`lsof -nP -iTCP:<port> -sTCP:LISTEN`).

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---

## M0 — Transport

### T-001 · Spike: raw TCP round-trip — `status: TODO` · `coder: sonnet` · `after: —`
Two files. `bridge_process.py`: a small reusable context manager that spawns
`godot4 --headless --path ../game -- --ugt-bridge --ugt-port=<port>`, polls
until the port accepts a connection (bounded timeout, clear error on
give-up), yields the port, and terminates the child on exit including on
exception. Every later rung imports this rather than re-rolling spawn logic.
`spike_sokoban.py`: use it to open a TCP socket, send `reset` then one
`step`, print both responses, close cleanly. No adapter class.
**Accept:** `python3 spike_sokoban.py` exits 0 from a cold machine with **no
Godot process already running**, and prints a valid `state` dict from both
commands; no `godot4` process survives the script (check with `pgrep -f
ugt-bridge`); the port is free again afterwards.

### T-002 · `GodotTcpAdapter` (`BaseAdapter`) — `status: TODO` · `coder: opus` · `after: T-001`
Wrap the spike's transport in a `BaseAdapter` subclass: `connect`/`reset`/
`step`/`close`, matching `../game/PRD.md`'s message shape.
**Accept:** `smoke_sokoban_adapter.py` (rung 2) does the same round-trip
through the adapter and exits 0.

## M1 — Correctness (Tier 1, R1/R2)

### T-003 · Invariants module — `status: TODO` · `coder: opus` · `after: T-002`
`invariants.py`: `moves_taken` monotonic, `player_x`/`player_y` in-bounds,
`boxes_on_target ≤ boxes_total`, reusable by R1/R2 and R3 (mirror
`examples/harness-game/invariants.py`'s `InvariantSuite` shape).
**Accept:** unit-callable; asserts pass against a known-good state sequence
and fail against a deliberately corrupted one (test fixture).

### T-004 · `verify_round1.py`: one solved level — `status: TODO` · `coder: opus` · `after: T-003`
Drive level 1's solution — read it from `../game/levels/solutions.json`, the
artifact `../game`'s T-005 commits; never hardcode a copy here, or the two
drift — to `level_solved: true`; assert F1, F2, F4, F5 from the PRD's table;
check invariants after every step.
**Accept:** script prints `[PASS]`/`[FAIL]` per check and a `ROUND 1 MET —
p/t` footer; exits non-zero on any failure.

### T-005 · `verify_round2.py`: full 3-level clear + no-op checks — `status: TODO` · `coder: opus` · `after: T-004`
All 3 levels back-to-back to `all_levels_solved: true`, again reading the
sequences from `../game/levels/solutions.json`; deliberately drive into a
wall and a blocked box to assert F1/F3 (no-op, state unchanged).
**Accept:** same PASS/FAIL + footer convention; exits non-zero on any
failure.

## M2 — Robustness (Tier 2, R3)

### T-006 · `verify_round3.py`: exploit-hunter + replay — `status: TODO` · `coder: opus` · `after: T-005`
Random walk ≥100 steps per level via `ugt/core/exploit_hunter.py`, invariants
after every step; then replay one seed twice and diff state.
**Accept:** 0 invariant violations across all 3 levels; replay diff empty;
footer reports `ROUND 3 MET`.

---

**Deliberately deferred:** Tier 3 (`ugt playtest`). An LLM playtester could
reasonably judge puzzle discoverability, move-efficiency vs. optimal, or
whether the push mechanic reads as intuitive — this is not a claim that
Sokoban has nothing to judge. It's cut here to keep this specific example's
scope to Tiers 1/2 only, since `dice` and `escape-room` already demonstrate
the Tier 3 pattern end-to-end.
