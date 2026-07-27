# UGT — Lessons Registry

> **This is the canonical, cross-game lessons file. Read it before onboarding a new game, before advancing
> any ladder rung, and — section B especially — before any LLM playtest run.**
>
> Everything here was paid for by a real run that went wrong. Each lesson carries an ID, a one-line rule, and
> the evidence that produced it. Per-game findings stay in each integration's own findings log; a finding is
> promoted here **only when it generalizes to games it was not found in**. To keep the lessons portable, games
> are named by genre and tech stack (e.g. "a TypeScript deck-building card game", "a Godot bullet-hell
> roguelike") rather than by project name.

Referenced from: `README.md` (Start here), `UGT-USER-MANUAL.md` (methodology), `PLAYTEST-DESIGN.md`
(tier-3 spec).

---

## A. Core methodology — applies to every game, every tier

**M1 · Drive the REAL game, never a re-implementation.** The single biggest failure mode: an adapter/bridge
that reimplements game logic (travel, combat, economy) instead of calling the running game. Whatever the
bridge forgets silently does not exist for the agent — an early TypeScript bridge for a space-trading sim
shipped with **no combat**, and every trained agent learned a game that could not fight. If your adapter
contains game *rules*, you are testing the adapter. Prefer, in order: (a) drive the game's real server/UI as a
client; (b) call the game's own functions; never (c) a parallel copy. An unmapped action must raise
`NotImplementedError`, never fabricate behavior.

**M2 · Dual validation — expect to find game bugs and pause.** UGT validates two things at once: that it can
test the game, and the game itself. Finding a real game bug and pausing to fix it upstream is a successful
outcome, not a distraction. Budget for test↔fix round-trips.

**M3 · Failed checks are data — record them.** Negative results (an agent that collapses, an unreachable
mechanic, a reward that rewards the wrong thing) are often the most valuable findings. Write them into the
integration's findings log so the next session does not re-learn them.

**M4 · Prove learnability cheaply before scaling.** Before spending compute, prove an agent beats a random
baseline on the simplest reachable objective. If it cannot clear that bar cheaply, more compute will not save
it — change the approach.

**M5 · Verify ≠ Train ≠ Play.** A feature passing a *verifier* (often with crutches — extra credits, perfect
nav) does not mean an agent can reach it under real play. The environment an agent plays in must be the same
MDP you certified.

**M6 · Reward realized outcomes, not activity.** Reward profit/wins/progress, not proxies for effort (trips
taken, actions issued) — proxies get gamed. Express agent personalities as reward *weights* over a shared
action set, never by hiding actions from the agent.

**M7 · Right tool per question.** Correctness → `ugt verify`. Robustness / does-it-break → the
invariant-fuzzer (no reward engineering needed). Balance / is-it-good → the LLM playtester (competent play
beats volume). Do not force one agent to answer all three.

**M8 · Test over the wire — a green in-process suite cannot see serialization-boundary bugs.** The game's own
client and tests route around the wire, so defects *on* it are invisible to them. A TypeScript deck-building
card game had 1,251 in-process tests green while 7 of 40 cards played blank for every wire client (a field
never exposed over the wire) and `create` accepted a config that `replay` would refuse (a missing key silently
played a *different game*). Demand exact-config-key sets; treat a refusal as different from silent inertness;
kill vacuous greens; and when an invariant never fires, suspect your own invariant first.

**M9 · Audit your own findings before citing them.** UGT has over-claimed from small samples and misread
cumulative counters. Investigate before *confirming*, not only before dismissing. Record corrections in the
integration's findings log rather than deleting the mistake.
*(Two of the card game's own findings were later partly refuted; one Godot-game finding was fully self-refuted.)*

**M10 · Know what a green tier PROVES, and name the tool accordingly.** A tier's name becomes what people
believe it did. The robustness tier was called `ExploitHunter` for its whole life while containing exactly two
detectors: crashes, and invariants a human had written for that game. It never searched for anything — the
policy is random by default, with no notion of reward, score or progress, so it cannot go *looking* for a
profitable loop. "Exploit hunter is green" was read as "nobody can game this"; it meant "no crash, and none of
the properties we listed were violated". The worked example is in this repo: a browser dice game held that rung
green at 11/11 for weeks while one allocation strictly dominated every other and the game's only decision was
meaningless. Renamed to **invariant fuzzer** on 2026-07-26 (263 occurrences across 81 files — budget for the
sweep). Two durable rules:
- **State the negative in the tier's own docstring.** What it does *not* prove is more load-bearing than what
  it does, because the name will keep over-promising after you stop reading.
- **Give every game a framework-owned floor**, so the oracle is not 100% author-supplied
  (`ugt/core/generic_checks.py`): monotone-growth (fields that only ever rise = farmable resource), state
  cycles, dead actions, nondeterminism, state starvation. Zero configuration — they discover the fields from
  the observed states. Make them **observations, not failures**: several are inherently dispositional ("is this
  a counter or a resource?" is a question, not a verdict), and a channel that turns existing green ladders red
  for unreviewed reasons gets disabled instead of read.
*What is still MISSING, named so it is not mistaken for done:* detection is not search. A random policy can
only stumble into a degenerate line; nothing in UGT yet goes LOOKING for one. That tier — novelty-driven
search, profitable-cycle detection, replay minimization — is specced in `PLAN-FORWARD.md` under "TRUE exploit
hunting". It answers a fourth question (gameability), and must not be bolted onto the fuzzer.

*Corollary — measure at the right granularity or the check is silently vacuous.* The first monotone-growth
implementation looked run-wide, so every episode reset registered as a fall and **nothing could ever flag**. It
passed its own gate by being useless. Farming happens within one life; per-episode is the window. It was caught
only because the rung asserted the channel could still SPEAK with the allowlist removed (O2 applied to a
whole channel, not one assertion).

**M11 · Red parts — a known-bad fixture must fail EXACTLY the check that owns its defect, and pass
everything else.** Borrowed from controls engineering, where a nightly test run includes deliberately
defective *red parts* alongside a known-good one. Each red part carries exactly **one** known defect — a
radiator with a bad inlet port is red part #1, a bad outlet port is red part #2 — and the acceptance
criterion has two halves:

1. the good part passes **100%**; and
2. **each red part passes everything except the one check that owns its known defect.**

Half 2 is the half that is usually missed, and it is the more valuable one. Asserting only that a broken
input goes red proves the suite noticed *something*. Asserting that everything else stays green proves the
checks are **independent** — because a defect that trips five checks at once means those five are entangled,
and their individual verdicts mean far less than they appear to. A suite of entangled checks reports five
findings for one bug and tells you almost nothing about where it is.

In software this is fault injection / mutation testing, and the "red part" is a **known-bad fixture**. The
analogy transfers further than it first looks: physical red parts also validate the *measurement system*
(gauge repeatability), and the software equivalent — testing the harness rather than the code — is exactly
what a conformance fixture is for (`CONFORMANCE-FIXTURE.md`).

This sharpens the older rule that a check must be shown able to fail (§C). *A test that cannot go red is
decoration; a suite whose checks all go red together is a smoke alarm, not a diagnosis.* And the practical
consequence for a reader of results: **an all-green suite that has never demonstrated it can go red is not
evidence.** A vacuous green is worse than a red, because it actively conceals.

**M12 · The point of all of this is that human UAT stops being wasted.** The tiers exist to catch what
would otherwise be discovered by a person sitting down to play. Sitting down to a build with *all tests
green* and finding the UI broken, or turn progression plainly not working, is the failure this whole
methodology is aimed at — and it costs twice, because it also destroys trust in the suite that passed
(reasonably: the tests may well have been vacuous — see M11).

Three consequences that should shape how a tier is built:
- **Optimize for cycle time, not report quality.** The value is in *playtest → fix → playtest* running in
  quick succession. A slow batch producing a document someone reads next week is a worse instrument than a
  rough loop that closes in minutes, because defects are fixed while the context is still loaded.
- **Human attention is the scarcest resource in the loop.** Spend machine time freely to protect it. Any
  defect a machine could plausibly have caught, and didn't, is a gap in the tiers — not bad luck.
- **Engine-level tiers cannot see the frontend, by construction.** Every tier in this framework drives the
  game's engine or its text channel. "The button does nothing" and "the turn never advances visibly" are
  invisible to all of them. That gap is real, is not closed by more of the same, and is tracked as its own
  piece of work rather than assumed away.

*For strategy games specifically — board games, 4X, anything where the interesting question is the quality
of a decision — the goal is a pilot that decides* well*, not one that acts often.* Note the tension this
creates with §B: an extensive strategy guide plus live state plus a recent-command window all compete for
the same finite context. Better decisions usually come from better **selection** of what the pilot is told,
not from telling it more.

---

## B. LLM playtest pre-flight — the information-integrity audit

**Run every check below and write a cited disposition for each BEFORE any balance batch.** Skipping this cost
two multi-hour balance batches on a card game that measured the wrong thing (one reported 92.6% from a *blind*
pilot; a later one 89.8% from a *rules-blind* pilot). Both numbers are permanently unpoolable with anything
measured after the fix.

The unifying failure mode has a name: **information starvation** — the game exposes what a competent player
needs, and the harness or the guide drops it on the floor. It is invisible in the run output: the loop reports
`PLAYTEST MET`, zero invariant violations, zero bugs, and a confident-sounding win rate.

> **Start with P12.** It is last by number and first in practice: run the whole audit against a LOCAL model
> (`--provider ollama`) before spending a single API call. P1–P8 are all findable for free, because they are
> defects in what the pilot can SEE rather than in how well it thinks.

### P1 · The LLM must see entity **identities**, not opaque handles
Counts and integer ids are not a choice. A card game's playtester picked among `instanceId` ints for 800
actions and said so mid-run: *"the current state shows no specific cards in hand are visible to me via the
JSON."* **Check:** read one real prompt and ask "could a human play well from only this?" **Fix pattern:**
annotate the legal-action list with display-only keys (`_card`, `_hand` — underscore prefix = stripped before
the wire), never by widening the wire payload.

**The STATE is a channel too, and auditing only the action names passes a game that is still starving.** A
text adventure's P1 was dispositioned PASS because the prompt listed `take_lantern` and never `14` — a correct
finding about the *action* channel, and the audit stopped there. Its state said `current_room: "R04"`, an
internal id no player is ever shown; a human sees `Storeroom`, printed on every entry. The pilot bound the
wrong name to the right id ("R04 (Guard Corridor)" — R04 was the Storeroom), then spent twelve of thirty moves
walking into a wall. **Check every field the prompt renders, not just the ones you had to build:** an id that
appears in the state because it is how the code indexes rooms is a handle, and it needs its display name
beside it. **Fix pattern:** carry the player-facing name in state next to the id, derived from the same source
the human front end prints, and add an invariant asserting the pair agrees on every transition — two fields
that can disagree will.

### P2 · The adapter must pass through every field the game marks PUBLIC
Normalizing state is where read layers die. A card game's `_seat()` normalizer discarded `echo`, `chain`,
`statuses` and `modifiers` — all four explicitly PUBLIC in the engine's own types and served to both seats by
its `playerView`. Echo is half the game's ratified core mechanic; **0 of 1,650 reasonings mentioned it.**
**Check:** diff the adapter's normalized state against the game's own player-view/serializer field list. Any
field you drop, justify in a comment.

**This is not a one-time check — re-run it every time the game's state surface changes.** A terminal-hacking
RPG passed P2 cleanly one day, and hours later a game-side feature added `toolTier` to its `player-state` route
while the HTTP adapter — which builds an explicit dict and silently discards anything unlisted — dropped it on
the floor. The pilot could have bought a toolkit and never seen that it owned one. An adapter that enumerates
fields explicitly is safer than one that passes everything through, but only if something re-checks it after
each schema change. Make it part of the definition of done for any game-side change.

**"Is there a channel" and "does the channel carry everything" are two different audits, and passing the first
feels exactly like passing both.** A text adventure's bridge was found dropping the engine's narration
entirely — room descriptions, examine text, authored refusals — so the pilot played a text adventure with no
text. Fixed, tested, dispositioned. The audit had asked whether narration crossed the wire, and it now did.
What it never asked was *on which responses*: `reset` still answered with state alone, so the pilot's **first**
decision was made with an empty text panel while a human's opening screen is the room they woke up in. Found
one run later, by a local model that could not say where it was. **Check the initial/reset response
explicitly** — it is the one response a client cannot recover by acting, because there is no earlier turn to
have learned it from, and it is systematically the one a step-shaped test never covers. Underneath it was a
framework bug with the same shape: `SubprocessAdapter.reset()` recorded no narration at all, starving the
first prompt of **every** simulation-engine game.

**Corollary — a partial list is a starvation defect the moment you treat it as authoritative.** In the same
round, a prompt knob was written to replace the action vocabulary with the game's own live `unlockedCommands`,
reasoning that the agent should never be offered a verb the game will refuse. That field turned out to be a
*hack-verb* list omitting a third of the game's commands, including two just added — so the replacement would
have hidden a brand-new subsystem from the pilot. Annotate with such lists; never let one subtract.

### P3 · Truncation is silent starvation
Budgets (`playtest.guide_char_budget`, `playtest.terminal_char_budget`) cut from a *tail*, and nothing warns
you. One game's guide budget went 2000 → 6000 → 11000 as the guide grew; each raise was in the same commit as
the content it had to fit. **Check:** assert `len(guide) <= guide_char_budget` and that the terminal budget
exceeds the game's longest single output (list/scan/inventory screens are the usual overflow).

### P4 · The action channel must send what the LLM thinks it is sending
A card game's `apply_legal` relayed legal actions verbatim with `targets: []`, so every targeted card played
blank — the exact wire defect already fixed upstream, replayed on the UGT side. The engine accepted it
silently, so zero invariants fired. **Check:** for one action of each shape, log the composed wire payload and
confirm it carries the arguments the LLM chose. **Fix pattern:** fill arguments at *enumeration* time so the
LLM chooses the action it will actually get.

### P5 · The prompt must not leak what the real client hides
The god-view state an invariant needs is not the view a player gets. A card game handed the always-second seat
the first mover's committed card-vs-pass bit — which the engine's redacted view deliberately withholds.
**Check:** name every field in the prompt that the game's own client cannot see. **Fix pattern:** the
game-agnostic `playtest.redact_state_fields` knob (dotted paths dropped from the *prompt only* — state JSON
and delta summaries; logs, invariants and reports keep the full state).
**Two knobs, and do not conflate them:** `redact_state_fields` is fog of war — the game hides it from the
player, so it leaves *every* channel the pilot reads, deltas included. `hide_from_state_block` is context
economy — the same information is rendered elsewhere in the prompt (usually the screen panel), so it leaves
the state JSON *only* and stays in the recent-action deltas. Putting an economy decision in the fog-of-war
list silently turns it into an information restriction on the pilot's **memory**: one game moved a whole-board
render to its screen panel that way, and because the board was then stripped from the deltas too — and a push
that crosses no target moves no visible scalar — a move that pushed a crate and a move that only walked
rendered *identically* in the pilot's own history. Ask of each hidden path: is it hidden from the player, or
merely printed somewhere better?
*(→ `ugt/core/playtester.py::_redaction_paths` / `_state_block_only_paths`.)*

### P6 · The strategy guide must teach the RULES that create the skill, not just the entities
A guide that lists commands/cards but not the mechanics that reward reading them produces a pilot that goes
through the motions. A card game's guide named `stance` but taught no type triangle, no stance transition/regen,
no echo, no chains: 745/1,650 reasonings mentioned stance, ~zero used its mechanics, and the +5 counter — the
game's core skill — was never once collected. The informed baselines (the game's own scripted AI tiers 2–3)
beat the LLM precisely because their evaluator priced those rules.
**Check:** list the game's scoring/skill mechanics from its rulebook; for each, grep the guide. Also cover
*known truncation/cap semantics* the player would otherwise mis-plan around.

**Verify every rule you write against the RUNNING game, not only against the code that appears to produce
it.** Two guide claims for a terminal-hacking RPG, written from source, were falsified by one live probe:
hardcore was stated as "~30% base odds" when the code applies a flat −10%, and a "+15% skill floor from level
1" was contradicted by a live breakdown reading `Exploit Skill Lv0` with no skill term at all — the cited
`floor(points/100)+1` was the *update* formula, not the starting value, and the real accessor returns `?? 0`.
A guide is prompt content: a wrong rule in it is not a harmless doc bug, it actively misinforms the pilot and
corrupts the batch, which is the same damage as omitting the rule (P6) with none of the visibility. Run one
action of each kind and read what the game actually prints.

### P7 · Verify competence from the reasoning text, not from the exit code
`PLAYTEST MET` only proves the channel works. The cheap, objective competence probe: after a short sanity run,
**grep the logged `reasoning` for the game's core mechanic terms and real entity names.** Zero mentions of a
central mechanic = starvation, no matter how clean the run. This is what turned both card-game batches around,
and it is the only check in section B that needs a live run.

**The AGILITY half of competence is now machine-measured — stop eyeballing it.** "Did the pilot follow the
quest lines and try the commands the game revealed mid-run?" had no metric until it became the
`playtest.revealed_content` config knob → `ugt/core/playtester.py::_RevealTracker`: a game declares which
state collections are progressively revealed, and the report separates REVEALED (an item newly appeared in
state) from ENGAGED (the pilot invoked/mentioned it, or the game reported progress on it, within N steps of
the reveal). Three rules keep it from going decorative, straight out of O2: items present at reset are the
STARTING KIT and are never scored; a reveal inside the last window is PENDING, not missed; and a run that
revealed nothing reports `no_reveals` with a **null** rate, never a perfect one. Optional content (side
quests) is reported but kept out of the denominator. One trap to carry to the next game: a field named
`unlockedCommands` may be an explicit-GRANT list rather than a report of what is currently unlocked (in the
terminal RPG, its only writer across 14 shipped missions is a single side quest), so a metric built on it is a
lower bound and must say so in its own output.
*(→ a content-engagement metric verifier, 27/27, mutation-tested.)*

### P8 · Never pool batches across an information fix
Any change to P1–P6 changes what was being measured. Mark the boundary explicitly in the integration's
findings log (e.g. "the 89.8% batch must not be pooled with any post-fix batch") and re-baseline.

### P9 · One clean run proves the channel, not the balance
A single sanity run establishes that the pilot can see and act. Balance verdicts need a batch with seats/roles
swapped and pooled (a card game pooled a deck×seat design because turn order confounded the first batch),
reported with a confidence interval, and compared against the game's own authoritative gate if it has one.

**And before you count that batch: CHECK THAT THE EPISODES ARE DIFFERENT GAMES.** The playtest loop resets
between episodes by calling the adapter's reset, and the documented soft-reset hook takes **no arguments** —
so a game whose reset defaults to "replay the current seed" hands the tier N copies of one match. It is
invisible: the run reports N episodes, the aggregate reports an N-sized denominator, and the sample size is 1.
Found on a browser dice game, where two consecutive "different" battles shared **10 of their first 12
(action, state-delta) pairs**. The cheap check is exactly that one — diff the per-step deltas of episode 1
against episode 2; identical actions producing identical deltas means one seed, not two battles. This is not a
property of that game: any integration following the parameterless soft-reset contract has it, so seed variety
has to be arranged deliberately, per episode or per run, and *stated* in the report.
*(→ `playtest.episode_seeds` + `BaseAdapter.reset_seeded`, which RAISES for adapters that cannot seed rather
than ignoring the argument. A raise is necessary and not sufficient: a JS hook discards extra arguments in
silence, so a browser adapter can forward a seed to a game that does nothing with it and nothing anywhere
throws. The integration must additionally PROVE variety — reset on two seeds, assert the battles differ, and
assert one seed reproduces itself — and that probe must itself be shown able to fail. It was: patching a live
page so `__RESET_GAME__` drops its argument reproduces the original bug exactly, and the probe catches it.)*

**Then choose the METRIC to fit the budget you can actually afford — a win rate usually does not.** The
instinct is to report "the pilot won N of M". At the batch sizes an LLM tier can pay for, that number cannot
answer anything. Worked on the dice game, all measured off its engine for free before a single paid call:

- **Win rate is hopeless at this scale.** 95% CI is ±34 points at 8 battles and ±30 at 10 — it cannot separate
  a 40% pilot from a 75% one. Getting to ±12 needs ~60 battles. Raising *n* is not the fix; it is the
  admission that the metric is wrong.
- **The variance is mostly the SEED, not the pilot.** Across 200 seeds a fixed policy's final-margin sd is
  3.53; the same policy's margin *minus that seed's mean across policies* has sd 2.16. And **31 of 200 seeds
  cannot be won by any policy at all**, so a small-*n* win rate largely reports which seeds you drew.
- **So score PAIRED, against the same seed's own baseline.** Removing seed difficulty is worth **2.7× the
  battles** ((3.53/2.16)²), which is what turns a budget of 8 battles from noise into a measurement: ±1.49
  against a mean best-vs-worst policy spread of 7.6. The baseline costs nothing — a deterministic engine plays
  every reference policy on those exact seeds in milliseconds (§D3, same instrument, different question).
- **Do not screen seeds on outcome.** Pick them by a fixed rule, declared before the run. Screening for
  "interesting" seeds biases the set toward whatever you screened for; the characterisation showed only
  17/200 seeds fail to discriminate anyway, so the cheap honest option is also the good one. Keep the
  unwinnable seeds — paired scoring handles them, because the baseline is negative there too.
- **Report the underpowered metric anyway, with an interval that can express doubt.** Use Wilson, not the
  normal approximation: the latter returns ±0.0 at 0/N and N/N, which asserts perfect certainty from the
  data that has least of it. A first pass here printed "0/1 = 0.0%, 95% CI ±0.0" — a vacuous number (O2) in
  the very line whose job was to show the metric could not be trusted.

*The general form: when a tier's sample size is set by cost rather than by statistics, spend the design effort
on removing variance you can compute for free, not on buying more samples.*

**Superseded in mechanism by P13, which makes this a declared, probed property instead of a per-game habit.
The reasoning above still stands; the manual per-integration proof no longer has to be re-written each time.**

### P10 · The pilot needs MEMORY, not just state — a sliding window is not memory
State tells the agent where it *is*; it does not tell it what it has already tried. Without a
cumulative record, an agent re-runs actions it completed long ago, and the run looks busy while
covering the same ground. This was first noticed on a space-trading sim (repeated inconsequential
actions) and then measured exactly on a terminal-hacking RPG: in a 40-step run the pilot cycled
`scan → connect → ls → analyze → exploit → escalate` over the **same two servers five times**,
ran `ls` 8x and `connect <host>` 4x, and **never issued `cat` — the verb that completes
missions — so it finished 0 missions.**

Both existing guards missed it, for structural reasons worth remembering:
- **The recent-actions window slides.** At the default 5 it can only reveal a cycle *shorter than
  itself*; this cycle was 6–7 steps, so every repeat had scrolled out of view before the next one.
- **The no-op counter is CONSECUTIVE and resets on any productive step.** The run had **zero**
  consecutive repeats, so it fired **zero** times in 40 steps.

**The fix is memory, NOT an anti-repetition rule.** ⚠️ First attempt at this lesson got it wrong
and was corrected the same day: the ledger was written to nudge the agent away from repeating
itself. That is actively harmful. In most games repetition is *correct play* — the terminal RPG's
`ls`/`scan`/`analyze` are scoped to the host you are standing on, so re-running them at a new server
is exactly what the game wants, and penalising it would suppress the behaviour under test. The agent
was not looping out of stubbornness; it had **no way to know** what it had already learned, and
re-running recon is the right response to not knowing.

**Check:** tally distinct actions vs. total steps and look for *interleaved* repetition —
`collections.Counter` over the action log takes seconds. Then ask the real question: could the
agent even *know* what it established 20 steps ago?

**Fix pattern, in two parts:**
1. **A cumulative ledger keyed by (action, CONTEXT)** — not by action alone. The context is a
   config-named state field defining "where you are" (`playtest.action_context_path`; e.g. a
   `currentServerId`). `ls` at four servers then reads as four legitimate observations, while `ls`
   four times at the *same* server is visible as such and the agent draws its own conclusion. The
   block **reports; it does not instruct.** Record attempts, how many *changed state*, and the last
   step — a bare count cannot tell a productive revisit from a stuck one. Bound it by distinct
   (action, context) count, not run length.
2. **Retain the read layer itself** where it lives only in transient output. If a game prints
   knowledge once into a rolling terminal buffer — server security levels, vulnerability names, file
   lists — then state alone never carries it and the agent is *structurally* forced to re-derive it.
   Keep the latest output per (action, context) within a char budget
   (`playtest.terminal_recall_budget`, default 0 = off).

Two adjacent knobs from the same round: **`playtest.objective`** (state what winning means high
in the prompt — the guide says it, but from the *bottom*, behind the state dump and terminal
buffer) and **`playtest.available_actions_path`** (drive the verb list from the game's own live
unlocked-command list, so the agent is never advertised a verb the game will refuse, and a verb
unlocked mid-run becomes visible the step it unlocks).
*(→ `playtest.history_window` / `_action_ledger_block`.)*

### P11 · A prompt-level warning is advice, not a guarantee — a hard loop ceiling needs code, not prose
A text warning that grows more insistent every step ("you've done this 8 times now") still relies on the
model choosing to comply. It does not. A live `gemma4:26b` run repeated one command 163 times in a row while
its own reasoning said "I'm stuck in a loop" on nearly every one of those steps — the warning was working
exactly as designed and changed nothing. Only a deterministic, code-enforced override (reject the Nth
consecutive identical action, substitute a fixed fallback, never re-ask the same model) actually bounds the
behavior. Even then, expect a *different* failure shape, not zero failures: an oscillating "try twice, get
blocked, immediately try the same dead target again" pattern is a real residual, since the ceiling only
remembers the immediately-previous action, not everything it has already blocked this run. A stronger
guarantee (memory of *every* target already blocked, not just the last one) is a bigger change than a soft
warning → hard ceiling upgrade, and worth treating as a separate, deliberate decision.

**Corollary — any "noise floor" metric must exclude synthetic no-op steps from its own denominator.** A
hard ceiling that substitutes a genuine no-op action (e.g. `wait`) for a rejected one will, by construction,
contribute an empty state-delta on every override. A frequency-based filter (e.g. "ignore delta keys that
change on ≥80% of actions, they carry no signal") computed over ALL actions including those synthetic
no-ops will have its threshold silently dragged down as override volume rises — a field that was reliably
~100%-ubiquitous can cross under the cutoff purely from the added no-op steps, and every real action
downstream starts reading as spuriously "surprising." Found on a terminal-hacking RPG: 62 forced-`wait` steps
in a 300-action run pushed `rngCounter`'s ratio to just under 80%, flipping `unexpected_delta_steps` from a
routine single-digit reading to 238/238. Fix: compute the frequency/threshold over only the steps that could
have produced a real delta, not over every step the loop consumed.

**Corollary — the inverse failure is worse, and it is the one you will ship: a warning that asserts a
constraint the loop does not enforce.** The ceiling above is a per-game knob, but the warning text that
announces it was written against the default and hardcoded the claim: *"Picking it again will be REJECTED and
forced to 'wait' — this is a hard rule, not a suggestion."* Any game that RAISES the threshold — because
repeating an action is legitimate play there — then has its prompt inventing a rule. Models comply with
invented rules. A browser dice game set the ceiling to 13 (a whole match on one allocation is a real strategy,
and the `wait` override does not advance a round, so an override would burn budget *and* corrupt the
measurement); at step 15 of 30 its pilot wrote *"I cannot use a3_d3 because I have used it 3 times in a row,
which would be rejected"* and abandoned the allocation its own strategy guide calls correct. `forced_repeat_blocks`
for that run was **0** — nothing was ever blocked. Fixing the text to emit the hard claim only when the next
repeat would genuinely be rejected moved false-prohibition beliefs 2 → 0 and the pilot's longest same-action run
3 → 7 on the very next run. This is P10's own correction resurfacing in a second code path: **report; do not
instruct**, and if you do state a constraint, make it *true at the threshold this game is actually running*.

**Every sentence in the prompt is under test, not just the guide.** Framework-owned prompt furniture — warnings,
ledgers, objective lines — is content the pilot reasons from exactly like the guide, and it is written once,
centrally, for a default that some game will change. Grep the prompt builders for load-bearing claims whenever a
game overrides a knob one of them mentions.

**Corollary — set the ceiling from the game's own committed solution, and DERIVE the bound.** The guard counts
consecutive identical proposals whether or not they changed the state. In a push-puzzle, moving a crate five
cells along a row *is* five consecutive `left`s, and the shipped optimal solutions contained runs of 5 and 6
against a default ceiling of 3 — so the default made the game's own solution physically unplayable, and each
override spent a step on a `wait` that never touched the game. The check that catches this must read the
solution artifact rather than hardcode a number, or authoring one longer push run silently re-breaks it.

**Corollary — neither standard stall detector can see a TWO-CYCLE, and it is the most natural way to waste a
budget.** A pilot alternating `right`/`left`/`right`/`left` between two cells trips nothing: the no-op detector
needs a step with no material delta (every move here changes state) and the repeat guard needs the *same*
action twice running (these alternate). An A-B-A-B loop therefore reads as productive play to every counter in
the loop. The shape is already detectable — `check_state_cycles` in the generic-checks floor finds exactly it —
but that floor runs in the robustness tier, not in the LLM loop. Until it runs in both, read the action log
rather than trusting `back_to_back_repeat_steps` to tell you the pilot was stuck.

### P12 · Validate the harness on a LOCAL model first — never spend an API call proving the plumbing
**Stage the tier: local model proves the CHANNEL, paid model measures the GAME.** They are different jobs and
the same run cannot do both.

> ⚠️ **"Smoke test" means three different things in this repo. Say which one.** We have called stage 1 below
> "the smoke test" in conversation for a long time, and it collides with two unrelated checks:
>
> | Name | What it is | What "it passed" means |
> |---|---|---|
> | `ugt smoke-test` | CLI subcommand, 5 random steps through `UniversalGameEnv` | the config/bridge wiring is alive |
> | **Smoke**, ladder rung 2 (`smoke_<game>_adapter.py`) | the spike's round-trip re-run through `BaseAdapter` | the adapter contract holds against the real game |
> | **Stage 1 / channel check** (below) | a short LOCAL-model playtest | the *pilot* can see and act — says nothing about correctness |
>
> They sit in different tiers and prove disjoint things, so "the smoke test passed" is not a reportable
> sentence. This is M10 again in a different costume: there the name over-promised what one tier proved, here
> one name covers three tiers. **Prefer "channel check" or "stage 1" for the local playtest**, and if you do
> say "smoke", name the rung.

**Stage 1 — local (`--provider ollama`, e.g. `gemma4:26b`). Free, so iterate hard.** Drive basic game actions,
then a **30-action channel check**, sometimes up to 100. This is where the strategy guide and the prompting get
written and rewritten *for that specific game* — the loop is edit-guide → re-run → read the reasoning → edit
again. Iterate until the pilot cleanly processes the basic game loop. Everything §B asks for is cheaper to
discover here, and P1–P8 are all findable on a local model because they are defects in what the pilot can SEE,
not in how well it thinks.

**There is a hard ceiling on stage 1, and it is lower than it looks: ~100 actions.** Beyond ~200 local calls
the run is not just slow, the decisions get measurably worse than Haiku's. **Bad decisions do not equate to
good tests** — a long local run buys degraded play, not more evidence, and any balance number read off it is
noise. Local is a harness check. Never quote it as a result.

*One asymmetry to hold onto, because it cuts against P7:* on a local model the competence grep is a **positive
signal only**. If the reasoning names the game's core mechanics, the channel is proven. If it does not, that
is **ambiguous** — starvation and a weak model look identical from the outside. Do not close a P1/P2/P6 finding
on local silence; re-check it on the paid run.

**Stage 2 — paid (Haiku is the working default: fast and cheap enough to re-run after every fix).** Only once
stage 1 loops cleanly. This is the run that produces numbers anyone is allowed to cite.

**Then iterate, and expect to change the game as often as the harness.** The stage-1/stage-2 loop turns
around far faster than human testing, and that is the whole point: **the target is that the first human UAT is
already relatively bug-free**, so a person's time is spent on feel, readability and onboarding — the things no
tier can see — instead of on defects a 30-action local run would have caught for nothing.

### P13 · Whether episodes are SAMPLES or REPLAYS is a property of the game — declare it, then prove it
P9 says arrange seed variety deliberately. The trap is one level up: **"no seeds configured" means two
opposite things and looks identical in both.** A deterministic game — a fixed-layout puzzle, a
single-solution text adventure, one map with one ordering — is *correct* to replay; its episodes are replays
by design and the honest sample size is 1 however large N is. A game that merely never configured seeds is
about to publish a rate whose denominator is N and whose sample is 1. Same config, same report, and no tier
can tell them apart by looking.

So the game declares its class and the tier proves the declaration against the live game before spending
anything:

| declaration | meaning | what the tier may report |
|---|---|---|
| `per_episode` | seedable RNG, seeds rotate | rates, with an interval |
| `deterministic` | no RNG at all | **competence only** — finished or not, in how many actions vs. a known optimum |
| `uncontrolled` | RNG that cannot be seeded | rates, but no finding can be replayed |

**Probe every mode in BOTH directions, because one-directional checks pass for the wrong reasons.** "Two
seeds differ" is satisfied by a hook returning random state on every call, which is just as broken as one
ignoring the seed. "Two resets match" is satisfied vacuously by a probe action that never moves the state.
Both shapes were caught by the generalised probe; the second fired against a real game the first time it ran,
on an action that is inert from the opening position.

*The general form, and why it is here rather than in one integration: a check that lives in a game's own
script is a habit, not a guarantee. The seed-variety proof sat in a browser dice game's playtest script for a
week, which meant every other game in the portfolio had no such proof and nobody noticed. Anything you would
write into every integration belongs in the framework, keyed off a declaration the game makes.*
*(→ `ugt/core/seeding.py`; `tools/prove_seeding.py` is its test suite.)*

### P14 · Trace the content graph: prove it is solvable, then prove every obstacle TEACHES
P1–P13 ask whether the pilot can see the game. This asks whether the game says anything back. They are
different failures and the second one looks exactly like a stupid model.

**Solvable is the easy half, and passing it proves less than it looks.** Walk the whole dependency graph —
every gate, what sets it, where that thing lives, in what order — and confirm a real playthrough reaches the
end. A committed walkthrough replayed by R1 does this for free. But solvable only says a path *exists*; it
says nothing about whether a player who does not already know the answer could find it.

**The half that actually bites: for every obstacle, ask what the player is told when they hit it.** Not what
they are told after solving it — at the moment of refusal. Do this per gate TYPE, because a game usually has
more than one and they are usually authored by different mechanisms:

> A ten-room text adventure had beautiful authored refusals on every *object* gate — *"the wick is bone dry,
> without oil it will never catch"* names the missing thing — and one shared engine string on every *door*:
> *"the way is shut."* The LLM pilot opened six of eight locks off the object hints, then spent its last
> twenty moves at a door that could not tell it anything, while holding both things that would have opened it.
> Same game, same session: one gate type carried the whole design and the other carried none of it, and
> nothing in the ladder could see the difference because both are legal refusals.

Checks worth running once per game, all cheap and all off-model:
- **Diff the gate types.** Group obstacles by mechanism (object gates, door gates, skill checks, currency
  walls). Any group whose refusal is a single shared engine constant is a group that teaches nothing.
- **Read the room text against the gate.** The obstacle must be *visible before* it refuses you. One room
  described a stair as simply climbing north and then refused it — the description advertised an exit the
  rules denied, which is worse than no description.
- **Look for double-gating, which makes authored content unreachable.** The same flag gated both a room and
  the key used inside it, so the player could never stand at the gate and *try* the key — and the key's
  refusal, the best hint in the game, could not be reached by anybody. **Fiction usually says which gate is
  the real one**; here the success text said the bolt was part of the gate, not the stair.
- **Grep for authored data the engine never reads.** A per-object verb column (`unlock`, `light`, `read`) was
  only ever null-checked, so the game authored a vocabulary it then refused to accept: `read ledger` answered
  *"I don't understand that."* Declared-but-unread content is the same defect class as dead refusal text.
- **Check that a rule applies where it should.** `use` verified held-and-prerequisite and never *location*,
  so every puzzle solved from anywhere — a door unlocked from a cell two rooms away, narrating "the door
  swings open" where you stood.

**Enforce the outcome as a content rule, not a review habit.** A gated room now *fails to load* without its
own refusal text, and fails to load if it carries refusal text while ungated. That is the P13 argument again:
a check that lives in someone's review checklist is a habit, and a habit does not survive the next author.

### P15 · The channel between the model and the loop is under test too — a truncated reply must not cost a turn
P1–P8 audit what reaches the model. This is the return leg, and it fails in a way that reads as a bad decision.

A local provider capped replies at 256 tokens. The response contract puts the action FIRST and
`reasoning`/`expected_outcome` after it, so a reply that ran long was cut mid-prose, failed to parse, and the
loop substituted a do-nothing `wait` — **spending a step of the pilot's budget on a decision that had already
been made.** Nothing in the run summary counted it.

**A ceiling set for one genre taxes another silently.** It surfaced on a grid puzzle and never on a card game,
because spatial reasoning is wordier: *"the player is at (4,2) and the crate is at (3,2), so moving left…"* runs
longer than *"attack-weighted, the enemy is at half strength"*. Any per-call ceiling — tokens, timeout, retry
count — is a per-genre tax until someone measures it on the genre in front of them.

- **Raise the ceiling AND salvage the prefix.** A truncated reply is never useful, so a larger ceiling can only
  preserve work; and when it still happens, the action is usually already there to recover.
- **A salvage must be able to REFUSE.** Recover only a name the config declares, or the salvage becomes exactly
  the coercion P4 forbids — a hallucinated verb snapped onto a neighbouring id. Prove both directions: it
  recovers the real name, and it declines an invented one.
- **Say a salvage happened, in the record.** Otherwise a transcript implies the model said more than it did.
- **Count what you discard.** If the loop can throw away a turn, the summary needs a number for it; a silent
  discard is indistinguishable from a pilot that chose to wait.

### P16 · Nothing downstream may score the pilot on a field you redacted from it
P5 removes a field from the prompt. This is the other half nobody remembers: every *analysis* path has to
learn about the redaction too, or the pilot is charged for information it was denied.

A contradiction detector compared the raw state delta against the pilot's stated expectation with no knowledge
of `redact_state_fields`, so two deliberately-hidden fields — a whole-board render and a move counter — were
logged as things the pilot "failed to predict" on **every successful move**. It was absorbed by an unrelated
noise floor (a key changing on ≥80% of steps carries no signal), which is luck rather than correctness: a
hidden field changing on *half* the steps sits under that floor and gets counted forever.

**Audit the redaction as a list of consumers, not a config line.** Prompt, delta summaries, surprise metrics,
auto-flag heuristics, engagement trackers — anything that reads state and reasons about the pilot.

**And separate an INFORMATION fix from a REPORTING fix, explicitly.** P8 invalidates pooling across a change to
what the pilot receives. A change to what gets *written down* invalidates nothing — the runs remain comparable.
Both mistakes cost real work: pooling across a real information change produces a confident wrong number, and
declaring a boundary that does not exist throws away a valid comparison out of caution.

### P17 · A guard that validates against a vocabulary must be proven to fire in every CHANNEL you support
P15 added a salvage so a truncated reply would stop costing a turn. It worked, shipped green, and was
**completely inert for an entire class of game** — which is P15's own lesson recurring one level up: the fix
was real, the failure survived, and nothing said so.

The salvage recovered the action only if the value was a member of the declared action vocabulary. That is
correct for an `action_id` channel, where the value IS an action name. In a **text channel** the value is a
whole command line — `connect 10.0.0.5` — which is never a vocabulary member, so the membership test refused
every salvage and every truncated reply still burned a turn. Measured on a terminal-hacking RPG
(Next.js + Postgres) driven by typed command lines: the wordiest genre in the portfolio and therefore the one
likeliest to truncate, i.e. the guard was absent exactly where it was most needed.

- **Keep the guarantee, change the unit you check.** Do not relax the guard to "accept anything" — that is the
  coercion P4 forbids. Match the part of the value that the config actually declares: for a command line,
  the **verb** (`connect …` recovers, `frobnicate …` refuses); the arguments stay the model's own text and are
  never invented by the recovery path.
- **A second backend can bypass the guard entirely.** The same tier's hosted-API backend forced a structured
  tool call and never reached the parser *or* its salvage, so a cap hit mid-call arrived as an empty argument
  dict the loop silently read as a do-nothing turn. One provider's fix is not the tier's fix — enumerate the
  backends, not just the modes.
- **Pin the old behaviour in the test.** The proof harness asserts that the pre-fix rule *still* discards the
  text-mode reply, so the regression cannot return quietly. 13/13, both directions, both channels.

**The general rule: for every guard, list the modes and backends it runs under, and prove it fires in each.**
A guard proven in one mode is evidence about that mode only.

---

## C. Operational discipline

**O1 · Verify the LISTENING PID is the process you spawned.** `lsof -nP -iTCP:<port> -sTCP:LISTEN` after every
server start. A stale server squatting the port once absorbed an entire campaign against OLD code — health
returning 200 is not evidence it is *your* server.

**O2 · No vacuous passes.** Every assertion must be able to fail. Comparing a value to itself, asserting over
an empty collection, or checking an input the run silently never populated is prohibited. UGT independently
rediscovered this failure mode three times (a card game's seed-search stitching bug, a hunt adapter's `step`
that never wired `info["result"]`, a Godot game's spawner suite asserting a cap against zero enemies). A
vacuous green is worse than a red.

**O3 · A carried "pre-existing failure" list is where bugs hide.** 21 such tests in a Godot bullet-hell game
concealed **6 real product bugs**; ~11 of them were structurally unpassable. "Not caused by my changes" is
never a disposition. A failure count *rising* mid-repair is progress.

**O4 · Verify the edit applied.** A no-op edit and a real one look identical from the exit code — BSD `sed`
`\t` and a stale `str.replace` target both produced silent no-ops that were read as evidence. Assert on the
patch target. Never `git checkout <file>` to undo a debug patch.

**O5 · Repair gaps before advancing a rung.** Do not go R2→R3 with open findings. Route each finding to the
right repo first (game bug → game repo; driver/harness gap → UGT), then re-run the gate until green or until
the limitation is explicitly named and agreed.

**O6 · Every run gets a debrief before any retest.** A/B/C/D: (A) did UGT do its job, (B) was the model
adequate, (C) what are the findings, (D) root cause per finding — game / harness / UGT-core.

**O7 · A conclusion needs cited evidence, not a feeling.** "Looks fine" is not a disposition. Every
found-and-fixed or checked-and-clean must name the specific code compared and why it differs from (or matches)
the known-bad pattern.

**O8 · Never widen a denominator to look better, never narrow one to hide a gap.** If a check's category
changes, state the before/after tally.

**O9 · Never point a test suite at a live environment — its setup may destroy data, and the damage
masquerades as a product bug.** Integration suites routinely truncate every table in `globalSetup`. Handing
one a `DATABASE_URL` for a running dev server wiped a terminal-hacking RPG's seeded game world mid-session; the
next gate run failed as *"exploit failed within 15 attempts"*, which reads like a broken hack. It was a missing
target host. Two defences: (a) run suites through their own config/runner, never by re-pointing the URL
yourself; (b) when a failure implies an absurd probability, believe the arithmetic over the error message — 15
consecutive failures at 90% is ~1e-15, and that number is what located the real cause. Same shape as a Godot
game where headless test runs were overwriting the real player's save.

**O10 · A rung that passes at its old check count after new content shipped has not tested the new content.**
A terminal-hacking RPG's R2 returned exactly its 36/36 baseline on a build that had just gained a whole
economy — because it never touched it. The identical count *was* the signal. When a game gains a system, the
gate's denominator must move; if it doesn't, the gate is certifying ground it never walked. Grep the gate for
the new system's nouns before trusting its green. (Bumping that gate 36/36 → 46/46 surfaced a determinism-seam
defect one rung before it would have corrupted R3's replay criterion.)

**O11 · A uniform-random probe is the wrong instrument for a context-gated game — measure how often it proves
nothing.** `ugt smoke-test` sends 5 random action ids and reports the wiring healthy. In a Node text-adventure
with 41 declared actions, only **6 are live from the opening position**, and the engine's refusals are
documented to consume *nothing* — not a move, not a counter. So five random steps leave the observation vector
frozen with probability (35/41)^5 ≈ **45%**, and the tier prints "fully operational" anyway. Observed in 2 of
3 consecutive runs. Nothing was broken, which is what makes it dangerous: a green meaning "the pipe is open"
is indistinguishable from a green meaning "the game works". This is not a property of that game — **any game
whose action space is large and mostly context-gated has it**, which is most adventure, RPG and strategy
games; a 4-action puzzle game does not. Fixes, in order of preference: drive a short known-good script instead
of random ids, and assert the state moved; and compute the inert fraction inside the rung so it stays honest
when the content changes. Corollary of O2 — an assertion that *can* fail but usually has nothing to fail
against is only marginally better than one that cannot.

**O12 · If a driver COMPOSES arguments, assert the composed command LANDS — a shape assertion cannot see a
dead argument.** An adapter for a terminal-hacking RPG (Next.js + Postgres) filled two verbs from invented
constants — plausible-looking Unix paths (`/etc/passwd`, `/etc/shadow`) that existed on no server in the
game. Both commands came back `File not found`. The rung driving them asserted only that a well-formed
4-tuple came back, which it always did, so the integration ran its **entire life** with `cat` — *the verb
that completes missions* — testing a missing file. Its siblings worked (`exploit <real-vuln-type>`,
`accept <mission-from-state>`), which is what hid it: spot-checking one composed argument tells you nothing
about the others. The fix has two halves and the second is the durable one: (1) compose from what the game
actually printed — cache the file listing the game already gave you, and when nothing is known send the verb
**bare** so the game issues its own usage refusal, because an invented argument earns a refusal
indistinguishable from a real answer about a real target; (2) **add the assertion that was missing** — drive
the real prerequisite chain, then require every argument-taking verb to return success. That rung went 5/5 →
7/7 and was mutation-proven both ways (restore the constant → 5/7 red; remove it → 7/7). Corollary of O2 and
O11: the constants were the symptom, the absent assertion was the defect.

---

## D. Deciding a design change — the mechanics bake-off

**When a balance finding is a *design* question rather than a constant to tune, do not argue it and do not
guess it. Get independent opinions, synthesize on agreement, then simulate every candidate before touching
code.** This section is a decision procedure, not a testing tier — it runs *before* an edit exists, which is
exactly why it is cheap.

The whole loop below cost ~2 minutes of compute and one session on a browser dice-combat prototype (React/JS),
and it killed the recommendation that had looked best on paper. The alternative — implement the plausible fix,
discover it was wrong three rungs later, unpick the test churn — is the shape that puts projects in development
hell for a year.

**D1 · Get independent opinions, and make them genuinely independent.** Same prompt, isolated context, no
shared scratchpad. Vary the *reviewer*, not the question: different models is one axis, but so is different
persona (game designer vs. competitive player vs. casual player; full-stack dev vs. mobile user). Two is the
minimum, not the target. This is a prompting discipline, not a coding one — the cost is a prompt, the return is
an assumption you would not have questioned alone.
*Instruct each reviewer to verify the framing rather than accept it. Both reviewers here corrected the premise
they were handed: "allocation is not a trade-off" was over-stated (the decision was already worth +0.12 under
state-aware play), and "mutual defense converges to zero" named the wrong mechanism.*

**D2 · Synthesize on agreement; treat a lone claim as a hypothesis, not a finding.** Publish the agreement
table first — where independent reviewers converge is the strongest signal available without running anything.
Here both independently returned `STRUCTURAL`, both proved it with a 7×7 strategy matrix that removed the AI
from the loop, both refuted the AI-is-the-culprit hypothesis, and both caught a stale PRD. All of that was safe
to bank. Where they *diverged* — which fix — is precisely what had to be measured, and each had proposed a fix
the other never tested.

**D3 · Simulate before you code. Opinions are a prior; the engine is the evidence.** A reviewer's
recommendation encodes training-data intuition about games in general, not *this* game's numbers. A
deterministic engine is usually pure and dependency-free, so a candidate change can be measured in seconds
without an edit, a migration, or a test rewrite. The dice bake-off ran **3.15 million battles across six rule
variants in 50 seconds.**
*This does not require a fully simulable game. Narrative and multi-branch games resist end-to-end simulation,
but their **mechanical subsystems** — combat resolution, XP curves, drop tables, economy loops, NPC
disposition — are almost always pure functions that can be swept in isolation. Sweep the subsystem, not the
story.*

**D4 · Generate variants from the real source by anchored substitution — never by re-implementing the rule.**
M1 applies to measuring instruments too. Copy the shipped engine and patch it at named anchors; assert each
anchor matched *exactly once* **and** that the output actually changed (O4). Assert the no-change control comes
back byte-identical to production. A variant that silently diverged from the game produces confident numbers
about a game nobody is shipping.

**D5 · Validate the rig on a prediction it did not produce.** Before trusting a bake-off, make it reproduce a
number some independent source called in advance. One reviewer predicted, blind, that a defense buff without a
draw-rule change would give ~79% draws; the rig returned 81%. That single agreement is what licenses every
other cell in the table. Without it a bake-off is just a spreadsheet of its own assumptions.

**D6 · Pick metrics that separate *balanced* from *deep* — win rate cannot.** A flat game and a rich game both
show ~50% win rates. The candidate that looked best on equal win rates turned out to have a 7×7 matrix that was
a **wall of 0.50–0.51**: it removed the dominant strategy by removing the decision, dropping the value of
choosing well to *half* the shipped game's. Measure at least:
- **regret of the naive strategy** — what does playing the obvious line cost against a best response? `0.000`
  means there is no decision.
- **best-response vector** across opponent strategies — if it reads `[0,0,0,0,0,0,0]`, the game has one answer.
- **dead options** — choices that beat nothing, at any opponent, ever.
- **value of deciding per turn** — best state-aware play minus best constant play. This is the depth number.
- **interior mass** — how often optimal play picks a genuine mix rather than a corner. The winning change moved
  this **6.8% → 61.3%**; the losing one raised option variety while *lowering* decision value.
- **how outcomes are reached**, not just who wins — the winning change had to be checked for quietly converting
  a knockout game into a points game (it did; a constant tune bought the knockout rate back).

**D7 · Sample size is a correctness property, not a performance tuning knob.** Cheap sims tempt small `n`, and
small `n` reverses conclusions. One reviewer's first sweep at 400 seeds/cell called the dominant strategy "not
dominant" in 33 of 42 configs — **every one reversed** at 2–3k. The losing candidate scored well at 200 seeds
and collapsed at 5,000. Where the enemy policy is a pure function of state, skip sampling entirely and solve the
MDP by backward induction — then **cross-validate the exact solve by playing its optimal policy back through
the real engine** (all six agreed to three decimals here, which is what made the exact numbers usable).

**D8 · A design verdict is the user's call, not the harness's.** The bake-off's job is to make the trade-off
legible — "this fix is deepest but converts 85% of battles from knockouts to points decisions" — not to pick
the game's identity. State the caveats and hand over the decision.

---

## E. Adding a lesson

1. The finding lands in the game's integration findings log first, with its evidence.
2. Promote it here only if it would have bitten a *different* game. Give it the next free ID in its section.
3. Every entry needs: the rule as an imperative, the evidence (numbers, not adjectives), and — for portability —
   the game named by genre + tech stack, not by project name.
4. If a lesson is later refuted, mark it struck-through with the correction — do not delete it (M9).
