# Example: `escape-room` — Tiny Escape Room (planned)

A 10-room, CSV-authored text adventure, built in Node.js, driven through
UGT's built-in **simulation** adapter. **Status: PRD + TASKS.md only — not
yet built.**

- [`game/PRD.md`](game/PRD.md) + [`game/TASKS.md`](game/TASKS.md) — the
  Node.js game, including the `rooms.csv`/`objects.csv` authoring format.
- [`integration/PRD.md`](integration/PRD.md) + [`integration/TASKS.md`](integration/TASKS.md) —
  the UGT-side config, feature map, and trial ladder.

## Build order

1. `cd game && /orchestrate all` — builds the Node.js game per `game/TASKS.md`.
2. `cd ../integration && /orchestrate all` — wires up and runs the UGT ladder
   per `integration/TASKS.md` (no export step needed — `ugt.config.yaml`
   points straight at `../game/src/bridge.js`).
