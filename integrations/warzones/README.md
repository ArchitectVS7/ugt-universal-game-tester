# Warzones integration (real client, browser adapter)

Drives the **real** warzones Phaser game (`../warzones/warzones-game`) in a headless
browser via `PlaywrightAdapter` and the UGT hooks installed in the game at
`src/ugt-hooks.ts` (`window.__GET_STATE__` / `__SEND_ACTION__` / `__RESET_GAME__(seed)`).

Do **not** use `examples/warzones/sim_bridge.py` — it wraps a Python re-implementation
of the game (`warzones-ml/sim`), the exact drift failure mode this project retired with
SpacerQuest's `sim_bridge.ts`.

## Run

```bash
# 1. Start the real game (Vite dev server on :3000)
cd ../warzones/warzones-game && npm run dev

# 2. Verify the LISTEN PID on :3000 is YOUR vite (stale-server lesson):
lsof -nP -iTCP:3000 -sTCP:LISTEN

# 3. From the UGT repo root:
python3 integrations/warzones/verify_round1.py
python3 integrations/warzones/verify_round2.py   # [seed] optional, default 20260706
```

## Test ladder (test → fix upstream → re-test)

| Round | Script | Gate |
|---|---|---|
| 1 | `verify_round1.py` | **PASSED 23/23 (2026-07-06).** One full turn cycle: player acts, all info accessible, bots act, cycle repeats. Probes record findings (determinism, trading dead end WZ-R2, combat run-destruction WZ-R1). |
| 2 | `verify_round2.py` | **PASSED 12/12 (2026-07-07).** Three clean consecutive turn cycles: a real buy AND sell through TradingScene's own handlers (credits/cargo/stock deltas == quoted prices), a mid-run combat the run survives (salvage credited exactly, hull damage persists, pirate removed), and per-action invariants (AP ≥ 0, fog monotonic, turnNumber only via end_turn, credits ≥ 0, cargo ≤ capacity, no stuck scene). Surfaced WZ-R8. |
| 3 | `verify_round10.py` (next) | Ten turns; exploit-hunter invariants (AP never negative, fog monotonic, no stuck scene). |

## Findings registry (Round 1: 2026-07-06 23/23; Round 2: 2026-07-07 12/12, seed 20260706)

- **WZ-R1 (critical) — FIXED & VERIFIED LIVE.** Was: any pirate encounter destroyed the
  run. Three compounding bugs fixed: (a) `CombatScene.init` expected `{botId}` but
  GalaxyMapScene passed `{enemy}` — `data.botId.toString()` threw on undefined, killing
  the scene stack; (b) `exitToMap()` went to `BootScene` (`// TODO: Phase 7`), now
  `GalaxyMapScene {gameState}`; (c) player death showed an inline GAME OVER → BootScene,
  now transitions to the real `DefeatScene`. Verified: fought a pirate, returned to the
  map, bot removed, salvage credited, hull damage persisted.
- **WZ-R2 (critical) — FIXED & VERIFIED LIVE.** Was: `TradingScene` never launched.
  Added a `#btn-trade` HUD button (+ `T` shortcut) enabled when the player's sector has
  a port → `TradingScene {gameState, portSectorId}`; both TradingScene exits now return
  to the galaxy map instead of BootScene. Verified: docked at a port, TradingScene
  opened, exited, run intact.
- **WZ-R6 (major, found while fixing R1/R2) — FIXED.** Scene re-entry exposed two latent
  bugs: `GalaxyMapScene.shutdown()` was never wired (Phaser doesn't auto-call it — now
  subscribed to the `SHUTDOWN` event), and `DOMHUD` stacked duplicate button listeners on
  every scene entry (now idempotent `onclick` assignment + detach in `destroy()`).
  Without this, each combat/trade round-trip would multiply End-Turn clicks.
- **WZ-R3 (major, open):** `ContractScene` never launched (known: scoped out of v0.8).
- **WZ-R4 — FIXED.** New games were seeded with `Date.now()` only; `launchNewGame`/
  `__FAST_RESET__` accept an optional fixed seed. Same-seed reproduction verified live.
- **WZ-R5 (minor) — FIXED & VERIFIED LIVE (pre-Round-3 cleanup).** The "Turn ended."
  summary was logged after `turnNumber++` and so stamped with the NEXT turn while the
  territory-income `TurnEnd` used the ending turn. Now logged before the increment;
  pinned by `tests/core/services/turn-end-stamp.test.ts`. Round 1's tolerant check
  passes without emitting the finding anymore.
- **WZ-R7 (minor) — FIXED & VERIFIED LIVE (pre-Round-3 cleanup).** Combat and bot
  randomness escaped the `SeededRandom` discipline in four places, making same-seed
  runs (and both gates) flaky: (a) `CombatScene.flee()` rolled `Math.random()`;
  (b) `CombatScene`'s `CombatSystem` was seeded from `Date.now()` — three same-seed
  Round-2 runs paid 488/878/533cr salvage for the same pirate; (c) `executeBotTurn`
  never passed an RNG to `selectBestAction`, so bot utility jitter and bot-vs-bot
  `CombatSystem`s were unseeded; (d) `getRandomPersonality()` rolled `Math.random()`
  at spawn, so same-seed galaxies got different bot personalities. Fix: per-encounter
  seeding (`pc:<seed>:<turn>:<botId>`) in `CombatScene.init`, flee draws from
  `CombatSystem.next()`, per-bot-turn RNG (`bot:<seed>:<turn>:<botId>`) in
  `executeBotTurn`, spawn RNG threaded into personalities. Pinned by
  `tests/core/combat/combat-rng-seam.test.ts`. Verified live: two back-to-back
  `verify_round2.py` runs are now byte-identical (salvage 598, hull 50→44, credits
  5341 each cycle). Residual unseeded sites, all outside the run loop today:
  `dialogue-service.ts` (cosmetic line pick), `contracts.ts:391` (default param,
  callers can pass a roll), `legendary-module-system.ts` (no live caller).
- **WZ-R8 (critical, found in Round 2) — FIXED & VERIFIED LIVE.** The commodity
  registry was NEVER populated in the running game: no code in `src/` called
  `registerCommodity` (only tests did), and the `commodities.json` referenced by
  comments didn't exist. `TradingScene.displayCommodities()` iterates
  `getAllCommodities()` → the commodities tab rendered **zero rows** for a real
  player; ports had prices/stock internally (`port-factory.ts` hardcodes bases)
  but the entire player-facing economy loop was unreachable. First player-driven
  trade attempt found it instantly. Fix upstream: new `src/core/data/commodities.json`
  (ids/bases in lockstep with `setupCommodities()`), `loadCommodities()` in
  `commodity.ts` mirroring `loadModules()`, called from `BootScene.create()`;
  pinned by `tests/core/entities/commodity-loading.test.ts`. Verified live: buy 1
  contraband at 280cr quoted = 280cr paid, stock −1; sell 2 fuel_ore at 108cr →
  +216cr, stack cleared.

Also removed (2026-07-06): the retired Python re-implementation. `examples/warzones/`
(UGT repo) and `warzones-ml/` (warzones repo) are deleted — recoverable from git
history; tombstone note in `warzones/docs/AI-ML-Testing/Phase-3-Orchestration.md`.
Warzones' own unit suite passes post-fix: 2,414/2,414.

Action ids in `ugt.config.yaml` must stay in lockstep with the switch in
`warzones-game/src/ugt-hooks.ts`.
