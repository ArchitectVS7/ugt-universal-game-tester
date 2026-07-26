# Sokoban Mini — UGT integration

Drives `../game` (Godot 4, headless) through a **hand-written, engine-first
adapter over a local TCP socket** — the same "transport-only adapter,
constructed directly by the ladder scripts" pattern that `engine.type: custom`
names. This is the reference example for that type: UGT's
built-in engines don't fit a Godot game, so you write a small `BaseAdapter`
subclass and the framework's ladder, invariants, and invariant-fuzzer all work
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
| 3 | `verify_round1.py` | **ROUND 1 MET — 12/12** (+1 finding) |
| 4 | `verify_round2.py` | **ROUND 2 MET — 13/13** |
| 5 | `verify_round3.py` | **ROUND 3 MET — 7/7** (240 random steps, 2 seeds, 0 findings) |

Every rung uses `ugt.core.trial.GateRunner`, so a failure is fail-closed
(non-zero exit) and a game anomaly that is *not* a gate failure has somewhere to
go — the `[FINDING]` channel, printed in a block above the footer.

Tier 3 (`ugt playtest`) is **not built yet** — no strategy guide, no playtest
script, nothing run. It is in scope: this is the only one of the three examples
inside a game engine, so it is the only place the LLM tier can be shown to drive
one. `playtest.seeding: deterministic` and `probe_action` in `ugt.config.yaml`
are already set for it. When it runs it measures competence (solved, and moves
against the committed 73-move solution), never a rate.

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
| `verify_round3.py` | Rung 5 — invariant fuzzer, illegal ids, replay determinism. |
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

**4. The state contract exposes no box coordinates.** Only `boxes_on_target` /
`boxes_total`, so a push that does not cross a target is **invisible to a
black-box tester**. F2 ("a box moves") can therefore only be evidenced where it
coincides with F4 ("a box reaches a target"). This is raised as a live
`[FINDING]` in R1 rather than buried here, because adding box positions to the
wire would let the two be tested independently. It is also the reason the
first version of this harness got F2 wrong — see below.

## Corrections to this harness

Recorded rather than quietly rewritten, because the failure mode is the one
this whole repo exists to catch.

**F2 was vacuous in the first version.** It read
`boxes_on_target >= prev_boxes_on_target`, which is true on *any* player move —
so "the solution actually moves boxes" could never fail. Proven against the live
game: a box-free walk (right/left along row 3, never touching the box) satisfied
the old predicate and fails the new one, which requires a **strict** increase.

**F3 was never tested — in R1 *or* R2.** Both probed for "any direction that is
a total no-op" and took the first hit. On `level_01` the player starts at (3,3)
with a wall directly below, so both found `down` — a **wall**, i.e. they
silently re-tested F1 while reporting F3 covered. A blocked *box push* is now
constructed explicitly: from the start, `up` lines the player up, the first
`left` pushes the box to x=1 (asserted **accepted**, so the setup is real), and
the second `left` would drive it into the wall at x=0 and must be refused with
the state completely unchanged.

**There was no findings channel.** The rungs originally hand-rolled their own
PASS/FAIL accumulator instead of using `GateRunner`, which meant an anomaly that
was not a hard failure had nowhere to go — it would have to be forced into a
FAIL or dropped. All five rungs now use `GateRunner` (and R3 uses
`first_divergence`), which restores the `[FINDING]` channel and removes the
duplication.

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
