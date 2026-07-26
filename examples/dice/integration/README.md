# Dice Duel — UGT integration

Drives `../game` (React + Vite) through UGT's built-in **`browser`** engine:
headless Chromium via Playwright, calling the `window.__GET_STATE__` /
`__SEND_ACTION__` / `__RESET__` hooks the game exposes. No adapter code and no
game logic on this side.

## Run it

```bash
# one-time
pip install -e ".[browser]" && playwright install chromium
cd examples/dice/game && npm install && npm run build   # dist/ is gitignored
```

Every rung spawns and reaps its own server on an **ephemeral** port, so nothing
needs starting first and a stale server on :8080 can never be mistaken for the
bundle under test:

```bash
for s in spike_dice smoke_dice_adapter verify_round1 verify_round2 verify_round3; do
  python3 examples/dice/integration/$s.py || break
done
```

`ugt verify` still works too, and still needs a server:

```bash
cd examples/dice/integration && python3 serve.py &
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml
```

Recorded results — **whole ladder re-run 2026-07-26 (late)**, after D19, against
the game at 162/162 tests green. Every number below came from that pass:

| Rung | Script | Result |
|---|---|---|
| 1 | `spike_dice.py` | **SPIKE MET — 19/19** (+1 finding) |
| 2 | `smoke_dice_adapter.py` | **SMOKE MET — 9/9** |
| 3 | `verify_round1.py` | **ROUND 1 MET — 12/12** |
| 4 | `verify_round2.py` | **ROUND 2 MET — 14/14** |
| 5 | `verify_round3.py` | **ROUND 3 MET — 13/13** |
| — | `ugt verify` (Tier 1, CLI) | 4/4 PASSED, 0 FAILED (was 5/5 — the `concluded_battle_is_inert` entry was deleted when the D14 termination fix made it pass for the wrong reason; the property is still covered by R1, R2 and the invariant suite) |
| — | `playtest_dice.py --provider ollama --seeds 1` (stage 1a) | **channel proven** — 1 battle, 0 violations |
| — | `playtest_dice.py --provider ollama` (stage 1b) | **rotation proven** — 8/8 distinct seeds, 9 battles, 96 actions, 0 violations |
| — | `playtest_dice.py --provider anthropic` (stage 2a/2b) | **not run** (bills API credits) |

`exploit_hunt.py` is gone: R3 absorbed its random walks and determinism check,
and R2 took its defense-vs-attack A/B and its knockout drive, which are
content-spine claims and belong there. Invariants now live once in
`invariants.py` (`InvariantSuite`), shared by R1/R2 (`check_command`) and R3
(`to_hunter_invariants`), so the scripted and random tiers cannot drift.

## Where the PRD's six features live

All six are covered. Four are in `feature-map.yaml`; two are not expressible in
that model and live in **R2** (`verify_round2.py`), which is also where the two
that `exploit_hunt.py` used to own went when it was absorbed.

| PRD | Rule | Where | Why |
|---|---|---|---|
| F1 | Attack reduces enemy force | feature map | `combat.attack_reduces_enemy_force` |
| F2 | All-defense takes less damage than all-attack | **R2** | comparison **between two rounds**; a feature only sees before/after of its own action list |
| F3 | Morale surge (+1 when ahead) | feature map | `bonus.morale_surge_when_ahead`, isolated at round 4 |
| F4 | Reinforcements (+2 at round 3) | feature map | `bonus.reinforcements_fire_once_at_round_three`, isolated via the enemy, which has no other bonus that round |
| F5 | Reaching 0 force sets a decisive winner | feature map **+ R2** | `battle.knockout_sets_decisive_winner`. It was unreachable on the default seed for two retunes running and had to live in R2 on a hand-picked seed; post-D18 six `a5_d1` rounds finish it on round 10, so the map can assert it directly. R2 still drives the arm too |
| F6 | The round-12 cap | **R2** | **The rule itself changed.** D18 made the cap DECIDE on force strength; a draw now happens only on an exact tie. R2 drives all three terminal arms — knockout, points decision at the cap, exact-tie draw — which is a claim about the whole content spine, not a single delta |

⚠️ Earlier versions of this table sent readers to **`exploit_hunt.py`** for F2 and
F5, and described F6 as "the cap forces a draw" in the feature map. The file was
deleted, the rule was rebalanced, and the map has four entries, not six. It is
recorded rather than silently fixed because it is the documentation half of the
same failure the ladder keeps catching in code: **a table does not fail when it
goes stale.**

