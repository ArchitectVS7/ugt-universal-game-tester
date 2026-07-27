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

Recorded results — **whole ladder re-run 2026-07-26 (late), after the game gained
its win state and then its two content-property assertions**, against the game at
115/115 tests green:

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
# No --max-actions: the paid default IS the derived budget floor (see below).
python3 examples/sokoban/integration/playtest_sokoban.py --provider anthropic \
    --model claude-haiku-4-5-20251001

# the model-free GATE — no bridge, no model, no spend. Exit 0 scored,
# 1 the core interaction never happened, 2 the log contradicts itself.
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

The moves-against-the-committed-reference ratio (73 moves) is **withheld unless
`all_levels_solved` is true** (see Finding 11). Its denominator is the cost of
FINISHING, so on a partial run it is not a worse score — it is not a score, and the
block prints an explicit line saying so instead of a number. **73 is the sum of three
per-level minima, and it is still printed as "the committed reference"** — the first
half is now proven (`game/tests/test_solution_optimality.gd` searches each level and
asserts the committed sequence is a shortest solution: 6 + 23 + 44), the second half is
a deliberate choice about the label rather than a hedge (Finding 14 and its follow-up).
"1.37× optimum" reads as a verdict on the level design as much as on the pilot, and only
the pilot is what this tier measures; the vocabulary control (case W) stays in for that
reason, so no line the tier prints matches `/optim/i` even now that the word would be
defensible in prose.

**A paid run's budget is floored so that finishing is possible at all** (Finding 13).
The floor is `2 ×` the committed 73-move reference — **146 actions** — derived from
`levels/solutions.json` rather than written down, so a re-authored level re-checks it
by itself. That is also the paid provider's *default*: `--provider anthropic` with no
`--max-actions` runs at 146, and an explicit value below the floor is refused with a
non-zero exit before the guide is read, before Godot starts and before a token is
spent. `2 ×` is stated rather than tuned: `1 ×` demands a pilot that has never seen
the puzzles make zero wasted moves, and *below* the reference `all_levels_solved` is
unreachable by construction — the whole spend would buy the refusal above. Stage 1 is
deliberately untouched and the two policies are disjoint: ollama keeps its 30-action
default and §B P12's 100 ceiling, with **no** floor, because stage 1 is priced to
prove the channel and not to finish the game.

**Scoring is gated on the core interaction having happened at all** (Finding 12).
Two conditions, ANDed and both read off the action log: a crate moved at least once
(grid-derived, so a push along open floor counts), and a crate *reached a target*
at least once (`boxes_on_target` rose on a step where the board gained a `*`,
excluding the reload and level-advance steps that can raise the count with nothing
achieved). Below that, the run prints **CHANNEL PROVEN / GAME UNMEASURED** and
exits non-zero — the banner *replaces* the competence block rather than sitting
beside it, and carries every figure the block would have printed plus the path of
the report, which is still written. Exit codes: **0** scored, **1** unmeasured (or
no report at all), **2** the two readings of "a crate reached a target" disagree,
which is a wire defect to file rather than a threshold to loosen.

