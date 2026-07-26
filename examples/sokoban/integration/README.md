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

Recorded results — **whole ladder re-run 2026-07-26 (late), on the wire contract
`b66f710` landed**, against the game at 89/89 tests green:

| Rung | Script | Result |
|---|---|---|
| 1 | `spike_sokoban.py` | **SPIKE MET — 18/18** |
| 2 | `smoke_sokoban_adapter.py` | **SMOKE MET — 9/9** |
| 3 | `verify_round1.py` | **ROUND 1 MET — 14/14** (F1–F6; no findings — see below) |
| 4 | `verify_round2.py` | **ROUND 2 MET — 15/15** (90 commands) |
| 5 | `verify_round3.py` | **ROUND 3 MET — 7/7** (240 random steps, 2 seeds, 0 findings) |

⚠️ **The previous table was stale in four places** (spike 14, R1 12 + a standing
finding, R2 13, suite 84/84) and nothing failed to say so. `b66f710` added the
`grid` field and action 4, which grew the spike and both scripted rungs, and the
table was written before it. **Re-run the ladder rather than citing this table**
whenever the game or the scripts have moved — a recorded result is evidence about
a commit, not about the working tree.

Every rung uses `ugt.core.trial.GateRunner`, so a failure is fail-closed
(non-zero exit) and a game anomaly that is *not* a gate failure has somewhere to
go — the `[FINDING]` channel, printed in a block above the footer.

Tier 3 is **not built yet** — no strategy guide, no playtest driver, nothing run.
It is in scope: this is the only one of the three examples inside a game engine,
so it is the only place the LLM tier can be shown to drive one. When it runs it
measures competence (solved, and moves against the committed 73-move solution),
never a rate.

What exists for it so far, all landed by `b66f710` while *preparing* the tier
rather than running it: the `grid` field (Finding 4), action 4 = `reload`
(Finding 5), `playtest.seeding: deterministic` and a non-vacuous `probe_action`
in `ugt.config.yaml`. What is still missing, so the gap is a list rather than a
shrug: `strategy-guide.md`; a `playtest_sokoban.py` (this is `engine.type:
custom`, so the `ugt playtest` CLI cannot dispatch it — the driver has to own the
bridge lifecycle and call `playtest_game_with_adapter()`, the way
`examples/dice/integration/playtest_dice.py` does for its server); the
`playtest.*` context knobs (`objective`, `guide_char_budget`, `history_window`
— the config carries only the seeding pair today); and a `LESSONS.md` §B P1–P14
disposition table, which per P12 gets worked through on a local model before any
paid call.

There is deliberately no `feature-map.yaml` here either: `ugt verify` has no
`custom` path to dispatch (see `PLAN-FORWARD.md`'s backlog), and the same
properties are asserted per command by the ladder's own rungs.

## Files

| File | Role |
|---|---|
| `bridge_process.py` | Spawns / waits for / reaps the headless Godot bridge. Every rung imports it. |
| `godot_tcp_adapter.py` | Transport-only `BaseAdapter`: connect/reset/step/close over newline-delimited JSON. **No game rules.** |
| `invariants.py` | The 9 properties, defined once, used by R1/R2 (`check_command`) and R3 (`to_hunter_invariants`). |
| `spike_sokoban.py` | Rung 1 — raw protocol, no adapter. |
| `smoke_sokoban_adapter.py` | Rung 2 — the `BaseAdapter` contract. |
| `verify_round1.py` | Rung 3 — level 1 solved, F1–F6. |
| `verify_round2.py` | Rung 4 — all 3 levels to `all_levels_solved`, no-op probes. |
| `verify_round3.py` | Rung 5 — invariant fuzzer, illegal ids, replay determinism. |
| `ugt.config.yaml` | Documentary (`engine.type: custom` — env.py dispatches nothing). 5 actions: four directions plus `4 = reload`. |

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

**3. `moves_taken` rewinds only on a reload — and this entry used to claim the
opposite.** What it said was "`moves_taken` resets on level advance", and that is
false: the counter counts the whole session, and the game's own test suite pins
it (`test_board.gd`). The one legal decrease is a `reset_level`, which zeroes it
exactly. `moves_never_decrease` is written to that boundary — a backwards step to
any non-zero value is a wire or rules defect — rather than being scoped per
`level_index`, which is what the false belief had produced. Left in place rather
than deleted, because the belief survived a green ladder: the old invariant was
*narrower* than the truth, so it never fired and never argued back.

**4. The state contract exposed no box coordinates — CLOSED by `b66f710`.**
`get_state()` used to carry only `boxes_on_target` / `boxes_total`, so a push that
did not cross a target was **invisible to a black-box tester**: F2 ("a box
moves") could only ever be evidenced where it coincided with F4 ("a box reaches a
target"), and R1 raised it as a live `[FINDING]` on every run. It is also why the
first version of this harness got F2 wrong (see below).

The wire now carries `grid` — the player-facing ASCII render, one string per row
in the PRD's legend, the same thing a human reads off the screen. R1 asserts F2
on its own from it: the accepted push moves a box cell `(2,2) -> (1,2)` while
`boxes_on_target` stays 0, which the old contract could not express. Reading the
render is **not** re-implementing a rule — the game drew the grid, the harness
only looks at it. A ninth invariant, `grid_matches_scalar_state`, checks the
render against the scalars on every transition so the two halves of the contract
cannot drift apart.

**5. The PRD promised a retry the game had never bound.** Preparing the LLM tier
asked a question the scripted rungs never had to: what does a machine player do
with a wedged box? A human presses R. There was no R — `main.gd` bound no key for
it, and the PRD's "a player can always retry" was unimplemented. So this is a
**real product bug found by preparing a test**, not by running one, and it is the
clearest dual-validation case in this example: the wire needed `reset_level`
(action 4, dispatched through the board's new `apply_action()`, the one id table
every front end shares), and giving the machine the capability revealed the human
never had it either. R1's F6 now proves action 4 returns the exact level-start
state, and the game's suite covers the keybinding.

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

**And this file asserted a fact about the game that was not true** — see
Finding 3. It is listed here as well as there because the mechanism is a harness
correction, not a game one: a doc claim and an invariant were written from the
same wrong belief, and because the invariant was narrower than reality it stayed
green and never contradicted the doc. Nothing in a passing ladder can catch that;
only the game's own test suite could, and it did.

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

Fail-closed is **demonstrated** on the current scripts, not inherited from an
older run: inverting R1's F4 predicate (`rises > 0` → `rises > 99`) gives
`ROUND 1 NOT MET — 13/14 checks passed` and exit **1**, and the file was restored
byte-identical (md5 compared) afterwards rather than reverted with a checkout.
