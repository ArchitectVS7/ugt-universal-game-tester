# After-Action Report — Has UGT Earned Its Place As a Product?

**Compiled:** 2026-07-31. **Scope:** cross-repo evidence pass across all eight known integration efforts (SpacerQuest ×2 eras, DDD, Iron-Ashes, nexus-dominion, tarot-war, warzones, the-pond, worldbreaker) plus this repo's own git history and internal docs (`Dev/UGT-TRACK-RECORD.md`, `LESSONS.md`, `PROTOCOL.md` analogs in each integration). This report answers a narrower question than `Dev/UGT-TRACK-RECORD.md` does: not "did UGT find real bugs" (yes — see §1), but "was building and maintaining UGT as a shared, installed, cross-repo *tool* the efficient way to get them."

**Bottom line:** the **methodology is validated** — long-horizon simulated play through a real adapter boundary, checked against declared invariants, found genuine, otherwise-invisible bugs in four different genres. The **product strategy is not** — every integration still required a bespoke hand-written bridge, the shared runtime accumulated its own defects that silently invalidated other games' results, and the protocol between UGT and any one game drifted out of sync with that game's own content without anything catching it. The thing that generalized was the *idea*. The thing that cost the most was maintaining a second, shared, versioned codebase that seven different games all had to stay compatible with at once.

---

## 1. What worked: the pattern found real bugs, across real genres

This is not a one-repo fluke. Distinct, otherwise-hard-to-catch bugs were found in every genre attempted:

- **SpacerQuest (Rimward, T-1604a):** a captain at 0 credits with a full undeliverable hold had no advertised income verb — invisible to unit tests, found by playing 385 consecutive simulated days and watching debt compound to 38,055,255. Also: two die-spent-before-check ordering bugs (Travel/fuel, Shipyard) that only manifest in a real action sequence, not in isolation.
- **SpacerQuest (Museum Edition, founding integration):** a fuel-gate exploit (attack at full power with no fuel — 35 wins/1 loss pre-fix) and a cargo-scoring formula that had silently dropped its distance/battle terms.
- **the-pond (real-time/Godot):** the single most player-visible bug in UGT's history — the tongue-attack hitbox was tip-only, making enemies functionally unkillable in normal play.
- **warzones:** pirate encounters destroyed every run, and the commodity economy rendered zero rows in the live browser build — two fully dead systems, both green in whatever tests existed before.
- **tarot-war:** a war-duplication scoring bug.
- **nexus-dominion:** empty Cosmic Order tiers left the empire inert for the opening 10 cycles.
- **worldbreaker (most recent, 2026-07-28):** a terminal command tokenizer silently swallowed leading flags, causing an LLM pilot to loop 250 of 300 turns on a dead command — a bug that would read as "the AI is bad at the game" if you weren't watching closely enough to see it was actually "the game is silently ignoring input."
- **DDD:** proved the harness's core thesis directly — 7 of 40 cards played blank over the wire despite 1,251/1,251 green in-process tests. This is the cleanest statement of why in-process test suites are insufficient: the wire is a real boundary bugs hide behind, and only playing through it finds them.

Every one of these is the class of bug the user built UGT to catch in the first place: real, structural, and invisible to a green in-process test suite. On that count, the bet paid off.

## 2. What it cost: a second codebase, maintained in parallel with seven others

- **242 commits, 2026-07-05 → 2026-07-27** (3.5 weeks of concentrated build time) on the UGT repo itself, plus large standing docs (`LESSONS.md` 62.8 KB, `TASKS.md` 78.2 KB, `UGT-USER-MANUAL.md` 31.5 KB) that all had to stay current as the core evolved.
- **Every integration still required bespoke, hand-written, per-game code** — `harness/ugt-harness.mjs` (Iron-Ashes, nexus-dominion, warzones), `src/ugt-hooks.ts` (tarot-war, warzones), `tests/harness/ugt_harness.gd` (the-pond, a first-of-its-kind real-time/Godot bridge), `rimward_gym_bridge.py` + `protocol-stdio.ts` (SpacerQuest). "Universal" never meant zero per-game work; it meant re-deriving the same adapter shape in a new language/engine every time, which is exactly the "working all over again" the user felt switching genres.
- **The shared runtime had its own defects, and they cost other games' results, not just SpacerQuest's:**
  - `verify_game` silently discarded every feature's before/after/delta evidence (a comparison bug: `if coverage[fid] not in details` was always true) — meaning *every* verify run before this was caught could have been reporting false confidence.
  - The idle-action picker defaulted to a state-key shape borrowed from one game (Warzones), silently defaulting to `wait` and making slow-precondition features permanently unreachable in any other game, regardless of `--max-turns`, until this was noticed via SpacerQuest.
  - A `type_text` branch in the shared playtester core discarded state after every use — found via an unrelated audit two weeks after it started, and retroactively invalidated 3 of ~3,150 already-logged SpacerQuest actions. This affected every browser-driven integration using that code path, not just one game.
  - Net effect: a bug found and fixed *because of* game A's campaign could mean game B's *prior* campaign result was quietly wrong the whole time. A shared runtime turns one game's dogfooding into every other game's silent risk.
