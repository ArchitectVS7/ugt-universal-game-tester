# Pond Conspiracy (the-pond) — UGT trial ladder

First real-time / first Godot integration. Game repo: `~/Dev/Games/the-pond/` (Godot 4.7.1,
GDScript bullet-hell roguelike). Direction + feasibility evidence: `HANDOFF.md`. Findings log:
`RESULTS.md`.

## How it works

No server. The ladder scripts spawn the REAL game headless through a JSON-lines harness that
lives in the game repo (`the-pond/tests/harness/ugt_harness.gd`, a `SceneTree` script):

```
godot --headless --fixed-fps 60 --path ~/Dev/Games/the-pond -s res://tests/harness/ugt_harness.gd
```

One JSON request per stdin line, one response per stdout line (protocol lines carry
`"ugt": true`; everything else is game log noise). Ops: `create` (seed) / `step`
(exactly N physics frames of held named-action input + aim override) / `state` / `quit`.
Between commands the harness blocks on stdin **inside** `_physics_process`, freezing the
engine — a driver can think for minutes and zero game frames elapse. `--fixed-fps 60`
decouples frames from wall clock (deterministic delta, runs at CPU speed).

The harness contains no game logic: named input actions, the player's own
`aim_target_override` hook, structural state reads, and a tap that drains every EventBus
signal into each step response. It also redirects `MetaProgression.save_path` before the
autoload's `_ready()`, so runs never touch the real user save and always start from a virgin
meta state (run #1 — run count is a difficulty input).

## Run the ladder (from the UGT repo root)

```bash
python3 integrations/pond/spike_pond.py          # raw protocol round-trip (13 checks) — DONE 13/13
python3 integrations/pond/smoke_pond_adapter.py  # BaseAdapter path (8 checks) — DONE 8/8 ×3
python3 integrations/pond/verify_round1.py [seed] # playability gate (18 checks) — DONE 18/18
# verify_round2..3.py — not yet written
```

R1 drives one full run loop: waves -> real tongue kills -> damage -> provoked dodge i-frames
-> level-up -> a mutation picked by a REAL mouse click on its card -> death -> `run_ended` ->
epilogue -> visible RunEndScreen, asserting `integrations/pond/invariants.py` after every
step. It defaults to seed 20260719 and is 18/18 on every seed tried (20260719, 777001, 424242, 90210).

The adapter is `ugt/adapters/pond_harness.py` (`PondHarnessAdapter`, engine keys +
14-action input-macro vocabulary in `ugt.config.yaml`). One episode per subprocess:
`reset()` reboots the game (~2s) so every episode starts from a virgin meta state.

Needs `godot` on PATH (or `UGT_GODOT_BIN`); game repo location overridable via `POND_ROOT`.
