# Dice Duel — Game PRD

**One-liner:** A two-force D6 dice-pool skirmish. Each round both sides secretly
allocate a fixed die pool between Attack and Defense, roll simultaneously, and
apply net damage. War-game flavor text over a deliberately small, fully
deterministic ruleset — built to be tested, not to be deep.

**Why this example exists:** Demonstrate `/tasklist` + `/orchestrate` building a
small React game from a PRD, then UGT driving it through a **browser** adapter
(Playwright + `window` hooks) — the same transport swap `examples/browser-game`
shows, applied to a fresh game instead of a documentation stub.

## Stack

- React + Vite, no backend, no router, no external state library (plain
  `useState`/`useReducer` is enough).
- All game logic in a single pure module (`src/engine.js`) — the UI only renders
  state and dispatches actions. This mirrors UGT rule M1 (adapter/UI never
  re-implements rules) one level up: **the React component tree must not
  contain rules, only the engine module does.**

## Core loop

1. Round starts. Player picks one of 7 preset allocations (below). The AI
   opponent picks its own allocation via a fixed, seeded heuristic (no
   randomness in the *choice*, only in the dice).
2. Both pools roll simultaneously: each allocated d6 that shows 5 or 6 is a
   **hit**.
3. Net damage to each side = (opponent's attack hits) − (own defense hits),
   floored at 0.
4. Force Strength (FS) drops by net damage. Round counter increments.
5. Battle ends when either side's FS ≤ 0 (decisive win/loss) or after round 12
   (draw).

## Mechanics

- **Force Strength:** both sides start at 20.
- **Die pool:** 6 dice per round, allocated across Attack/Defense via one of 7
  fixed presets: `(6,0) (5,1) (4,2) (3,3) (2,4) (1,5) (0,6)`.
- **Bonus dice** (flavor: reinforcements/terrain/morale), all deterministic
  given state — no hidden RNG on *whether* they trigger:
  - **Morale surge:** if your FS > opponent's FS at round start, +1 Attack die
    this round ("advancing with confidence").
  - **Dug in:** if your FS ≤ 10 (half), +1 Defense die this round ("soldiers
    dig in").
  - **Reinforcements:** exactly once, at the start of round 3, +2 dice to
    whichever pool the player allocated the most to that round.
- **RNG discipline (required for UGT R3 determinism):** dice rolls must be a
  pure function of `(seed, roll_counter)`, with `roll_counter` stored in game
  state and incremented once per die rolled — never call the platform RNG
  (`Math.random`) directly. Mirror `examples/harness-game/engine.py`'s
  `rng_counter` pattern.
- **AI opponent:** deterministic heuristic — allocate defense dice
  proportional to `1 - own_FS/20` (rounded to nearest preset), rest to attack.
  No hidden state, no RNG in the decision.

## UGT hooks required (the game/integration contract)

Exposed on `window` for the Playwright adapter, matching
`examples/browser-game`'s pattern:

- `window.__GET_STATE__()` →
  ```json
  {
    "player": {"force_strength": 20, "bonus_dice": 0},
    "enemy":  {"force_strength": 20, "bonus_dice": 0},
    "round_number": 0,
    "battle_over": false,
    "winner": null
  }
  ```
  `winner` ∈ `null | "player" | "enemy" | "draw"`, set only when `battle_over`
  is true.
- `window.__SEND_ACTION__(actionId)` — `actionId` 0-6 maps to the 7 allocation
  presets above (0 = all-attack `(6,0)` … 6 = all-defense `(0,6)`); resolves
  one full round (both sides act, dice roll, damage applies) and returns the
  new state.
- `window.__RESET__(seed)` — new battle, FS reset to 20/20, `roll_counter`
  reset, RNG reseeded.
- A visible round log in the UI (for human readability) is expected but not
  part of the UGT contract.

## Non-goals

No multiplayer/networking, no persistence/save, no animations beyond a simple
dice/HP display, no additional unit types, no difficulty settings, no
accessibility pass, no mobile layout.

## Acceptance criteria

- `npm run build` produces a static bundle servable by any static file server
  (matches `examples/browser-game/serve.py`'s expectation).
- A full battle (12 rounds or a decisive FS ≤ 0) completes without console
  errors.
- Same seed + same action sequence (via `__SEND_ACTION__`) reproduces
  byte-identical state at every round.