`--prove-scoring` is all of that logic's own negative and positive control:
synthetic reports for a walk that solves nothing, a push along open floor with
`boxes_on_target` untouched, a reload, a level advance, a solve visible only in the
log, an episode reset that replays level 1, a finished run that *does* print the
ratio, a push that moves a crate but reaches no target, a clean `all_levels_solved`
summary above an empty log, a hypothetical level that ships a crate already on a
target and is reloaded, both directions of counter-vs-board disagreement, and the
exit code `--score` returns off a real file on disk. It is the **budget floor's**
control too: a synthetic level set that moves the reference and the floor with it (the
case a hard-coded 73 cannot pass), a truncated `solutions.json` failing closed rather
than yielding a floor of 0, both sides of the refusal boundary plus the fact that it is
paid-only, the provider-dependent defaults, and §B P12's ceiling still refusing 101 on
ollama. And it is the **denominator's own name**'s control: that no line the tier
prints — on the scored path or the refused one — calls the 73-move reference an
optimum. That control is **kept on purpose now that minimality is proven** game-side
(Finding 14's follow-up): it no longer guards an unproven claim, it guards the label
against re-acquiring a reading that would make the scoreline a verdict on the level
design. It needs no game and no model.

### The §B pre-flight (2026-07-26)

Run before spending anything, per P12. Everything below was free.

| # | Check | Verdict |
|---|---|---|
| P1 | Identities, not handles | **PASS.** Actions are `up`/`down`/`left`/`right`/`reload`, never ids. State names are plain (`boxes_on_target`, not `bot`). No room-code equivalent exists — the board is the world |
| P2 | Adapter passes through every PUBLIC field | **PASS, and the channel had to be built.** This game has NO prose: `main.tscn` is ColorRects with no Label, no font, no message line. So the board IS the entire player-facing text channel, and `GodotTcpAdapter.get_terminal_text()` now carries it by joining the very rows `board.gd::render_rows()` draws for the human. Asserted live in both directions — a board arrives, AND it changes when the game changes (a channel serving a stale screen forever would pass the first check and is worse than an empty one, because it looks right). **Still true after the win state was added** (Finding 15): it is colour and geometry — a frame, a backdrop change, a crate-on-target colour — with **no text node of any kind**, precisely so the channel did not have to grow. The pilot already had that information as `level_solved` / `all_levels_solved` and as `*` in the rendered board, so nothing was added to the wire and this verdict stands unchanged. Zero prose is now a stated `PRD.md` constraint rather than an accident of the scene, which is what keeps this row true against a future edit |
| P3 | Truncation is silent starvation | **WOULD HAVE FAILED — FIXED.** The guide is 4,422 chars against the 2,000 default. The cut lands from "The one rule that matters" onward, i.e. every rule that creates the skill. Budget set to 6,000 and `assert_guide_fits` fails the run before any model is contacted |
| P4 | Action channel sends what the LLM thinks | **PASS.** `action_id` mode maps name → id 1:1; an unknown name is dropped, never coerced to a neighbouring id. The truncation salvage added in Finding 7 keeps that property — it refuses to salvage a name the config does not declare |
| P5 | Prompt must not leak what the client hides | **WAS LEAKING — CLOSED, and the audit ran the other way too.** There is no HUD at all here, so every field had to be justified rather than passed through. Six of eight are derivable by looking at the board. Two are redacted: `moves_taken` (a score the game keeps and shows nobody — Finding 6 — and the exact number this tier scores against) and `grid` (not hidden, *moved* to the Terminal panel where it renders aligned instead of JSON-quoted). Verified against a **rendered prompt**, not against the config. **One asymmetry ran the OTHER way and is now closed on the human side** (Finding 15): the pilot could see `*` in the board and `all_levels_solved` in its state block, and the player at the keyboard could see neither — a crate on a target was painted like a crate on floor, and the finished game looked hung. Fixed in the game as colour, so **nothing entered or left `redact_state_fields`** and this row's disposition is unchanged. P5 is a two-way audit: "the prompt must not leak what the client hides" has a mirror, "the client must not hide what the prompt is given" |
| P6 | Guide teaches the RULES that create skill | **PASS.** Push-not-pull and its consequences: why a wall-flush crate can only slide, why a corner is permanent, why finishing a crate early can wall you off, and that reload is the correct move rather than a failure. No solution sequences — teaching the moves would measure recall |
| P7 | Competence from the reasoning, not the exit code | **RUN — the channel is proven and the local model is below the floor.** Quantified rather than sensed: across 160 actions over three runs the pilot moved a crate **0 times** on a first level solvable in 6 moves (instrument-derived from the boards since Finding 11, not counted by hand), and of the crate positions it stated out loud only ~40% matched the board (9/17, 9/21, 41/59 right/wrong). It is engaged with the right concepts (`crate` 67×, `push` 30×, `target` 33× in 30 actions) and cannot reliably localise a glyph in a 7×5 grid. This is NOT P12's ambiguous-silence case: a specific wrong belief, stated out loud, is diagnosable — see Finding 8 |
| P8 | Never pool across an information fix | **Boundaries declared** — see the run table. Row 1 → 2 crosses the Finding 7 fix and is a before/after pair, never a trend. Findings 9 and 11 are *reporting* fixes that never touched a prompt, so neither creates a behavioural boundary — the three rows stay comparable across both |
| P9/P13 | Episodes: samples or replays? | **Declared `deterministic` and probed live** before every run: two resets replay identically over 4 steps, and the probe (`left`, level 1's first committed move) really moved the state, so "identical" is not vacuous |
| P10 | Pilot needs memory, not just state | **Configured** — `history_window: 12`, roughly one crate's worth of work including the walking. The default 5 forgets the plan halfway through executing it |
| P11 | A prompt guard is part of the game | **WOULD HAVE MADE THE GAME UNPLAYABLE — FIXED.** The repeat guard blocks the 3rd identical proposal at its default. Pushing a crate five cells along a row *is* five consecutive `left`s, and the committed solutions contain runs of 5 and 6. Raised to 8, and `assert_repeat_guard_allows_real_play` derives the bound from `solutions.json` so authoring a longer push run re-checks it automatically |
| P12 | Local model first | **DONE — `gemma4:26b`, zero API cost.** It paid for itself: P3, P11, and Findings 6–9 were all found free, and two of those are UGT-core defects that would otherwise have surfaced on a paid bill |
| P14 | Content: solvable, and every obstacle teaches | **Solvable is PROVEN, and each shipped sequence is the SHORTEST possible** — R1 and R2 replay the committed solutions through the live engine every run, and `game/tests/test_solution_optimality.gd` breadth-first-searches each level *through `board.gd::try_move()` itself* and asserts the committed length is minimal (6 / 23 / 44 = the 73-move reference; level_03 costs ~7.7e5 states and ~16 s, with an opt-out flag). That proof is game-side because minimality is a claim about authored CONTENT, and a solver in this harness would be a second rules engine next to the one it checks. **Two further content claims became assertions on 2026-07-26 (T-007), both game-side and neither a solver:** the *gradient* — the shortest solution getting strictly longer across the three levels, which is the part of "increasing difficulty" that crate count and grid area never covered (`game/tests/test_shipped_levels.gd`, asserted as a relationship, not as 6 / 23 / 44) — and *deadlock-capability*, the claim `reload` rests on: every shipped level contains at least one cell a crate could never be recovered from (`game/tests/test_deadlock_cells.gd`, 4 / 8 / 8 cells, ≥ 1 asserted). **Name the limit of that second one:** it is a geometric witness counted off `board.gd::render_rows()` — a non-target cell walled on one vertical *and* one horizontal side, or a wall-flush lane with no target in it — not an enumeration of every deadlock (two crates jamming each other is one it does not count) and not a claim that a player can reach one. Reachability would need the searcher; the reload button's justification does not. "Teaching" works differently in this genre and needs saying: there is no authored refusal text because there is no text. A refused move returns byte-identical state, and the board itself is the explanation — a human sees the wall. The guide therefore has to teach *how to read a refusal* ("if the board comes back exactly as it was…"), which is the substitute for a spoken one |

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

**All three rows now trip the core-interaction gate**, re-derived on this commit:
`--score` exits **1** on each with the CHANNEL PROVEN / GAME UNMEASURED banner and
prints no competence figure. That is the correct reading of a stage-1 result and
costs nothing — per P12 no figure from these rows was quotable anyway; the gate is
what makes that unquotability machine-enforced instead of remembered.

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
| `playtest_sokoban.py` | Tier 3 — the LLM runner. Owns the §B pre-flight, then hands the adapter to `playtest_game_with_adapter()`. Also owns the competence scoreline and the core-interaction gate that refuses to score a run in which no crate ever moved — re-runnable model-free via `--score` and self-proving via `--prove-scoring`. Also owns the **paid action-budget floor** — derived from `levels/solutions.json`, so a paid run that could not reach `all_levels_solved` is refused before anything is spent. |
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

**Follow-up (2026-07-26): one of the three things listed above was a defect, not a
scope call, and it is fixed.** The finding is left as written. Of "nor the level
number, nor any *solved* acknowledgement", the second half was never a missing
feature — the game *entered* a terminal state and showed nobody, which is Finding
15 and a game defect. It is fixed as **colour, not text**: a crate on a target
gets its own colour, and finishing the third level draws a frame and changes the
backdrop. Deliberately non-textual, so the P2 premise (the rendered board is the
whole text channel) survives and `get_terminal_text()` needed no change. The other
two halves — the invisible **move counter** and the level number — are still filed
and still a scope call for the game's owner, and still carry the coupling named in
the master task list: if `moves_taken` reaches the screen it must leave
`playtest.redact_state_fields`, and the competence metric changes with it, so that
decision belongs *before* stage 2.

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
That label was wrong twice over — it printed on a partial run, *and* it called the
denominator an optimum, which nothing here pins; the second half was not caught
until Finding 14. The quoted strings below are what the code actually printed at
that commit and are left as they were.
`report_competence` printed the moves/reference ratio unconditionally, so the real
100-action stage-1 report — **0 of 3 levels solved, 0 crates moved** — was scored
`100 moves (1.37x optimum)`. That reads as "37% off the pace", i.e. as a pilot
that played competently and finished a bit slowly. The true reading is that the
game was never played.

The ratio is not a lenient measure of a partial run; it is undefined for one. Its
denominator is the cost of FINISHING all three levels, and a run that finished
none has no numerator to compare against it. Worse than being wrong, it was
*quotable-looking* — a bare multiple of a committed reference, produced by the one
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

**12. The tier could not tell "the pilot played the game" from "the pilot walked
around for 100 turns". FIXED — it is a gate now, not a judgement call.** Finding 11
made the two figures honest; nothing yet *acted* on them. A run that moved zero
crates still printed a competence block, still said PLAYTEST MET, and still exited
0 — so the only thing standing between a stage-1 walk and a quotable-looking result
was a human reading the scoreline carefully.

`LESSONS.md` §B P7 is the check that is supposed to catch this, and its literal
form — grep the reasoning for the core mechanic — is **defeated by this exact
run**. Re-derived on this commit from the recorded 100-action report (`results/` is
generated, so this is evidence about that artifact and this commit only): the pilot
said "push" in its reasoning on **96 of 100 steps** and pushed a crate **0** times.
Word-matching the transcript scores that a clean pass. The one objective observable
that contradicts it was sitting in the same file, unread. A keyword grep measures
whether the pilot has learned the vocabulary; only the board says whether it played.

So scoring is now conditional on two things, ANDed, both from the action log:

* **a crate moved at all** — grid-derived (Finding 11), so a push along open floor
  counts. `boxes_on_target` alone is blind to one, which is why this condition
  cannot be built from the scalar;
* **a crate reached a target at least once** — `boxes_on_target` rose on a step
  where the rendered board also gained a `*`. `crates_moved` alone cannot stand in
  for this: a pilot can shove a crate around for a hundred moves and never satisfy
  the game's objective, and the tier's whole question is whether the *puzzles* are
  any good.

Neither implies the other, so the AND is the check; either alone is a weaker gate
that the real report would have taught us to trust. Below the threshold the run
prints `CHANNEL PROVEN / GAME UNMEASURED`, carries every figure the competence
block would have carried plus the path of the report it declined to score, and
exits non-zero. It is a refusal to publish a number with nothing behind it, not a
claim the pilot played badly.

Two subtleties are worth naming, because both are places a lazier gate would have
been wrong:

* **The arrival is a RISE, not a high-water mark.** A reload restores the level's
  authored arrangement and a level advance replaces the board wholesale, and either
  can raise `boxes_on_target` without the pilot achieving anything — the moment a
  level ships a crate already on a target. None of the three shipped levels does, so
  the exclusion is unobservable *today*; a gate resting on a content fact a level
  author can silently change is not a gate, and `--prove-scoring` carries a
  hypothetical such level as its control.
* **The two readings are made to argue.** A crate landing on a target increments the
  counter *and* turns `$` into `*` on the same step, so on honest wire data the two
  step lists are identical. When they are not, the run is **refused with its own
  exit code (2)** rather than scored: that disagreement is the wire-only defect
  class the ninth invariant (`grid_matches_scalar_state`) exists to catch, and
  scoring across it would publish a figure derived from two different games.

Proven able to fail, four ways, each mutation applied by hand and the file restored
byte-identically (sha256 compared before and after, never `git checkout`):
inverting the arrival threshold turns the scored fixtures red (and lets the walk
"pass"); inverting the crate-moved threshold does the same, so neither condition is
being carried by the other; neutering the contradiction branch turns both
disagreement fixtures red; and neutering the arrival exclusions makes the
pre-placed-target reload score a run that pushed nothing.

Like Findings 9 and 11, this changed only what is **REPORTED** — and the exit code —
never what the pilot receives: no prompt, no redaction and no guard moved, so it
creates **no §B P8 boundary**, and the three stage-1 rows stay comparable on exactly
the terms they already were. The generalisable half of this — that P7 needs an
objective observable and not a keyword grep — belongs in `LESSONS.md` §B and is not
written here.

**13. A paid run could not reach the win condition, and nothing refused it.
FIXED.** `--max-actions` defaulted to **30 for both providers**. The committed
reference solution for all three levels is **73 moves**, so at the default budget
`all_levels_solved` was unreachable *by construction* — not unlikely, impossible.
And after Findings 11 and 12 that is worse than a low score: the ratio is withheld
on a partial run and the core-interaction gate refuses to score one that pushed
nothing, so the entire spend would have bought a **CHANNEL PROVEN / GAME UNMEASURED
banner**. A budget that cannot finish is not a cheap measurement, it is a purchased
refusal, and the tier had no opinion about it.

The paid provider now has a floor, and the floor is also its default: `2 ×` the
committed reference, **146 actions**. `--provider anthropic` with no `--max-actions`
runs at 146; an explicit value below the floor exits non-zero naming the requested
value, the 73-move reference and where it was read from, the required 146, and why —
before the guide is read, before Godot is started, before a token is spent.

The multiple is *stated*, not tuned. 73 is what playing three known puzzles perfectly
costs; a pilot that has never seen them pays for every exploratory step, every walk to
line up behind a crate, and every `reload` (which costs an action *and* rewinds the
level). At `1 ×` finishing demands zero waste; below `1 ×` it is impossible. `2 ×` is
the smallest floor that leaves a non-zero error allowance. Rejected: a
`playtest.paid_budget_multiple` config knob — `playtest.*` carries per-game *game*
facts, and how much credit a run may spend is a harness policy that stays in the
harness.

**Derived, not typed** — the same discipline `assert_repeat_guard_allows_real_play`
already uses (Finding 11's neighbour, P11): `reference_moves()` sums the sequences in
`levels/solutions.json`, so authoring a longer level re-floors the budget without
anyone remembering to. It also **fails closed** on an empty or zero-move solutions
file, because a truncated artifact must not silently hand a paid run an unbounded
default. `--prove-scoring` proves the derivation with a synthetic level set (10 + 5
moves → floor 30), which is precisely the case a hard-coded 73 cannot pass.

**Stage 1 is untouched, and the two policies are deliberately disjoint** (the floor,
146, sits above the ceiling, 100): ollama keeps its 30-action default and §B P12's ~100
cap and gets **no** floor. They price different jobs — stage 1 proves the CHANNEL and
may not spend; stage 2 measures the GAME and must be able to finish it. A floor applied
to ollama would make stage 1 unrunnable.

Proven able to fail, four ways, each mutation applied by hand and the file restored
byte-identically (sha256 compared before and after, never `git checkout`): hard-coding
73 into the floor turns the synthetic-level-set case red; weakening the comparison to
`< 0` turns both refusal cases red; returning the stage-1 default for anthropic turns
the paid-default case red; and dropping the `provider == "anthropic"` guard turns the
paid-only case red, so the scoping is asserted rather than incidental.

**P8: no boundary.** `max_actions` is a loop bound, recorded in the report and absent
from `_build_prompt` — no prompt, redaction or guard moved, so like Findings 9, 11 and
12 this changes only what is *spent and recorded*, never what the pilot receives. Two
caveats that are about arithmetic rather than information: runs at different budgets
answer different questions and are not poolable on their own terms (the stage-1 table
already treats row 3 that way), and the three recorded stage-1 rows are unaffected
because the stage-1 default and ceiling are unchanged. The generalisable half — derive
the pilot's action budget from the game's own committed reference, and refuse a paid run
that cannot reach the win condition — belongs in `LESSONS.md` §B and is not written
here.

**14. The scoring denominator was called an "optimum", and nothing anywhere proves
it is one. FIXED.** There is **no solver in this repo** — no BFS, no minimality
search, nothing that could establish a lower bound on any level. What
`tests/test_shipped_levels.gd` actually pins about each committed sequence is three
properties, and minimality is not among them: it **solves** its level, it is
**unpadded** (`moves_taken == actions.size()`, so no no-op can hide in it), and it
does **not solve early** (`is_solved()` is asserted false before the final action).
A shorter solution may well exist for all three levels; nobody has looked.

The word travelled. It started in `game/TASKS.md`'s T-005 delivery note ("every
committed sequence is BFS-**optimal**"), reached both READMEs, and ended up as the
printed **label of the ratio's denominator** — `optimum for all 3 levels: 73 moves`
and `moves/optimum ratio: 1.37x`. That is the worst place for it to land. "1.37×
optimum" asserts a proven floor and reads as a verdict on two separate things at
once: that the pilot played 37% off the best possible line, and that 73 is what the
level design costs. "1.37× the committed reference" claims only what is true — 37%
more moves than one sequence known to work, which may itself be beatable. Finding 11
caught half of this (the ratio printing on a partial run) and left the other half
sitting in the label it rewrote.

Renamed to *the committed reference* in the scorer's own strings, the P11 pre-flight
message, both config comments and both READMEs; `game/TASKS.md`'s claim is corrected
in place with a dated correction line rather than quietly reworded. **No logic, no
threshold, no withholding rule and no gate moved** — this is vocabulary. The one
structural improvement that came with it: `competence_lines` now calls
`reference_moves()` instead of re-summing the sequences inline, so the scoreline and
the budget floor share a single derivation (and inherit its fail-closed behaviour on
a truncated `solutions.json`, which the inline `sum` did not have).

The new control is a **vocabulary** control, case W, and it is what makes the rename
permanent rather than a one-time edit: for a finished run *and* for a walk, no line
the tier prints — competence block or `CHANNEL PROVEN / GAME UNMEASURED` banner —
may match `/optim/i`. The block also says out loud what the number is not: *"the
committed levels/solutions.json sequences — a known-working reference, not a proven
minimum; no solver exists here"*. And case A's old guard, `"x optimum" not in text`,
was **coupled to the very word being renamed** — it would have gone on passing while
guarding nothing. It now guards the *shape* of a ratio, `\d+\.\d+x`, which no rename
can defeat.

Proven able to fail, three ways, each mutation applied by hand and the file restored
byte-identically (sha256 compared before and after, never `git checkout`), against a
58-check green baseline:

* putting the old `optimum for all 3 levels` label back turns **both** W rows red
  (`NOT MET (2 failed)`, exit 1) while every `_RATIO`-keyed row stays green — which
  is exactly the point: those rows follow the label wherever it goes and cannot see
  this defect;
* making only the **refused** path claim it (adding "undefined against the optimum"
  to the `NOT REPORTED` line) turns the walk's W row red alone (`NOT MET (1 failed)`),
  so the banner path is covered and W is not one-sided;
* dropping the `if finished and moves and reference:` condition, i.e. reproducing
  Finding 11's original defect, turns case A's hardened row red via the new
  `\d+\.\d+x` regex — along with A's refusal row and G — `NOT MET (3 failed)`. The
  printed multiple on the walk fixture is `1.37x` again, the original figure.

**P8: no boundary.** Nothing here touches `_build_prompt`, `redact_state_fields`, a
guard threshold or a budget; like Findings 9, 11, 12 and 13 it changes only what is
**REPORTED**, so the three stage-1 rows stay comparable on exactly the terms they
already were and no run needs redoing. The generalisable half — *a scoring
denominator must name what is actually pinned about it, and a control keyed on a
label cannot outlive a rename* — is a `LESSONS.md` candidate and is not promoted
here.

**Follow-up (2026-07-26, T-005): the retracted claim was re-established by
evidence, and the vocabulary control was deliberately kept.** The finding above is
left exactly as written — the record of the mistake is the artifact, and "it turned
out to be true" is not a reason to un-write a retraction that was correct at the
time. What changed is that there is now a search: `game/tests/test_solution_optimality.gd`
computes the true shortest solution for each level and asserts it equals the
committed sequence's length. All three were already minimal — **6 / 23 / 44, summing
to the 73-move reference** — so nothing about the content moved; what moved is that
the claim is now *tested* rather than believed.

Three deliberate decisions, so a later reader does not read them as oversights:

* **The proof lives game-side, not here.** Minimality is a claim about authored
  content, so it belongs to the repo that owns the levels. A BFS in
  `playtest_sokoban.py` or in `godot_tcp_adapter.py` would be a second rules engine
  standing beside the one it is meant to be checking — the exact drift the
  transport-only adapter rule exists to prevent. Nothing under `integration/` gained
  a solver, a frontier or a shortest-path anything.
* **The search drives `board.gd::try_move()`, it does not re-implement pushing.** A
  hand-rolled push/collision loop would answer a question about a copy of the game.
  Driving the real engine costs ~16 s and 772,948 reached states for level_03 (0 ms /
  66 states for level_01, 183 ms / 11,231 for level_02), which is affordable, so there
  was no excuse. It also gives the check a property a private transition function
  could not have: mutating `board.gd`'s push rule changes the searcher's answers.
* **The scoreline still says "the committed reference", and case W stays.** The word
  is now defensible in prose, and it has returned to prose — the §B P14 row, both
  READMEs, the game's own delivery note. It has *not* returned to the instrument's
  label, because "1.37× optimum" is heard as a verdict on two things at once (how far
  off the best line the pilot played, and what the level design costs) and only the
  first is what this tier measures. Trading a working control for a word buys nothing
  measurable.

Proven able to fail, five ways, each mutation applied by hand and every file
restored byte-identically (sha256 compared before and after, never `git checkout`),
against a 99/99 green baseline:

* **the mutation this check exists for** — replacing `level_01`'s sequence with
  `[0, 1, 2, 0, 2, 0, 3, 3]`, an honest **8-move** solution that solves the level,
  contains no refused move and does not win early. All 10 cases in
  `test_shipped_levels.gd` stay **green** (it satisfies every property that file
  pins) and only the two new cases go red: `97 passed, 2 failed`, exit 1. That defect
  was invisible to everything that existed before this suite, which is the whole
  point of the task;
* **the literal one-move pad** the Accept criterion names — appending a 7th action to
  `level_01` gives `95 passed, 4 failed`. Worth being precise about who catches what:
  no honest 7-move solution to `level_01` exists (a solved position is reachable at
  depth 7 only by passing through one at depth 6, and the engine freezes on a solved
  board), so a +1 pad is necessarily a *refused* move — it is caught by the
  pre-existing unpadded / not-solved-early checks in `test_shipped_levels.gd` **and**
  by the new length comparison. The 8-move case above is the one only the new suite
  can see;
* **one-sidedness** — weakening the searcher's goal test to
  `boxes_on_target >= boxes_total - 1` so it can *under*-report gives
  `93 passed, 6 failed`, with the per-level cases failing as `search < committed`
  (level_01 found 1 vs 6, level_02 found 7 vs 23) and four of the six searcher
  controls red alongside them. So the equality is two-sided, not "committed ≤ search";
* **the state-key capacity guard** — lowering `MAX_NON_WALL_CELLS` to 5 fails every
  level with its named message (`…holds at most 5 non-wall cells (this level has 32)…`)
  rather than silently returning a wrong number, which for a test whose entire output
  *is* a number is the failure mode that matters most;
* **that the searcher really consumes the live rules engine** — making a push onto a
  target illegal in `board.gd::try_move()` turns every fixture and both fast levels
  red with "unsolvable" (`76 passed, 23 failed`, wide collateral redness across the
  other suites, as expected). A searcher with its own private copy of the rules would
  have gone on answering 6 / 23 / 44.

**Two skip-path facts, because a skippable check is where a vacuous green hides.**
`SOKOBAN_SKIP_SLOW_TESTS=1` drops *only* level_03's search (suite back to ~0.7 s from
~16.5 s) and is **opt-out**: nothing in the game's tooling, this harness's ladder or
`tools/check_runner_reports_failure.sh` sets it, so the default is always the real
search. And the skipped case still asserts the recorded length, so the 8-move mutation
above is red with the flag **set** too (`97 passed, 2 failed`).

**P8: no boundary.** Nothing here touches `_build_prompt`, `redact_state_fields`, a
guard threshold or a budget, and no ladder rung, invariant or adapter behaviour
changed. The only edits under `integration/` are prose: three comments and the two
printed lines that stated "no solver exists here", which this task made false. Like
Findings 9, 11, 12, 13 and 14 it changes what is **tested and recorded**, never what
the pilot receives — the three stage-1 rows stay comparable on exactly the terms they
already were, and no run needs redoing. No stage-1 figure is quoted here.

**15. The game reached its terminal state, and its own player could not tell that
from a crash. FIXED, game-side.** Two defects with one cause: `main.gd` — the human
front end — contained **no reference to `level_solved` or `all_levels_solved`**, so
the view never read either flag.

* **A crate standing on a target was drawn identically to a crate on floor.** The
  crate is a full-cell rect and the target is a 35%-of-a-cell pip underneath it, so
  arriving on a target erased the only marker that said it was one. The *objective*
  of a Sokoban level was invisible to the player achieving it — while this harness's
  wire carried `*` for that exact cell and `boxes_on_target` beside it.
* **After the third level the game read as hung.** `board.gd` freezes `try_move()`
  once `all_levels_solved` latches — deliberate, documented, and depended on by R2
  and by `invariants.py::all_levels_solved_is_terminal`. But nothing on screen
  changed and no message appeared, so *winning* and *crashing* looked the same. The
  freeze was never the bug; showing it to nobody was.

**Fixed as colour and geometry, with no text node of any kind** — a crate-on-target
colour, a frame around the finished board, a changed backdrop. Text was rejected on
purpose: the rendered board is this game's entire player-facing text channel (§B
P2), so a `Label` would have to travel down the wire or the pilot would be told less
than a human, and the P2/P5 rows would need re-dispositioning for a cosmetic. The
board's freeze is unchanged, `R` still clears it, and the game's own suite proves the
un-freeze by a **move being accepted** rather than by reading a flag (suite 99 →
105/105, six mutations red and restored byte-identically).

Two things worth separating, because they are the reason this sat green for so long:

* **Nothing in this harness could have caught it.** Every ladder rung and the LLM
  tier read `get_state()`, which has carried `level_solved`, `all_levels_solved` and
  `grid` all along. The tester was told *more* than the player, so a perfectly green
  ladder is consistent with a game that looks broken to a human. §B P5 is normally
  read one way — the prompt must not leak what the client hides — and this is its
  mirror: **the client must not hide what the prompt is given.** Auditing the
  asymmetry in that direction is what surfaced it.
* **Route: the game's repo.** No adapter, invariant, config or wire field changed;
  the fix is entirely in `game/scripts/main.gd` plus a stated `PRD.md` constraint
  that the screen carries no text, so the P2 premise cannot be broken by accident
  later.

**P8: no boundary.** Nothing the pilot receives moved — no prompt, no
`redact_state_fields`, no guard, no budget, and no wire field. The bridge front end
owns its own `Board` and never calls `main.gd`, so the three stage-1 rows stay
comparable and no run needs redoing. No stage-1 figure is quoted here.

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
