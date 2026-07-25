# Dice Duel (game) — Master Task List

Build the React game per `PRD.md` in this folder.

## Orchestrator protocol

1. Check out the first `status: TODO` task whose `after:` are all DONE; set IN-PROGRESS.
2. Plan → 3. Code → 4. Review vs **Accept** → 5. Gate, commit `<ID>: <title>`, set DONE, update this file in the same commit.

**Gate (every task):** `npm test -- --run` (Vitest) and `npm run build` (Vite) both exit 0.

**Format check (optional):** `npm run lint`

**Standing constraints:**
- All game rules live in `src/engine.js`; React components only render state
  and dispatch actions (no rules in JSX/handlers).
- Dice rolls are a pure function of `(seed, roll_counter)`; `roll_counter` is
  part of state. Never call `Math.random()` outside the seeded RNG.
- `window.__GET_STATE__` / `window.__SEND_ACTION__` / `window.__RESET__` must
  match `PRD.md`'s UGT hooks contract exactly — the integration side is written
  against this shape and cannot be changed independently.

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---

## M0 — Scaffold

### T-001 · Vite + React scaffold — `status: TODO` · `coder: sonnet` · `after: —`
Initialize a Vite React project in this folder. Add Vitest for unit tests and
ESLint. No routing, no state library.
**Accept:** `npm run build` exits 0; `npm test -- --run` runs (0 tests ok);
`npm run lint` exits 0.

## M1 — Engine

### T-002 · Seeded RNG + dice resolution — `status: TODO` · `coder: opus` · `after: T-001`
Implement `src/engine.js`: a seeded RNG keyed by `(seed, roll_counter)`, and a
`rollPool(n)` helper that rolls `n` d6 and counts 5-6 hits, advancing
`roll_counter` once per die.
**Accept:** unit tests assert the same `(seed, roll_counter)` always returns
the same roll; two different `roll_counter` values for the same seed differ
at least once across 20 samples.

### T-003 · Round resolution + bonus-dice rules — `status: TODO` · `coder: opus` · `after: T-002`
Implement the 7 allocation presets, the Morale surge / Dug in / Reinforcements
bonus rules, and full round resolution (both sides act, damage applies, FS
updates, round increments) per PRD.
**Accept:** unit tests cover: all-attack vs all-defense damage math; Morale
surge triggers only when FS is strictly greater; Dug in triggers at FS ≤ 10;
Reinforcements fires exactly once, at round 3, added to the larger-allocated
pool.

### T-004 · Battle end conditions — `status: TODO` · `coder: sonnet` · `after: T-003`
Implement `battle_over` / `winner` per PRD (FS ≤ 0 decisive win/loss; round 12
reached with both sides alive → draw).
**Accept:** unit tests cover decisive win, decisive loss, and
draw-by-round-cap; `winner` is `null` while `battle_over` is `false`.

### T-005 · Deterministic AI opponent — `status: TODO` · `coder: sonnet` · `after: T-003`
Implement the AI allocation heuristic (`defense dice ∝ 1 - own_FS/20`, rounded
to nearest preset, remainder to attack). No RNG in the choice.
**Accept:** unit test asserts the AI's chosen preset is a pure function of its
current FS (same FS → same preset, across repeated calls).

## M2 — UI + UGT hooks

### T-006 · Round log + HP display — `status: TODO` · `coder: sonnet` · `after: T-004, T-005`
Build the React UI: FS bars for both sides, a scrolling round log with flavor
text ("Your soldiers charge forward!", "Enemy reinforcements arrive!"), and 7
allocation buttons.
**Accept:** manual allocation click resolves a round and updates the log and
bars; build has no console errors.

### T-007 · Window hooks for UGT — `status: TODO` · `coder: opus` · `after: T-006`
Expose `window.__GET_STATE__`, `window.__SEND_ACTION__(actionId)`,
`window.__RESET__(seed)` per PRD's exact shape.
**Accept:** unit/integration test drives a full 12-round battle via
`__SEND_ACTION__` only (no UI clicks) and matches `__GET_STATE__` at each
step; same seed + same action sequence reproduces identical state twice in a
row.

---

**Deliberately deferred:** multiplayer, persistence, animations, additional
unit types, difficulty settings, mobile layout — see PRD Non-goals.
