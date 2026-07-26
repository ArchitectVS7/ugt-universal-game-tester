# Tiny Escape Room — UGT integration

Drives `../game` (Node.js, JSON-lines over stdio) through UGT's built-in
**`simulation`** engine. No adapter code: `engine.type: simulation` +
`entry: ../game/src/bridge.js` is handled entirely by `SubprocessAdapter`,
which runs `.js` entries with `node`. This is the most CLI-native of the three
examples.

## Run it

```bash
# from the repo root
cd examples/escape-room/game && npm test && cd -      # game suite: 104/104

# the trial ladder — each rung is fail-closed, exit 0 only when every check passed
for s in spike_escape_room smoke_escape_room_adapter \
         verify_round1 verify_round2 verify_round3; do
  python3 examples/escape-room/integration/$s.py || break
done
```

Recorded results — **whole ladder re-run 2026-07-26 (late), and again after each
of the Finding 7 and Finding 9–11 fixes.** Every number below came from the last
of those passes, not carried forward:

| Rung | Script | Result |
|---|---|---|
| 1 spike | `spike_escape_room.py` | **SPIKE MET — 30/30** |
| 2 smoke | `smoke_escape_room_adapter.py` | **SMOKE MET — 12/12** |
| 3 R1 playability | `verify_round1.py` | **ROUND 1 MET — 18/18** |
| 4 R2 full spine | `verify_round2.py` | **ROUND 2 MET — 56/56**, 570 commands |
| 5 R3 robustness | `verify_round3.py` | **ROUND 3 MET — 10/10**, 2 seeds × 160 steps, 14 invariants |
| — Tier 1 CLI | `ugt verify` | **6/6 PASSED**, 0 FAILED, exit 0 |
| — stage 1 | `ugt playtest --provider ollama` | **channel PROVEN** (Finding 7); after Findings 9–11 the pilot **escapes** |

Game suite **104/104** (88 + 6 for the Finding 7 fixes, + 10 for Findings 9–11).

⚠️ **The previous table was stale in three places** (spike 27, R1 17, suite
85/85) and nothing failed to say so. The `700c46c` pre-flight added 3 game tests
and `3a47494` added R1's flag-announcement check, both *after* the table was
written. **Re-run the ladder rather than citing this table** whenever the game
or the scripts have moved — a recorded result is evidence about a commit, not
about the working tree.

The generic CLI tiers still work and are still worth running, but they are no
longer what the gate rests on — see Findings 1 and 2 for why:

```bash
cd examples/escape-room/integration
ugt smoke-test --config ugt.config.yaml                               # PASSED 5/5
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml    # 6/6, 0 FAILED
```

| Tier | Command | Result |
|---|---|---|
| 3 LLM stage 1 | `ugt playtest --provider ollama` | **run repeatedly** — see "Tier 3" below |
| 3 LLM stage 2 | `ugt playtest --provider anthropic` | **not run** (bills API credits) |

## Files

| File | Role |
|---|---|
| `ugt.config.yaml` | `engine.type: simulation`; 41 actions, **generated** from `node ../game/src/bridge.js --actions` so ids cannot drift from the CSVs (the spike asserts this) |
| `invariants.py` | 14 predicates as an `InvariantSuite` — written once, consumed by R1/R2 (per command) and R3 (wrapped for the fuzzer) |
| `spike_escape_room.py` | Rung 1 — raw JSON-lines over pipes, no adapter |
| `smoke_escape_room_adapter.py` | Rung 2 — the `SubprocessAdapter` contract |
| `verify_round1.py` | R1 — one full escape, invariants after every step |
| `verify_round2.py` | R2 — the whole content surface: all 41 actions, every object, every use-gate, every place-bound puzzle |
| `verify_round3.py` | R3 — `InvariantFuzzer` + negative control + generic checks + determinism |
| `feature-map.yaml` | `ugt verify` — F1–F6 as one continuous playthrough of the real flag chain |
| `strategy-guide.md` | Tier 3 — the briefing an LLM playtester reads |

`fuzz_escape_room.py` was **removed** on 2026-07-26, superseded by
`verify_round3.py`. It pre-dated `invariants.py` and carried a private copy of
six predicates that R1/R2 had no way to share; keeping both would have been the
exact drift `InvariantSuite` exists to prevent. Its three good ideas were kept:
the negative control, same-seed replay, and the non-vacuity guard.

