# UGT Track Record — Has It Earned Its Place?

*Compiled 2026-07-21; refreshed same day after the L-001–L-006 LLM-tier push. Sources: `PLAN-FORWARD.md`,
`PLAN-FORWARD-spacerquest.md` (this folder), every `integrations/<game>/{HANDOFF,RESULTS,README}.md`,
`PLAYTEST-DESIGN.md`, `UGT-USER-MANUAL.md`, `TASKS.md` (L-001–L-006 delivery notes), the surviving
`integrations/spacerquest_old/results/**/*.json` campaign logs, and git history of `ugt/core`, `ugt/adapters`,
`ugt/cli.py`, `ugt/utils`.*

## Bottom line

Eight integration efforts across seven distinct game codebases (plus one restart), three transport paradigms,
and four genres have now run through UGT. Every one of them found and fixed real, player-facing bugs in the
*game*, not just in the tester — including three CRITICAL-severity bugs a real player would have hit
immediately (SpacerQuest's free-attack fuel exploit, Nexus Dominion's inert-empire opening, Pond's
un-killable enemy). UGT also broke itself in smaller ways along the way, caught its own three false findings,
and has now independently rediscovered the same failure mode (a check that silently never runs and reports a
vacuous green) **four times** — DDD, Pond, and, as of today's audit pass, Warzones/Tarot-War's determinism
checks and, most significantly, **the shared playtester core itself**. The LLM balance tier, which one review
ago had driven a verdict on exactly one game, is now wired and `ollama`-validated on five of seven games —
but that same push found the core tier had been silently blind on a real (if rare) class of action the whole
time, which is either the best possible argument for doing this work or a reason to treat every prior LLM
playtest result with one more grain of salt. Both are true; see below.

---

## Chronological lesson log