- **Protocol drift is real and was silent.** SpacerQuest shipped two new player verbs (`Reroll`, `Crew/dismiss`) that had zero UGT-side coverage for roughly two weeks — nobody updated the sibling repo's action vocabulary, and nothing flagged the gap. No campaign run in that window would have said anything about those verbs, and no CI anywhere caught it; it only surfaced because someone happened to diff the id list by hand during T-1604a.
- **Cadence was bursty, not continuous.** Only one full campaign exists against SpacerQuest's current codebase. A prior 71,107-action batch (2026-07-17) had to be discarded entirely and declared permanently unpoolable once two information-integrity bugs were fixed in between. There's a documented two-week dead gap (2026-07-12 → 2026-07-26) with no UGT activity on SpacerQuest at all. This is occasional-audit cadence, not CI.
- **The most ambitious promised capability — paid LLM-driven strategic/balance verdicts — has completed exactly once**, on an archived game line (Museum Edition). Every other integration's LLM tier is a 20–30 action wiring smoke test, explicitly caveated as such in `Dev/UGT-TRACK-RECORD.md`. Anthropic usage caps have independently blocked paid runs on at least five games as of the last self-audit.

## 3. The actual lesson: methodology transfers, runtime dependency doesn't

Look at what *didn't* need re-deriving across genres: the shape of the adapter contract (`connect/reset/step/close`), the ladder (spike → smoke → R1 playability → R2 full spine → R3 invariant-fuzzer), the rule that an unmapped action must raise `NotImplementedError` rather than fabricate behavior, and the discipline of checking declared invariants after every step rather than trusting a single pass/fail. Those are ideas, expressible as a spec and a worked example, and they held up unchanged from a turn-based space trader to a real-time Godot platformer to a terminal roguelike.

Now look at what *did* need re-deriving every time, and what broke when it was shared instead of owned: the transport-specific bridge code (impossible to share — every game's process/wire/engine shape differs), and the runtime package that tried to be the one thing every game imports and stays version-synced against (this is exactly what accumulated meta-bugs, went stale against a specific game's content without anyone noticing, and turned any one game's dogfooding into every other game's silent risk).

This maps directly onto a known failure mode: a shared dependency across independent, differently-paced projects either becomes everyone's bottleneck (wait for the shared thing to be fixed/released) or drifts silently out of sync with whichever project isn't actively driving it (the Reroll/Crew-dismiss gap, the type_text bug sitting undetected for two weeks). Seven codebases with different languages, engines, and release cadences is close to the worst case for "one shared runtime dependency," and the evidence bears that out.

## 4. Proposal: UGT becomes a framework and a training document, not a runtime dependency

Stop building toward "one installed package every game imports." Instead:

1. **Keep, and sharpen, the methodology document.** `LESSONS.md`'s lettered-rule registry (M1: the adapter never fabricates behavior; the ladder sequence; the invariant-checking discipline) is the actual asset. Turn it into a precise, implementation-agnostic spec good enough that a competent engineer (or an agent) can build a compliant harness *inside* a target repo from the doc alone, without importing anything from this repo at runtime.
2. **Replace the installed core (`ugt_tester`) with a small library of copy-paste starter scripts**, one per common transport shape already proven out here: subprocess JSON-lines (SpacerQuest's shape), browser/Playwright, a Godot/GDScript shim (the-pond's shape), and a generic HTTP/stdio shape. Each ships as a short, readable reference implementation a game vendors into its own repo and owns — not a dependency it tracks.
3. **Keep the existing demo games (`_dice`, `_escape-room`, `_sokoban`) as teaching examples**, not infrastructure — they're already the right shape for this: small, illustrative, self-contained.
4. **Drop the shared invariant-fuzzer and playtester runtime as live, imported code.** The pattern (walk N steps, check M invariants, log state deltas, an LLM picks the next action from the real legal-actions list) is what should ship, expressed as a template a game's own harness implements natively, in its own language, against its own state shape. This is the direct fix for the `verify_game` and `type_text` class of bug: a defect in a game's own in-repo harness only ever costs that game, and whoever owns the game's content changes is the same person who'd notice the harness needs updating — no more silent drift between two repos on two different people's cadences.
5. **The cross-repo value this repo should keep producing is the track record and lesson registry itself** — `UGT-TRACK-RECORD.md` and `LESSONS.md`, kept current as a knowledge base other integrations (and future ones) read before building their own harness, not as a change log for a shared runtime.

This does not throw away three and a half weeks of work. Every real finding in §1 came from the *methodology*, and every integration effort that struggled did so on the *shared-runtime* parts, not the ladder or the invariant discipline. Keeping the spec and dropping the shared package is keeping exactly the part that was earning its keep.

## 5. Suggested next steps for this repo

- Fold `UGT-USER-MANUAL.md` + the relevant `LESSONS.md` sections into a single **adapter spec** document, written for "implement this in your own repo" rather than "install and call this package."
- Extract the four transport starter scripts named in §4.2 out of the existing per-game `integrations/*/` bridges (they already exist in working form — Iron-Ashes's `ugt-harness.mjs`, the-pond's `ugt_harness.gd`, SpacerQuest's `rimward_gym_bridge.py`, and a generic HTTP shape) into a `templates/` directory, stripped of game-specific logic.
- Retire the `ugt_tester` installable package's ambition to be a live dependency; keep its code as the reference implementation the templates were extracted from.
- Leave `Dev/UGT-TRACK-RECORD.md` and `LESSONS.md` as living documents — they are the part of this project that has actually proven durable.
