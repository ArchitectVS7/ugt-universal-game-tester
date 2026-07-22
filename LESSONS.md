# UGT — Lessons Registry

> **This is the canonical, cross-game lessons file. Read it before onboarding a new game, before advancing
> any ladder rung, and — section B especially — before any LLM playtest run.**
>
> Everything here was paid for by a real run that went wrong. Each lesson carries an ID, a one-line rule, the
> evidence that produced it, and where the full write-up lives. Per-game findings stay in
> `integrations/<game>/RESULTS.md`; a finding is promoted here **only when it generalizes to games it was not
> found in**.

Referenced from: `CLAUDE.md` (Start here), `UGT-USER-MANUAL.md` (methodology), `PLAYTEST-DESIGN.md`
(tier-3 spec), `integrations/README.md`.

---

## A. Core methodology — applies to every game, every tier

**M1 · Drive the REAL game, never a re-implementation.** The single biggest failure mode: an adapter/bridge
that reimplements game logic (travel, combat, economy) instead of calling the running game. Whatever the
bridge forgets silently does not exist for the agent — we shipped a bridge with **no combat**, and every
trained agent learned a game that could not fight. If your adapter contains game *rules*, you are testing the
adapter. Prefer, in order: (a) drive the game's real server/UI as a client; (b) call the game's own functions;
never (c) a parallel copy. An unmapped action must raise `NotImplementedError`, never fabricate behavior.
*Source: `sim_bridge.ts` collapse — `Dev/PLAN-FORWARD-spacerquest.md`.*

**M2 · Dual validation — expect to find game bugs and pause.** UGT validates two things at once: that it can
test the game, and the game itself. Finding a real game bug and pausing to fix it upstream is a successful
outcome, not a distraction. Budget for test↔fix round-trips.

**M3 · Failed checks are data — record them.** Negative results (an agent that collapses, an unreachable
mechanic, a reward that rewards the wrong thing) are often the most valuable findings. Write them into
`RESULTS.md` so the next session does not re-learn them.

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
exploit-hunter (no reward engineering needed). Balance / is-it-good → the LLM playtester (competent play
beats volume). Do not force one agent to answer all three.

**M8 · Test over the wire — a green in-process suite cannot see serialization-boundary bugs.** The game's own
client and tests route around the wire, so defects *on* it are invisible to them. DDD had 1,251 in-process
tests green while 7 of 40 cards played blank for every wire client (a field never exposed over the wire) and
`create` accepted a config that `replay` would refuse (a missing key silently played a *different game*).
Demand exact-config-key sets; treat a refusal as different from silent inertness; kill vacuous greens; and
when an invariant never fires, suspect your own invariant first.
*Source: `integrations/ddd/RESULTS.md` D-F1/D-F2.*

**M9 · Audit your own findings before citing them.** UGT has over-claimed from small samples and misread
cumulative counters. Investigate before *confirming*, not only before dismissing. Record corrections in the
integration's `RESULTS.md` rather than deleting the mistake.
*Source: `integrations/ddd/RESULTS.md` D-C1/D-C2 (both partly refuted); pond PC-9 (my own bad finding).*

---

## B. LLM playtest pre-flight — the information-integrity audit

**Run every check below and write a cited disposition for each BEFORE any balance batch.** Skipping this cost
two multi-hour DDD batches that measured the wrong thing (L-008: 92.6% from a *blind* pilot; L-010: 89.8% from
a *rules-blind* pilot). Both numbers are permanently unpoolable with anything measured after the fix.

The unifying failure mode has a name: **information starvation** — the game exposes what a competent player
needs, and the harness or the guide drops it on the floor. It is invisible in the run output: the loop reports
`PLAYTEST MET`, zero invariant violations, zero bugs, and a confident-sounding win rate.