The map used to add a fifth of its own — `battle.concluded_battle_is_inert` —
which is **removed** as of 2026-07-26 and worth reading about in
`feature-map.yaml:124`: it only ever passed *because of* the termination bug
(Finding 2). With that fixed, the verifier resets after a terminal feature, so a
feature map structurally cannot look at post-battle state any more. The property
moved somewhere strictly better — R1 asserts it, R2 asserts it for all seven
allocations, and `invariants.py::concluded_battle_is_inert` checks it after every
command in every rung.

## Tier 3 pre-flight — the `LESSONS.md` §B audit (T-008, 2026-07-26)

Run with `playtest_dice.py`, which owns the server lifecycle and the bundle
freshness check the way every other rung does, and passes the shared invariant
suite into the LLM loop so a defect the pilot does not notice is still caught.

**Stage 1 (local, free) result:** `gemma4:26b`, 30 actions, two runs (225s and
213s). Each played two complete battles to a real `winner: "player"` with a
third in progress at the budget; **0 invariant violations across all 60 actions**
in both, 0 forced repeat-blocks, `ended_early: null`. The channel works.

Run 2 is the same harness after the finding-8 fix, and the fix is visible in the
play: false-prohibition beliefs in the pilot's own reasoning went **2 → 0**, and
its longest run of one allocation went **3 → 7** — it stopped switching away
from the allocation the guide calls correct because the prompt had told it it
must.

Run 2 also flagged 2 potential bugs, both from the contradiction detector, and
**both are correct readings rather than defects**: `a3_d3` three rounds running
with nothing moving but the clock. That is the game's real mid-battle stall — a
balanced player against a wounded, turtling AI trades zero damage for a few
rounds — and it is visible only because this integration puts `round_number` in
`ignore_delta_fields`. Without that the detector could never fire for this game
at all, since the round counter ticks on every resolved round. Whether those
stalls are good pacing is a stage-2 question.

**Stage 1b — the seeded rotation (96 actions, 710s).** After finding 7 was fixed:
`distinct_episode_seeds: 8` of 8, **9 completed battles**, 10 episodes recorded,
0 invariant violations, 0 forced repeat-blocks. The rotation wrapped back to
`dice-s01` for the ninth battle and reproduced its first battle's result exactly
(margin −3, paired −0.714), which is the determinism contract holding across the
whole loop rather than only in R3.

Its paired score was **+1.65, 95% CI ±1.91 (n=9)** — reported as *not
distinguishable from the average reference policy*. That is the correct reading
at n=9 on a local model, and per §B P12 it is a channel check, **not** a result:
no stage-1 number may be quoted. Stage 2 (Haiku) is T-006 and remains
credit-gated.

### Disposition per check

