# Tiny Escape Room — Game PRD

**One-liner:** A 10-room, CSV-authored text-adventure escape room. No combat,
no monsters — pure exploration, inventory, and flag-gated puzzles. New
adventures are authored entirely by editing `rooms.csv` and `objects.csv`; no
code changes needed for new content.

**Why this example exists:** Demonstrate `/tasklist` + `/orchestrate` building
a Node.js CLI game from a PRD, then UGT driving it through the built-in
**simulation** (subprocess JSON-lines) adapter — the same transport
`examples/mock-game` uses, in Node instead of Python, against a genuinely
content-rich game instead of a toy economy.

## Stack

Node.js, no dependencies beyond a CSV parser (e.g. a single small hand-rolled
parser — no framework needed for 2 flat files). One process, two front ends
over one core:

- **`src/engine.js`** — loads the CSVs, holds the only game-state mutation
  logic, exposes `executeCommand(verb, objectId | direction)`. This is the
  single place rules live (UGT rule M1, one level up, same discipline as the
  Dice Duel engine module).
- **`src/cli.js`** — human-facing REPL: parses free text ("take key", "go
  north", "use lantern") into `executeCommand()` calls, prints room
  descriptions and flavor text.
- **`src/bridge.js`** — machine-facing JSON-lines loop (stdin/stdout) for
  UGT: maps a numeric `action_id` to a fixed `(verb, objectId|direction)`
  pair and calls the same `executeCommand()`. **Never re-implements a rule**
  — only translates.

## Content format (the CSV authoring contract)

### `content/rooms.csv`

| column | meaning |
|---|---|
| `room_id` | unique id, e.g. `R01` |
| `name` | display name |
| `description` | shown on entry / `look` |
| `exit_north`, `exit_south`, `exit_east`, `exit_west` | target `room_id` or empty (no exit) |
| `entry_requires_flag` | flag name that must be `true` to enter; empty = unlocked |

### `content/objects.csv`

| column | meaning |
|---|---|
| `object_id` | unique id, e.g. `key_brass` |
| `name` | display name, matched case-insensitively by the parser |
| `start_room` | starting `room_id`, or `INV` to start in inventory |
| `description` | shown on `examine` |
| `takeable` | `true`/`false` |
| `take_sets_flag` | flag set immediately on successful `take` (empty = none) |
| `use_verb` | the verb this object responds to (e.g. `unlock`, `open`, `light`); empty = not usable |
| `use_requires_flag` | flag that must already be `true` for `use` to succeed (empty = no prerequisite) |
| `use_sets_flag` | flag set on successful `use` (empty = none) |
| `use_consumes` | `true`/`false` — removed from inventory after a successful use |
| `use_success_text` / `use_fail_text` | flavor text shown on each outcome |

**Scope for this example:** exactly 10 rooms, ≤ 12 objects, a single
linear-with-branches flag chain ending in one exit room (`R10`) whose
`entry_requires_flag` is the final puzzle's flag.

## Parser verbs (human CLI)

`look` · `go <direction>` (also `n`/`s`/`e`/`w`) · `take <object>` ·
`drop <object>` · `inventory` / `inv` · `examine <object>` · `use <object>` ·
`help`. Unrecognized input or an inapplicable action (wrong room, missing
prerequisite, already held) prints a short in-fiction refusal and consumes no
state.

## UGT hooks required (the game/integration contract)

`bridge.js` speaks newline-delimited JSON on stdin/stdout, matching UGT's
`SubprocessAdapter` protocol exactly:

- `{"command": "reset"}` → `{"state": {...}}`
- `{"command": "step", "action_id": N}` → `{"state": {...}, "terminated": bool, "truncated": bool, "info": {}}`
- `{"command": "close"}` → clean process exit

State shape:

```json
{
  "current_room": "R05",
  "inventory": ["key_brass", "lantern"],
  "flags": {"has_brass_key": true, "found_map": false},
  "moves_taken": 14,
  "rooms_visited": 6,
  "escaped": false
}
```

`escaped` becomes `true` the moment the player successfully enters `R10`;
`terminated` in the bridge's step response should mirror it.

**Fixed discrete action space** (built once at startup from the CSVs, so it's
stable across the whole run): 4 movement actions + `look` + `inventory` +
`take`/`drop`/`examine`/`use` for every object that supports each verb.
Target ≤ 60 total actions for this content scope. An action invalid in the
current context (e.g. `use` on an object not held, `take` on something not in
the room) is a no-op that still returns state (mirrors the CLI's in-fiction
refusal, just without the flavor text).

## Non-goals

No monsters/combat/NPCs, no timers or countdowns, no save/load, no hint
system, no colored terminal output requirement, no branching narrative beyond
the flag-gated room chain.

## Acceptance criteria

- `node src/cli.js` is playable start-to-finish by a human with only the 8
  verbs above.
- `node src/bridge.js` under the exact JSON-lines protocol above completes a
  full escape (`escaped: true`) given the correct action sequence.
- Same action sequence from a fresh `reset` reproduces identical state every
  time (the engine has no hidden randomness — CSV-driven puzzles are pure
  functions of state + action).
