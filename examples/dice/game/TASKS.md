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

### T-003 · Round resolution + bonus-dice rules — `status: DONE` · `coder: opus` · `after: T-002`
Implement the 7 allocation presets, the Morale surge / Dug in / Reinforcements
bonus rules, and full round resolution (both sides act, damage applies, FS
updates, round increments) per PRD.
**Accept:** unit tests cover: all-attack vs all-defense damage math; Morale
surge triggers only when FS is strictly greater; Dug in triggers at FS ≤ 10;
Reinforcements fires exactly once, at round 3, for each side independently,
added to whichever pool that side allocated the most to that round (ties →
Attack).

**Delivered (2026-07-25):** Added the round-resolution layer to `src/engine.js`
below T-002's RNG layer (T-002's exports untouched): the frozen `ALLOCATIONS`
table of the 7 presets in `__SEND_ACTION__` id order, `createInitialState(seed)`,
a single symmetric `sideBonuses()` helper both sides call (so player and enemy
rules cannot drift), and `resolveRound(state, playerPresetIndex,
enemyPresetIndex)` — which reads every bonus off the pre-damage round-start
snapshot, rolls the four pools in a fixed order (player attack → player defense
→ enemy attack → enemy defense, threading `roll_counter` one tick per die),
applies `max(0, opponent attack hits − own defense hits)` to both sides
simultaneously, floors FS at exactly 0, increments the round, and returns a
brand-new state plus a structured `last_round` record appended to `log` (data
only, no flavor strings — T-006 renders prose from it). Decisions pinned in
comments so later tasks agree: `round_number` counts *completed* rounds so the
round being resolved is `round_number + 1` (reinforcements fire when that equals
3); reinforcement routing reads the side's **base** preset, `>=` sending the
(3,3) tie to Attack, so a morale/dug-in die can never redirect it; `bonus_dice`
is the total granted in the round just resolved. `src/round.test.js` adds 49
tests covering each Accept clause — all-attack vs all-defense damage math with
golden literals cross-checked against an independent `rollPool` computation,
morale's strict-greater boundary (20/19, 19/20, ties), dug-in's 11/10/9
boundary per side independently, and reinforcements firing exactly once at
round 3 across a 12-round battle, routed per side by its own allocation —
plus FS-clamp, no-heal, immutability, counter-advance, same-seed replay and
`Math.random`-throws discipline checks. Every rule branch was mutation-checked
(`>` → `>=`, `<=` → `<`, dropped `Math.max` floors, `===` → `>=` on the
reinforcement round): all six mutants were killed by the suite, so nothing is
vacuously green. Scope held to this layer — `battle_over`/`winner` are carried
through unchanged with the entry guard deliberately left off (T-004), the enemy
allocation is an explicit parameter with no placeholder AI (T-005), and no UI
or `window.__*__` hook was touched (T-006/T-007). Gate: `npm test -- --run`
70/70 green, `npm run build` and `npm run lint` both clean.
Orchestration: graphify=none — no `graphify-out/graph.json` exists in the repo root (`examples/dice/game`) or anywhere above it; the task area is two files (`src/engine.js`, its test)  · attempts=1/4.

### T-004 · Battle end conditions — `status: DONE` · `coder: sonnet` · `after: T-003`
Implement `battle_over` / `winner` per PRD (FS ≤ 0 decisive win/loss; round 12
reached with both sides alive → draw).
**Accept:** unit tests cover decisive win, decisive loss, and
draw-by-round-cap; `winner` is `null` while `battle_over` is `false`.

**Delivered (2026-07-25):** Added `evaluateOutcome(playerFS, enemyFS,
roundNumber)` to `src/engine.js` as the single source of truth for
`battle_over`/`winner`, and wired it into `resolveRound` so end conditions are
re-derived every round from the post-damage FS and the completed round count
rather than carried through from the previous state. Precedence is pinned:
a same-round mutual knockout (both sides ≤ 0) resolves as `"draw"` before the
one-sided checks, decisive FS ≤ 0 checks come before the round-cap draw (so a
round-12 knockout is decisive, not a draw), and both comparisons use `<=`/`>=`
rather than `===` so a hand-built or rewound state is still handled correctly.
Also added a post-battle no-op guard (D10) to `resolveRound`: once
`battle_over` is true, further calls return the same state object unchanged
(no throw), which keeps `roll_counter` frozen for same-seed replay and matches
the PRD's no-console-errors acceptance bar for a black-box `__SEND_ACTION__`
driver that may keep sending actions after the battle ends. New
`src/battle.test.js` (28 tests) covers `evaluateOutcome` in isolation
(decisive win/loss, the D9 mutual-destruction draw, `<=`/`>=` boundary
correctness) plus `resolveRound` integration (draw-by-round-cap, winner stays
`null` while in progress, the post-battle no-op by reference equality);
`src/round.test.js` was updated to point its old "leaves battle_over to
T-004" placeholder at the real behavior. Scope was held to this layer only —
the AI opponent's allocation heuristic (T-005) and all UI/`window.__*__` hook
work (T-006/T-007) were deliberately left untouched. Gate: `npm test -- --run`
green, `npm run build` and `npm run lint` both clean.
Orchestration: graphify=none — no `graphify-out/graph.json` exists in this
repo root (`examples/dice/game`) or above it, so there is no graph to query; I
grounded the plan in `PRD.md`, · attempts=1/4.

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
