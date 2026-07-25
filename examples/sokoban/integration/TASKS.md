# Sokoban Mini (integration) — Master Task List

Build the UGT-side adapter and trial ladder per `PRD.md` in this folder,
against `../game`.

## Orchestrator protocol

1. Check out the first `status: TODO` task whose `after:` are all DONE; set IN-PROGRESS.
2. Plan → 3. Code → 4. Review vs **Accept** → 5. Gate, commit `<ID>: <title>`, set DONE, update this file in the same commit.

**Gate (every task):** `python -m py_compile *.py` and the ladder script(s)
introduced so far all exit 0.

**Standing constraints:**
- No push/collision/win logic here — every rule lives in
  `../game/scripts/board.gd`. This folder only transports state and actions.
- `GodotTcpAdapter` is constructed directly by each ladder script, per
  `examples/harness-game`'s precedent — it is not wired into
  `ugt/core/env.py`'s `engine.type` dispatch.
- `../game` must export/run headless with `--ugt-bridge` before any ladder
  script beyond the spike can pass.

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---

## M0 — Transport

### T-001 · Spike: raw TCP round-trip — `status: TODO` · `coder: sonnet` · `after: —`
`spike_sokoban.py`: launch (or attach to) the headless Godot bridge, open a
TCP socket, send `reset` then one `step`, print both responses, close
cleanly. No adapter class.
**Accept:** script exits 0 and prints a valid `state` dict from both
commands.

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

### T-004 · `verify_round1.py` — one solved level — `status: TODO` · `coder: opus` · `after: T-003`
Drive level 1's documented solution to `level_solved: true`; assert F1, F2,
F4, F5 from the PRD's table; check invariants after every step.
**Accept:** script prints `[PASS]`/`[FAIL]` per check and a `ROUND 1 MET —
p/t` footer; exits non-zero on any failure.

### T-005 · `verify_round2.py` — full 3-level clear + no-op checks — `status: TODO` · `coder: opus` · `after: T-004`
All 3 levels back-to-back to `all_levels_solved: true`; deliberately drive
into a wall and a blocked box to assert F1/F3 (no-op, state unchanged).
**Accept:** same PASS/FAIL + footer convention; exits non-zero on any
failure.

## M2 — Robustness (Tier 2, R3)

### T-006 · `verify_round3.py` — exploit-hunter + replay — `status: TODO` · `coder: opus` · `after: T-005`
Random walk ≥100 steps per level via `ugt/core/exploit_hunter.py`, invariants
after every step; then replay one seed twice and diff state.
**Accept:** 0 invariant violations across all 3 levels; replay diff empty;
footer reports `ROUND 3 MET`.

---

**Deliberately deferred:** Tier 3 (`ugt playtest`) — Sokoban has no
balance/strategy dimension worth an LLM judgment call; noted here rather than
silently skipped.
