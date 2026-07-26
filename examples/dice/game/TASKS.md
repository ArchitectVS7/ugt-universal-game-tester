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

### T-001 · Vite + React scaffold — `status: DONE` · `coder: sonnet` · `after: —`
Initialize a Vite React project in this folder. Add Vitest for unit tests and
ESLint. No routing, no state library.
**Accept:** `npm run build` exits 0; `npm test -- --run` runs (0 tests ok);
`npm run lint` exits 0.

**Delivered (2026-07-25):** Scaffolded the project with Vite's React template
(`package.json`, `vite.config.js`, `index.html`, `src/`), added Vitest for
unit testing and ESLint for lint checks, and committed the generated
`.gitignore` alongside `package-lock.json`. Scope was held to the bare
scaffold only — no routing library, no state-management library, no engine
code, and no UI beyond the template default, all deliberately deferred to
their own later tasks (T-002 onward) per this file's task boundaries.
Orchestration: graphify=none — no `graphify-out/graph.json` exists at the
repo root or in `examples/dice/game`, and T-001 is a self-contained scaffold
task with no existing source to m · attempts=1/4.

## M1 — Engine

### T-002 · Seeded RNG + dice resolution — `status: DONE` · `coder: opus` · `after: T-001`
Implement `src/engine.js`: a seeded RNG keyed by `(seed, roll_counter)`, and a
`rollPool(n)` helper that rolls `n` d6 and counts 5-6 hits, advancing
`roll_counter` once per die.
**Accept:** unit tests assert the same `(seed, roll_counter)` always returns
the same roll; two different `roll_counter` values for the same seed differ
at least once across 20 samples.

**Delivered (2026-07-25):** Implemented `src/engine.js` with `rollDie(seed,
rollCounter)` (FNV-1a string hash over `${seed}:${rollCounter}` plus a
splitmix32 finalizer for bit avalanche, reduced mod 6 for the face), `isHit`
for the 5-6 threshold, and `rollPool(n, seed, rollCounter)` which rolls `n`
dice at consecutive counter values, counts hits, and returns the advanced
counter without mutating any input — no `Math.random()` anywhere and no
module-level state, so calls are pure and reproducible. `src/engine.test.js`
covers same-`(seed, roll_counter)` reproducibility, divergence across 20
distinct roll_counter samples, the `n === 0` empty-pool case, and
counter-advancement bookkeeping. Scope was held to the RNG/roll-resolution
layer only — round resolution, allocation presets, bonus-dice rules, battle
end conditions, the AI opponent, and all UI/hooks work are deliberately left
for T-003 onward per this file's task boundaries.
Orchestration: graphify=none — no `graphify-out/graph.json` exists at the
repo root or in `examples/dice/`, so there is no graph to query. · attempts=1/4.

### T-003 · Round resolution + bonus-dice rules — `status: TODO` · `coder: opus` · `after: T-002`
Implement the 7 allocation presets, the Morale surge / Dug in / Reinforcements
bonus rules, and full round resolution (both sides act, damage applies, FS
updates, round increments) per PRD.
**Accept:** unit tests cover: all-attack vs all-defense damage math; Morale
surge triggers only when FS is strictly greater; Dug in triggers at FS ≤ 10;
Reinforcements fires exactly once, at round 3, for each side independently,
added to whichever pool that side allocated the most to that round (ties →
Attack).

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
bars; a Vitest component test spies on `console.error`/`console.warn` during
a scripted multi-round battle and asserts zero calls.

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
