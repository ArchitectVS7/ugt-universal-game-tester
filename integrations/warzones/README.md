# Warzones integration (real client, browser adapter)

**Status: FULL LADDER COMPLETE and green** — `R1 23/23 · R2 12/12 · R3 6/6`. This
README's core ladder narrative and findings table were already accurate as of the
2026-07-21 documentation-audit survey (warzones is the best-organized of the six
integrations) — what follows is a **moderate addendum**, not a rewrite: a naming-quirk
callout, the 2026-07-21 self-audit (L-001), and folding in the operational warnings that
previously lived only in `HANDOFF.md`.

- **Resume-here doorway (full current state):** [HANDOFF.md](HANDOFF.md)
- **Findings log (commit-traceable):** [RESULTS.md](RESULTS.md)
- No historical/superseded docs exist for this integration yet, so there is no
  `archive/` directory — all 8 tracked files here are current and none were moved by
  the 2026-07-21 audit.

Drives the **real** warzones Phaser 3 game (`../warzones/warzones-game`, sibling repo,
branch `main`) in a headless browser via `PlaywrightAdapter` and the UGT hooks installed
in the game at `src/ugt-hooks.ts` (`window.__GET_STATE__` / `__SEND_ACTION__` /
`__RESET_GAME__(seed)`). `verify_round10.py` additionally uses a `SeededWarzonesAdapter`
subclass layered on top of `PlaywrightAdapter`.

Do **not** use `examples/warzones/sim_bridge.py` — it wraps a Python re-implementation
of the game (`warzones-ml/sim`), the exact drift failure mode this project retired with
SpacerQuest's `sim_bridge.ts`. (Also removed 2026-07-06: `examples/warzones/` in this
repo and `warzones-ml/` in the warzones repo are both deleted — recoverable from git
history; tombstone note in `warzones/docs/AI-ML-Testing/Phase-3-Orchestration.md`.)

## Naming quirk — read this before looking for `verify_round3.py`

**There is no `verify_round3.py` in this integration.** R3 (the ExploitHunter /
robustness tier) lives in **`verify_round10.py`** — an artifact of an earlier
"ten-turn" naming scheme that stuck. If you go looking for the R3 script by the pattern
used in every other integration, you will not find it; `verify_round10.py` is it.

## Run

```bash
# 1. Start the real game (Vite dev server on :3000)
cd ../warzones/warzones-game && npm run dev

# 2. Verify the LISTEN PID on :3000 is YOUR vite (stale-server lesson):
lsof -nP -iTCP:3000 -sTCP:LISTEN

# 3. From the UGT repo root — the full re-run recipe, in order:
python3 integrations/warzones/verify_round1.py        # 23/23 — one full turn cycle
python3 integrations/warzones/verify_round2.py         # 12/12 — economy + combat + invariants; [seed] optional, default 20260706
python3 integrations/warzones/verify_round10.py        # 6/6  — R3 ExploitHunter (misnamed "round10"); [base_seed] optional, default 20260707

# 4. Regression artifact — no server/browser needed, run any time:
python3 integrations/warzones/determinism_selftest.py  # 6/6 synthetic vacuous-guard cases
```

Action ids in `ugt.config.yaml` must stay in lockstep with the switch in
`warzones-game/src/ugt-hooks.ts`.

## Test ladder (test -> fix upstream -> re-test)

| Round | Script | Gate |
|---|---|---|
| 1 | `verify_round1.py` | **PASSED 23/23 (2026-07-06).** One full turn cycle: player acts, all info accessible, bots act, cycle repeats. Probes record findings (determinism, trading dead end WZ-R2, combat run-destruction WZ-R1). |
| 2 | `verify_round2.py` | **PASSED 12/12 (2026-07-07).** Three clean consecutive turn cycles: a real buy AND sell through TradingScene's own handlers (credits/cargo/stock deltas == quoted prices), a mid-run combat the run survives (salvage credited exactly, hull damage persists, pirate removed), and per-action invariants (AP >= 0, fog monotonic, turnNumber only via end_turn, credits >= 0, cargo <= capacity, no stuck scene). Surfaced WZ-R8. |
| 3 | `verify_round10.py` | **PASSED 6/6 (2026-07-07).** Ten-turn cycles under UGT's real `ExploitHunter` tier — its first-ever browser-game outing: 3 seeded episodes x 400 steps with a scene-aware heuristic policy, 11 invariants checked after every step (AP >= 0, fog monotonic, turn only via end_turn, credits >= 0, cargo <= capacity, hull bounds, no bot resurrection, world constants stable, event log append-only, no stuck scene, no soft-lock), all 12 hook actions attempted, and a same-seed replay of episode 0 reproducing all 400 steps exactly. Surfaced WZ-R9. Trial ladder complete. |

## Findings registry (R1: 23/23 · R2: 12/12 · R3: 6/6 — ladder complete 2026-07-07)

9 findings total (WZ-R1..WZ-R9). 8 fixed and verified live upstream; 1 (WZ-R3) remains
open and is explicitly scoped out of the game, not a tester defect.

