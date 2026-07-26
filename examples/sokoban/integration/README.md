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
| 2 | `smoke_sokoban_adapter.py` | **SMOKE MET — 11/11** (incl. the screen channel the LLM tier reads) |
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

There is deliberately no `feature-map.yaml` here: `ugt verify` has no `custom`
path to dispatch (see `PLAN-FORWARD.md`'s backlog), and the same properties are
asserted per command by the ladder's own rungs.

## Tier 3 — the LLM playtester

```bash
# stage 1 — local, free, proves the CHANNEL and never produces a number
python3 examples/sokoban/integration/playtest_sokoban.py --provider ollama --max-actions 30
# stage 2 — paid, the only stage allowed to produce a quotable figure. NOT RUN.
python3 examples/sokoban/integration/playtest_sokoban.py --provider anthropic \
    --model claude-haiku-4-5-20251001 --max-actions 150

# scoring only — no bridge, no model, no spend
python3 examples/sokoban/integration/playtest_sokoban.py --score results/<report>.json
python3 examples/sokoban/integration/playtest_sokoban.py --prove-scoring
```

`ugt playtest` cannot drive this game — `engine.type: custom` means `env.py` has
no adapter to dispatch, and `playtest_game()` raises saying exactly that. The LLM
loop is unchanged: `playtest_sokoban.py` builds `GodotTcpAdapter`, runs the §B
pre-flight fail-closed, and hands the adapter to
`playtest_game_with_adapter(..., action_mode="action_id")`. It also passes the
same 9 predicates R1/R2/R3 assert, so a defect the pilot never notices is still
caught — one invariant definition, now three tiers.

**This tier measures COMPETENCE here, never a rate.** No RNG exists anywhere in
the game, so N episodes are N replays of one puzzle set and a percentage over them
has a denominator of N and a sample size of 1 (§B P9/P13). The report says so
itself in `sample_note`.

The scoreline's primary output is `levels_solved: N/3` and `crates_moved: N`, both
derived from the action log rather than from a scalar the game happens to keep:
a crate counts as moved when the set of `$`/`*` cells in the rendered board changes
between two consecutive states, so **a push that never crosses a target still
counts** — `boxes_on_target` alone cannot see one. Level advances and reloads
change the board without being pushes, so both are excluded, and the count of what
was excluded is printed next to the total.

The moves-against-the-committed-73 ratio is **withheld unless `all_levels_solved`
is true** (see Finding 11). Its denominator is the cost of FINISHING, so on a
partial run it is not a worse score — it is not a score, and the block prints an
explicit line saying so instead of a number. `--prove-scoring` is that logic's own
negative and positive control: synthetic reports for a walk that solves nothing, a
push along open floor with `boxes_on_target` untouched, a reload, a level advance,
a solve visible only in the log, an episode reset that replays level 1, and a
finished run that *does* print the ratio. It needs no game and no model.

### The §B pre-flight (2026-07-26)

Run before spending anything, per P12. Everything below was free.

| # | Check | Verdict |
|---|---|---|
| P1 | Identities, not handles | **PASS.** Actions are `up`/`down`/`left`/`right`/`reload`, never ids. State names are plain (`boxes_on_target`, not `bot`). No room-code equivalent exists — the board is the world |
| P2 | Adapter passes through every PUBLIC field | **PASS, and the channel had to be built.** This game has NO prose: `main.tscn` is ColorRects with no Label, no font, no message line. So the board IS the entire player-facing text channel, and `GodotTcpAdapter.get_terminal_text()` now carries it by joining the very rows `board.gd::render_rows()` draws for the human. Asserted live in both directions — a board arrives, AND it changes when the game changes (a channel serving a stale screen forever would pass the first check and is worse than an empty one, because it looks right) |
| P3 | Truncation is silent starvation | **WOULD HAVE FAILED — FIXED.** The guide is 4,422 chars against the 2,000 default. The cut lands from "The one rule that matters" onward, i.e. every rule that creates the skill. Budget set to 6,000 and `assert_guide_fits` fails the run before any model is contacted |
| P4 | Action channel sends what the LLM thinks | **PASS.** `action_id` mode maps name → id 1:1; an unknown name is dropped, never coerced to a neighbouring id. The truncation salvage added in Finding 7 keeps that property — it refuses to salvage a name the config does not declare |
| P5 | Prompt must not leak what the client hides | **WAS LEAKING — CLOSED, and the audit ran the other way too.** There is no HUD at all here, so every field had to be justified rather than passed through. Six of eight are derivable by looking at the board. Two are redacted: `moves_taken` (a score the game keeps and shows nobody — Finding 6 — and the exact number this tier scores against) and `grid` (not hidden, *moved* to the Terminal panel where it renders aligned instead of JSON-quoted). Verified against a **rendered prompt**, not against the config |
| P6 | Guide teaches the RULES that create skill | **PASS.** Push-not-pull and its consequences: why a wall-flush crate can only slide, why a corner is permanent, why finishing a crate early can wall you off, and that reload is the correct move rather than a failure. No solution sequences — teaching the moves would measure recall |
| P7 | Competence from the reasoning, not the exit code | **RUN — the channel is proven and the local model is below the floor.** Quantified rather than sensed: across 160 actions over three runs the pilot moved a crate **0 times** on a first level solvable in 6 moves (instrument-derived from the boards since Finding 11, not counted by hand), and of the crate positions it stated out loud only ~40% matched the board (9/17, 9/21, 41/59 right/wrong). It is engaged with the right concepts (`crate` 67×, `push` 30×, `target` 33× in 30 actions) and cannot reliably localise a glyph in a 7×5 grid. This is NOT P12's ambiguous-silence case: a specific wrong belief, stated out loud, is diagnosable — see Finding 8 |
| P8 | Never pool across an information fix | **Boundaries declared** — see the run table. Row 1 → 2 crosses the Finding 7 fix and is a before/after pair, never a trend. Findings 9 and 11 are *reporting* fixes that never touched a prompt, so neither creates a behavioural boundary — the three rows stay comparable across both |
| P9/P13 | Episodes: samples or replays? | **Declared `deterministic` and probed live** before every run: two resets replay identically over 4 steps, and the probe (`left`, level 1's first committed move) really moved the state, so "identical" is not vacuous |
| P10 | Pilot needs memory, not just state | **Configured** — `history_window: 12`, roughly one crate's worth of work including the walking. The default 5 forgets the plan halfway through executing it |
| P11 | A prompt guard is part of the game | **WOULD HAVE MADE THE GAME UNPLAYABLE — FIXED.** The repeat guard blocks the 3rd identical proposal at its default. Pushing a crate five cells along a row *is* five consecutive `left`s, and the committed solutions contain runs of 5 and 6. Raised to 8, and `assert_repeat_guard_allows_real_play` derives the bound from `solutions.json` so authoring a longer push run re-checks it automatically |
| P12 | Local model first | **DONE — `gemma4:26b`, zero API cost.** It paid for itself: P3, P11, and Findings 6–9 were all found free, and two of those are UGT-core defects that would otherwise have surfaced on a paid bill |
| P14 | Content: solvable, and every obstacle teaches | **Solvable is PROVEN** — R1 and R2 replay the committed solutions through the live engine every run. "Teaching" works differently in this genre and needs saying: there is no authored refusal text because there is no text. A refused move returns byte-identical state, and the board itself is the explanation — a human sees the wall. The guide therefore has to teach *how to read a refusal* ("if the board comes back exactly as it was…"), which is the substitute for a spoken one |

### Stage 1 runs — local, free, and no number from here is quotable

```bash
python3 examples/sokoban/integration/playtest_sokoban.py --provider ollama \
  --max-actions 30 --output results/channel-check-ollama-30.json
```

| Run | Actions | Real moves | Crates moved | Levels solved | Invariant violations | Stated crate position right/wrong |
|---|---|---|---|---|---|---|
| pre-Finding-7 | 30 | **26** | 0 | 0/3 | 0 | 9 / 17 |
| post-Finding-7 | 30 | **30** | 0 | 0/3 | 0 | 9 / 21 |
| post-Finding-7, fair budget | 100 | **100** | 0 | 0/3 | 0 | 41 / 59 |

The `Crates moved` and `Levels solved` columns were hand-computed when this table
was written. Finding 11 turned both into instrument output, so they were
**re-derived rather than carried forward** — `--score` against all three reports
agrees with every cell (0 crates, 0/3 levels, on 26/30/100 grid-changing steps).

**Row 1 → 2 is the Finding 7 fix, and it is worth more than it looks: 4 of 30
actions — 13% of the pilot's budget — were destroyed by truncated replies, and the
run summary had no field that said so.** All four show in the log as
`wait` with reasoning `(no json)`. Post-fix: zero, three runs in a row.

⚠️ **P8: these are before/after pairs, not a trend.** Row 1 → 2 crosses an
information fix, so no number may be pooled across it; row 3 additionally changes
the budget, so it answers "given a fair budget" rather than continuing row 2. And
per P12 no stage-1 figure is quotable at all, whichever row it comes from.

**What stage 1 established, which is its whole job:** the pilot can see the game
(a real board, aligned, in the panel a player looks at), acts on it legally, and
never broke an invariant in 160 actions of trying. The transport question this
example exists to answer — *can a language model drive a game running inside a
real engine frame loop* — is answered yes. The transport is proven.

**What stage 1 did NOT establish, and is honest about:** whether the puzzles are
any good. The local model never pushed a single crate in 160 actions — not once,
across three runs, including one at P12's full 100-action ceiling — so it produced
no evidence about the game's difficulty at all. It also never once used `reload`,
which is unsurprising given it never created a position that needed one. That is
the expected shape of a stage-1 result and precisely why P12 forbids quoting one.

Stage 2 (Haiku) is un-run and is a credit decision, not a blocked one.

## Files

| File | Role |
|---|---|
| `bridge_process.py` | Spawns / waits for / reaps the headless Godot bridge. Every rung imports it. |
| `godot_tcp_adapter.py` | Transport-only `BaseAdapter`: connect/reset/step/close over newline-delimited JSON. **No game rules.** |
| `invariants.py` | The 9 properties, defined once, used by R1/R2 (`check_command`) and R3 (`to_hunter_invariants`). |
| `spike_sokoban.py` | Rung 1 — raw protocol, no adapter. |
| `smoke_sokoban_adapter.py` | Rung 2 — the `BaseAdapter` contract, including `get_terminal_text()`: the tier-3 screen channel is asserted on **every ladder run**, because `BaseAdapter`'s default returns `""` and losing it would otherwise be silent. |
| `verify_round1.py` | Rung 3 — level 1 solved, F1–F6. |
| `verify_round2.py` | Rung 4 — all 3 levels to `all_levels_solved`, no-op probes. |
| `verify_round3.py` | Rung 5 — invariant fuzzer, illegal ids, replay determinism. |
| `playtest_sokoban.py` | Tier 3 — the LLM runner. Owns the §B pre-flight, then hands the adapter to `playtest_game_with_adapter()`. Also owns the competence scoreline, re-runnable model-free via `--score` and self-proving via `--prove-scoring`. |
| `strategy-guide.md` | Tier 3 — the briefing the pilot reads. Teaches push geometry, corner deaths and when to reload; no solutions. |
| `ugt.config.yaml` | `engine.type: custom` — env.py dispatches nothing, so the rungs and the tier-3 runner construct the adapter. 5 actions: four directions plus `4 = reload`. Also carries the `playtest.*` block, where every setting is justified inline. |

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

**6. The game keeps exactly one number and shows it to nobody. FILED, not
fixed.** The PRD's one-liner is "no scoring beyond move count", so `moves_taken`
is the whole score — and `main.tscn` is ColorRects with no Label, no font and no
message line, so a human at the keyboard never sees it. Nor the level number, nor
any "solved" acknowledgement. The PRD's own state-shape section sets the standard
this fails: *"exactly what the human sees on screen … so a machine player is told
no less and no more than a person at the keyboard."* The wire sends eight scalars
the screen does not.

Not fixed, because unlike the missing R key (Finding 5) the PRD never promised a
HUD, and adding one is a scope decision for whoever owns the game rather than a
defect to repair. Handled on the tester's side instead, which is the half this
repo owns: `moves_taken` is redacted from the prompt, so the pilot plays with what
a player has. Recorded because a puzzle game whose only score is invisible is
worth someone deciding about on purpose.

**7. UGT core: a truncated reply silently cost the pilot its move. FIXED.** The
Ollama client capped responses at `num_predict: 256`. The required JSON puts the
action FIRST and `reasoning`/`expected_outcome` after it, so a reply cut off
mid-prose is unparseable — and the loop turned that into a forced `wait`, which
spends a step of the budget without touching the game. The model had already
decided; the cap threw the decision away.

**Spatial reasoning is what exposed it.** "The player is at (4, 2) and the crate
is at (3, 2). Moving left will…" runs longer than a card game's "attack-weighted,
the enemy is at half strength", so this game hit the ceiling where dice and
escape-room never did — 1 action in 30 on the first run, invisible in the summary,
which has no counter for it.

Fixed twice over in `ugt/core/playtester.py`: the ceiling is 512 (a truncated
reply is never useful, so a larger one can only preserve work), and
`_salvage_truncated_action` recovers the action from the prefix when it still
happens. The salvage is deliberately conservative and was proven in both
directions — it recovers `"value": "down"`, and **refuses** `"value": "teleport"`
because the config does not declare it, so it can never invent an action or coerce
a hallucinated name onto a neighbouring id (§B P4). A salvaged step says so in its
own reasoning, so a transcript never implies the model said more than it did.

**8. The pilot is handed a coordinate frame for itself and has to derive everyone
else's. FILED — it needs a paid run to settle.** The state gives `player_x` and
`player_y` as numbers; every crate and target must be located by reading ASCII.
The local model's error pattern follows that split exactly: across 160 actions it
stated its own position correctly essentially every time, and only ~40% of the
crate positions it asserted out loud matched the board. It moved a crate zero
times on a level solvable in six moves, while talking about crates constantly.

Two candidate fixes point in opposite directions and both are defensible:

* **Redact `player_x`/`player_y` too**, so everything comes off the board and
  there is one frame instead of two. Maximally faithful — a human is not given
  their own coordinates either.
* **Label the board's rows and columns**, so a text reader can locate a glyph the
  way vision does. Reveals nothing about the puzzle, and arguably restores parity
  rather than granting an advantage.

Not chosen here, on purpose. Which one is right is a question about the
*measurement instrument*, and the evidence that would settle it — does the
localisation error rate drop — has to come from a model that can localise at all,
i.e. stage 2. Guessing now would bake a choice into the tier and then measure it
(`LESSONS.md` §D).

**9. UGT core: a redacted field could be recorded as something the pilot "failed
to predict". FIXED.** `_unexpected_delta_fields` compared the raw state delta
against the pilot's expectation text with no knowledge of
`playtest.redact_state_fields` — so `grid` and `moves_taken`, both deliberately
hidden from the prompt, were logged as surprises on every successful move. The
pilot was being charged for information it had been denied.

Here the summary's ubiquity floor (a key changing on ≥80% of delta-bearing steps
carries no signal) happened to absorb both, which is luck rather than correctness:
a redacted field changing on *half* the steps sits under that floor and would be
counted forever. The filter now drops redacted paths before the comparison, and it
was proven able to fail — with redaction removed, the same delta reports all four
keys.

This one changed only what is RECORDED, never what the pilot is shown, so it
creates no P8 boundary. Worth separating explicitly: an information fix invalidates
comparisons across it, and a reporting fix does not.

**10. Neither stall detector can see a two-cycle. FILED.** The pilot spent long
stretches alternating `right`, `left`, `right`, `left` between two cells. Every
one of those moves is legal and changes the state, so:

* the **no-op detector** never fires — it needs a step with no material delta;
* the **repeat guard** never fires — it needs the *same* action twice in a row.

An A-B-A-B loop is invisible to both, and it is the single most natural way for a
pilot to waste a whole budget. UGT already knows how to detect the shape —
`ugt/core/generic_checks.py::check_state_cycles` finds exactly this — but the
generic checks run in the invariant-fuzzer tier and not in the LLM loop. Filed as
a framework item rather than patched here, because it belongs to `ugt/core/` and
wants its own negative control.

**11. The scorer printed `1.37x optimum` for a run that solved nothing. FIXED.**
`report_competence` printed the moves/optimum ratio unconditionally, so the real
100-action stage-1 report — **0 of 3 levels solved, 0 crates moved** — was scored
`100 moves (1.37x optimum)`. That reads as "37% off the pace", i.e. as a pilot
that played competently and finished a bit slowly. The true reading is that the
game was never played.

The ratio is not a lenient measure of a partial run; it is undefined for one. Its
denominator is the cost of FINISHING all three levels, and a run that finished
none has no numerator to compare against it. Worse than being wrong, it was
*quotable-looking* — a bare multiple of a committed optimum, produced by the one
function whose entire stated job is to say what a run is worth, in exactly the
tier where §B P12 forbids quoting stage-1 numbers at all.

Three changes, all in `playtest_sokoban.py`:

* the primary output is now `levels_solved: N/3` and `crates_moved: N`, printed
  first, so the headline is what the run *achieved* rather than a derived score;
* `crates_moved` is read off the rendered board — the `$`/`*` cell set changing
  between two consecutive states — because `boxes_on_target` only moves when a
  push *crosses* a target and so cannot see an ordinary push along open floor.
  Level advances (detected by the wall set, which fingerprints the level) and
  reloads change the board without being pushes, and are excluded and counted;
* the ratio prints **only** when `all_levels_solved` is true. Otherwise the block
  states that it is undefined, and why.

Proven able to fail, and the proof is permanent: `--prove-scoring` builds
synthetic reports in memory (`results/` is generated, so the real ones cannot be
the regression) and carries a control for every rule, including the two that only
a fixture can distinguish — a solve visible *only* in the log across the lazy
advance, and an episode reset after which re-solving level 1 must still read 1/3
rather than 2/3. Each guard was additionally mutation-tested red by hand and the
file restored byte-identically (sha256 compared, never `git checkout`); the
ratio-gate mutation reproduces the original `1.37x` exactly.

One defensive branch was **deleted rather than left in**, because no fixture and no
real report could ever take it the other way: a `baseline_state.level_index` read,
since a run always starts on level 1 — the same fact the reset branch already
relies on. A check that cannot go red is decoration, and decoration in a scorer is
how the `1.37x` survived in the first place.

Like Finding 9, this changed only what is **REPORTED**, never what the pilot
receives — no prompt, no redaction and no guard moved — so it creates **no §B P8
boundary**, and the three stage-1 rows remain comparable to each other on exactly
the terms they already were.

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
