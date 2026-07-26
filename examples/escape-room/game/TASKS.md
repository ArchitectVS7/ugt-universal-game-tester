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

### T-001 · Project scaffold — `status: DONE` · `coder: sonnet` · `after: —`
`package.json`, `node --test` wired up, empty `src/engine.js` /
`src/cli.js` / `src/bridge.js`, empty `content/rooms.csv` /
`content/objects.csv` with header rows only.
**Accept:** `npm test` runs (0 tests ok); `node src/cli.js` starts and exits
cleanly on `Ctrl+D`.

**Delivered (2026-07-25):** Added `package.json` (ESM, `node --test` as the
`test` script, `start`/`bridge` convenience scripts, `node >=20` engine pin);
header-only `content/rooms.csv` and `content/objects.csv`; and scaffold
`src/engine.js` / `src/cli.js` / `src/bridge.js`. The engine's three exports
(`loadContent`/`createGame`/`executeCommand`) are signatures only, each
throwing a "not implemented yet (T-00N)" error, so `cli.js`'s REPL and
`bridge.js`'s documented JSON-lines protocol comment wire cleanly against the
real entry points without pulling any rule logic ahead of T-002/T-004/T-006 —
the deliberate scope boundary for this task. No CSV content, no engine
behavior, and no bridge protocol implementation are in this commit.
Orchestration: graphify=none — no graphify-out/graph.json in this repo; task is a self-contained project scaffold · attempts=1/4.

### T-002 · CSV loader + validation — `status: DONE` · `coder: opus` · `after: T-001`
Parse both CSVs into in-memory room/object maps. Validate at load time: every
`exit_*` target room_id exists; every `entry_requires_flag` is set by *some*
object's `take_sets_flag`/`use_sets_flag`; no duplicate `room_id`/`object_id`.
**Accept:** unit tests cover a valid fixture CSV pair (loads clean) and at
least 3 invalid fixtures (dangling exit, unreachable flag, duplicate id) —
each throws a descriptive error.

**Delivered (2026-07-25):** Implemented `parseContent()`/`loadContent()` in
`src/engine.js`: a small hand-rolled CSV parser (quoted-field support, `""`
escaping, BOM/CRLF tolerance), strict header-shape checks against the
`ROOM_COLUMNS`/`OBJECT_COLUMNS` schema, and a `validate()` pass that collects
every violation before throwing a single descriptive `ContentError` — dangling
`exit_*` targets, `entry_requires_flag`/`use_requires_flag` values no object's
`take_sets_flag`/`use_sets_flag` ever sets, and duplicate `room_id`/
`object_id`. `test/loader.test.js` covers a valid fixture pair plus four
invalid fixtures (dangling exit, unreachable flag, duplicate room id,
duplicate object id) — one more than Accept's floor of three. Scope boundary:
no engine state/movement/command logic (`createGame`/`executeCommand` remain
T-004's stubs) and no real adventure content — only the loader and its
fixtures landed here.
Orchestration: graphify=none — no graphify-out/graph.json in this repo (checked repo root); orientation came from PRD.md, TASKS.md, and the T-001 scaffold in src/. · attempts=1/4.

## M1 — Content authoring

### T-003 · Author the 10-room adventure — `status: DONE` · `coder: opus` · `after: T-002`
Write the real `content/rooms.csv` (10 rooms) and `content/objects.csv`
(≤ 12 objects) per PRD's scope: a linear-with-branches flag chain ending at
`R10`. Also produce `content/walkthrough.json`: a flat array of
`{"verb": <string>, "object": <object_id or direction>}` steps from the
start room to `R10`, e.g.
`[{"verb":"take","object":"key_brass"},{"verb":"go","object":"north"}, ...]`.
**Accept:** loader (T-002) accepts the content with 0 validation errors; a
walkthrough move sequence (room-by-room verb+object list) is committed as a
fixture (`content/walkthrough.json`) and hand-traced against the CSVs to
confirm it reaches `R10` while satisfying every `entry_requires_flag` and
`use_requires_flag` it crosses. This task's Accept is a structural/traced
check, not an executed one — the engine to actually *run* the sequence
doesn't exist until T-004, which re-verifies the same fixture by running it.

**Delivered (2026-07-25):** Wrote the real `content/rooms.csv` (a 10-room
prison-escape map, R01→R10, linear-with-branches: Watch Post and Flooded
Cistern are dead-end side rooms off the main spine) and `content/objects.csv`
(11 objects: a map-scrap/rusted-helmet/stone-mural red herring in each of
three rooms, plus the real chain — iron key opens the banded door, lantern +
oil flask lets you read the vented steam pipe, valve wheel vents it, bronze
cog + ledger yield the hour to set the gallery clock, and the resulting
skeleton key opens the outer gate into R10). Added `content/walkthrough.json`
(a 27-step verb/object fixture tracing start to escape) and
`test/content.test.js`, a new executed check (not just hand-traced) that
loads the real CSVs through the T-002 loader and walks the fixture against
the exits/flags/takeable/use_requires_flag/use_consumes the CSV columns
declare, confirming 0 validation errors, exactly 10 rooms, ≤ 12 objects, the
action-space budget, and that the walkthrough reaches R10 satisfying every
gate it crosses. Scope boundary: this is still a structural/simulated trace
against the CSV's declared rules, not a run through `executeCommand()` — no
engine logic was added or changed, and T-004 remains the task that re-verifies
this same fixture by actually executing it.
Orchestration: graphify=none — no `graphify-out/graph.json` in the repo (checked repo root); orientation came from PRD.md, TASKS.md, and the T-002 loader in `src/engine.js`. · attempts=1/4.

## M2 — Engine

### T-004 · `executeCommand` core — `status: TODO` · `coder: opus` · `after: T-003`
Implement movement, `take`/`drop`/`examine`/`use`/`look`/`inventory` against
loaded content, flag state, and the `escaped` transition on entering `R10`.
**Accept:** unit tests cover: locked-room entry refusal, `use` prerequisite
enforcement, `use_consumes` removing an item, and running T-003's
`content/walkthrough.json` fixture through `executeCommand()` end-to-end
reaches `escaped: true`.

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