### P1 · The LLM must see entity **identities**, not opaque handles
Counts and integer ids are not a choice. DDD's playtester picked among `instanceId` ints for 800 actions and
said so mid-run: *"the current state shows no specific cards in hand are visible to me via the JSON."*
**Check:** read one real prompt and ask "could a human play well from only this?" **Fix pattern:** annotate
the legal-action list with display-only keys (`_card`, `_hand` — underscore prefix = stripped before the
wire), never by widening the wire payload.
*Source: DDD L-009 / D-L1.*

### P2 · The adapter must pass through every field the game marks PUBLIC
Normalizing state is where read layers die. DDD's `_seat()` discarded `echo`, `chain`, `statuses` and
`modifiers` — all four explicitly PUBLIC in the engine's own types and served to both seats by its
`playerView`. Echo is half the game's ratified core mechanic; **0 of 1,650 reasonings mentioned it.**
**Check:** diff the adapter's normalized state against the game's own player-view/serializer field list. Any
field you drop, justify in a comment.

**This is not a one-time check — re-run it every time the game's state surface changes.** NEXUS passed P2
cleanly on 2026-07-22, and hours later a game-side feature added `toolTier` to its `player-state` route while
`NexusHttpAdapter._read_state()` — which builds an explicit dict and silently discards anything unlisted —
dropped it on the floor. The pilot could have bought a toolkit and never seen that it owned one. An adapter
that enumerates fields explicitly is safer than one that passes everything through, but only if something
re-checks it after each schema change. Make it part of the definition of done for any game-side change.

**Corollary — a partial list is a starvation defect the moment you treat it as authoritative.** In the same
round, a prompt knob was written to replace the action vocabulary with the game's own live `unlockedCommands`,
reasoning that the agent should never be offered a verb the game will refuse. That field turned out to be a
*hack-verb* list omitting a third of the game's commands, including two just added — so the replacement would
have hidden a brand-new subsystem from the pilot. Annotate with such lists; never let one subtract.
*Source: DDD L-011 / D-L4; NEXUS L-015 / D-L15-1, D-L15-2.*

### P3 · Truncation is silent starvation
Budgets (`playtest.guide_char_budget`, `playtest.terminal_char_budget`) cut from a *tail*, and nothing warns
you. DDD's guide budget went 2000 → 6000 → 11000 as the guide grew; each raise was in the same commit as the
content it had to fit. **Check:** assert `len(guide) <= guide_char_budget` and that the terminal budget
exceeds the game's longest single output (list/scan/inventory screens are the usual overflow).
*Source: DDD L-009, L-011.*

### P4 · The action channel must send what the LLM thinks it is sending
DDD's `apply_legal` relayed legal actions verbatim with `targets: []`, so every targeted card played blank —
the exact wire defect already fixed upstream, replayed on the UGT side. The engine accepted it silently, so
zero invariants fired. **Check:** for one action of each shape, log the composed wire payload and confirm it
carries the arguments the LLM chose. **Fix pattern:** fill arguments at *enumeration* time so the LLM chooses
the action it will actually get.
*Source: DDD L-009 / D-L3.*

### P5 · The prompt must not leak what the real client hides
The god-view state an invariant needs is not the view a player gets. DDD handed the always-second seat the
first mover's committed card-vs-pass bit — which the engine's redacted view deliberately withholds.
**Check:** name every field in the prompt that the game's own client cannot see. **Fix pattern:** the
game-agnostic `playtest.redact_state_fields` knob (dotted paths dropped from the *prompt only* — state JSON
and delta summaries; logs, invariants and reports keep the full state).
*Source: DDD L-009 / D-L2 → `ugt/core/playtester.py::_redact`.*

### P6 · The strategy guide must teach the RULES that create the skill, not just the entities
A guide that lists commands/cards but not the mechanics that reward reading them produces a pilot that goes
through the motions. DDD's guide named `stance` but taught no type triangle, no stance transition/regen, no
echo, no chains: 745/1,650 reasonings mentioned stance, ~zero used its mechanics, and the +5 counter — the
game's core skill — was never once collected. The informed baselines (`@ddd/ai` tiers 2–3) beat the LLM
precisely because their evaluator priced those rules.
**Check:** list the game's scoring/skill mechanics from its rulebook; for each, grep the guide. Also cover
*known truncation/cap semantics* the player would otherwise mis-plan around.

