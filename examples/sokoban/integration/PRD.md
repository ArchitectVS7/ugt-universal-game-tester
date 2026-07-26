# Sokoban Mini — Integration PRD (UGT side)

**One-liner:** Drive `../game` (Godot, headless) through a **hand-written,
engine-first adapter** over a local TCP socket — the same "purpose-built
transport-only adapter, constructed directly by the ladder scripts" pattern
`examples/harness-game` uses, because Godot has no built-in UGT engine type.

## Why a hand-written adapter

UGT dispatches two engine types from `ugt/core/env.py`: `browser` (Playwright
+ `window` hooks) and `simulation` (subprocess + blocking stdio JSON-lines).
Neither fits a Godot game:

- Not a web page → not `browser`.
- Godot's frame-based `_process()` loop doesn't do a blocking
  `stdin.readline()` the way a Python/Node script can — a synchronous stdio
  bridge would either block the render loop or need a second thread, whereas
  a **non-blocking TCP socket polled once per frame** is Godot's natural
  idiom (the same reason the community's Godot-RL-Agents plugin uses TCP,
  not stdio).

So this integration follows `examples/harness-game`'s precedent exactly: a
small `BaseAdapter` subclass, constructed directly by the ladder scripts,
**not** dispatched by `env.py`. Its `ugt.config.yaml` therefore declares
`engine.type: custom` — the type reserved for exactly this case (documentary
config, no entrypoint for `env.py` to spawn) — same caveat as
`harness-game`'s.

## Adapter: `godot_tcp_adapter.py`

`connect()` spawns `godot4 --headless --path ../game -- --ugt-bridge
--ugt-port=8910` (or attaches to an already-running instance), then opens a
TCP client to `127.0.0.1:8910`. `reset()`/`step()`/`close()` send the same
newline-delimited JSON the subprocess protocol uses, just over a socket
instead of stdio:

- `{"command": "reset"}` → `{"state": {...}}`
- `{"command": "step", "action_id": N}` → `{"state": {...}, "terminated": bool, "truncated": bool, "info": {}}`
- `{"command": "close"}` → Godot process exits cleanly

Python's `socket.makefile()` gives a natural blocking `readline()` here, so
the framing complexity is one-sided — it's the Godot bridge
(`../game/PRD.md`'s `ugt_bridge.gd`), not this adapter, that has to hand-roll
message buffering.

## State contract (must match `../game/PRD.md` exactly)

```
level_index         int 0-2
player_x, player_y  int (grid coords)
boxes_on_target     int
boxes_total         int
moves_taken         int
level_solved        bool
all_levels_solved   bool
```

## Action contract

4 discrete actions: `0=up, 1=down, 2=left, 3=right`, matching
`../game/PRD.md`'s bridge mapping exactly.

## Feature map coverage plan

(Driven directly by the ladder scripts, same as `harness-game` — the `ugt
verify` CLI only drives adapters `env.py` dispatches, so these assertions are
asserted in-harness by the ladder rather than through `verifier.py`.)

| ID | Assertion | Precondition |
|---|---|---|
| F1 | Moving into a wall leaves `player_x`/`player_y` and `moves_taken` unchanged | adjacent wall exists |
| F2 | Pushing a box into open floor moves both box and player one cell | box with open cell behind it |
| F3 | Pushing a box into a wall or another box is a no-op (neither position nor `moves_taken` changes) | box blocked behind |
| F4 | `boxes_on_target` increments when a pushed box lands on a target | box adjacent to a target, floor push direction |
| F5 | `level_solved` becomes true exactly when `boxes_on_target == boxes_total` | drive a level to completion |
| F6 | Solving level 3 sets `all_levels_solved: true` and `terminated: true` | complete all 3 levels in sequence |

## Trial ladder plan (harness-game shape: spike → smoke → R1 → R2 → R3)

- **Spike** — raw TCP round-trip: connect, `reset`, one `step`, `close`. No
  adapter class yet.
- **Smoke** — same round-trip through `GodotTcpAdapter` (the `BaseAdapter`
  contract).
- **R1** — one full documented solution per level (from `../game/PRD.md`'s
  fixtures) to a real `level_solved`, asserting F1-F5 along the way.
- **R2** — all 3 levels back-to-back to `all_levels_solved`, plus deliberate
  wall/box-blocked no-op checks (F1, F3).
- **R3** — exploit-hunter random walk (uniform over the 4 actions) for ≥100
  steps per level; invariants: `moves_taken` never decreases, `player_x`/
  `player_y` stay in-bounds, `boxes_on_target` never exceeds `boxes_total`.
  Same-seed replay — trivial here since Sokoban has no RNG, but still
  asserted (proves the *adapter/bridge* introduces no nondeterminism, e.g.
  socket message reordering).
- **Tier 3 (`ugt playtest`) is deliberately out of scope for this specific
  example** — not because Sokoban has nothing to judge (an LLM playtester
  could reasonably assess puzzle discoverability, solution efficiency vs.
  optimal, or whether the push mechanic reads as intuitive), but to keep
  this example's scope to Tiers 1/2 only; `dice` and `escape-room` already
  cover the Tier 3 pattern end-to-end.

## Acceptance criteria

- All 5 rungs pass (spike/smoke/R1/R2/R3), matching `examples/harness-game`'s
  PASS/FAIL ladder convention.
- 0 invariant violations across R3's random walks, all 3 levels.
- Same-seed replay is byte-identical.
