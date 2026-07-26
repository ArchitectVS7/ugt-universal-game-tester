# Tiny Escape Room — Integration PRD (UGT side)

**One-liner:** Drive `../game` through UGT's built-in **simulation** engine
(subprocess JSON-lines), the same transport `examples/mock-game` uses —
proving the pattern holds for a Node.js game with real branching content, not
just a toy economy.

## Adapter type: `simulation`

No custom adapter code needed — `ugt.config.yaml`'s `engine.type: simulation`
+ `entry: ./src/bridge.js` is handled entirely by the built-in
`SubprocessAdapter` (it already runs `.js` entries via `node`, per
`ugt/adapters/subprocess.py`). This is the most CLI-native of the three
examples — `ugt verify` / `ugt playtest` work immediately.

## Wire protocol (fixed by `SubprocessAdapter`, must match `../game/PRD.md`)

- request: `{"command": "reset"}` → response: `{"state": {...}}`
- request: `{"command": "step", "action_id": N}` → response: `{"state": {...}, "terminated": bool, "truncated": bool, "info": {}}`
- request: `{"command": "close"}` → process exits
- `UGT_SEED` env var is set by the adapter; this game has no randomness to
  seed, so `bridge.js` may ignore it.

## Two state views (an intentional split — see `ugt/core/env.py`)

- **Full raw state** (returned by every `step`/`reset`) — `current_room`,
  `inventory` (list), `flags` (dict), `moves_taken`, `rooms_visited`,
  `escaped`. This is what `ugt verify`'s feature-map assertions and the
  invariant-fuzzer's invariants read directly.
- **`observation_space` (box, numeric only, legacy RL path)** — the formula
  evaluator and Gym `Box` wrapper need scalars, so only derived numeric
  fields are mapped: `moves_taken (0-200)`, `inventory_count (0-12)`,
  `rooms_visited (1-10)`, `flags_set_count (0-N)`. `inventory` and `flags`
  themselves are **not** mapped here (they're lists/dicts, not scalars) —
  they're still fully visible to Tier 1/2/3 via the raw state.
- **Known SafeEvaluator limit:** the formula evaluator has no `in` operator —
  a feature-map assertion cannot say `"key_brass" in state.inventory`. Model
  "do you have X" as a boolean flag instead (`take_sets_flag` in the game's
  CSV) and assert on that flag, not on list membership.

## Feature map coverage plan (Tier 1 — `ugt verify`)

| ID | Assertion | Precondition |
|---|---|---|
| F1 | Locked room refuses entry when its `entry_requires_flag` is unset | none |
| F2 | Taking a flagged item sets the corresponding flag | item in starting room |
| F3 | `use` fails (state unchanged, flag not set) when its prerequisite flag is unset | prerequisite flag unset |
| F4 | `use` succeeds and sets its flag once the prerequisite is met | prerequisite flag set |
| F5 | A `use_consumes: true` object decrements `inventory_count` by 1 after a successful use (checked as `after.inventory_count == before.inventory_count - 1` — list membership can't be asserted directly since SafeEvaluator has no `in` operator) | object held, prerequisite met |
| F6 | Reaching `R10` sets `escaped: true` | full flag chain satisfied |

## Trial ladder plan

- `ugt smoke-test` — 5 random actions round-trip cleanly (a no-op for an
  invalid context still returns valid state, never crashes).
- `ugt verify` — F1-F6 above.
- Invariant-fuzzer (Tier 2) — random walk ≥150 steps; invariants: `moves_taken`
  and `rooms_visited` never decrease, `current_room` is always a valid
  `room_id`, `escaped` never flips back to `false`. Same-seed replay is
  trivially deterministic here (no RNG in the game) — the replay check
  instead validates that the *harness* introduces no nondeterminism (e.g.
  object iteration order).
- `ugt playtest` — Tier 3, `strategy-guide.md` describing the verbs,
  inventory, and win condition; judges whether the puzzle chain is
  discoverable without hints.

## Acceptance criteria

- All ladder steps pass against `../game`.
- `feature-map.yaml` scores 6/6 PASSED.
- Invariant-fuzzer: 0 invariant violations over ≥150 steps, two seeds.
