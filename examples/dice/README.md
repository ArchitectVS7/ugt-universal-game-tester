# Example: `dice` — Dice Duel (planned)

A D6 dice-pool war-game duel, built in React, driven through UGT's **browser**
adapter. **Status: PRD + TASKS.md only — not yet built.**

- [`game/PRD.md`](game/PRD.md) + [`game/TASKS.md`](game/TASKS.md) — the React game itself.
- [`integration/PRD.md`](integration/PRD.md) + [`integration/TASKS.md`](integration/TASKS.md) —
  the UGT-side config, feature map, and trial ladder.

## Build order

1. `cd game && /orchestrate all` — builds the React app per `game/TASKS.md`.
2. `npm run build` (in `game/`) to produce a servable bundle.
3. `cd ../integration && /orchestrate all` — wires up and runs the UGT ladder
   per `integration/TASKS.md`.

Same two-file (PRD + TASKS.md), two-folder (game/integration) split as the
other planned examples — see `../README.md` for why.
