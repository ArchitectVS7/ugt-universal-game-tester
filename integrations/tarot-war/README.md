# Tarot-war integration (real client, browser adapter)

Drives the **real** tarot-war React game (`../tarot-war`) in a headless browser
via `PlaywrightAdapter` and the UGT hooks installed in the game at
`src/ugt-hooks.ts` (`window.__GET_STATE__` / `__SEND_ACTION__` / `__RESET_GAME__(seed)`).

The hooks are **transport only**: they call the exact `useGameState` callbacks the
UI buttons receive (play/reset/difficulty/mode) — never a re-implementation of the
reducer (the sim_bridge / warzones-ml lesson). The seeded-RNG seam
(`src/utils/seededRandom.ts`, routed through `shuffleArray`, the war tie-breakers,
and the discard-picking card effects) was added upstream as a real game fix and is
pinned by the game's own `src/__tests__/utils/seededRandom.test.ts`.

## Run

```bash
# 1. Start the real game (Vite dev server on :5173)
cd ../tarot-war && npm run dev

# 2. Verify the LISTEN PID on :5173 is YOUR vite (stale-server lesson):
lsof -nP -iTCP:5173 -sTCP:LISTEN

# 3. From the UGT repo root:
python3 integrations/tarot-war/verify_round1.py   # [seed] optional, default 20260707
python3 integrations/tarot-war/verify_round2.py   # [base_seed] optional, default 20260708
```

## Test ladder (test → fix upstream → re-test)