## Tier 3 pre-flight — the `LESSONS.md` §B audit (2026-07-26)

Run before spending anything, per P12. Findings below were all free.

| # | Check | Verdict |
|---|---|---|
| P1 | Entities have identities, not handles | **WAS HALF-CHECKED — NOW FIXED.** The original disposition ("the prompt lists `take_lantern`, never `14`") audited the *action* channel and stopped there. **State is a channel too**, and it was answering `current_room: "R04"` — a handle a player is never shown. `room_name` added; see Finding 7b |
| P2 | Adapter passes through every PUBLIC field | **WAS BROKEN — FIXED TWICE.** The step path (narration dropped entirely), then the reset path (opening room never sent); see Finding 7a. **Auditing that a channel exists is not auditing that it is complete** |
| P3 | Truncation is silent starvation | **FIXED, then re-checked after the Finding 7 rewrite.** The guide grew 3,206 → **5,813** chars, leaving only 187 under the 6,000 budget; raised to **8,000** (now 6,584 after the Findings 9–11 rewrite). A budget only protects while it has slack, and this one is worth re-measuring (`wc -c`) every time the guide is edited |
| P4 | Action channel sends what the LLM thinks | **PASS** — names map 1:1 to ids, asserted by the spike against the game's own table |
| P5 | Prompt must not leak what the real client hides | **WAS LEAKING — CLOSED.** `flags` redacted; see below |
| P6 | Guide teaches the RULES that create skill | **PASS** after two rewrites — refusal-reading, the flag chain, the exhaustive `Exits:` line, and that a puzzle resolves where it lives. **P14 is the other half**: the *game* must teach too, and it did not (Findings 9–11) |
| P7 | Verify competence from reasoning text | **RUN — failed, fixed, re-run; now PASS on the strongest available evidence: the pilot finished the game.** Pre-fix the reasoning mis-bound room codes to names; after Finding 7 it derived objectives from authored refusals unprompted; after Findings 9–11 it escaped. Note this was never P12's ambiguous **silence** case — a specific wrong belief, stated out loud, is diagnosable, and both halves reproduced off-model against the CLI |
| P8 | Never pool across an information fix | **four boundaries** — one per information fix. See the run table under "Tier 3": those rows are before/after pairs, never a trend |
| P9/P13 | Episodes: samples or replays? | **declared `deterministic` and probed live** |
| P10 | Pilot needs memory, not just state | **configured** — `history_window: 12`, ledger keyed on `current_room`, narration recall on |
| P11 | Hard loop ceiling needs code | **fired for real.** The pilot invented the action name `use_flask_oil` and asked seven times; the unknown name was dropped rather than coerced (P4) and the hard block broke the loop deterministically instead of re-asking the model |
| P12 | Local model first | **DONE — four `gemma4:26b` runs (2×30, 2×100), zero API cost.** It paid for itself repeatedly: Findings 7 and 9–11 would all have been discovered on Haiku's bill, and each fix was verified on the free model too |
| P14 | Content graph: solvable, and every obstacle teaches | **TRACED — solvable confirmed (26 moves, 10/10 rooms), teaching was NOT.** Three defects: one door described an exit the rules denied, a double-gate stranded the game's best hint, and an authored verb vocabulary was never accepted. See Findings 9–11 |

### P2 — the pilot was going to play a text adventure with no text

`src/bridge.js` called `executeCommand(...).state` and **discarded `.message`**.
The engine narrates every command — room descriptions, exits, what is visible,
object descriptions on `examine`, and the authored success/refusal lines — and
`src/cli.js` prints all of it. None of it crossed the wire. `BaseAdapter`'s
`get_terminal_text()` returns `""` for adapters that cannot expose text, so the
tier would have rendered an empty Terminal panel, silently, forever.

For this genre that is total: the guide's own advice — *"`examine` everything,
descriptions tell you what an object is for"* — would have been unfollowable, and
`examine` would have been a pure move-waster. The refusal *"The wick is bone dry.
Without oil it will never catch"* is the game telling you the next objective, and
the pilot would have seen `use_lantern` change nothing, with no idea why.

