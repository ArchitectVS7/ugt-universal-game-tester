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
*Corollary — measure at the right granularity or the check is silently vacuous.* The first monotone-growth
implementation looked run-wide, so every episode reset registered as a fall and **nothing could ever flag**. It
passed its own gate by being useless. Farming happens within one life; per-episode is the window. It was caught
only because the rung asserted the channel could still SPEAK with the allowlist removed (O2 applied to a
whole channel, not one assertion).

---

## B. LLM playtest pre-flight — the information-integrity audit

**Run every check below and write a cited disposition for each BEFORE any balance batch.** Skipping this cost
two multi-hour balance batches on a card game that measured the wrong thing (one reported 92.6% from a *blind*
pilot; a later one 89.8% from a *rules-blind* pilot). Both numbers are permanently unpoolable with anything
measured after the fix.

The unifying failure mode has a name: **information starvation** — the game exposes what a competent player
needs, and the harness or the guide drops it on the floor. It is invisible in the run output: the loop reports
`PLAYTEST MET`, zero invariant violations, zero bugs, and a confident-sounding win rate.

### P1 · The LLM must see entity **identities**, not opaque handles
Counts and integer ids are not a choice. A card game's playtester picked among `instanceId` ints for 800
actions and said so mid-run: *"the current state shows no specific cards in hand are visible to me via the
JSON."* **Check:** read one real prompt and ask "could a human play well from only this?" **Fix pattern:**
annotate the legal-action list with display-only keys (`_card`, `_hand` — underscore prefix = stripped before
the wire), never by widening the wire payload.

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
*(→ `ugt/core/playtester.py::_redact`.)*

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
