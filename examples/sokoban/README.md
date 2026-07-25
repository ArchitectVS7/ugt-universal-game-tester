# Example: `sokoban` — Sokoban Mini (planned)

A 4-direction push-crate puzzle, built in Godot, driven through a
**hand-written, engine-first TCP adapter** (the same pattern
`../harness-game` uses — Godot has no built-in UGT engine type). **Status:
PRD + TASKS.md only — not yet built.**

- [`game/PRD.md`](game/PRD.md) + [`game/TASKS.md`](game/TASKS.md) — the
  Godot game, including the level format and the `--ugt-bridge` TCP protocol.
- [`integration/PRD.md`](integration/PRD.md) + [`integration/TASKS.md`](integration/TASKS.md) —
  the adapter, feature map, and trial ladder (`spike`/`smoke`/
  `verify_round1-3`, same shape as `../harness-game`).

## Build order

1. `cd game && /orchestrate all` — builds the Godot project per `game/TASKS.md`.
2. Export a headless build (or run in-editor with `--headless`).
3. `cd ../integration && /orchestrate all` — builds the TCP adapter and
   ladder scripts per `integration/TASKS.md`.