Fixed on both sides: the bridge now carries narration in `info.message` (response
shape unchanged), and `SubprocessAdapter` gained a **configured** narration
channel (`playtest.narration_field`, default `info.message`) plus
`narration_is_live()` so a pre-flight can assert the channel really carries
rather than trusting it was wired. 3 game tests added, mutation-checked (removing
the fix fails 6). The spike's old `info == {}` assertion was **pinning the bug**
and now asserts the channel instead.

### P5 — the pilot sees the puzzle's skeleton; a human does not

The state dump lists all 8 flags **by name**: `iron_door_open`, `has_oil`,
`steam_vented`, `has_cog`, `knows_hour`, `clock_set`, `gate_open`. Piping the
same six commands through `node src/cli.js` prints those names **zero** times —
they are internal machine state, and a human infers the chain from prose alone.

Reading `knows_hour` and `clock_set` in the opening cell tells you there is a
clock to set from an hour you must learn, long before you find the ledger. That
is a structural hint sheet, and it makes the pilot's job easier than the game's.

**Closed by redacting them** — `playtest.redact_state_fields: ["flags"]`. The
pilot plays with player-facing information only, from the channel check onward.
Redaction is prompt-only: `evaluation.victory_key`, the invariants, the episode
records and the report all keep the full state. Verified against a prompt
rendered after two flags had actually been set — **no flag name appears anywhere
in it**, including in the recent-action deltas, which `_redact_delta` also
strips.

**Removing a signal is only safe if the replacement is really there**, so that is
now asserted rather than assumed. A human learns a lock opened by reading the
game's reply, and R1 gained a check that **every one of the 8 flag flips is
announced in the narration** — proven able to fail by mutating the bridge's
narration back out (8 silent flips, R1 red, reverted md5-identical). A future
content edit that adds a flag whose flip is silent now fails R1 instead of being
discovered mid-playtest.

The guide was rewritten to match: it no longer calls `flags` a progress bar,
because there isn't one. It says so plainly — *"The state will not tell you what
you have unlocked… you find that out the way anyone in a prison would, by trying
a door and reading what the game says back"* — which teaches the skill the game
actually rewards (P6).

### Context budget

The rendered prompt is **~9,900 chars (~2,500 tokens)** after the Finding 7
rewrite: objective, state, 12 recent actions with deltas, the narration tail,
then the guide. Sized for this game rather than copied — a comparable RPG
integration runs ~20,000 chars because it has an 8-mission story and a 35-verb
surface; here that would be padding, and padding costs local-model latency
without adding knowledge.

## Tier 3 — stage 1 run, stage 2 still gated

**Stage 1 (local) has been run four times**, across three information fixes.
Command, verbatim:

```bash
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md \
  --max-actions 30 --provider ollama --model gemma4:26b \
  --output results/channel-check-ollama.json
```

| Run | Actions | Auto-flags | Rooms | Flags set | Outcome |
|---|---|---|---|---|---|
| pre-Finding-7 | 30 | **2** | 4/10 | 1/8 | stuck in R04 for 12 moves |
| post-Finding-7 | 30 | **0** | 5/10 | 1/8 | R05 Furnace Room, valve wheel held |
| post-Finding-7 | 100 | **0** | 8/10 | **6/8** | stalled at the mute door — this is Finding 9 |
| post-Findings-9–11 | 100 | 3 | **10/10** | **8/8** | **ESCAPED**, 30 moves vs. the 26-move optimum |

⚠️ **P8: four separate boundaries.** Each row measured a different information
surface, so no two rows may be pooled or read as a trend. They are four
before/after pairs, each one evidence about the fix immediately above it.

Both runs: 0 invariant violations, `escaped` false, seeding declaration proven
live beforehand (`deterministic`, two resets identical over 4 steps, probe
non-vacuous).

**The pre-fix run is why this stage exists.** The channel was live — narration
arrived, action names mapped, nothing crashed — and the pilot still could not
process the basic loop, because two things a human sees were missing from the
wire. Finding 7 has the diagnosis; both are now fixed, and the post-fix run
shows the loop working: navigate, collect, unlock, advance a room tier, read a
gated refusal and derive the next objective from it.

Stage 2 (Anthropic) remains deliberately un-run, and is now a credit decision
rather than a blocked one:

```bash
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md --max-actions 40
```