- **WZ-R1 (critical) — FIXED & VERIFIED LIVE.** Was: any pirate encounter destroyed the
  run. Three compounding bugs fixed: (a) `CombatScene.init` expected `{botId}` but
  GalaxyMapScene passed `{enemy}` — `data.botId.toString()` threw on undefined, killing
  the scene stack; (b) `exitToMap()` went to `BootScene` (`// TODO: Phase 7`), now
  `GalaxyMapScene {gameState}`; (c) player death showed an inline GAME OVER -> BootScene,
  now transitions to the real `DefeatScene`. Verified: fought a pirate, returned to the
  map, bot removed, salvage credited, hull damage persisted.
- **WZ-R2 (critical) — FIXED & VERIFIED LIVE.** Was: `TradingScene` never launched.
  Added a `#btn-trade` HUD button (+ `T` shortcut) enabled when the player's sector has
  a port -> `TradingScene {gameState, portSectorId}`; both TradingScene exits now return
  to the galaxy map instead of BootScene. Verified: docked at a port, TradingScene
  opened, exited, run intact.
- **WZ-R6 (major, found while fixing R1/R2) — FIXED.** Scene re-entry exposed two latent
  bugs: `GalaxyMapScene.shutdown()` was never wired (Phaser doesn't auto-call it — now
  subscribed to the `SHUTDOWN` event), and `DOMHUD` stacked duplicate button listeners on
  every scene entry (now idempotent `onclick` assignment + detach in `destroy()`).
  Without this, each combat/trade round-trip would multiply End-Turn clicks.
- **WZ-R3 (major, OPEN):** `ContractScene` never launched — scoped out of game v0.8,
  explicitly not a tester defect. Everything else (WZ-R1/R2/R4/R5/R6/R7/R8/R9) is fixed,
  verified live, and pinned in the game's own suite.
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
  `verify_round2.py` runs are now byte-identical (salvage 598, hull 50->44, credits
  5341 each cycle). Residual unseeded sites, all outside the run loop today:
  `dialogue-service.ts` (cosmetic line pick), `contracts.ts:391` (default param,
  callers can pass a roll), `legendary-module-system.ts` (no live caller).
- **WZ-R9 (major, found in Round 3) — FIXED & VERIFIED LIVE.** A successful flee
  never marked the combat resolved: `CombatScene.flee()` only scheduled
  `exitToMap` 3 wall-clock seconds later, so during that window ATTACK still
  worked and re-engaged an enemy the player had already escaped ("COMBAT
  AVOIDED" on screen, full combat resolution anyway) — a rules hole for humans
  and a wall-clock race for agents. Surfaced by Round 3's coverage gate: flee
  was unreachable at 30% sampling (combats resolve in 1–2 steps), and forcing
  coverage exposed the timing hazard. Fix: on flee success the scene now sets
  `combatResolved = true` with a `CombatOutcome.Fled` result (the enum existed,
  unused) before the delayed exit; `attack()` already guards on
  `combatResolved`. Verified live: flee exercised 5x in Round 3 and the
  same-seed 400-step replay stayed byte-identical with combat+flee in the
  trajectory.
- **WZ-R8 (critical, found in Round 2) — FIXED & VERIFIED LIVE.** The commodity
  registry was NEVER populated in the running game: no code in `src/` called
  `registerCommodity` (only tests did), and the `commodities.json` referenced by
  comments didn't exist. `TradingScene.displayCommodities()` iterates
  `getAllCommodities()` -> the commodities tab rendered **zero rows** for a real
  player; ports had prices/stock internally (`port-factory.ts` hardcodes bases)
  but the entire player-facing economy loop was unreachable. First player-driven
  trade attempt found it instantly. Fix upstream: new `src/core/data/commodities.json`
  (ids/bases in lockstep with `setupCommodities()`), `loadCommodities()` in
  `commodity.ts` mirroring `loadModules()`, called from `BootScene.create()`;
  pinned by `tests/core/entities/commodity-loading.test.ts`. Verified live: buy 1
  contraband at 280cr quoted = 280cr paid, stock −1; sell 2 fuel_ore at 108cr →
  +216cr, stack cleared.

Warzones' own unit suite passes post-fix: **2,414/2,414 green.**

## 2026-07-21 audit (L-001) — the gap vs. the pre-audit README

A separate self-audit (L-001) swept all three ladder scripts for the DDD/Pond
vacuous-check failure class (a check that can pass on empty/degenerate input and so
never actually tests anything). It found and fixed **one tester-side defect**: the R3
same-seed determinism check was vacuous on an empty trajectory — `same_len and
divergence is None` evaluates `True` for two empty trajectories, i.e. it would have
false-passed "identical" runs that never took a single step. Fixed by extracting a
`trajectories_match` predicate and pinning it with a new committed regression file,
**`determinism_selftest.py`** (6/6 synthetic cases, no game/browser needed to run it).

Live MET counts were **unchanged** by this audit — still 23/12/6 — because the real
same-seed replay runs used in R3 were never actually empty; the vacuous form was a
latent risk, not something that had produced a false pass in this game's history.

**Operational warning carried over from HANDOFF.md: do not simplify `trajectories_match`
back to the old inline boolean** (`len(a)==len(b) and next(...) is None`) — that is
exactly the vacuous form L-001 removed, and `determinism_selftest.py` exists to catch a
regression back to it.

## LLM playtest tier — not yet run

The **LLM balance-playtest tier** (`ugt playtest`) — the "is this a good game?" tier, as
opposed to the correctness/robustness tiers above — has **not been run against
warzones**. It is credit-gated and is the one remaining open tier for this integration.