**2026-07-04 → 07-06 — SpacerQuest (game #1), the founding lesson.**
UGT's very first integration was `sim_bridge.ts`, a headless reimplementation of SpacerQuest. It slowly drifted
from the real game — no combat, broken upgrades — and every agent trained against it learned a *different
game* than the one players actually played. This is the reason the whole architecture exists in its current
form: `RealClientAdapter` was rebuilt to contain **zero game logic**, talking Socket.IO + HTTP to the live
running server, with unmapped actions raising `NotImplementedError` by design rather than inventing behavior.
Phase 0–2 then ran a full ladder (spike 7/7, smoke 8/8, DoD 13/13), an exploit-hunter pass (200 steps, 0
violations), and the only LLM balance campaign UGT has ever completed (Gate-C). It surfaced 7 ranked findings,
all fixed and reverified live — most importantly a **fuel-gate exploit** letting players attack at full power
with no fuel (35 wins/1 loss pre-fix, 0/14 post-fix) and a cargo-scoring formula that had silently dropped its
distance/battle terms. Two *new* exploits (a bare-endpoint score pump, an `end_turn`/`buy_fuel` poverty trap)
turned up on the reverify pass itself. UGT also got one of its own findings wrong here — a "battlesWon
double-increment bug" was a cumulative-counter misread, retracted rather than buried. **Lesson banked:**
play the game with the game; audit your own findings before citing them.

**2026-07-05–06 — the stale-server lesson.** A full 3×100-step campaign had to be aborted mid-run because a
stale process was squatting SpacerQuest's port and passing health checks — the campaign had been testing old
code the whole time. This produced the standing rule (still enforced today): after every server start, confirm
the LISTENING PID with `lsof` is the process you actually spawned. Health check 200 is not proof.

**2026-07-06 — Warzones (game #2), first browser game, first `PlaywrightAdapter` outing.**
A Phaser space-trader driven headlessly via `window.__GET_STATE__`/`__SEND_ACTION__` hooks — proof the
adapter pattern generalizes beyond sockets. R1 23/23 → R2 12/12 → R3 6/6, with two **critical** bugs found:
any pirate encounter destroyed the run (three compounding scene bugs), and the entire commodity economy
rendered zero rows because the registry was never populated in the running game — a bug no unit test could
see because nothing in-process ever asked "is the registry actually populated after a real boot." A later
finding (WZ-R9) showed a successful flee never marked combat resolved, leaving a race window where ATTACK
still worked after the player had already fled. One finding (WZ-R3, contract scene never launches) is still
open, explicitly deferred to a future game version, not silently dropped.

**2026-07-07 — Tarot-War (game #3), first turn-resolution/card game.**
A React war-card game reached full ladder completion the same week: R1 22/22, R2 12/12, R3 7/7, all 8
findings closed. The standout is TW-R3: this game had **no seed seam at all** before UGT arrived — UGT's own
determinism requirement (same-seed replay must be byte-identical) forced the game to add a
`seededRandom.ts` and route nine call sites through it, which is a case of the testing methodology directly
improving the game's own architecture, not just finding bugs in it. TW-R8 (a game continuing to resolve after
an instant-win condition already fired) needed two fix passes — the first fix was itself incomplete, and UGT
caught that on the second pass rather than accepting a partial fix as done.

**2026-07-08–09 — NEXUS (game #4), first live-HTTP integration, and the core extraction.**
A hacking/world-builder Next.js app tested against its own live `/api/test/*` routes (no browser, no
subprocess — plain HTTP). Full ladder: spike 8/8, R1 25/25, R2 36/36 (all 8 missions to a real win across 3
difficulty modes), R3 9/9 with **zero game findings** — the first integration where R3 turned up nothing new
in the game itself, only two harness-side (UGT) issues (a parse regex, a policy composition bias). Because
NEXUS was the fifth informal ladder in a row, its scaffold was pulled out into `ugt/core/trial.py`
(`GateRunner`, `InvariantSuite`, `first_divergence`) — and the extraction was validated the honest way: by
re-running NEXUS's exact ladder against the new shared code and confirming byte-identical results
(spike 8/8, R1 25/25, R2 36/36, R3 9/9). This is the one framework refactor in UGT's history and it has not
regressed since — no commits have touched `trial.py`/`exploit_hunter.py` after that extraction.

**2026-07-11–12 — DDD (game #5), first subprocess-harness game, and the "wire-only defect" thesis proven.**
A card-battler tested via a JSON-lines subprocess harness (no server, no browser). This is where UGT's central
claim — that a green in-process suite cannot see serialization-boundary bugs — got its sharpest proof: DDD's
own suite was 1,251/1,251 green while **7 of 40 Swarm cards played permanently blank for every wire client**,
because the harness never exposed `legalTargets` over the wire even though the in-process engine had it. A
second wire-only bug (`create` silently accepting a config `replay` would refuse) had already caused one
*entire earlier R1 run to silently play a different game* — a missing wave key turned the type-triangle
mechanic off for the whole 2026-07-11 run without anything reporting an error. That run was voided rather than
kept once the mistake was found. DDD is also where UGT caught **itself** overclaiming twice: "the Focus
economy is dead code" was disproven by the game's own re-tuning pass; "`@ddd/ai` never fills targets" was
flat wrong (a grep miss), and only the *random*-policy tier actually had the gap. Both corrections are on the
public record rather than quietly dropped. A same-day evening re-run against the game's follow-up patch
closed both findings live (R3 32/32, zero findings, INSUFFICIENT_FOCUS finally provoked and shown to bind).

**2026-07-16 — Nexus Dominion (game #6), same-day full ladder, and the deepest single bug list.**
A 4X grand-strategy engine, same subprocess-harness pattern as DDD, went spike→R3 complete the same day it was
proposed: 11/11, 6/6, 12/12, 17/17, 43/43. It also produced UGT's largest single defect list — 10 findings,
every one fixed upstream — headlined by **ND-3, a CRITICAL bug where a fresh campaign's Cosmic Order tiers
were left empty, meaning no empire could resolve anything for its first 10 cycles**: a brand-new game was
functionally inert for a real player's entire opening. ND-2 (77 completed unit builds silently never joining
a fleet) and ND-7 (a divergent, effectless second implementation of the player's own covert-ops path) are the
same "two copies of the same system quietly diverge" shape as SpacerQuest's original sim-bridge problem, just
inside one codebase instead of between a bridge and a game. Nexus Dominion is also the first integration to
explicitly connect an engine-trial finding to a **failed human UAT** (U-110): the game's own human playtester
had already flagged the game as broken/confusing at the start, and ND-3 is very likely the mechanical cause —
but the report is explicit that an engine trial cannot itself *sign off* U-110, because U-110's remaining
complaints (unreadable star map, no onboarding) are visual/UX, invisible to a subprocess harness by
construction.

**2026-07-17 — a genuinely new UGT-side fix, and the Rimward restart.**
`fix(ugt): stable DDD R3 seed + wire up .env for the playtest tier` — a small but real core-adjacent fix
(deterministic seed selection, environment wiring for future LLM runs). The same week, `spacerquest_old` was
formally archived (the 1991-BBS game is being redesigned away, decision out of UGT's hands) and a **new,
unrelated** `integrations/spacerquest/` was opened against the from-scratch "Rimward" rebuild — no Socket.IO
server this time, a pure protocol core over a line-delimited-JSON day-loop wire. Its first campaign
(`ugt verify` 9/9, then a real PPO training run) is a good sanity check on the RL-as-balance-oracle path that
was otherwise retired after SpacerQuest's collapse history: trained mean **+124.0** vs random **−8.4**, 71,107
actions with zero protocol errors, and — notably — an *earlier* eval run had already collapsed to all-`wait`
and was correctly caught and flagged **invalid** by UGT's own collapse detector before anyone treated it as a
result. That detector doing its job on a real collapse, rather than the collapse being missed, is itself a
data point in UGT's favor.

**2026-07-19–21 — Pond Conspiracy (game #7), first real-time game, and the vacuous-check pattern
rediscovered a second and third time.**
A Godot 4.7.1 real-time bullet-hell — the first non-turn-based game and the first non-Python-adjacent engine
(GDScript), driven by a brand-new JSON-lines subprocess harness inside the game's own headless `SceneTree`.
This integration found the single most player-visible CRITICAL bug in UGT's whole history: **PC-5, the tongue
attack's hitbox was tip-only, so everything inside ~119px was unhittable and the player could never kill
anything** — 24 swings landed on a genuinely un-fightable enemy. It also found **PC-2**, arguably the scariest
class of finding UGT has produced: headless test runs were silently deleting the game's real meta-save and
had already bumped the real run-counter to #12866 — an automated *test suite* was destroying real player
progression, and it was only caught because someone asked why a counter looked wrong. R2 needed real
game-side repair work before it went green (21/26 → 45/45 across six denominator revisions, every one
disclosed rather than quietly re-scoped), and that repair surfaced two more real bugs that a shipped game test
had been hiding: **PC-16** (the player could walk out of the arena because of a wrong collision layer) and
**PC-17** (pause was cosmetic — `get_tree().paused` flipped true while gameplay kept running underneath it).
Separately, an 11-test "pre-existing failures, not my problem" list in the game's own suite was investigated
rather than waved off — every one of those 11 turned out to be either structurally unpassable or hiding a real
bug (screen-shake ignoring its duration argument, a synergy silently doing nothing from a key-name mismatch, a
spawner test that was vacuously green because it asserted a cap against zero enemies). And — the methodological
payoff — **the R3 exploit-hunter itself was found to be silently vacuous**: `HuntAdapter.step` never wired the
real snapshot into `info["result"]`, so the entire invariant suite had been running against an empty dict.
This is the *same* failure shape as DDD's R3 stitching bug from five weeks earlier (a probe that silently never
ran, reporting the opposite of the real measurement) — two unrelated per-game scripts, written independently,
both shipped a check that looked green because it never actually executed. That is the clearest evidence yet
that "does my own check actually run" needs to become a standing item in the ladder, not a one-off catch.
Pond also self-corrected one of its own findings (**PC-9**, "max-range tongue hit detection may be broken" —
refuted, reproduced to 2 decimal places as the correctly-working retract animation) and one balance diagnosis
(**PC-15**, withdrawn in favor of the game's own re-measurement). Trial ladder complete as of today: spike
13/13, smoke 8/8, R1 18/18, R2 45/45, R3 11/11.

**2026-07-21 — the LLM-tier push (`TASKS.md` L-001–L-006), and a bug that predates this session by two weeks.**
Following this same day's first version of this report, an orchestrated run closed the LLM-playtest gap it
identified. **L-001** re-audited Warzones' and Tarot-War's ladder scripts for the DDD/Pond vacuous-check
pattern (per explicit priority) and found one real instance: both games' R3 same-seed determinism checks used
an inline predicate (`same_len and divergence is None`) that would report "identical" for two *empty*
trajectories — a latent false-pass for a class of failure that never happened to fire, fixed with a shared,
named `trajectories_match()` predicate and a committed negative-case regression script per game, in the style
of Pond's own self-tests. Both games got a `RESULTS.md`/`HANDOFF.md` for the first time. **L-002** then built
the actual missing piece: a `"legal_action"` schema value and an adapter-instance entry point in
`ugt/core/playtester.py`, letting the LLM tier drive a JSON-lines subprocess harness (no terminal) by reading
its real structured state and choosing from its real legal-action list — validated end to end against DDD via
the free `ollama` provider before touching anything else. **L-003** and **L-004** then wired Nexus Dominion (a
fixed 0–17 order menu, since the engine has no native legal-action enumerator) and Pond (deliberately scoped to
the macro layer only — the LLM is consulted solely at level-up mutation choices, with combat driven by the
existing R1 heuristic policy, since real-time frame-by-frame play was already judged the wrong granularity for
an LLM). **L-005** wired Tarot-War through its *existing* browser engine path (no new schema needed) and, in
the process, disclosed rather than hid a deviation: the game has no keyboard handlers, so the "existing
`press_key`/`type_text`" wording in its own accept criteria didn't fit, and the run used `action_id` mode
instead — the honest choice over a technically-compliant but vacuous one. **L-006** wired NEXUS through its
existing `type_text`/`get_terminal_text` real-server path — and its first attempt exposed a bug in the *shared
core*, not the game: the `type_text` branch of `playtest_game()`'s main loop never reassigned `current_state`
after sending a command, so every state-delta assertion on that path had silently been comparing against `{}`.
This is the exact vacuous-check failure class the whole push was hunting for, except it was sitting in the
tester's own core loop rather than in any one game's script. It was root-caused and fixed in the same task
(guarded so `press_key`-only adapters are byte-for-byte unchanged), and the live NEXUS re-run confirmed all 25
`type_text` steps then carried real state deltas.

Because this bug lived in code every browser/real-server game's playtest run already shared, it was worth
checking whether it had ever fired for real — not just in theory. It had: the surviving
`integrations/spacerquest_old/results/**/*.json` campaign logs (SpacerQuest is the one game with a completed
Gate-C balance verdict) show `type_text` was used only 6 times across roughly 3,150 total playtest actions
recorded — a rare escape hatch, not the campaign's main channel (nearly all of it ran through discrete
`action_id`s, which were never affected). But 3 of those 6 were "accept a found weapon-enhancement salvage
item" prompts (`action: "Y"`, `expected: "...boosting weapon strength"`), and all 3 recorded `"state_delta": {}`
— the bug, caught in the act, two weeks before anyone knew to look for it. Gate-C's actual ranked findings
don't appear to rest on these particular turns (see the open item below), but whether the salvage-enhancement
mechanic itself does what the game intends was never actually verified by UGT — the tooling was blind on
exactly the turns that would have shown it.

---

## How UGT tests different kinds of games

| Genre / stack | Transport | Adapter | Game(s) |
|---|---|---|---|
| Text/BBS RPG over sockets | Socket.IO + HTTP against a live server | `RealClientAdapter` | SpacerQuest (archived) |
| Turn-based headless protocol core | line-delimited JSON over stdio, day-loop | `rimward_gym_bridge.py` (Gym shim, no game logic) | Rimward/SpacerQuest restart |
| Browser action/economy game | headless Chromium, `window.__GET_STATE__`/`__SEND_ACTION__` | `PlaywrightAdapter` | Warzones |
| Browser turn-resolution card game | headless Chromium, exposed React hooks | `PlaywrightAdapter` | Tarot-War |
| Server-rendered web app | plain HTTP against the app's own live test routes | `NexusHttpAdapter` | NEXUS |
| Pure-logic engine, no server | JSON-lines subprocess harness | `DddHarnessAdapter` | DDD |
| Pure-logic engine, no server | JSON-lines subprocess harness | `NexusDominionHarnessAdapter` | Nexus Dominion |
| Real-time engine, no server | JSON-lines subprocess harness inside a headless `SceneTree` | `PondHarnessAdapter` | Pond |

Every adapter obeys the same contract (`connect`/`reset`/`step`/`close`) and the same non-negotiable rule: an
action UGT doesn't understand raises `NotImplementedError` rather than being faked. Six distinct transport
shapes across four genres (text-RPG, browser economy/combat, browser card game, real-time action) is a
reasonable claim that the adapter pattern itself — not just any one adapter — is validated.

## The three tiers, per game

| Game | Loop validation (R1/R2) | Exploit-hunting (R3) | Imbalance / design findings | LLM playtest | Frontend/human UAT |
|---|---|---|---|---|---|
| SpacerQuest (old) | ✅ Phase 0 DoD 13/13 | ✅ Phase 1, 200 steps clean | ✅ Gate-C, 7 ranked findings | ✅ completed balance verdict — **but see the type_text caveat above**: 3 of ~3,150 logged actions had a silently-empty state delta, now understood as the same bug L-006 just fixed | not tracked in UGT |
| Rimward/SpacerQuest | ✅ verify 9/9 | n/a (RL evaluate instead) | RL collapse-detector caught one invalid run | not run (RL path used instead) | not tracked in UGT |
| Warzones | ✅ R1 23/23, R2 12/12 | ✅ R3 6/6 | 2 criticals + 1 open (WZ-R3, deferred); L-001 audit found + fixed an empty-trajectory vacuous-pass risk in the R3 determinism check | not wired — **in active development, deliberately deferred a few days per the user**; L-001 only audited it, no wiring task exists yet | not tracked in UGT |
| Tarot-War | ✅ R1 22/22, R2 12/12 | ✅ R3 7/7 | 8/8 findings closed; same determinism-check fix as Warzones (L-001) | ✅ **wired (L-005)** — `ollama`, 30 actions to round 30, 0 bugs, `action_id` mode (disclosed deviation: no keyboard handlers, so `press_key`/`type_text` didn't fit) | not tracked in UGT |
| NEXUS | ✅ R1 25/25, R2 36/36 | ✅ R3 9/9, zero game findings | 5 fixes, 2 characterizations | ✅ **wired (L-006)** — `ollama`, 25 actions, all with real state deltas after the core `type_text` fix, 0 violations | not tracked in UGT |
| DDD | ✅ R1 11/11, R2 26/26 | ✅ R3 32/32 (re-run), zero findings | 2 wire-only defects, 2 self-corrections | ✅ **wired (L-002)** — new `legal_action` mode, `ollama`, 25 actions, live HP deltas, 0 violations | not tracked in UGT |
| Nexus Dominion | ✅ R1 12/12, R2 17/17 | ✅ R3 43/43, zero findings | 10 findings, 1 CRITICAL (ND-3) | ✅ **wired (L-003)** — `legal_action` mode (fixed 0–17 order menu, no native legal-list), `ollama`, 22 actions, 18 with real deltas | ⚠️ human UAT U-110 **failed**; ND-3 likely a root cause, retest recommended |
| Pond | ✅ R1 18/18, R2 45/45 | ✅ R3 11/11, zero findings | 1 CRITICAL (PC-5), 1 data-destroying bug (PC-2), 17 named findings total | ✅ **wired (L-004), macro-layer only** — LLM consulted at level-up mutation choices only, combat auto-driven by the existing R1 heuristic; `ollama`, 7 decisions across 9 runs | ⚠️ needed for tongue feel (PC-10) + accessibility, explicitly flagged as separate from the ladder |

**Important caveat on every ✅ above except SpacerQuest's:** these are `ollama`-validated wiring smoke tests
(20–30 actions), not balance verdicts. None of the five newly-wired games has had a real Anthropic-funded
balance campaign yet — that stays credit-gated (see Roadmap).

---

## Improvements made to UGT itself

- **`RealClientAdapter` rebuilt transport-only** (SpacerQuest, 2026-07-05) — the founding architectural fix;
  every adapter since has inherited the "no game logic" discipline from this decision.
- **Exploit-hunter tier built** (`ugt/core/exploit_hunter.py`, 2026-07-05) and the LLM playtester wired to a
  real server with run isolation, invariants, and a contradiction detector added across several fix passes
  during the SpacerQuest Gate-B/Gate-C work (2026-07-05–06). These fixes predate every other game's use of the
  tier, so tarot-war/NEXUS/DDD/nexus-dominion/pond will all get the *already-improved* playtester on their
  first run — there is nothing to retest here, only a first run pending.
- **Trial-ladder scaffold extracted** to `ugt/core/trial.py` (commit `74eee8e`, 2026-07-09) — the one true
  core refactor. Explicitly validated by an exact NEXUS re-run (byte-identical pass counts before/after). No
  commit has touched `trial.py` or `exploit_hunter.py` since — it has been stable across DDD, Nexus Dominion,
  and Pond.
- **One false start, corrected same-day**: `DDDSubprocessAdapter` was added directly to `ugt/adapters/`, then
  reverted the same day as "wrong paradigm, wrong repo" and rebuilt correctly as a per-integration harness
  adapter (`ddd_harness.py`) — the mistake was caught before it shipped into a result, not after.
  `NexusDominionHarnessAdapter` and `PondHarnessAdapter` both then followed the corrected pattern cleanly.
- **DDD R3 seed stability + `.env` wiring for the playtest tier** (commit `9ecd139`, 2026-07-17).
- **`"legal_action"` playtest schema + adapter-instance entry point** (L-002, 2026-07-21) — the structured-state
  drive mode DDD/Nexus Dominion/Pond needed, added without touching the existing browser/simulation/real_server
  dispatch branch (verified unaffected via an `examples/mock-game` smoke re-run).
- **`type_text` state-delta fix** (L-006, 2026-07-21) — `playtest_game()`'s main loop now reassigns
  `current_state` after a `type_text` action instead of silently discarding the adapter's return value. This is
  a correctness fix to code every browser/real-server playtest run shares, not a NEXUS-specific patch — see the
  chronological entry above for what it retroactively explains in SpacerQuest's own historical logs.

## Recommendation: what should be retested

The one shared-core refactor from the prior review (`trial.py` extraction) was already validated the right
way, by an exact re-run, and nothing has touched that shared code since. Today's push closes out two of the
four targeted recommendations from that review and surfaces one new one:

1. ~~Audit Warzones' and Tarot-War's R3 scripts for silently-vacuous checks~~ — **DONE (L-001, 2026-07-21)**.
   Found and fixed one real instance (an empty-trajectory vacuous-pass in both games' determinism checks),
   with committed negative-case regression scripts. Both games also got a `RESULTS.md`/`HANDOFF.md` for the
   first time.
2. **Re-run Nexus Dominion's human UAT (U-110) — still open.** ND-3 (empty Cosmic Order tiers, empire inert
   for 10 cycles) is fixed upstream and was flagged as a likely root cause of that UAT's failure, but an
   engine/LLM trial still cannot sign off UAT itself — that needs an actual human retest.
3. **No retest needed for SpacerQuest (old)** — archived, the game is being redesigned, unchanged from before.
4. ~~When credits return, treat the first LLM playtest run per game as new coverage~~ — **now literally true**:
   tarot-war, NEXUS, DDD, and nexus-dominion each got their first-ever LLM-driven run today (via `ollama`),
   and Pond got its first macro-layer run. There is no prior baseline for any of them to reconcile against.
5. **NEW: audit whether SpacerQuest Gate-C's `type_text`-driven turns hold up, now that the core bug is fixed.**
   The surviving campaign logs show exactly 3 "accept salvage weapon enhancement" turns with a
   silently-empty `state_delta` — real fallout from the bug L-006 fixed, caught after the fact rather than
   during the campaign. Gate-C's 7 ranked findings don't appear to depend on these specific turns (they're a
   different mechanic — salvage installs, not the fuel-gate/cargo-scoring findings the verdict rests on), but
   *whether the salvage-enhancement mechanic itself works as the game intends* was never actually verified —
   the tooling was blind on exactly the turns that would show it. This is a small, targeted, evidence-grounded
   follow-up (drive a few salvage-install turns against the live server and confirm the stat change now
   registers), not a reason to distrust the whole verdict.

## Where the LLM tier stands now

**Five of seven in-scope games now have a working, `ollama`-validated LLM playtest path**: tarot-war, NEXUS,
DDD, nexus-dominion, and pond (macro-layer). SpacerQuest (old) remains the only game with a *completed balance
verdict* (Gate-C) — the five new wirings are smoke-tested integration proofs (20–30 actions, 0 bugs each), not
balance campaigns. Warzones remains unwired, deliberately: it's under active development and the user asked
to hold off testing it for a few days rather than test a moving target.

What's still blocking a *paid* balance verdict on any of the five newly-wired games:

- **Anthropic API credits ran out mid-campaign on 2026-07-06** and nothing Anthropic-funded has run since;
  every wiring task today was deliberately validated against the free local `ollama` provider instead so this
  wasn't a blocker for the coding work itself, but it's still the gate on a real verdict.
- **The structured-JSON drive mode blocker is resolved** (L-002) — this was the other half of what was keeping
  DDD/Nexus Dominion/Pond off the tier, and it's now built and proven on all three.

## Roadmap ahead

1. **Top up Anthropic API credits**, then run real balance campaigns against tarot-war, NEXUS, DDD, nexus-
   dominion, and pond — five games' worth of first-ever balance verdicts are now just a credit top-up away.
2. **The new L-002 follow-up**: drive a few live salvage-enhancement turns against SpacerQuest to confirm the
   stat change registers now that the `type_text` delta bug is fixed (recommendation 5 above).
3. **Re-run Nexus Dominion's human UAT (U-110)** now that ND-3 is fixed upstream.
4. **Wire Warzones once its active-dev phase settles** — same shape as tarot-war's L-005 (browser engine,
   already supported, no new drive mode needed); deliberately not started yet per the user.
5. **Formalize human/frontend UAT as an explicit fourth doorway**, not an ad hoc note. It has only been
   tracked at all for the two most recent games (Nexus Dominion, Pond), and in both cases it caught things —
   visual readability, onboarding, animation feel, accessibility — that no engine-level tier can see by
   construction. Every future integration's `HANDOFF.md` should carry a UAT status line the same way it
   already carries ladder status.
6. **Game #8 candidate: `overlord`.** The last portfolio re-ranking (2026-07-09) shortlisted overlord ahead of
   what were then DDD/nexus-dominion — both of those are now done, and pond was added from a later pass, so
   overlord is the one remaining named candidate never onboarded. Worth confirming this is still the right
   pick before starting, since the portfolio hasn't been re-surveyed since pond was added.
7. **Framework backlog, revisit-when-blocking items** (unchanged priority, still valid): a config-driven CLI
   path for the trial ladder (arguably due for a look now that 7 integrations all hand-roll their own ladder
   scripts, and L-002 added an *adapter-instance* entry point specifically to sidestep this rather than solve
   it), a browser feature-map/screen-detection story for `ugt verify`, and a desktop (`pyautogui`/computer-use)
   adapter for non-browser, non-terminal games beyond what subprocess harnesses can cover.
