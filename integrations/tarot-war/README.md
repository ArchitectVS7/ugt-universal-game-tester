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
```

## Test ladder (test → fix upstream → re-test)

| Round | Script | Gate |
|---|---|---|
| 1 | `verify_round1.py` | **PASSED 22/22 (2026-07-07, twice back-to-back).** One full playable loop: seeded reset, info accessibility, setup pickers through real handlers, player turn + Oracle answers in-turn, UI auto-advance cycles the game, second cycle, same-seed determinism (fingerprint + 3-round replay), full classic game terminates (161 rounds, 3 wars, 2 Tower destructions) with all 44 cards conserved. Surfaced TW-R1 live (21/22 on first run). |
| 2 | (planned) | Multi-game economy-equivalent: all three modes (classic / survival / endless) played to completion through the hooks, war + card-effect coverage (Tower destruction, Magician/Empress/Hierophant discard moves observed and conserved), per-round invariants (scores monotonic, phase machine legal, log append-only), hard-AI pattern determinism. |
| 3 | (planned) | Exploit-hunter invariants: seeded episodes of random/heuristic action streams, invariants after every step (card conservation, score bounds, no stuck phase, no soft-lock, finished is terminal), full action coverage incl. refusal paths, same-seed episode replay byte-identical. |

## Findings registry (R1: 22/22)

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
- **TW-R5 (minor, OPEN).** `ActiveEffect` ids use wall-clock uniqueness
  (`tower-${Date.now()}`, `sun-${Date.now()}` in `majorArcana.ts`) — two
  effects minted in the same millisecond collide, and ids are nondeterministic
  across same-seed runs (harmless today: nothing looks effects up by id, and
  the UGT projection omits them). Fold into any future effect-system cleanup.
- **Observation (design, not a bug):** in classic mode `score` is *cumulative
  cards claimed*, while the win comes from opponent total-exhaustion — so the
  classic winner can finish with the LOWER score (seen live: 178–179). Worth a
  Round-2 balance look at whether the GameSummary explains this to players.

Baseline: tarot-war's own suite must stay green — 434 tests pre-integration,
**442 after the trial's pinning tests** (seededRandom ×6, warConservation ×2),
verified 3× consecutive. Run `npx vitest run` in `../tarot-war`.

Action ids in `ugt.config.yaml` must stay in lockstep with the dispatch table in
`tarot-war/src/ugt-hooks.ts`.
