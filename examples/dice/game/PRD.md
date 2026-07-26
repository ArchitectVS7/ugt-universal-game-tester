# Dice Duel — Game PRD

**One-liner:** A two-force D6 dice-pool skirmish. Each round both sides secretly
allocate a fixed die pool between Attack and Defense, roll simultaneously, and
apply net damage. War-game flavor text over a deliberately small, fully
deterministic ruleset — built to be tested, not to be deep.

**Why this example exists:** Demonstrate `/tasklist` + `/orchestrate` building a
small React game from a PRD.

## Stack

- React + Vite, no backend, no router, no external state library (plain
  `useState`/`useReducer` is enough).
- All game logic in a single pure module (`src/engine.js`) — the UI only renders
  state and dispatches actions: **the React component tree must not contain
  rules, only the engine module does.**

## Core loop

1. Round starts. Player picks one of 7 preset allocations (below). The AI
   opponent picks its own allocation via a fixed, seeded heuristic (no
   randomness in the *choice*, only in the dice).
2. Both pools roll simultaneously: each allocated d6 that shows 5 or 6 is a
   **hit**.
3. Net damage to each side = (opponent's attack hits) − `DEFENSE_BLOCK` × (own
   defense hits), floored at 0. `DEFENSE_BLOCK` is 2: one defense hit cancels
   two attack hits.
4. Force Strength (FS) drops by net damage. Round counter increments.
5. Battle ends when either side's FS ≤ 0 (decisive win/loss), or at the round 12
   cap — where the side with the **higher FS wins on points**, and only an exact
   tie is a draw.

## Mechanics

- **Force Strength:** both sides start at `STARTING_FS` (8), floored at 0 (a hit that would
  take FS negative clamps it to exactly 0, not below).
- **Die pool:** 6 dice per round, allocated across Attack/Defense via one of 7
  fixed presets: `(6,0) (5,1) (4,2) (3,3) (2,4) (1,5) (0,6)`.
- **Bonus dice** (flavor: reinforcements/terrain/morale), all deterministic
  given state — no hidden RNG on *whether* they trigger:
  - **Morale surge:** if your FS > opponent's FS at round start, +1 Attack die
    this round ("advancing with confidence").
  - **Dug in:** if your FS ≤ `DUG_IN_THRESHOLD` (4, half), +1 Defense die this round ("soldiers
    dig in").
  - **Reinforcements:** exactly once, at the start of round 3, each side
    independently gains +2 dice added to whichever pool *that side*
    allocated the most to that round (a tie splits toward Attack).
- **RNG discipline (required for deterministic replay):** dice rolls must be a
  pure function of `(seed, roll_counter)`, with `roll_counter` stored in game
  state and incremented once per die rolled — never call the platform RNG
  (`Math.random`) directly. This RNG-in-state pattern is what makes a same-seed
  replay byte-identical.
- **AI opponent:** deterministic heuristic — allocate defense dice
  proportional to `1 - own_FS/STARTING_FS` (rounded to nearest preset), rest to attack.
  No hidden state, no RNG in the decision.

## UI

- FS bars for both sides and 7 allocation buttons.
- A visible round log, newest round first, with flavor text derived from what
  the engine recorded that round (bonuses granted, damage taken, posture).
- `winner` ∈ `null | "player" | "enemy" | "draw"`, surfaced as an outcome
  banner only once `battle_over` is true, plus a reset control that starts a
  new battle with FS back to `STARTING_FS` on both sides and `roll_counter`
  reset.

## Non-goals

No multiplayer/networking, no persistence/save, no animations beyond a simple
dice/HP display, no additional unit types, no difficulty settings, no
accessibility pass, no mobile layout.

## Acceptance criteria

- `npm run build` produces a static bundle servable by any static file server.
- A full battle (12 rounds or a decisive FS ≤ 0) completes without console
  errors.
- Same seed + same allocation sequence reproduces byte-identical state at every
  round.