**Verify every rule you write against the RUNNING game, not only against the code that appears to produce
it.** Two NEXUS guide claims written from source were falsified by one live probe: hardcore was stated as
"~30% base odds" when the code applies a flat −10%, and a "+15% skill floor from level 1" was contradicted by
a live breakdown reading `Exploit Skill Lv0` with no skill term at all — the cited `floor(points/100)+1` was
the *update* formula, not the starting value, and the real accessor returns `?? 0`. A guide is prompt content:
a wrong rule in it is not a harmless doc bug, it actively misinforms the pilot and corrupts the batch, which
is the same damage as omitting the rule (P6) with none of the visibility. Run one action of each kind and read
what the game actually prints.
*Source: DDD L-011 / D-L5; NEXUS L-015 / D-L15-3.*

### P7 · Verify competence from the reasoning text, not from the exit code
`PLAYTEST MET` only proves the channel works. The cheap, objective competence probe: after a short sanity run,
**grep the logged `reasoning` for the game's core mechanic terms and real entity names.** Zero mentions of a
central mechanic = starvation, no matter how clean the run. This is what turned both DDD batches around, and
it is the only check in section B that needs a live run.

### P10 · The pilot needs MEMORY, not just state — a sliding window is not memory
State tells the agent where it *is*; it does not tell it what it has already tried. Without a
cumulative record, an agent re-runs actions it completed long ago, and the run looks busy while
covering the same ground. This was first noticed on SpacerQuest (repeated inconsequential
actions) and then measured exactly on NEXUS 2026-07-22: in a 40-step run the pilot cycled
`scan → connect → ls → analyze → exploit → escalate` over the **same two servers five times**,
ran `ls` 8x and `connect 192.168.1.105` 4x, and **never issued `cat` — the verb that completes
missions — so it finished 0 missions.**

Both existing guards missed it, for structural reasons worth remembering:
- **The recent-actions window slides.** At the default 5 it can only reveal a cycle *shorter than
  itself*; this cycle was 6–7 steps, so every repeat had scrolled out of view before the next one.
- **The no-op counter is CONSECUTIVE and resets on any productive step.** The run had **zero**
  consecutive repeats, so it fired **zero** times in 40 steps.

**The fix is memory, NOT an anti-repetition rule.** ⚠️ First attempt at this lesson got it wrong
and was corrected by the repo owner the same day: the ledger was written to nudge the agent away
from repeating itself. That is actively harmful. In most games repetition is *correct play* —
NEXUS's `ls`/`scan`/`analyze` are scoped to the host you are standing on, so re-running them at a
new server is exactly what the game wants, and penalising it would suppress the behaviour under
test. The agent was not looping out of stubbornness; it had **no way to know** what it had already
learned, and re-running recon is the right response to not knowing.

**Check:** tally distinct actions vs. total steps and look for *interleaved* repetition —
`collections.Counter` over the action log takes seconds. Then ask the real question: could the
agent even *know* what it established 20 steps ago?

**Fix pattern, in two parts:**
1. **A cumulative ledger keyed by (action, CONTEXT)** — not by action alone. The context is a
   config-named state field defining "where you are" (`playtest.action_context_path`; NEXUS:
   `currentServerId`). `ls` at four servers then reads as four legitimate observations, while `ls`
   four times at the *same* server is visible as such and the agent draws its own conclusion. The
   block **reports; it does not instruct.** Record attempts, how many *changed state*, and the last
   step — a bare count cannot tell a productive revisit from a stuck one. Bound it by distinct
   (action, context) count, not run length.
