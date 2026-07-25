# Tiny Escape Room (game) — Master Task List

Build the Node.js game per `PRD.md` in this folder.

## Orchestrator protocol

1. Check out the first `status: TODO` task whose `after:` are all DONE; set IN-PROGRESS.
2. Plan → 3. Code → 4. Review vs **Accept** → 5. Gate, commit `<ID>: <title>`, set DONE, update this file in the same commit.

**Gate (every task):** `npm test` (Node's built-in test runner, `node --test`) exits 0.

**Format check (optional):** none — omitted (no formatter chosen for this project).

**Standing constraints:**
- All rules live in `src/engine.js`. `src/cli.js` and `src/bridge.js` only
  translate input into `executeCommand()` calls — neither may contain a rule
  (a flag check, an exit lock, a puzzle effect) that isn't in the engine.
- `content/rooms.csv` and `content/objects.csv` are the only places
  room/object/puzzle content is defined — no hardcoded room or object data in
  `.js` files.
- The bridge's JSON-lines protocol (`reset`/`step`/`close`, response shape)
  must match `PRD.md` exactly — the integration side is written against this
  shape and cannot change it independently.

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---

## M0 — Scaffold + content loading

### T-001 · Project scaffold — `status: TODO` · `coder: sonnet` · `after: —`
`package.json`, `node --test` wired up, empty `src/engine.js` /
`src/cli.js` / `src/bridge.js`, empty `content/rooms.csv` /
`content/objects.csv` with header rows only.
**Accept:** `npm test` runs (0 tests ok); `node src/cli.js` starts and exits
cleanly on `Ctrl+D`.

### T-002 · CSV loader + validation — `status: TODO` · `coder: opus` · `after: T-001`
Parse both CSVs into in-memory room/object maps. Validate at load time: every
`exit_*` target room_id exists; every `entry_requires_flag` is set by *some*
object's `take_sets_flag`/`use_sets_flag`; no duplicate `room_id`/`object_id`.
**Accept:** unit tests cover a valid fixture CSV pair (loads clean) and at
least 3 invalid fixtures (dangling exit, unreachable flag, duplicate id) —
each throws a descriptive error.

## M1 — Content authoring

### T-003 · Author the 10-room adventure — `status: TODO` · `coder: opus` · `after: T-002`
Write the real `content/rooms.csv` (10 rooms) and `content/objects.csv`
(≤ 12 objects) per PRD's scope: a linear-with-branches flag chain ending at
`R10`.
**Accept:** loader (T-002) accepts the content with 0 validation errors; a
hand-written walkthrough (documented in a comment or fixture) reaches
`escaped: true` in ≤ 40 moves.

## M2 — Engine

### T-004 · `executeCommand` core — `status: TODO` · `coder: opus` · `after: T-003`
Implement movement, `take`/`drop`/`examine`/`use`/`look`/`inventory` against
loaded content, flag state, and the `escaped` transition on entering `R10`.
**Accept:** unit tests cover: locked-room entry refusal, `use` prerequisite
enforcement, `use_consumes` removing an item, and the full T-003 walkthrough
reaching `escaped: true`.

## M3 — Front ends

### T-005 · Human CLI — `status: TODO` · `coder: sonnet` · `after: T-004`
Free-text parser (8 verbs, direction shorthands) over `executeCommand()`;
prints descriptions/flavor text.
**Accept:** manual playthrough of the T-003 walkthrough via typed commands
reaches "You escape!"; unrecognized input prints a refusal without crashing.

### T-006 · Machine bridge (JSON-lines) — `status: TODO` · `coder: opus` · `after: T-004`
Build the fixed action table (movement + per-object verbs) and the
stdin/stdout JSON-lines loop per PRD's exact protocol.
**Accept:** piping the T-003 walkthrough (as `action_id`s) into `node
src/bridge.js` via stdin produces `escaped: true` in the final state; an
out-of-context action_id returns state unchanged (no-op) instead of erroring.

---

**Deliberately deferred:** NPCs, timers, save/load, hint system, colored
output — see PRD Non-goals.
