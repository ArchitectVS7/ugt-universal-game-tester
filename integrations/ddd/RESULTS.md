# DDD × UGT — results log

Commit-traceable record of every ladder round run against the real DDD engine over
the harness wire. A round is only "green" if it was **run live** and printed its own
`MET — n/n` footer; nothing here is inferred.

Game: `/Users/vs7/Dev/Games/DDD`, branch `feat/d16-type-triangle`.
Driver: `ugt/adapters/ddd_harness.py::DddHarnessAdapter` → `packages/harness/bin/harness.mjs`.

## Rounds

| Round | Date | Script | Result (live) | Findings | UGT commit | DDD commit |
|---|---|---|---|---|---|---|
| Spike | 2026-07-12 | `spike_ddd.py` | **10/10** raw-protocol | — | `00aaa33` | `61125b64` |
| Smoke | 2026-07-12 | `smoke_ddd_adapter.py` | **5/5** BaseAdapter contract | — | `00aaa33` | `61125b64` |
| R1 | 2026-07-12 | `verify_round1.py` | **11/11** — one full match to WIN/KNOCKOUT (turn 11, 24 plies), sweep clean both runs, byte-identical same-seed replay, harness self-replay verified | — | `00aaa33` | `61125b64` |
| R2 | 2026-07-12 | `verify_round2.py` | **26/26** — 12-match corpus, 348 plies: 4 wave configs × 2 formats × 4 decks (mirrors + crosses); 4 terminal arms; **36/36 cards played**; 19 `CARD_RETURNED` w/ zero-firing control; D16 differential (+4 exactly); D2 in all 20 combats; both determinism oracles | — | `00aaa33` | `61125b64` |
| R3 | 2026-07-12 | `verify_round3.py` | **31/31** — ExploitHunter 8 ep × 60 steps, full 13-id vocabulary, **zero findings**; 9 RulesError arms provoked, 14/14 probes state-inert; fog-of-war clean; same-seed episode-0 replay byte-identical | 1 characterization (D-C1) | `9ff38b1` | `61125b64` |

**Prior run superseded.** An earlier R1 (UGT `61d3c6d`, 2026-07-11) reported 11/11 —
but against the **wrong game**. See D-F2 below. Its hashes and its 44-ply/turn-21
match shape are void; the re-baselined match resolves in 24 plies / turn 11.

## Re-run vs DDD `0eb0df83` (2026-07-12, evening — T6.0 instruments + T6.5 economy + D17)

