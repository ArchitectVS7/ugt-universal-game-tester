# Tiny Escape Room — UGT integration

Drives `../game` (Node.js, JSON-lines over stdio) through UGT's built-in
**`simulation`** engine. No adapter code: `engine.type: simulation` +
`entry: ../game/src/bridge.js` is handled entirely by `SubprocessAdapter`,
which runs `.js` entries with `node`. This is the most CLI-native of the three
examples.

## Run it

```bash
# from the repo root
cd examples/escape-room/game && npm test && cd -      # game suite: 85/85

# the trial ladder — each rung is fail-closed, exit 0 only when every check passed
for s in spike_escape_room smoke_escape_room_adapter \
         verify_round1 verify_round2 verify_round3; do
  python3 examples/escape-room/integration/$s.py || break
done
```

Recorded results (2026-07-26, against the game at 85/85 green):

| Rung | Script | Result |
|---|---|---|
| 1 spike | `spike_escape_room.py` | **SPIKE MET — 27/27** |
| 2 smoke | `smoke_escape_room_adapter.py` | **SMOKE MET — 12/12** |
| 3 R1 playability | `verify_round1.py` | **ROUND 1 MET — 17/17** |
| 4 R2 full spine | `verify_round2.py` | **ROUND 2 MET — 47/47**, 552 commands |
| 5 R3 robustness | `verify_round3.py` | **ROUND 3 MET — 10/10**, 2 seeds × 160 steps |

The generic CLI tiers still work and are still worth running, but they are no
longer what the gate rests on — see Findings 1 and 2 for why:

```bash
cd examples/escape-room/integration
ugt smoke-test --config ugt.config.yaml                               # PASSED 5/5
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml    # 6/6, 0 FAILED
```

| Tier | Command | Result |
|---|---|---|
| 3 LLM | `ugt playtest` | guide written, **run not yet performed** — see below |

## Files

| File | Role |
|---|---|
| `ugt.config.yaml` | `engine.type: simulation`; 41 actions, **generated** from `node ../game/src/bridge.js --actions` so ids cannot drift from the CSVs (the spike asserts this) |
| `invariants.py` | 13 predicates as an `InvariantSuite` — written once, consumed by R1/R2 (per command) and R3 (wrapped for the fuzzer) |
| `spike_escape_room.py` | Rung 1 — raw JSON-lines over pipes, no adapter |
| `smoke_escape_room_adapter.py` | Rung 2 — the `SubprocessAdapter` contract |
| `verify_round1.py` | R1 — one full escape, invariants after every step |
| `verify_round2.py` | R2 — the whole content surface: all 41 actions, every object, every use-gate |
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
| P1 | Entities have identities, not handles | **PASS** — the prompt lists `take_lantern`, never `14` |
| P2 | Adapter passes through every PUBLIC field | **WAS BROKEN — FIXED.** See below |
| P3 | Truncation is silent starvation | **FIXED** — guide is 4,345 chars against a 2,000 default; budget set to 6,000 |
| P4 | Action channel sends what the LLM thinks | **PASS** — names map 1:1 to ids, asserted by the spike against the game's own table |
| P5 | Prompt must not leak what the real client hides | **OPEN — decision needed before the paid run.** See below |
| P6 | Guide teaches the RULES that create skill | **PASS** after rewrite — refusal-reading and the flag chain are now taught |
| P7 | Verify competence from reasoning text | pending the run |
| P8 | Never pool across an information fix | **boundary set here** — nothing before 2026-07-26 is poolable with anything after |
| P9/P13 | Episodes: samples or replays? | **declared `deterministic` and probed live** |
| P10 | Pilot needs memory, not just state | **configured** — `history_window: 12`, ledger keyed on `current_room`, narration recall on |
| P11 | Hard loop ceiling needs code | default threshold retained; repetition is not correct play here |
| P12 | Local model first | this audit is the local stage; `gemma4:26b` confirmed available |

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

**Left visible for the local channel check**, deliberately: that stage proves
plumbing and produces no quotable number, and running with flags visible tells us
whether the pilot even uses them. **It needs a decision before any paid run**,
because it changes what is being measured. The knob exists —
`playtest.redact_state_fields: ["flags"]` — and the guide would need its
"flags are your progress bar" section rewritten to match.

### Context budget

The rendered prompt is **7,237 chars (~1,800 tokens)**: objective, state, 12
recent actions with deltas, the narration tail, then the guide. Sized for this
game rather than copied — a comparable RPG integration runs ~20,000 chars because
it has an 8-mission story and a 35-verb surface; here that would be padding, and
padding costs local-model latency without adding knowledge.

## Tier 3 is written but not run

`ugt playtest` bills a real Anthropic API call per action. The guide is
committed and the wiring is ready, but the run itself was deliberately left for
a human to trigger:

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
repo re-run to check nothing had been silently red: `dice` 4/4, `escape-room`
6/6, `spacerquest` 9/9, all still exit 0. Blast radius was zero.

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

## Notes on the feature map

`ugt verify` does not navigate to satisfy preconditions — it only steps
action 0 when nothing is eligible, and here action 0 is `go_north`, a real
move. The map is therefore written as one continuous playthrough split into six
assertions, relying on two runner behaviours documented in the file's header:
features run sorted by `(priority, definition order)` — so all six are
`critical` to preserve file order — and `MAX_TASKS_PER_TURN = 3`, so no feature
may depend on a precondition that only an earlier feature *in the same turn*
sets.
