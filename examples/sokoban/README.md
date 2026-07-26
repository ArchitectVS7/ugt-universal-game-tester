# Example: `sokoban` — Sokoban Mini (planned)

A 4-direction push-crate puzzle, built in Godot, driven through a
**hand-written, engine-first TCP adapter** (the same pattern
UGT's built-in engines cannot cover — Godot has no built-in engine type). **Status:
PRD + TASKS.md only — not yet built.**

**Prerequisite:** a local `godot4` CLI binary (Godot 4.x) on `PATH`. Unlike
`dice`/`escape-room`, there's no zero-dependency fallback here — every task
in both `game/TASKS.md` and `integration/TASKS.md` gates on it.

- [`game/PRD.md`](game/PRD.md) + [`game/TASKS.md`](game/TASKS.md) — the
  Godot game, including the level format and the `--ugt-bridge` TCP protocol.
- [`integration/PRD.md`](integration/PRD.md) + [`integration/TASKS.md`](integration/TASKS.md) —
  the adapter, feature map, and trial ladder (`spike`/`smoke`/
  `verify_round1-3` — the canonical trial-ladder shape).

## Build order

1. `cd game && /orchestrate all` — builds the Godot project per `game/TASKS.md`.
2. Export a headless build (or run in-editor with `--headless`).
3. `cd ../integration && /orchestrate all` — builds the TCP adapter and
   ladder scripts per `integration/TASKS.md`.
