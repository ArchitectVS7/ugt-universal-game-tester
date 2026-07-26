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
  the `engine.type: custom` contract — it is not dispatched by
  `ugt/core/env.py` (its `ugt.config.yaml` declares `engine.type: custom`).
- **Every ladder script owns the bridge's lifecycle** — it spawns
  `godot4 --headless --path ../game -- --ugt-bridge --ugt-port=<port>` itself,
  waits for the port to accept a connection, and tears the process down on
  exit (including on failure). Attaching to an already-running bridge is a
  fallback for interactive debugging, not the normal path. This mirrors
  the way a subprocess adapter spawns its own harness rather than
  requiring a human to start it, and it is what `PRD.md` specifies for
  `connect()`. No ladder script may require a manual pre-step: a rung that
  only passes when someone started a server by hand cannot run unattended,
  and a rung that silently passes because it attached to a *stale* bridge
  from an earlier build is worse — verify the PID you spawned is the one
  listening (`lsof -nP -iTCP:<port> -sTCP:LISTEN`).

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---

## M0 — Transport

### T-001 · Spike: raw TCP round-trip — `status: DONE` · `coder: sonnet` · `after: —`
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

**Delivered (2026-07-26):** `bridge_process.py` (spawn / wait-for-listen / reap, refuses to attach to an occupied port) + `spike_sokoban.py` — **SPIKE MET, 14/14**. Cold start with no Godot running, exact message shapes, inert refusals, cross-write framing, deterministic replay, clean EOF on close, and no surviving process. Found a real defect while building this: a readiness probe that CONNECTS consumes the bridge's single connection slot and makes the real client race its re-accept (see README Finding 1); readiness is now read via lsof without connecting.

### T-002 · `GodotTcpAdapter` (`BaseAdapter`) — `status: DONE` · `coder: opus` · `after: T-001`
Wrap the spike's transport in a `BaseAdapter` subclass: `connect`/`reset`/
`step`/`close`, matching `../game/PRD.md`'s message shape.
**Accept:** `smoke_sokoban_adapter.py` (rung 2) does the same round-trip
through the adapter and exits 0.

## M1 — Correctness (Tier 1, R1/R2)

**Delivered (2026-07-26):** `godot_tcp_adapter.py` + `smoke_sokoban_adapter.py` — **SMOKE MET, 9/9**. Transport-only BaseAdapter with its own read buffer (TCP has no framing), owning the bridge lifecycle in connect()/close(). Verified the port is genuinely free again after close and that a second adapter can connect independently.

### T-003 · Invariants module — `status: DONE` · `coder: opus` · `after: T-002`
`invariants.py`: `moves_taken` monotonic, `player_x`/`player_y` in-bounds,
`boxes_on_target ≤ boxes_total`, reusable by R1/R2 and R3 (mirror
`ugt.core.trial.InvariantSuite`).
**Accept:** unit-callable; asserts pass against a known-good state sequence
and fail against a deliberately corrupted one (test fixture).

**Delivered (2026-07-26):** `invariants.py` — 8 predicates via `InvariantSuite`, one definition consumed by R1/R2 (`check_command`) and R3 (`to_hunter_invariants`) so the scripted and random tiers cannot drift. Proven able to fail: every rung feeds the suite a corrupted transition and requires violations. `moves_taken` monotonicity is scoped per level_index — the counter resets on level advance (README Finding 3).

### T-004 · `verify_round1.py`: one solved level — `status: DONE` · `coder: opus` · `after: T-003`
Drive level 1's solution — read it from `../game/levels/solutions.json`, the
artifact `../game`'s T-005 commits; never hardcode a copy here, or the two
drift — to `level_solved: true`; assert F1, F2, F4, F5 from the PRD's table;
check invariants after every step.
**Accept:** script prints `[PASS]`/`[FAIL]` per check and a `ROUND 1 MET —
p/t` footer; exits non-zero on any failure.

**Delivered (2026-07-26):** `verify_round1.py` — **ROUND 1 MET, 12/12**. Level 1 driven to a real solve from `../game/levels/solutions.json` (never a local copy). F1 wall no-op, F2 box push, F3 blocked no-op, F4 boxes_on_target increment, F5 level_solved all asserted; invariants after every one of 12 commands. Walls are found by PROBING the live game, not by parsing the level file — an adapter that read the grid would be re-implementing the rule it is testing.

### T-005 · `verify_round2.py`: full 3-level clear + no-op checks — `status: DONE` · `coder: opus` · `after: T-004`
All 3 levels back-to-back to `all_levels_solved: true`, again reading the
sequences from `../game/levels/solutions.json`; deliberately drive into a
wall and a blocked box to assert F1/F3 (no-op, state unchanged).
**Accept:** same PASS/FAIL + footer convention; exits non-zero on any
failure.

## M2 — Robustness (Tier 2, R3)

**Delivered (2026-07-26):** `verify_round2.py` — **ROUND 2 MET, 11/11**. All 3 shipped levels solved back to back over the wire (6 + 23 + 44 = 73 actions) to `all_levels_solved` with `terminated=True`; 83 commands, 0 invariant violations. No-op probes compare the WHOLE state rather than just position (README Finding 2).

### T-006 · `verify_round3.py`: exploit-hunter + replay — `status: DONE` · `coder: opus` · `after: T-005`
Random walk ≥100 steps per level via `ugt/core/exploit_hunter.py`, invariants
after every step; then replay one seed twice and diff state.
**Accept:** 0 invariant violations across all 3 levels; replay diff empty;
footer reports `ROUND 3 MET`.

**Delivered (2026-07-26):** `verify_round3.py` — **ROUND 3 MET, 7/7**. UGT's real ExploitHunter, 120 uniform-random steps x 2 seeds = 240 steps, zero findings, using the same invariant suite as R1/R2. Illegal action ids (-1, 4, 99, 1e9) proven state-inert with the bridge still healthy afterwards; two fresh processes replay a fixed sequence byte-identically (14 distinct states over 16 steps, so non-vacuous).

---

**Deliberately deferred:** Tier 3 (`ugt playtest`). An LLM playtester could
reasonably judge puzzle discoverability, move-efficiency vs. optimal, or
whether the push mechanic reads as intuitive — this is not a claim that
Sokoban has nothing to judge. It's cut here to keep this specific example's
scope to Tiers 1/2 only, since `dice` and `escape-room` already demonstrate
the Tier 3 pattern end-to-end.