| Round | Script | Gate |
|---|---|---|
| 1 | `verify_round1.py` | **PASSED 22/22 (2026-07-07, twice back-to-back).** One full playable loop: seeded reset, info accessibility, setup pickers through real handlers, player turn + Oracle answers in-turn, UI auto-advance cycles the game, second cycle, same-seed determinism (fingerprint + 3-round replay), full classic game terminates (161 rounds, 3 wars, 2 Tower destructions) with all 44 cards conserved. Surfaced TW-R1 live (21/22 on first run). |
| 2 | `verify_round2.py` | **PASSED 12/12 (2026-07-07).** All three modes played to completion through the hooks under per-dispatch invariants (legal phase transitions, scores/rounds/log monotonic, war pile empty between dispatches, finished⇒winner, card census with exact Tower −2 accounting), effect coverage aggregated with exact accounting (wars, Towers, Magician/Empress/Hierophant discard moves, recycling), effect-log round stamping, hard-AI same-seed determinism (12 rounds move-for-move), reset preserving mode/difficulty. Surfaced TW-R6 live (86 mis-stamped entries) and TW-R8 (twice — the first fix left the opponent's effect executing post-finish). |
| 3 | (planned) | Exploit-hunter invariants: seeded episodes of random/heuristic action streams, invariants after every step (card conservation, score bounds, no stuck phase, no soft-lock, finished is terminal), full action coverage incl. refusal paths, same-seed episode replay byte-identical. |

## Findings registry (R1: 22/22 · R2: 12/12)

- **TW-R1 (critical) — FIXED & VERIFIED LIVE.** Every war round duplicated the
  two tied cards and inflated the war winner's score by +2: the war-resolution
  branches reset `warDepth` to 0 *before* the claim phase's
  `warDepth > 0 && winner` skip-check ran, so the normal claim re-awarded
  `player1Card`/`player2Card` (already claimed inside the war pile). The
  duplicated objects then recycled into decks as extra copies — first live
  observation: seed 20260707, round 4, both players played The Empress
  (identical decks make same-card ties routine, ~1 war/37 rounds observed),
  census showed `empress` ×4. Predicted by code inspection, confirmed live by
  the conservation probe, fixed by leaving `warDepth` for the skip-check to
  reset, pinned by `src/__tests__/integration/warConservation.test.ts`.
  Verified live: full 161-round game, every card id exactly twice throughout.
- **TW-R2 (major) — FIXED (probe-verified + pinned).** Endless mode skipped the
  total-exhaustion check, so a player with 0 deck + 0 discard made the reducer
  draw `undefined` as their card and push `undefined` into the winner's discard
  (silent corruption; later card effects would crash on it). Deterministic
  probe confirmed the undefined push. Fringe reachability in real play
  (in-war exhaustion checks catch most drains), but the state handling was
  plainly broken and inconsistent — cardlessness already ended endless games
  when it happened mid-war. Fix: the total-exhaustion check now runs in every
  mode, and (bonus) the previously SILENT exhaustion game-over now writes a
  "has no cards left" log entry in all modes. Pinned in
  `warConservation.test.ts`; endless-mode test updated for the new path.
- **TW-R3 (tooling/game fix) — DONE.** No seed seam existed: unseeded
  `Math.random()` in `shuffleArray` (all deck builds/recycles), three war
  tie-breakers, four card-effect discard picks, and the Oracle's flavor-line
  pick. Added `src/utils/seededRandom.ts` (mulberry32; unseeded boot stays
  random for players) and routed all nine game-logic call sites through it;
  `__RESET_GAME__(seed)` seeds it. Pinned by
  `src/__tests__/utils/seededRandom.test.ts`; verified live (deck fingerprints
  + 3-round replays identical across same-seed resets, twice).
- **TW-R4 (minor, OPEN — watch).** tarot-war's own
  `gameModes.test.tsx` › "logs an ENDLESS-tagged special entry" failed ONCE
  mid-session and never again (0 repros in ~50 subsequent runs: 30× isolated,
  10× file, 8× full suite; assertion detail lost). TW-R2's undefined-card
  corruption is the best crash-class candidate and is now fixed. Watch during
  Round 2, which plays endless mode to completion repeatedly through the real
  game.
- **TW-R6 (major, found in Round 2) — FIXED & VERIFIED LIVE.** Every log entry
  pushed during REVEAL/PRE_COMBAT/EFFECT_EXECUTE (Oracle flavor lines,
  Temperance balancing, all card-effect messages) was stamped with the
  PREVIOUS round from round 2 onward, because the reducer incremented
  `currentRound` only *after* effects executed. Player impact: GameBoard's
  "Magical Effects" panel filters `log.round === currentRound`, so card
  effects were INVISIBLE in the battle arena from round 2 on, and GameLog
  labeled them under the wrong round. Predicted from a code read, confirmed
  live (86 mis-stamped entries in one classic game). Fix: the round number is
  now stamped at the top of the round-resolution path; pinned by
  `src/__tests__/integration/logRoundStamps.test.ts`.
- **TW-R7 (design question, OPEN — report upstream).** The World's instant
  victory triggers on `deck.length + hand.length <= 7` and IGNORES the discard
  pile — the "comeback" can fire while the caster still owns 20+ cards that
  would recycle back. Needs a design decision (include discard, or rename the
  trigger); not changed unilaterally.
- **TW-R8 (major, found in Round 2) — FIXED & VERIFIED LIVE.** The World's
  instant victory set `gamePhase='finished'` mid-pipeline but the round KEPT
  RESOLVING: the opponent's card effect still executed (a post-finish Magician
  would move cards between players), the claim still awarded +2, and a tie
  would have rolled a full war — all after the game was over. Observed live
  twice: first as a post-victory claim log, then (after a first fix guarded
  only the end of the effect phase) as the opponent's Hanged Man effect firing
  post-finish. Fix: resolution stops the moment an effect finishes the game —
  the other card's effect is skipped and the interrupted round's cards return
  to their owners' discards (census intact). Pinned in
  `warConservation.test.ts`.
- **TW-R5 (minor, OPEN).** `ActiveEffect` ids use wall-clock uniqueness
  (`tower-${Date.now()}`, `sun-${Date.now()}` in `majorArcana.ts`) — two
  effects minted in the same millisecond collide, and ids are nondeterministic
  across same-seed runs (harmless today: nothing looks effects up by id, and
  the UGT projection omits them). Fold into any future effect-system cleanup.
- **Observation (design, not a bug):** in classic mode `score` is *cumulative
  cards claimed*, while the win comes from opponent total-exhaustion — so the
  classic winner can finish with the LOWER score (seen live: 178–179). Worth a
  Round-2 balance look at whether the GameSummary explains this to players.

- **TW-R4 update (Round 2):** no recurrence — Round 2 played endless mode to
  completion live plus dozens more suite runs; still 1 occurrence total.
  TW-R2/TW-R8 both removed crash-classes from the endless path. Stays open as
  a watch-item.

Baseline: tarot-war's own suite must stay green — 434 tests pre-integration,
**444 after the trial's pinning tests** (seededRandom ×6, warConservation ×3,
logRoundStamps ×1). Run `npx vitest run` in `../tarot-war`.

Action ids in `ugt.config.yaml` must stay in lockstep with the dispatch table in
`tarot-war/src/ugt-hooks.ts`.