| # | Check | Disposition |
|---|---|---|
| P1 | LLM sees identities, not handles | **PASS, no change.** The 7 actions are named `a6_d0`…`a0_d6` — the allocation *is* the name. A sample prompt was dumped and read end to end (`_build_prompt` with real engine state); a human could play from it. |
| P2 | Adapter passes through every PUBLIC field | **FAILED → FIXED (D19).** See finding 6. |
| P3 | Truncation is silent starvation | **FAILED → FIXED.** Guide is 5,649 chars; the default `guide_char_budget` is 2,000, which would have cut everything from "What you can see" on — i.e. the entire skill half. Budget set to 8,000 and `playtest_dice.py::assert_guide_fits` now fails the run before contacting any model. Terminal budget sized from measurement too: a full 12-round dispatch log is ~3,900 chars (~323/round), the default 400 would show ~one round; set to 4,400. |
| P4 | The action channel sends what the LLM thinks | **PASS.** `action_id` mode maps `value` through `name_to_id` — one name, one id, no arguments to fill. An unknown name is skipped with a printed message, never coerced into a neighbouring id. |
| P5 | Prompt must not leak what the client hides | **PASS, verified field by field.** All 7 projected fields are on screen for a human (`App.jsx:36-49` both ForceBars, `:123` the round track, `:127-131` the outcome banner), so `redact_state_fields` is deliberately empty. D19's text hook was written to the same bound and a test pins it: no preset indices, no raw die faces, no seed, no `roll_counter`. |
| P6 | The guide teaches the RULES that create the skill | **PASS after two fixes.** The two-for-one block, the points decision and "all-out attack loses" were already there (rewritten for D18). Two defects found and fixed here: (a) the guide described `bonus_dice` as "granted this round" when it reports the round that just **resolved** (`engine.js:362` writes it from that round's `bonuses`; the UI labels it "last round" at `App.jsx:49`) — a pilot planning off it would be a round out; (b) the guide said nothing at all about the opponent, so the newly-visible dispatch log had no rule to attach to. Added: the enemy is deterministic and reacts to *its own* strength only (`engine.js::chooseEnemyPreset` D13). The closed-form is deliberately withheld — teaching the formula would measure exploitation of a leaked policy rather than the game. |
| P7 | Competence from the reasoning, not the exit code | **PASS (positive signal).** Grep over all 30 reasonings: `defense` 23, `lead` 23, `attack` 25, `round 12` 8, `bonus` 8, `morale` 7, `points` 6, `margin` 5, `cap` 4, `round 3`/`reinforce` 3, `half strength` 3. Step 26 inferred the opponent unprompted — *"the enemy's behavior is deterministic and they attack aggressively when at full strength"* — and step 15 quoted the guide's own 58% figure back. `two-for-one` scored 0/30, but `block` 9/30; per P12 local silence is **ambiguous**, so that one re-checks on Haiku rather than closing here. |
| P8 | Never pool across an information fix | **Boundary declared.** Everything before D19 + the P3 budget fix measured a pilot that could not see the dispatch log. Nothing from before 2026-07-26 is poolable with anything after, and no pre-stage-2 run is poolable with anything at all. |
| P9 | One clean run proves the channel, not the balance | **FAILED → FIXED (finding 7), and the metric changed with it — see "Sampling design" below.** Every episode used to replay one seed. Now `playtest.episode_seeds` rotates 8 declared seeds per episode via `BaseAdapter.reset_seeded`, and `assert_seed_rotation_works` proves the rotation is real before every run. |
| P10 | The pilot needs memory | **PASS by configuration.** `history_window` raised 5 → 12 so the whole battle's decisions stay in view; a 5-step window hides the first half of every match including the round-3 swing. `action_context_path` is unset on purpose: there is no "where you are" in this game, so plain per-action keying is correct. |
| P11 | A prompt warning is advice, not a guarantee | **FAILED → FIXED in UGT core.** See finding 8. Separately: the spike's `RangeError` divergence (finding 1) is unreachable from this tier — a hallucinated action name never reaches the adapter, it is dropped by `name_to_id.get(value) is None`. |
| P12 | Validate on a LOCAL model first | **DONE — that is this whole section.** Two 30-action `gemma4:26b` runs, zero API calls spent. `playtest_dice.py` refuses `--max-actions > 100` on `--provider ollama` rather than leaving the ceiling to discipline. Ollama 0.32.3 serves `gemma4:26b` at a runtime `context_length` of 32,768 against a ~2,980-token prompt (`/api/ps`), so there is no second, quieter truncation underneath P3. |

### Sampling design — 8 seeds, scored paired

Once seeding worked, the question became how many seeds and scored how. Both were
settled off the engine before any paid call, because a deterministic engine plays
every reference policy on any seed in milliseconds (`game/tools/paired_baseline.mjs`,
§D3 applied to a measurement instrument rather than a design change).

**Characterisation over 200 seeds, 7 reference policies:**

| | |
|---|---|
| mean best-vs-worst policy spread within one seed | **7.6** force-strength points |
| sd of a fixed policy's raw final margin | **3.53** |
| sd of the same margin **minus that seed's own mean** | **2.16** |
| seeds no policy can win | **31 / 200 (15.5%)** |
| seeds that fail to discriminate between policies | 17 / 200 |

**So the win rate is not the headline, at any budget we would spend.** Its 95% CI
is ±34 points at 8 battles and ±30 at 10; reaching ±12 needs ~60 battles. It is
also largely reporting which seeds were drawn — with 8 seeds you expect ~1.2 of
them to be unwinnable no matter how well the pilot plays.

**The headline is the paired margin:** the pilot's final force-strength margin
minus that seed's mean margin across the reference policies. Removing seed
difficulty is worth **2.7×** the battles ((3.53/2.16)²), giving ±1.49 at n=8
against a 7.6-point spread — enough to answer "does the pilot play at least as
well as the average sensible line", which is the question the tier is for. The
win rate is still printed, with a **Wilson** interval so it can express doubt at
0/N and N/N where the normal approximation collapses to ±0.0.

**The seed set is 8, fixed by rule (`dice-s01…s08`), not screened on outcome.**
Screening would bias the set toward "the game is winnable"; the characterisation
says a rule-based set already discriminates. The chosen set comes out neutral —
mean baseline margin **+0.05**, mean spread **8.25**, exactly **1** unwinnable
seed (s08), matching the 15.5% base rate. Eight also fits ~90 actions, just under
§B P12's ~100-action local ceiling, so the whole rotation runs free in stage 1.
**Changing the list re-baselines the tier (P8) — extend the tail, never renumber.**

The staging is therefore four steps, not two:

| Stage | Provider | Shape | Question |
|---|---|---|---|
| 1a | ollama | 1 seed, ~14 actions | does the loop work on one battle? |
| 1b | ollama | 8 seeds, ~96 actions | does the rotation actually rotate? |
| 2a | anthropic | 1 seed, ~14 actions | is the data good before committing spend? |
| 2b | anthropic | 8 seeds × 2 runs = 16 battles | the measurement (paired CI ±1.06) |

## Findings

**1. The spike found something four tiers of CLI testing never touched.**
`__SEND_ACTION__` **throws** a `RangeError` on an out-of-range or ill-typed
action id, where `escape-room` and `sokoban` both return current state
unchanged. `engine.js` does this deliberately — "validate, throwing rather than
coercing" — and state is *not* corrupted (verified across `-1, 7, 999, null,
'x', 1.5, undefined`: all rejected, all left the battle byte-identical, game
still usable afterwards). So it is a contract divergence, not a bug. But dice's
PRD never specifies hook-level behaviour, and a black-box client has to wrap
calls in `try/except` for this game and not the other two. Worth settling one
way across all three. Neither `ugt smoke-test` nor the feature map could ever
have found this: both only ever send ids drawn from the declared action space.

**2. The termination gap — quantified, then FIXED (D14).** `PlaywrightAdapter`
reads `state.pop("terminated")`; the hooks exposed `battle_over` and nothing else,
so UGT never saw a match end and never reset the episode. R3 put the cost in
numbers: in a 120-step random episode **only ~11 steps (9%) landed on a live
battle** — the rest hammered a concluded one. The invariants did still cover those
steps (a concluded battle staying inert is a real property), but nine tenths of
the nominal exploration budget was spent proving one thing.

`ugtHooks.js:173` now returns the structured envelope
(`{state, terminated: state.battle_over, truncated, info}`), which is deliberately
**not** the same as adding `terminated` to the state projection — the projection
is what a human can see on screen, and `terminated` is a transport concern. Today's
R3 reports **110 live steps across 10 completed battles, 55% of a 200-step budget**,
against ~9% before.

The fix had a second effect worth knowing, because it looks like a regression: it
made a feature-map entry start failing, correctly. See the `concluded_battle_is_inert`
note above — that entry had only ever passed because of this bug.

Still generalises: ANY browser game whose terminal flag is not literally named
`terminated` has this blind spot, and it presents as a green run with a tenth of
the coverage it claims.

**3. Draws dominated, then depth did — BOTH CLOSED 2026-07-26, in two retunes.**
This entry is kept in two halves on purpose: the first retune fixed the symptom
and left the real defect standing, which is the interesting part.

The original finding: 205 sequences on the shipped seed never got the enemy below
1 force strength inside the 12-round cap, and only 2 of 12 seeds produced a
knockout under pure all-attack. `game/tools/balance_sweep.mjs` put a number on
it — **13% decisive, 87% draws** across four player strategies x 40 seeds.

Fixed by holding `MAX_ROUNDS` at 12 (a deliberate design call — the short fixed
match is the intent) and moving `STARTING_FS` 20 -> 12 with `DUG_IN_THRESHOLD`
10 -> 6. `HIT_THRESHOLD` was left alone on purpose: "a die showing 5 or 6 is a
hit" is a rule players read in the PRD, where starting strength is just a
number. Sweep after: **50% decisive**, and an aggressive line converts ~90%.
(D18 later took it to **91% decisive** on the shipped engine, with `STARTING_FS`
12 → 8; the cap now decides rather than draws, so a draw needs an exact tie.)

**What that retune did NOT fix — and it was the bigger problem. Now CLOSED by
D18.** Allocation barely mattered: in the same sweep all-attack won 35 of 60 while
a balanced allocation won **1 of 60**, so the round-by-round choice was not a
trade-off but a question with one right answer. It followed from the damage model
(`damage = max(0, attack hits − defense hits)`, so two cautious sides converge on
zero damage while the AI turtles harder as it drops), which is why it was filed as
a **design** question rather than a constant to tune.

Two independent reviews then showed it was structural — the marginal gap between
an attack die and a defense die is `p(1−p)·P(tie) > 0`, an expression containing no
balance constant, so no retune could ever have fixed it. Resolved by
`DEFENSE_BLOCK = 2` plus a cap that decides on force strength, chosen by
simulating six rule variants over **3.15M battles before any code was written**
(`LESSONS.md` §D). Best response is now `[3,3,3,3,3,2,0]` rather than all-zeros,
the regret of all-attack went **0.000 → 0.131**, and optimal play picks a genuine
mix **61%** of the time against 7% before.

R2 still prints it every run — as a **CLOSED** record with those numbers, not as an
open item — and `game/tools/balance_sweep.mjs` now warns if regret ever falls back
under 0.02, so the finding has a regression guard rather than a memory.

**This is the finding that justified the whole robustness-tier rename.** R3 held
this game green at 11/11 for weeks while one allocation strictly dominated every
other. Random input against an oracle cannot find "the game's only decision is
meaningless", because it has no notion of reward to notice it with — see
`PLAN-FORWARD.md` on the exploit-hunting tier that still does not exist.

**4. `engine.reset_command` is silently ignored whenever `__RESET_GAME__`
exists.** In `PlaywrightAdapter.reset()`, the soft-reset branch runs first and
`reset_command` is only consulted in the `else`. Since the documented hook
contract tells games to expose `__RESET_GAME__`, any game that follows the
contract can never use `reset_command` — which is exactly what would have let
this integration pick a seed and test F5 through `ugt verify`. Configuring it
produces no error and no effect.

**5. `ugt verify` exits 0 even when features FAIL.** Same as recorded in
`examples/escape-room/integration/README.md` — `handle_verify` only exits
non-zero on an exception. Gate on the `failed` count in
`results/coverage-report.json`, not on `$?`.

**6. The pilot was reading strictly less than a human — the whole battle log was
on the floor.** Found by the §B P2 pre-flight, before any model was contacted.
`App.jsx:151` renders `state.log` through `flavorLines()` into the "Field
dispatches" panel, so a human reads every round how many attack hits each side
landed, how many were blocked, which bonus dice fired and what posture the enemy
took. D15's seven-field projection drops `log` and `last_round`, and
`PlaywrightAdapter.get_terminal_text` (playwright.py:160-167) found neither a
`__GET_TERMINAL_TEXT__` hook nor a `.xterm-rows`/`#terminal` element, so it
returned `""`. The pilot could watch force strength move and never learn *why* —
and the exchange line is the only place the game says how the last allocation
actually performed.

Fixed game-side as **D19**: `__GET_TERMINAL_TEXT__` serializes the same
`flavorLines()` output on the same `state.log`, read through the same seam as
`__GET_STATE__`, emitting nothing the panel withholds (a test pins the absence
of preset indices, raw rolls and the seed — §B P5). Order is oldest-round-first,
opposite the UI's scroll, because the consumer keeps `text[-chars:]` and
newest-first would truncate away exactly the recent rounds. Contract hooks
untouched; game suite 157 → 162.

Non-vacuity, proven rather than assumed (O2): deleting the hook from a live page
mid-session drops the channel straight back to `''`. `playtest_dice.py::
assert_terminal_channel_is_live` now asserts two resolved rounds and an exchange
line are both in view before any run starts.

*Generalises:* a browser game's richest player-facing information is often in
rendered prose that no state projection carries. The `__GET_TERMINAL_TEXT__`
hook is the intended channel for it and is trivially easy to simply never
implement — at which point the tier reports `PLAYTEST MET` on a starved pilot.

**7. EVERY EPISODE REPLAYED THE SAME SEED — found 2026-07-26, FIXED the same
day.** `PlaywrightAdapter.reset()` calls `window.__RESET_GAME__()`
with **no arguments** (playwright.py:50); `__RESET_GAME__` aliases `__RESET__`
(D18); `useBattle.js:73` is `reset = (seed = stateRef.current.seed)` — i.e. the
default replays the current seed. Measured, not inferred: in the 30-action run,
**10 of the first 12 (action, state-delta) pairs of battle 2 are identical to
battle 1's**.

So a playtest "batch" of N episodes is one battle sampled N times. A balance
figure computed over it would carry an N-sized denominator and a 1-sized
sample — the §B P9 / O8 failure shape, and invisible in the output. This is
**not dice-specific**: any game following the documented soft-reset contract
gets a parameterless reset, so the playtest tier has no seed variety anywhere.

**Fixed in UGT core, because the blind spot is generic.** `playtest.episode_seeds`
rotates a declared seed list one seed per *episode*; `BaseAdapter.reset_seeded()`
is the new optional capability, and it **raises** for adapters that cannot seed
rather than ignoring the argument. `PlaywrightAdapter.reset_seeded()` forwards to
`window.__RESET_GAME__(seed)` — which dice already honoured, so the game needed
**zero changes**; the adapter had simply never passed an argument. The report now
carries a per-episode record (`{seed, first_step, last_step, actions, end_reason,
outcome, final_state}`) plus `distinct_episode_seeds` in the summary, so "N
episodes, 1 seed" is visible in the output instead of having to be discovered.

**The raise is necessary and not sufficient, which is the part worth carrying to
other games.** JavaScript discards extra arguments in silence, so forwarding a
seed to a game that never implemented seeding returns a normal state and throws
nothing anywhere — the original bug would have survived the fix while showing a
green light. So `assert_seed_rotation_works` runs before every playtest: two
seeds must produce different battles AND one seed must reproduce itself exactly
(a hook returning random state would pass the first test and be equally broken).
That probe was itself proven able to fail (O2) by patching a live page so
`__RESET_GAME__` drops its argument — it catches it, naming both seeds.

**8. UGT core told the pilot a rule that was not true, and the pilot obeyed it.**
`_noop_warning_block` printed *"Picking it again will be REJECTED and forced to
'wait' instead — this is a hard rule, not a suggestion"* whenever an action
repeated twice back-to-back. That text was written when the hard ceiling was
always its default of 3. This integration sets `repeat_block_threshold: 13`,
because repeating an allocation is legitimate — often correct — play here, and
`wait` does not resolve a round, so an override would burn budget *and* corrupt
the measurement.

The result: at step 15 of 30 the pilot wrote *"I cannot use a3_d3 because I have
used it 3 times in a row, which would be rejected"* and switched away from the
allocation its own strategy guide calls correct. `forced_repeat_blocks` for that
run was **0** — nothing was ever blocked. The prompt was not reporting a
constraint, it was inventing one, and it steered the exact behaviour under test.

Fixed in `ugt/core/playtester.py`: the threshold is threaded into the warning
from `playtest.repeat_block_threshold`, and the hard-rule sentence is emitted
only when the next repeat would genuinely be rejected. Otherwise the warning
reports the streak and says the repeat is allowed. Games on the default
threshold are unaffected (verified: dice is the only config in the repo that
sets the knob, and at the default the same branch still fires).

This is `LESSONS.md` P10's own correction resurfacing in a second code path —
"the ledger was written to nudge the agent away from repeating itself; that is
actively harmful" — this time in the warning block rather than the ledger.
**Report; do not instruct.**

**9. This script's own documented stage-1a command had stopped working. FIXED
2026-07-26.** `playtest_dice.py --seeds 1` narrowed `playtest.episode_seeds` to a
single entry, and `seeding.resolve` refuses `per_episode` with one seed — correctly,
because a one-entry rotation replays one match while the declaration claims variety.
So the command in this file's own docstring exited 1 before contacting a model.

The recorded 1a result predates the seeding declaration landing (`694eb9d`), and
nobody re-ran the command afterwards — **a documented command is a claim, and it
goes stale exactly like a results table.** Found by re-running it as a regression
check after an unrelated `ugt/core/playtester.py` change, which is the only reason
it surfaced at all.

No config surgery was needed in the end: the rotation starts at `seeds[0]`, so a
budget that only affords one episode already plays exactly `dice-s01` with all
eight seeds declared and honest. The script now says that in its output instead of
rewriting the declaration underneath itself.

## Notes

`feature-map.yaml` is one continuous battle split into five assertions, because
`ugt verify` resets once and never again. It relies on features running sorted
by `(priority, definition order)` — hence all `critical` — and on
`MAX_TASKS_PER_TURN = 3`. The file header documents both.

Every rung spawns `serve.py` through `serve_process.py` on an **ephemeral** port
rather than 8080, so a stale server left on 8080 cannot silently substitute its
own bundle for the one under test — and `served_bundle()` additionally refuses to
serve a `dist/` older than `src/`, because the first ladder run after the D18
rebalance came back green against a stale build.
