# UGT Track Record — Has It Earned Its Place?

*Compiled 2026-07-21. Sources: `PLAN-FORWARD.md`, `archive/PLAN-FORWARD-spacerquest.md`, every
`integrations/<game>/{HANDOFF,RESULTS,README}.md`, `PLAYTEST-DESIGN.md`, `UGT-USER-MANUAL.md`, and git history
of `ugt/core`, `ugt/adapters`, `ugt/cli.py`, `ugt/utils`.*

## Bottom line

Eight integration efforts across seven distinct game codebases (plus one restart), three transport paradigms,
and four genres have now run through UGT. Every one of them found and fixed real, player-facing bugs in the
*game*, not just in the tester — including three CRITICAL-severity bugs a real player would have hit
immediately (SpacerQuest's free-attack fuel exploit, Nexus Dominion's inert-empire opening, Pond's
un-killable enemy). UGT also broke itself in smaller ways along the way, caught its own three false findings,
and — most reassuring — has now independently rediscovered the same failure mode (a check that silently
never runs and reports a vacuous green) in three unrelated integrations, which is exactly the kind of
"boring but real" bug class the project should be worried about missing. The one tier that has **not**
earned its keep yet is the LLM balance playtester: it has driven a verdict on exactly one game.

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
| SpacerQuest (old) | ✅ Phase 0 DoD 13/13 | ✅ Phase 1, 200 steps clean | ✅ Gate-C, 7 ranked findings | ✅ **Only game with a completed LLM balance verdict** | not tracked in UGT |
| Rimward/SpacerQuest | ✅ verify 9/9 | n/a (RL evaluate instead) | RL collapse-detector caught one invalid run | not run (RL path used instead) | not tracked in UGT |
| Warzones | ✅ R1 23/23, R2 12/12 | ✅ R3 6/6 | 2 criticals + 1 open (WZ-R3, deferred) | not run | not tracked in UGT |
| Tarot-War | ✅ R1 22/22, R2 12/12 | ✅ R3 7/7 | 8/8 findings closed | not run | not tracked in UGT |
| NEXUS | ✅ R1 25/25, R2 36/36 | ✅ R3 9/9, zero game findings | 5 fixes, 2 characterizations | not run — **explicitly deferred** | not tracked in UGT |
| DDD | ✅ R1 11/11, R2 26/26 | ✅ R3 32/32 (re-run), zero findings | 2 wire-only defects, 2 self-corrections | not run — **needs structured-JSON drive mode first** | not tracked in UGT |
| Nexus Dominion | ✅ R1 12/12, R2 17/17 | ✅ R3 43/43, zero findings | 10 findings, 1 CRITICAL (ND-3) | not run — **credit-gated** | ⚠️ human UAT U-110 **failed**; ND-3 likely a root cause, retest recommended |
| Pond | ✅ R1 18/18, R2 45/45 | ✅ R3 11/11, zero findings | 1 CRITICAL (PC-5), 1 data-destroying bug (PC-2), 17 named findings total | not run — **judged wrong granularity for real-time**, macro-layer variant proposed | ⚠️ needed for tongue feel (PC-10) + accessibility, explicitly flagged as separate from the ladder |

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

## Recommendation: what should be retested

The good news first: the one shared-core refactor (`trial.py` extraction) was already validated the right
way, by an exact re-run, and nothing has touched that shared code since — **no blanket re-run of the whole
portfolio is justified by core changes.** The recommendations below are narrower and targeted at real,
specific gaps this history surfaced:

1. **Audit Warzones' and Tarot-War's own R3/exploit-hunter scripts for silently-vacuous checks.** These two
   integrations (2026-07-06/07) were written *before* the vacuous-check failure mode was ever seen. It has
   since been independently rediscovered twice — DDD's `verify_round3.py` seed-search stitching bug and
   Pond's `HuntAdapter.step` never wiring `info["result"]` — in two unrelated, independently-written scripts.
   That is a real pattern, not a coincidence, and it means the two oldest, never-refactored ladder scripts are
   exactly the ones that have never been checked against it. This is a cheap, targeted read-through, not a
   full re-run.
2. **Re-run Nexus Dominion's human UAT (U-110).** ND-3 (empty Cosmic Order tiers, empire inert for 10 cycles)
   was flagged as a likely root cause of that UAT's failure and is now fixed upstream. The engine trial cannot
   sign off UAT itself — that requires an actual human retest, which is the recommended next action for this
   game specifically, not another engine ladder run.
3. **No retest needed for SpacerQuest (old)** — it's archived, the game itself is being redesigned, and
   re-running a ladder against code that's about to be replaced wouldn't produce actionable information.
4. **When credits return, treat the first LLM playtest run per game as new coverage, not a retest** — none of
   tarot-war/NEXUS/DDD/nexus-dominion/pond has ever had one, so there's no prior baseline to reconcile against;
   just run it.

## Where the LLM tier stands (and why it's paused)

**Only SpacerQuest (old) has ever completed an LLM playtest campaign.** Every other game — tarot-war, NEXUS,
DDD, nexus-dominion, and pond — has this tier explicitly deferred, for two compounding reasons:

- **Anthropic API credits ran out mid-campaign on 2026-07-06** and this has blocked every LLM run since; it is
  the single largest item on the framework backlog by a wide margin.
- **A structured-JSON drive mode doesn't exist yet.** `ugt playtest` currently reads text/terminal state via
  `press_key`/`get_terminal_text` — fine for a browser or a real server, but DDD, Nexus Dominion, and Pond are
  all subprocess harnesses with no terminal at all. This was scoped as a DDD-only gap in earlier planning, but
  it is now a **three-game shared blocker** and worth building once as a generic structured-state playtester
  variant rather than solving it per game.
- **Pond specifically has a third, separate reason**: real-time bullet-hell dodging was judged the wrong
  granularity for a per-action LLM loop. A macro-layer variant (LLM chooses upgrades/strategy, not
  frame-by-frame dodges) has been proposed but not built.

## Roadmap ahead

1. **Top up Anthropic API credits.** Blocking five games' worth of balance verdicts; nothing else on this list
   matters until this is unblocked.
2. **Build the structured-JSON playtest drive mode** once credits exist — benefits DDD, Nexus Dominion, and
   Pond (macro-layer) simultaneously rather than being built three times.
3. **Run the two targeted actions above**: the Warzones/Tarot-War vacuous-check audit, and Nexus Dominion's
   human UAT retest.
4. **Formalize human/frontend UAT as an explicit fourth doorway**, not an ad hoc note. It has only been
   tracked at all for the two most recent games (Nexus Dominion, Pond), and in both cases it caught things —
   visual readability, onboarding, animation feel, accessibility — that no engine-level tier can see by
   construction. Every future integration's `HANDOFF.md` should carry a UAT status line the same way it
   already carries ladder status.
5. **Game #8 candidate: `overlord`.** The last portfolio re-ranking (2026-07-09) shortlisted overlord ahead of
   what were then DDD/nexus-dominion — both of those are now done, and pond was added from a later pass, so
   overlord is the one remaining named candidate never onboarded. Worth confirming this is still the right
   pick before starting, since the portfolio hasn't been re-surveyed since pond was added.
6. **Framework backlog, revisit-when-blocking items** (unchanged priority, still valid): a config-driven CLI
   path for the trial ladder (arguably due for a look now that 7 integrations all hand-roll their own ladder
   scripts), a browser feature-map/screen-detection story for `ugt verify`, and a desktop
   (`pyautogui`/computer-use) adapter for non-browser, non-terminal games beyond what subprocess harnesses can
   cover.
