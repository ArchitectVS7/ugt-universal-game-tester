# Pond Conspiracy ('the-pond') — UGT trial ladder

**Status: FULL LADDER COMPLETE as of 2026-07-21.** UGT's game #7, and its **first real-time**
and **first Godot** integration.

Pond Conspiracy is a real-time top-down bullet-hell roguelike built in Godot 4.7.1 / GDScript:
a frog protagonist investigating a corporate conspiracy, fighting waves of enemies, collecting
evidence, and leveling up through mutation picks between deaths. Game repo: `~/Dev/Games/the-pond/`.

See `HANDOFF.md` for the full resume-here state (direction, feasibility evidence, exact
per-round detail) and `RESULTS.md` for the commit-traceable findings log. This folder is
already clean — no `archive/` subfolder was needed for this pass; there is no
historical/superseded material to point to.

## How it works

No server. The ladder scripts spawn the REAL game headless through a JSON-lines subprocess
harness that lives in the game repo — the same pattern used for DDD and Nexus Dominion, not a
registered `engine.type`.

**Game side:** `the-pond/tests/harness/ugt_harness.gd`, a `SceneTree` script run via:

```
godot --headless --fixed-fps 60 --path ~/Dev/Games/the-pond -s res://tests/harness/ugt_harness.gd
```

One JSON request per stdin line, one response per stdout line (protocol lines carry
`"ugt": true`; everything else is game log noise). Ops: `create` (seed) / `step` (exactly N
physics frames of held named-action input + aim override) / `choose` (level-up mutation pick)
/ `state` / `quit`. Between commands the harness blocks on stdin **inside**
`_physics_process`, freezing the engine — a driver can think for minutes and zero game frames
elapse. `--fixed-fps 60` decouples frames from wall clock (deterministic delta, runs at CPU
speed).

The harness contains no game logic: named input actions, the player's own
`aim_target_override` hook, structural state reads, and a tap that drains every EventBus
signal into each step response. It also redirects `MetaProgression.save_path` before the
autoload's `_ready()`, so runs never touch the real user save and always start from a virgin
meta state (run #1 — run count is a difficulty input).

**UGT side:** `ugt/adapters/pond_harness.py` (`PondHarnessAdapter`), transport-only, exposing
14 discrete input-macro action ids declared in `ugt.config.yaml`. One episode per subprocess —
`reset()` reboots the game (~2s) so every episode starts from a virgin meta state.

Needs `godot` on PATH (or `UGT_GODOT_BIN`); game repo location overridable via `POND_ROOT`.

**Godot lesson worth knowing before touching any headless-UI script here:** the headless root
window is 64x64 by default, so no synthesized UI click lands until `root.size` is set **twice**.

## Run the ladder (from the UGT repo root)

```bash
python3 integrations/pond/spike_pond.py           # raw protocol round-trip
python3 integrations/pond/smoke_pond_adapter.py   # BaseAdapter path
python3 integrations/pond/verify_round1.py [seed] # R1: playability gate
python3 integrations/pond/verify_round2.py        # R2: full spine
python3 integrations/pond/verify_round3.py        # R3: exploit-hunter + replay determinism
python3 integrations/pond/playtest_pond.py         # LLM playtest tier (mutation-choice macro layer)
```

Also present, kept as committed regression guards (not scratch scripts) — run them whenever
`verify_round1.py`/`verify_round2.py` or `invariants.py` change:

- `pc6_ordering_selftest.py` — 4 cases, guards the PC-6 evidence/epilogue ordering predicate
  used by `verify_round2.py`.
- `stderr_scan_selftest.py` — 5 cases, guards the `SCRIPT ERROR` stderr-scan predicate shared
  by `verify_round1.py`/`verify_round2.py`.

`invariants.py` holds the shared game-invariant predicates asserted after every step across
the ladder (no negative resources, no stuck screens, no soft-lock, no crash, plus the
Pond-specific ordering/pool/save-path checks below).

## Ladder results

| Stage | Result |
|---|---|
| Spike (raw protocol) | 13/13 |
| Smoke (`PondHarnessAdapter`) | 8/8, run 3 times |
| R1 — playability | MET 18/18, seed-independent across 4 seeds |
| R2 — full spine | MET 45/45, including 2 named owner-accepted uncounted limitations (below) |
| R3 — ExploitHunter | MET 11/11, zero findings, full 14/14 action-vocabulary coverage, bit-identical same-seed replay |

R2's two disclosed (not hidden) limitations:

- **PC-12** — the JSON-lines wire has no op to observe/reach a `victory` run result. The code
  path exists and is verified in-engine by the game's own test suite; it just isn't reachable
  from this harness's current op set.
- **PC-15** — a scripted driver cannot reliably out-dodge the real-time bullet-hell boss. This
  is a play-skill limitation of the driver, not a balance bug — the-pond's own T-062
  measurement showed the balance is sound for a realistic human build.

## Headline findings (8 game defects found + fixed upstream)

Dual-validation wins: the ladder validated both that UGT can drive this game and that the game
itself works. In severity order:

- **PC-5 (CRITICAL)** — the tongue's hitbox only covered its tip, leaving ~83% of its own
  reach unhittable. The player could never kill anything at realistic engagement range.
- **PC-11 (CRITICAL)** — only one of the three bosses was ever wired up in `BossArena`; the
  other two were referenced only by unit tests. The true ending could never unlock.
- **PC-6** — a run's own evidence reward could never appear in that same run's epilogue, a
  signal-ordering bug between two autoloads.
- **PC-8** — triggering the boss froze/freed the entire ~122-instance dormant enemy pool,
  causing 74 script errors on every later spawn.
- **PC-16** — a collision-mask bug let the player escape the arena bounds during the boss
  fight.
- **PC-17** — pause was purely cosmetic: `get_tree().paused` flipped but gameplay kept
  running underneath it.
- **PC-1** — the global RNG was unseeded, blocking deterministic same-seed replay.
- **PC-2** — headless test/harness runs were silently overwriting/polluting the REAL player
  save file and the run-count-driven difficulty curve. Verified this was destroying real
  player progression; now fixed, with byte-identical save verification confirming the fix.

## LLM playtest tier

**WIRED AND MET (L-004, 2026-07-21)** via Ollama (`qwen3-coder:30b`), using a macro-layer
design: the LLM is consulted **only** at level-up mutation choices — the one reasoning-shaped
decision point in an otherwise real-time game — while combat itself is auto-played by the
reused R1 heuristic. Result: 7/7 level-up decisions across 9 runs applied a real mutation, 0
bugs.

The Anthropic-provider run — the one that produces the actual balance **verdict** — remains
credit-gated/pending. Stated plainly: this tier is wired and functioning, but the balance
judgment itself has not yet been rendered.