DDD moved three commits past the ladder baseline (`fe493a4a`, `7a246d74` "T6.0: Fix the
balance instruments", `0eb0df83` "playability fixes"): the Focus economy was re-priced
to bind (costs now 0–4), **D17 re-ratified `TYPE_ADVANTAGE_POWER` 4 → 5**, Chaos
Master's +2 Focus payoff was zeroed, and the sim/tier-1 random choosers now fill
targets. The full ladder was re-run against it:

| Round | Result (live) | Notes |
|---|---|---|
| Spike | **10/10** | wire contract unchanged |
| Smoke | **5/5** | |
| R1 | **11/11** | match shape moved (WIN/KNOCKOUT turn 14 / 30 plies — economy re-price); sweep clean, determinism byte-identical |
| R2 | **26/26** | after re-pinning the D16 differential to D17's ratified **+5** (first run correctly went red at the stale +4: `power 4->9 (+5, expected +4)` — the pin did its job, then was moved to the newly ratified constant, not weakened); 12 matches / 344 plies, 36/36 cards, 23 `CARD_RETURNED` w/ zero control |
| R3 | **32/32** — zero findings | **`INSUFFICIENT_FOCUS` provoked for the first time** (10th refusal arm, 15/15 probes state-inert) — the economy now BINDS over the wire; hunt 8 ep × 165 steps, 51 combats, 26 returns, fog-of-war clean, episode-0 replay byte-identical |

Two artifacts of this re-run, both in the tester, both fixed here:
1. **Stale pin:** `verify_round2.py` hard-coded `TYPE_ADVANTAGE_POWER = 4`; D17
   re-ratified 5. Updated with a D17 citation.
2. **Tester defect (stitching):** `verify_round3.py`'s INSUFFICIENT_FOCUS seed search
   could find an unaffordable-card state N plies deep, but the battery `reset()` to the
   seed and probed only **turn 1** — so the probe silently never ran and the report
   printed the *opposite* of the measurement ("zero cards ever unaffordable") using the
   search's own counter. Invisible pre-T6.5 (nothing was ever unaffordable anywhere);
   exposed the moment the economy bound. Fixed: the battery re-walks to the found
   depth, and a found-but-not-reproduced state is now a **failing check**, not a silent
   skip. D-C1 is **closed** by this run — see below.

## Game fixes (each pinned by a test in DDD's own suite)

### D-F1 · `legalTargets` was unreachable over the wire — graveyard cards were inert
**Fixed:** DDD `61125b64` — new `targets` op on the harness protocol.
**Pinned by:** `packages/harness/src/harness.test.ts` ("targets op — graveyard targets
are reachable over the wire", 5 tests) + `bin/stdio-smoke.mjs` (real subprocess wire,
asserts a `CARD_RETURNED` actually fires).

`legalActions` deliberately enumerates every action with `targets: []` (engine D-A:
choosing zero targets is legal, so the base move is legal; richer sets are enumerated
on demand via `legalTargets`). But `legalTargets` was exported from the engine and
**never exposed over the protocol**. A stdio client could therefore *play* a
graveyard-targeting card but never *fill* it — the effect was permanently inert.

That is **7 of `sw_competitive`'s 40 cards**: `sw_nest_builder` ×3,
`sw_adaptation_chamber` ×2, `sw_endless_tide`, `sw_deep_emergence`. `apps/play`
escaped it only because it calls `dispatch()` in-process. UGT's only door is the
wire, so the mechanic was invisible to it — and the 2026-07-11 R1 run played every
one of those cards blank without noticing.

This is the same class as DDD's own T6.0 finding ("the balance gate had been
measuring a game nobody plays"). The wire can now express targets;
**`@ddd/ai` and `@ddd/sim` still cannot** — see D-C2.

### D-F2 · `create` accepted a `MatchConfig` that `replay` would refuse
**Fixed:** DDD `61125b64` — `create` now validates with the same predicate `replay`
uses (`validateMatchConfig`, exported from the engine).
**Pinned by:** `harness.test.ts` ("create — structural MatchConfig validation shares
one predicate with replay", 3 tests) + `stdio-smoke.mjs` (partial config refused).

`parse.ts` cast `config` to `MatchConfig` after an `isPlainObject` check and nothing
else. So a config omitting a wave key was **accepted**: the key read as `undefined` →
falsy → the wave was silently OFF and the harness played a *different game* than the
caller asked for. Meanwhile `replay` **refused** that same config
(`MALFORMED_RECORD: missing key "typeTriangle"`). A match could be created that could
never be verified — the engine's own determinism oracle silently disabled.

The validator already existed (`validateConfig`, private behind `validateMatchRecord`);
it simply was not run at the door. Both doors now share it and cannot drift — the
`capturesTurnHash` discipline.

**This was not hypothetical.** UGT's `ugt.config.yaml` predated D16 and named only two
of the three wave keys, so its entire 2026-07-11 R1 run certified a game with the type
triangle **off** — the one mechanic D16 exists to add — and never ran combo chains or
Rare predictions at all (`chainsPredictions: false`). Found by re-running the spike.

## Characterizations (by design — recorded, not defects)

### D-C1 · ~~The Focus economy never binds~~ **CLOSED (2026-07-12, DDD T6.5/D17)**
**Closed by the re-run vs DDD `0eb0df83`:** the pack was re-priced (costs 0–4, six
cost-4 cards), the seed search found an unaffordable held card within one seed, and
the battery provoked a real **`INSUFFICIENT_FOCUS`** refusal, state-inert, over the
wire (R3 32/32). The economy now binds. Whether it binds *enough* to make cost an
interesting decision is the LLM-playtest tier's question (T8.2), not R3's.
Original record below, kept for the method trail:

Measured by `verify_round3.py`: across **26 probed turn-states over 20 seeds, zero
cards were ever unaffordable**. `STARTING_FOCUS` is 1, but resource regen plus
Balanced-stance regen puts a seat at focus **3 on turn 1** and at the cap (**5**) by
turn 4 — while the most expensive card in the entire 36-card pack costs **3**.

Consequences: cost is never a real decision, and the `INSUFFICIENT_FOCUS` rules arm is
~~unreachable in normal play (dead code against shipped content)~~.

**Caveat (2026-07-12, DDD-side re-measurement):** the 26-state sample was too small
for the "unreachable/dead code" claim. Over ~1,700 live selection states per pairing
(60 games, skilled play), **6–10% of states contain at least one unaffordable card**
— the arm is *rare*, not dead. The headline conclusion stands and is confirmed at
scale: **90–94% of states can afford the entire hand and 40–51% sit at the focus
cap**, so cost is not a decision.

This is DDD's own open **T6.5** ("The Focus economy — make cost a real decision"), so
it is ratified design debt, not a robustness defect. R3 records it and does **not**
fail on it.

### D-C2 · ~~The in-process instruments still never fill targets~~ **REFUTED IN PART (2026-07-12, DDD-side re-measurement)**
Original claim: `@ddd/ai` and `@ddd/sim` never call `legalTargets` (verified: zero
references), so even after D-F1 the AI tiers and the Monte-Carlo balance sim still
play all four graveyard-return cards inert, and the AI-ladder numbers in CI are
measured on a Swarm deck with 7 dead cards.

**Correction.** The "zero references" verification was wrong — a grep at DDD HEAD
(`e89e4abe`, same commit range this round ran against) finds `legalTargets` called at
`packages/ai/src/eval/candidate.ts:45` (`chooseTargets`), present since T5.1/T5.2 and
used by BOTH tier 2 (greedy) and tier 3 (one-ply). Confirmed empirically (60
games/pairing, real pack): greedy filled targets on **131/136** grave-card plays
(242 `CARD_RETURNED`), one-ply **140/144** (211). **The AI-ladder CI numbers are
measured with the subject tier fully armed and stand.**

What the claim got right: `@ddd/sim`'s `randomPolicy` and tier-1
`uniformRandomStrategy` never fill targets (**0/121** grave-card plays, 0 returns), so
the random-vs-random *balance gate* does blank 7 of `sw_competitive`'s 40 cards —
that half remains owned by DDD **T6.0** (b)/(c), and was deliberately not fixed here
because it moves published balance numbers.
*(Since resolved upstream: DDD `7a246d74` (T6.0 DONE) arms both random choosers via
`legalTargets` and re-pins the ladder floors; the honest skilled-play matchup —
Blitzblade ~36% — is owned by DDD T6.2.)*

**Method lesson for UGT:** a static-reference claim ("zero references, verified") must
be pinned by the actual search command + commit hash in the results log, exactly as
dynamic claims are pinned by scripts. This one wasn't, and it shipped a false finding
into DDD's task ledger (since corrected in DDD `TASKS.md` T6.0(c)).

### D-C3 · Some RulesError arms are shadowed by earlier checks
The battery provokes 10 of the 14 arms (`INSUFFICIENT_FOCUS` joined in the
`0eb0df83` re-run — see D-C1 closure). The rest are not unreachable bugs — they are
*shadowed* by validation ordering, which is correct behavior:
- phase is checked before card ownership → a bad commit in MULLIGAN returns
  `WRONG_PHASE`, not `CARD_NOT_IN_HAND` (both reachable; just probe in the right phase);
- shape is checked before semantics → a non-`CardType` prediction returns
  `MALFORMED_ACTION`, not `INVALID_PREDICTION`.
`NOT_YOUR_ACTION` / `UNSUPPORTED_ACTION` remain defensive arms with no wire route found.

## How to re-run

No server to start — the adapter spawns the harness itself. Needs node ≥ 24 and DDD
deps installed.

```bash
# from the UGT repo root
python3 integrations/ddd/spike_ddd.py           # 10/10 raw protocol (incl. the targets op)
python3 integrations/ddd/smoke_ddd_adapter.py   #  5/5 BaseAdapter contract
python3 integrations/ddd/verify_round1.py       # 11/11 one match + determinism
python3 integrations/ddd/verify_round2.py       # 26/26 full content spine
python3 integrations/ddd/verify_round3.py       # 32/32 ExploitHunter + refusal battery

# DDD's own gate (from /Users/vs7/Dev/Games/DDD)
pnpm typecheck && pnpm lint && pnpm test && pnpm smoke && pnpm bench
node apps/ladder/bin/ladder.mjs
```

Every script is fail-closed (`GateRunner.finish` returns 0 only when passed == total)
and prints `[FINDING]` lines inline. A failed check is DATA: fix it upstream in DDD
with a pinning test and re-run — never weaken it here.

## L-007: LLM playtest tier wired + run (2026-07-21)

`integrations/ddd/playtest_ddd.py` drives DDD through the L-002 direct-adapter entry
point (`playtest_game_with_adapter`) — `DddHarnessAdapter` has no
`press_key`/`get_terminal_text` (the harness is structured JSON, not a terminal), so
this uses `action_mode="legal_action"`: the LLM reads the adapter's own structured
state plus its live legal-action list and picks one legal action per step by index.
Same loop as every other engine (state-delta assertion, bug-report shape, invariant
suite) — this only adds the input channel. The invariant suite handed to the loop is
the exact one R3 hands the ExploitHunter (`invariants.build_suite().to_hunter_invariants()`).

**Bug found + fixed in UGT core (not DDD):** the first probe run crashed —
`ugt/core/playtester.py:552` (the display-only-verb check added same-day in
commit `80d4af8`) called `value.split(None, 1)` unconditionally, assuming `value` is
always a string. In `legal_action` mode `value` is the LLM's chosen index, an `int`
— `AttributeError: 'int' object has no attribute 'split'` killed every legal-action
playtest run outright (DDD, and would have hit nexus-dominion too if wired).
Fixed by guarding on `isinstance(value, str)`:
```python
_verb = value.split(None, 1)[0] if isinstance(value, str) and value else value
```
`display_only_verbs` remains meaningless for `legal_action` mode (there is no verb to
match), so the guard is a correct no-op there, not a workaround.

**Live ollama run (`--provider ollama --model gemma4:26b --max-actions 40`):**
a 5-action probe first confirmed the channel (5/5 steps with a genuine state delta),
then the full run: **PLAYTEST MET** — `actions_taken=40`, **all 40 steps produced a
state delta**, invariant suite ran with **0 violations**, **0 bugs flagged**, **0
novel behaviors**. One full match played to termination mid-run (episode reset once,
step 38, P1 at 1 HP) and a second match began before the action budget ran out
(cumulative `p0_hp_delta=-28`, `p1_hp_delta=-30` across both matches). gemma4:26b
mostly picked index 0 (frequently the "commit next card"/lowest-index legal option)
with occasional stance/aggression-driven deviations (e.g. step 14 "AGGRESSIVE stance",
step 25 "P0 at 1 HP, P1 has 18 HP — play aggressively"), showing HP-state-aware
reasoning rather than uniform-random selection. Report at
`integrations/ddd/results/playtest-report.json` (gitignored via root `results/`).

This closes DDD's T8.2 wiring and gives D-C1 (Focus economy binding — whether cost is
an *interesting* decision, not just a reachable constraint) its first LLM-observed
data point: no stuck/refused-action pattern emerged over 40 steps, though a
`max-actions 40` local-model run is a smoke test of the channel, not a balance
verdict — a longer run (or `--provider anthropic`) is the next lever if a deeper
balance read is wanted.

## L-008: First multi-run LLM balance batch (2026-07-21) — 92.6% seat-0 win rate, CONFOUNDED with seat/turn-order, not yet comparable to T6.2's 36%

> ⚠️ **Superseded caveat (L-009, same day):** the seat/turn-order confound below is
> real but UNDERSTATES the problem. The batch also measured **blind play** (the
> prompt never carried any card identity) and **sw's targeted cards were played
> blank** (`apply_legal` never filled targets). The 92.6% figure is a
> blind-policy/single-cell/handicapped-sw artifact and is not usable for balance
> even after seat-swap pooling — read L-009 before acting on anything in this
> section.

`playtest_ddd.py` gained `--runs N` (threads straight through to the existing
`playtest_game_with_adapter(..., runs=N)` / `_aggregate_runs` machinery in
`ugt/core/playtester.py` — no new aggregation code needed, this is exactly
PLAYTEST-DESIGN.md's "N runs with confidence intervals" balance tier). Each run is
an independent `adapter.reset()`; `DddHarnessAdapter.reset()` derives a fresh seed
per reset (`f"{self.seed}#{self._reset_count}"`, counter never resets across runs in
one process), so no two runs or episodes replay the same match.

New `integrations/ddd/analyze_playtest_batch.py` recovers per-episode winner/via from
the recorded `action_log`: `_compute_delta` flattens nested dicts with dotted keys,
so a match's terminal step's `state_delta` contains `resultKind: "'ONGOING' → 'WIN'"`
alongside `result.winner: "None → 0"` and `result.via: "None → 'KNOCKOUT'"` — no core
change needed, this is a read-only parse of data the loop already logs. Verified
against the existing single-run report before trusting it on the batch.

**Run: `--provider ollama --model gemma4:26b --runs 8 --max-actions 100`.** Real
duration ~9500s total (one run, #6, took 2020s vs ~570-640s for the rest — root
cause was the host machine sleeping mid-run on low battery, not a game or harness
defect; the process survived the sleep/wake cleanly). Result: **8/8 runs complete,
800/800 actions, 0 bugs flagged, 0 invariant violations, 27 completed matches** (all
27 resolved via KNOCKOUT, zero TURN_LIMIT/EXHAUSTION endings, zero soft-locks).

**Raw win rate: seat 0 (bb_competitive/Blitzblade) won 25/27 (92.6%)**, seat 1
(sw_competitive) won 2/27 (7.4%).

**This number is NOT comparable to T6.2's "Blitzblade ~36% skilled winrate" and must
not be read as "balance flipped."** `apps/ladder/bin/ladder.mjs` (read to compare)
documents that DDD's own AI-ladder gate deliberately runs a **4-cell deck×seat
design** — `{bb as P0, sw as P0, bb as P1, sw as P1}`, pooled — specifically because
an earlier non-pooled measurement ("random-vs-random gives bb_competitive ~69%") was
itself a measurement artifact, and because **seat/turn-order bias is a known,
already-instrumented confound in this engine**. `DddHarnessAdapter._pending_seat()`
always resolves seat 0 first in every MULLIGAN and SELECTION phase for the entire
match (`for s in (0, 1): if not committed...`), and `engine.decks` in
`ugt.config.yaml` fixes `bb_competitive` to seat 0 for every match — so this batch
sampled exactly ONE of the ladder's 4 cells (bb-as-P0 vs sw-as-P1) 27 times. Deck
identity and seat/first-move order are perfectly confounded in this dataset; the
92.6% figure could be real deck power, pure first-mover advantage, or both, and
there is no way to tell from this batch alone.

**What this batch DOES establish cleanly:** the multi-run channel and the win-rate
analyzer both work correctly (verified stand-alone before trusting the aggregate),
and 800 actions of real LLM-driven play produced zero bugs/invariant violations
across 27 real match completions — a clean robustness data point layered on top of
R3's exploit-hunter coverage, from a genuinely different "skilled-ish" play source.

**Next step (not yet run):** mirror batch with `engine.decks` reversed
(`["sw_competitive", "bb_competitive"]`) so bb plays seat 1 / second-mover, pool both
batches' win rates the same way the AI ladder does — that isolates deck power from
seat bias and is the actual prerequisite for any T6.2 balance verdict from this tier.
Raw data: `integrations/ddd/results/playtest-run-{1..8}.json`,
`playtest-batch-analysis.json` (all gitignored via root `results/`).

## L-009: The L-008 batch was measuring BLIND play — 3 harness defects found + fixed before any further balance batch (2026-07-21)

A test-of-the-test pass over the L-008 data and the playtest channel, prompted by
the question "is this data decisive?" Answer: no — and the seat-swap mirror batch
L-008 recommended would have burned another ~90 min measuring the wrong thing.
Three defects, all UGT-side (the game exposes everything needed; the harness
dropped it on the floor):

**D-L1 (information starvation — the big one): the LLM never saw a single card
identity.** The normalized state (`ddd_harness.py::_seat`) exposes only counts
(`handCount` etc.), and the legal list relays the engine's raw actions, which carry
only opaque `instanceId` ints. So every "choice" between cards was a blind pick
among integers — the LLM even said so mid-run (run 1 step 4 reasoning: *"the
current state shows no specific cards in hand are visible to me via the JSON"*).
The harness view carries `defId` per own-hand card the whole time; the adapter
discarded it. **Fix:** `legal_actions()` now annotates each COMMIT_SELECTION with
`_card` (its defId) and each MULLIGAN with `_hand` (the hand's defIds), stripped by
`send_raw_action` before the wire (underscore prefix = display-only convention);
`strategy-guide.md` gained a full card reference for both competitive decks
(generated from `packages/content/data/base/manifest.json`), and
`playtest.guide_char_budget` rose 2000→6000 so it isn't truncated.

**D-L2 (fog-of-war leak to the second mover):** the engine's redacted opponent
view exposes only `hasCommitted` — never card-vs-pass — and the rulebook's T3.5
audit ruling makes prediction secrecy explicit. But the adapter's god-view state
(needed by the card-conservation invariant, whose sum includes `committedCard`)
handed the always-second seat 1 `p0.committedKind: "CARD"` in every prompt.
Harmless while the LLM was blind; would corrupt the prediction game the moment it
isn't. **Fix (game-agnostic core knob):** `playtest.redact_state_fields` — dotted
paths dropped ONLY from what the LLM is shown (state JSON + recent-action delta
summaries, all three prompt builders); logs, invariants, and reports keep the full
state. DDD's config redacts `p0/p1.committedKind` + `committedCard`.

**D-L3 (playtest path replayed the L-007 wire defect): `apply_legal` sent legal
actions verbatim with `targets: []`.** The DDD harness contract
(`packages/harness/src/router.ts`: "`legalActions` always reports `targets: []`…
the `targets` op is the ONLY way a wire client can discover" eligible ids) means a
verbatim send plays every targeted card blank — exactly the "7 of 40 Swarm cards
played blank" defect L-007 got fixed upstream, this time on the UGT side. The
exploit-hunter path (`_select`) has always called `fill_targets`; the playtest path
never did, and the engine accepts empty targets silently (hence 0
`inv_no_error_on_legal` violations in L-008 while sw — always seat 1 — played its
graveyard-return package blank). **Fix:** `legal_actions()` fills targets at
enumeration time, so the LLM sees the action it is actually choosing.

**What the L-008 data still cleanly established** (from a delta-signature
reconstruction of all 800 actions): the LLM played BOTH seats identically —
seat 0 committed a card in 363/366 non-mulligan decisions, seat 1 in ~365/366,
mulligans 34/34, zero invalid indices, zero concedes — so the blowout was not an
LLM-behavior asymmetry; and the channel itself is robust (800/800 valid legal picks
from a local 26B model). The 92.6% is a real observation about *blind always-commit
play at one deck×seat cell with sw's targeted cards blanked* — i.e. about nothing a
balance verdict can use.

**Validation after the fixes:** full ladder re-run green — spike 10/10 · smoke 5/5
· R1 11/11 · R2 26/26 · R3 32/32 (R3 matters most here: `send_raw_action` is the
refusal-probe + replay channel and now strips annotation keys; the prompt-side
redaction adds no invariant regressions because the state object is untouched).
In-process prompt assertions: `_card`/`_hand` present, `committedKind`/
`committedCard` absent from the prompt while `hasCommitted` and the god-view state
survive, guide not truncated, annotated actions apply cleanly.

**Sanity run (post-fix, ollama/gemma4:26b, 24 actions): PLAYTEST MET, and the play
is now visibly card-aware** — every step's logged reasoning names real cards and
costs ("Playing bb_battle_instinct…", "sw_feeding_frenzy is a power…", "I am
playing as P1 (seat 1). I have 3 focus available"), chosen indices are varied
rather than low-index-biased, and the single match ran as an actual contest (P0
30→8 HP vs P1 30→5 at the 24-action cutoff) instead of an L-008-style blowout.
0 invariant violations, 0 bugs; one step lost to a malformed (non-JSON) local-model
reply, safely skipped by the loop. One 24-action run proves the channel, not the
balance.

## Next tier

The T6.2-oriented balance read now needs the 4-cell (or at minimum seat-swapped
2-cell) pooled batch matching
`apps/ladder/bin/ladder.mjs`'s own design — with competent, non-leaking play this
time. The L-008 numbers must not be pooled with post-L-009 batches (different
policy). DDD T6.3's conformance audit #2 remains untouched.