**There is no seed axis here, and it is now DECLARED rather than described in
prose.** The game has no RNG at all — one map, one solution, one ending, no lose
state — so dice's `playtest.episode_seeds` has nothing to rotate, and
`SubprocessAdapter` does not implement `reset_seeded()` (it inherits
`BaseAdapter`'s raise). The config says so explicitly:

```yaml
playtest:
  seeding: deterministic
  probe_action: 4          # `look` — always legal, always moves the state
```

UGT probes that against the live game before a run starts (verified: PROVEN over
4 steps, and the vacuity guard confirmed to fire when pointed at an action that
is inert from the opening position). The consequence: this tier is a
**competence** measure — does a pilot given the guide escape, and in how many
moves against the 26-move optimum — never a rate. The run report now carries
`seeding_mode` and a `sample_note` saying the effective sample size is 1
regardless of episode count, so the denominator cannot be misread later.

If variety is ever wanted it has to come from authoring alternate CSV content
sets, which the game's design already supports. See `LESSONS.md` **P13** and
`ugt/core/seeding.py`.

## Findings

Things this integration surfaced that are worth knowing.

**1. `ugt verify` exited 0 even when features FAILED — FIXED 2026-07-26.**
`handle_verify` (`ugt/cli.py`) discarded `verify_game`'s return value and only
called `sys.exit(1)` on an *exception*, so a run reporting `1 FAILED` still
exited 0. Confirmed by inverting F6's assertion: report said `passed 5 failed 1`,
shell saw 0. Every example's gate is phrased "`ugt verify` … exits 0 with 0
FAILED features", so **a gate checking only the exit code was passing red runs**.
Also hit independently by `dice` (its Finding 5).

Now exits 1 on `failed` **or** `not_reached` (a feature never reached has not
been verified). Negative control run before believing it — inverted assertion
gives exit 1, clean map gives exit 0 — and every feature-map integration in the
portfolio re-run to check nothing had been silently red: `dice` 4/4,
`escape-room` 6/6, and a third (a space trading game kept outside this repo)
9/9 — all still exit 0. Blast radius was zero.

**2. `ugt smoke-test` passes ~45% of the time on a FROZEN state here.** Only
**6 of 41** actions change state from the start room, and an inapplicable action
is documented to consume nothing — not even `moves_taken`. So five uniform-random
steps leave the observation vector untouched with probability `(35/41)^5 ≈ 45%`,
and the CLI still prints "fully operational". Measured, not modelled: three
consecutive runs on 2026-07-26 produced a frozen vector in two of them.
`smoke_escape_room_adapter.py` drives a known-good script instead and asserts
the state moved. **This generalises to any game with a large action space and
context-gated actions** — the smoke tier's uniform-random policy is the wrong
probe for that shape. Promoted to `LESSONS.md` **O11**; the CLI tier itself is
unchanged, so `ugt smoke-test` still has this property and the ladder's smoke
rung is what the gate rests on.

**3. Random play cannot solve this game, by design.** R3's walk reached **9
distinct states and 2 of 10 rooms in 60 steps**, and never escaped. A uniform
policy almost never advances an 8-link flag chain. That is a property of the
genre, not a defect, and it is the clearest illustration in this repo of why the
tiers are not interchangeable: R3 proves the game never *breaks* under nonsense
input, while only R1/R2 (scripted) and Tier 3 (an LLM reading
`strategy-guide.md`) can show it is *completable*. R3 prints its own reach for
exactly this reason, and three generic-check observations (`state-cycle`,
`dead-action`, `action-coverage`) are dispositioned in the script with the
reason — `dead-action` in particular is refuted by R2, which issues all 41
actions and asserts each one's real effect.

**4. Observation aggregators are list-only.** The integration PRD proposed
mapping `flags_set_count`, but `flags` is a dict and `count` only applies to
lists (`ugt/core/env.py::get_value_by_path`) — it would have silently read 0
forever, a mapped field that is always a lie. `escaped` is mapped instead, so
all four observation fields are real.

**5. The assertion language has no `len()` and no `in`.** So "the inventory
shrank by one" is not directly expressible in `feature-map.yaml`. It is asserted
there through a behavioural consequence instead (see F5). The ladder has no such
limit — `verify_round2.py` asserts take → drop → **re-take** directly, which is
the stronger claim anyway: a `drop` that *deleted* the item would look identical
to a working one if you only read the inventory.

**6. Two of my own invariants were wrong before the game was.** R1 immediately
failed `escaped_only_in_the_exit_room`: R10 exits south back to R09 and
`escaped` latches, so walking back out leaves a true flag in another room —
which is the PRD's documented behaviour. The predicate now asserts the
*transition* (escaped may only become true in the exit room), which is
compatible with latching and still catches winning from the wrong place.
Separately, R2's first draft asserted "exactly 3 non-puzzle objects" from
memory; the content has 4. Both are the same lesson: **suspect your own
invariant before the game.**

**7. The channel check's pilot got lost, and two halves of why are measurable
off-model. OPEN.** The run stalled: after opening the iron door it spent its
last 12 actions in R04 trying to `go_north` through a wall. Its reasoning names
the confusion outright — *"I am currently in R04 (Guard Corridor)"*, *"I am in
R03 (Guard Corridor)"*, *"I am currently in R04 (Watch Post)"*. R04 is the
Storeroom and R03 is the Watch Post. **It had room codes and it had prose, and
it did not reliably join them.**

P12 warns that a weak local model and genuine starvation look identical from
outside, so the *stall* alone proves nothing. But two components are not model
opinions — they reproduce by diffing `node src/cli.js` against the wire, the
same method that found P2 and P5:

- **7a — `reset` carries no narration; the pilot's first decision is made with
  an empty text panel.** A human's opening screen is the cell: name, description,
  `Exits: north.`, `You can see: map scrap, iron bunk.` Over the wire,
  `get_terminal_text()` after `reset()` returns `''` — verified directly. The
  bridge is not at fault by its own contract: `handleCommand` pins the reset
  reply to exactly one key (`bridge.js:85`, quoting the PRD), so there is
  nowhere for `info.message` to go. The pilot must spend a move on `look` to see
  the room it woke up in, and **the guide never tells it to**. This is the P2
  fix's blind spot: the audit asked whether the narration channel existed, not
  whether it covered every response.
- **7b — the state gives the room's HANDLE, never its player-facing NAME.**
  `current_room: "R04"` is an internal id a human is never shown; what a human
  is shown, on every single entry, is `Storeroom`. So the one field whose job is
  "where you are" answers in a code, and the name lives only in prose that
  scrolls. That is P1 applied to state rather than to actions — the original P1
  disposition ("`take_lantern`, never `14`") checked the *action* channel and
  stopped there.

**Both FIXED 2026-07-26, and the re-run says they were the cause.**

- 7a: `reset` now answers `{state, info}` and narrates the opening room, using
  the same `describeRoom()` the CLI prints — pinned to one source by a test, not
  left as two that happen to agree. `terminated`/`truncated` are still absent: a
  fresh game can be neither, and the bridge does not invent rules.
- 7b: `getState()` now carries `room_name`, derived from the same `rooms.csv`
  column the CLI prints. The PRD's state shape names it, `STATE_KEYS` (spike and
  smoke) pins it, and a **14th invariant** — `room_name_agrees_with_the_room_id`
  — checks the pair against the CSV on **every transition** in R1/R2/R3, so the
  id and the name can never drift apart again.