2. **Retain the read layer itself** where it lives only in transient output. If a game prints
   knowledge once into a rolling terminal buffer — NEXUS server security levels, vulnerability
   names, file lists — then state alone never carries it and the agent is *structurally* forced to
   re-derive it. Keep the latest output per (action, context) within a char budget
   (`playtest.terminal_recall_budget`, default 0 = off).

Two adjacent knobs from the same round: **`playtest.objective`** (state what winning means high
in the prompt — the guide says it, but from the *bottom*, behind the state dump and terminal
buffer) and **`playtest.available_actions_path`** (drive the verb list from the game's own live
unlocked-command list, so the agent is never advertised a verb the game will refuse, and a verb
unlocked mid-run becomes visible the step it unlocks).
*Source: NEXUS L-014 P10 → `playtest.history_window` / `_action_ledger_block`.*

### P8 · Never pool batches across an information fix
Any change to P1–P6 changes what was being measured. Mark the boundary explicitly in `RESULTS.md`
("L-010's 89.8% must not be pooled with any post-L-011 batch") and re-baseline.

### P9 · One clean run proves the channel, not the balance
A single sanity run establishes that the pilot can see and act. Balance verdicts need a batch with seats/roles
swapped and pooled (DDD pooled a deck×seat design because turn order confounded the first batch), reported
with a confidence interval, and compared against the game's own authoritative gate if it has one.
*Source: DDD L-008 (confounded), L-010 (pooled seat-swap).*

---

## C. Operational discipline

**O1 · Verify the LISTENING PID is the process you spawned.** `lsof -nP -iTCP:<port> -sTCP:LISTEN` after every
server start. A stale server squatting the port once absorbed an entire campaign against OLD code — health
returning 200 is not evidence it is *your* server.

**O2 · No vacuous passes.** Every assertion must be able to fail. Comparing a value to itself, asserting over
an empty collection, or checking an input the run silently never populated is prohibited. UGT independently
rediscovered this failure mode three times (DDD's seed-search stitching bug, pond's `HuntAdapter.step` never
wiring `info["result"]`, the-pond's spawner suite asserting a cap against zero enemies). A vacuous green is
worse than a red.

**O3 · A carried "pre-existing failure" list is where bugs hide.** 21 such tests in the-pond concealed **6
real product bugs**; ~11 of them were structurally unpassable. "Not caused by my changes" is never a
disposition. A failure count *rising* mid-repair is progress.

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
one a `DATABASE_URL` for a running dev server wiped NEXUS's seeded game world mid-session; the next gate run
failed as *"exploit failed within 15 attempts"*, which reads like a broken hack. It was a missing target host.
Two defences: (a) run suites through their own config/runner, never by re-pointing the URL yourself; (b) when
a failure implies an absurd probability, believe the arithmetic over the error message — 15 consecutive
failures at 90% is ~1e-15, and that number is what located the real cause. Same shape as the-pond PC-2, where
headless test runs were overwriting the real player's save.
*Source: NEXUS L-016.*

**O10 · A rung that passes at its old check count after new content shipped has not tested the new content.**
NEXUS R2 returned exactly its 36/36 baseline on a build that had just gained a whole economy — because it
never touched it. The identical count *was* the signal. When a game gains a system, the gate's denominator
must move; if it doesn't, the gate is certifying ground it never walked. Grep the gate for the new system's
nouns before trusting its green.
*Source: NEXUS L-016 (R2 36/36 → 46/46, which surfaced NX-L15-1 one rung before it would have corrupted R3's
determinism criterion).*

---

## D. Adding a lesson

1. The finding lands in `integrations/<game>/RESULTS.md` first, with its evidence.
2. Promote it here only if it would have bitten a *different* game. Give it the next free ID in its section.
3. Every entry needs: the rule as an imperative, the evidence (numbers, not adjectives), and a source pointer.
4. If a lesson is later refuted, mark it struck-through with the correction — do not delete it (M9).
