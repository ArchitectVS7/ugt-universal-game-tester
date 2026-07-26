# Tiny Escape Room — Game PRD

**One-liner:** A 10-room, CSV-authored text-adventure escape room. No combat,
no monsters — pure exploration, inventory, and flag-gated puzzles. New
adventures are authored entirely by editing `rooms.csv` and `objects.csv`; no
code changes needed for new content.

**Why this example exists:** Demonstrate `/tasklist` + `/orchestrate` building
a Node.js CLI game from a PRD, against a genuinely content-rich game instead
of a toy economy.

## Stack

Node.js, no dependencies beyond a CSV parser (e.g. a single small hand-rolled
parser — no framework needed for 2 flat files). One process, one front end
over one core:

- **`src/engine.js`** — loads the CSVs, holds the only game-state mutation
  logic, exposes `executeCommand(verb, objectId | direction)`. This is the
  single place rules live, same discipline as the Dice Duel engine module.
- **`src/cli.js`** — human-facing REPL: parses free text ("take key", "go
  north", "use lantern") into `executeCommand()` calls, prints room
  descriptions and flavor text. It **never re-implements a rule** — only
  translates input and renders output.

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

## Game state

The engine exposes a snapshot of exactly this shape:

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

`escaped` becomes `true` the moment the player successfully enters `R10`, and
latches. `inventory` serializes in `objects.csv` file order, and the `flags`
key set covers the whole flag universe from the first move on, so a given held
set always serializes identically.

## Non-goals

No monsters/combat/NPCs, no timers or countdowns, no save/load, no hint
system, no colored terminal output requirement, no branching narrative beyond
the flag-gated room chain.

## Acceptance criteria

- `node src/cli.js` is playable start-to-finish by a human with only the 8
  verbs above, reaching `escaped: true`.
- Same command sequence from a fresh game reproduces identical state every
  time (the engine has no hidden randomness — CSV-driven puzzles are pure
  functions of state + action).