- UGT core: `SubprocessAdapter.reset()` recorded no narration at all, so the
  tier's first decision was made with an empty panel *for every simulation-engine
  game*, however much prose the game sent. It now records reset narration, and
  clears the tail first so episode 2 cannot open showing episode 1's last line.

Mutation-checked rather than trusted: removing either game-side fix fails 10
tests, and the suite returns to green when restored. Ladder re-run end to end
after the change — spike **30/30**, smoke 12/12, R1 18/18, R2 47/47, R3 10/10
(14 invariants), `ugt verify` 6/6. (R2 later grew to 56/56 under Findings 9–11.)

**The re-run is the evidence.** Same model, same 30 actions: the room confusion
is gone (every reasoning now names its room correctly — *"the Storeroom (R04)"*,
*"the Watch Post (R03)"*), auto-flagged bugs went **2 → 0**, and the pilot got
two rooms deeper, through the iron door into the Furnace Room. It also produced
the first genuine puzzle inference in this integration's history: *"The lantern
is out because it lacks oil. I need to find oil."* — which is P6/P7's positive
signal, the pilot reading an authored refusal and deriving the next objective
from it.

Neither 30-action run escaped, but 30 actions against a **26-move optimum** is
almost no slack for exploration, so that number says little. Given a fair
budget (100, P12's ceiling) the same local model got **6 of the 8 flags and 8 of
the 10 rooms** in 59 moves: through the iron door, lantern lit, steam vented,
cog taken, ledger read, hour known. That is the loop working.

Where it finally stalled is Finding 9 — and it is a content finding, not a
harness one.

**P8 boundary: the pre-fix run is not poolable with anything after it.** Both
runs are kept (`results/channel-check-ollama.json` and `-postfix.json`) because
the pair *is* the finding. Per P12 no number from either is quotable regardless.

**8. A discrete action space leaks the object roster.** The prompt lists all 41
action names, so `use_key_skeleton`, `take_ledger` and `use_cog_bronze` are
visible from inside the opening cell — a human does not know a skeleton key
exists until they find one. Unlike Finding 7 this is **structural to
`action_id` mode**, not a wiring defect: the ids must be declared up front for a
discrete space to exist at all. Recorded because it puts a ceiling on how
faithfully this genre can be measured in this mode — the honest fix is a text
drive mode, not a config change — and because it explains why the pilot's very
first action was `take_map_scrap` from a blank text panel (Finding 7a): it read
the object's name off the action list, not out of the game.

**9. The game taught through refusals — but only on one of its two gate types.
FIXED 2026-07-26.** Every *object* gate had authored, specific fail text
(*"The wick is bone dry. Without oil it will never catch"* names the missing
thing), which is why the pilot solved six links. Every *room* gate shared one
generic engine string — *"The way is shut. You are missing something you'd need
to pass."* — and `rooms.csv` had no column with which to say more. The
100-action run ended exactly there: standing in R07 holding the cog with
`knows_hour` already set — i.e. holding **both** prerequisites — spending its
last ~20 moves re-trying the blocked north door instead of using the cog on the
clock in the room it was standing in.

Fixed by making the door speak: `rooms.csv` gained **`entry_fail_text`**,
authored per locked door, and validation now **requires** it on a gated room and
**forbids** it on an ungated one. The engine's generic line survives only as an
unreachable fallback, and was shortened to *"The way is shut."* — a door with
nothing to teach should not pretend otherwise.

Tracing the chain to author those lines turned up **a structural problem the
content had been carrying all along.** R09 was gated on `clock_set` *and*
`key_skeleton` required `clock_set` — the same lock twice. Because you could not
enter the Antechamber until the clock was set, you could never stand at the
outer gate and *try* the key first, so the key's authored refusal — *"The key
turns a quarter and stops. Something heavier than a lock is holding this gate."*
— was **unreachable content**. And it is the best hint in the game: it is the
line that sends you to find the bolt.

The already-authored fiction said which way round it should be (*"The drawn bolt
lets the key turn at last"* — the bolt is part of the **gate's** lock, not the
stair's), so R09 is now ungated and the chain reads properly: reach the gate →
*"it will want a key cut for this gate alone"* → find the key → *"something
heavier than a lock is holding this gate"* → find the bolt → set the clock →
out. Four beats, each one naming the next obstacle. **Optimum is unchanged at 26
moves**, and R1 still proves it.

**10. `use_verb` was decoration — the game authored a vocabulary it refused to
accept. FIXED.** `objects.csv` declares `unlock`/`light`/`turn`/`fit`/`read` per
object; the engine only ever asked whether the column was non-null and never
read the value. So `read ledger` — the most natural thing a player could type —
answered *"I don't understand that."*, and no output ever printed the verb
either. The authored verb is now a real command, accepted **only** on the object
that declares it (`read ledger` works, `read lantern` does not), which keeps the
vocabulary content-driven: a new object teaches the parser a word with no engine
edit. `unknownVerb` now names the verbs that exist instead of dead-ending.

**11. Puzzles had no geography. FIXED.** `doUse` checked held → usable → flag and
never location, so **every puzzle in the game resolved from anywhere**: you could
unlock the banded iron door while still locked in your cell two rooms away, and
be told *"The door swings open"* where you stood. New `use_requires_room` binds
a puzzle to its place, checked **before** the flag so a player carrying the right
thing is told to move rather than sent hunting for another item. Four objects are
bound (the two keys, the valve wheel, the cog); the lantern and ledger stay
usable anywhere, because lighting a lamp and reading a book are things you do to
the object, not to the world.

Two things worth recording about how this was found. The committed walkthrough
**already** performed every puzzle in its proper room — the geography was the
intent all along and the engine simply never enforced it, which is why the fix
cost 0 moves. And R2 caught the change correctly by failing: its
`key_skeleton` gate arm had been staged in R08, so with the room rule in place it
was refused for the *wrong reason*. Staging both arms in R09 restores what the
check was for, and a new R2 section now asserts every place-bound object refuses
from the wrong room (content-derived, so a newly bound object is covered the
moment it is authored). R2 47 → **56**.

All three fixes are mutation-checked: reverting any one of them turns exactly one
test red, and the suite returns to 104/104 restored.

### What the re-run says about them

The same local model on the same 100-action budget **escaped**: all 8 flags, all
10 rooms, `escaped=True` in 30 moves. The run before these fixes stalled at 6 of
8 with both remaining prerequisites already in hand.

**Read that as evidence about the CHANNEL and the content, not as a score.** P12
is explicit that no stage-1 number is quotable, and that holds here even though
this game's honest metric is competence rather than a rate: 30-vs-26 is a
local-model figure and stage 2 is what may produce a citable one. What the run
*does* establish is the thing the fixes were for — a pilot reading only
player-facing information can now finish the game, which was not true of any
earlier run.

Two things in the log worth keeping:

- **The repeat-block guard (P11) earned its keep.** The pilot invented an action
  name — `use_flask_oil` — and asked for it seven times. There is no such action:
  the flask has no `use_verb`, because taking it is what sets `has_oil` and the
  lantern's own `use` does the filling. UGT dropped the unknown name rather than
  coercing it to a neighbouring id (P4), and the hard block broke the loop
  deterministically instead of asking the model again. **Not a game defect**, but
  it is a natural thing for a player to try, and it is the one place in the
  chain where the fiction has no verb for what the player is imagining.
- **The 3 auto-flags are benign, checked one by one** rather than waved off.
  Step 13 `go_north` and step 77 `go_north` are both in R04, whose only exit is
  east; step 76 `go_south` is in R01, whose only exit is north. All three are the
  pilot walking into a wall the `Exits:` line had already ruled out, and the game
  answers *"You can't go that way."* every time. No door refuses silently.

Also checked, because it was a risk this session created: `room_name` never
causes a spurious contradiction flag. Of 49 steps with unexpected deltas, 21
mention `room_name` and **0** are `room_name` alone — it always rides along with
a real change, so adding it did not make every successful move look surprising.

### Channel check: PASSED. Open items, none blocking

Stage 1's job is done — the pilot can see the game, act on it, and finish it.
What is still open is recorded here rather than left in a session:

| # | Item | Disposition |
|---|---|---|
| A | **No verb for pouring the oil.** The pilot asked for `use_flask_oil` seven times. Taking the flask sets `has_oil` and the *lantern's* `use` does the filling, so the flask is correctly not usable — but it is the most natural thing a player would try, and the one step in the chain with no verb for what the player is picturing | **Filed, not fixed.** A design call (an authored refusal on the flask would answer it), not a defect |
| B | **The action list leaks the object roster** (Finding 8). `use_key_skeleton` is visible from the opening cell; a human does not know a skeleton key exists until they find one | **Won't fix in this mode.** Structural to `action_id`: ids must be declared up front for a discrete space to exist. The honest fix is a text drive mode |
| C | **`key_iron` lost its authored refusal.** *"There is nothing here this key will bite on."* was written for a use that could not fail, and `use_requires_room` gave it a failure mode — but the wrong-place refusal is a generic engine line, so the authored one was dropped rather than reused | **Deliberate.** One authored string cannot serve both a place gate and a flag gate well (the cog's line is about the hour, not the room). Recorded so the deletion is a decision, not a loss |
| D | **Stage 2 (Haiku) not run** | By definition outside a channel check. P12: only stage 2 may produce a citable number, so the 30-vs-26 above stays unquotable |

## Notes on the feature map

`ugt verify` does not navigate to satisfy preconditions — it only steps
action 0 when nothing is eligible, and here action 0 is `go_north`, a real
move. The map is therefore written as one continuous playthrough split into six
assertions, relying on two runner behaviours documented in the file's header:
features run sorted by `(priority, definition order)` — so all six are
`critical` to preserve file order — and `MAX_TASKS_PER_TURN = 3`, so no feature
may depend on a precondition that only an earlier feature *in the same turn*
sets.
