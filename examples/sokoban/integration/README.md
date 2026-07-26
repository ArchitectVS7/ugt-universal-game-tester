# Sokoban Mini — UGT integration

Drives `../game` (Godot 4, headless) through a **hand-written, engine-first
adapter over a local TCP socket** — the same "transport-only adapter,
constructed directly by the ladder scripts" pattern `examples/harness-game`
uses for a Python engine. This is the example for `engine.type: custom`: UGT's
built-in engines don't fit a Godot game, so you write a small `BaseAdapter`
subclass and the framework's ladder, invariants, and exploit-hunter all work
unchanged.

## Prerequisites

A Godot 4.x CLI on `PATH` as `godot4`. Homebrew installs it as `godot`:

```bash
ln -s "$(command -v godot)" /usr/local/bin/godot4
```

No server to start. **Every rung spawns and reaps its own bridge.**

## Run the ladder

```bash
# from the repo root
for s in spike_sokoban smoke_sokoban_adapter verify_round1 verify_round2 verify_round3; do
  python3 examples/sokoban/integration/$s.py || break
done
```

Recorded results (2026-07-26, against the game at 84/84 tests green):

| Rung | Script | Result |
|---|---|---|
| 1 | `spike_sokoban.py` | **SPIKE MET — 14/14** |
| 2 | `smoke_sokoban_adapter.py` | **SMOKE MET — 9/9** |
| 3 | `verify_round1.py` | **ROUND 1 MET — 12/12** |
| 4 | `verify_round2.py` | **ROUND 2 MET — 11/11** |
| 5 | `verify_round3.py` | **ROUND 3 MET — 7/7** (240 random steps, 2 seeds, 0 findings) |

Tier 3 (`ugt playtest`) is deliberately out of scope for this example — `dice`
and `escape-room` already demonstrate that tier end to end.

## Files

| File | Role |
|---|---|
| `bridge_process.py` | Spawns / waits for / reaps the headless Godot bridge. Every rung imports it. |
| `godot_tcp_adapter.py` | Transport-only `BaseAdapter`: connect/reset/step/close over newline-delimited JSON. **No game rules.** |
| `invariants.py` | The 8 properties, defined once, used by R1/R2 (`check_command`) and R3 (`to_hunter_invariants`). |
| `spike_sokoban.py` | Rung 1 — raw protocol, no adapter. |
| `smoke_sokoban_adapter.py` | Rung 2 — the `BaseAdapter` contract. |
| `verify_round1.py` | Rung 3 — level 1 solved, F1–F5. |
| `verify_round2.py` | Rung 4 — all 3 levels to `all_levels_solved`, no-op probes. |
| `verify_round3.py` | Rung 5 — exploit hunter, illegal ids, replay determinism. |
| `ugt.config.yaml` | Documentary (`engine.type: custom` — env.py dispatches nothing). |

## Findings

**1. The bridge serves one client at a time, and a readiness probe that
*connects* silently breaks it.** The first version of `bridge_process.py` waited
for boot by dialling the port in a loop. That consumed the bridge's single
connection slot, and the real client then hit `ConnectionResetError` while the
bridge was re-accepting. It was intermittent — the spike passed, the smoke test
failed, purely because the spike happened to call `lsof` in between and gave
the bridge time to recover. Readiness is now read from the OS socket table via
`lsof` (`wait_until_listening`), which observes without connecting, and the one
real connection is made by `connect_with_retry`. **A liveness check that
consumes the resource it is checking is not a liveness check** — the failure
mode is timing-dependent, so it presents as flakiness rather than as a bug.

**2. No-op checks have to compare the WHOLE state.** "The player didn't move"
is far too weak an assertion for a blocked move: a transport bug can leave the
position alone while still advancing `moves_taken`. R2 asserts `after == before`
across every field, and R3 does the same for illegal action ids. Both hold.

**3. `moves_taken` resets on level advance.** So the monotonic invariant is
scoped to a single `level_index`; asserting it globally would have produced a
false violation the moment level 1 was solved. Noted because it is exactly the
kind of thing that gets discovered by a red run rather than by reading a spec.

## Notes

Ports are **ephemeral**, not the PRD's fixed 8910. Two consequences, both
deliberate: repeated or parallel runs cannot collide, and a stale bridge left
over from an earlier build can never be mistaken for the one under test.
`bridge_process.bridge()` additionally refuses to start if its port is already
occupied, rather than attaching — this repo has been bitten once already by a
whole campaign that ran green against a stale server.

Every rung is a fail-closed gate: it prints `[PASS]`/`[FAIL]` per check and a
`<RUNG> MET — p/t` footer, exiting non-zero if anything failed. Each also
asserts its own non-vacuity — the invariant suite is fed a deliberately
corrupted transition and must report violations, because a suite that has never
been seen to fail is not evidence.
